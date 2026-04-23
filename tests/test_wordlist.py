"""Tests for the wordlist loader."""
from __future__ import annotations

from pathlib import Path

from xsolver.wordlist import Wordlist

DATA = Path(__file__).parent.parent / "data" / "ukacd.txt"


def test_wordlist_loads_from_file():
    wl = Wordlist.load(DATA)
    assert wl.count() > 50_000


def test_wordlist_normalises_to_uppercase():
    wl = Wordlist.load(DATA)
    # Every entry should be uppercase when queried
    sample = wl.by_length(5)[:10]
    assert all(w == w.upper() for w in sample)


def test_wordlist_by_length_filters_correctly():
    wl = Wordlist.load(DATA)
    for w in wl.by_length(7)[:100]:
        # Count only A-Z letters (phrases include spaces / punctuation)
        letters_only = "".join(c for c in w if c.isalpha())
        assert len(letters_only) == 7
