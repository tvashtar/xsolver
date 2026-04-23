"""UKACD wordlist loader with length-indexed lookup."""
from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from pathlib import Path

_VALID_PATTERN_CHARS = frozenset(string.ascii_uppercase + "?")


def _letter_count(word: str) -> int:
    """Number of A-Z letters (ignoring spaces, hyphens, punctuation)."""
    return sum(1 for c in word if c.isalpha())


@dataclass
class Wordlist:
    """Loaded word/phrase list, indexed by letter count."""

    by_letter_count: dict[int, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Wordlist:
        wl = cls()
        seen: dict[int, set[str]] = {}
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                entry = raw.strip().upper()
                if not entry:
                    continue
                length = _letter_count(entry)
                if length == 0:
                    continue
                bucket = seen.setdefault(length, set())
                if entry in bucket:
                    continue
                bucket.add(entry)
                wl.by_letter_count.setdefault(length, []).append(entry)
        return wl

    def by_length(self, n: int) -> list[str]:
        """Return all entries with exactly n letters."""
        return self.by_letter_count.get(n, [])

    def count(self) -> int:
        return sum(len(v) for v in self.by_letter_count.values())

    def match_phrase(
        self,
        pattern: str,
        enumeration: list[int],
        max_results: int | None = 50,
    ) -> list[str]:
        """Return entries matching a multi-word pattern.

        `pattern` uses `?` for unknowns and `,` to separate words.
        `enumeration` is the list of word lengths, e.g. [6, 3, 5] for (6,3,5).
        The pattern's comma-separated segments must have lengths matching
        `enumeration`.

        Returns uppercase phrases joined by single spaces.

        Note: hyphenated entries (e.g. `JEAN-PIERRE`) are not reachable
        through this method — segments are split on whitespace only. Treat
        hyphenated answers as single words via `match_pattern` instead.
        """
        pattern_upper = pattern.upper()
        segments = pattern_upper.split(",")

        # Validate: after stripping commas, only A-Z and ? are allowed
        invalid = set(pattern_upper.replace(",", "")) - _VALID_PATTERN_CHARS
        if invalid:
            raise ValueError(
                f"pattern {pattern!r} contains invalid characters "
                f"{sorted(invalid)}; only A-Z and ? are allowed"
            )

        if [len(s) for s in segments] != enumeration:
            raise ValueError(
                f"pattern segments {[len(s) for s in segments]} do not match "
                f"enumeration {enumeration}"
            )

        if max_results is not None and max_results <= 0:
            return []

        total_letters = sum(enumeration)
        regex_parts = [seg.replace("?", "[A-Z]") for seg in segments]
        regex = re.compile("^" + r"\s+".join(regex_parts) + "$")

        hits: list[str] = []
        for entry in self.by_letter_count.get(total_letters, []):
            parts = entry.split()
            if [len(p) for p in parts] != enumeration:
                continue
            if regex.match(entry):
                hits.append(entry)
                if max_results is not None and len(hits) >= max_results:
                    break
        return hits

    def match_pattern(
        self,
        pattern: str,
        max_results: int | None = 50,
    ) -> list[str]:
        """Return single-word entries matching `pattern`.

        Pattern uses `?` for unknown letters. Case-insensitive.
        Only matches single-word entries (letters A-Z, no spaces).
        For phrases see `match_phrase`.
        """
        pattern_upper = pattern.upper()
        invalid = set(pattern_upper) - _VALID_PATTERN_CHARS
        if invalid:
            raise ValueError(
                f"pattern {pattern!r} contains invalid characters "
                f"{sorted(invalid)}; only A-Z and ? are allowed"
            )
        if max_results is not None and max_results <= 0:
            return []
        length = len(pattern_upper)
        regex = re.compile("^" + pattern_upper.replace("?", "[A-Z]") + "$")

        hits: list[str] = []
        for entry in self.by_letter_count.get(length, []):
            # Only pure single words (no spaces, hyphens, or punctuation)
            if not entry.isalpha():
                continue
            if regex.match(entry):
                hits.append(entry)
                if max_results is not None and len(hits) >= max_results:
                    break
        return hits
