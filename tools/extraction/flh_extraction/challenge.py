"""Validation and leakage checks for the paired cue challenge slice.

  python3 -m flh_extraction challenge-check --challenge C.jsonl --train T [T2 …] --eval E.jsonl
         [--boundary B.jsonl] [--validated V.jsonl] --out REPORT.json

Failing checks (`pass` false):
  - structural record checks and honest unreviewed statuses;
  - every reference accepted by the production validator (`extraction-render
    expected`) with its units unchanged;
  - groups: exactly the variants aligned / conflicting / rb; identical learner
    text, context and reference inside a group; no two variants with the same
    model-visible input; the cue actually changes (category `other` flips
    between aligned and conflicting; rb is never `other`);
  - splits: one split per group (challenge_dev or challenge_test), both
    intents in both splits, families never shared between groups, and `sft`
    refuses every record;
  - against training (train and dev, base and increment): no point, canonical
    or headword in common, no exact duplicate and no near duplicate
    (word 3-gram Jaccard >= 0.8) of an input;
  - against the frozen evaluation and the boundary cases: no exact or near
    duplicate (>= 0.8) of an input; across unrelated groups: none either.
Reported: near pairs >= 0.5 against every pool and between groups, and the
objectives shared with the frozen evaluation (both are held out by design).
"""

from collections import Counter, defaultdict

from . import records, sft, splits
from .dedup import exact_groups, near_pairs

VARIANTS = ("aligned", "conflicting", "rb")
SPLITS = ("challenge_dev", "challenge_test")
CUE_FIELDS = ("effective_category", "effective_explanation", "resolution")


def groups_of(recs):
    g = defaultdict(list)
    for r in recs:
        g[r["meta"]["challenge"]["group_id"]].append(r)
    return dict(sorted(g.items()))


def _units(us):
    return [(u["kind"], u["canonical"], u["statement"].strip(), u["statement_zh"], u["example"], u["confidence"]) for u in us]


def _cross(recs, pool, label):
    ex = [g for g in exact_groups(list(recs) + list(pool)) if any(i.startswith("ext-chl") for i in g)
          and not all(i.startswith("ext-chl") for i in g)]
    ne = near_pairs(recs, 0.5, other=pool)
    return {"pool": label, "pool_records": len(pool), "exact_duplicates": ex, "near_pairs_ge_0.5": len(ne),
            "near_pairs_ge_0.8": sum(1 for *_, s in ne if s >= 0.8), "examples": ne[:5]}


def check(chl, train, evals, boundary=(), validated=None):
    rep = {"schema": "flh_extraction_challenge_check_v1", "records": len(chl)}
    rep["structural_errors"] = {r["id"]: e for r in chl for e in [records.structural_errors(r)] if e}
    rep["not_unreviewed"] = [r["id"] for r in chl if r["meta"].get("review_status") != "unreviewed"
                             or r["meta"].get("label_status") != "machine_authored_unreviewed"]
    if validated is not None:
        v = {x["id"]: x for x in validated}
        bad = [r["id"] for r in chl if not v.get(r["id"], {}).get("valid")]
        drift = [r["id"] for r in chl if v.get(r["id"], {}).get("valid")
                 and _units(v[r["id"]]["units"]) != _units(r["expected"]["units"])]
        rep["production_validation"] = {"valid": len(chl) - len(bad), "of": len(chl), "invalid_ids": bad,
                                        "units_changed_by_validation": drift}
    else:
        rep["production_validation"] = "not run (pass --validated)"

    # Groups: one intent, cues varied, nothing else.
    gs = groups_of(chl)
    probs = defaultdict(list)
    for gid, rs in gs.items():
        vs = sorted(r["meta"]["challenge"]["variant"] for r in rs)
        if vs != sorted(VARIANTS):
            probs["variants"].append(gid)
        if len({(r["input"]["original_input"], r["input"]["original_context"]) for r in rs}) != 1:
            probs["learner_text_differs"].append(gid)
        if len({repr(_units(r["expected"]["units"])) for r in rs}) != 1:
            probs["reference_differs"].append(gid)
        if len({tuple(r["input"][f] for f in CUE_FIELDS) for r in rs}) != len(rs):
            probs["identical_variants"].append(gid)
        by = {r["meta"]["challenge"]["variant"]: r for r in rs}
        intent = {r["meta"]["challenge"]["intent"] for r in rs}
        if len(intent) != 1 or (intent == {"extract"}) != bool(rs[0]["expected"]["units"]):
            probs["intent_mismatch"].append(gid)
        if set(by) == set(VARIANTS):
            a, c = (by[x]["input"]["effective_category"] == "other" for x in ("aligned", "conflicting"))
            if a == c or (intent == {"extract"} and a) or (intent == {"abstain"} and not a):
                probs["cue_does_not_flip"].append(gid)
            if by["rb"]["input"]["effective_category"] == "other":
                probs["rb_category_other"].append(gid)
        if len({r["meta"]["split_group"] for r in rs}) != 1 or rs[0]["meta"]["split_group"] not in SPLITS:
            probs["split_not_per_group"].append(gid)
        if len({r["meta"]["family_id"] for r in rs}) != 1:
            probs["family_differs_in_group"].append(gid)
    fam = Counter(rs[0]["meta"]["family_id"] for rs in gs.values())
    probs["family_shared_between_groups"] = sorted(f for f, n in fam.items() if n > 1)
    rep["groups"] = {"count": len(gs), "problems": {k: v for k, v in sorted(probs.items())}}
    split_intent = Counter((rs[0]["meta"]["split_group"], rs[0]["meta"]["challenge"]["intent"]) for rs in gs.values())
    rep["splits"] = {"groups_by_split_and_intent": {f"{s}/{i}": n for (s, i), n in sorted(split_intent.items())},
                     "records_by_split": dict(sorted(Counter(r["meta"]["split_group"] for r in chl).items())),
                     "both_intents_in_both_splits": all(split_intent[(s, i)] > 0 for s in SPLITS for i in ("extract", "abstain"))}
    _, refused = sft.build(chl, [])
    rep["splits"]["refused_by_sft"] = f"{len(refused)}/{len(chl)}"

    # Unrelated groups: one representative per group (variants share the learner text by design).
    reps = [rs[0] for rs in gs.values()]
    ne = near_pairs(reps, 0.5)
    rep["between_groups"] = {"exact_duplicates": exact_groups(reps), "near_pairs_ge_0.5": len(ne),
                             "near_pairs_ge_0.8": sum(1 for *_, s in ne if s >= 0.8), "examples": ne[:5]}

    # Training (base + increment, train and dev), evaluation, boundary.
    tr = [r for r in train if r["meta"]["split_group"] in ("train", "dev")]
    rep["against"] = {"train_dev": _cross(reps, tr, "train+dev"), "eval": _cross(reps, evals, "frozen eval"),
                      "boundary": _cross(reps, boundary, "boundary") if boundary else "not given"}
    cpts = {p for r in chl for p in r["meta"]["points"]}
    tpts = {p for r in tr for p in r["meta"]["points"]}
    cc = {u["canonical"] for r in chl for u in r["expected"]["units"]}
    tc = {u["canonical"] for r in tr for u in r["expected"]["units"]}
    th = {h for c in tc for h in splits.headwords(c)}
    rep["objectives"] = {"points_in_training": sorted(cpts & tpts), "canonicals_in_training": sorted(cc & tc),
                         "headwords_in_training": sorted({h for c in cc for h in splits.headwords(c)} & th),
                         "points_shared_with_frozen_eval": len(cpts & {p for r in evals for p in r["meta"]["points"]}),
                         "points": len(cpts)}
    rep["composition"] = {"by_variant_and_cue": dict(sorted(Counter(f"{r['meta']['challenge']['variant']}:{r['meta']['challenge']['cue']}"
                                                                    for r in chl).items())),
                          "units_hist": dict(sorted(Counter(len(r["expected"]["units"]) for r in chl).items())),
                          "resolution": dict(sorted(Counter(r["input"]["resolution"] for r in chl).items())),
                          "learner_text_languages": "French, English and Chinese learner messages"}
    pv = rep["production_validation"]
    against = [x for x in rep["against"].values() if isinstance(x, dict)]
    rep["pass"] = not (rep["structural_errors"] or rep["not_unreviewed"] or any(rep["groups"]["problems"].values())
                       or not rep["splits"]["both_intents_in_both_splits"] or len(refused) != len(chl)
                       or rep["between_groups"]["exact_duplicates"] or rep["between_groups"]["near_pairs_ge_0.8"]
                       or any(x["exact_duplicates"] or x["near_pairs_ge_0.8"] for x in against)
                       or rep["objectives"]["points_in_training"] or rep["objectives"]["canonicals_in_training"]
                       or rep["objectives"]["headwords_in_training"]
                       or (isinstance(pv, dict) and (pv["invalid_ids"] or pv["units_changed_by_validation"])))
    return rep
