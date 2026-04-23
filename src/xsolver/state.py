"""State and puzzle file management for xsolver."""

from __future__ import annotations

import fcntl
import json
import os
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HISTORY_FILENAME = "history.jsonl"
LOCK_FILENAME = ".puzzle.lock"
PUZZLE_FILENAME = "puzzle.json"
STATE_FILENAME = "state.json"


# --------------------------- dataclasses -------------------------------


@dataclass
class Puzzle:
    title: str
    rows: int
    cols: int
    grid: list[list[str]]  # "." white, "#" black
    # spec-shaped dicts (id, number, direction, text, enumeration, cells)
    clues: list[dict[str, Any]]


@dataclass
class Attempt:
    answer: str
    confidence: str  # "high" | "medium" | "low"
    pattern_at_attempt: str  # e.g. "?A?K?"
    reasoning: str
    rejected_reason: str | None = None


@dataclass
class ClueState:
    committed: bool = False
    committed_answer: str | None = None
    attempts: list[Attempt] = field(default_factory=list)


@dataclass
class State:
    cells: list[str | None]
    iteration: int
    clues: dict[str, ClueState]


# --------------------------- paths -------------------------------------


def _path(puzzle_dir: Path, name: str) -> Path:
    return Path(puzzle_dir) / name


# --------------------------- puzzle ------------------------------------


def write_puzzle(puzzle_dir: Path, puzzle: Puzzle) -> None:
    puzzle_dir = Path(puzzle_dir)
    puzzle_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(_path(puzzle_dir, PUZZLE_FILENAME), asdict(puzzle))


def load_puzzle(puzzle_dir: Path) -> Puzzle:
    data = json.loads(_path(puzzle_dir, PUZZLE_FILENAME).read_text())
    return Puzzle(**data)


# --------------------------- state -------------------------------------


def init_state(puzzle_dir: Path) -> State:
    """Create initial empty state from an already-written puzzle."""
    puzzle = load_puzzle(puzzle_dir)
    # Count white cells to size the cells list
    # For simplicity, use one entry per distinct cell index referenced in clues.
    max_cell = max((idx for clue in puzzle.clues for idx in clue["cells"]), default=-1)
    cells: list[str | None] = [None] * (max_cell + 1)
    clues = {clue["id"]: ClueState() for clue in puzzle.clues}
    state = State(cells=cells, iteration=0, clues=clues)
    write_state(puzzle_dir, state)
    return state


def write_state(puzzle_dir: Path, state: State) -> None:
    payload = {
        "cells": state.cells,
        "iteration": state.iteration,
        "clues": {cid: asdict(cs) for cid, cs in state.clues.items()},
    }
    _atomic_write_json(_path(puzzle_dir, STATE_FILENAME), payload)


def load_state(puzzle_dir: Path) -> State:
    data = json.loads(_path(puzzle_dir, STATE_FILENAME).read_text())
    clues = {
        cid: ClueState(
            committed=cs["committed"],
            committed_answer=cs["committed_answer"],
            attempts=[Attempt(**a) for a in cs["attempts"]],
        )
        for cid, cs in data["clues"].items()
    }
    return State(cells=data["cells"], iteration=data["iteration"], clues=clues)


# --------------------------- atomic write ------------------------------


def _atomic_write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# --------------------------- history -----------------------------------


def append_history(puzzle_dir: Path, event: dict[str, Any]) -> None:
    """Append a JSON event line to history.jsonl. Auto-stamps `t`."""
    puzzle_dir = Path(puzzle_dir)
    puzzle_dir.mkdir(parents=True, exist_ok=True)
    stamped = {"t": datetime.now(UTC).isoformat(timespec="seconds"), **event}
    line = json.dumps(stamped) + "\n"
    with _path(puzzle_dir, HISTORY_FILENAME).open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()


def read_history(puzzle_dir: Path) -> list[dict[str, Any]]:
    path = _path(puzzle_dir, HISTORY_FILENAME)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --------------------------- record ------------------------------------

ALLOWED_CONFIDENCES = {"high", "medium", "low"}


def _find_clue(puzzle: Puzzle, clue_id: str) -> dict[str, Any]:
    for c in puzzle.clues:
        if c["id"] == clue_id:
            return c
    raise KeyError(f"clue {clue_id} not found")


def _normalise_answer(answer: str) -> str:
    """Uppercase and strip whitespace — but keep spaces inside phrases."""
    return " ".join(answer.upper().split())


def _letter_count(s: str) -> int:
    return sum(1 for c in s if c.isalpha())


def current_pattern(puzzle: Puzzle, state: State, clue_id: str) -> str:
    """Build a `?`/letter string for the clue's current cell letters."""
    clue = _find_clue(puzzle, clue_id)
    chars: list[str] = []
    for idx in clue["cells"]:
        v = state.cells[idx]
        chars.append(v if v else "?")
    return "".join(chars)


def record(
    puzzle_dir: Path,
    clue_id: str,
    answer: str,
    confidence: str,
    reasoning: str,
) -> None:
    """Record an attempt. Validates tier, length, and pattern compatibility."""
    if confidence not in ALLOWED_CONFIDENCES:
        raise ValueError(f"confidence {confidence!r} not in {sorted(ALLOWED_CONFIDENCES)}")

    with acquire_puzzle_lock(puzzle_dir):
        puzzle = load_puzzle(puzzle_dir)
        state = load_state(puzzle_dir)
        clue = _find_clue(puzzle, clue_id)

        normalised = _normalise_answer(answer)
        expected_len = sum(clue["enumeration"])
        actual_len = _letter_count(normalised)
        if actual_len != expected_len:
            raise ValueError(f"answer length {actual_len} != expected {expected_len} for {clue_id}")

        pattern = current_pattern(puzzle, state, clue_id)
        letters_only = "".join(c for c in normalised if c.isalpha())
        for i, (p, a) in enumerate(zip(pattern, letters_only, strict=False)):
            if p != "?" and p != a:
                raise ValueError(
                    f"pattern mismatch for {clue_id} at position {i}: "
                    f"grid={p!r}, answer letter={a!r}"
                )

        clue_state = state.clues[clue_id]
        attempt = Attempt(
            answer=normalised,
            confidence=confidence,
            pattern_at_attempt=pattern,
            reasoning=reasoning,
        )
        clue_state.attempts.append(attempt)
        state.iteration += 1
        write_state(puzzle_dir, state)
        append_history(
            puzzle_dir,
            {
                "event": "attempt",
                "clue": clue_id,
                "answer": normalised,
                "confidence": confidence,
                "pattern_at_attempt": pattern,
            },
        )


# --------------------------- lock --------------------------------------

# In-process guard: set of resolved lock-file paths currently held.
# fcntl.flock/lockf are reentrant within the same process on macOS, so we
# layer a threading-safe in-memory set on top to catch same-process contention.
_held_locks: set[str] = set()
_held_locks_mutex = threading.Lock()


@contextmanager
def acquire_puzzle_lock(puzzle_dir: Path):
    """Non-blocking exclusive lock over a puzzle working directory.

    Raises BlockingIOError if already locked by another process or context
    (including nested calls within the same process, which flock/lockf permit
    on macOS but we explicitly disallow via an in-memory guard).
    """
    puzzle_dir = Path(puzzle_dir)
    puzzle_dir.mkdir(parents=True, exist_ok=True)
    lock_path = str(_path(puzzle_dir, LOCK_FILENAME).resolve())

    with _held_locks_mutex:
        if lock_path in _held_locks:
            raise BlockingIOError(f"Puzzle lock already held: {lock_path}")
        _held_locks.add(lock_path)

    fh = open(lock_path, "a+")  # noqa: SIM115
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()
        with _held_locks_mutex:
            _held_locks.discard(lock_path)


if __name__ == "__main__":
    import sys

    from xsolver.cli import _state_main

    raise SystemExit(_state_main(sys.argv[1:]))
