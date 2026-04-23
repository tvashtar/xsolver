"""End-to-end plumbing test with scripted attempts (Claude stand-in)."""
from __future__ import annotations

import json
from pathlib import Path

from xsolver.commit import run_wave
from xsolver.reassess import list_stale
from xsolver.state import Puzzle, init_state, load_state, record, write_puzzle

FIXTURES = Path(__file__).parent / "fixtures" / "mini"


def _load_fixture(tmp_dir: Path) -> tuple[Puzzle, dict]:
    data = json.loads((FIXTURES / "puzzle.json").read_text())
    puzzle = Puzzle(**data)
    write_puzzle(tmp_dir, puzzle)
    init_state(tmp_dir)
    expected = json.loads((FIXTURES / "expected_cells.json").read_text())
    return puzzle, expected


def test_full_solve_wave_based(tmp_puzzle_dir: Path):
    """Script a Claude-free end-to-end solve of the 5x5 word square."""
    puzzle, expected = _load_fixture(tmp_puzzle_dir)

    # Phase 1: record all correct answers as high in clue-number order
    for clue in puzzle.clues:
        record(
            tmp_puzzle_dir,
            clue_id=clue["id"],
            answer=expected["solution"][clue["id"]],
            confidence="high",
            reasoning="scripted",
        )

    # Phase 2: commit wave
    summary = run_wave(tmp_puzzle_dir)
    assert summary["conflicts"] == []
    assert set(summary["committed"]) == set(expected["solution"].keys())

    state = load_state(tmp_puzzle_dir)
    assert state.cells == expected["cells"]

    # No stale clues after full solve
    assert list_stale(tmp_puzzle_dir) == []


def test_reassess_loop_with_one_initial_wrong_then_correction(tmp_puzzle_dir: Path):
    """Simulate a cross where an initial low guess gets corrected after commits."""
    puzzle, expected = _load_fixture(tmp_puzzle_dir)

    # Record 1A and 1D correctly at high
    record(tmp_puzzle_dir, clue_id="1A", answer="HEART", confidence="high", reasoning="r")
    record(tmp_puzzle_dir, clue_id="1D", answer="HEART", confidence="high", reasoning="r")
    # Record 2D as a wrong low guess against empty pattern
    record(tmp_puzzle_dir, clue_id="2D", answer="EERIE", confidence="low", reasoning="guess")

    run_wave(tmp_puzzle_dir)
    stale = list_stale(tmp_puzzle_dir)
    # 2D's pattern changed (first letter now E), so it should be in stale
    assert any(s["clue"] == "2D" for s in stale)


def test_resume_after_partial_commit(tmp_puzzle_dir: Path):
    """Simulate interrupt: write state partway, resume — reassess picks up change."""
    puzzle, expected = _load_fixture(tmp_puzzle_dir)
    record(tmp_puzzle_dir, clue_id="1A", answer="HEART", confidence="high", reasoning="r")
    run_wave(tmp_puzzle_dir)

    # Now simulate resume: no Claude calls, just check the state persisted
    state = load_state(tmp_puzzle_dir)
    assert state.clues["1A"].committed is True
    assert state.cells[0] == "H"
    # And that stale is empty for un-attempted clues without any letters yet
    # (but 2D has letter E at position 0 → stale should include 2D)
    stale = list_stale(tmp_puzzle_dir)
    assert any(s["clue"] == "2D" for s in stale)
