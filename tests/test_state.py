"""Tests for state/puzzle file handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from xsolver.state import (
    Puzzle,
    acquire_puzzle_lock,
    append_history,
    candidates_by_clue,
    init_state,
    load_puzzle,
    load_state,
    promote_candidates,
    propose,
    read_guesses,
    read_history,
    record,
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


def test_append_history_writes_line(tmp_puzzle_dir: Path):
    append_history(tmp_puzzle_dir, {"event": "commit", "clue": "1A"})
    append_history(tmp_puzzle_dir, {"event": "commit", "clue": "2A"})
    events = read_history(tmp_puzzle_dir)
    assert [e["event"] for e in events] == ["commit", "commit"]
    assert [e["clue"] for e in events] == ["1A", "2A"]
    # Each event got a timestamp auto-populated
    assert all("t" in e for e in events)


def test_puzzle_lock_blocks_concurrent_claim(tmp_puzzle_dir: Path):
    import pytest as _pytest

    with acquire_puzzle_lock(tmp_puzzle_dir):  # noqa: SIM117
        with _pytest.raises(BlockingIOError):
            with acquire_puzzle_lock(tmp_puzzle_dir):
                pass  # should not reach


# ---------------------------------------------------------------------------
# record() tests
# ---------------------------------------------------------------------------


def _setup(tmp_puzzle_dir: Path, tiny_puzzle: Puzzle):
    write_puzzle(tmp_puzzle_dir, tiny_puzzle)
    init_state(tmp_puzzle_dir)


def test_record_stores_attempt_with_derived_pattern(tmp_puzzle_dir: Path, tiny_puzzle: Puzzle):
    _setup(tmp_puzzle_dir, tiny_puzzle)
    record(
        tmp_puzzle_dir,
        clue_id="1A",
        answer="CAT",
        confidence="high",
        reasoning="test",
    )
    state = load_state(tmp_puzzle_dir)
    att = state.clues["1A"].attempts[-1]
    assert att.answer == "CAT"
    assert att.confidence == "high"
    # No cells filled yet, so pattern is all ?
    assert att.pattern_at_attempt == "???"


def test_record_rejects_wrong_length(tmp_puzzle_dir: Path, tiny_puzzle: Puzzle):
    _setup(tmp_puzzle_dir, tiny_puzzle)
    with pytest.raises(ValueError, match="length"):
        record(
            tmp_puzzle_dir,
            clue_id="1A",
            answer="CATS",
            confidence="high",
            reasoning="oops",
        )


def test_record_rejects_pattern_mismatch(tmp_puzzle_dir: Path, tiny_puzzle: Puzzle):
    _setup(tmp_puzzle_dir, tiny_puzzle)
    # Pre-fill cell 0 with "B", then try to record answer "CAT" (starts with C)
    state = load_state(tmp_puzzle_dir)
    state.cells[0] = "B"
    write_state(tmp_puzzle_dir, state)
    with pytest.raises(ValueError, match="pattern"):
        record(
            tmp_puzzle_dir,
            clue_id="1A",
            answer="CAT",
            confidence="high",
            reasoning="oops",
        )


def test_record_rejects_bad_confidence(tmp_puzzle_dir: Path, tiny_puzzle: Puzzle):
    _setup(tmp_puzzle_dir, tiny_puzzle)
    with pytest.raises(ValueError, match="confidence"):
        record(
            tmp_puzzle_dir,
            clue_id="1A",
            answer="CAT",
            confidence="maybe",
            reasoning="oops",
        )


def test_propose_appends_without_lock(tmp_puzzle_dir: Path, tiny_puzzle: Puzzle):
    _setup(tmp_puzzle_dir, tiny_puzzle)
    # Hold the puzzle lock — propose must still succeed
    with acquire_puzzle_lock(tmp_puzzle_dir):
        propose(
            tmp_puzzle_dir,
            clue_id="1A",
            answer="CAT",
            confidence="medium",
            reasoning="first guess",
        )
        propose(
            tmp_puzzle_dir,
            clue_id="1A",
            answer="BAT",
            confidence="low",
            reasoning="alt",
        )
    guesses = read_guesses(tmp_puzzle_dir)
    assert [g["answer"] for g in guesses] == ["CAT", "BAT"]
    assert [g["confidence"] for g in guesses] == ["medium", "low"]


def test_propose_rejects_wrong_length(tmp_puzzle_dir: Path, tiny_puzzle: Puzzle):
    _setup(tmp_puzzle_dir, tiny_puzzle)
    with pytest.raises(ValueError, match="length"):
        propose(
            tmp_puzzle_dir,
            clue_id="1A",
            answer="CATS",
            confidence="low",
            reasoning="oops",
        )


def test_candidates_by_clue_sorts_by_confidence_and_dedupes(
    tmp_puzzle_dir: Path, tiny_puzzle: Puzzle
):
    _setup(tmp_puzzle_dir, tiny_puzzle)
    propose(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="low", reasoning="a")
    propose(tmp_puzzle_dir, clue_id="1A", answer="BAT", confidence="medium", reasoning="b")
    propose(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="high", reasoning="upgraded")
    grouped = candidates_by_clue(tmp_puzzle_dir)
    # Latest-per-(clue,answer) wins, so CAT/high replaces CAT/low
    answers = [(g["answer"], g["confidence"]) for g in grouped["1A"]]
    assert answers == [("CAT", "high"), ("BAT", "medium")]


def test_promote_picks_highest_confidence_compatible_candidate(
    tmp_puzzle_dir: Path, tiny_puzzle: Puzzle
):
    _setup(tmp_puzzle_dir, tiny_puzzle)
    # Pre-fill the first cell with "C" so only CAT is pattern-compatible
    state = load_state(tmp_puzzle_dir)
    state.cells[0] = "C"
    write_state(tmp_puzzle_dir, state)

    propose(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="medium", reasoning="fits")
    propose(tmp_puzzle_dir, clue_id="1A", answer="BAT", confidence="high", reasoning="bat!")
    propose(tmp_puzzle_dir, clue_id="1A", answer="RAT", confidence="high", reasoning="rat!")
    promoted = promote_candidates(tmp_puzzle_dir)
    assert promoted == ["1A"]
    state = load_state(tmp_puzzle_dir)
    attempts = state.clues["1A"].attempts
    # BAT and RAT are higher-confidence but don't fit the C pattern — skipped.
    # CAT (medium, compatible) gets promoted.
    assert attempts[-1].answer == "CAT"


def test_promote_is_idempotent(tmp_puzzle_dir: Path, tiny_puzzle: Puzzle):
    _setup(tmp_puzzle_dir, tiny_puzzle)
    propose(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="high", reasoning="r")
    first = promote_candidates(tmp_puzzle_dir)
    second = promote_candidates(tmp_puzzle_dir)
    assert first == ["1A"]
    assert second == []  # already recorded; nothing new to promote


def test_retract_clears_non_shared_cells_and_uncommits(
    tmp_puzzle_dir: Path, tiny_puzzle: Puzzle
):
    _setup(tmp_puzzle_dir, tiny_puzzle)
    from xsolver.commit import run_wave
    from xsolver.state import retract

    record(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="high", reasoning="r")
    run_wave(tmp_puzzle_dir)
    state = load_state(tmp_puzzle_dir)
    assert state.cells == ["C", "A", "T"]
    assert state.clues["1A"].committed is True

    cleared = retract(tmp_puzzle_dir, clue_id="1A", reasoning="reconsidering")
    assert set(cleared) == {0, 1, 2}
    state = load_state(tmp_puzzle_dir)
    assert state.cells == [None, None, None]
    assert state.clues["1A"].committed is False
    assert state.clues["1A"].committed_answer is None
    # History event logged
    events = read_history(tmp_puzzle_dir)
    assert any(e.get("event") == "retract" and e.get("clue") == "1A" for e in events)


def test_promote_upgrades_confidence_for_same_answer(
    tmp_puzzle_dir: Path, tiny_puzzle: Puzzle
):
    """A later, higher-confidence propose of the same answer must promote again."""
    _setup(tmp_puzzle_dir, tiny_puzzle)
    propose(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="medium", reasoning="1st")
    assert promote_candidates(tmp_puzzle_dir) == ["1A"]

    propose(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="high", reasoning="2nd")
    assert promote_candidates(tmp_puzzle_dir) == ["1A"]

    state = load_state(tmp_puzzle_dir)
    confidences = [a.confidence for a in state.clues["1A"].attempts]
    # Both tiers recorded; commit wave will see the high one.
    assert "high" in confidences and "medium" in confidences


def test_record_appends_history_event(tmp_puzzle_dir: Path, tiny_puzzle: Puzzle):
    _setup(tmp_puzzle_dir, tiny_puzzle)
    record(
        tmp_puzzle_dir,
        clue_id="1A",
        answer="CAT",
        confidence="high",
        reasoning="test",
    )
    events = read_history(tmp_puzzle_dir)
    assert any(e.get("event") == "attempt" and e.get("clue") == "1A" for e in events)
