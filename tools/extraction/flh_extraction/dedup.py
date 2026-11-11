"""Exact and near-duplicate detection over candidate inputs.

The compared text is the model-visible learner material: original_input and
original_context. Near duplicates are found with word 3-gram shingles and an
inverted index, so only pairs that share a shingle are compared.
"""

from collections import defaultdict

from .textnorm import jaccard, norm, shingles


def visible_text(rec: dict) -> str:
    i = rec["input"]
    return f"{i['original_input']} || {i['original_context']}"


def exact_groups(recs):
    seen = defaultdict(list)
    for r in recs:
        seen[norm(visible_text(r))].append(r["id"])
    return [ids for ids in seen.values() if len(ids) > 1]


def near_pairs(recs, threshold=0.8, other=None):
    """Pairs (id_a, id_b, score) with Jaccard >= threshold. With `other`, only
    cross pairs between recs and other are reported (leakage checks)."""
    sh = {r["id"]: shingles(visible_text(r)) for r in recs}
    pool = other if other is not None else recs
    psh = {r["id"]: shingles(visible_text(r)) for r in pool} if other is not None else sh
    index = defaultdict(set)
    for rid, s in psh.items():
        for g in s:
            index[g].add(rid)
    out = []
    for rid, s in sh.items():
        cands = set()
        for g in s:
            cands |= index[g]
        for cid in cands:
            if other is None and cid <= rid:
                continue
            score = jaccard(s, psh[cid])
            if score >= threshold:
                out.append((rid, cid, round(score, 3)))
    return sorted(out)
