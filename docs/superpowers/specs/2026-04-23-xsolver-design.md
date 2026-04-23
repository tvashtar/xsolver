# XSolver — Design Spec

**Date:** 2026-04-23
**Status:** Approved (pending user review of this doc)

## Overview

XSolver is a tool that solves British cryptic crosswords from a JPG image. It combines:

- **Claude Code** (via the user's subscription) for all generative reasoning — image interpretation, wordplay analysis, candidate generation.
- **Local Python helpers** for everything deterministic — grid parsing from the image, wordlist lookups, anagram and pattern tools, state management, commit/overlap checks, undo.

No Anthropic API calls are made. The system is invoked by the user inside a Claude Code session; the main session orchestrates the workflow, dispatching subagents only for hard clues that resist first-pass reasoning.

## Goals

1. Solve a scanned/photographed British cryptic crossword (The Times, Guardian, etc.) end-to-end from a JPG.
2. Work in clearly defined waves: initial solve → commit high-confidence → reassess clues whose letter pattern changed → repeat.
3. Detect and auto-correct wrong guesses via overlap conflict detection and undo.
4. Keep a full audit trail so any answer, retraction, or conflict can be traced.
5. Be resumable: interrupted runs pick up from where they left off.

## Non-goals (v1)

- Generating crosswords.
- Solving non-cryptic (American-style) or barred/variety crosswords.
- Running outside Claude Code (no headless CLI mode).
- Continuous-integration pipeline (may come later).
- Calibrated numeric confidence scores (tiered only).

## Architecture

### Repo layout

```
xsolver/
  pyproject.toml                   # uv-managed; deps: pillow, opencv-python, numpy, pytest, ruff
  README.md
  .claude/
    skills/
      solve-crossword/SKILL.md     # main orchestrating skill (user-invoked)
      solve-hard-clue/SKILL.md     # sub-skill for hard-clue subagents
  src/xsolver/
    __init__.py
    parse_image.py                 # JPG → puzzle.json via OpenCV + Claude-audited clue text
    wordlist.py                    # UKACD loader + pattern index
    helpers.py                     # match_pattern, anagram, check_word, check_phrase, etc.
    state.py                       # read/write state.json, append history.jsonl
    commit.py                      # commit wave + overlap check + auto-retract
    reassess.py                    # list clues whose pattern changed since last attempt
    render.py                      # ASCII grid renderer for progress visibility
    cli.py                         # thin entry points for `python -m xsolver.<module>`
  data/
    ukacd.txt                      # UK Advanced Cryptics Dictionary (~4 MB, public domain)
  crosswords/
    sample_crossword.jpg           # existing sample (Times #29,523)
    sample_crossword/              # per-puzzle working dir, created on first run
      puzzle.json                  # immutable parsed definition
      state.json                   # current grid + clue assignments (mutable)
      history.jsonl                # append-only event log
  tests/
    fixtures/
      mini/                        # 5×5 non-cryptic puzzle fixture
      synthetic_grids/             # programmatic black/white PNGs for parse tests
    test_helpers.py
    test_wordlist.py
    test_state.py
    test_commit.py
    test_reassess.py
    test_parse_image.py
    test_integration.py
  docs/
    superpowers/specs/             # this doc lives here
    runs/                          # manual-E2E run logs (post-v1 convention)
```

### Component diagram

```
                User: /solve crossword.jpg
                         │
                         ▼
            ┌──────────────────────────┐
            │  solve-crossword SKILL   │   ◀── main Claude session = orchestrator
            │  (SKILL.md workflow doc) │
            └──────────────────────────┘
                         │
   ┌─────────────────────┼──────────────────────────────────┐
   │                     │                                  │
   ▼                     ▼                                  ▼
parse_image.py   Claude reasoning (in-session)     solve-hard-clue SKILL
 (Python only,   "given clue X + pattern ?A?K?     (subagent, reserved for
 image→JSON)      propose answer+confidence")       stuck clues after wave 2)
                         │                                  │
                         ▼                                  ▼
                   helpers.py tools:                 same helpers +
                   match_pattern / anagram /         forced deeper analysis
                   check_word / check_phrase                │
                         │                                  │
                         └──────────────┬───────────────────┘
                                        ▼
                              state.py / commit.py
                              (mutations to state.json,
                               appends to history.jsonl,
                               auto-retract on conflict)
```

### Key invariants

- **Freshness:** every Claude invocation (main session or subagent) reads `state.json` at call time and is given the current letter pattern in its prompt. No stale snapshots.
- **Separation of concerns:** Python scripts never reason about clue content. Claude never mutates state files directly — always through `state.py` / `commit.py` so every change is logged.
- **Replayability:** `history.jsonl` is sufficient to reconstruct `state.json` at any point. Undo = drop the tail and replay.
- **No API costs:** all GenAI is the running Claude Code session or subagents dispatched within it.
- **Validation at the boundary:** `state.py record` rejects any write that violates schema, enumeration length, or current letter pattern. Claude cannot corrupt state with a bad write.

## Components

### Skills (Claude-facing, pure markdown)

#### `.claude/skills/solve-crossword/SKILL.md`
Main orchestrator, invoked by the user.

```yaml
name: solve-crossword
description: Use when the user asks to solve a cryptic crossword from an image, or invokes /solve on a crossword file. Triggers: "solve this crossword", "solve xword.jpg", British cryptic puzzle solving.
```

Contents: step-by-step workflow with explicit `uv run python -m xsolver.<module>` invocations, the wave loop structure, confidence-tier rules, when to dispatch hard-clue subagents, and the freshness invariant (always re-read state before solving a clue).

#### `.claude/skills/solve-hard-clue/SKILL.md`
Narrow skill for the subagent phase.

```yaml
name: solve-hard-clue
description: Use when dispatched as a subagent to solve one specific hard cryptic clue that the main solver could not crack. Requires clue text, enumeration, current letter pattern, and prior failed attempts.
```

Contents: deeper wordplay reference (anagram indicators, hidden-word markers, homophone markers, reversal markers, charade construction, &lit clues), instructions to exhaust every helper tool, and a requirement to record reasoning alongside the attempt.

### Python package (`src/xsolver/`)

| Module | Role | Notes |
|---|---|---|
| `parse_image.py` | JPG → `puzzle.json` | OpenCV for grid detection and cell classification; Claude does clue-text reading in an audit step (no Tesseract). |
| `wordlist.py` | UKACD loader + pattern-index | Cached pickle for startup speed; indexed by length and by known-letter positions. |
| `helpers.py` | Deterministic Claude-facing tools | `match_pattern("?A?K?", max=50)`, `anagram("dormitory")`, `check_word("parka")`, `check_phrase("board deal", [4,4])`, `contains_word(...)`, `deletion(...)`. All pure Python. |
| `state.py` | Read/write `state.json`, append `history.jsonl` | Single source of truth for mutations. Atomic writes (tmp + fsync + rename). Validation: schema, enumeration length, current pattern compatibility. |
| `commit.py` | Commit wave | Sort order: confidence DESC, then length DESC. Writes high-confidence answers to `cells`, runs overlap check, auto-retracts conflicts (demote both to `medium`). |
| `reassess.py` | Find clues to re-solve | Returns clues where current pattern ≠ `pattern_at_attempt` AND clue is not committed-high. |
| `render.py` | ASCII grid + unsolved-clue summary | Cosmetic; used in progress output. |
| `cli.py` | `python -m xsolver.<module>` entry points | Thin wrappers calling into module functions. |

### Data files (per-puzzle)

- **`puzzle.json`** — immutable parsed puzzle (grid, cell numbering, clues, enumerations). Written once in Phase 0.
- **`state.json`** — living document. Top-level: `cells` array (null or single uppercase letter per white cell), `iteration` counter, `clues` dict keyed by clue id. Per-clue structure:
  ```jsonc
  {
    "committed": false,              // true once answer is written to cells
    "committed_answer": null,        // the answer currently written to cells (null if not committed)
    "attempts": [
      {
        "answer": "PARKA",
        "confidence": "low",         // "high" | "medium" | "low"
        "pattern_at_attempt": "?A???",// derived from cells at record time (see below)
        "reasoning": "…",
        "rejected_reason": null      // filled in if later retracted or demoted
      }
    ]
  }
  ```
  The latest element of `attempts` is always the "current best guess". `committed_answer` is only non-null when the clue's letters live in `cells`.
- **`history.jsonl`** — append-only event log. Event types: `attempt` (every `state.py record` call), `commit`, `retract`, `conflict`, `phase-start`, `phase-end`.

### Confidence tiers

- `high` — commits immediately (only tier that ever writes to `cells` in v1).
- `medium` — recorded as attempt but not committed; eligible for promotion on reassess.
- `low` — never committed; kept for reference and for the final "stuck" report.

### Bundled assets

- `data/ukacd.txt` — UK Advanced Cryptics Dictionary, plain text, ~4 MB, checked into repo (no git-lfs).

### Subagent dispatch contract

When the main session dispatches a hard-clue subagent (Phase 4), it passes:

- Skill reference: `solve-hard-clue`.
- Clue id, text, enumeration.
- **Current letter pattern, read fresh from `state.json` at dispatch time.**
- Full list of prior attempts with reasoning.
- Absolute paths to helpers and state files.

The subagent returns a single structured result `{answer, confidence, reasoning}`. The main session validates it via `state.py record`, runs `commit.py wave`, then dispatches the next batch (1–3 at a time) with refreshed state.

## Solving loop

### Phase 0 — Parse
1. `python -m xsolver.parse_image <jpg>`: OpenCV detects grid contour, binarizes, detects cells, classifies black/white, reads cell numbers, crops clue-list regions into `clues_across.png` / `clues_down.png`. Writes `puzzle.json` with grid + numbering; clue text left blank.
2. **Claude audits.** Reads the original image + cropped clue images, fills in clue text via `python -m xsolver.parse_image set-clues <puzzle.json>`. Renders the grid with `render.py` and spot-checks shape against the original. If anything looks wrong (ambiguous cells, unreadable clues), halts and asks the user.

### Phase 1 — Initial solve wave
For each clue (serial, in-session):
1. Read current pattern from `state.json` (empty on first pass).
2. Claude reasons about the wordplay, using helpers as tools.
3. Records an attempt via `python -m xsolver.state record --clue <id> --answer <str> --confidence <tier> --reasoning <str>`. `state.py` derives `pattern_at_attempt` from the live `cells` at write time — Claude never passes it, which removes a class of "wrong pattern passed" bugs.

### Phase 2 — Commit wave
1. `python -m xsolver.commit wave`: walks clues whose latest attempt is `high` and uncommitted, sorts (confidence DESC, length DESC), commits one at a time. Each commit writes letters to `cells` and runs an overlap check.
2. On conflict (two `high`s contradict on a cell): demote both to `medium`, remove both from `cells`, append `retract` events for both and a `conflict` event describing the collision. Continue.
3. Exit when no more uncommitted `high`s.

### Phase 3 — Reassess wave
1. `python -m xsolver.reassess list` returns clues where `current_pattern != pattern_at_attempt` and the clue is not committed-high.
2. Claude re-solves each in-session; records a new attempt.
3. Return to Phase 2.

**Loop exit (between Phases 2 and 3):** a full Phase-2 pass produces zero new commits AND a full Phase-3 pass finds zero clues to reassess. Advance to Phase 4.

### Phase 4 — Hard-clue phase
1. Build hard set: all still-uncommitted clues.
2. Sort by "most constrained first" (highest fraction of known letters).
3. Dispatch subagents 1–3 at a time, using `solve-hard-clue` skill.
4. Between batches: record attempts via `state.py`, run Phase 2, run Phase 3 in-session for any newly unlocked clues, then dispatch the next batch.

**Phase 4 exit:** hard set is empty, OR every remaining clue either has no attempt or only `low` attempts that don't fit committed letters. No Hail Mary.

### Phase 5 — Report
1. Render final grid via `render.py`.
2. List unsolved clues with their best-guess attempts for human inspection.
3. Point to `history.jsonl` for full trace.

### Letter-propagation example

1A = 13-letter answer, Claude solves with `high`. 1D starts at the same cell.
- Phase 1: both get attempts. 1D was attempted against `??????` pattern.
- Phase 2: commits 1A. 1D's current pattern changes to `N?????`.
- Phase 3: reassess includes 1D because pattern changed. Claude re-solves with the first letter now known. If `high`, committed in the next Phase 2, which may unlock further clues.

### Stop-and-resume

`state.json` + `history.jsonl` are the only mutable state. If interrupted, next `/solve <same-image>` invocation loads existing state and resumes from whichever phase is appropriate based on progress. `--reset` forces a clean start.

## Error handling

### Image parsing (Phase 0)

| Failure | Response |
|---|---|
| Grid contour not found | Abort with clear message; suggest user recrop. |
| Ambiguous cell count | Abort, render detection, ask user to confirm dimensions. |
| Cell number misreads | Claude audit step catches; correct via `set-clues` or re-invoke with tighter crop. |
| Clue text OCR errors | Claude audit step corrects in `puzzle.json`. Mandatory before Phase 1. |
| Symmetry check fails | Warn but don't abort; ask user to confirm (some puzzles are asymmetric). |

**Principle:** only Phase 0 can halt the run. Downstream phases are recoverable.

### Solve-time

| Failure | Response |
|---|---|
| Non-word proposed | `helpers.check_word` returns `False`; skill requires re-thinking before recording. |
| Length mismatch with enumeration | `state.py record` rejects write; Claude re-solves. |
| Answer inconsistent with committed letters | `state.py record` rejects write; Claude re-solves. |
| Helper script exception | Surface as tool error; abort phase and report. |
| Wordlist missing | Lazy-load check; abort with actionable message. |

### Commit wave

| Failure | Response |
|---|---|
| Two-way conflict | Auto-retract both, demote to `medium`, log. Continue. |
| Three-way cascading conflict | State corruption bug; abort and dump history. |
| Overlap check errors | Don't modify `cells`; log and continue to next. |

### Subagent phase

| Failure | Response |
|---|---|
| Malformed result | Discard, log, move on (no retry, stays within token budget). |
| Timeout | Same as malformed. |
| Answer violates pattern | Caught by `state.py record`; discard. |
| All-low batch | Continue; loop exit kicks in when phase plateaus. |

### State & concurrency

| Failure | Response |
|---|---|
| Interrupted mid-write | Atomic `tmp` + `fsync` + `rename`. Jsonl appends line-buffered. |
| Concurrent runs | `fcntl.flock` on `state.json`. Second run refuses with clear error. |
| State file corrupted | Offer to rebuild from `history.jsonl`. |

### Loop safety

- **Max waves:** 25. Beyond = abort (non-convergence).
- **Max attempts per clue:** 8. Beyond = stop re-solving (stuck on something pathological).
- **Progress requirement:** each iteration must reduce unsolved count by ≥1 OR change ≥1 cell. Two consecutive no-progress iterations advance to Phase 4.

### Ambiguities to resist

- Don't fabricate clue text if OCR gibberish + unreadable image. Ask the user.
- Don't record speculative `high` answers just to get unstuck.
- Don't bypass `state.py`. All mutations go through it.

## Testing

### What we test vs. don't

- **Test deterministically:** every Python module (pure logic, clear IO).
- **Don't test:** Claude's wordplay reasoning quality. Verified manually by running on the sample.
- **Do test:** all plumbing around Claude — state mutations, validations, commit/retract paths — so bad Claude outputs are rejected cleanly.

### Unit tests

| Module | Key tests |
|---|---|
| `wordlist.py` | UKACD loads; pattern index returns expected matches; enumeration-aware phrase lookups. |
| `helpers.py` | `match_pattern` respects length/wildcards/case; `anagram` known pairs; `check_word` rejects non-words; `check_phrase` on multi-word enumerations; edge cases. |
| `state.py` | Round-trip R/W; schema validation rejects bad tiers; length/pattern mismatches rejected; atomic write on crash simulation; file lock behaviour; jsonl append order. |
| `commit.py` | Confidence+length sort; cells written correctly; conflict detection; two-way retract demotes both + logs; idempotent with no new highs. |
| `reassess.py` | Detects pattern change vs. `pattern_at_attempt`; excludes committed-high; includes previously-low where pattern changed. |
| `parse_image.py` | Cell detection on synthetic grids; symmetry check; cell numbering on fixture. |
| `render.py` | ASCII rendering matches expected on a known state. |

### Integration tests

1. **Mini 5×5 non-cryptic puzzle (fixture).** Drive `state.py` + `commit.py` + `reassess.py` directly, scripting attempts in lieu of Claude. Assert final `cells` matches known solution.
2. **Conflict resolution.** Script two committed `high`s sharing a cell with different letters (bypass pattern check for setup). Run `commit.py`. Assert both retracted, demoted, conflict logged, cells reverted.
3. **Reassess loop.** Script initial attempts, commit one answer that changes others' patterns, run `reassess list`. Assert correct clues returned.
4. **Resume from state.** Write partial `state.json` + `history.jsonl`, invoke orchestration (scripted Claude stand-in), assert it resumes correctly.
5. **Parse → audit → solve round-trip on sample.** `parse_image.py` on `sample_crossword.jpg`; assert grid dims, cell count, clue count. Golden-file once manually verified.

### End-to-end manual verification

1. Run `/solve crosswords/sample_crossword.jpg` in Claude Code.
2. Inspect final rendered grid.
3. Cross-reference against The Times published solution.
4. Review `history.jsonl` for retract storms or oddities.
5. Record metrics: % solved correctly, % attempted-wrong, % unattempted in `docs/runs/<date>-<puzzle>.md`.

### Test fixtures

- `tests/fixtures/mini/` — 5×5 non-cryptic, simple straight definitions. Plumbing-only.
- `tests/fixtures/synthetic_grids/` — programmatically generated black/white PNGs for cell-detection tests.
- `data/ukacd.txt` — real wordlist, used by `wordlist.py` tests.

### Coverage policy

No explicit percentage target for v1. Aim: every public function has at least one test. Expand as the codebase hardens.

## Out of scope (v1)

- Headless / CI execution.
- GitHub Actions pipeline.
- Pre-commit hooks.
- Generating crosswords.
- Non-cryptic crosswords.
- Online cryptic-helper lookups.
- Numeric (0–1) confidence scores.

## Open questions

None remaining at design time. Any discovered during planning/implementation will be surfaced in the plan.
