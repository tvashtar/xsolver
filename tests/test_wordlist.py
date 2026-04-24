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


def test_match_pattern_all_wildcards_returns_all_single_word_of_length():
    wl = Wordlist.load(DATA)
    got = wl.match_pattern("?????", max_results=None)
    # match_pattern returns single-word entries — letters-only plus
    # hyphenated/apostrophised forms whose letter count matches. Phrases
    # (entries containing spaces) are reached via match_phrase.
    expected = [w for w in wl.by_length(5) if " " not in w]
    assert set(got) == set(expected)


def test_match_pattern_includes_hyphenated_entries():
    wl = Wordlist.load(DATA)
    # ROUGH-NECK has 9 letters and should be matched by a 9-? pattern
    # with H at position 5.
    got = wl.match_pattern("????H????", max_results=None)
    assert "ROUGH-NECK" in got


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


def test_match_pattern_zero_max_results_returns_empty():
    wl = Wordlist.load(DATA)
    assert wl.match_pattern("?????", max_results=0) == []


def test_match_phrase_zero_max_results_returns_empty():
    wl = Wordlist.load(DATA)
    assert wl.match_phrase("P?RK?", enumeration=[5], max_results=0) == []


def test_load_deduplicates_entries():
    # macOS dict has both lowercase and uppercase "A"; after uppercasing they
    # collapse to the same entry. Ensure the bucket has no duplicates.
    wl = Wordlist.load(DATA)
    for length, entries in wl.by_letter_count.items():
        assert len(entries) == len(set(entries)), (
            f"bucket {length} has duplicates"
        )


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
    # match_pattern additionally surfaces hyphenated/apostrophised entries
    # (e.g. ROUGH-NECK); match_phrase's regex treats non-letters as literal
    # and so excludes them. Restrict the comparison to pure-alpha entries.
    pattern_alpha = {w for w in pattern_hits if w.isalpha()}
    assert set(phrase_hits) == pattern_alpha


def test_match_phrase_rejects_regex_metacharacters():
    import pytest as _pytest

    wl = Wordlist.load(DATA)
    with _pytest.raises(ValueError, match="invalid characters"):
        wl.match_phrase("BO.RD,????", enumeration=[5, 4])
    with _pytest.raises(ValueError):
        wl.match_phrase("BO+RD,????", enumeration=[5, 4])
