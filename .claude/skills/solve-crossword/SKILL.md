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
uv run python -m xsolver.parse_image parse \
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
   uv run python -m xsolver.parse_image reconstruct \
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
   uv run python -m xsolver.parse_image set-clues \
     --output-dir "$PUZZLE_DIR" --updates-json "$PUZZLE_DIR/clue_updates.json"
   ```
5. Render the grid and sanity-check against the image:
   ```bash
   uv run python -m xsolver.render --puzzle-dir "$PUZZLE_DIR"
   ```
   If the shape still looks wrong at this point — after `parse` (or `reconstruct`) has already passed `validate_grid` — it means either your clue-text transcription is wrong or the number-positions in the spec file are wrong. Re-read the image before proceeding.

### Step 3 — Initialise state if not already

```bash
test -f "$PUZZLE_DIR/state.json" || \
  uv run python -c "from xsolver.state import init_state; from pathlib import Path; init_state(Path('$PUZZLE_DIR'))"
```

### Step 4 — Initial solve wave (parallel subagents)

**Don't reason through all clues yourself** — that is what makes this step hang. Instead, dispatch `solve-hard-clue` subagents in parallel batches of 6–10. Every uncommitted clue gets a subagent; each subagent proposes 1–5 candidates via `state propose` and returns.

For each batch, send a single message with multiple `Task` tool calls (this is what makes them run concurrently — serial dispatch gives you no speedup). Dispatch prompt template for each subagent:

> Clue `<id>`: "<clue text>" (<enumeration>)
> Current pattern: `<from state.json>`
> Prior candidates for this clue (from `guesses.jsonl`): `<list or "none">`
>
> Propose 1–5 candidates. Call `uv run python -m xsolver.state propose --puzzle-dir "<abs path>" --clue <id> --answer "<ANSWER>" --confidence <high|medium|low> --reasoning "<one sentence>"` for each. Use `high` only if you're confident in BOTH wordplay and definition and the answer fits the pattern. Return a one-line summary of what you logged.

After every batch returns:

```bash
uv run python -m xsolver.state promote --puzzle-dir "$PUZZLE_DIR"
uv run python -m xsolver.commit wave --puzzle-dir "$PUZZLE_DIR"
```

`promote` picks the highest-confidence pattern-compatible candidate per clue and copies it into `state.json` attempts; `commit wave` then writes letters for every `high`-confidence attempt.

**Tip:** read the grouped candidates back with `state candidates` when you want to see what's logged for a clue:

```bash
uv run python -m xsolver.state candidates --puzzle-dir "$PUZZLE_DIR" --clue 6D
```

### Step 5 — Reassess wave

```bash
uv run python -m xsolver.reassess list --puzzle-dir "$PUZZLE_DIR"
```

For each stale clue returned, **first** re-run `state promote` — a candidate that was pattern-incompatible before may now fit. Then `commit wave`. Only if those two don't make progress do you dispatch fresh subagents for the stale clues (same template as Step 4, but pass the updated pattern and the full candidate list). Loop until both reassess is empty AND a commit wave produced zero new commits.

### Step 6 — Hard-clue phase

List remaining unsolved clues:

```bash
uv run python -m xsolver.render --puzzle-dir "$PUZZLE_DIR" --summary
```

For each unsolved clue, ordered by most-constrained-first (highest fraction of known letters in its current pattern), dispatch 1–3 subagents using the `solve-hard-clue` skill. Pass each subagent:

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
uv run python -m xsolver.render --puzzle-dir "$PUZZLE_DIR"
uv run python -m xsolver.render --puzzle-dir "$PUZZLE_DIR" --summary
```

Tell the user: `X / Y` clues solved, any unsolved ones listed with best-guess attempts, and the path to `$PUZZLE_DIR/history.jsonl` for a full audit trail.

## Stuck on a clue with an impossible pattern?

If every cross-pattern lookup for a remaining clue returns nothing — e.g. pattern `?D?C?C?R?S` matches no English (5,5) phrase — then one of its committed crossings is probably a **near-miss** of the setter's intended answer. Same letter count, fits all of its OTHER crossings, but a letter or two off from the real answer.

The human move: retract the shakiest-wordplay crossing, propose an alternative that fits the same crossings but has a different letter in the blocking position, then re-run promote + commit.

```bash
# Retract a committed answer (clears cells not owned by another committed clue)
uv run python -m xsolver.state retract --puzzle-dir "$PUZZLE_DIR" --clue 16A \
  --reasoning "Locks 13D pattern into unsolvable state"

# Propose the corrected answer
uv run python -m xsolver.state propose --puzzle-dir "$PUZZLE_DIR" --clue 16A \
  --answer "ROE DEER" --confidence high --reasoning "..."

# Now the blocked clue may resolve
uv run python -m xsolver.state propose --puzzle-dir "$PUZZLE_DIR" --clue 13D \
  --answer "MERCY CORPS" --confidence high --reasoning "..."

uv run python -m xsolver.state promote --puzzle-dir "$PUZZLE_DIR"
uv run python -m xsolver.commit wave --puzzle-dir "$PUZZLE_DIR"
```

Rank crossings by wordplay strength when picking what to retract: hidden-word solves and clean anagrams are near-certain; definition-only guesses with hand-waved wordplay are the usual culprits. Don't retract `high`-wordplay solves without strong evidence.

**After retract-and-reassess, re-verify wordplay — don't just pattern-match.** Once the previously-impossible pattern opens up, several candidates will fit. Pattern-fit alone is what got you into this mess the first time. For each candidate that fits the new pattern, ask: does the wordplay decompose cleanly (charade, anagram, homophone, hidden, reversal)? Does the definition directly match the surface reading? Prefer the candidate where both parse without hand-waving. Example from a real solve: both `MERCY CORPS` and `PEACE CORPS` fit `?E?C?C?R?S`, but only PEACE CORPS has a clean charade (PE "training" + ACE "expert" + CORPS "non-combatant volunteers") — MERCY CORPS fits letters but doesn't decompose.

## Observability

To watch progress in a separate terminal while a solve is running:

```bash
uv run python -m xsolver.watch --puzzle-dir "$PUZZLE_DIR"
```

Re-renders the grid + summary when `state.json` changes, and streams every new event from `history.jsonl` (`attempt`, `promoted`, `commit`, `retract`, phase boundaries). Ctrl-C to stop. For raw propose events, `tail -f "$PUZZLE_DIR/guesses.jsonl"` gives the firehose.

## Safety caps

- Max 25 wave iterations. If you hit it, abort and report.
- Max 8 attempts per clue. If any clue has 8 attempts, stop re-solving it.
- Two consecutive no-progress iterations (no commits AND no reassess unlocks) → advance to Phase 4.

## When to stop and ask the user

- Image parse produced nonsense (wrong grid shape, unreadable clues, ambiguous cell count). Don't fabricate clue text.
- Two `high`s conflict repeatedly on the same clue after multiple reassesses — the system is genuinely confused; hand back to the user for a hint.
