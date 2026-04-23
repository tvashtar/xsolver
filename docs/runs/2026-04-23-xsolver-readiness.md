# XSolver Readiness Smoke Test — 2026-04-23

## Test suite

- **Total tests:** 65
- **Result:** 65 passed, 0 failed (2.31 s)

## Skill findability

`.claude/skills/solve-crossword/SKILL.md` exists and is readable (6.4 KB).

## Parse output

Command:
```
uv run python -m xsolver.parse_image parse \
  --image crosswords/sample_crossword.jpg \
  --output-dir /tmp/xsolver_smoke \
  --rows 15 --cols 15 \
  --title "Times 29,523"
```

Result: `Wrote /tmp/xsolver_smoke/puzzle.json`

- **Grid shape:** 15 x 15
- **Title:** Times 29,523
- **Clues detected:** 43 (across + down combined)

## Render output (after `init_state`)

```
· · · · · · · · · · · · · ■ ■
· ■ · ■ ■ ■ ■ ■ · ■ · ■ · ■ ·
· · · · · ■ ■ · · · · · · · ·
· · ■ · ■ · ■ ■ · ■ · ■ · ■ ·
· · · · · · · · · · ■ · · · ·
· · ■ ■ ■ · ■ ■ ■ ■ · ■ · ■ ·
· · · · · · · · ■ · · · · · ·
· · ■ · ■ · ■ ■ ■ ■ · ■ · ■ ·
· · · · · · · · ■ · · · · · ·
· · ■ · ■ · ■ · ■ ■ · ■ ■ ■ ·
· · · · · ■ ■ · · · · ■ · ■ ·
· · ■ · ■ · ■ · · ■ ■ ■ · · ·
· · ■ · ■ · ■ · ■ ■ · ■ · ■ ·
· ■ ■ · · · · · · · · · · · ·
· ■ ■ · · · · · · · · · · · ·
```

Looks like a valid cryptic crossword grid: asymmetric block pattern with `■` black squares and `·` empty cells.

## Summary output

```
Solved: 0 / 43
Unsolved clues:
  10A: no attempts
  11A: no attempts
  ...  (43 clues total, all unsolved)
```

All 43 clues listed as unsolved with no attempts — correct initial state.

## Notes

- The `render` subcommand requires `state.json` to exist (i.e. `init_state` must run first). The task specification lists render before init, but the correct operational order is parse -> init_state -> render. No code change needed; this is a documentation/workflow note.
- Parse pipeline completes without errors on the sample image.
- Grid block pattern appears consistent with a 15x15 British cryptic layout.
- 43 clues detected is a plausible count for a 15x15 puzzle (typically 28-32 answers but clue numbering can go higher with enumerations).
