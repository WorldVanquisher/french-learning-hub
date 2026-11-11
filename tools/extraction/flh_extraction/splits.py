"""Split integrity and leakage checks across training, evaluation, boundary
and workbook material."""

import re

from .dedup import exact_groups, near_pairs, visible_text
from .textnorm import norm

QUOTED = re.compile(r"«\s*([^»]+?)\s*»")


def headwords(canonical):
    forms = QUOTED.findall(canonical)
    if not forms:
        forms = [canonical.split(" — ")[0].split(" (")[0]]
    return {norm(f) for f in forms if norm(f)}


def check(train, evals, boundary=(), workbook_texts=()):
    rep = {"counts": {"train": sum(1 for r in train if r["meta"]["split_group"] == "train"),
                      "dev": sum(1 for r in train if r["meta"]["split_group"] == "dev"),
                      "eval": len(evals), "boundary": len(boundary)}}
    ids = [r["id"] for r in list(train) + list(evals) + list(boundary)]
    rep["duplicate_ids"] = sorted({i for i in ids if ids.count(i) > 1})
    # Families never cross splits; points never cross train/dev.
    fam_split = {}
    for r in list(train) + list(evals):
        fam_split.setdefault(r["meta"]["family_id"], set()).add(r["meta"]["split_group"])
    rep["families_in_two_splits"] = sorted(f for f, s in fam_split.items() if len(s) > 1)
    point_split = {}
    for r in train:
        for p in r["meta"]["points"]:
            point_split.setdefault(p, set()).add(r["meta"]["split_group"])
    rep["points_in_train_and_dev"] = sorted(p for p, s in point_split.items() if len(s) > 1)
    train_points = {p for r in train for p in r["meta"]["points"]}
    eval_points = {p for r in evals for p in r["meta"]["points"]}
    rep["points_in_train_and_eval"] = sorted(train_points & eval_points)
    # Objective overlap: identical canonicals and shared quoted headwords.
    tc = {u["canonical"] for r in train for u in r["expected"]["units"]}
    ec = {u["canonical"] for r in evals for u in r["expected"]["units"]}
    bc = {u["canonical"] for r in boundary for u in r["expected"]["units"]}
    rep["canonical_overlap_train_eval"] = sorted(tc & ec)
    th = {h for c in tc for h in headwords(c)}
    rep["headword_overlap_train_eval"] = sorted({h for c in ec for h in headwords(c)} & th)
    rep["canonical_overlap_boundary_train"] = sorted(bc & tc)
    rep["canonical_overlap_boundary_eval"] = sorted(bc & ec)
    # Duplicates.
    rep["exact_duplicate_groups"] = {"train": exact_groups(train), "eval": exact_groups(evals),
                                     "across_train_eval": [g for g in exact_groups(list(train) + list(evals))
                                                           if any(i.startswith("ext-evl") for i in g) and any(i.startswith("ext-trn") for i in g)]}
    cross = near_pairs(evals, 0.5, other=train)
    rep["near_pairs_eval_train"] = {"jaccard_ge_0.5": len(cross), "jaccard_ge_0.8": sum(1 for _, _, s in cross if s >= 0.8),
                                    "examples": cross[:10]}
    bcross = near_pairs(list(boundary), 0.5, other=list(train) + list(evals))
    rep["near_pairs_boundary_vs_datasets"] = {"jaccard_ge_0.5": len(bcross), "examples": bcross[:10]}
    if workbook_texts:
        wb = [{"id": f"wb-{k}", "input": {"original_input": t, "original_context": ""}} for k, t in enumerate(workbook_texts)]
        wcross = near_pairs(evals, 0.3, other=wb)
        rep["near_pairs_eval_workbook"] = {"jaccard_ge_0.3": len(wcross), "examples": wcross[:10]}
    rep["pass"] = not (rep["duplicate_ids"] or rep["families_in_two_splits"] or rep["points_in_train_and_dev"]
                       or rep["points_in_train_and_eval"] or rep["canonical_overlap_train_eval"]
                       or rep["exact_duplicate_groups"]["across_train_eval"] or rep["near_pairs_eval_train"]["jaccard_ge_0.8"])
    return rep
