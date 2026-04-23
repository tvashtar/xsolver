"""UKACD wordlist loader with length-indexed lookup."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


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
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                entry = raw.strip().upper()
                if not entry:
                    continue
                length = _letter_count(entry)
                if length == 0:
                    continue
                wl.by_letter_count.setdefault(length, []).append(entry)
        return wl

    def by_length(self, n: int) -> list[str]:
        """Return all entries with exactly n letters."""
        return self.by_letter_count.get(n, [])

    def count(self) -> int:
        return sum(len(v) for v in self.by_letter_count.values())

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
