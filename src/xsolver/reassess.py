"""Identify clues whose letter pattern has changed since their last attempt."""
from __future__ import annotations

from pathlib import Path

from xsolver.state import (
    acquire_puzzle_lock,
    current_pattern,
    load_puzzle,
    load_state,
)


def list_stale(puzzle_dir: Path) -> list[dict]:
    """Return clues where:
      - the clue is not committed-high, AND
      - the latest attempt exists AND its pattern_at_attempt differs from current.

    Also return clues with no attempts at all but a non-empty current pattern
    (letters arrived from neighbours before this clue was ever tried).
    """
    with acquire_puzzle_lock(puzzle_dir):
        puzzle = load_puzzle(puzzle_dir)
        state = load_state(puzzle_dir)

        stale: list[dict] = []
        for clue_id, cs in state.clues.items():
            if cs.committed:
                continue
            pattern = current_pattern(puzzle, state, clue_id)
            if cs.attempts:
                last = cs.attempts[-1]
                if last.pattern_at_attempt != pattern:
                    stale.append(
                        {
                            "clue": clue_id,
                            "current_pattern": pattern,
                            "pattern_at_attempt": last.pattern_at_attempt,
                            "last_answer": last.answer,
                            "last_confidence": last.confidence,
                        }
                    )
            else:
                if any(c != "?" for c in pattern):
                    stale.append(
                        {
                            "clue": clue_id,
                            "current_pattern": pattern,
                            "pattern_at_attempt": None,
                            "last_answer": None,
                            "last_confidence": None,
                        }
                    )
        return stale
