---
name: solve-crossword
description: Use when the user asks to solve a cryptic crossword from an image, or runs /solve on a crossword file. Triggers include "solve this crossword", "solve xword.jpg", British cryptic puzzles from The Times / Guardian / Independent.
---

# Solve Crossword

## Overview

Solve a British cryptic crossword from a JPG. You orchestrate a wave-based loop:

1. Parse image → puzzle.json (Python).
2. Audit clue text against the image (you read the image).
3. Initial solve wave: attempt every clue in isolation.
4. Commit wave: high-confidence answers written to cells; conflicts auto-retract.
5. Reassess wave: re-solve any clue whose letter pattern changed.
6. Hard-clue phase: dispatch `solve-hard-clue` subagents, 1–3 at a time.
7. Report.

## Invariants (non-negotiable)

- **Freshness:** before solving any clue, re-read `state.json` (you can get the current pattern from it). Never cache patterns across iterations.
- **Mutations go through Python:** use `python -m xsolver.state record ...`, `python -m xsolver.commit wave`, `python -m xsolver.reassess list`. Never edit `state.json` or `history.jsonl` directly.
- **Confidence discipline:** `high` = "I'm confident in both wordplay AND definition, and candidate is a real word that fits enumeration"; `medium` = "plausible but unsure"; `low` = "guess". Only `high` is committed to cells.
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
   If the shape looks wrong (cells misclassified as black/white, clue count disagrees with the image), STOP and ask the user.

### Step 3 — Initialise state if not already

```bash
test -f "$PUZZLE_DIR/state.json" || \
  uv run python -c "from xsolver.state import init_state; from pathlib import Path; init_state(Path('$PUZZLE_DIR'))"
```

### Step 4 — Initial solve wave (in-session)

For every clue in `puzzle.json` that isn't already committed:

1. Re-read `state.json`, compute the current letter pattern for the clue (cells whose letters are filled in → that letter; others → `?`).
2. Reason about the wordplay. Call helper tools as needed via one-liners like:
   ```bash
   uv run python -c "from xsolver.helpers import match_pattern; print(match_pattern('?A?K?'))"
   uv run python -c "from xsolver.helpers import anagram; print(anagram('DORMITORY', length=10))"
   ```
3. Decide on `high` / `medium` / `low` based on the discipline above.
4. Record:
   ```bash
   uv run python -m xsolver.state record --puzzle-dir "$PUZZLE_DIR" \
     --clue <id> --answer "<ANSWER>" --confidence <tier> --reasoning "<brief>"
   ```
   `state.py` will reject the write if the length is wrong or the answer conflicts with existing letters. If it rejects, re-think; don't force the write.

### Step 5 — Commit wave

```bash
uv run python -m xsolver.commit wave --puzzle-dir "$PUZZLE_DIR"
```

Review the JSON summary printed to stdout. `retracted`/`conflicts` entries mean two high answers clashed — both are now `medium`.

### Step 6 — Reassess wave

```bash
uv run python -m xsolver.reassess list --puzzle-dir "$PUZZLE_DIR"
```

For each entry returned, re-solve the clue (repeat Step 4 for that single clue), then go back to Step 5. Loop until reassess returns `[]` AND a full commit wave produced zero new commits.

### Step 7 — Hard-clue phase

List remaining unsolved clues:

```bash
uv run python -m xsolver.render --puzzle-dir "$PUZZLE_DIR" --summary
```

For each unsolved clue, ordered by most-constrained-first (highest fraction of known letters in its current pattern), dispatch 1–3 subagents using the `solve-hard-clue` skill. Pass each subagent:

- Clue id, text, enumeration.
- Current letter pattern (freshly read from `state.json` at dispatch time).
- The list of prior attempts and why they were rejected.
- The absolute path to `$PUZZLE_DIR` so the subagent can call helpers.

After each batch returns, record their attempts, run a commit wave, run a reassess wave, then dispatch the next batch with refreshed state.

**Exit the hard-clue phase when:**
- The hard set is empty, OR
- A full batch produces zero new high-confidence commits AND reassess unlocks nothing new — i.e. every remaining clue has either no attempt or only `low` attempts that don't fit committed letters.

No Hail Mary: don't keep dispatching subagents once the phase plateaus.

### Step 8 — Report

```bash
uv run python -m xsolver.render --puzzle-dir "$PUZZLE_DIR"
uv run python -m xsolver.render --puzzle-dir "$PUZZLE_DIR" --summary
```

Tell the user: `X / Y` clues solved, any unsolved ones listed with best-guess attempts, and the path to `$PUZZLE_DIR/history.jsonl` for a full audit trail.

## Safety caps

- Max 25 wave iterations. If you hit it, abort and report.
- Max 8 attempts per clue. If any clue has 8 attempts, stop re-solving it.
- Two consecutive no-progress iterations (no commits AND no reassess unlocks) → advance to Phase 4.

## When to stop and ask the user

- Image parse produced nonsense (wrong grid shape, unreadable clues, ambiguous cell count). Don't fabricate clue text.
- Two `high`s conflict repeatedly on the same clue after multiple reassesses — the system is genuinely confused; hand back to the user for a hint.
