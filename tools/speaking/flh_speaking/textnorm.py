"""French transcript normalization and word/character error rates.

``flh_fr_asr_norm_v1`` is applied identically to references and hypotheses
before scoring. It removes differences that a learner-facing transcript does
not depend on (case, punctuation, apostrophe and quote variants, ligatures,
hyphenation, bracketed non-speech tags) and keeps everything else, including
accents and elision. Numbers are NOT converted: "1823" and "mille huit cent
vingt-trois" differ, and evaluation reports digit-bearing utterances separately.
"""

from __future__ import annotations

import re
import unicodedata

NORM_VERSION = "flh_fr_asr_norm_v1"

_APOS = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'", "´": "'"})
_LIG = {"œ": "oe", "æ": "ae"}
_BRACKETS = re.compile(r"\[[^\]]*\]|\([^)]*\)|<[^>]*>")
_QUOTE = re.compile(r"(?<![^\W\d_])'|'(?![^\W\d_])")


def normalize_fr(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).translate(_APOS).lower()
    t = _BRACKETS.sub(" ", t)
    for a, b in _LIG.items():
        t = t.replace(a, b)
    t = _QUOTE.sub(" ", t)  # an apostrophe not between two letters is a quotation mark
    out = []
    for ch in t:
        if ch == "'":
            out.append("' ")  # elision stays attached to its article: l'homme -> "l' homme"
        elif ch.isalnum():
            out.append(ch)
        else:  # punctuation, symbols, hyphens, whitespace
            out.append(" ")
    t = "".join(out)
    return " ".join(t.split())


def words(text: str) -> list[str]:
    return normalize_fr(text).split()


def align(ref: list, hyp: list) -> tuple[int, int, int]:
    """(substitutions, deletions, insertions) of a minimum-edit alignment."""
    n, m = len(ref), len(hyp)
    prev = list(range(m + 1))
    # store full table of ops for backtrace in compact form
    back = [[0] * (m + 1) for _ in range(n + 1)]
    for j in range(1, m + 1):
        back[0][j] = 3  # insertion
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        back[i][0] = 2  # deletion
        ri = ref[i - 1]
        for j in range(1, m + 1):
            if ri == hyp[j - 1]:
                best, op = prev[j - 1], 0
            else:
                best, op = prev[j - 1] + 1, 1
            if prev[j] + 1 < best:
                best, op = prev[j] + 1, 2
            if cur[j - 1] + 1 < best:
                best, op = cur[j - 1] + 1, 3
            cur[j] = best
            back[i][j] = op
        prev = cur
    s = d = ins = 0
    i, j = n, m
    while i > 0 or j > 0:
        op = back[i][j]
        if op in (0, 1):
            s += op
            i, j = i - 1, j - 1
        elif op == 2:
            d += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return s, d, ins


def score(ref_text: str, hyp_text: str) -> dict:
    """Per-utterance counts; corpus rates are sums of errors over sums of reference units."""
    rw, hw = words(ref_text), words(hyp_text)
    s, d, i = align(rw, hw)
    rc, hc = list(" ".join(rw)), list(" ".join(hw))
    cs, cd, ci = align(rc, hc)
    return {
        "ref_words": len(rw), "sub": s, "del": d, "ins": i,
        "ref_chars": len(rc), "char_errors": cs + cd + ci,
        "hyp_has_digit": any(ch.isdigit() for ch in hyp_text),
        "ref_has_digit": any(ch.isdigit() for ch in ref_text),
    }


def rate(rows: list[dict]) -> dict:
    n = sum(r["ref_words"] for r in rows)
    e = sum(r["sub"] + r["del"] + r["ins"] for r in rows)
    c = sum(r["ref_chars"] for r in rows)
    ce = sum(r["char_errors"] for r in rows)
    return {
        "utterances": len(rows), "ref_words": n,
        "wer": round(e / n, 5) if n else None,
        "cer": round(ce / c, 5) if c else None,
        "sub": sum(r["sub"] for r in rows), "del": sum(r["del"] for r in rows), "ins": sum(r["ins"] for r in rows),
    }
