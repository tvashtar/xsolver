"""Live observability for a running solve.

Re-renders the grid + clue summary whenever `state.json` changes, and streams
new `history.jsonl` events as they're appended. Intended to run in a separate
terminal alongside an active solve.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from xsolver.render import render_grid, render_summary
from xsolver.state import HISTORY_FILENAME, STATE_FILENAME

_CLEAR = "\033[2J\033[H"


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def watch(puzzle_dir: Path, interval: float = 2.0) -> int:
    """Loop: on each tick, re-render if state.json changed and drain new history."""
    state_path = puzzle_dir / STATE_FILENAME
    history_path = puzzle_dir / HISTORY_FILENAME

    last_state_mtime = -1.0
    history_offset = 0  # bytes read so far — stream new appended events

    try:
        while True:
            state_mtime = _mtime(state_path)
            if state_mtime != last_state_mtime:
                last_state_mtime = state_mtime
                sys.stdout.write(_CLEAR)
                sys.stdout.write(f"# {puzzle_dir}\n\n")
                if state_path.exists():
                    sys.stdout.write(render_grid(puzzle_dir) + "\n\n")
                    sys.stdout.write(render_summary(puzzle_dir) + "\n")
                else:
                    sys.stdout.write("(no state.json yet — waiting)\n")
                sys.stdout.write("\n--- events ---\n")

            # Stream new history lines
            if history_path.exists():
                with history_path.open("r", encoding="utf-8") as fh:
                    fh.seek(history_offset)
                    new = fh.read()
                    history_offset = fh.tell()
                if new:
                    sys.stdout.write(new)

            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        sys.stdout.write("\n[watch stopped]\n")
        return 0


def _main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m xsolver.watch")
    p.add_argument("--puzzle-dir", required=True)
    p.add_argument("--interval", type=float, default=2.0, help="Poll interval in seconds")
    args = p.parse_args(argv)
    return watch(Path(args.puzzle_dir), interval=args.interval)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
