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
        init_state,
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
    r.add_argument(
        "--wordplay", choices=["clean", "partial", "unparsed"], default=None,
        help="Wordplay-parse strength, separate from confidence. "
             "clean=decomposes cleanly; partial=some parses; "
             "unparsed=definition-only guess. Drives retract-target ranking.",
    )

    pr = sub.add_parser(
        "propose",
        help="Append a candidate to guesses.jsonl (lock-free, parallel-safe)",
    )
    pr.add_argument("--puzzle-dir", required=True)
    pr.add_argument("--clue", required=True)
    pr.add_argument("--answer", required=True)
    pr.add_argument("--confidence", required=True, choices=["high", "medium", "low"])
    pr.add_argument("--reasoning", required=True)
    pr.add_argument(
        "--wordplay", choices=["clean", "partial", "unparsed"], default=None,
        help="Wordplay-parse strength, separate from confidence. "
             "clean=decomposes cleanly; partial=some parses; "
             "unparsed=definition-only guess. Drives retract-target ranking.",
    )

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

    it = sub.add_parser("init", help="Initialise state.json from puzzle.json")
    it.add_argument("--puzzle-dir", required=True)

    rs = sub.add_parser(
        "reset",
        help="Delete state.json, guesses.jsonl, history.jsonl, .puzzle.lock — "
             "keeps puzzle.json so you can re-solve without re-parsing the image.",
    )
    rs.add_argument("--puzzle-dir", required=True)
    rs.add_argument(
        "--init", action="store_true",
        help="Also run `state init` after clearing, so you can go straight to solving.",
    )

    args = p.parse_args(argv)
    if args.cmd == "record":
        try:
            do_record(
                Path(args.puzzle_dir),
                clue_id=args.clue,
                answer=args.answer,
                confidence=args.confidence,
                reasoning=args.reasoning,
                wordplay_strength=args.wordplay,
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
                wordplay_strength=args.wordplay,
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
    if args.cmd == "init":
        init_state(Path(args.puzzle_dir))
        print(f"Initialised state in {args.puzzle_dir}/state.json")
        return 0
    if args.cmd == "reset":
        from xsolver.state import reset as do_reset
        try:
            removed = do_reset(Path(args.puzzle_dir))
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        result: dict = {"puzzle_dir": args.puzzle_dir, "removed": removed}
        if args.init:
            init_state(Path(args.puzzle_dir))
            result["initialised"] = True
        print(json.dumps(result, indent=2))
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
    from xsolver.reassess import list_impossible, list_stale

    p = argparse.ArgumentParser(prog="python -m xsolver.reassess")
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="Clues whose pattern changed since last attempt")
    ls.add_argument("--puzzle-dir", required=True)
    im = sub.add_parser(
        "impossible",
        help="Clues whose current pattern admits no dictionary word — a committed crossing is wrong",
    )
    im.add_argument("--puzzle-dir", required=True)

    args = p.parse_args(argv)
    if args.cmd == "list":
        stale = list_stale(Path(args.puzzle_dir))
        print(json.dumps(stale, indent=2))
        return 0
    if args.cmd == "impossible":
        report = list_impossible(Path(args.puzzle_dir))
        print(json.dumps(report, indent=2))
        return 0
    return 1


# --- render --------------------------------------------------------

def _render_main(argv: list[str]) -> int:
    from xsolver.render import next_batch, render_grid, render_html, render_summary

    p = argparse.ArgumentParser(prog="python -m xsolver.render")
    p.add_argument("--puzzle-dir", required=True)
    p.add_argument("--summary", action="store_true")
    p.add_argument(
        "--html", action="store_true",
        help="Emit a self-contained HTML page (grid + clue list with answers)",
    )
    p.add_argument(
        "--next-batch", type=int, metavar="N",
        help="Print the N unsolved clues most ready to solve (highest % known), as JSON",
    )

    args = p.parse_args(argv)
    if args.html:
        print(render_html(Path(args.puzzle_dir)))
    elif args.next_batch is not None:
        print(json.dumps(next_batch(Path(args.puzzle_dir), n=args.next_batch), indent=2))
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


def _watch_main(argv: list[str]) -> int:
    from xsolver.watch import _main as watch_main
    return watch_main(argv)


def _wave_main(argv: list[str]) -> int:
    """One-shot orchestration loop: promote → commit → reassess → summary.

    Replaces the common cycle of running four separate subcommands. Returns
    a single JSON blob so the orchestrator can act on all signals in one
    roundtrip instead of paying per-call Python startup cost × 4.
    """
    from xsolver.commit import run_wave
    from xsolver.reassess import list_impossible, list_stale
    from xsolver.render import next_batch, render_summary
    from xsolver.state import promote_candidates

    p = argparse.ArgumentParser(prog="python -m xsolver.wave")
    p.add_argument("--puzzle-dir", required=True)
    p.add_argument(
        "--next-batch", type=int, default=0,
        help="Include top-N most-constrained unsolved clues (0 = skip)",
    )
    p.add_argument(
        "--stale", action="store_true",
        help="Include clues whose pattern changed since last attempt",
    )
    p.add_argument(
        "--format", default="all",
        choices=["all", "terse", "committed", "retracted", "conflicts",
                 "impossible", "likely_proper_noun", "summary"],
        help=(
            "Output mode. 'all' = full JSON (default). 'terse' = compact "
            "human-readable summary covering committed/retracted/impossible/"
            "summary in <30 lines. The named single-field options print just "
            "that field as JSON — saves piping through python -c."
        ),
    )
    args = p.parse_args(argv)
    puzzle_dir = Path(args.puzzle_dir)

    promoted = promote_candidates(puzzle_dir)
    commit_summary = run_wave(puzzle_dir)
    impossible = list_impossible(puzzle_dir)

    out: dict = {
        "promoted": promoted,
        "committed": commit_summary["committed"],
        "retracted": commit_summary["retracted"],
        "conflicts": commit_summary["conflicts"],
        "impossible": impossible["impossible"],
        "likely_proper_noun": impossible["likely_proper_noun"],
        "multi_word_unchecked": impossible["multi_word_unchecked"],
        "summary": render_summary(puzzle_dir),
    }
    if args.next_batch > 0:
        out["next_batch"] = next_batch(puzzle_dir, n=args.next_batch)
    if args.stale:
        out["stale"] = list_stale(puzzle_dir)

    if args.format == "all":
        print(json.dumps(out, indent=2))
    elif args.format == "terse":
        # Compact view: just the actionable bits, no JSON nesting.
        print(f"committed: {out['committed']}")
        print(f"retracted: {out['retracted']}")
        if out["conflicts"]:
            print(f"conflicts: {out['conflicts']}")
        if out["impossible"]:
            print(f"impossible: {[(x.get('clue'), x.get('pattern')) for x in out['impossible']]}")
        if out["likely_proper_noun"]:
            print(f"proper_noun: {[(x.get('clue'), x.get('pattern')) for x in out['likely_proper_noun']]}")
        print("---")
        print(out["summary"])
    else:
        print(json.dumps(out[args.format], indent=2))
    return 0


def _helpers_main(argv: list[str]) -> int:
    """Wordplay helpers as CLI subcommands. Each prints JSON to stdout.

    Exists so subagents can call helpers via the `uv run xsolver *` allowlist
    instead of `uv run python -c "from xsolver.helpers import ..."`, which
    would require allowing arbitrary Python execution.
    """
    from xsolver import helpers

    p = argparse.ArgumentParser(prog="xsolver helpers")
    sub = p.add_subparsers(dest="op", required=True)

    mp = sub.add_parser("match-pattern", help="Words matching pattern (? = unknown)")
    mp.add_argument("pattern")
    mp.add_argument("--max", type=int, default=50)

    an = sub.add_parser("anagram", help="Words formable from letters")
    an.add_argument("letters")
    an.add_argument("--length", type=int, default=None)
    an.add_argument("--max", type=int, default=50)

    cw = sub.add_parser("check-word", help="True if word is in wordlist")
    cw.add_argument("word")

    cp = sub.add_parser("check-phrase", help="True if phrase fits enumeration + in wordlist")
    cp.add_argument("phrase")
    cp.add_argument("enumeration", help="Comma-separated, e.g. 4,6")

    cn = sub.add_parser("contains-word", help="Wordlist entries hidden as substrings of text")
    cn.add_argument("text")
    cn.add_argument("length", type=int)

    dl = sub.add_parser("deletion", help="Words formed by deleting N letters from source")
    dl.add_argument("source")
    dl.add_argument("chars_to_drop", type=int)

    args = p.parse_args(argv)

    if args.op == "match-pattern":
        result = helpers.match_pattern(args.pattern, max_results=args.max)
    elif args.op == "anagram":
        result = helpers.anagram(args.letters, length=args.length, max_results=args.max)
    elif args.op == "check-word":
        result = helpers.check_word(args.word)
    elif args.op == "check-phrase":
        enum = [int(x) for x in args.enumeration.split(",")]
        result = helpers.check_phrase(args.phrase, enum)
    elif args.op == "contains-word":
        result = helpers.contains_word(args.text, args.length)
    elif args.op == "deletion":
        result = helpers.deletion(args.source, args.chars_to_drop)
    else:
        return 1

    print(json.dumps(result))
    return 0


def _image_main(argv: list[str]) -> int:
    """Image utilities. Currently: crop a region from an image at full resolution.

    Exists so the orchestrator can read photo regions sharply without using
    `uv run python -c "from PIL import Image; ..."` (arbitrary Python).
    """
    from PIL import Image

    p = argparse.ArgumentParser(prog="xsolver image")
    sub = p.add_subparsers(dest="op", required=True)

    cr = sub.add_parser("crop", help="Crop a bounding box out of an image")
    cr.add_argument("--in", dest="src", required=True)
    cr.add_argument("--out", required=True)
    cr.add_argument(
        "--bbox", required=True,
        help="x0,y0,x1,y1 (pixel coordinates of crop box)",
    )

    sz = sub.add_parser("size", help="Print image dimensions as JSON {width,height}")
    sz.add_argument("--in", dest="src", required=True)

    args = p.parse_args(argv)

    if args.op == "crop":
        img = Image.open(args.src)
        bbox = tuple(int(x) for x in args.bbox.split(","))
        if len(bbox) != 4:
            print("--bbox needs 4 comma-separated ints", file=sys.stderr)
            return 1
        img.crop(bbox).save(args.out)
        print(json.dumps({"out": args.out, "bbox": list(bbox), "src_size": list(img.size)}))
        return 0
    elif args.op == "size":
        img = Image.open(args.src)
        print(json.dumps({"width": img.size[0], "height": img.size[1]}))
        return 0
    return 1


DISPATCH = {
    "state": _state_main,
    "commit": _commit_main,
    "reassess": _reassess_main,
    "render": _render_main,
    "parse_image": _parse_image_main,
    "watch": _watch_main,
    "wave": _wave_main,
    "helpers": _helpers_main,
    "image": _image_main,
}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(
            "usage: xsolver {state|commit|reassess|render|parse_image|watch|wave} ...",
            file=sys.stderr,
        )
        return 1
    sub = argv[0]
    if sub not in DISPATCH:
        print(f"unknown subcommand {sub!r}", file=sys.stderr)
        return 1
    return DISPATCH[sub](argv[1:])
