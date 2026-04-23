from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from xsolver.parse_image import classify_cells, detect_grid_bbox


@pytest.fixture
def synthetic_grid(tmp_path: Path) -> Path:
    """Make a 300x300 image with a black 200x200 box centred on it."""
    img = Image.new("RGB", (300, 300), "white")
    pixels = img.load()
    for y in range(50, 250):
        for x in range(50, 250):
            pixels[x, y] = (0, 0, 0)
    # Add a ring of white inside so it's a rectangle outline
    for y in range(55, 245):
        for x in range(55, 245):
            pixels[x, y] = (255, 255, 255)
    path = tmp_path / "grid.png"
    img.save(path)
    return path


def test_detect_grid_bbox_returns_expected_rectangle(synthetic_grid: Path):
    bbox = detect_grid_bbox(synthetic_grid)
    # Expect a rectangle close to (50,50) - (250,250), within ±3 pixels
    x, y, w, h = bbox
    assert abs(x - 50) <= 3
    assert abs(y - 50) <= 3
    assert abs(w - 200) <= 3
    assert abs(h - 200) <= 3


@pytest.fixture
def small_grid_image(tmp_path: Path) -> tuple[Path, list[list[str]]]:
    """Render a 3x3 grid where the centre cell is black.
    Grid size: 300x300, cell size 100x100."""
    img = Image.new("RGB", (300, 300), "white")
    pixels = img.load()
    # Outer grid lines at x=0, 100, 200, 300 — draw as thin black
    for i in (0, 100, 200, 299):
        for y in range(300):
            pixels[i, y] = (0, 0, 0)
            pixels[y, i] = (0, 0, 0)
    # Fill centre cell (row 1, col 1: pixels 101..199, 101..199) as black
    for y in range(101, 199):
        for x in range(101, 199):
            pixels[x, y] = (0, 0, 0)

    path = tmp_path / "3x3.png"
    img.save(path)
    expected = [
        [".", ".", "."],
        [".", "#", "."],
        [".", ".", "."],
    ]
    return path, expected


def test_classify_3x3_grid(small_grid_image):
    path, expected = small_grid_image
    # bbox is the whole image (first contour we find)
    grid = classify_cells(path, bbox=(0, 0, 300, 300), rows=3, cols=3)
    assert grid == expected
