"""Crossword image parsing via OpenCV.

Stages (implemented across Tasks 18-21):
  18. detect_grid_bbox — find the grid rectangle in the image
  19. classify_cells — divide the grid into N×N cells, mark black/white
  20. number_cells — assign crossword numbering to white cells
  21. crop_clue_lists — extract clue-list sub-images for Claude to read
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from xsolver.state import Puzzle, write_puzzle


def _load_gray(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"could not load image {path}")
    return img


def detect_grid_bbox(image_path: Path) -> tuple[int, int, int, int]:
    """Locate the crossword grid in the image.

    Strategy: threshold, find external contours, pick the largest roughly-square
    contour by bounding-rect aspect ratio (0.8..1.25).
    Returns (x, y, w, h).
    """
    gray = _load_gray(image_path)
    # Invert so grid lines become foreground
    _, bin_img = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(bin_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("no contours found — is the image blank or inverted?")

    def _score(contour):
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        ratio = w / h if h else 0
        squarish = 0.8 <= ratio <= 1.25
        return (squarish, area)

    best = max(contours, key=_score)
    return cv2.boundingRect(best)


def classify_cells(
    image_path: Path,
    bbox: tuple[int, int, int, int],
    rows: int,
    cols: int,
    black_threshold: float = 0.5,
) -> list[list[str]]:
    """Divide the grid bbox into rows×cols equal cells and classify each.

    Returns a 2D list: "." for white, "#" for black.
    Classification rule: mean intensity of the cell's interior (cropped to
    avoid edges) below `black_threshold * 255`.
    """
    gray = _load_gray(image_path)
    x, y, w, h = bbox
    grid = gray[y : y + h, x : x + w]

    cell_w = w / cols
    cell_h = h / rows

    output = []
    for r in range(rows):
        row = []
        for c in range(cols):
            # 20% inset to avoid grid lines
            cx0 = int(c * cell_w + 0.2 * cell_w)
            cx1 = int((c + 1) * cell_w - 0.2 * cell_w)
            cy0 = int(r * cell_h + 0.2 * cell_h)
            cy1 = int((r + 1) * cell_h - 0.2 * cell_h)
            cell = grid[cy0:cy1, cx0:cx1]
            mean = float(cell.mean()) if cell.size else 255.0
            row.append("#" if mean < black_threshold * 255 else ".")
        output.append(row)
    return output


def _build_clue_list(
    grid: list[list[str]],
    numbered: list[list[int | None]],
) -> list[dict]:
    """Build the minimal clue list (no text yet): id, number, direction, cells."""
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    # Flat index for white cells in reading order
    idx_of: dict[tuple[int, int], int] = {}
    idx = 0
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] == ".":
                idx_of[(r, c)] = idx
                idx += 1

    clues: list[dict] = []
    for r in range(rows):
        for c in range(cols):
            n = numbered[r][c]
            if n is None:
                continue
            # Across run?
            if (c == 0 or grid[r][c - 1] == "#") and (
                c + 1 < cols and grid[r][c + 1] == "."
            ):
                cells = []
                cc = c
                while cc < cols and grid[r][cc] == ".":
                    cells.append(idx_of[(r, cc)])
                    cc += 1
                clues.append({
                    "id": f"{n}A",
                    "number": n,
                    "direction": "across",
                    "text": "",
                    "enumeration": [len(cells)],
                    "cells": cells,
                })
            # Down run?
            if (r == 0 or grid[r - 1][c] == "#") and (
                r + 1 < rows and grid[r + 1][c] == "."
            ):
                cells = []
                rr = r
                while rr < rows and grid[rr][c] == ".":
                    cells.append(idx_of[(rr, c)])
                    rr += 1
                clues.append({
                    "id": f"{n}D",
                    "number": n,
                    "direction": "down",
                    "text": "",
                    "enumeration": [len(cells)],
                    "cells": cells,
                })
    return clues


def number_cells(grid: list[list[str]]) -> list[list[int | None]]:
    """Assign crossword numbering to white cells.

    A cell gets a number if it starts an Across run (cell to the left is
    black or out of bounds, cell to the right is white and in bounds)
    OR a Down run (cell above is black/out of bounds, cell below is white
    and in bounds).
    """
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    numbered: list[list[int | None]] = [[None] * cols for _ in range(rows)]
    next_num = 1
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] != ".":
                continue
            starts_across = (c == 0 or grid[r][c - 1] == "#") and (
                c + 1 < cols and grid[r][c + 1] == "."
            )
            starts_down = (r == 0 or grid[r - 1][c] == "#") and (
                r + 1 < rows and grid[r + 1][c] == "."
            )
            if starts_across or starts_down:
                numbered[r][c] = next_num
                next_num += 1
    return numbered


class GridValidationError(ValueError):
    """Raised when a parsed grid fails structural sanity checks."""


def validate_grid(
    grid: list[list[str]], min_word_length: int = 3
) -> list[str]:
    """Structural sanity-checks on a parsed crossword grid.

    Returns a list of problem descriptions (empty = grid looks fine). Fast
    checks that catch the usual parser failures (drifted sampling, wrong bbox):

    - 180° rotational symmetry (standard British/American cryptic convention).
    - No white run (across or down) shorter than `min_word_length` cells —
      cryptics never have 1- or 2-letter words.
    """
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    problems: list[str] = []

    # Symmetry
    asym = []
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] != grid[rows - 1 - r][cols - 1 - c]:
                asym.append((r, c))
    if asym:
        problems.append(
            f"grid is not 180°-rotationally symmetric ({len(asym)} mismatched cells; "
            f"first at {asym[0]})"
        )

    # Minimum run length (across)
    for r in range(rows):
        c = 0
        while c < cols:
            if grid[r][c] == ".":
                start = c
                while c < cols and grid[r][c] == ".":
                    c += 1
                run = c - start
                if 1 < run < min_word_length:
                    problems.append(
                        f"across run at row {r} col {start} is {run} cells "
                        f"(< {min_word_length})"
                    )
            else:
                c += 1
    # Minimum run length (down)
    for c in range(cols):
        r = 0
        while r < rows:
            if grid[r][c] == ".":
                start = r
                while r < rows and grid[r][c] == ".":
                    r += 1
                run = r - start
                if 1 < run < min_word_length:
                    problems.append(
                        f"down run at col {c} row {start} is {run} cells "
                        f"(< {min_word_length})"
                    )
            else:
                r += 1

    return problems


def _classify_with_auto_tune(
    image_path: Path,
    bbox: tuple[int, int, int, int],
    rows: int,
    cols: int,
) -> tuple[list[list[str]], tuple[int, int, int, int]]:
    """Try the given bbox; if validation fails, search small perturbations.

    The parser's most common failure mode is a bbox that includes a few pixels
    of page margin — cell-centre sampling then drifts across rows until it lands
    on grid lines. We try shrinking the bbox by up to ~cell_size/2 on each side
    and pick the first candidate that passes validate_grid().
    """
    grid = classify_cells(image_path, bbox=bbox, rows=rows, cols=cols)
    if not validate_grid(grid):
        return grid, bbox

    x, y, w, h = bbox
    cell_w, cell_h = w / cols, h / rows
    # Try insets in small steps, up to half a cell
    max_inset_x = int(cell_w * 0.5)
    max_inset_y = int(cell_h * 0.5)
    step_x = max(1, max_inset_x // 6)
    step_y = max(1, max_inset_y // 6)

    best_grid, best_bbox, best_problems = grid, bbox, validate_grid(grid)
    for dx_l in range(0, max_inset_x + 1, step_x):
        for dx_r in range(0, max_inset_x + 1, step_x):
            for dy_t in range(0, max_inset_y + 1, step_y):
                for dy_b in range(0, max_inset_y + 1, step_y):
                    nb = (x + dx_l, y + dy_t, w - dx_l - dx_r, h - dy_t - dy_b)
                    if nb[2] <= 0 or nb[3] <= 0:
                        continue
                    g = classify_cells(image_path, bbox=nb, rows=rows, cols=cols)
                    p = validate_grid(g)
                    if not p:
                        return g, nb
                    if len(p) < len(best_problems):
                        best_grid, best_bbox, best_problems = g, nb, p
    return best_grid, best_bbox


def parse_puzzle(
    image_path: Path,
    output_dir: Path,
    rows: int,
    cols: int,
    title: str = "",
    bbox: tuple[int, int, int, int] | None = None,
    strict: bool = True,
    auto_tune: bool = True,
) -> None:
    """Run Phase 0 on an image: grid bbox → cell classification → numbering →
    write puzzle.json with empty clue text (to be filled by Claude audit step).

    If `strict` (default), raises `GridValidationError` when the classified grid
    fails `validate_grid()`. Pass `strict=False` to write a known-bad grid for
    debugging.

    If `auto_tune` (default), perturbs the bbox by up to half a cell on each
    side to try to recover from a slightly-off bbox before giving up.
    """
    if bbox is None:
        bbox = detect_grid_bbox(image_path)
    if auto_tune:
        grid, bbox = _classify_with_auto_tune(image_path, bbox, rows, cols)
    else:
        grid = classify_cells(image_path, bbox=bbox, rows=rows, cols=cols)
    problems = validate_grid(grid)
    if problems and strict:
        raise GridValidationError(
            "parsed grid failed validation — the bbox or cell classification "
            "is wrong. Fall back to reconstruct_from_clues(). Problems:\n  - "
            + "\n  - ".join(problems)
        )
    numbered = number_cells(grid)
    clues = _build_clue_list(grid, numbered)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    puzzle = Puzzle(title=title, rows=rows, cols=cols, grid=grid, clues=clues)
    write_puzzle(output_dir, puzzle)

    # Save the cropped clue-list region for the Claude audit step
    crop_clue_lists(image_path, output_dir, grid_bbox=bbox)


def crop_clue_lists(
    image_path: Path, output_dir: Path, grid_bbox: tuple[int, int, int, int]
) -> None:
    """Crop the image region to the right of the grid (heuristic: assume clues
    live in the rightmost slice of the page). Saves clues.png in output_dir.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(image_path)
    h, w = img.shape[:2]
    gx, gy, gw, gh = grid_bbox
    # Take everything to the right of the grid
    x0 = gx + gw + 5
    if x0 >= w:
        # No space — skip; the caller can fall back to the whole image
        return
    clue_region = img[:, x0:]
    cv2.imwrite(str(Path(output_dir) / "clues.png"), clue_region)


def reconstruct_from_clues(
    rows: int,
    cols: int,
    clue_specs: list[dict],
) -> list[list[str]]:
    """Reconstruct a crossword grid when image parsing fails.

    `clue_specs` is a list of per-clue records:
        {"number": N, "direction": "across"|"down", "length": L,
         "row": R, "col": C}
    where (R, C) is the 0-indexed position of the numbered cell in the grid
    (the digit printed in its top-left corner). Claude reads these positions
    from the image — they are usually trivially identifiable by eye.

    The grid is determined as follows:
      - Every cell covered by an across run (r, c..c+L-1) or down run
        (r..r+L-1, c) is white.
      - Every cell immediately before/after a run (within bounds) is black.
      - Remaining unknown cells default to black, then the grid is reflected
        under 180° symmetry to fill any gaps.

    Raises `GridValidationError` if the result fails `validate_grid()`.
    """
    grid: list[list[str]] = [["?"] * cols for _ in range(rows)]

    def mark(r: int, c: int, s: str) -> None:
        if not (0 <= r < rows and 0 <= c < cols):
            return
        if grid[r][c] == "?":
            grid[r][c] = s
        elif grid[r][c] != s:
            raise GridValidationError(
                f"clue conflict at ({r},{c}): already {grid[r][c]!r}, tried {s!r}"
            )

    for spec in clue_specs:
        n = int(spec["number"])
        d = spec["direction"]
        L = int(spec["length"])
        r = int(spec["row"])
        c = int(spec["col"])
        if d == "across":
            for k in range(L):
                mark(r, c + k, ".")
            mark(r, c - 1, "#")
            mark(r, c + L, "#")
        elif d == "down":
            for k in range(L):
                mark(r + k, c, ".")
            mark(r - 1, c, "#")
            mark(r + L, c, "#")
        else:
            raise ValueError(f"clue {n}: direction must be across/down, got {d}")

    # Fill unknowns via 180° symmetry
    for r in range(rows):
        for c in range(cols):
            mr, mc = rows - 1 - r, cols - 1 - c
            a, b = grid[r][c], grid[mr][mc]
            if a == b:
                continue
            if a == "?":
                grid[r][c] = b
            elif b == "?":
                grid[mr][mc] = a
            else:
                raise GridValidationError(
                    f"symmetry conflict: ({r},{c})={a!r} vs ({mr},{mc})={b!r}"
                )
    # Remaining unknowns are cells not touched by any clue → black.
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] == "?":
                grid[r][c] = "#"

    problems = validate_grid(grid)
    if problems:
        raise GridValidationError(
            "reconstructed grid failed validation:\n  - " + "\n  - ".join(problems)
        )
    return grid


def build_puzzle_from_clues(
    output_dir: Path,
    rows: int,
    cols: int,
    clue_specs: list[dict],
    title: str = "",
) -> None:
    """Build puzzle.json purely from the clue list (no image needed).

    `clue_specs` is a list of `{"number": int, "direction": "across"|"down",
    "length": int, "text": str?, "enumeration": [int]?}`. The grid is
    reconstructed by `reconstruct_from_clues`; text/enumeration are copied
    through when provided.
    """
    grid = reconstruct_from_clues(rows, cols, clue_specs)
    numbered = number_cells(grid)
    clues = _build_clue_list(grid, numbered)
    text_by_id = {
        f"{s['number']}{'A' if s['direction'] == 'across' else 'D'}": s
        for s in clue_specs
    }
    for c in clues:
        s = text_by_id.get(c["id"])
        if s is None:
            continue
        if "text" in s:
            c["text"] = s["text"]
        if "enumeration" in s:
            c["enumeration"] = list(s["enumeration"])
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    puzzle = Puzzle(title=title, rows=rows, cols=cols, grid=grid, clues=clues)
    write_puzzle(output_dir, puzzle)


def set_clues_from_json(output_dir: Path, updates: dict[str, dict]) -> None:
    """Apply a {clue_id: {text, enumeration}} override to puzzle.json."""
    pj_path = Path(output_dir) / "puzzle.json"
    data = json.loads(pj_path.read_text())
    by_id = {c["id"]: c for c in data["clues"]}
    for cid, upd in updates.items():
        if cid not in by_id:
            raise KeyError(f"clue id {cid} not in puzzle")
        if "text" in upd:
            by_id[cid]["text"] = upd["text"]
        if "enumeration" in upd:
            by_id[cid]["enumeration"] = list(upd["enumeration"])
    pj_path.write_text(json.dumps(data, indent=2))


if __name__ == "__main__":
    import sys

    from xsolver.cli import _parse_image_main

    raise SystemExit(_parse_image_main(sys.argv[1:]))
