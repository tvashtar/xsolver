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


def test_match_pattern_all_wildcards_returns_all_of_length():
    wl = Wordlist.load(DATA)
    got = wl.match_pattern("?????", max_results=None)
    expected = wl.by_length(5)
    assert set(got) == set(expected)


def test_match_pattern_partial():
    wl = Wordlist.load(DATA)
    # 5-letter word P?RK? should include PARKA
    got = wl.match_pattern("P?RK?", max_results=None)
    assert "PARKA" in got


def test_match_pattern_respects_case_and_returns_uppercase():
    wl = Wordlist.load(DATA)
    got = wl.match_pattern("p?rk?", max_results=None)
    assert all(w == w.upper() for w in got)
    assert "PARKA" in got


def test_match_pattern_length_mismatch_returns_empty():
    wl = Wordlist.load(DATA)
    got = wl.match_pattern("P?RK?A", max_results=None)
    # 6-char pattern should not match 5-letter PARKA
    assert "PARKA" not in got


def test_match_pattern_max_results_caps_list():
    wl = Wordlist.load(DATA)
    got = wl.match_pattern("?????", max_results=10)
    assert len(got) == 10


def test_match_pattern_rejects_regex_metacharacters():
    import pytest as _pytest

    wl = Wordlist.load(DATA)
    with _pytest.raises(ValueError, match="invalid characters"):
        wl.match_pattern("P.RK?")
    with _pytest.raises(ValueError):
        wl.match_pattern("P+RK?")


def test_match_phrase_enumeration_respected():
    wl = Wordlist.load(DATA)
    # 5,4 phrase — assert no returned phrase violates the enumeration
    got = wl.match_phrase("?????,????", enumeration=[5, 4], max_results=None)
    for phrase in got:
        parts = phrase.split()
        assert [len(p) for p in parts] == [5, 4]


def test_match_phrase_known_letters_applied():
    wl = Wordlist.load(DATA)
    # Enumeration 4,4 with first word BO??
    got = wl.match_phrase("BO??,????", enumeration=[4, 4], max_results=None)
    for phrase in got:
        parts = phrase.split()
        assert parts[0].startswith("BO")
        assert len(parts[0]) == 4 and len(parts[1]) == 4


def test_match_phrase_single_word_enumeration_equivalent_to_match_pattern():
    wl = Wordlist.load(DATA)
    phrase_hits = wl.match_phrase("P?RK?", enumeration=[5], max_results=None)
    pattern_hits = wl.match_pattern("P?RK?", max_results=None)
    assert set(phrase_hits) == set(pattern_hits)


def test_match_phrase_rejects_regex_metacharacters():
    import pytest as _pytest

    wl = Wordlist.load(DATA)
    with _pytest.raises(ValueError, match="invalid characters"):
        wl.match_phrase("BO.RD,????", enumeration=[5, 4])
    with _pytest.raises(ValueError):
        wl.match_phrase("BO+RD,????", enumeration=[5, 4])
