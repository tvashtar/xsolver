"""Commit wave: write high-confidence answers into cells with overlap checks."""

from __future__ import annotations

from pathlib import Path

from xsolver.state import (
    Puzzle,
    State,
    _find_clue,
    acquire_puzzle_lock,
    append_history,
    load_puzzle,
    load_state,
    write_state,
)

CONFIDENCE_ORDER = {"high": 3, "medium": 2, "low": 1}


def _latest_attempt(clue_state) -> tuple[str, str] | None:
    """(answer, confidence) of the most recent attempt, or None."""
    if not clue_state.attempts:
        return None
    a = clue_state.attempts[-1]
    return a.answer, a.confidence


def _answer_letters(answer: str) -> list[str]:
    return [c for c in answer.upper() if c.isalpha()]


def _commit_one(puzzle_dir: Path, puzzle: Puzzle, state: State, clue_id: str, answer: str) -> None:
    clue = _find_clue(puzzle, clue_id)
    letters = _answer_letters(answer)
    for idx, letter in zip(clue["cells"], letters, strict=True):
        state.cells[idx] = letter
    state.clues[clue_id].committed = True
    state.clues[clue_id].committed_answer = answer
    write_state(puzzle_dir, state)
    append_history(
        puzzle_dir,
        {"event": "commit", "clue": clue_id, "answer": answer},
    )


def run_wave(puzzle_dir: Path) -> dict:
    """Commit every uncommitted clue whose latest attempt is `high`.

    Returns summary: {committed: [clue_ids], retracted: [], conflicts: []}.
    Conflict logic added in Task 13.
    """
    with acquire_puzzle_lock(puzzle_dir):
        puzzle = load_puzzle(puzzle_dir)
        state = load_state(puzzle_dir)

        candidates = []
        for clue_id, cs in state.clues.items():
            if cs.committed:
                continue
            latest = _latest_attempt(cs)
            if latest is None:
                continue
            answer, confidence = latest
            if confidence != "high":
                continue
            clue = _find_clue(puzzle, clue_id)
            length = sum(clue["enumeration"])
            candidates.append((clue_id, answer, confidence, length))

        # Sort: confidence DESC (tier), length DESC
        candidates.sort(
            key=lambda t: (CONFIDENCE_ORDER[t[2]], t[3]),
            reverse=True,
        )

        append_history(puzzle_dir, {"event": "phase-start", "phase": "commit"})
        committed: list[str] = []
        for clue_id, answer, _conf, _len in candidates:
            _commit_one(puzzle_dir, puzzle, state, clue_id, answer)
            committed.append(clue_id)
        append_history(
            puzzle_dir,
            {
                "event": "phase-end",
                "phase": "commit",
                "committed": committed,
            },
        )

        return {"committed": committed, "retracted": [], "conflicts": []}
