"""Tests for state/puzzle file handling."""
from __future__ import annotations

from pathlib import Path

import pytest

from xsolver.state import (
    Puzzle,
    init_state,
    load_puzzle,
    load_state,
    write_puzzle,
    write_state,
)


@pytest.fixture
def tiny_puzzle() -> Puzzle:
    # 3-cell horizontal strip: numbered cells 0,1,2 on a 1x3 grid
    return Puzzle(
        title="tiny",
        rows=1,
        cols=3,
        grid=[[".", ".", "."]],
        clues=[
            {
                "id": "1A",
                "number": 1,
                "direction": "across",
                "text": "test clue",
                "enumeration": [3],
                "cells": [0, 1, 2],
            }
        ],
    )


def test_write_and_load_puzzle_roundtrip(tmp_puzzle_dir: Path, tiny_puzzle: Puzzle):
    write_puzzle(tmp_puzzle_dir, tiny_puzzle)
    loaded = load_puzzle(tmp_puzzle_dir)
    assert loaded == tiny_puzzle


def test_init_state_creates_empty_state(tmp_puzzle_dir: Path, tiny_puzzle: Puzzle):
    write_puzzle(tmp_puzzle_dir, tiny_puzzle)
    state = init_state(tmp_puzzle_dir)
    assert state.cells == [None, None, None]
    assert state.iteration == 0
    assert "1A" in state.clues
    assert state.clues["1A"].committed is False
    assert state.clues["1A"].committed_answer is None
    assert state.clues["1A"].attempts == []


def test_write_and_load_state_roundtrip(tmp_puzzle_dir: Path, tiny_puzzle: Puzzle):
    write_puzzle(tmp_puzzle_dir, tiny_puzzle)
    state = init_state(tmp_puzzle_dir)
    state.cells[0] = "A"
    state.iteration = 3
    write_state(tmp_puzzle_dir, state)
    loaded = load_state(tmp_puzzle_dir)
    assert loaded.cells == ["A", None, None]
    assert loaded.iteration == 3


def test_load_state_raises_when_missing(tmp_puzzle_dir: Path):
    with pytest.raises(FileNotFoundError):
        load_state(tmp_puzzle_dir)
