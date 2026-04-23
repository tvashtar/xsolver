from __future__ import annotations

from pathlib import Path

import pytest

from xsolver.commit import run_wave
from xsolver.reassess import list_stale
from xsolver.state import (
    Puzzle,
    init_state,
    record,
    write_puzzle,
)


@pytest.fixture
def two_clue_puzzle() -> Puzzle:
    return Puzzle(
        title="cross",
        rows=3,
        cols=3,
        grid=[[".", ".", "."], [".", "#", "#"], [".", "#", "#"]],
        clues=[
            {"id": "1A", "number": 1, "direction": "across", "text": "across",
             "enumeration": [3], "cells": [0, 1, 2]},
            {"id": "1D", "number": 1, "direction": "down", "text": "down",
             "enumeration": [3], "cells": [0, 3, 4]},
        ],
    )


def test_no_stale_after_initial(tmp_puzzle_dir: Path, two_clue_puzzle: Puzzle):
    write_puzzle(tmp_puzzle_dir, two_clue_puzzle)
    init_state(tmp_puzzle_dir)
    record(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="high", reasoning="r")
    # No commits yet; patterns haven't changed since attempts recorded.
    assert list_stale(tmp_puzzle_dir) == []


def test_stale_appears_after_committed_letters_flow(
    tmp_puzzle_dir: Path, two_clue_puzzle: Puzzle
):
    write_puzzle(tmp_puzzle_dir, two_clue_puzzle)
    init_state(tmp_puzzle_dir)
    # Record 1D against empty pattern, record 1A high, commit 1A → 1D pattern changes
    record(tmp_puzzle_dir, clue_id="1D", answer="COW", confidence="medium", reasoning="r")
    record(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="high", reasoning="r")
    run_wave(tmp_puzzle_dir)
    stale = list_stale(tmp_puzzle_dir)
    assert any(s["clue"] == "1D" for s in stale)
    s = next(s for s in stale if s["clue"] == "1D")
    assert s["pattern_at_attempt"] == "???"
    assert s["current_pattern"].startswith("C")


def test_committed_high_not_in_stale_list(
    tmp_puzzle_dir: Path, two_clue_puzzle: Puzzle
):
    write_puzzle(tmp_puzzle_dir, two_clue_puzzle)
    init_state(tmp_puzzle_dir)
    record(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="high", reasoning="r")
    record(tmp_puzzle_dir, clue_id="1D", answer="COW", confidence="high", reasoning="r")
    run_wave(tmp_puzzle_dir)
    stale = list_stale(tmp_puzzle_dir)
    assert all(s["clue"] != "1A" for s in stale)
    assert all(s["clue"] != "1D" for s in stale)
