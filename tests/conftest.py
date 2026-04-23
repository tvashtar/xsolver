"""Shared pytest fixtures."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_puzzle_dir(tmp_path: Path) -> Path:
    """A fresh empty working dir for per-puzzle state files."""
    d = tmp_path / "puzzle"
    d.mkdir()
    return d


@pytest.fixture
def mini_puzzle_json() -> dict:
    """Load the 5x5 non-cryptic fixture puzzle definition."""
    return json.loads((FIXTURES / "mini" / "puzzle.json").read_text())
