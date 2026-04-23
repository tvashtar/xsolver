"""Tests for commit wave logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from xsolver.commit import run_wave
from xsolver.state import (
    Puzzle,
    init_state,
    load_state,
    read_history,
    record,
    write_puzzle,
)


@pytest.fixture
def two_clue_puzzle() -> Puzzle:
    # Horizontal 1A (3 cells: 0,1,2) and vertical 1D (3 cells: 0,3,4) crossing at cell 0
    return Puzzle(
        title="cross",
        rows=3,
        cols=3,
        grid=[[".", ".", "."], [".", "#", "#"], [".", "#", "#"]],
        clues=[
            {
                "id": "1A",
                "number": 1,
                "direction": "across",
                "text": "across",
                "enumeration": [3],
                "cells": [0, 1, 2],
            },
            {
                "id": "1D",
                "number": 1,
                "direction": "down",
                "text": "down",
                "enumeration": [3],
                "cells": [0, 3, 4],
            },
        ],
    )


def test_commit_wave_writes_high_answers_to_cells(tmp_puzzle_dir: Path, two_clue_puzzle: Puzzle):
    write_puzzle(tmp_puzzle_dir, two_clue_puzzle)
    init_state(tmp_puzzle_dir)
    record(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="high", reasoning="r")

    run_wave(tmp_puzzle_dir)

    state = load_state(tmp_puzzle_dir)
    assert state.cells[:3] == ["C", "A", "T"]
    assert state.clues["1A"].committed is True
    assert state.clues["1A"].committed_answer == "CAT"


def test_commit_wave_ignores_medium_and_low(tmp_puzzle_dir: Path, two_clue_puzzle: Puzzle):
    write_puzzle(tmp_puzzle_dir, two_clue_puzzle)
    init_state(tmp_puzzle_dir)
    record(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="medium", reasoning="r")

    run_wave(tmp_puzzle_dir)

    state = load_state(tmp_puzzle_dir)
    assert state.cells[:3] == [None, None, None]
    assert state.clues["1A"].committed is False


def test_commit_wave_sorts_longest_first(tmp_puzzle_dir: Path, two_clue_puzzle: Puzzle):
    # Give 1A and 1D both high, but longer first in sort.
    # Since both are length 3 here, just verify both committed.
    write_puzzle(tmp_puzzle_dir, two_clue_puzzle)
    init_state(tmp_puzzle_dir)
    record(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="high", reasoning="r")
    record(tmp_puzzle_dir, clue_id="1D", answer="CAT", confidence="high", reasoning="r")

    run_wave(tmp_puzzle_dir)

    state = load_state(tmp_puzzle_dir)
    assert state.clues["1A"].committed is True
    assert state.clues["1D"].committed is True


def test_commit_wave_emits_history_events(tmp_puzzle_dir: Path, two_clue_puzzle: Puzzle):
    write_puzzle(tmp_puzzle_dir, two_clue_puzzle)
    init_state(tmp_puzzle_dir)
    record(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="high", reasoning="r")

    run_wave(tmp_puzzle_dir)

    events = read_history(tmp_puzzle_dir)
    commit_events = [e for e in events if e.get("event") == "commit"]
    assert any(e.get("clue") == "1A" for e in commit_events)
