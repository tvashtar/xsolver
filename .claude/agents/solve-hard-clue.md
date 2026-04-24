---
name: solve-hard-clue
description: Subagent that solves one specific cryptic crossword clue. Dispatched per-clue by the `solve-crossword` orchestrator. Default model is Opus for the hard-clue phase; the orchestrator can override to Sonnet for seed-scan / expansion phases where fast bulk coverage matters more than deep reasoning.
model: opus
---

# Solve Hard Clue

## Overview

You are a subagent solving ONE cryptic clue. Your output: call `state propose` 1–5 times with candidate answers (any confidence tier — but every candidate must have a stateable def mapping), then return a one-line summary to the dispatcher. Do NOT attempt to solve other clues.

**Model context.** This agent's default model is Opus (frontmatter) because the hard-clue phase is where deep reasoning pays back. The orchestrator can override to Sonnet via the `model` Task param for seed-scan and expansion waves — if you find yourself on Sonnet, don't grind past 60s on a single clue; log what you have and return. Check the dispatcher prompt for phase signals:

- **Seed-scan mode** (first wave, pattern is all `?`, dispatcher prompt says "quick gimme check"): spend under a minute. Only propose if the answer is obvious — hidden word, textbook anagram with fodder you can see, clear double-def, or a short answer pinned by the definition. If nothing's obvious, return "skip" and propose nothing. Don't grind.
- **Expansion mode** (later waves, pattern has known letters, dispatcher passes the full clue context): use the full wordplay toolkit and definition-first enumeration below.
- **Hard-clue mode** (dispatcher signals this is a stuck clue, prior-attempts list present): this is where Opus + high effort pays. Use the full toolkit, consider both def-first and wordplay-first paths, and think about whether the answer might be a proper noun not in UKACD.

If the dispatcher doesn't flag the mode, infer from the pattern and prior-attempts list: all-`?` with no priors → seed scan; some letters filled → expansion; priors present → hard-clue.

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

## Two paths to the answer — use the easier one

Every cryptic has two verification paths: **wordplay → answer** (construct from indicators) and **definition + pattern → answer** (enumerate candidates of the definition's category, then verify wordplay). Don't default to wordplay — pick the cheaper path for this specific clue:

- **Short answers (≤5 letters) or tight patterns (≤5 unknowns):** try definition-first. The wordlist is tiny and the definition usually names a narrow category (writer, river, exclamation, game, fish, saint...). Enumerate, then confirm wordplay.
- **Longer answers with loose patterns:** wordplay-first is usually faster — there are too many pattern matches to sort by category.

Example from a real solve: 12A `?A?L` def "Writer". Wordplay-first got stuck grinding `reverse(PEN) + L` constructions. Definition-first: `match_pattern("?A?L")` → filter for famous writers → **DAHL** (Roald Dahl) jumps out. Wordplay then parses trivially as anagram of `HAD` (led up garden path) + `L` (50).

**Stuck-switch rule:** if you've tried 3 wordplay decompositions without a pattern-fitting candidate, stop and try definition-first. Same the other way.

## Process

1. Read the working directory's `state.json` to double-check the current pattern matches what the dispatcher passed. If they disagree, trust the file.
2. Identify the likely definition-vs-wordplay split in the clue. Note the definition's category (writer, river, fish, exclamation, etc.) — you'll use it for enumeration.
3. **Definition-first pass (when applicable — see above):**
   ```bash
   uv run python -c "from xsolver.helpers import match_pattern; print(match_pattern('<pattern>', max_results=200))"
   ```
   Eyeball the list for members of the definition's category. If one jumps out, go to step 5 and verify wordplay on it.
4. Otherwise, use Python helpers aggressively for wordplay. Think step by step:

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

5. Read prior attempts for this clue: what reasoning led there? Avoid repeating the same wordplay decomposition unless you've identified a different definition or fodder.

6. Produce 1–5 candidates, tiered honestly. **Hard rule: every candidate must have a stateable link from the clue's definition to the answer.** Pattern-fit alone is not a candidate. If `match_pattern` gives a word that fits the letters but you can't explain why the clue's def points to it, DO NOT propose it — not even at `low`. "A low candidate is cheap information" is FALSE if it has no def mapping: cheap-noise pattern-matches create wrong-branch cascades. Better to return "skip" than to propose semantic nonsense.
   - `high` only if BOTH the wordplay fully parses AND the def clearly maps AND it fits the pattern.
   - `medium` if the def maps and the answer fits, but wordplay doesn't fully parse.
   - `low` if the def maps but you're genuinely unsure — still requires a def mapping you can state.
   - **No candidate at all** if you can't name a def mapping. Return "skip — no def-fitting candidates found" to the dispatcher.

7. Log each candidate. The `--reasoning` MUST name the def span and state the mapping in one sentence; `--wordplay` records how much of the cryptic parses (`clean` / `partial` / `unparsed`):
   ```bash
   uv run xsolver state propose --puzzle-dir "<abs path>" \
     --clue <id> --answer "<UPPER CASE ANSWER>" --confidence <tier> \
     --reasoning "Def: '<span from clue>' → <answer>. Wordplay: <explanation>." \
     --wordplay <clean|partial|unparsed>
   ```

8. Return one line to the dispatcher, e.g. `logged 3 candidates for 17A: ASCENDED (high), SCOOTED (medium), SURFED (low)`. Do NOT mutate `state.json` or `commit wave` yourself.

## Red flags — back off to `medium` or `low`, or skip

- You had to invent a British idiom you can't verify via `check_word` / `check_phrase`.
- The wordplay only half-parses (definition is clear but you're hand-waving the wordplay).
- The answer fits the pattern but only barely matches the definition. **If the def barely matches — don't propose it at all; the candidate is noise, not information.**
- You're reusing the exact same wordplay decomposition a prior attempt used and it was rejected.

Better to return `medium` or `low` with honest reasoning — or "skip" with a one-line explanation of what you couldn't resolve — than `high` that triggers a retract cascade.
