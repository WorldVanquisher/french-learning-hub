"""FLH-154 part 3 (items 41-46, 52-53, 57-58): offline checks (OFFLINE ONLY).

  python3 -I -B docs/validation/FLH-154/part3_checks.py --repo . --pipeline OUT [--pipeline-before OUT0] --out docs/validation/FLH-154

OUT is a `comparison_pipeline.sh` output; OUT0 an earlier one (to show that
nothing published changed). Writes OUT/part3-checks.json and .md, and the
minimal G5 fixture under OUT/fixtures/. Synthetic systems only; the
production validator runs in-process. No provider, AWS, model or download;
the pinned scorer, the frozen evaluation and the published digests are only read.
"""

import argparse
import hashlib
import itertools
import json
import math
import re
import sys
import tempfile
from collections import Counter
from fractions import Fraction
from pathlib import Path

A = argparse.ArgumentParser()
A.add_argument("--repo", required=True)
A.add_argument("--pipeline", required=True)
A.add_argument("--pipeline-before")
A.add_argument("--out", required=True)
ARGS = A.parse_args()
REPO, OUT = Path(ARGS.repo).resolve(), Path(ARGS.pipeline).resolve()
TOOLS = REPO / "tools" / "extraction"
DEPLOY = REPO / "deploy" / "aws" / "sagemaker-extractor"
sys.path.insert(0, str(TOOLS))

from flh_extraction import comparison, controls, decision, evaluate, experimental_report as xr, matrix, quality  # noqa: E402
from flh_extraction import reviewer_evidence as rev  # noqa: E402

BIN = OUT / "bin" / "extraction-render"
VALIDATE = controls.render_validator(BIN, Path(tempfile.mkdtemp(prefix="flh154p3-")) / "v")
SLICE = OUT / "slice" / "comparison-slice.jsonl"
REFS = [json.loads(x) for x in SLICE.read_text(encoding="utf-8").splitlines() if x.strip()]
IDS = [r["id"] for r in REFS]
INPUTS = {r["id"]: r["input"] for r in REFS}
PART = {r["id"]: matrix.part_of(r) for r in REFS}
FROZEN = [r for r in REFS if PART[r["id"]] == "frozen"]
R = {}


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def run(rows):
    acc = comparison.account_with_validator(IDS, INPUTS, rows, VALIDATE)
    res = comparison.scored_results(acc)
    sysrep = {"status": "MEASURED", "rows": {k: acc[k] for k in ("references", "scorable", "status_counts", "unknown_ids", "unknown_id_rows")},
              "metrics": matrix._metrics(REFS, res, rows)}
    return acc, res, sysrep


def other_unit(k, units):
    n = len(REFS)
    for step in range(1, n):
        o = REFS[(k + 37 * step) % n]["expected"]["units"]
        if o and all(o[0]["canonical"] != u["canonical"] for u in units):
            return dict(o[0])
    return None


def system(name):
    if name in ("oracle", "over_abstain", "unsupported_swap", "bilingual_drift", "false_claim", "over_split", "merge",
                "duplicate", "hallucinate_on_zero", "struct_truncated"):
        return controls.outputs(REFS, name)
    if name == "unsupported_extra":       # every unit reference keeps its units and gains one unrelated unit
        rows = []
        for k, r in enumerate(REFS):
            units = [dict(u) for u in r["expected"]["units"]]
            if units:
                units.append(other_unit(k, units))
            rows.append({"id": r["id"], "input": r["input"], "output_text": json.dumps({"units": units}, ensure_ascii=False)})
        return rows
    raise KeyError(name)


def canon(c):
    return re.sub(r" \(\d\)$", "", c)


def same_objective(pred_canonical, ref_canonical):
    """Synthetic outputs keep their source's canonical: equal after the over-split suffix,
    or a merge "a / b" built by controls.py from two reference canonicals."""
    pc = canon(pred_canonical)
    return pc == ref_canonical or pc.startswith(ref_canonical + " / ") or pc.endswith(" / " + ref_canonical)


# ---------------------------------------------------------------- 41/42 G5 trace and categories
def trace(name, rows):
    acc, res, _ = run(rows)
    st = {r["id"]: r["status"] for r in acc["rows"]}
    rz = {x["id"]: x for x in res}
    fz_res = [rz[r["id"]] for r in FROZEN]
    q, e = quality.report(FROZEN, fz_res), evaluate.evaluate(FROZEN, fz_res)
    cats = Counter()
    per_row = []
    false_match = unmatched_pred = unmatched_ref_valid = unmatched_ref_invalid = 0
    for r in FROZEN:
        refu = r["expected"]["units"]
        s = st[r["id"]]
        valid = s in comparison.SCORABLE
        pred = rz[r["id"]]["units"] if valid else []
        if valid and refu and pred:
            sim = [[evaluate.similarity(p, x) for x in refu] for p in pred]
            pairs = evaluate.best_assignment(sim)
            false_match += sum(1 for p, x in pairs if not same_objective(pred[p]["canonical"], refu[x]["canonical"]))
            unmatched_pred += len(pred) - len(pairs)
            unmatched_ref_valid += len(refu) - len(pairs)
        elif valid:
            unmatched_pred += len(pred)
            unmatched_ref_valid += len(refu)
        else:
            unmatched_ref_invalid += len(refu)
        key = ("reference has units" if refu else "reference empty") + " / " + ("valid output" if valid else "non-scorable output")
        cats[key] += 1
        if not valid and refu:
            per_row.append({"id": r["id"], "status": s, "reference_units": len(refu),
                            "evaluate": "reference units counted as missed; row counted as 'answered empty'",
                            "quality": "row left out of unit F1 and of 'answered empty'"})
    out = {"rows_by_category": dict(sorted(cats.items())),
           "false_matches_valid_rows": false_match, "unmatched_predicted_units_valid_rows": unmatched_pred,
           "unmatched_reference_units_valid_rows": unmatched_ref_valid,
           "reference_units_of_non_scorable_rows": unmatched_ref_invalid,
           "quality": {"unit_f1": q["semantic"]["heuristic"]["unit_f1"], "recall": q["semantic"]["heuristic"]["unit_recall"],
                       "precision": q["semantic"]["heuristic"]["unit_precision"], "examples_in_f1": q["semantic"]["heuristic"]["examples"],
                       "unit_refs_answered_empty": q["abstention"]["unit_refs_answered_empty"], "abstention_rate": q["abstention"]["rate"]},
           "evaluate": {"unit_f1": None if e["unit_f1"] is None else round(e["unit_f1"], 3),
                        "recall": None if e["unit_recall"] is None else round(e["unit_recall"], 3),
                        "precision": None if e["unit_precision"] is None else round(e["unit_precision"], 3),
                        "examples_in_f1": e["examples"], "unit_refs_answered_empty": e["abstention"]["nonzero_refs_answered_empty"],
                        "abstention_rate": round(e["abstention"]["rate"], 3)}}
    out["reports_disagree_on"] = [k for k in ("unit_f1", "recall", "unit_refs_answered_empty", "abstention_rate")
                                  if out["quality"][k] != out["evaluate"][k]]
    return out, per_row


def p41_42():
    fx = jl(OUT / "fixture-untuned.jsonl")
    t, rows = trace("parsing fixture", fx)
    R["p41_g5_trace"] = {"status": "DONE", "input": "parsing fixture (fixture-untuned.jsonl), frozen part (200 rows)", **t,
                         "disagreeing_rows": rows,
                         "arithmetic": "quality: matched / reference units over valid rows = 177 / 177; evaluate adds the 28 reference "
                                       "units of the 25 non-scorable unit rows: 177 / 205 = 0.863 recall, F1 2·1·0.863 / 1.863 = 0.927"}
    per = {}
    for name in ("oracle", "over_abstain", "unsupported_swap", "over_split", "merge", "duplicate", "hallucinate_on_zero",
                 "struct_truncated", "unsupported_extra"):
        per[name], _ = trace(name, system(name))
    R["p42_categories"] = {"status": "DONE", "parsing_fixture": {k: t[k] for k in ("rows_by_category", "reports_disagree_on")},
                           "synthetic_systems": per,
                           "reading": "False matches, unmatched predicted units and unmatched reference units on valid rows are "
                                      "counted identically by both reports (one matcher, evaluate.judge_example). Rows whose "
                                      "reference is empty never cause G5: both count an invalid answer against abstention and "
                                      "neither counts it in F1. G5 comes only from non-scorable rows on unit references: "
                                      "evaluate counts their reference units as missed and the rows as answered empty."}


# ---------------------------------------------------------------- 43 minimal fixture
def p43():
    from flh_extraction import evaluate as ev
    unit = {"kind": "grammar", "canonical": "ne… jamais", "statement": "« Ne… jamais » means « never »: « je ne fume jamais ».",
            "statement_zh": "« ne… jamais » 表示“从不”。", "example": None, "confidence": 0.9}
    fake = dict(controls.FAKE)

    def ref(i, has):
        return {"schema": "flh_extraction_candidate_v1", "id": f"g5-{i}", "input": {"entry_id": 0, "original_input": "Je fume jamais.",
                "original_context": "", "effective_category": "grammar", "effective_explanation": "", "resolution": "accepted"},
                "expected": {"units": [unit] if has else []}, "meta": {"case_type": "single" if has else "zero", "split_group": "eval"}}

    answers = {"valid_same": lambda r: {"valid": True, "units": r["expected"]["units"]}, "valid_empty": lambda r: {"valid": True, "units": []},
               "valid_extra": lambda r: {"valid": True, "units": r["expected"]["units"] + [fake]},
               "invalid": lambda r: {"valid": False, "error_class": "unparseable_output", "units": []}}
    found = {}
    for size in (1, 2):
        for combo in itertools.combinations_with_replacement(list(itertools.product((True, False), answers)), size):
            refs = [ref(i, has) for i, (has, _) in enumerate(combo)]
            res = [dict(answers[a](r), id=r["id"]) for r, (_, a) in zip(refs, combo)]
            q, e = quality.report(refs, res), ev.evaluate(refs, res)
            qf = q["semantic"]["heuristic"]["unit_f1"]
            ef = None if e["unit_f1"] is None else round(e["unit_f1"], 3)
            for what, a, b in (("unit_f1", qf, ef), ("answered_empty", q["abstention"]["unit_refs_answered_empty"], e["abstention"]["nonzero_refs_answered_empty"])):
                if a != b and what not in found:
                    found[what] = {"rows": size, "case": [f"{'unit' if h else 'zero'} reference + {x}" for h, x in combo],
                                   "quality": a, "evaluate": b, "refs": refs, "results": res}
    fx = Path(ARGS.out) / "fixtures"
    fx.mkdir(exist_ok=True)
    f1 = found["unit_f1"]
    (fx / "g5-minimal-refs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in f1["refs"]), encoding="utf-8")
    (fx / "g5-minimal-results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in f1["results"]), encoding="utf-8")
    R["p43_minimal_fixture"] = {"status": "DONE",
                                "smallest": {k: {x: v[x] for x in ("rows", "case", "quality", "evaluate")} for k, v in found.items()},
                                "files": ["FLH-154/fixtures/g5-minimal-refs.jsonl", "FLH-154/fixtures/g5-minimal-results.jsonl"],
                                "search": "every multiset of 1 and 2 rows over {zero, unit reference} x {valid same, valid empty, valid "
                                          "with an extra unit, invalid}: one invalid unit row already splits 'answered empty' (0 vs 1); "
                                          "unit F1 needs two rows (one matched, one invalid), because with no valid unit both are null",
                                "regression": "tests/test_reporting.py CrossReportDenominators (expected failure until D1)"}


# ---------------------------------------------------------------- 45/46/57 G6 and the draft report
SIGNALS = ("unit_f1", "unsupported_units", "not_anchored_units", "bilingual_flagged_units", "over_split+merged+duplicate", "exact_unit_count_rate")
HUMAN_FIELD = {"unsupported_swap": ("unsupported_units", "unit_f1"), "unsupported_extra": ("unsupported_units",),
               "bilingual_drift": ("bilingual_mismatch",), "false_claim": ("false_claims",)}


def p45_46():
    base = {}
    for name in ("oracle", "unsupported_swap", "unsupported_extra", "bilingual_drift", "false_claim"):
        acc, res, rep = run(system(name))
        q = quality.report(FROZEN, [x for x in res if PART[x["id"]] == "frozen"])
        base[name] = {"gates_failed": [g["criterion"] for g in decision.gates(rep) if g["status"] == "FAIL"],
                      "frozen_heuristic": {k: q["headline"][k][0] for k in SIGNALS},
                      "unit_count_over_examples": q["unit_count"]["over_count_examples"], "sysrep": rep}
    o = base["oracle"]["frozen_heuristic"]
    lacks = {}
    for name in ("unsupported_swap", "unsupported_extra", "bilingual_drift", "false_claim"):
        h = base[name]["frozen_heuristic"]
        moved = {k: [o[k], h[k]] for k in SIGNALS if o[k] != h[k]}
        lacks[name] = {"passes_every_exact_gate": not base[name]["gates_failed"], "automatic_signals_that_moved (not gating)": moved,
                       "unit_count_over_examples (exact, not gating)": base[name]["unit_count_over_examples"],
                       "human_evidence_that_would_catch_it": HUMAN_FIELD[name]}
    R["p45_g6"] = {"status": "DONE" if all(v["passes_every_exact_gate"] for v in lacks.values()) else "UNEXPECTED",
                   "systems": {k: {x: v[x] for x in ("gates_failed", "frozen_heuristic", "unit_count_over_examples")} for k, v in base.items()},
                   "definitions": {"unsupported_swap": "each single-unit reference answered with an unrelated objective (controls.py)",
                                   "unsupported_extra": "each unit reference keeps its units and gains one unrelated unit",
                                   "bilingual_drift": "every statement_zh replaced by a vague sentence (controls.py)",
                                   "false_claim": "every statement turned into a false claim, canonical kept (controls.py)"}}
    R["p46_missing_evidence"] = {"status": "DONE", "by_system": lacks,
                                 "reading": "Each bad system passes the exact gates because they only test structure, abstention and "
                                            "cue consistency. What it lacks is human evidence on content: whether a unit was raised "
                                            "by the learner (unsupported_units), whether its claim is true (false_claims), whether "
                                            "the Chinese says the same (bilingual_mismatch). The heuristics move for three of the four "
                                            "but do not gate; false_claim moves nothing automatic at all."}
    return base


def p57(base):
    acc_e, _, ce = run(controls.outputs(REFS, "over_abstain"))
    sys3 = {"oracle": base["oracle"]["sysrep"], "constant_empty": ce, "unrelated_output": base["unsupported_swap"]["sysrep"]}
    comp = {"refused": [], "systems": sys3}
    # Part 4 (experimental report v1): a preference also needs per-unit reviewer evidence. Scope: the review-sample ids
    # in the slice; SYNTHETIC evidence = what a reviewer records if each control behaves as built.
    accounts = {"oracle": run(system("oracle"))[0], "constant_empty": acc_e, "unrelated_output": run(system("unsupported_swap"))[0]}
    sample_ids = [json.loads(x)["id"] for x in (REPO / "tools/extraction/review/review-sample-v1.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    queue = rev.queue(REFS, accounts, [i for i in sample_ids if i in INPUTS], None, comparison.sha256_file(SLICE),
                      "review-sample-v1 ids in the slice")
    reviewer_rows = [dict(r, source_raised="no" if r["system"] == "unrelated_output" else "yes", claim_true="yes", zh_same="yes",
                          reviewer="synthetic (part-3 controls)", date="2026-11-17") for r in rev.template(queue)]
    assumed = {  # SYNTHETIC human evidence: what a reviewer would find if each control behaves as built
        "oracle": {"unit_f1": 1.0, "judged_examples": 120, "judged_objectives": 45, "false_claims": {"judged_units": 150, "false": 0},
                   "unsupported_units": {"judged_units": 150, "unsupported": 0}, "bilingual_mismatch": {"judged_units": 150, "mismatched": 0}},
        "constant_empty": {"unavailable": {"reason": "no units to judge"}},
        "unrelated_output": {"unit_f1": 0.0, "judged_examples": 120, "judged_objectives": 45, "false_claims": {"judged_units": 150, "false": 0},
                             "unsupported_units": {"judged_units": 150, "unsupported": 150}, "bilingual_mismatch": {"judged_units": 150, "mismatched": 0}}}
    review_ok = [{"id": f"r{k}", "verdict": "accept"} for k in range(79)]
    review_bad = [{"id": f"r{k}", "verdict": "reject" if k < 16 else "accept"} for k in range(79)]
    scen = {"no human evidence": xr.report(comp, None, review_ok),
            "assumed human evidence (synthetic), no reviewer evidence (report v1)": xr.report(comp, assumed, review_ok),
            "assumed human evidence (synthetic)": xr.report(comp, assumed, review_ok, queue, reviewer_rows),
            "assumed human evidence, failed reference review (16 of 79 rejected)": xr.report(comp, assumed, review_bad, queue, reviewer_rows)}
    out = {}
    for k, v in scen.items():
        out[k] = {"verdict": v["verdict"], "preference": v["preference"], "production_go": v["production_go"],
                  "systems": {s: {"eligible": x["eligible"], "excluded_by_exact_gates": x["excluded_by_exact_gates"],
                                  "excluded_by_human_evidence": x["excluded_by_human_evidence"],
                                  "reviewer": x["reviewer"]["status"],
                                  "excluded_by_reviewer_evidence": len(x["excluded_by_reviewer_evidence"])} for s, x in v["systems"].items()},
                  "reasons": v["reasons"]}
    exact_same = all(xr.report(comp, assumed, review_ok)["systems"][s]["exact"] == decision.gates(sr) for s, sr in sys3.items())
    ok = (out["no human evidence"]["verdict"] == "PENDING" and out["assumed human evidence (synthetic)"]["preference"] == "oracle"
          and out["assumed human evidence (synthetic), no reviewer evidence (report v1)"]["verdict"] == "PENDING"
          and out["assumed human evidence, failed reference review (16 of 79 rejected)"]["verdict"] == "BLOCKED"
          and all(v["production_go"] is False for v in out.values()) and exact_same)
    R["p57_controls_through_draft"] = {"status": "PASS" if ok else "FAIL", "scenarios": out, "exact_gates_identical_to_decision_py": exact_same,
                                       "note": "assumed human evidence is synthetic and labelled so; with it the unrelated output is "
                                               "excluded on unsupported units although it passes every exact gate. Part 4 (report v1): "
                                               "the same scenario without per-unit reviewer evidence is PENDING; with synthetic reviewer "
                                               "evidence over the review-sample ids the unrelated output is also excluded on source_raised",
                                       "reviewer_scope_units": {s: v["units_in_scope"] for s, v in queue["systems"].items()}}


# ---------------------------------------------------------------- 52/53 G7 exact binomial
def tail(n, k, p):
    p = Fraction(p)
    return sum(Fraction(math.comb(n, i)) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def tail_float(n, k, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def cp_lower(n, k, alpha=0.05):
    """Exact (Clopper-Pearson) one-sided lower bound: the p at which P(X >= k | p) = alpha."""
    if k == 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if tail_float(n, k, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return lo


OPTIONS = {
    "A point >= 0.90 (current abstention and consistency gates)": lambda n: math.ceil(Fraction(9, 10) * n),
    "A2 point >= 0.80 (current abstain-group accuracy gate)": lambda n: math.ceil(Fraction(8, 10) * n),
    "B point >= 0.95": lambda n: math.ceil(Fraction(19, 20) * n),
    "C exact 95% lower bound >= 0.80": lambda n: next((k for k in range(n + 1) if cp_lower(n, k) >= 0.80), None),
    "D exact 95% lower bound >= 0.85": lambda n: next((k for k in range(n + 1) if cp_lower(n, k) >= 0.85), None),
}
SIZES = {9: "abstain groups in challenge_test", 20: "zero-unit references per part (frozen, rb)", 24: "challenge_test groups",
         40: "frozen + rb pooled (NOT independent: same learner texts)", 60: "hypothetical new held-out set", 100: "hypothetical", 200: "hypothetical"}
RATES = ("0.75", "0.80", "0.85", "0.90", "0.95", "0.99")


def p52_53():
    table = {}
    for opt, need in OPTIONS.items():
        table[opt] = {}
        for n, what in SIZES.items():
            k = need(n)
            if k is None or k > n:
                table[opt][str(n)] = {"size_meaning": what, "needs": None, "pass_probability": None, "note": "cannot pass at this size"}
                continue
            pp = {p: round(float(tail(n, k, p)), 4) for p in RATES}
            table[opt][str(n)] = {"size_meaning": what, "needs": f"{k} of {n}", "pass_probability": pp,
                                  "false_pass_at_0.85": pp["0.85"], "false_pass_at_0.80": pp["0.80"], "false_fail_at_0.95": round(1 - pp["0.95"], 4)}
    both = {p: round(float(tail(20, 18, p) ** 2), 4) for p in RATES}
    R["p52_g7_exact"] = {"status": "DONE", "method": "exact binomial tails with rational arithmetic (fractions.Fraction); exact "
                                                     "(Clopper-Pearson) one-sided 95% lower bounds by bisection on the exact tail",
                         "options": table, "current_rule_on_both_frozen_and_rb_if_independent": both}
    R["p53_assumptions"] = {"status": "DONE", "assumptions": [
        "each row is an independent trial with one true rate (real rates vary by case type, so the spread is wider)",
        "frozen and rb are the same 20 learner texts under two cue sets: they are not independent, so pooling them is not n = 40",
        "the references are correct (they are machine-authored and unreviewed)",
        "sizes above 24 need a new held-out set: the frozen evaluation and its digests stay as they are; a larger set is a new "
        "slice with its own matrix, never a re-pin of v1"],
        "false_pass": "probability that a system whose true rate is 0.85 (or 0.80) passes", "false_fail": "probability that one at 0.95 fails"}


# ---------------------------------------------------------------- 58 nothing published changed
def p58():
    pins = {}
    files = [f"tools/extraction/flh_extraction/{m}.py" for m in ("audit", "challenge", "comparison", "controls", "evaluate", "matrix", "paired",
                                                                 "quality", "textnorm", "decision")]
    files += ["tools/extraction/review/review-sample-v1.jsonl", "tools/extraction/review/REVIEW_SAMPLE_V1.md",
              "tools/extraction/review/review-sample-v1-selection.json"]
    files += sorted(str(p.relative_to(REPO)) for p in (DEPLOY / "readiness").glob("*.json"))
    for f in files:
        pins[f] = hashlib.sha256((REPO / f).read_bytes()).hexdigest()
    m = json.loads((DEPLOY / "readiness" / "comparison-matrix.json").read_text())
    em = json.loads((DEPLOY / "readiness" / "experiment-manifest.json").read_text())
    sv = comparison.scoring_version()
    out = {"scoring_version": sv["sha256"], "scoring_version_equals_matrix_pin": sv["sha256"] == m["scoring_version"]["sha256"],
           "matrix_sha256": m["matrix_sha256"], "experiment_manifest_sha256": em["manifest_sha256"], "file_sha256": pins}
    if ARGS.pipeline_before:
        before = Path(ARGS.pipeline_before).resolve()
        diff, same, added = [], 0, []
        for p in sorted(x for x in OUT.rglob("*") if x.is_file() and x.name != "last.log"):
            rel = p.relative_to(OUT)
            if {"bin"} & set(rel.parts) or any(q.endswith(".work") for q in rel.parts):
                continue
            q = before / rel
            if not q.is_file():
                added.append(str(rel))
            elif p.read_bytes() == q.read_bytes() or re.sub(r"\d{8}-\d{6}", "T", p.read_text(errors="replace")) == re.sub(r"\d{8}-\d{6}", "T", q.read_text(errors="replace")):
                same += 1
            else:
                diff.append(str(rel))
        out["pipeline_vs_before"] = {"identical": same, "changed": diff, "added": added}
    ok = out["scoring_version_equals_matrix_pin"] and (not ARGS.pipeline_before or not out["pipeline_vs_before"]["changed"])
    R["p58_unchanged"] = {"status": "PASS" if ok else "FAIL", **out,
                          "reading": "The draft report reads decision.gates and decision.reviewed and changes neither; "
                                     "the scoring modules, decision.py, the reviewer sample and every readiness digest are those "
                                     "of the sealed part-2 handoff (compared there by file hash)."}


# ---------------------------------------------------------------- 54-56 the fixed sample, the sheet, no silent acceptance
def p54_56():
    import csv
    import io
    from flh_extraction import review_sample, review_sheet
    packet = jl(TOOLS / "review" / "review-sample-v1.jsonl")
    sheet = (TOOLS / "review" / "REVIEW_SHEET_V1.csv").read_text(encoding="utf-8")
    regen_sheet = (OUT / "evidence" / "review-sheet-v1.csv").read_text(encoding="utf-8")
    regen_packet = (OUT / "evidence" / "review-sample-v1.jsonl").read_bytes() == (TOOLS / "review" / "review-sample-v1.jsonl").read_bytes()

    def filled(position=True, verdict="accept", skip=()):
        rows = list(csv.DictReader(io.StringIO(sheet)))
        for r in rows:
            if r["item_id"] in skip:
                continue
            if r["unit"] != "0":
                r.update({c: "yes" for c in review_sheet.UNIT if c != "C_wording_fix"})
            if r["unit"] in ("0", "1"):
                r.update(A_intent_decision_ok="yes", A_intent_objectives_ok="yes", D_verdict=verdict, D_reviewer="(synthetic)", D_date="2026-11-17")
                if r["dispute"] and position:
                    r["D_dispute_position"] = "synthetic position"
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=review_sheet.HEADER, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue()

    scen = {"blank sheet": sheet, "every item accepted, disputes without a position": filled(position=False),
            "every item quarantined": filled(verdict="quarantine"), "first item left blank": filled(skip=(packet[0]["id"],)),
            "every item accepted with positions": filled()}
    out = {}
    good = {"refused": [], "systems": {s: {"status": "MEASURED", "rows": {"references": 472, "scorable": 472, "status_counts": {}},
                                           "metrics": {"frozen": {"headline": {"abstention_rate": 1.0}, "over_abstention_rate": 0.0},
                                                       "rb": {"headline": {"abstention_rate": 1.0}, "over_abstention_rate": 0.0},
                                                       "challenge_test": {"headline": {"paired_consistency": 1.0},
                                                                          "by_intent": {"abstain": {"paired_correct": 1.0}}}}}
                                       for s in decision.SYSTEMS}}
    human = {s: {"unit_f1": f, "judged_examples": 120} for s, f in zip(decision.SYSTEMS, (0.9, 0.6, 0.5))}
    in_manifest = json.loads((DEPLOY / "readiness" / "input-manifest.json").read_text())
    run_manifest = {"train_sha256": in_manifest["files"]["sft-train.jsonl"]["sha256"],
                    "dev_sha256": in_manifest["files"]["sft-dev.jsonl"]["sha256"], "suitable_for_production": False, "smoke": False}
    losses = [{"dev_loss": 1.0}, {"dev_loss": 0.9}, {"dev_loss": 0.8}]
    for k, text in scen.items():
        fp, rep = review_sheet.load(packet, text)
        d = decision.decide(good, human, fp, losses, run_manifest, in_manifest)
        out[k] = {"labels": {x: len(v) for x, v in rep["labels"].items()}, "decision_report": d["verdict"],
                  "decision_review": d["review"]["status"], "experimental_review": xr.review_state(fp)["status"],
                  "agreement_unresolved_disputes": len(review_sample.agreement(fp)["disputed_unresolved"])}
    refusals = {}
    for k, text in {"a fixed column edited": sheet.replace("ne… aucun(e)", "edited", 1),
                    "a verdict with a blank answer": filled().replace("yes,yes,yes,yes,yes", "yes,,yes,yes,yes", 1)}.items():
        try:
            review_sheet.load(packet, text)
            refusals[k] = "imported (NOT refused)"
        except ValueError as e:
            refusals[k] = "refused: " + str(e)[:120]
    silent = [k for k, v in out.items() if k != "every item accepted with positions" and v["decision_report"] != "PENDING"]
    files = [TOOLS / "review" / "REVIEW_SHEET_V1.csv", TOOLS / "review" / "REVIEW_SHEET_V1.md"] + \
        [p for p in sorted((REPO / "docs" / "validation" / "FLH-154").glob("*")) if p.is_file() and (p.name.startswith(("part3", "repin")))] + \
        sorted((REPO / "docs" / "validation" / "FLH-154" / "fixtures").glob("*")) + sorted((REPO / "docs" / "validation").glob("FLH-154-part3*.md"))
    priv = {str(f.relative_to(REPO)): review_sample.export_findings(f.read_text(encoding="utf-8")) for f in files}
    ok = (regen_packet and regen_sheet == sheet and not silent and all(v.startswith("refused") for v in refusals.values())
          and out["every item accepted with positions"]["decision_review"] == "PASS" and not any(priv.values()))
    R["p54_56_sheet"] = {"status": "PASS" if ok else "FAIL", "sample_fixed": regen_packet, "sheet_equals_regenerated": regen_sheet == sheet,
                         "open_disputes_labelled": out["blank sheet"]["labels"], "scenarios": out, "refusals": refusals,
                         "silently_accepted": silent, "privacy_findings": {k: v for k, v in priv.items() if v},
                         "privacy_files_scanned": sorted(priv)}


def md(rep):
    L = ["# FLH-154 part 3 checks (generated, OFFLINE ONLY)", "", "| Check | Status |", "|---|---|"]
    L += [f"| {k} | {v['status']} |" for k, v in rep.items()]
    return "\n".join(L) + "\n"


def main():
    p41_42()
    p43()
    base = p45_46()
    p57(base)
    p52_53()
    p54_56()
    p58()
    out = Path(ARGS.out)
    doc = {"schema": "flh154_part3_checks_v1", "offline_only": True, "synthetic_only": True, "real_runs_performed": 0, **R}
    (out / "part3-checks.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "part3-checks.md").write_text(md(R), encoding="utf-8")
    print(json.dumps({k: v["status"] for k, v in R.items()}, indent=1))


if __name__ == "__main__":
    main()
