---
name: solve-crossword
description: Use when the user asks to solve a cryptic crossword from an image, or runs /solve on a crossword file. Triggers include "solve this crossword", "solve xword.jpg", British cryptic puzzles from The Times / Guardian / Independent.
---

# Solve Crossword

## Overview

Solve a British cryptic crossword from a JPG. You orchestrate a wave-based loop:

1. Parse image → puzzle.json (Python).
2. Audit clue text against the image (you read the image).
3. Initial solve wave: **dispatch subagents in parallel** — one per clue — that write candidates to `guesses.jsonl`. Do NOT reason through 28 clues yourself in one turn; that's the main cause of 20-minute hangs.
4. Promote + commit: `state promote` picks the best compatible candidate per clue; `commit wave` writes letters; conflicts auto-retract.
5. Reassess wave: re-dispatch subagents for clues whose letter pattern changed — they re-filter their existing guesses first before generating new ones.
6. Hard-clue phase: dispatch `solve-hard-clue` subagents for clues still stuck after reassess plateaus.
7. Report.

## Invariants (non-negotiable)

- **Externalize every candidate.** Each clue gets 1–5 candidates written to `guesses.jsonl` via `state propose`, even low-confidence ones. The main agent must NOT hold a mental shortlist — if a later pattern change makes a rejected candidate viable, `promote_candidates` re-checks all logged guesses, but only the logged ones.
- **Freshness:** before re-solving any clue, re-read `state.json` for its current pattern. Never cache patterns across iterations.
- **Mutations go through Python:** `state propose` (lock-free, parallel-safe), `state promote` (takes the lock), `commit wave`, `reassess list`. Never edit `state.json`, `history.jsonl`, or `guesses.jsonl` directly.
- **Confidence discipline:** `high` = "I'm confident in both wordplay AND definition, and candidate is a real word that fits enumeration"; `medium` = "plausible but unsure"; `low` = "guess". Only `high` gets committed to cells by `commit wave`. `medium`/`low` candidates sit in `guesses.jsonl` waiting to be promoted if patterns resolve them to `high`.
- **No speculative highs:** it's better to leave a clue uncommitted than to commit a wrong `high` — that creates cascading conflicts.

## Step-by-step

### Step 0 — Set up the working directory

Given an image at `<image>`:

```bash
PUZZLE_DIR="$(dirname <image>)/$(basename <image> .jpg)"
mkdir -p "$PUZZLE_DIR"
```

If `$PUZZLE_DIR/state.json` already exists and the user did NOT pass `--reset`, skip to Step 3 — the run is being resumed.

### Step 1 — Parse the image

```bash
uv run xsolver parse_image parse \
  --image <image> --output-dir "$PUZZLE_DIR" \
  --rows <N> --cols <N> --title "<title>"
```

If the user didn't tell you the grid size, read the image yourself and count. Most Times cryptics are 15×15.

**The parser validates the grid (180° symmetry + no sub-3-letter runs) before writing.** If it exits non-zero with a `GridValidationError`, the photo likely has perspective distortion or the auto-detected bbox was off. **Do not retry the same command** — skip to Step 1b.

### Step 1b — Fallback: reconstruct the grid from clue-start positions

When `parse` fails, read the image yourself and build a spec file. Each clue-start cell shows its number in the top-left; record `(row, col)` 0-indexed for each.

1. Write `$PUZZLE_DIR/clue_specs.json` as a list like:
   ```json
   [
     {"number": 1, "direction": "across", "length": 13, "row": 0, "col": 0,
      "text": "Board deal", "enumeration": [13]},
     {"number": 1, "direction": "down", "length": 14, "row": 0, "col": 0,
      "text": "On which a Bow Street Runner might be laid?",
      "enumeration": [6, 3, 5]},
     ...
   ]
   ```
   (`length` is the total letter count = sum of enumeration.)
2. Reconstruct:
   ```bash
   uv run xsolver parse_image reconstruct \
     --output-dir "$PUZZLE_DIR" --rows <N> --cols <N> \
     --title "<title>" --specs-json "$PUZZLE_DIR/clue_specs.json"
   ```
   This runs the same `validate_grid` checks and errors out if the spec is internally inconsistent (e.g. a clue's position conflicts with another's extent).
3. If reconstruction succeeded you can skip Step 2's `set-clues` call — `reconstruct` already populated text/enumeration from the spec.

### Step 2 — Audit the clue text (you read the image)

1. Read the original image (via the Read tool) AND `$PUZZLE_DIR/clues.png`.
2. Transcribe the clue list into a mapping: `{clue_id: {"text": "...", "enumeration": [...]}}`. Each clue's text ends with an enumeration in parentheses, e.g. `(6,3,5)` → `[6,3,5]`.
3. Write the mapping to `$PUZZLE_DIR/clue_updates.json`.
4. Apply it:
   ```bash
   uv run xsolver parse_image set-clues \
     --output-dir "$PUZZLE_DIR" --updates-json "$PUZZLE_DIR/clue_updates.json"
   ```
5. Render the grid and sanity-check against the image:
   ```bash
   uv run xsolver render --puzzle-dir "$PUZZLE_DIR"
   ```
   If the shape still looks wrong at this point — after `parse` (or `reconstruct`) has already passed `validate_grid` — it means either your clue-text transcription is wrong or the number-positions in the spec file are wrong. Re-read the image before proceeding.

### Step 3 — Initialise state if not already

```bash
test -f "$PUZZLE_DIR/state.json" || uv run xsolver state init --puzzle-dir "$PUZZLE_DIR"
```

### Step 4 — Initial solve wave (parallel subagents)

**Don't reason through all clues yourself** — that is what makes this step hang. Instead, dispatch subagents in parallel. A human solver has two distinct modes and you should too: a one-shot **seed scan** across all clues, followed by iterative **neighborhood expansion** from what landed.

### Wave 0 — Seed scan (one parallel burst, ALL clues)

Dispatch one lightweight subagent per uncommitted clue (chunk into message-size groups of ~10–15 parallel `Task` calls if needed). Prompt each with a different instruction than later waves:

> Clue `<id>`: "<text>" (<enumeration>). Pattern: `<???>`.
> **Quick gimme check.** If this clue is solvable in under a minute with no helper calls — hidden word, textbook anagram with obvious fodder, a clear double definition, or a short answer where the definition pins it down — propose the answer at `high`/`medium`. If it's not obvious, propose nothing and return "skip". Don't grind: this is the fast pass.

Goal: 8–12 seeds committed from this wave. These will anchor the grid.

### Waves 1+ — Neighborhood expansion (batches of 4–5)

Now iterate. Each wave:

1. Pick 4–5 unsolved clues, prioritized by **spatial proximity to recent commits** — clues whose pattern is most filled-in right now. Get the list mechanically:
   ```bash
   uv run xsolver render --puzzle-dir "$PUZZLE_DIR" --next-batch 5
   ```
   This returns JSON of the 5 clues with the highest `% of pattern letters already known`, ties broken by shorter clue first. Treat its output as the batch; no manual picking.
2. Dispatch in parallel (single message, multiple `Task` calls). Use the full `solve-hard-clue` prompt — these get the helper toolkit.
3. After the batch returns:
   ```bash
   uv run xsolver state promote --puzzle-dir "$PUZZLE_DIR"
   uv run xsolver commit wave --puzzle-dir "$PUZZLE_DIR"
   uv run xsolver reassess impossible --puzzle-dir "$PUZZLE_DIR"   # auto-detect near-miss commits
   uv run xsolver render --puzzle-dir "$PUZZLE_DIR" --summary
   ```
   If `reassess impossible` returned any single-word clues, go to the **Stuck on a clue with an impossible pattern** section below before the next wave — a committed crossing is a near-miss and needs retracting.
4. Exit the loop when two consecutive waves commit zero new clues AND `reassess impossible` is empty.

**Why small batches for waves 1+?** A batch is all-or-nothing — the dispatcher waits for every subagent to return before running `promote` + `commit`, so letters revealed by the fast-finishing agents in a batch are NOT visible to the slow ones in the SAME batch. Small batches let slow subagents in wave N+1 see the letters fast ones landed in wave N. Don't go below 3 — the round-trip overhead stops being worth it.

**Why spatial locality beats global constrainedness?** Humans follow letter unlocks visually. If you just committed three answers in the top-left quadrant, the high-leverage next move is more top-left clues (which just got new letters) — not some random globally-constrained clue in the bottom-right whose crossings haven't changed since the last wave.

For each batch, send a single message with multiple `Task` tool calls (this is what makes them run concurrently — serial dispatch gives you no speedup). Dispatch prompt template for each subagent:

> Clue `<id>`: "<clue text>" (<enumeration>)
> Current pattern: `<from state.json>`
> Definition category (if obvious from the clue): `<e.g. "famous writer", "European river", "exclamation", "fish">`
> Prior candidates for this clue (from `guesses.jsonl`): `<list or "none">`
>
> Propose 1–5 candidates. Call `uv run xsolver state propose --puzzle-dir "<abs path>" --clue <id> --answer "<ANSWER>" --confidence <high|medium|low> --reasoning "<one sentence>"` for each. Use `high` only if you're confident in BOTH wordplay and definition and the answer fits the pattern. Return a one-line summary of what you logged.

**Prime the category.** If the clue has a narrow-category definition (a noun/adjective at start or end that names a class of things), pass it explicitly in the `Definition category` line. Short answers (≤5 letters) or tight patterns (≤5 unknowns) benefit enormously — the subagent can enumerate `match_pattern` hits filtered by category instead of grinding wordplay. Example: 12A "Writer, turning 50, led up the garden path" (4) → `Definition category: famous writer` → subagent goes `match_pattern("?A?L")` + filter writers → `DAHL` → wordplay parses trivially.

After every batch returns:

```bash
uv run xsolver state promote --puzzle-dir "$PUZZLE_DIR"
uv run xsolver commit wave --puzzle-dir "$PUZZLE_DIR"
```

`promote` picks the highest-confidence pattern-compatible candidate per clue and copies it into `state.json` attempts; `commit wave` then writes letters for every `high`-confidence attempt.

**Tip:** read the grouped candidates back with `state candidates` when you want to see what's logged for a clue:

```bash
uv run xsolver state candidates --puzzle-dir "$PUZZLE_DIR" --clue 6D
```

### Step 5 — Reassess wave

```bash
uv run xsolver reassess list --puzzle-dir "$PUZZLE_DIR"
```

For each stale clue returned, **first** re-run `state promote` — a candidate that was pattern-incompatible before may now fit. Then `commit wave`. Only if those two don't make progress do you dispatch fresh subagents for the stale clues (same template as Step 4, but pass the updated pattern and the full candidate list). Loop until both reassess is empty AND a commit wave produced zero new commits.

### Step 6 — Hard-clue phase

List remaining unsolved clues:

```bash
uv run xsolver render --puzzle-dir "$PUZZLE_DIR" --summary
```

For each unsolved clue, ordered by most-constrained-first (highest fraction of known letters in its current pattern), dispatch **2–4** subagents in parallel using the `solve-hard-clue` skill (smaller than Step 4 batches because hard clues benefit more from early checkpoints — a single unlock often frees multiple others). Pass each subagent:

- Clue id, text, enumeration.
- Current letter pattern (freshly read from `state.json` at dispatch time).
- The current `state candidates --clue <id>` output, so they don't re-propose duplicates.
- The absolute path to `$PUZZLE_DIR` so the subagent can call helpers and run `state propose`.

Subagents write candidates via `state propose` exactly like Step 4. After each batch returns, run `state promote` → `commit wave` → `reassess list`, then dispatch the next batch with refreshed state.

**Exit the hard-clue phase when:**
- The hard set is empty, OR
- A full batch produces zero new high-confidence commits AND reassess unlocks nothing new — i.e. every remaining clue has either no attempt or only `low` attempts that don't fit committed letters.

No Hail Mary: don't keep dispatching subagents once the phase plateaus.

### Step 7 — Report

```bash
uv run xsolver render --puzzle-dir "$PUZZLE_DIR"
uv run xsolver render --puzzle-dir "$PUZZLE_DIR" --summary
```

Tell the user: `X / Y` clues solved, any unsolved ones listed with best-guess attempts, and the path to `$PUZZLE_DIR/history.jsonl` for a full audit trail.

## Stuck on a clue with an impossible pattern?

**Detect mechanically — don't wait for a user nudge.** After every commit wave, run:

```bash
uv run xsolver reassess impossible --puzzle-dir "$PUZZLE_DIR"
```

This returns every unsolved clue whose current pattern admits NO dictionary word, along with the committed crossings that contribute each letter. If the `impossible` list is non-empty, one of those crossings is almost certainly wrong — a **near-miss** of the setter's intended answer (same letter count, fits all its OTHER crossings, but a letter or two off).

Multi-word phrases land in `multi_word_unchecked` — those can't be checked by a single `match_pattern` call, so inspect them manually when the single-word `impossible` list is empty but you're still stuck.

The human move: retract the shakiest-wordplay crossing, propose an alternative that fits the same crossings but has a different letter in the blocking position, then re-run promote + commit.

```bash
# Retract a committed answer (clears cells not owned by another committed clue)
uv run xsolver state retract --puzzle-dir "$PUZZLE_DIR" --clue 16A \
  --reasoning "Locks 13D pattern into unsolvable state"

# Propose the corrected answer
uv run xsolver state propose --puzzle-dir "$PUZZLE_DIR" --clue 16A \
  --answer "ROE DEER" --confidence high --reasoning "..."

# Now the blocked clue may resolve
uv run xsolver state propose --puzzle-dir "$PUZZLE_DIR" --clue 13D \
  --answer "MERCY CORPS" --confidence high --reasoning "..."

uv run xsolver state promote --puzzle-dir "$PUZZLE_DIR"
uv run xsolver commit wave --puzzle-dir "$PUZZLE_DIR"
```

Rank crossings by wordplay strength when picking what to retract: hidden-word solves and clean anagrams are near-certain; definition-only guesses with hand-waved wordplay are the usual culprits. Don't retract `high`-wordplay solves without strong evidence.

**After retract-and-reassess, re-verify wordplay — don't just pattern-match.** Once the previously-impossible pattern opens up, several candidates will fit. Pattern-fit alone is what got you into this mess the first time. For each candidate that fits the new pattern, ask: does the wordplay decompose cleanly (charade, anagram, homophone, hidden, reversal)? Does the definition directly match the surface reading? Prefer the candidate where both parse without hand-waving. Example from a real solve: both `MERCY CORPS` and `PEACE CORPS` fit `?E?C?C?R?S`, but only PEACE CORPS has a clean charade (PE "training" + ACE "expert" + CORPS "non-combatant volunteers") — MERCY CORPS fits letters but doesn't decompose.

## Observability

To watch progress in a separate terminal while a solve is running:

```bash
uv run xsolver watch --puzzle-dir "$PUZZLE_DIR"
```

Re-renders the grid + summary when `state.json` changes, and streams every new event from `history.jsonl` (`attempt`, `promoted`, `commit`, `retract`, phase boundaries). Ctrl-C to stop. For raw propose events, `tail -f "$PUZZLE_DIR/guesses.jsonl"` gives the firehose.

## Safety caps

- Max 25 wave iterations. If you hit it, abort and report.
- Max 8 attempts per clue. If any clue has 8 attempts, stop re-solving it.
- Two consecutive no-progress iterations (no commits AND no reassess unlocks) → advance to Phase 4.

## When to stop and ask the user

- Image parse produced nonsense (wrong grid shape, unreadable clues, ambiguous cell count). Don't fabricate clue text.
- Two `high`s conflict repeatedly on the same clue after multiple reassesses — the system is genuinely confused; hand back to the user for a hint.
