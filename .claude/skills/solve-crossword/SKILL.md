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
- **Punctuation is load-bearing.** Question marks, quotation marks, dashes, exclamation marks, and apostrophes in clues are never decorative — they are placed deliberately by the setter and frequently flip which span is the definition versus the wordplay. **A `?` in a cryptic clue is NEVER a literal question** — it always flags definition-by-association, whimsical/oblique definition, or a category-not-instance pointer. Examples: `King John?` (7) is not a literal king named John but the Shakespeare history play (HISTORY); `Jesus?` = Jesus College = COLLEGE; `crude oil source?` = NORTH SEA / MARSH GAS, with the `?` meaning "any source, broadly construed." When you see `?`, expect the definition span to be a category, role, or associative link rather than a literal synonym. Em-dashes often isolate the wordplay chunk from the definition. Exclamation marks can mark an `&lit` or flag an exclamation synonym (`Jesus!` = GEE). Before locking in a definition, re-read the clue with the punctuation respected — if the obvious "definition" span is adjacent to a `?` or tucked between dashes, suspect the real definition lies elsewhere.
- **Never propose purely on pattern-fit.** Every candidate you write to `guesses.jsonl` — at any tier, `high` `medium` or `low` — must have a stateable semantic link between the clue's definition and the answer. Pattern-fit alone is not evidence; `match_pattern` returns words whose letters fit, not words the clue means. If you can't say in one sentence why the def points to this answer, don't propose it. Name the def's category in plain English first and only propose candidates whose meaning lands in that category. When no category member fits the pattern, that's a signal to re-slice the def span (see Clue-parsing heuristics below) or that a *committed crossing* is wrong — it is **never** the signal to propose a pattern-fit with a shrug def. This is the single rule that most frequently gets violated under auto-mode pressure; the cost is 20-minute wrong-branch cascades.
- **Proper-noun answers escape the wordlist.** UKACD excludes most nationalities, places, named works, people, and brands. A `reassess impossible` hit is a *hypothesis*, not a verdict: if the clue's def could plausibly be a proper-noun answer, brainstorm candidates semantically **before** retracting any crossing. The reassess output now splits these into `likely_proper_noun` vs `impossible` — treat the proper-noun list as "consider a non-dictionary answer" not "retract immediately."

## Clue-parsing heuristics

When you're stuck on a clue, work through these before committing to a pattern-fit or declaring a crossing wrong. They're domain-general and catch most of the stuck-clue failure modes:

- **The definition is a SPAN you choose, not a fixed phrase.** The setter puts the def as one contiguous span somewhere in the clue; when the obvious def yields no candidates at the right length, re-slice. A noun phrase can split: "drug from South America" could be def-span `drug` (wordplay = the rest) or def-span `from South America` (wordplay = `drug...handles...`). Move the word boundary and re-try before declaring the clue impossible.
- **Test both grammar readings of every content word.** Many cryptic setters exploit noun↔verb ambiguity: `houses` can be "dwellings" OR "contains"; `post` can be "mail" OR "station" OR "job"; `tree` can be "oak/fir/elm" OR "genealogy"; `party` can be "bash" OR "side"; `saw` can be "tool" OR "perceived" OR "adage". If the obvious reading stalls, flip the part of speech and re-parse. Compound-noun reads ("tree houses" = structures in trees) are especially tempting and especially wrong; try `tree`(noun) + `houses`(verb, container) as a default alternative.
- **Re-expand common words to longer synonyms when the letter count doesn't work.** If `post` (4) minus an opening letter gives 3 letters and you need 6, try `post` = STATION, POSITION, LETTER, SENTINEL, JOB. Same pattern for `car` → VEHICLE/MOTOR/AUTO, `drink` → BEVERAGE/TIPPLE/LIQUOR, `tree` → specific species letter-count-dependent. Short synonyms are ambushes; longer synonyms fit when they don't.
- **"Perhaps" / "maybe" / "say" / "kind of" / "sort of" / trailing "?" flag definition-by-example or oblique definition.** When you see one, don't expect the def span to be a literal synonym of the answer — it's pointing to the category or an associative link. A flirtation is not literally a pickup attempt, it's "an attempt to pick up *perhaps*." A trailing `?` on the whole clue often means the entire thing is cryptic-def or semi-&lit. Read the flagged span loosely.
- **On retract cascades, walk back to the weakest-def commit in the chain, not the newest.** When an `impossible` fires and you realize a committed crossing is wrong, don't assume it's the most recently committed one. Walk the chain of commits whose letters contribute to the stuck clue's pattern and rank each by def-strength (not wordplay-strength — wordplay-strength is already sorted for you in `committed_crossings`). The real culprit is often an earlier commit whose def was always a bit hand-wavy but seemed OK in isolation.
- **Try past-tense / participle pivots before retracting.** When a committed answer has partial wordplay and is blocking a stuck clue, often the setter's intended answer is a one-letter inflection of yours: CARICATURES vs CARICATURED, RUNNING vs RUNNERS, PEPPERED vs PEPPERS. The def usually still maps to either form, but the trailing letter changes the crossing pattern entirely. Always try the past-tense/participle/plural variant before assuming the whole answer is wrong.
- **Pre-mine the clue surface for proper-noun fragments before parsing wordplay.** Before grinding wordplay, scan the clue for embedded famous-name fragments: presidents (BUSH(es), TRUMP, LINCOLN), sergeants (PEPPER), explorers (DORA, COOK, SCOTT), poets, physicists, biblical figures, Shakespeare plays. Setters love to use these as cryptic units (PEPPERCORN RENT = SGT PEPPER + CORN; GOOSEBERRY BUSHES = unwanted-party + the Bushes; PAULI = PAUL I). If a clue mentions "presidents" or "sergeant" or "explorer," check whether the answer uses a specific named one before treating those words as generic categories.
- **Slang as definition is common in Times cryptics.** "On grass" = informer (STOOL PIGEON); "Cockney safe" = PETER; "Bob" = shilling or any nickname-derived unit. When a literal reading of the def yields nothing, try British/cockney/underworld/criminal slang for the same span.

## Step-by-step

### Step 0 — Set up the working directory

**Preferred input layout (faster path — ask the user to use this if they haven't):**

```
crosswords/<puzzle_name>/
  grid.jpg     # tight crop of just the grid — no surrounding text or page margins
  clues.jpg    # OR clues.txt / clues.rtf — separate from the grid
```

When the user has set up the folder this way, `<image>` in the rest of this skill refers to `grid.jpg`. Skip the bbox-detection failure mode entirely (Step 1b becomes rare), and read clue text directly from `clues.jpg` or `clues.txt` in Step 2. This convention removes the two slowest/flakiest parts of a fresh solve and is worth a one-line nudge if the user dropped a single full-page photo: "Want me to wait while you crop the grid out separately? It'll save a few minutes."

**Fallback layout:** if the user provides a single image at `<image>`:

```bash
PUZZLE_DIR="$(dirname <image>)/$(basename <image> .jpg)"
mkdir -p "$PUZZLE_DIR"
```

If `$PUZZLE_DIR/state.json` already exists and the user did NOT pass `--reset`, skip to Step 3 — the run is being resumed. If the user DID pass `--reset`, run `uv run xsolver state reset --puzzle-dir "$PUZZLE_DIR" --init` to wipe the prior solve artefacts (state/guesses/history/lock) while preserving `puzzle.json` and `clues.png` — this avoids re-parsing the image and re-auditing the clue text.

**Reading photos at full resolution.** The Read tool downsamples large images, which can render newspaper-grain clue text unreadable (and once you've seen the downsampled view, it's tempting to tell the user "the image is blurry" when it isn't). When clue text or grid numbers look fuzzy, do NOT just re-Read the same file — crop sections at full resolution and read each crop separately:

```bash
uv run xsolver image size --in <path>                                      # check dimensions
uv run xsolver image crop --in <path> --bbox x0,y0,x1,y1 --out /tmp/section.jpg
```

Then `Read /tmp/section.jpg`. A 4000×3000 photo cropped to a 1500×2000 region of clues reads at full sharpness. Apply this whenever you'd otherwise complain about resolution — for grid number-counting, clue text transcription, or verifying black-square positions in Step 1b.

### Step 1 — Parse the image

```bash
uv run xsolver parse_image parse \
  --image <image> --output-dir "$PUZZLE_DIR" \
  --rows <N> --cols <N> --title "<title>"
```

If the user didn't tell you the grid size, read the image yourself and count. Most Times cryptics are 15×15.

**The parser validates the grid (180° symmetry + no sub-3-letter runs) before writing.** If it exits non-zero with a `GridValidationError`, the photo likely has perspective distortion or the auto-detected bbox was off. **Do not retry the same command.** Before falling back to Step 1b (which is slow and prone to subagent hallucination of the black-square map), **ask the user for a tighter crop** — a JPG containing just the grid, no surrounding clue text or page margins. A clean grid-only image often parses on the first try; the previous failure was usually bbox detection getting confused by adjacent print. Only proceed to Step 1b if the user can't provide a better crop or the cropped image still fails.

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

**Subagent type and model tiering.** Every `Task` dispatch uses `subagent_type: "solve-hard-clue"` (the agent defined in `.claude/agents/solve-hard-clue.md`). Its frontmatter sets `model: opus` as default, which is correct for the hard-clue phase. For the faster phases, **override the model explicitly** via the Task `model` param:

| Phase | `subagent_type` | `model` (Task param) | Why |
|---|---|---|---|
| Wave 0 seed scan | `"solve-hard-clue"` | `"sonnet"` (override) | Gimme-check quality; Sonnet is ~3× faster and the reasoning depth is sufficient for hidden-words, textbook anagrams, double defs. |
| Waves 1+ expansion | `"solve-hard-clue"` | `"sonnet"` (override) | Deep enough for wordplay decomposition, fast enough to keep batches moving. |
| Hard-clue phase | `"solve-hard-clue"` | omit (use frontmatter default = `opus`) | Deep reasoning on genuinely stuck clues. Run `/effort high` in the orchestrator before dispatching this phase. |

Don't pin a specific Sonnet version — `"sonnet"` resolves to the current default, which the harness keeps up-to-date. The `solve-hard-clue` agent reads the dispatcher's prompt to infer which mode it's in and adjusts its grind-time accordingly.

### Wave 0 — Seed scan (one parallel burst, ALL clues)

Dispatch one lightweight subagent per uncommitted clue (chunk into message-size groups of ~10–15 parallel `Task` calls if needed). **Every Task call: `subagent_type: "solve-hard-clue"`, `model: "sonnet"`** (overriding the agent's Opus default). Prompt each with a different instruction than later waves:

> Clue `<id>`: "<text>" (<enumeration>). Pattern: `<???>`.
> **Quick gimme check.** If this clue is solvable in under a minute with no helper calls — hidden word, textbook anagram with obvious fodder, a clear double definition, or a short answer where the definition pins it down — propose the answer at `high`/`medium`. If it's not obvious, propose nothing and return "skip". Don't grind: this is the fast pass.

Goal: 8–12 seeds committed from this wave. These will anchor the grid.

### Waves 1+ — Neighborhood expansion (non-overlapping batches)

Now iterate. Each wave:

1. Get the batch mechanically — `next-batch` now returns a non-overlapping subset of unsolved clues (clues whose cells don't intersect each other), filtered to those with ≥1 letter already revealed, prioritized by `known_frac`:
   ```bash
   uv run xsolver render --puzzle-dir "$PUZZLE_DIR" --next-batch 30
   ```
   Pass a generous `n` (e.g. 30) — the picker only returns as many clues as the grid topology supports without overlap, so it self-caps. Late-game the batch shrinks naturally; early-mid solve you might get 6–10. Treat its output as the batch; no manual picking.
2. Dispatch in parallel (single message, multiple `Task` calls with **`subagent_type: "solve-hard-clue"`, `model: "sonnet"`**). The agent's built-in prompt gives it the helper toolkit; just pass the per-clue context in your Task prompt.
3. After the batch returns:
   ```bash
   uv run xsolver state promote --puzzle-dir "$PUZZLE_DIR"
   uv run xsolver commit wave --puzzle-dir "$PUZZLE_DIR"
   uv run xsolver reassess impossible --puzzle-dir "$PUZZLE_DIR"   # auto-detect near-miss commits
   uv run xsolver render --puzzle-dir "$PUZZLE_DIR" --summary
   ```
   If `reassess impossible` returned any single-word clues, go to the **Stuck on a clue with an impossible pattern** section below before the next wave — a committed crossing is a near-miss and needs retracting.
4. Exit the loop when two consecutive waves commit zero new clues AND `reassess impossible` is empty.

**Why non-overlapping batches?** A batch is all-or-nothing — the dispatcher waits for every subagent to return before `promote` + `commit`, so letters revealed by fast-finishing agents are NOT visible to slow agents in the SAME batch. The fix used to be "small batch (4–5) so slow agents in wave N+1 see letters fast ones landed in wave N." But that artificially capped parallelism even when it was safe. The new picker keeps the same guarantee structurally: agents in one batch can't make each other's patterns stale, because their cells don't intersect. So batch size is set by the grid, not a magic number — pack in as many independent clues as topology allows. The ≥1-letter filter avoids the seed-scan-like regime where unconstrained mid-solve dispatches grind and produce toxic mediums.

**Why spatial locality beats global constrainedness?** Humans follow letter unlocks visually. If you just committed three answers in the top-left quadrant, the high-leverage next move is more top-left clues (which just got new letters) — not some random globally-constrained clue in the bottom-right whose crossings haven't changed since the last wave.

For each batch, send a single message with multiple `Task` tool calls (this is what makes them run concurrently — serial dispatch gives you no speedup). Dispatch prompt template for each subagent:

> Clue `<id>`: "<clue text>" (<enumeration>)
> Current pattern: `<from state.json>`
> Definition category (if obvious from the clue): `<e.g. "famous writer", "European river", "exclamation", "fish">`
> Prior candidates for this clue (from `guesses.jsonl`): `<list or "none">`
>
> Propose 1–5 candidates. **Hard rule: every candidate must have a stateable semantic link from the clue's definition to the answer.** Pattern-fit alone is not a candidate — if `match_pattern` gives you a word that fits the letters but you can't explain why the def points to it, skip it. Better to propose nothing than to propose a pattern-match with a shrug. Your `--reasoning` must name the def span and explain the mapping in one sentence.
>
> **Sanity-check the pattern before proposing.** When the clue has ≥1 known letter, run `match_pattern` against the current pattern and confirm your candidate is among the returned words. If it isn't, only proceed if your candidate is plausibly a proper noun (person, place, brand, named work, nationality) — UKACD excludes most of those, so absence from the list is expected and not disqualifying. For ordinary common-noun / verb / adjective answers, absence from `match_pattern` means the candidate doesn't actually fit the pattern and should be reworked. Past failures (ACTING UP, AILING, DAIRY CATTLE, BLACKBERRY BUSHES) all had clean def mappings but didn't fit the live pattern — a one-line check up front would have caught each one.
>
> Call `uv run xsolver state propose --puzzle-dir "<abs path>" --clue <id> --answer "<ANSWER>" --confidence <high|medium|low> --reasoning "<one sentence naming the def>" --wordplay <clean|partial|unparsed>` for each. Use `high` only if you're confident in BOTH wordplay and definition and the answer fits the pattern. Set `--wordplay clean` when the cryptic decomposes without hand-waving (charade, anagram, hidden, homophone, reversal); `partial` when some of it parses; `unparsed` when you only have the definition and the wordplay is a mystery. This score drives retract-target ranking downstream — an `unparsed` `high` is exactly the kind of commit that turns out to be a near-miss. Return a one-line summary of what you logged (or "skip — no def-fitting candidates" if nothing qualified).

**Prime the category.** If the clue has a narrow-category definition (a noun/adjective at start or end that names a class of things), pass it explicitly in the `Definition category` line. Short answers (≤5 letters) or tight patterns (≤5 unknowns) benefit enormously — the subagent can enumerate `match_pattern` hits filtered by category instead of grinding wordplay. Example: 12A "Writer, turning 50, led up the garden path" (4) → `Definition category: famous writer` → subagent goes `match_pattern("?A?L")` + filter writers → `DAHL` → wordplay parses trivially.

After every batch returns, use the one-shot `wave` command — it runs promote + commit + `reassess impossible` + summary in a single call and returns JSON with everything the next iteration needs:

```bash
uv run xsolver wave --puzzle-dir "$PUZZLE_DIR" --next-batch 5
```

Output buckets you must inspect every wave:

- `promoted` / `committed` / `retracted` — what moved this wave.
- `conflicts` — high-confidence clashes (automatic retract already happened).
- `impossible` — clue patterns with no wordlist match; a committed crossing is likely wrong. **Crossings are pre-sorted weakest-wordplay-first** — retract the first entry unless you have a strong reason not to.
- `likely_proper_noun` — same as impossible, but clue text suggests a nationality/place/named work/person/brand. Do NOT reflexively retract; UKACD excludes most proper nouns. Brainstorm proper-noun candidates semantically first.
- `multi_word_unchecked` — phrases the impossibility check can't evaluate directly.
- `summary` — human-readable status; `next_batch` — top-N most-constrained unsolved clues to target next.

Running the four steps separately (`state promote`, `commit wave`, `reassess impossible`, `render --summary`) is still supported but slower — each subcommand pays Python startup cost. Prefer `wave`.

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

For each unsolved clue, ordered by most-constrained-first (highest fraction of known letters in its current pattern), dispatch **2–4** `Task` calls in parallel with **`subagent_type: "solve-hard-clue"`** and **no `model` override** — the agent's frontmatter default (`opus`) is correct here. Smaller batches than Step 4 because hard clues benefit more from early checkpoints — a single unlock often frees multiple others. Before dispatching the first hard-clue batch, run `/effort high` in the orchestrator — this phase is where deep reasoning pays back.

Pass each subagent:

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

This returns unsolved clues whose current pattern admits no dictionary word, split into three buckets:

- **`impossible`** — pattern has no wordlist match AND the clue text doesn't look proper-noun-leaning. One of the committed crossings is almost certainly a **near-miss** of the setter's intended answer (same letter count, fits all its OTHER crossings, but a letter or two off). This is the retract signal.
- **`likely_proper_noun`** — pattern has no wordlist match BUT the clue text suggests a nationality, place, named work, person, or brand. **Do NOT reflexively retract.** UKACD excludes most of these. Brainstorm proper-noun candidates semantically first (e.g. `S?R????E?E` + "from South America" → SURINAMESE, not in the wordlist). Only treat as a real `impossible` if no proper-noun answer plausibly fits.
- **`multi_word_unchecked`** — phrases can't be checked by a single `match_pattern` call; inspect them manually when the single-word `impossible` list is empty but you're still stuck.

**Root-cause before retract — 30-second checkpoint.** Before any retract, list three candidate root causes in one sentence each:
1. Which committed crossing has the weakest wordplay parse? (most likely wrong)
2. Could the stuck clue's answer be a proper noun not in UKACD?
3. Does the stuck clue's definition category have ANY pattern-fitting member — including proper nouns, compounds, or archaic terms?

Only proceed to retract if #1 is strong and #2/#3 are ruled out. Chaining retracts without this check is how 20-minute wrong branches start.

The retract move: remove the shakiest-wordplay crossing, propose an alternative that fits the same crossings but has a different letter in the blocking position, then re-run promote + commit.

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
