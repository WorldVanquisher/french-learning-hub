"""Generate the targeted training increment v2 (flh_extraction_candidate_v1).

  python3 -I -B generate_increment.py OUT_DIR
      writes OUT_DIR/increment_candidates.jsonl (deterministic)
  python3 -I -B generate_increment.py --analysis-requests REQUESTS.jsonl
      the inputs whose effective category and explanation must come from the
      production default analyzer: feed them to
      `extraction-render analyze -in REQUESTS.jsonl -out ANALYSES.jsonl`
  python3 -I -B generate_increment.py --freeze ANALYSES.jsonl
      (re)writes increment_v2_rule_based.json from that output

Every record is synthetic, hand-authored (bank_increment_v2.py), unreviewed and
labelled machine_authored_unreviewed. Units are training-bank points reused
verbatim; a record's split is its points' split (zero-unit records: a hash of
the text, as in generate_train.py). Records the production analyzer would see
as `unreviewed` carry the analyzer's frozen category and explanation.
"""

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import CONFIDENCE_POLICY  # noqa: E402
import bank_train_a, bank_train_b, bank_train_c, bank_increment_v2  # noqa: E402,E401

GENERATOR = "flh_extraction_increment_generator_v2"
SCHEMA = "flh_extraction_candidate_v1"
INCREMENT = "extraction_increment_v2"
AUTHORING = ("claude-code local authoring session 2026-11-12 (hand-written increment after the failure-mode audit; "
             "no provider call)")
FROZEN = HERE / "increment_v2_rule_based.json"
ANALYZER = "rule-based:v2:fr_l2_taxonomy_v1"
POINTS = {p["id"]: p for p in bank_train_a.POINTS + bank_train_b.POINTS + bank_train_c.POINTS}


def h(s):
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def split_group(point_id):
    return "dev" if h(point_id) % 10 == 0 else "train"


def key(rec):
    return hashlib.sha256(json.dumps([rec["text"], rec["ctx"]], ensure_ascii=False).encode()).hexdigest()[:16]


def unit(p, conf=0.9):
    return {"kind": p["kind"], "canonical": p["canonical"], "statement": p["en"], "statement_zh": p["zh"],
            "example": p["example"], "confidence": conf}


def load_frozen():
    if not FROZEN.is_file():
        return {}
    data = json.loads(FROZEN.read_text(encoding="utf-8"))
    if data.get("analyzer") != ANALYZER:
        raise SystemExit(f"{FROZEN.name}: analyzer {data.get('analyzer')!r} is not {ANALYZER!r}")
    return data["analyses"]


def build():
    frozen = load_frozen()
    recs, missing = [], []
    for k, r in enumerate(bank_increment_v2.RECORDS, 1):
        ps = [POINTS[pid] for pid in r["points"]]
        groups = {split_group(p["id"]) for p in ps}
        if len(groups) > 1:
            raise SystemExit(f"record {k}: points from train and dev in one record")
        if len({p["group"] for p in ps}) < len(ps):
            raise SystemExit(f"record {k}: two points of one topic group")
        group = groups.pop() if groups else ("dev" if h(r["text"]) % 10 == 0 else "train")
        if r["expl"] == "RB":
            a = frozen.get(key(r))
            if a is None:
                missing.append(key(r))
                continue
            cat, expl, analysis = a["effective_category"], a["effective_explanation"], ANALYZER
        elif r["expl"] == "POINT":
            if len(ps) == 1:
                cat, expl = ps[0]["category"], ps[0]["expl"]
            else:
                cat, expl = "mixed", " ".join(p["expl"] for p in ps)
            analysis = "point explanation (correct analysis)"
        else:
            cat, expl, analysis = r["cat"], r["expl"], "literal (authored)"
        band = max((p["band"] for p in ps), key=["A1", "A2", "B1"].index) if ps else None
        family = f"inc2:{r['mode']}:" + ("+".join(sorted(p["id"] for p in ps)) if ps else key(r))
        meta = {"family_id": family, "split_group": group, "points": [p["id"] for p in ps],
                "topics": sorted({p["topic"] for p in ps}), "band": band, "style": r["mode"],
                "case_type": r["mode"] if ps or r["mode"] != "zero_production_cues" else "zero_production_cues",
                "origin": "synthetic", "review_status": "unreviewed", "label_status": "machine_authored_unreviewed",
                "authoring": AUTHORING, "generator": GENERATOR, "increment": INCREMENT,
                "confidence_policy": CONFIDENCE_POLICY, "explanation_source": analysis,
                "rationale": r["why"], "input_key": key(r)}
        inp = {"entry_id": 0, "original_input": r["text"], "original_context": r["ctx"], "effective_category": cat,
               "effective_explanation": expl, "resolution": r["res"]}
        recs.append({"schema": SCHEMA, "input": inp, "expected": {"units": [unit(p) for p in ps]}, "meta": meta})
    if missing:
        raise SystemExit(f"{len(missing)} rule-based analyses missing from {FROZEN.name}; run --analysis-requests, "
                         "extraction-render analyze and --freeze (see the module docstring)")
    fams = Counter(r["meta"]["family_id"] for r in recs)
    for r in recs:
        if fams[r["meta"]["family_id"]] > 1:
            raise SystemExit(f"duplicate family {r['meta']['family_id']}")
    for k, r in enumerate(recs, 1):
        r["id"] = f"ext-trn-i2-{k:04d}"
    return recs


def analysis_requests(path):
    rows = []
    for r in bank_increment_v2.RECORDS:
        if r["expl"] == "RB":
            rows.append({"id": key(r), "input": {"entry_id": 0, "original_input": r["text"], "original_context": r["ctx"],
                                                 "effective_category": "other", "effective_explanation": "-",
                                                 "resolution": "unreviewed"}})
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
    with open(out / "increment_candidates.jsonl", "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"increment_candidates": len(recs), "by_mode": Counter(r["meta"]["style"] for r in recs),
                      "units_hist": Counter(len(r["expected"]["units"]) for r in recs),
                      "by_split_group": Counter(r["meta"]["split_group"] for r in recs),
                      "resolution": Counter(r["input"]["resolution"] for r in recs),
                      "category_other": sum(r["input"]["effective_category"] == "other" for r in recs)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
