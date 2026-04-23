"""Crossword image parsing via OpenCV.

Stages (implemented across Tasks 18-21):
  18. detect_grid_bbox — find the grid rectangle in the image
  19. classify_cells — divide the grid into N×N cells, mark black/white
  20. number_cells — assign crossword numbering to white cells
  21. crop_clue_lists — extract clue-list sub-images for Claude to read
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


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
