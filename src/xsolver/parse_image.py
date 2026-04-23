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


def parse_puzzle(
    image_path: Path,
    output_dir: Path,
    rows: int,
    cols: int,
    title: str = "",
    bbox: tuple[int, int, int, int] | None = None,
) -> None:
    """Run Phase 0 on an image: grid bbox → cell classification → numbering →
    write puzzle.json with empty clue text (to be filled by Claude audit step).
    """
    if bbox is None:
        bbox = detect_grid_bbox(image_path)
    grid = classify_cells(image_path, bbox=bbox, rows=rows, cols=cols)
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
