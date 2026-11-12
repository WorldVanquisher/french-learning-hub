"""Validation of a training increment against the base training set, the
frozen evaluation set and the boundary cases.

  python3 -m flh_extraction increment-check --base T.jsonl --increment I.jsonl --eval E.jsonl
         [--boundary B.jsonl] [--validated V.jsonl] --out REPORT.json

Checks (a failure makes `pass` false):
  - structural record checks and honest unreviewed statuses on every record;
  - every record validated by the production validator (`extraction-render
    expected` output given with --validated), and the validated units equal
    the expected units;
  - ids unique across base and increment; families never shared with the base;
  - every point already in the base, in the same split (no new objective, no
    train/dev crossing), none in the evaluation set;
  - no canonical shared with the evaluation set; no exact or near duplicate
    (word 3-gram Jaccard >= 0.8) of an evaluation input; split integrity of
    base + increment (splits.check).
Reported (not failing): headwords shared with evaluation canonicals, near
pairs >= 0.5 with evaluation and boundary inputs, near duplicates of base inputs.
"""

from collections import Counter

from . import records, splits
from .dedup import exact_groups, near_pairs


def check(base, inc, evals, boundary=(), validated=None):
    rep = {"schema": "flh_extraction_increment_check_v1", "counts": {"base": len(base), "increment": len(inc)}}
    rep["structural_errors"] = {r["id"]: e for r in inc for e in [records.structural_errors(r)] if e}
    rep["not_unreviewed"] = [r["id"] for r in inc if r["meta"].get("review_status") != "unreviewed"
                             or r["meta"].get("label_status") != "machine_authored_unreviewed"]
    if validated is not None:
        v = {x["id"]: x for x in validated}
        bad = [r["id"] for r in inc if not v.get(r["id"], {}).get("valid")]
        drift = [r["id"] for r in inc if r["id"] in v and v[r["id"]].get("valid") and
                 [(u["kind"], u["canonical"], u["statement"], u["statement_zh"], u["example"], u["confidence"])
                  for u in v[r["id"]]["units"]] !=
                 [(u["kind"], u["canonical"], u["statement"].strip(), u["statement_zh"], u["example"], u["confidence"])
                  for u in r["expected"]["units"]]]
        rep["production_validation"] = {"valid": len(inc) - len(bad), "of": len(inc), "invalid_ids": bad,
                                        "units_changed_by_validation": drift}
    else:
        rep["production_validation"] = "not run (pass --validated)"
    ids = [r["id"] for r in list(base) + list(inc)]
    rep["duplicate_ids"] = sorted({i for i, n in Counter(ids).items() if n > 1})
    base_fams = {r["meta"]["family_id"] for r in base}
    rep["families_shared_with_base"] = sorted({r["meta"]["family_id"] for r in inc} & base_fams)
    base_point_split = {}
    for r in base:
        for p in r["meta"]["points"]:
            base_point_split.setdefault(p, set()).add(r["meta"]["split_group"])
    eval_points = {p for r in evals for p in r["meta"]["points"]}
    rep["new_points"] = sorted({p for r in inc for p in r["meta"]["points"]} - set(base_point_split))
    rep["points_in_other_split"] = sorted({p for r in inc for p in r["meta"]["points"]
                                           if p in base_point_split and base_point_split[p] != {r["meta"]["split_group"]}})
    rep["points_in_eval"] = sorted({p for r in inc for p in r["meta"]["points"]} & eval_points)
    ic = {u["canonical"] for r in inc for u in r["expected"]["units"]}
    ec = {u["canonical"] for r in evals for u in r["expected"]["units"]}
    rep["canonical_overlap_eval"] = sorted(ic & ec)
    eh = {h for c in ec for h in splits.headwords(c)}
    rep["headword_overlap_eval"] = sorted({h for c in ic for h in splits.headwords(c)} & eh)
    rep["exact_duplicates_with_eval"] = [g for g in exact_groups(list(inc) + list(evals))
                                         if any(i.startswith("ext-evl") for i in g)]
    ne = near_pairs(inc, 0.5, other=evals)
    rep["near_pairs_eval"] = {"jaccard_ge_0.5": len(ne), "jaccard_ge_0.8": sum(1 for *_, s in ne if s >= 0.8),
                              "examples": ne[:10]}
    nb = near_pairs(inc, 0.5, other=boundary) if boundary else []
    rep["near_pairs_boundary"] = {"jaccard_ge_0.5": len(nb), "examples": nb[:10]}
    nbase = near_pairs(inc, 0.8, other=base)
    rep["near_duplicates_of_base"] = {"jaccard_ge_0.8": len(nbase), "examples": nbase[:10]}
    rep["within_increment"] = {"exact_duplicate_groups": exact_groups(inc),
                               "near_pairs_ge_0.8": near_pairs(inc, 0.8)}
    combined = splits.check(list(base) + list(inc), evals, boundary)
    rep["combined_split_check"] = {k: combined[k] for k in ("counts", "pass", "families_in_two_splits", "points_in_train_and_dev",
                                                             "points_in_train_and_eval", "canonical_overlap_train_eval")}
    rep["composition"] = {"by_mode": dict(Counter(r["meta"].get("style") for r in inc)),
                          "units_hist": dict(Counter(len(r["expected"]["units"]) for r in inc)),
                          "by_split_group": dict(Counter(r["meta"]["split_group"] for r in inc)),
                          "resolution": dict(Counter(r["input"]["resolution"] for r in inc)),
                          "zero_unit_categories": dict(Counter(r["input"]["effective_category"] for r in inc
                                                              if not r["expected"]["units"])),
                          "unit_records_with_category_other": sum(1 for r in inc if r["expected"]["units"]
                                                                  and r["input"]["effective_category"] == "other")}
    rep["pass"] = not (rep["structural_errors"] or rep["not_unreviewed"] or rep["duplicate_ids"]
                       or rep["families_shared_with_base"] or rep["new_points"] or rep["points_in_other_split"]
                       or rep["points_in_eval"] or rep["canonical_overlap_eval"] or rep["exact_duplicates_with_eval"]
                       or rep["near_pairs_eval"]["jaccard_ge_0.8"] or rep["within_increment"]["exact_duplicate_groups"]
                       or not combined["pass"]
                       or (isinstance(rep["production_validation"], dict)
                           and (rep["production_validation"]["invalid_ids"]
                                or rep["production_validation"]["units_changed_by_validation"])))
    return rep
