"""ASCII grid rendering and progress summary."""

from __future__ import annotations

from pathlib import Path

from xsolver.state import load_puzzle, load_state

BLACK = "■"
EMPTY = "·"


def _cells_by_coords(puzzle_dir: Path) -> dict[tuple[int, int], int]:
    """Map (row, col) → cell index by walking the grid in reading order."""
    puzzle = load_puzzle(puzzle_dir)
    coords_to_idx: dict[tuple[int, int], int] = {}
    idx = 0
    for r in range(puzzle.rows):
        for c in range(puzzle.cols):
            if puzzle.grid[r][c] == ".":
                coords_to_idx[(r, c)] = idx
                idx += 1
    return coords_to_idx


def render_grid(puzzle_dir: Path) -> str:
    puzzle = load_puzzle(puzzle_dir)
    state = load_state(puzzle_dir)
    coords_to_idx = _cells_by_coords(puzzle_dir)

    lines = []
    for r in range(puzzle.rows):
        row_chars = []
        for c in range(puzzle.cols):
            if puzzle.grid[r][c] == "#":
                row_chars.append(BLACK)
            else:
                idx = coords_to_idx[(r, c)]
                v = state.cells[idx]
                row_chars.append(v if v else EMPTY)
        lines.append(" ".join(row_chars))
    return "\n".join(lines)


def render_summary(puzzle_dir: Path) -> str:
    puzzle = load_puzzle(puzzle_dir)
    state = load_state(puzzle_dir)

    total = len(puzzle.clues)
    committed = sum(1 for cs in state.clues.values() if cs.committed)
    unsolved_ids = [cid for cid, cs in state.clues.items() if not cs.committed]
    lines = [
        f"Solved: {committed} / {total}",
        "Unsolved clues:",
    ]
    for cid in sorted(unsolved_ids):
        cs = state.clues[cid]
        last = cs.attempts[-1] if cs.attempts else None
        if last:
            lines.append(f"  {cid}: best guess {last.answer!r} ({last.confidence})")
        else:
            lines.append(f"  {cid}: no attempts")
    return "\n".join(lines)
