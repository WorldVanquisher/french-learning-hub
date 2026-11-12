"""Generate the paired cue challenge slice v1 (flh_extraction_candidate_v1,
evaluation only).

  python3 -I -B generate_challenge.py OUT_DIR
      writes OUT_DIR/challenge_candidates.jsonl (deterministic)
  python3 -I -B generate_challenge.py --analysis-requests REQUESTS.jsonl
      the group inputs for `extraction-render analyze -in REQUESTS.jsonl -out ANALYSES.jsonl`
  python3 -I -B generate_challenge.py --freeze ANALYSES.jsonl
      (re)writes challenge_v1_rule_based.json from that output

Every record is synthetic, hand-authored (bank_challenge_v1.py), unreviewed and
labelled machine_authored_unreviewed. Splits are assigned per GROUP, never per
record: the three variants of a group always share `challenge_dev` or
`challenge_test`. Within each intent (extract / abstain), groups are ordered
by a hash of their slug and the first quarter (rounded up) goes to
`challenge_dev`, so both splits hold both intents. `sft` refuses both splits.
"""

import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import CONFIDENCE_POLICY  # noqa: E402
import bank_eval, bank_challenge_v1  # noqa: E402,E401

GENERATOR = "flh_extraction_challenge_generator_v1"
SLICE = "flh_extraction_challenge_v1"
SCHEMA = "flh_extraction_candidate_v1"
AUTHORING = ("claude-code local authoring session 2026-11-12 (hand-written paired cue challenge; evaluation only; "
             "no provider call)")
FROZEN = HERE / "challenge_v1_rule_based.json"
ANALYZER = "rule-based:v2:fr_l2_taxonomy_v1"
POINTS = {p["id"]: p for p in bank_eval.POINTS}
VARIANTS = ("aligned", "conflicting", "rb")
DEV_SHARE = 0.25


def h(s):
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def key(g):
    return hashlib.sha256(json.dumps([g["text"], g["ctx"]], ensure_ascii=False).encode()).hexdigest()[:16]


def unit(p, conf):
    return {"kind": p["kind"], "canonical": p["canonical"], "statement": p["en"], "statement_zh": p["zh"],
            "example": p["example"], "confidence": conf}


def assign_splits(groups):
    """{slug: split}, per group and stratified by intent."""
    out = {}
    for intent in ("extract", "abstain"):
        gs = sorted((g for g in groups if g["intent"] == intent), key=lambda g: h(g["slug"]))
        n_dev = math.ceil(len(gs) * DEV_SHARE)
        for k, g in enumerate(gs):
            out[g["slug"]] = "challenge_dev" if k < n_dev else "challenge_test"
    return out


def load_frozen():
    if not FROZEN.is_file():
        return {}
    data = json.loads(FROZEN.read_text(encoding="utf-8"))
    if data.get("analyzer") != ANALYZER:
        raise SystemExit(f"{FROZEN.name}: analyzer {data.get('analyzer')!r} is not {ANALYZER!r}")
    return data["analyses"]


def cues(g, variant, index, frozen):
    """(category, explanation, resolution, explanation_source, cue label)."""
    if variant == "rb":
        a = frozen[key(g)]
        return a["effective_category"], a["effective_explanation"], "unreviewed", ANALYZER, "production_rule_based"
    if g["intent"] == "extract":
        if variant == "aligned":
            ps = [POINTS[p] for p in g["points"]]
            cat = ps[0]["category"] if len(ps) == 1 else "mixed"
            return cat, g["aligned"], "accepted", "literal (authored, correct)", "aligned_objective_category"
        if index % 2 == 0:
            expl = bank_challenge_v1.DISMISSIVE[(index // 2) % len(bank_challenge_v1.DISMISSIVE)]
            return "other", expl, "unreviewed", "literal (authored, wrong)", "other_dismissive"
        return "other", bank_challenge_v1.NO_SUMMARY, "unreviewed", "literal (authored, no summary)", "other_no_summary"
    if variant == "aligned":
        return "other", g["aligned"], "accepted", "literal (authored, correct)", "aligned_other_abstention"
    cat, expl = g["conflict"]
    return cat, expl, "unreviewed", "literal (authored, names a rule not raised)", "real_category_rule_not_raised"


def build():
    groups = bank_challenge_v1.GROUPS
    slugs = Counter(g["slug"] for g in groups)
    if any(n > 1 for n in slugs.values()):
        raise SystemExit("duplicate group slug")
    used = Counter(p for g in groups for p in g["points"])
    if any(n > 1 for n in used.values()):
        raise SystemExit("a point is used by two groups")
    frozen = load_frozen()
    missing = [key(g) for g in groups if key(g) not in frozen]
    if missing:
        raise SystemExit(f"{len(missing)} rule-based analyses missing from {FROZEN.name}; run --analysis-requests, "
                         "extraction-render analyze and --freeze (see the module docstring)")
    split = assign_splits(groups)
    recs = []
    for gi, g in enumerate(groups, 1):
        ps = [POINTS[p] for p in g["points"]]
        units = [unit(p, c) for p, c in zip(ps, g["conf"])]
        gid = f"chl-g{gi:02d}"
        for variant in VARIANTS:
            cat, expl, res, source, cue = cues(g, variant, gi, frozen)
            band = max((p["band"] for p in ps), key=["A1", "A2", "B1"].index) if ps else None
            meta = {"family_id": f"chl:{g['slug']}", "split_group": split[g["slug"]], "points": [p["id"] for p in ps],
                    "topics": sorted({p["topic"] for p in ps}), "band": band, "style": "paired_cue_challenge",
                    "case_type": f"challenge_{g['intent']}", "origin": "synthetic", "review_status": "unreviewed",
                    "label_status": "machine_authored_unreviewed", "authoring": AUTHORING, "generator": GENERATOR,
                    "confidence_policy": CONFIDENCE_POLICY, "explanation_source": source, "rationale": g["why"],
                    "input_key": key(g),
                    "challenge": {"slice": SLICE, "group_id": gid, "variant": variant, "intent": g["intent"], "cue": cue,
                                  "reference": "identical across the group's variants"}}
            inp = {"entry_id": 0, "original_input": g["text"], "original_context": g["ctx"], "effective_category": cat,
                   "effective_explanation": expl, "resolution": res}
            recs.append({"schema": SCHEMA, "input": inp, "expected": {"units": [dict(u) for u in units]}, "meta": meta})
    for k, r in enumerate(recs, 1):
        r["id"] = f"ext-chl-{k:04d}"
    return recs


def analysis_requests(path):
    rows = [{"id": key(g), "input": {"entry_id": 0, "original_input": g["text"], "original_context": g["ctx"],
                                     "effective_category": "other", "effective_explanation": "-", "resolution": "unreviewed"}}
            for g in bank_challenge_v1.GROUPS]
    Path(path).write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in rows), encoding="utf-8")
    print(json.dumps({"analysis_requests": len(rows)}))


def freeze(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if {r["analyzer"] for r in rows} != {ANALYZER}:
        raise SystemExit(f"expected only {ANALYZER} analyses")
    data = {"analyzer": ANALYZER, "source": "extraction-render analyze (internal/analyzer rule engine, offline)",
            "analyses": {r["id"]: {"effective_category": r["effective_category"],
                                   "effective_explanation": r["effective_explanation"]} for r in rows}}
    FROZEN.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"frozen": len(rows), "categories": Counter(r["effective_category"] for r in rows)}))


def main(argv):
    if argv[:1] == ["--analysis-requests"]:
        return analysis_requests(argv[1])
    if argv[:1] == ["--freeze"]:
        return freeze(argv[1])
    out = Path(argv[0])
    recs = build()
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "challenge_candidates.jsonl", "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"challenge_candidates": len(recs), "groups": len(bank_challenge_v1.GROUPS),
                      "by_split_and_intent": Counter(f"{r['meta']['split_group']}/{r['meta']['challenge']['intent']}"
                                                     for r in recs),
                      "by_variant_category_other": Counter(f"{r['meta']['challenge']['variant']}:"
                                                           f"{r['input']['effective_category'] == 'other'}" for r in recs),
                      "units_hist": Counter(len(r["expected"]["units"]) for r in recs)}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
