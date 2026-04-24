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


_HTML_CSS = """
body { font-family: system-ui, sans-serif; margin: 2em; }
h1 { font-size: 1.3em; margin-bottom: 0.5em; }
table.grid { border-collapse: collapse; margin-bottom: 1.5em; }
table.grid td {
  width: 36px; height: 36px;
  border: 1px solid #222;
  text-align: center; vertical-align: middle;
  font-weight: bold; font-size: 1.1em;
  position: relative;
  background: #fff;
}
table.grid td.black { background: #222; }
table.grid td .num {
  position: absolute; top: 1px; left: 2px;
  font-size: 0.55em; font-weight: normal; color: #666;
}
.clues { display: flex; gap: 2em; }
.clues section { flex: 1; max-width: 30em; }
.clues h2 { font-size: 1em; margin: 0 0 0.4em; border-bottom: 1px solid #ccc; }
.clues ol { padding-left: 2em; margin: 0; }
.clues li { margin-bottom: 0.3em; font-size: 0.9em; }
.clues .answer { color: #0a6; font-weight: bold; margin-left: 0.4em; }
.clues .unsolved .answer { color: #c40; }
"""


def _number_cells(puzzle) -> dict[tuple[int, int], int]:
    """Return {(r,c): number} for every clue-start cell."""
    nums: dict[tuple[int, int], int] = {}
    for clue in puzzle.clues:
        # clue["cells"] is a flat index list; reconstruct (r,c) via first cell
        idx_to_coords: dict[int, tuple[int, int]] = {}
        i = 0
        for r in range(puzzle.rows):
            for c in range(puzzle.cols):
                if puzzle.grid[r][c] == ".":
                    idx_to_coords[i] = (r, c)
                    i += 1
        r, c = idx_to_coords[clue["cells"][0]]
        nums[(r, c)] = clue["number"]
    return nums


def render_html(puzzle_dir: Path) -> str:
    """Self-contained HTML page: grid table + across/down clue lists with answers."""
    puzzle = load_puzzle(puzzle_dir)
    state = load_state(puzzle_dir)
    coords_to_idx = _cells_by_coords(puzzle_dir)
    numbers = _number_cells(puzzle)

    # Grid
    rows_html = []
    for r in range(puzzle.rows):
        tds = []
        for c in range(puzzle.cols):
            if puzzle.grid[r][c] == "#":
                tds.append('<td class="black"></td>')
                continue
            idx = coords_to_idx[(r, c)]
            letter = state.cells[idx] or ""
            num = numbers.get((r, c))
            num_html = f'<span class="num">{num}</span>' if num else ""
            tds.append(f'<td>{num_html}{letter}</td>')
        rows_html.append("<tr>" + "".join(tds) + "</tr>")
    grid_html = '<table class="grid"><tbody>' + "".join(rows_html) + "</tbody></table>"

    # Clue lists
    def _clue_items(direction: str) -> str:
        items = []
        clues = sorted(
            (c for c in puzzle.clues if c["direction"] == direction),
            key=lambda c: c["number"],
        )
        for clue in clues:
            cid = clue["id"]
            cs = state.clues[cid]
            answer = cs.committed_answer or (
                cs.attempts[-1].answer if cs.attempts else ""
            )
            klass = "" if cs.committed else ' class="unsolved"'
            enum = ",".join(str(x) for x in clue["enumeration"])
            ans_html = f'<span class="answer">{answer}</span>' if answer else ""
            items.append(
                f'<li{klass}><b>{clue["number"]}</b>. {clue["text"]} ({enum}){ans_html}</li>'
            )
        return "\n".join(items)

    across_html = _clue_items("across")
    down_html = _clue_items("down")

    title = puzzle.title or "Crossword"
    total = len(puzzle.clues)
    committed = sum(1 for cs in state.clues.values() if cs.committed)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{_HTML_CSS}</style></head><body>
<h1>{title} — {committed}/{total} solved</h1>
{grid_html}
<div class="clues">
  <section><h2>Across</h2><ol>{across_html}</ol></section>
  <section><h2>Down</h2><ol>{down_html}</ol></section>
</div>
</body></html>
"""


if __name__ == "__main__":
    import sys

    from xsolver.cli import _render_main

    raise SystemExit(_render_main(sys.argv[1:]))
