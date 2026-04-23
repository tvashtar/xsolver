from __future__ import annotations

from pathlib import Path

from xsolver.commit import run_wave
from xsolver.render import render_grid, render_summary
from xsolver.state import Puzzle, init_state, record, write_puzzle


def _mini_puzzle() -> Puzzle:
    return Puzzle(
        title="mini",
        rows=2,
        cols=3,
        grid=[[".", ".", "."], [".", "#", "."]],
        clues=[
            {
                "id": "1A",
                "number": 1,
                "direction": "across",
                "text": "across top",
                "enumeration": [3],
                "cells": [0, 1, 2],
            },
            {
                "id": "1D",
                "number": 1,
                "direction": "down",
                "text": "down left",
                "enumeration": [2],
                "cells": [0, 3],
            },
            {
                "id": "3D",
                "number": 3,
                "direction": "down",
                "text": "down right",
                "enumeration": [2],
                "cells": [2, 4],
            },
        ],
    )


def test_render_empty_grid(tmp_puzzle_dir: Path):
    write_puzzle(tmp_puzzle_dir, _mini_puzzle())
    init_state(tmp_puzzle_dir)
    out = render_grid(tmp_puzzle_dir)
    # Two rows, black square represented with ■ or #, empty whites with ·
    assert out.count("\n") >= 1  # multi-line
    assert "·" in out or "." in out  # some empty white representation


def test_render_grid_shows_committed_letters(tmp_puzzle_dir: Path):
    write_puzzle(tmp_puzzle_dir, _mini_puzzle())
    init_state(tmp_puzzle_dir)
    record(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="high", reasoning="r")
    run_wave(tmp_puzzle_dir)
    out = render_grid(tmp_puzzle_dir)
    assert "C" in out and "A" in out and "T" in out


def test_render_summary_lists_unsolved(tmp_puzzle_dir: Path):
    write_puzzle(tmp_puzzle_dir, _mini_puzzle())
    init_state(tmp_puzzle_dir)
    summary = render_summary(tmp_puzzle_dir)
    assert "1A" in summary
    assert "unsolved" in summary.lower() or "uncommitted" in summary.lower()
