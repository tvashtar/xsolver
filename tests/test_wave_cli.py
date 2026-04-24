"""Integration test for the `xsolver wave` one-shot command."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from xsolver.cli import main as cli_main
from xsolver.state import Puzzle, init_state, propose as do_propose, write_puzzle


@pytest.fixture
def puzzle() -> Puzzle:
    return Puzzle(
        title="t", rows=3, cols=3,
        grid=[[".", ".", "."], [".", "#", "#"], [".", "#", "#"]],
        clues=[
            {"id": "1A", "number": 1, "direction": "across",
             "text": "across", "enumeration": [3], "cells": [0, 1, 2]},
            {"id": "1D", "number": 1, "direction": "down",
             "text": "down", "enumeration": [3], "cells": [0, 3, 4]},
        ],
    )


def test_wave_runs_promote_commit_reassess_in_one_call(
    tmp_puzzle_dir: Path, puzzle: Puzzle, capsys
):
    write_puzzle(tmp_puzzle_dir, puzzle)
    init_state(tmp_puzzle_dir)
    do_propose(tmp_puzzle_dir, clue_id="1A", answer="CAT",
               confidence="high", reasoning="r")

    rc = cli_main(["wave", "--puzzle-dir", str(tmp_puzzle_dir)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)

    # Promoted 1A, committed it, no conflicts, no impossibilities yet
    assert "1A" in out["promoted"]
    assert "1A" in out["committed"]
    assert out["retracted"] == []
    assert out["conflicts"] == []
    # New buckets present
    assert "likely_proper_noun" in out
    assert "multi_word_unchecked" in out
    # Summary text included
    assert "Solved:" in out["summary"]


def test_wave_includes_next_batch_when_flag_set(
    tmp_puzzle_dir: Path, puzzle: Puzzle, capsys
):
    write_puzzle(tmp_puzzle_dir, puzzle)
    init_state(tmp_puzzle_dir)
    do_propose(tmp_puzzle_dir, clue_id="1A", answer="CAT",
               confidence="high", reasoning="r")

    cli_main(["wave", "--puzzle-dir", str(tmp_puzzle_dir), "--next-batch", "3"])
    out = json.loads(capsys.readouterr().out)
    assert "next_batch" in out
    # 1D is the only unsolved clue after 1A commits
    assert any(c["id"] == "1D" for c in out["next_batch"])
