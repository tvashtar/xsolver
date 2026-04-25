from __future__ import annotations

from pathlib import Path

from xsolver.commit import run_wave
from xsolver.render import next_batch, render_grid, render_summary
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


def test_next_batch_picks_non_overlapping_clues(tmp_puzzle_dir: Path):
    # 1A overlaps both 1D (cell 0) and 3D (cell 2). Once 1A commits,
    # both 1D and 3D have a known letter — but they share NO cells with
    # each other, so the picker should return both in one batch.
    write_puzzle(tmp_puzzle_dir, _mini_puzzle())
    init_state(tmp_puzzle_dir)
    record(tmp_puzzle_dir, clue_id="1A", answer="CAT", confidence="high", reasoning="r")
    run_wave(tmp_puzzle_dir)

    batch = next_batch(tmp_puzzle_dir, n=10)
    ids = {r["id"] for r in batch}
    assert ids == {"1D", "3D"}  # both included, neither dropped for overlap


def test_next_batch_excludes_fully_open_clues_when_others_qualify(
    tmp_puzzle_dir: Path,
):
    # After committing 1A, 1D and 3D each have 1 known letter; if we add
    # a hypothetical 4th unsolved clue with 0 known letters, it would be
    # filtered out — but our mini puzzle only has 3 clues so we test the
    # symmetric case: with no commits, all clues are 0-known and the
    # fallback returns top-n anyway.
    write_puzzle(tmp_puzzle_dir, _mini_puzzle())
    init_state(tmp_puzzle_dir)
    # No commits → every clue is fully open. Fallback should return top-n
    # (we have 3 clues) so the batch isn't empty.
    batch = next_batch(tmp_puzzle_dir, n=5)
    assert len(batch) == 3  # fallback kicked in, all returned
