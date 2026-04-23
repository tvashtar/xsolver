"""State and puzzle file management for xsolver."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PUZZLE_FILENAME = "puzzle.json"
STATE_FILENAME = "state.json"
HISTORY_FILENAME = "history.jsonl"


# --------------------------- dataclasses -------------------------------

@dataclass
class Puzzle:
    title: str
    rows: int
    cols: int
    grid: list[list[str]]          # "." white, "#" black
    # spec-shaped dicts (id, number, direction, text, enumeration, cells)
    clues: list[dict[str, Any]]


@dataclass
class Attempt:
    answer: str
    confidence: str                 # "high" | "medium" | "low"
    pattern_at_attempt: str         # e.g. "?A?K?"
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
