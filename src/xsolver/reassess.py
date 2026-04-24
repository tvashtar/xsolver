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


def list_impossible(puzzle_dir: Path) -> dict:
    """Find unsolved clues whose current pattern admits NO dictionary word.

    A clue is "impossible" if:
      - it's not committed
      - its pattern has ≥2 known letters (so it's meaningfully constrained)
      - its enumeration is a single word (multi-word phrases need per-segment
        checks that match_pattern doesn't do directly — flag those separately)
      - `match_pattern(current_pattern)` returns zero hits

    For each impossible clue, lists the COMMITTED crossing clues whose letters
    contribute to the pattern — one of them is almost certainly wrong and a
    candidate for `state retract`. The orchestrator picks which to retract
    (weakest wordplay is usually the right choice).

    Multi-word answers are returned under a separate `multi_word_unchecked`
    key so they're not silently skipped.
    """
    from xsolver.helpers import match_pattern

    with acquire_puzzle_lock(puzzle_dir):
        puzzle = load_puzzle(puzzle_dir)
        state = load_state(puzzle_dir)

    impossible: list[dict] = []
    multi_word_unchecked: list[dict] = []
    # Reverse-index: cell -> list of committed clue ids that cover it
    cell_committers: dict[int, list[str]] = {}
    for clue in puzzle.clues:
        cs = state.clues[clue["id"]]
        if cs.committed:
            for idx in clue["cells"]:
                cell_committers.setdefault(idx, []).append(clue["id"])

    for clue in puzzle.clues:
        cs = state.clues[clue["id"]]
        if cs.committed:
            continue
        pattern = current_pattern(puzzle, state, clue["id"])
        known = sum(1 for ch in pattern if ch != "?")
        if known == 0:
            continue  # nothing fixed yet; match_pattern would match everything
        # Which crossings contributed?
        crossings: list[dict] = []
        for pos, (idx, ch) in enumerate(zip(clue["cells"], pattern, strict=False)):
            if ch == "?":
                continue
            for other_id in cell_committers.get(idx, []):
                if other_id == clue["id"]:
                    continue
                crossings.append({"clue": other_id, "letter": ch, "position": pos})

        entry = {
            "clue": clue["id"],
            "pattern": pattern,
            "known": known,
            "total": len(clue["cells"]),
            "committed_crossings": crossings,
        }

        if len(clue["enumeration"]) != 1:
            multi_word_unchecked.append(entry)
            continue

        hits = match_pattern(pattern)
        if not hits:
            impossible.append(entry)

    return {"impossible": impossible, "multi_word_unchecked": multi_word_unchecked}


if __name__ == "__main__":
    import sys

    from xsolver.cli import _reassess_main

    raise SystemExit(_reassess_main(sys.argv[1:]))
