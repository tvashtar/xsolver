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


def _best_attempt(clue_state) -> tuple[str, str] | None:
    """(answer, confidence) of the highest-confidence attempt, tiebroken by recency.

    Commit wave only writes cells for `high` attempts, so we must look at the
    strongest tier available rather than the most recent one — otherwise a
    later `low` propose can shadow a committable `high` from the same clue
    and stall the puzzle.
    """
    if not clue_state.attempts:
        return None
    best = max(
        enumerate(clue_state.attempts),
        key=lambda ea: (CONFIDENCE_ORDER.get(ea[1].confidence, 0), ea[0]),
    )[1]
    return best.answer, best.confidence


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


def _conflict_for(
    puzzle: Puzzle, state: State, clue_id: str, answer: str
) -> tuple[int, str, str] | None:
    """If committing `answer` to `clue_id` would disagree with an existing letter,
    return (cell_idx, existing, proposed). Otherwise None."""
    clue = _find_clue(puzzle, clue_id)
    letters = _answer_letters(answer)
    for idx, letter in zip(clue["cells"], letters, strict=False):
        existing = state.cells[idx]
        if existing is not None and existing != letter:
            return idx, existing, letter
    return None


def _retract_clue(
    puzzle_dir: Path, puzzle: Puzzle, state: State, clue_id: str, reason: str
) -> None:
    """Remove clue's letters from cells, demote latest attempt to medium, log."""
    cs = state.clues[clue_id]
    if cs.committed:
        clue = _find_clue(puzzle, clue_id)
        for idx in clue["cells"]:
            # Only null out cells that aren't also committed by another clue.
            # Simpler approach: null everything owned by this clue, then let
            # any still-committed neighbours re-write their letters.
            state.cells[idx] = None
        cs.committed = False
        cs.committed_answer = None
    if cs.attempts:
        # Demote the highest-conf attempt (the one commit_wave picked) —
        # not blindly the latest, which may be a later low-tier propose.
        to_demote = max(
            enumerate(cs.attempts),
            key=lambda ea: (CONFIDENCE_ORDER.get(ea[1].confidence, 0), ea[0]),
        )[1]
        to_demote.confidence = "medium"
        to_demote.rejected_reason = reason
    append_history(
        puzzle_dir,
        {"event": "retract", "clue": clue_id, "reason": reason},
    )


def _reapply_committed(puzzle: Puzzle, state: State) -> None:
    """After a retract, any still-committed neighbours may have had their letters
    nulled out. Re-write them."""
    for clue_id, cs in state.clues.items():
        if cs.committed and cs.committed_answer:
            clue = _find_clue(puzzle, clue_id)
            letters = _answer_letters(cs.committed_answer)
            for idx, letter in zip(clue["cells"], letters, strict=False):
                state.cells[idx] = letter


def run_wave(puzzle_dir: Path) -> dict:
    with acquire_puzzle_lock(puzzle_dir):
        puzzle = load_puzzle(puzzle_dir)
        state = load_state(puzzle_dir)

        candidates = []
        for clue_id, cs in state.clues.items():
            if cs.committed:
                continue
            best = _best_attempt(cs)
            if best is None:
                continue
            answer, confidence = best
            if confidence != "high":
                continue
            clue = _find_clue(puzzle, clue_id)
            length = sum(clue["enumeration"])
            candidates.append((clue_id, answer, confidence, length))

        candidates.sort(
            key=lambda t: (CONFIDENCE_ORDER[t[2]], t[3]),
            reverse=True,
        )

        append_history(puzzle_dir, {"event": "phase-start", "phase": "commit"})

        committed: list[str] = []
        retracted: list[str] = []
        conflicts: list[dict] = []

        for clue_id, answer, _conf, _len in candidates:
            conflict = _conflict_for(puzzle, state, clue_id, answer)
            if conflict is None:
                _commit_one(puzzle_dir, puzzle, state, clue_id, answer)
                committed.append(clue_id)
                continue

            cell_idx, existing, proposed = conflict
            # Find the committed clue(s) occupying that cell
            occupiers = [
                cid
                for cid, cs in state.clues.items()
                if cs.committed and cell_idx in _find_clue(puzzle, cid)["cells"]
            ]
            conflict_event = {
                "event": "conflict",
                "cell": cell_idx,
                "proposed_clue": clue_id,
                "proposed_letter": proposed,
                "existing_letter": existing,
                "occupiers": occupiers,
            }
            append_history(puzzle_dir, conflict_event)
            conflicts.append(conflict_event)

            # Demote the newcomer (never committed, just its attempt tier).
            # Find the specific attempt whose answer matches — it may not be
            # the latest one now that commit uses the best-confidence attempt.
            newcomer_cs = state.clues[clue_id]
            for att in reversed(newcomer_cs.attempts):
                if att.answer == answer and att.confidence == "high":
                    att.confidence = "medium"
                    att.rejected_reason = (
                        f"conflict at cell {cell_idx}: would place {proposed!r} "
                        f"where {existing!r} is committed by {occupiers}"
                    )
                    break
            append_history(
                puzzle_dir,
                {"event": "retract", "clue": clue_id,
                 "reason": f"conflict with {occupiers}"},
            )
            retracted.append(clue_id)

            # Also retract every occupier at that cell
            for occ in occupiers:
                _retract_clue(
                    puzzle_dir, puzzle, state, occ,
                    reason=f"conflict with {clue_id} at cell {cell_idx}",
                )
                retracted.append(occ)

            _reapply_committed(puzzle, state)
            write_state(puzzle_dir, state)

        append_history(
            puzzle_dir,
            {
                "event": "phase-end",
                "phase": "commit",
                "committed": committed,
                "retracted": retracted,
                "conflicts": len(conflicts),
            },
        )
        return {"committed": committed, "retracted": retracted, "conflicts": conflicts}


if __name__ == "__main__":
    import sys

    from xsolver.cli import _commit_main

    raise SystemExit(_commit_main(sys.argv[1:]))
