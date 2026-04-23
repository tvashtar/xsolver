# XSolver

Claude Code-orchestrated solver for British cryptic crosswords.

## Setup

```bash
uv sync --all-extras
bash scripts/fetch_wordlist.sh
```

## Usage

Inside a Claude Code session:

```
/solve crosswords/sample_crossword.jpg
```

Claude will:
1. Parse the image (Python/OpenCV).
2. Audit the OCR'd clue text against the image.
3. Solve wave by wave, committing only high-confidence answers and auto-retracting on letter conflicts.
4. Dispatch hard-clue subagents for clues that resist initial solving.
5. Report the filled grid and any unsolved clues, with a full audit trail in `crosswords/<name>/history.jsonl`.

## Design

See [`docs/superpowers/specs/2026-04-23-xsolver-design.md`](docs/superpowers/specs/2026-04-23-xsolver-design.md) for the full design spec and [`docs/superpowers/plans/2026-04-23-xsolver.md`](docs/superpowers/plans/2026-04-23-xsolver.md) for the implementation plan.

## Testing

```bash
uv run pytest
```

## Layout

- `src/xsolver/` — deterministic Python helpers (wordlist, state, commit, reassess, render, parse_image, cli).
- `.claude/skills/solve-crossword/` — main orchestration skill (user-invoked).
- `.claude/skills/solve-hard-clue/` — subagent skill for hard clues.
- `data/ukacd.txt` — bundled UK Advanced Cryptics Dictionary wordlist.
- `crosswords/` — input images and per-puzzle working dirs.
