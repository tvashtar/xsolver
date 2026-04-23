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
