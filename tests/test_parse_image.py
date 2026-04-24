from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from xsolver.parse_image import (
    GridValidationError,
    classify_cells,
    detect_grid_bbox,
    number_cells,
    parse_puzzle,
    reconstruct_from_clues,
    set_clues_from_json,
    validate_grid,
)


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


def test_number_cells_standard_case():
    grid = [
        [".", ".", ".", ".", "."],
        ["#", "#", ".", "#", "."],
        [".", ".", ".", ".", "."],
    ]
    numbered = number_cells(grid)
    # Row 0: cell 0 is 1 (starts both across+down), 2 is 2 (down), 4 is 3 (down)
    # Row 2: cell 0 is 4 (starts across), 1 continues down 1
    assert numbered[0][0] == 1
    assert numbered[0][1] is None  # no number (not start)
    assert numbered[0][2] == 2
    assert numbered[0][3] is None
    assert numbered[0][4] == 3
    assert numbered[1][0] is None  # black
    assert numbered[1][1] is None  # continues down 1 from above, no new number
    assert numbered[2][0] == 4


def test_number_cells_nothing_when_all_black():
    grid = [["#", "#"], ["#", "#"]]
    numbered = number_cells(grid)
    assert all(v is None for row in numbered for v in row)


def test_parse_puzzle_writes_puzzle_json(small_grid_image, tmp_path: Path):
    path, _ = small_grid_image
    out_dir = tmp_path / "out"
    parse_puzzle(
        image_path=path,
        output_dir=out_dir,
        rows=3,
        cols=3,
        title="synthetic-3x3",
        bbox=(0, 0, 300, 300),
    )
    pj = json.loads((out_dir / "puzzle.json").read_text())
    assert pj["title"] == "synthetic-3x3"
    assert pj["rows"] == 3 and pj["cols"] == 3
    # Clue list initially has clue ids but empty text (Claude audit fills later)
    assert all(c["text"] == "" for c in pj["clues"])
    # cells arrays are lists of indices
    assert all(isinstance(c["cells"], list) and len(c["cells"]) >= 1 for c in pj["clues"])


def test_validate_grid_accepts_symmetric_standard_grid():
    rows = [
        '.............##',
        '.#.#.#.#.#.#.#.',
        '.....#.........',
        '.#.#.#.#.#.#.#.',
        '..........#....',
        '.###.#.#.#.#.#.',
        '.......#.......',
        '.#.#.#####.#.#.',
        '.......#.......',
        '.#.#.#.#.#.###.',
        '....#..........',
        '.#.#.#.#.#.#.#.',
        '.........#.....',
        '.#.#.#.#.#.#.#.',
        '##.............',
    ]
    assert validate_grid([list(r) for r in rows]) == []


def test_validate_grid_flags_asymmetric_grid():
    grid = [[".", ".", "."], [".", ".", "."], [".", ".", "#"]]
    probs = validate_grid(grid)
    assert any("symmetric" in p for p in probs)


def test_validate_grid_flags_two_letter_runs():
    grid = [
        [".", ".", "#", ".", "."],
        [".", ".", "#", ".", "."],
        ["#", "#", "#", "#", "#"],
        [".", ".", "#", ".", "."],
        [".", ".", "#", ".", "."],
    ]
    probs = validate_grid(grid)
    assert probs, "expected 2-letter runs to be flagged"
    assert any("2 cells" in p for p in probs)


def test_reconstruct_from_clues_roundtrip_small():
    """Reconstruct a tiny 5x5 grid from its clue specs and verify symmetry."""
    specs = [
        {"number": 1, "direction": "across", "length": 5, "row": 0, "col": 0},
        {"number": 1, "direction": "down", "length": 5, "row": 0, "col": 0},
        {"number": 2, "direction": "down", "length": 5, "row": 0, "col": 4},
        {"number": 3, "direction": "across", "length": 5, "row": 4, "col": 0},
    ]
    grid = reconstruct_from_clues(5, 5, specs)
    assert grid[0] == list(".....")
    assert grid[4] == list(".....")
    assert grid[0][0] == "." and grid[0][4] == "."
    assert validate_grid(grid) == []


def test_reconstruct_from_clues_conflict_raises():
    specs = [
        {"number": 1, "direction": "across", "length": 3, "row": 0, "col": 0},
        # Overlapping down clue forcing a white cell where across ended black
        {"number": 2, "direction": "down", "length": 3, "row": 0, "col": 3},
    ]
    with pytest.raises(GridValidationError):
        reconstruct_from_clues(3, 5, specs)


def test_parse_puzzle_strict_raises_on_broken_grid(tmp_path: Path):
    """Feed a small asymmetric image and confirm strict validation kicks in."""
    img = Image.new("RGB", (200, 200), "white")
    pixels = img.load()
    # Paint only top-left cell black — produces an asymmetric 2x2
    for y in range(0, 100):
        for x in range(0, 100):
            pixels[x, y] = (0, 0, 0)
    path = tmp_path / "bad.png"
    img.save(path)
    with pytest.raises(GridValidationError):
        parse_puzzle(
            image_path=path,
            output_dir=tmp_path / "out",
            rows=2, cols=2,
            bbox=(0, 0, 200, 200),
        )


def test_set_clues_from_json_fills_text(small_grid_image, tmp_path: Path):
    path, _ = small_grid_image
    out_dir = tmp_path / "out"
    parse_puzzle(
        image_path=path, output_dir=out_dir, rows=3, cols=3,
        title="x", bbox=(0, 0, 300, 300),
    )
    # Build the minimal override dict the real skill would build from OCR
    current = json.loads((out_dir / "puzzle.json").read_text())
    updates = {c["id"]: {"text": f"clue {c['id']}", "enumeration": [len(c["cells"])]}
               for c in current["clues"]}
    set_clues_from_json(out_dir, updates)
    refreshed = json.loads((out_dir / "puzzle.json").read_text())
    assert all(c["text"].startswith("clue ") for c in refreshed["clues"])
    assert all(c["enumeration"] == [len(c["cells"])] for c in refreshed["clues"])
