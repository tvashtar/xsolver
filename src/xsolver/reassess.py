"""Identify clues whose letter pattern has changed since their last attempt."""
from __future__ import annotations

from pathlib import Path

from xsolver.state import (
    acquire_puzzle_lock,
    current_pattern,
    load_puzzle,
    load_state,
)


def list_stale(puzzle_dir: Path) -> list[dict]:
    """Return clues where:
      - the clue is not committed-high, AND
      - the latest attempt exists AND its pattern_at_attempt differs from current.

    Also return clues with no attempts at all but a non-empty current pattern
    (letters arrived from neighbours before this clue was ever tried).
    """
    with acquire_puzzle_lock(puzzle_dir):
        puzzle = load_puzzle(puzzle_dir)
        state = load_state(puzzle_dir)

        stale: list[dict] = []
        for clue_id, cs in state.clues.items():
            if cs.committed:
                continue
            pattern = current_pattern(puzzle, state, clue_id)
            if cs.attempts:
                last = cs.attempts[-1]
                if last.pattern_at_attempt != pattern:
                    stale.append(
                        {
                            "clue": clue_id,
                            "current_pattern": pattern,
                            "pattern_at_attempt": last.pattern_at_attempt,
                            "last_answer": last.answer,
                            "last_confidence": last.confidence,
                        }
                    )
            else:
                if any(c != "?" for c in pattern):
                    stale.append(
                        {
                            "clue": clue_id,
                            "current_pattern": pattern,
                            "pattern_at_attempt": None,
                            "last_answer": None,
                            "last_confidence": None,
                        }
                    )
        return stale


# Clue-text signals that the answer is likely a proper noun — a nationality,
# place, named work, person, brand, or similar. UKACD excludes most of these,
# so a "no dictionary match" on a clue like this should NOT auto-trigger a
# retract: the committed crossings may all be right and the answer just
# escapes the wordlist. Hit-rate over precision here; false positives cost a
# gentle hint, false negatives cost a wrong-branch cascade.
_PROPER_NOUN_HINTS = (
    # Nationalities / geographies
    "south america", "north america", "latin america", "central america",
    "african", "european", "asian", "oceania", "middle east",
    "argentin", "brazil", "peru", "chile", "colomb", "venezuel", "bolivia",
    "uruguay", "paragua", "suriname", "guyana", "ecuador", "panama",
    "mexico", "cuba", "jamaica", "spanish", "portuguese", "italian",
    "french", "german", "dutch", "swedish", "norwegian", "danish",
    "russian", "polish", "greek", "turkish", "arab", "iranian", "persian",
    "indian", "chinese", "japanese", "korean", "thai", "vietnamese",
    "american", "british", "english", "irish", "scottish", "welsh",
    # Places / toponyms
    "capital", "city", "country", "region", "province", "state", "county",
    "river", "lake", "mountain", "peak", "island", "bay", "strait",
    # Named categories that tend to be proper nouns
    "hymn", "canticle", "psalm", "anthem", "carol",
    "composer", "poet", "playwright", "novelist", "painter",
    "character", "hero", "heroine", "villain",
    "brand", "marque", "company",
    "saint", "prophet", "god", "goddess", "myth",
)


def _likely_proper_noun(clue_text: str) -> bool:
    """Heuristic: does the clue text suggest a proper-noun answer?

    When True, `list_impossible` should NOT treat a no-wordlist-match as
    evidence a crossing is wrong — the answer may simply not be in UKACD.
    """
    lower = clue_text.lower()
    return any(hint in lower for hint in _PROPER_NOUN_HINTS)


def list_impossible(puzzle_dir: Path) -> dict:
    """Find unsolved clues whose current pattern admits NO dictionary word.

    A clue is "impossible" if:
      - it's not committed
      - its pattern has ≥2 known letters (so it's meaningfully constrained)
      - its enumeration is a single word (multi-word phrases need per-segment
        checks that match_pattern doesn't do directly — flag those separately)
      - `match_pattern(current_pattern)` returns zero hits

    For each impossible clue, lists the COMMITTED crossing clues whose letters
    contribute to the pattern — one of them MAY be wrong and a candidate for
    `state retract`.

    IMPORTANT: "no dictionary match" is a wordlist-only signal. UKACD excludes
    most proper-noun answers (nationalities, places, named works, people,
    brands). When the clue text suggests a proper-noun answer, entries are
    moved to `likely_proper_noun` instead of `impossible`, so the orchestrator
    doesn't reflexively retract a correct commit. Inspect these: if a
    proper-noun answer fits the pattern, propose it; otherwise treat as
    impossible and retract the weakest crossing.

    Multi-word answers are returned under `multi_word_unchecked` so they're
    not silently skipped.
    """
    from xsolver.helpers import match_pattern

    with acquire_puzzle_lock(puzzle_dir):
        puzzle = load_puzzle(puzzle_dir)
        state = load_state(puzzle_dir)

    # Lower score = weaker wordplay = better retract candidate.
    # Attempts without a score sort in the middle.
    _WP_RANK = {"unparsed": 0, "partial": 1, None: 2, "clean": 3}

    def _committed_wordplay_strength(clue_id: str) -> str | None:
        cs = state.clues[clue_id]
        if not cs.committed_answer:
            return None
        for att in cs.attempts:
            if att.answer == cs.committed_answer:
                return att.wordplay_strength
        return None

    impossible: list[dict] = []
    multi_word_unchecked: list[dict] = []
    likely_proper_noun: list[dict] = []
    # Reverse-index: cell -> list of committed clue ids that cover it
    cell_committers: dict[int, list[str]] = {}
    for clue in puzzle.clues:
        cs = state.clues[clue["id"]]
        if cs.committed:
            for idx in clue["cells"]:
                cell_committers.setdefault(idx, []).append(clue["id"])

    for clue in puzzle.clues:
        cs = state.clues[clue["id"]]
        if cs.committed:
            continue
        pattern = current_pattern(puzzle, state, clue["id"])
        known = sum(1 for ch in pattern if ch != "?")
        if known == 0:
            continue  # nothing fixed yet; match_pattern would match everything
        # Which crossings contributed?
        crossings: list[dict] = []
        for pos, (idx, ch) in enumerate(zip(clue["cells"], pattern, strict=False)):
            if ch == "?":
                continue
            for other_id in cell_committers.get(idx, []):
                if other_id == clue["id"]:
                    continue
                crossings.append({
                    "clue": other_id,
                    "letter": ch,
                    "position": pos,
                    "wordplay_strength": _committed_wordplay_strength(other_id),
                })
        # Sort crossings so the weakest-wordplay retract target is first.
        crossings.sort(
            key=lambda c: _WP_RANK.get(c.get("wordplay_strength"), 2)
        )

        entry = {
            "clue": clue["id"],
            "pattern": pattern,
            "known": known,
            "total": len(clue["cells"]),
            "committed_crossings": crossings,
        }

        if len(clue["enumeration"]) != 1:
            multi_word_unchecked.append(entry)
            continue

        hits = match_pattern(pattern)
        if not hits:
            if _likely_proper_noun(clue.get("text", "")):
                entry["note"] = (
                    "No wordlist match, but clue text suggests a proper-noun "
                    "answer (nationality/place/named work/person/brand). "
                    "Do NOT reflexively retract a committed crossing — "
                    "consider proper-noun answers not in UKACD first."
                )
                likely_proper_noun.append(entry)
            else:
                entry["note"] = (
                    "No wordlist match. One of committed_crossings is likely "
                    "a near-miss; retract the weakest-wordplay one before "
                    "re-proposing."
                )
                impossible.append(entry)

    return {
        "impossible": impossible,
        "likely_proper_noun": likely_proper_noun,
        "multi_word_unchecked": multi_word_unchecked,
    }


if __name__ == "__main__":
    import sys

    from xsolver.cli import _reassess_main

    raise SystemExit(_reassess_main(sys.argv[1:]))
