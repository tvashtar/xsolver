"""Command-line entry points invoked by the Claude skill via `python -m xsolver.<cmd>`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# --- state record --------------------------------------------------

def _state_main(argv: list[str]) -> int:
    from xsolver.state import (
        candidates_by_clue,
        promote_candidates,
        propose as do_propose,
        record as do_record,
        retract as do_retract,
    )

    p = argparse.ArgumentParser(prog="python -m xsolver.state")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="Record a solve attempt (locked, strict)")
    r.add_argument("--puzzle-dir", required=True)
    r.add_argument("--clue", required=True)
    r.add_argument("--answer", required=True)
    r.add_argument("--confidence", required=True, choices=["high", "medium", "low"])
    r.add_argument("--reasoning", required=True)

    pr = sub.add_parser(
        "propose",
        help="Append a candidate to guesses.jsonl (lock-free, parallel-safe)",
    )
    pr.add_argument("--puzzle-dir", required=True)
    pr.add_argument("--clue", required=True)
    pr.add_argument("--answer", required=True)
    pr.add_argument("--confidence", required=True, choices=["high", "medium", "low"])
    pr.add_argument("--reasoning", required=True)

    cd = sub.add_parser("candidates", help="List candidates (guesses.jsonl contents)")
    cd.add_argument("--puzzle-dir", required=True)
    cd.add_argument("--clue", help="Filter to a single clue id")

    pm = sub.add_parser(
        "promote",
        help="Promote compatible candidates from guesses.jsonl into state.json",
    )
    pm.add_argument("--puzzle-dir", required=True)

    rt = sub.add_parser(
        "retract",
        help="Uncommit a clue; clears its non-shared cells",
    )
    rt.add_argument("--puzzle-dir", required=True)
    rt.add_argument("--clue", required=True)
    rt.add_argument("--reasoning", default="")

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
    if args.cmd == "propose":
        try:
            do_propose(
                Path(args.puzzle_dir),
                clue_id=args.clue,
                answer=args.answer,
                confidence=args.confidence,
                reasoning=args.reasoning,
            )
        except (ValueError, KeyError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"Proposed {args.clue}: {args.answer} ({args.confidence})")
        return 0
    if args.cmd == "candidates":
        grouped = candidates_by_clue(Path(args.puzzle_dir))
        if args.clue:
            out = {args.clue: grouped.get(args.clue, [])}
        else:
            out = grouped
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "promote":
        promoted = promote_candidates(Path(args.puzzle_dir))
        print(json.dumps({"promoted": promoted}, indent=2))
        return 0
    if args.cmd == "retract":
        cleared = do_retract(
            Path(args.puzzle_dir), clue_id=args.clue, reasoning=args.reasoning
        )
        print(json.dumps({"clue": args.clue, "cleared_cells": cleared}, indent=2))
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
    from xsolver.render import render_grid, render_html, render_summary

    p = argparse.ArgumentParser(prog="python -m xsolver.render")
    p.add_argument("--puzzle-dir", required=True)
    p.add_argument("--summary", action="store_true")
    p.add_argument(
        "--html", action="store_true",
        help="Emit a self-contained HTML page (grid + clue list with answers)",
    )

    args = p.parse_args(argv)
    if args.html:
        print(render_html(Path(args.puzzle_dir)))
    elif args.summary:
        print(render_summary(Path(args.puzzle_dir)))
    else:
        print(render_grid(Path(args.puzzle_dir)))
    return 0


def _parse_image_main(argv: list[str]) -> int:
    from xsolver.parse_image import (
        GridValidationError,
        build_puzzle_from_clues,
        parse_puzzle,
        set_clues_from_json,
    )

    p = argparse.ArgumentParser(prog="python -m xsolver.parse_image")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("parse")
    pa.add_argument("--image", required=True)
    pa.add_argument("--output-dir", required=True)
    pa.add_argument("--rows", type=int, required=True)
    pa.add_argument("--cols", type=int, required=True)
    pa.add_argument("--title", default="")
    pa.add_argument(
        "--no-strict", action="store_true",
        help="Skip grid validation (for debugging a known-bad parse)",
    )

    sc = sub.add_parser("set-clues")
    sc.add_argument("--output-dir", required=True)
    sc.add_argument(
        "--updates-json", required=True,
        help="Path to JSON file mapping clue_id -> {text, enumeration}",
    )

    rc = sub.add_parser(
        "reconstruct",
        help="Build puzzle.json from a clue-specs JSON when image parsing fails",
    )
    rc.add_argument("--output-dir", required=True)
    rc.add_argument("--rows", type=int, required=True)
    rc.add_argument("--cols", type=int, required=True)
    rc.add_argument("--title", default="")
    rc.add_argument(
        "--specs-json", required=True,
        help="Path to JSON file: list of {number, direction, length, row, col, "
             "text?, enumeration?}",
    )

    args = p.parse_args(argv)
    if args.cmd == "parse":
        try:
            parse_puzzle(
                image_path=Path(args.image),
                output_dir=Path(args.output_dir),
                rows=args.rows,
                cols=args.cols,
                title=args.title,
                strict=not args.no_strict,
            )
        except GridValidationError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            print(
                "HINT: read the clue-start numbers off the image and call "
                "`python -m xsolver.parse_image reconstruct --specs-json ...`",
                file=sys.stderr,
            )
            return 3
        print(f"Wrote {args.output_dir}/puzzle.json")
        return 0
    if args.cmd == "set-clues":
        updates = json.loads(Path(args.updates_json).read_text())
        set_clues_from_json(Path(args.output_dir), updates)
        print(f"Updated clue text in {args.output_dir}/puzzle.json")
        return 0
    if args.cmd == "reconstruct":
        specs = json.loads(Path(args.specs_json).read_text())
        try:
            build_puzzle_from_clues(
                output_dir=Path(args.output_dir),
                rows=args.rows,
                cols=args.cols,
                clue_specs=specs,
                title=args.title,
            )
        except GridValidationError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 3
        print(f"Wrote {args.output_dir}/puzzle.json (reconstructed from clues)")
        return 0
    return 1


DISPATCH = {
    "state": _state_main,
    "commit": _commit_main,
    "reassess": _reassess_main,
    "render": _render_main,
    "parse_image": _parse_image_main,
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
