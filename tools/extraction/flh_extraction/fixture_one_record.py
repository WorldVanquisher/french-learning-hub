"""One-record fixture (FLH-154 part 4, OFFLINE ONLY; not a scoring source).

  python3 -m flh_extraction one-record-fixture --out DIR [--fixture DIR] [--check]

From fixtures/one_record_v1/fixture.json alone (no Go, model, provider or
network) this builds:

  - the fixture slice, 10 rows around one synthetic learning record: the record
    and its follow-up thank-you (frozen part), their rb probes (probe.build with the
    recorded rule-based analyses) and two paired cue groups (challenge_test);
  - every synthetic system's raw predictions and validator-shaped results;
  - the existing reports on them, unchanged (evaluate, quality, paired consistency,
    decision.gates, decision.decide) and the experimental report with and without
    per-unit reviewer evidence (reviewer_evidence.py);
  - per case, which report accepts it and why.

It writes DIR/inputs/ (slice parts, predictions, reviewer queue and evidence
sets) and DIR/actual.json. --check compares actual.json with the hand-written
expectations in the fixture's expected.json and exits 1 on any difference. The
library path feeds results that are already validator-shaped; part4_checks.py
runs the same predictions through the production validator and the CLI.
"""

import copy
import json
from pathlib import Path

from . import challenge, comparison, decision, evaluate, experimental_report, matrix, paired, probe, quality
from . import reviewer_evidence as rev

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "one_record_v1"
SCHEMA = "flh154_one_record_fixture_actual_v1"
LIBRARY_MATRIX = "one-record-fixture-library"
SCOPE = "all fixture records"
CUE = {"aligned": "category and explanation agree with the reference decision",
       "conflicting": "category and explanation point the other way",
       "rb": "production default (rule-based) analysis, unreviewed"}
REVIEW_OK = [{"id": f"fixture-review-{k:02d}", "verdict": "accept"} for k in range(30)]
REVIEW_FAILED = [{"id": f"fixture-review-{k:02d}", "verdict": "reject" if k < 6 else "accept"} for k in range(30)]
LOSSES = [{"dev_loss": 1.2}, {"dev_loss": 1.0}, {"dev_loss": 0.9}]
INPUT_MANIFEST = {"files": {"sft-train.jsonl": {"sha256": "fixture-train"}, "sft-dev.jsonl": {"sha256": "fixture-dev"}}}
RUN_MANIFEST = {"train_sha256": "fixture-train", "dev_sha256": "fixture-dev", "suitable_for_production": False, "smoke": False}
REVIEWER = "fixture reviewer (synthetic)"
DATE = "2026-11-17"


def load(d=FIXTURE_DIR):
    return json.loads((Path(d) / "fixture.json").read_text(encoding="utf-8"))


def systems(fx):
    return {k: v for k, v in fx["systems"].items() if k != "note"}


def cases(fx):
    return {c["case"]: c for c in fx["cases"]}


def build(fx):
    """{"frozen", "rb", "challenge"} record lists (the comparison-slice parts)."""
    src = {"record": fx["record"], "follow_up": fx["follow_up"]}
    evals = []
    for name in ("record", "follow_up"):
        r = copy.deepcopy(src[name])
        r["meta"]["fixture_source"] = name
        evals.append(r)
    an = [{"id": r["id"], **fx["rule_based_analyses"][r["id"]]} for r in evals]
    rb = probe.build(evals, an, "rb")
    chl = []
    for g in fx["challenge"]["groups"]:
        s = src[g["source"]]
        a = fx["rule_based_analyses"][s["id"]]
        for v in challenge.VARIANTS:
            rec = copy.deepcopy(s)
            cue = g["variants"].get(v) or {"effective_category": a["effective_category"],
                                           "effective_explanation": a["effective_explanation"], "resolution": "unreviewed"}
            rec["input"].update(cue)
            rec["id"] = f"{g['group_id']}-{v}"
            rec["meta"].update(case_type=g["case_type"], split_group="challenge_test", fixture_source=g["source"],
                               challenge={"cue": CUE[v], "group_id": g["group_id"], "intent": g["intent"],
                                          "reference": "identical across the group's variants",
                                          "slice": "flh154_one_record_fixture_v1", "variant": v})
            chl.append(rec)
    return {"frozen": evals, "rb": rb, "challenge": chl}


def slice_refs(parts):
    return parts["frozen"] + parts["rb"] + parts["challenge"]


def outputs(fx, refs):
    """({system: raw prediction rows}, {system: validator-shaped results})."""
    cs = cases(fx)
    raw, res = {}, {}
    for s, plan in systems(fx).items():
        raw[s], res[s] = [], []
        for r in refs:
            out = cs[plan[r["meta"]["fixture_source"]]]["output"]
            raw[s].append({"id": r["id"], "output_text": json.dumps(out, ensure_ascii=False), "stopped": "eos"})
            res[s].append({"id": r["id"], "valid": True, "units": copy.deepcopy(out["units"]), "error_class": None})
    return raw, res


def comparison_report(refs, results, matrix_sha256=LIBRARY_MATRIX):
    """matrix.compare's per-system scoring for results that are already
    validator-shaped (matrix.account_results path), without the matrix checks."""
    ids = [r["id"] for r in refs]
    comp = {"schema": "flh_extractor_comparison_report_v1", "matrix_sha256": matrix_sha256, "systems": {}, "refused": []}
    accounts = {}
    for s, rows in results.items():
        acc = matrix.account_results(ids, rows)
        accounts[s] = acc
        comp["systems"][s] = {"status": "MEASURED", "rows": {k: acc[k] for k in ("references", "scorable", "status_counts",
                                                                                  "unknown_ids", "unknown_id_rows")},
                              "metrics": matrix._metrics(refs, comparison.scored_results(acc), None)}
    comp["real_runs_measured"] = 0
    return comp, accounts


def evidence_sets(fx, q):
    """Synthetic reviewer evidence: what a reviewer records if each case behaves
    as authored (fixture.json `reviewer`), plus the broken variants the contract
    must handle. Never a real review."""
    cs, plans = cases(fx), systems(fx)
    src_of = {}
    for part in build(fx).values():
        for r in part:
            src_of[r["id"]] = r["meta"]["fixture_source"]
    full = []
    for s, v in q["systems"].items():
        for i in v["items"]:
            ans = cs[plans[s][src_of[i["id"]]]]["reviewer"][i["unit"]]
            full.append({"schema": rev.EVIDENCE_SCHEMA, "system": s, "id": i["id"], "unit": i["unit"], "unit_sha256": i["unit_sha256"],
                         **ans, "reviewer": REVIEWER, "date": DATE, "note": ""})
    blank = rev.template(q)
    first_correct = next(k for k, r in enumerate(full) if r["system"] == "correct")
    first_drift = next(k for k, r in enumerate(blank) if r["system"] == "bilingual_drift")
    other = cs["unsupported_claim"]["output"]["units"][0]
    stale = copy.deepcopy(full)
    stale[first_correct]["unit_sha256"] = rev.unit_sha256(other)
    fails_correct = copy.deepcopy(full)
    fails_correct[first_correct].update(claim_true="no", note="synthetic: a reviewer records a failure on the correct system")
    explicit_no = copy.deepcopy(blank)
    explicit_no[first_drift].update(zh_same="no", reviewer=REVIEWER, date=DATE)
    return {"none": None, "blank": blank,
            "partial": [r if r["system"] == "correct" else b for r, b in zip(full, blank)],
            "full": full, "stale": stale, "fails_correct": fails_correct, "explicit_no_incomplete": explicit_no,
            "duplicate": full + [dict(full[first_correct])],
            "invalid": [dict(full[0], claim_true="maybe")] + full[1:]}


def _verdict(rep):
    out = {"verdict": rep["verdict"], "preference": rep.get("preference"), "production_go": rep["production_go"],
           "systems": {s: {"eligible": v["eligible"], "excluded_by_exact_gates": bool(v.get("excluded_by_exact_gates")),
                           "excluded_by_human_evidence": bool(v.get("excluded_by_human_evidence")),
                           "reviewer": (v.get("reviewer") or {}).get("status"),
                           "excluded_by_reviewer_evidence": v.get("excluded_by_reviewer_evidence") or []}
                       for s, v in rep["systems"].items()}}
    return out


def without_reviewer(sysrep):
    """Eligibility from the exact gates and the aggregate human evidence only (the
    part-3 draft's rule), for the before/after table."""
    v = sysrep
    if v.get("incomplete_run"):
        return None
    if v.get("excluded_by_exact_gates") or v.get("excluded_by_human_evidence"):
        return False
    pend = [c for c in (v.get("exact") or []) + (v.get("human") or []) if c["status"] == "PENDING"]
    return None if pend else True


def experimental_scenarios(fx, comp, q, ev):
    human = fx["assumed_human_evidence"]["experimental"]
    other_q = dict(q, matrix_sha256="another-comparison")
    spec = {
        "E0 no human evidence, no reviewer queue": (None, REVIEW_OK, None, None),
        "E1 assumed aggregates, no reviewer queue": (human, REVIEW_OK, None, None),
        "E2 assumed aggregates, queue, no evidence file": (human, REVIEW_OK, q, ev["none"]),
        "E3 assumed aggregates, queue, blank template": (human, REVIEW_OK, q, ev["blank"]),
        "E4 assumed aggregates, only the correct system reviewed": (human, REVIEW_OK, q, ev["partial"]),
        "E5 assumed aggregates, every unit reviewed": (human, REVIEW_OK, q, ev["full"]),
        "E6 every unit reviewed, one review bound to another output (stale hash)": (human, REVIEW_OK, q, ev["stale"]),
        "E7 every unit reviewed, the reviewer fails the correct system's unit": (human, REVIEW_OK, q, ev["fails_correct"]),
        "E8 one explicit failure (bilingual_drift), everything else blank": (human, REVIEW_OK, q, ev["explicit_no_incomplete"]),
        "E9 every unit reviewed, one unit reviewed twice": (human, REVIEW_OK, q, ev["duplicate"]),
        "E10 every unit reviewed, queue built for another comparison": (human, REVIEW_OK, other_q, ev["full"]),
        "E11 every unit reviewed, failed reference review (6 of 30 rejected)": (human, REVIEW_FAILED, q, ev["full"]),
    }
    out = {}
    for name, (h, review, qq, rows) in spec.items():
        rep = experimental_report.report(comp, h, review, qq, rows)
        out[name] = _verdict(rep)
        if name.startswith("E1 "):
            out[name]["eligible_without_reviewer_criterion"] = {s: without_reviewer(v) for s, v in rep["systems"].items()}
    try:
        rev.load_evidence(ev["invalid"])
        out["E12 an answer that is not yes, no or blank"] = {"refused": None}
    except ValueError as e:
        out["E12 an answer that is not yes, no or blank"] = {"refused": str(e)}
    return out


def slot_comparison(comp, slots):
    return {**comp, "systems": {slot: comp["systems"][s] for slot, s in slots.items()}}


def decision_scenarios(fx, comp):
    out = {}
    for name, slots in fx["cli_scenarios"].items():
        if name == "note":
            continue
        c = slot_comparison(comp, slots)
        human = {slot: fx["assumed_human_evidence"]["decision"][s] for slot, s in slots.items()}
        rep = decision.decide(c, human, REVIEW_OK, LOSSES, RUN_MANIFEST, INPUT_MANIFEST)
        out[name] = {"slots": slots, "verdict": rep["verdict"], "winner": rep["winner"],
                     "winner_system": slots.get(rep["winner"]) if rep["winner"] else None,
                     "eligible": {slots[k]: v["eligible"] for k, v in rep["systems"].items()}, "reasons": rep["reasons"]}
    return out


def _accept(ok):
    return "accept" if ok else "reject"


def case_table(fx, parts, comp, xr_before, xr_after):
    refs = slice_refs(parts)
    out = {}
    for c in fx["cases"]:
        rows = [r for r in refs if r["meta"]["fixture_source"] == c["source"]]
        res = [{"id": r["id"], "valid": True, "units": copy.deepcopy(c["output"]["units"]), "error_class": None} for r in rows]
        ev = evaluate.evaluate(rows, res)
        q = quality.report(rows, res)
        ab, uc = q["abstention"], q["unit_count"]
        exact_ok = ab["correct_empty"] == ab["zero_unit_refs"] and ab["unit_refs_answered_empty"] == 0 and uc["exact_rate"] == 1.0
        gh, bh, sh = q["grounding"]["heuristic"], q["bilingual"]["heuristic"], q["semantic"]["heuristic"]
        heur_ok = not sh["errors"] and gh["not_anchored"] == 0 and gh["anchored_only_in_explanation"] == 0 and not bh.get("units_flagged")
        grp = [r for r in rows if r["meta"].get("challenge")]
        pc = paired.report(grp, [x for x in res if x["id"] in {r["id"] for r in grp}])
        s = c["system"]
        gates = decision.gates(comp["systems"][s])
        out[c["case"]] = {
            "bad": c["bad"], "source": c["source"], "rows": len(rows), "system": s,
            "evaluate (heuristic)": {"result": _accept(not ev["errors"] and ev["example_perfect_rate"] == 1.0), "errors": ev["errors"],
                                     "unit_f1": ev["unit_f1"]},
            "quality exact (abstention, unit count)": {"result": _accept(exact_ok), "correct_empty": f"{ab['correct_empty']}/{ab['zero_unit_refs']}",
                                                       "false_extraction_on_zero_refs": ab["false_extraction_on_zero_refs"],
                                                       "unit_refs_answered_empty": ab["unit_refs_answered_empty"],
                                                       "exact_unit_count_rate": uc["exact_rate"]},
            "quality heuristic (matcher, grounding, bilingual)": {"result": _accept(heur_ok), "matcher_errors": sh["errors"],
                                                                  "anchored_in_learner_text": gh["anchored_in_learner_text"],
                                                                  "not_anchored": gh["not_anchored"],
                                                                  "bilingual_flagged_units": bh.get("units_flagged", 0)},
            "paired consistency (exact, its cue group)": {"result": _accept(pc["all"]["paired_correct"]["count"] == pc["all"]["groups"]),
                                                          "decision_consistent": pc["all"]["decision_consistent"]["count"],
                                                          "paired_correct": pc["all"]["paired_correct"]["count"]},
            "decision.gates (exact, its system)": {"result": _accept(all(g["status"] == "PASS" for g in gates)),
                                                   "failed": [g["criterion"] for g in gates if g["status"] == "FAIL"]},
            "experimental report without reviewer evidence (its system, E1)":
                {"result": {True: "eligible", False: "excluded", None: "pending"}[xr_before["eligible_without_reviewer_criterion"][s]]},
            "experimental report with reviewer evidence (its system, E5)":
                {"result": {True: "eligible", False: "excluded", None: "pending"}[xr_after["systems"][s]["eligible"]],
                 "excluded_by_reviewer_evidence": xr_after["systems"][s]["excluded_by_reviewer_evidence"]},
            "why": c["why"]}
    return out


def run(fx, out_dir=None):
    parts = build(fx)
    refs = slice_refs(parts)
    raw, res = outputs(fx, refs)
    comp, accounts = comparison_report(refs, res)
    q = rev.queue(refs, accounts, [r["id"] for r in refs], LIBRARY_MATRIX, "library (no slice file)", SCOPE)
    ev = evidence_sets(fx, q)
    xs = experimental_scenarios(fx, comp, q, ev)
    doc = {"schema": SCHEMA, "status": "OFFLINE ONLY; synthetic fixture; library path (validator-shaped results)",
           "slice": {p: [r["id"] for r in rs] for p, rs in parts.items()},
           "scoring_version": comparison.scoring_version()["sha256"],
           "reviewer_queue": {s: {"units_in_scope": v["units_in_scope"],
                                  "accepted_by_every_automatic_check": sum(i["automatic"]["accepted_by_every_automatic_check"] for i in v["items"]),
                                  "abstentions_in_scope": len(v["abstentions_in_scope"])} for s, v in q["systems"].items()},
           "cases": case_table(fx, parts, comp, xs["E1 assumed aggregates, no reviewer queue"],
                               xs["E5 assumed aggregates, every unit reviewed"]),
           "experimental_scenarios": xs,
           "decision_scenarios": decision_scenarios(fx, comp)}
    if out_dir:
        d = Path(out_dir) / "inputs"
        d.mkdir(parents=True, exist_ok=True)
        for p, rs in parts.items():
            matrix.write_jsonl(d / f"{p}.jsonl", rs)
        for s in raw:
            matrix.write_jsonl(d / f"predictions-{s}.jsonl", raw[s])
        (d / "reviewer-queue.json").write_text(json.dumps(q, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        for k, rows in ev.items():
            if rows is not None:
                matrix.write_jsonl(d / f"reviewer-evidence-{k}.jsonl", rows)
        (Path(out_dir) / "actual.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return doc


def project(doc):
    """The fields expected.json pins (hand-written expectations)."""
    return {"cases": {k: {col: v[col]["result"] for col in v if isinstance(v[col], dict) and "result" in v[col]}
                      for k, v in doc["cases"].items()},
            "experimental_scenarios": {k: ({"verdict": v["verdict"], "preference": v["preference"], "production_go": v["production_go"],
                                            "eligible": {s: x["eligible"] for s, x in v["systems"].items()}}
                                           if "verdict" in v else {"refused": v["refused"] is not None})
                                       for k, v in doc["experimental_scenarios"].items()},
            "decision_scenarios": {k: {"verdict": v["verdict"], "winner_system": v["winner_system"], "eligible": v["eligible"]}
                                   for k, v in doc["decision_scenarios"].items()}}


def diff(expected, actual, path=""):
    out = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for k in sorted(set(expected) | set(actual)):
            if k not in actual:
                out.append(f"{path}/{k}: expected {json.dumps(expected[k], ensure_ascii=False)}, missing")
            elif k not in expected:
                out.append(f"{path}/{k}: not expected, got {json.dumps(actual[k], ensure_ascii=False)}")
            else:
                out += diff(expected[k], actual[k], f"{path}/{k}")
    elif expected != actual:
        out.append(f"{path}: expected {json.dumps(expected, ensure_ascii=False)}, got {json.dumps(actual, ensure_ascii=False)}")
    return out
