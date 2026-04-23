"""UKACD wordlist loader with length-indexed lookup."""
from __future__ import annotations

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
