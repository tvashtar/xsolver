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


def test_commit_wave_auto_retracts_on_conflict(
    tmp_puzzle_dir: Path, two_clue_puzzle: Puzzle
):
    """
    1A and 1D share cell 0. If Claude records two high answers whose first
    letters disagree, both should be demoted and cells cleared.
    We must bypass the record()-time pattern validation to set this up,
    so we write state directly.
    """
    write_puzzle(tmp_puzzle_dir, two_clue_puzzle)
    init_state(tmp_puzzle_dir)

    from xsolver.state import Attempt, load_state, write_state

    state = load_state(tmp_puzzle_dir)
    state.clues["1A"].attempts.append(
        Attempt(answer="CAT", confidence="high", pattern_at_attempt="???", reasoning="x")
    )
    state.clues["1D"].attempts.append(
        Attempt(answer="DOG", confidence="high", pattern_at_attempt="???", reasoning="x")
    )
    write_state(tmp_puzzle_dir, state)

    summary = run_wave(tmp_puzzle_dir)

    # Both should be demoted to medium, neither committed, cells rolled back.
    after = load_state(tmp_puzzle_dir)
    assert after.clues["1A"].committed is False
    assert after.clues["1D"].committed is False
    assert after.clues["1A"].attempts[-1].confidence == "medium"
    assert after.clues["1D"].attempts[-1].confidence == "medium"
    assert all(c is None for c in after.cells[:5])
    assert "1A" in summary["retracted"] and "1D" in summary["retracted"]
    assert len(summary["conflicts"]) == 1

    events = read_history(tmp_puzzle_dir)
    assert any(e.get("event") == "conflict" for e in events)
    assert any(e.get("event") == "retract" and e.get("clue") == "1A" for e in events)
    assert any(e.get("event") == "retract" and e.get("clue") == "1D" for e in events)


def test_no_conflict_when_letters_agree(
    tmp_puzzle_dir: Path, two_clue_puzzle: Puzzle
):
    write_puzzle(tmp_puzzle_dir, two_clue_puzzle)
    init_state(tmp_puzzle_dir)
    # Both answers start with C — no conflict at cell 0
    record(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="high", reasoning="r")
    record(tmp_puzzle_dir, clue_id="1D", answer="COW", confidence="high", reasoning="r")

    summary = run_wave(tmp_puzzle_dir)

    assert summary["conflicts"] == []
    after = load_state(tmp_puzzle_dir)
    assert after.clues["1A"].committed is True
    assert after.clues["1D"].committed is True
