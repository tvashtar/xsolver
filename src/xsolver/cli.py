"""Command-line entry points invoked by the Claude skill via `python -m xsolver.<cmd>`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# --- state record --------------------------------------------------

def _state_main(argv: list[str]) -> int:
    from xsolver.state import record as do_record

    p = argparse.ArgumentParser(prog="python -m xsolver.state")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="Record a solve attempt")
    r.add_argument("--puzzle-dir", required=True)
    r.add_argument("--clue", required=True)
    r.add_argument("--answer", required=True)
    r.add_argument("--confidence", required=True, choices=["high", "medium", "low"])
    r.add_argument("--reasoning", required=True)

    args = p.parse_args(argv)
    if args.cmd == "record":
        try:
            do_record(
                Path(args.puzzle_dir),
                clue_id=args.clue,
                answer=args.answer,
                confidence=args.confidence,
                reasoning=args.reasoning,
            )
        except (ValueError, KeyError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"Recorded attempt for {args.clue}: {args.answer} ({args.confidence})")
        return 0
    return 1


# --- commit wave ---------------------------------------------------

def _commit_main(argv: list[str]) -> int:
    from xsolver.commit import run_wave

    p = argparse.ArgumentParser(prog="python -m xsolver.commit")
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wave")
    w.add_argument("--puzzle-dir", required=True)

    args = p.parse_args(argv)
    if args.cmd == "wave":
        summary = run_wave(Path(args.puzzle_dir))
        print(json.dumps(summary, indent=2))
        return 0
    return 1


# --- reassess ------------------------------------------------------

def _reassess_main(argv: list[str]) -> int:
    from xsolver.reassess import list_stale

    p = argparse.ArgumentParser(prog="python -m xsolver.reassess")
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--puzzle-dir", required=True)

    args = p.parse_args(argv)
    if args.cmd == "list":
        stale = list_stale(Path(args.puzzle_dir))
        print(json.dumps(stale, indent=2))
        return 0
    return 1


# --- render --------------------------------------------------------

def _render_main(argv: list[str]) -> int:
    from xsolver.render import render_grid, render_summary

    p = argparse.ArgumentParser(prog="python -m xsolver.render")
    p.add_argument("--puzzle-dir", required=True)
    p.add_argument("--summary", action="store_true")

    args = p.parse_args(argv)
    if args.summary:
        print(render_summary(Path(args.puzzle_dir)))
    else:
        print(render_grid(Path(args.puzzle_dir)))
    return 0


DISPATCH = {
    "state": _state_main,
    "commit": _commit_main,
    "reassess": _reassess_main,
    "render": _render_main,
}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m xsolver {state|commit|reassess|render} ...", file=sys.stderr)
        return 1
    sub = argv[0]
    if sub not in DISPATCH:
        print(f"unknown subcommand {sub!r}", file=sys.stderr)
        return 1
    return DISPATCH[sub](argv[1:])
