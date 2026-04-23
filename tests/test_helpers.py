"""Tests for Claude-facing helper functions."""
from __future__ import annotations

from xsolver.helpers import (
    anagram,
    check_phrase,
    check_word,
    contains_word,
    deletion,
    match_pattern,
)


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


def test_check_word_known_word_returns_true():
    assert check_word("PARKA") is True


def test_check_word_nonword_returns_false():
    assert check_word("XQZPL") is False


def test_check_word_case_insensitive():
    assert check_word("parka") is True


def test_check_phrase_validates_enumeration_and_membership():
    # Single word phrase (trivial case)
    assert check_phrase("PARKA", enumeration=[5]) is True


def test_check_phrase_wrong_enumeration_returns_false():
    # PARKA is 5, not 4,1
    assert check_phrase("PARKA", enumeration=[4, 1]) is False


def test_check_phrase_unknown_phrase_returns_false():
    assert check_phrase("XQZPL MRFTK", enumeration=[5, 5]) is False


def test_contains_word_hidden_in_string():
    # 'PARKA' is hidden in 'SPARKA...' etc. Test: find PARKA inside 'APARKAGE'
    result = contains_word("APARKAGE", length=5)
    assert "PARKA" in result


def test_contains_word_no_match():
    # Nothing valid hides in X's
    result = contains_word("XXXXXX", length=5)
    assert result == []


def test_deletion_single_char():
    # Given 'PARKA' delete one char to form a word — e.g. 'PARK'
    result = deletion("PARKA", chars_to_drop=1)
    assert "PARK" in result


def test_deletion_wrong_count_errors():
    import pytest as _pytest
    with _pytest.raises(ValueError):
        deletion("PARKA", chars_to_drop=0)
