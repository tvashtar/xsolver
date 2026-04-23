"""Deterministic helpers Claude calls as tools during solve."""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path

from xsolver.wordlist import Wordlist

_WORDLIST_PATH = Path(__file__).parent.parent.parent / "data" / "ukacd.txt"


@lru_cache(maxsize=1)
def _wordlist() -> Wordlist:
    """Lazy-load the wordlist once per process."""
    return Wordlist.load(_WORDLIST_PATH)


def match_pattern(pattern: str, max_results: int | None = 50) -> list[str]:
    """Return words matching `pattern` (with `?` as unknown).

    Wrapper around Wordlist.match_pattern using the bundled UKACD.
    """
    return _wordlist().match_pattern(pattern, max_results=max_results)


def anagram(
    letters: str,
    length: int | None = None,
    max_results: int | None = 50,
) -> list[str]:
    """Return single words that can be formed from `letters`.

    If `length` is provided, results have exactly that many letters,
    drawn from `letters` (without repetition beyond what's available).
    If `length` is None, returns full anagrams (same letter count).
    """
    if max_results is not None and max_results <= 0:
        return []
    wl = _wordlist()
    letters_upper = "".join(c for c in letters.upper() if c.isalpha())
    target_len = length if length is not None else len(letters_upper)
    if target_len <= 0:
        return []

    available = Counter(letters_upper)

    hits: list[str] = []
    for entry in wl.by_length(target_len):
        if not entry.isalpha():
            continue
        entry_counter = Counter(entry)
        if all(entry_counter[c] <= available.get(c, 0) for c in entry_counter):
            hits.append(entry)
            if max_results is not None and len(hits) >= max_results:
                break
    return hits


def check_word(word: str) -> bool:
    """Return True if `word` is a single-word entry in the wordlist."""
    word_upper = word.upper().strip()
    if not word_upper.isalpha():
        return False
    wl = _wordlist()
    return word_upper in set(wl.by_length(len(word_upper)))


def check_phrase(phrase: str, enumeration: list[int]) -> bool:
    """Return True if `phrase` matches `enumeration` and is in the wordlist."""
    phrase_upper = phrase.upper().strip()
    parts = phrase_upper.split()
    if [len(p) for p in parts] != enumeration:
        return False
    wl = _wordlist()
    total_letters = sum(enumeration)
    return phrase_upper in set(wl.by_letter_count.get(total_letters, []))
