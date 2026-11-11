"""Text normalization and similarity used by duplicate and leakage checks."""

import re
import unicodedata

_WORD = re.compile(r"[\w']+", re.UNICODE)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower().replace("’", "'")
    return " ".join(_WORD.findall(s))


def words(s: str) -> list:
    return norm(s).split()


def shingles(s: str, n: int = 3) -> frozenset:
    w = words(s)
    if len(w) < n:
        return frozenset([tuple(w)]) if w else frozenset()
    return frozenset(tuple(w[i:i + n]) for i in range(len(w) - n + 1))


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)
