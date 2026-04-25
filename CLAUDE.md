# xsolver

Cryptic crossword solver orchestrated by Claude Code. The `solve-crossword` skill drives the loop; this package is the tool layer — pattern helpers, state management, commit logic, image parsing.

## Setup (one time)

```bash
uv sync
```

Creates `.venv`, installs the project (editable) + runtime deps + dev deps (from PEP 735 `[dependency-groups]`), and reads `uv.lock` for reproducible resolution. `uv.lock` is committed. To skip dev deps (pytest, ruff): `uv sync --no-dev`.

After this, `uv run xsolver <subcommand>` works anywhere. The `.claude/settings.json` allow-list only whitelists `uv run xsolver *` and `uv run pytest *` — arbitrary `uv run python -c "..."` still prompts (intentional: every solving operation has a dedicated `xsolver` subcommand, so there's no legitimate reason an agent should reach for inline Python). The wordplay helpers (`match_pattern`, `anagram`, `check_word`, `check_phrase`, `contains_word`, `deletion`) are exposed as `xsolver helpers <op>` subcommands; image cropping is `xsolver image crop`.

## Mental model

A solve produces three append-only log files and two rewritable state files per puzzle:

| File | Role | Writer |
|---|---|---|
| `puzzle.json` | Immutable puzzle spec: grid, clues, cell indices | `xsolver parse_image` once |
| `state.json` | Current letters + per-clue attempts + commit flags | `record`, `commit wave`, `promote`, `retract` (locked) |
| `guesses.jsonl` | Every candidate proposed by any subagent | `xsolver state propose` (lock-free, parallel-safe) |
| `history.jsonl` | Audit trail of all events | `commit`, `promote`, `retract`, etc. |

The **propose → promote → commit** pipeline is what makes parallel subagents safe:

1. Subagents `propose` candidates to `guesses.jsonl` concurrently — no lock, POSIX-atomic appends.
2. Orchestrator runs `state promote` — under the lock, picks best-pattern-compatible candidate per clue, writes it to `state.clues[*].attempts`.
3. Orchestrator runs `commit wave` — under the lock, writes letters for every `high`-confidence attempt, retracts conflicts.

In practice, use the one-shot `xsolver wave` command (runs all three plus `reassess impossible` and a summary in a single Python process — see cheat sheet). The individual commands are still available for debugging.

### Subagent architecture and model tiering

Per-clue subagents are defined by the **`solve-hard-clue` agent** at `.claude/agents/solve-hard-clue.md`. Its frontmatter sets `model: opus` as the default — correct for the hard-clue phase. For the faster phases, the orchestrator **overrides** via the Task `model` param:

| Phase | `subagent_type` | `model` override | Effort |
|---|---|---|---|
| Wave 0 seed scan (gimme checks) | `solve-hard-clue` | `"sonnet"` | default |
| Waves 1+ expansion (wordplay) | `solve-hard-clue` | `"sonnet"` | default |
| Hard-clue phase (stuck clues) | `solve-hard-clue` | *omit* (use frontmatter `opus`) | `/effort high` in orchestrator |

Single agent, mode-aware — the agent itself infers which phase it's in from the dispatcher prompt (presence of a prior-attempts list, "gimme check" phrasing, etc.) and adjusts grind-time accordingly. Don't pin a Sonnet version string — `"sonnet"` resolves to the current default.

Rationale: the model default lives in frontmatter so the hard-clue dispatch site needs no per-call model annotation, which is exactly when the orchestrator is most likely to be thinking about something else (stuck-unsticking). The seed/expansion sites have to opt into faster model explicitly, which is the right direction for a cost guardrail — the default errs toward quality.

Never mutate `state.json`, `history.jsonl`, or `guesses.jsonl` by hand. Use the CLI.

### Confidence vs wordplay strength

Two orthogonal scores on every `propose` / `record`:

- `--confidence <high|medium|low>` — overall bet that this is the answer. Only `high` commits letters.
- `--wordplay <clean|partial|unparsed>` — does the cryptic parse decompose without hand-waving? `clean` = charade / anagram / hidden / homophone / reversal parses end-to-end; `partial` = some of it parses; `unparsed` = definition-only guess.

Why both: an `unparsed` `high` is the classic near-miss pattern (def fits, wordplay is a shrug — PYROLACEAE for "drug from South America" is the canonical example). `reassess impossible` uses the wordplay score to rank committed crossings weakest-first in the `committed_crossings` list, so the retract target is mechanical rather than a judgment call.

### `reassess impossible` output buckets

- `impossible` — pattern has no wordlist match AND the clue doesn't look proper-noun-leaning. Retract the first `committed_crossings` entry (already sorted weakest-wordplay-first).
- `likely_proper_noun` — pattern has no wordlist match BUT the clue text suggests a nationality/place/named work/person/brand. UKACD excludes most of these. Brainstorm proper-noun candidates semantically before retracting anything. This is the bucket that caught SURINAMESE after the wordlist-only check had falsely accused CLUBS.
- `multi_word_unchecked` — phrases that `match_pattern` can't directly evaluate.

## CLI cheat sheet

```bash
# Parse + reconstruct
uv run xsolver parse_image parse --image X.jpg --output-dir DIR --rows 15 --cols 15
uv run xsolver parse_image reconstruct --specs-json specs.json  # fallback when photo is distorted
uv run xsolver parse_image set-clues --updates-json X.json
uv run xsolver state init --puzzle-dir DIR

# Candidate lifecycle (subagents write, orchestrator promotes+commits)
uv run xsolver state propose --clue 17A --answer "ASCENDS" --confidence high \
    --reasoning "..." --wordplay clean   # --wordplay drives retract-target ranking
uv run xsolver state candidates --puzzle-dir DIR [--clue 17A]
uv run xsolver state retract --puzzle-dir DIR --clue 16A --reasoning "blocks 13D"

# Reset a puzzle (delete state/guesses/history/lock, keep puzzle.json) to re-solve
# from scratch without re-parsing the image. Add --init to also run state init.
uv run xsolver state reset --puzzle-dir DIR [--init]

# One-shot orchestration (preferred — single Python process)
uv run xsolver wave --puzzle-dir DIR [--next-batch 5] [--stale]
# Runs: promote → commit wave → reassess impossible → summary; returns JSON with
# promoted/committed/retracted/conflicts/impossible/likely_proper_noun/
# multi_word_unchecked/summary [+ next_batch/stale if flagged].

# Lower-level commands (still supported for debugging)
uv run xsolver state promote --puzzle-dir DIR
uv run xsolver commit wave --puzzle-dir DIR
uv run xsolver reassess list --puzzle-dir DIR        # stale: pattern changed since last attempt
uv run xsolver reassess impossible --puzzle-dir DIR  # same three-bucket output as `wave`

# Inspecting progress
uv run xsolver render --puzzle-dir DIR               # ASCII grid
uv run xsolver render --puzzle-dir DIR --summary     # per-clue status
uv run xsolver render --puzzle-dir DIR --next-batch 5 # JSON: N clues most ready to solve
uv run xsolver render --puzzle-dir DIR --html > grid.html

# Live observability (run in a separate terminal)
uv run xsolver watch --puzzle-dir DIR
```

## Architecture

- `src/xsolver/cli.py` — argparse dispatch for every subcommand, including the one-shot `wave`.
- `src/xsolver/state.py` — `Puzzle` / `State` / `Attempt` dataclasses (Attempt carries `wordplay_strength`), `propose` (unlocked append), `record` / `promote_candidates` / `retract` (locked), `acquire_puzzle_lock`.
- `src/xsolver/commit.py` — `run_wave`: reads attempts, picks HIGHEST-confidence attempt per clue (not latest — a late `low` propose must not shadow an earlier `high`), commits non-conflicting set, writes letters.
- `src/xsolver/reassess.py` — `list_stale` (pattern changed since last attempt), `list_impossible` (three buckets: `impossible`, `likely_proper_noun`, `multi_word_unchecked`; `committed_crossings` pre-sorted weakest-wordplay-first).
- `src/xsolver/parse_image.py` — OpenCV grid detection with auto-tune; `validate_grid` (symmetry + min-word-length); `reconstruct_from_clues` fallback using number positions.
- `src/xsolver/helpers.py` — `match_pattern` (LRU-cached per-process), `anagram`, `check_word`, `check_phrase`, `contains_word`, `deletion`. These are the subagents' wordplay toolkit; called via `uv run xsolver helpers <op>` (under the `xsolver *` allowlist, no permission prompt). The CLI wrapper lives in `cli.py::_helpers_main` and prints JSON.
- `src/xsolver/render.py` — grid display, summary, HTML export, `next_batch` picker (sort by % pattern known).
- `src/xsolver/watch.py` — polls `state.json` mtime and tails `history.jsonl` in a second terminal.

## Parallel-safety contract

- `propose` is the only write that's safe from concurrent subagents. Everything else (promote, commit, retract, record) takes the puzzle lock.
- `promote_candidates` is idempotent per (clue, answer, confidence) — higher tiers can re-promote to upgrade, but same tier is a no-op.
- The lock is a `flock` on `.puzzle.lock` inside the puzzle dir. Don't hold it across subagent dispatch.

## Parser fragility (known)

`detect_grid_bbox` + equal-division `classify_cells` can't recover from newspaper-photo perspective distortion. `parse_puzzle` validates (`validate_grid`) and raises `GridValidationError` on failure. Fallback path: read number positions off the image yourself and call `reconstruct_from_clues` with a `clue_specs.json`. This is the robust path for any photo that isn't a flat scan.

## Stuck-unsticking

Every commit cycle, run `xsolver wave` and inspect three buckets:

1. **`impossible`** — pattern admits no dictionary word. `committed_crossings` is pre-sorted weakest-wordplay-first; retract `committed_crossings[0]`, re-propose a pattern-compatible alternative for both the retracted clue and the stuck one. Real example: `RED DEER` at 16A blocked 13D; retracting and substituting `ROE DEER` (same letter count, different pos-2) unlocked `PEACE CORPS`.
2. **`likely_proper_noun`** — pattern admits no dictionary word BUT the clue text mentions a nationality/place/named work/person/brand. UKACD excludes most of these. Do NOT reflexively retract; brainstorm proper-noun candidates semantically first. Real example: `S?R????E?E` + "from South America" → SURINAMESE (not in UKACD); an earlier version of this skill retracted CLUBS here and cascaded into a 20-minute wrong branch.
3. **`multi_word_unchecked`** — inspect manually when the single-word lists are both empty.

30-second checkpoint before any retract:
- (a) Which committed crossing has the weakest wordplay? `committed_crossings[0]` — but sanity-check: if two are tied on "unparsed," prefer the one whose def is also weakest.
- (b) Could the stuck clue's answer be a proper noun not in UKACD?
- (c) Does the stuck clue's definition category have ANY pattern-fitting member including proper nouns, compounds, or archaics?

Only retract if (a) is clearly weakest and (b)/(c) are ruled out.

## Testing

```bash
uv run pytest
```

87 tests, ~3s. Covers state/commit/reassess/render/parse_image/wordlist + `wave` CLI integration. Integration tests in `tests/test_integration.py` run the full propose → promote → commit path on a toy 3-clue puzzle. Regression tests to watch when touching commit/reassess:

- `test_commit_picks_highest_confidence_not_latest_attempt` — a late `low` must not shadow an earlier `high`.
- `test_impossible_sorts_crossings_by_wordplay_weakness` — `committed_crossings[0]` is the retract target.
- `test_impossible_flags_proper_noun_clues_separately` — proper-noun-leaning clues land in `likely_proper_noun`, not `impossible`.

## Style

- Type hints everywhere; modern Python (3.11+).
- Dataclasses for state types; `_atomic_write_json` for safe JSON writes.
- Minimal comments — only for non-obvious invariants.
- Exceptions in Python are the contract: `GridValidationError`, pattern mismatches raise `ValueError`, puzzle lock raises `BlockingIOError`.

## Don'ts

- Don't edit `state.json`, `history.jsonl`, or `guesses.jsonl` directly.
- Don't use `uv run python -m xsolver.*` — the entry point is `uv run xsolver *`.
- **Never propose purely on pattern-fit.** Every proposed answer must have a plausible semantic path from the clue to the answer — at minimum, the definition span of the clue must map to the answer in a way you can state in one sentence. Pattern-fit without a def explanation is not a candidate; it's noise. If `match_pattern` gives you a word that fits the letters but you can't explain why the clue's def points to it, **don't propose it at any tier**. This is how wrong commits cascade (PYROLACEAE for "drug from South America," TELPHERS for "ice age," MERCY CORPS for "non-combatant volunteers"). When you genuinely can't find a def-fitting candidate, the correct move is to name the problem and stop — not to offer a pattern-match and hope.
- Don't commit `high` candidates on pattern-fit alone; verify wordplay first. Pattern-fit twins (MERCY CORPS vs PEACE CORPS) are the classic trap.
- Don't grind wordplay on short answers (≤5 letters) — enumerate pattern matches filtered by the definition's category instead.
- Don't retract on `likely_proper_noun` without first brainstorming non-dictionary candidates (nationalities, places, named works, people, brands). UKACD is a crossword wordlist, not an encyclopedia.
- Don't skip `--wordplay` when proposing a `high` candidate. Without it, `reassess impossible` can't rank retract targets and the orchestrator has to guess.
