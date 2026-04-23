"""Tests for Claude-facing helper functions."""
from __future__ import annotations

from xsolver.helpers import anagram, match_pattern


def test_match_pattern_simple():
    result = match_pattern("P?RK?", max_results=None)
    assert "PARKA" in result


def test_match_pattern_honours_limit():
    result = match_pattern("?????", max_results=5)
    assert len(result) == 5


def test_anagram_known_pair():
    # LISTEN <-> SILENT is the canonical anagram example
    result = anagram("LISTEN")
    assert "SILENT" in result


def test_anagram_length_filter():
    # Restricting length should include only exact-length matches
    result = anagram("LISTEN", length=6)
    assert "SILENT" in result
    # All results must be length 6 single words
    assert all(len(w) == 6 and w.isalpha() for w in result)


def test_anagram_of_shorter_length():
    # Partial anagrams: use a subset of letters
    result = anagram("LISTEN", length=4)
    # LIST, LENS, NEST, etc. should all be findable
    assert any(w in result for w in ["LIST", "LENS", "NEST"])
    assert all(len(w) == 4 for w in result)


def test_anagram_zero_max_results_returns_empty():
    assert anagram("LISTEN", max_results=0) == []


def test_anagram_zero_length_returns_empty():
    assert anagram("LISTEN", length=0) == []
