---
name: solve-hard-clue
description: Use when dispatched as a subagent to solve one specific hard cryptic clue that the main solver could not crack. Requires clue text, enumeration, current letter pattern, and prior failed attempts.
---

# Solve Hard Clue

## Overview

You are a subagent solving ONE cryptic clue. You have more runway to reason deeply. Your output: call `state propose` 1–5 times with candidate answers (any confidence tier), then return a one-line summary to the dispatcher. Do NOT attempt to solve other clues.

Use `propose` (not `record`) — it's lock-free and parallel-safe, so multiple subagents running concurrently don't stomp on each other. The main dispatcher runs `state promote` after your batch returns, which picks the best compatible candidate per clue and promotes it for the commit wave.

## What you receive from the dispatcher

- Clue id (e.g. `17A`), text, enumeration (e.g. `[3,4]`).
- **Current letter pattern**, freshly read from `state.json` at dispatch time. This IS the truth; trust it.
- Prior attempts for this clue and their rejection reasons (e.g. "conflicted with 3D at cell 12").
- Absolute path to the puzzle working directory.

## British cryptic setter's toolkit (reference)

A cryptic clue almost always decomposes into **definition + wordplay**. The definition is at one end (start or finish) of the clue; the wordplay is the rest. Your job: find where the split is.

Common wordplay types and their indicator words:

| Type | Indicators (partial list) |
|---|---|
| **Anagram** | confused, wild, messy, sort, broken, strange, drunk, disturbed, out, crazy |
| **Hidden word** | in, within, among, held by, some, part of, contains |
| **Reversal** | back, returning, up, westward, retreats (in Across clues), rising (in Down clues) |
| **Homophone** | sounds like, reportedly, we hear, on the radio, said |
| **Deletion** | beheaded (drop first), curtailed/endless (drop last), topless, heartless (drop middle) |
| **Container** | in, around, surrounds, admits, holds, covers |
| **Charade** | multi-part: concatenation of letter/word substrings |
| **Double definition** | the clue has two definitions of the same answer, no wordplay marker |
| **&lit** | the whole clue is both definition and wordplay |

Frequent abbreviations UK setters assume:
- `RE` = about, regarding; `OR` = soldiers (Other Ranks); `GI` = US soldier; `SS` = ship
- `E/W/N/S` = direction; `L/R` = left/right
- `A/C` = account; `K` = king; `Q` = queen; `NB` = note; `PS` = postscript
- `U` = acceptable, posh; `IN` = fashionable; `IT` = sex appeal; `CH` = church
- Single letters: `E` = energy/English, `L` = learner/left, `T` = time/model

## Process

1. Read the working directory's `state.json` to double-check the current pattern matches what the dispatcher passed. If they disagree, trust the file.
2. Identify the likely definition-vs-wordplay split in the clue.
3. Use Python helpers aggressively. Think step by step:

```bash
cd <puzzle-dir-parent>

# List words matching pattern:
uv run python -c "from xsolver.helpers import match_pattern; print(match_pattern('<pattern>', max_results=200))"

# Anagrams of a fodder word, filtered to the expected length:
uv run python -c "from xsolver.helpers import anagram; print(anagram('<fodder>', length=<n>))"

# Is it a real word/phrase?
uv run python -c "from xsolver.helpers import check_word; print(check_word('<candidate>'))"
uv run python -c "from xsolver.helpers import check_phrase; print(check_phrase('<phrase>', enumeration=[<lengths>]))"

# Hidden word?
uv run python -c "from xsolver.helpers import contains_word; print(contains_word('<clue fragment letters>', length=<n>))"

# Deletion?
uv run python -c "from xsolver.helpers import deletion; print(deletion('<source>', chars_to_drop=<k>))"
```

4. Read prior attempts for this clue: what reasoning led there? Avoid repeating the same wordplay decomposition unless you've identified a different definition or fodder.

5. Produce 1–5 candidates, tiered honestly:
   - `high` only if BOTH the wordplay fully parses AND the result is a genuine word/phrase AND it fits the pattern.
   - `medium` if plausible but wordplay doesn't fully parse.
   - `low` if it's a shot in the dark — still log it! A low candidate that later becomes pattern-compatible is cheap information.

6. Log each candidate:
   ```bash
   uv run python -m xsolver.state propose --puzzle-dir "<abs path>" \
     --clue <id> --answer "<UPPER CASE ANSWER>" --confidence <tier> \
     --reasoning "Definition: '<part>'. Wordplay: <explanation>."
   ```

7. Return one line to the dispatcher, e.g. `logged 3 candidates for 17A: ASCENDED (high), SCOOTED (medium), SURFED (low)`. Do NOT mutate `state.json` or `commit wave` yourself.

## Red flags — back off to `medium` or `low`

- You had to invent a British idiom you can't verify via `check_word` / `check_phrase`.
- The wordplay only half-parses (definition is clear but you're hand-waving the wordplay).
- The answer fits the pattern but only barely matches the definition.
- You're reusing the exact same wordplay decomposition a prior attempt used and it was rejected.

Better to return `medium` or `low` with honest reasoning than `high` that triggers a retract cascade.
