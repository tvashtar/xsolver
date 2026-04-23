from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from xsolver.parse_image import detect_grid_bbox


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
