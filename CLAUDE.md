# xsolver

Cryptic crossword solver orchestrated by Claude Code. The `solve-crossword` skill drives the loop; this package is the tool layer — pattern helpers, state management, commit logic, image parsing.

## Setup (one time)

```bash
uv sync
```

Creates `.venv`, installs the project (editable) + runtime deps + dev deps (from PEP 735 `[dependency-groups]`), and reads `uv.lock` for reproducible resolution. `uv.lock` is committed. To skip dev deps (pytest, ruff): `uv sync --no-dev`.

After this, `uv run xsolver <subcommand>` works anywhere. The `.claude/settings.json` allow-list only whitelists `uv run xsolver *` and `uv run pytest *` — arbitrary `uv run python -c "..."` still prompts (intentional: those are arbitrary-code injection points for ad-hoc helper queries).

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

Never mutate `state.json`, `history.jsonl`, or `guesses.jsonl` by hand. Use the CLI.

## CLI cheat sheet

```bash
# Parse + reconstruct
uv run xsolver parse_image parse --image X.jpg --output-dir DIR --rows 15 --cols 15
uv run xsolver parse_image reconstruct --specs-json specs.json  # fallback when photo is distorted
uv run xsolver parse_image set-clues --updates-json X.json
uv run xsolver state init --puzzle-dir DIR

# Candidate lifecycle (subagents write, orchestrator promotes+commits)
uv run xsolver state propose --clue 17A --answer "ASCENDS" --confidence high --reasoning "..."
uv run xsolver state promote --puzzle-dir DIR
uv run xsolver commit wave --puzzle-dir DIR
uv run xsolver state candidates --puzzle-dir DIR [--clue 17A]
uv run xsolver state retract --puzzle-dir DIR --clue 16A --reasoning "blocks 13D"

# Inspecting progress
uv run xsolver render --puzzle-dir DIR               # ASCII grid
uv run xsolver render --puzzle-dir DIR --summary     # per-clue status
uv run xsolver render --puzzle-dir DIR --next-batch 5 # JSON: N clues most ready to solve
uv run xsolver render --puzzle-dir DIR --html > grid.html
uv run xsolver reassess list --puzzle-dir DIR        # clues whose pattern changed since last attempt
uv run xsolver reassess impossible --puzzle-dir DIR  # clues whose pattern admits no dictionary word (retract signal)

# Live observability (run in a separate terminal)
uv run xsolver watch --puzzle-dir DIR
```

## Architecture

- `src/xsolver/cli.py` — argparse dispatch for every subcommand.
- `src/xsolver/state.py` — `Puzzle` / `State` dataclasses, `propose` (unlocked append), `record` / `promote_candidates` / `retract` (locked), `acquire_puzzle_lock`.
- `src/xsolver/commit.py` — `run_wave`: reads attempts, picks high-confidence non-conflicting set, writes letters.
- `src/xsolver/reassess.py` — `list_stale` (clues to re-try), `list_impossible` (pattern has zero dictionary matches → something's wrong upstream).
- `src/xsolver/parse_image.py` — OpenCV grid detection with auto-tune; `validate_grid` (symmetry + min-word-length); `reconstruct_from_clues` fallback using number positions.
- `src/xsolver/helpers.py` — `match_pattern`, `anagram`, `check_word`, `check_phrase`, `contains_word`, `deletion`. These are the subagents' wordplay toolkit; called via `uv run python -c "from xsolver.helpers import ..."` (each call prompts — that's fine).
- `src/xsolver/render.py` — grid display, summary, HTML export, `next_batch` picker (sort by % pattern known).
- `src/xsolver/watch.py` — polls `state.json` mtime and tails `history.jsonl` in a second terminal.

## Parallel-safety contract

- `propose` is the only write that's safe from concurrent subagents. Everything else (promote, commit, retract, record) takes the puzzle lock.
- `promote_candidates` is idempotent per (clue, answer, confidence) — higher tiers can re-promote to upgrade, but same tier is a no-op.
- The lock is a `flock` on `.puzzle.lock` inside the puzzle dir. Don't hold it across subagent dispatch.

## Parser fragility (known)

`detect_grid_bbox` + equal-division `classify_cells` can't recover from newspaper-photo perspective distortion. `parse_puzzle` validates (`validate_grid`) and raises `GridValidationError` on failure. Fallback path: read number positions off the image yourself and call `reconstruct_from_clues` with a `clue_specs.json`. This is the robust path for any photo that isn't a flat scan.

## Stuck-unsticking

After every commit wave, run `xsolver reassess impossible`. If it returns any single-word clues, one of the listed committed crossings is a near-miss of the setter's intended answer. Retract the weakest-wordplay one (definition-only solves with no parseable wordplay are usually the culprit), re-propose, re-promote, re-commit. Real example from the sample solve: `RED DEER` at 16A blocked 13D; retracting and substituting `ROE DEER` (same letter count, different pos-2) unlocked `PEACE CORPS`.

## Testing

```bash
uv run pytest
```

80 tests, ~3s. Covers state/commit/reassess/render/parse_image/wordlist. Integration tests in `tests/test_integration.py` run the full propose → promote → commit path on a toy 3-clue puzzle.

## Style

- Type hints everywhere; modern Python (3.11+).
- Dataclasses for state types; `_atomic_write_json` for safe JSON writes.
- Minimal comments — only for non-obvious invariants.
- Exceptions in Python are the contract: `GridValidationError`, pattern mismatches raise `ValueError`, puzzle lock raises `BlockingIOError`.

## Don'ts

- Don't edit `state.json`, `history.jsonl`, or `guesses.jsonl` directly.
- Don't use `uv run python -m xsolver.*` — the entry point is `uv run xsolver *`.
- Don't commit `high` candidates on pattern-fit alone; verify wordplay first. Pattern-fit twins (MERCY CORPS vs PEACE CORPS) are the classic trap.
- Don't grind wordplay on short answers (≤5 letters) — enumerate pattern matches filtered by the definition's category instead.
