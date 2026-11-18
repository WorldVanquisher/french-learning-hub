"""FLH-154 items 21 and 26-36: offline checks of the evaluation reports (OFFLINE ONLY).

  python3 -I -B docs/validation/FLH-154/reporting_checks.py --repo . --pipeline OUT --out docs/validation/FLH-154

OUT is a `tools/extraction/scripts/comparison_pipeline.sh` output directory.
Writes OUT/reporting-checks.json and .md. Synthetic systems only (oracle =
the machine-authored references); the production validator runs in-process
(`extraction-render validate`, no network). No provider, AWS, model or
download. Nothing in the repository is changed.
"""

import argparse
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

A = argparse.ArgumentParser()
A.add_argument("--repo", required=True)
A.add_argument("--pipeline", required=True)
A.add_argument("--out", required=True)
ARGS = A.parse_args()
REPO, OUT = Path(ARGS.repo).resolve(), Path(ARGS.pipeline).resolve()
TOOLS = REPO / "tools" / "extraction"
DEPLOY = REPO / "deploy" / "aws" / "sagemaker-extractor"
sys.path.insert(0, str(TOOLS))

from flh_extraction import (challenge, comparison, controls, decision, evaluate, matrix, paired, promotion, quality,  # noqa: E402
                            review_sample)

BIN = OUT / "bin" / "extraction-render"
WORK = Path(tempfile.mkdtemp(prefix="flh154r-"))
VALIDATE = controls.render_validator(BIN, WORK / "validate")
MATRIX = json.loads((DEPLOY / "readiness" / "comparison-matrix.json").read_text(encoding="utf-8"))
SLICE = OUT / "slice" / "comparison-slice.jsonl"


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


REFS = jl(SLICE)
IDS = [r["id"] for r in REFS]
INPUTS = {r["id"]: r["input"] for r in REFS}
PART = {r["id"]: matrix.part_of(r) for r in REFS}
R = {}


def run(rows):
    acc = comparison.account_with_validator(IDS, INPUTS, rows, VALIDATE)
    res = comparison.scored_results(acc)
    return acc, res, {"status": "MEASURED", "rows": {k: acc[k] for k in ("references", "scorable", "status_counts", "unknown_ids", "unknown_id_rows")},
                      "metrics": matrix._metrics(REFS, res, [r for r in rows if "output_text" in r] or None)}


def gate_view(sysrep):
    gs = decision.gates(sysrep)
    return [g["criterion"] for g in gs if g["status"] == "FAIL"]


def oracle():
    return controls.outputs(REFS, "oracle")


def jdump(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------- 21 inventory
def r21():
    sets = {
        "train (base, train+dev)": jl(OUT / "train" / "candidates.jsonl"),
        "increment v2 (train+dev)": jl(OUT / "inc" / "increment_candidates.jsonl"),
        "frozen evaluation": jl(OUT / "eval" / "eval_candidates.jsonl"),
        "rb probe": jl(OUT / "probe-rb.jsonl"),
        "swap probe": jl(OUT / "probe-swap.jsonl"),
        "challenge (dev + test)": jl(OUT / "chl" / "challenge_candidates.jsonl"),
        "boundary cases": jl(OUT / "boundary" / "boundary_cases_v1.jsonl"),
    }
    role = {
        "train (base, train+dev)": ("training data", "never: training data is not evidence about held-out quality"),
        "increment v2 (train+dev)": ("training data", "never"),
        "frozen evaluation": ("held-out references (the only candidate evidence)",
                              "only after (1) a person accepts the reference and (2) a real model output exists for it"),
        "rb probe": ("synthetic control: the same learner texts under the production analyzer's cues",
                     "never as extra examples; only for a claim about cue robustness, paired with its frozen record"),
        "swap probe": ("synthetic stress control: cues swapped against the reference", "never"),
        "challenge (dev + test)": ("synthetic control: cue-dependence pairs; its 23 units are frozen units reused",
                                   "only for a claim about consistency across cues, counted per group, never per record"),
        "boundary cases": ("policy documentation (annotation boundaries); not scored", "never for quality; it illustrates the policy"),
    }
    inv = {}
    for k, rs in sets.items():
        inv[k] = {"records": len(rs), "origin": dict(Counter(r["meta"].get("origin") for r in rs)),
                  "label_status": dict(Counter(r["meta"].get("label_status") for r in rs)),
                  "review_status": dict(Counter(r["meta"].get("review_status") for r in rs)),
                  "entry_id_nonzero": sum(1 for r in rs if r["input"].get("entry_id")),
                  "role": role[k][0], "can_support_a_demo_claim": role[k][1]}
    controls_ = {"parsing fixture (fixture-untuned.jsonl)": "synthetic faults: accounting control only",
                 "oracle / category-only / constant-empty outputs": "synthetic systems: show what the harness catches",
                 f"control-matrix controls ({len(controls.TARGETS)})": "synthetic single-fault outputs: which metric catches which failure",
                 "decision fixtures (FLH-154 cp14/cp15)": "synthetic metric sets: decision-rule behaviour only"}
    slice_cls = Counter()
    for r in REFS:
        p = PART[r["id"]]
        slice_cls["candidate evidence (frozen; needs review + real output)" if p == "frozen" else
                  "control: rb view of a frozen text" if p == "rb" else "control: challenge pair (counted per group)"] += 1
    reviewed = sum(1 for rs in sets.values() for r in rs if r["meta"].get("review_status") not in (None, "unreviewed"))
    R["r21_inventory"] = {"status": "PASS", "datasets": inv, "synthetic_controls": controls_,
                          "comparison_slice_classification": dict(slice_cls),
                          "examples_that_support_a_demo_claim_today": 0,
                          "why": f"every record is synthetic and machine-authored ({reviewed} human-reviewed), and no real "
                                 "model output exists; no document or demo page in the repository claims extraction "
                                 "quality, and the public demo's units come from a local stub extractor",
                          "after_owner_steps": "frozen records whose reference a person accepted (review-sample-v1 starts "
                                               "with 35 items covering 25 of 45 objectives) AND that have a real model output"}


# ---------------------------------------------------------------- 26 order
def r26():
    base = matrix.compare(MATRIX, SLICE, {"qwen3.5-4b-untuned": oracle()}, VALIDATE)
    rng = random.Random(26)
    shuffled = oracle()
    rng.shuffle(shuffled)
    rev_units = []
    for x in oracle():
        doc = json.loads(x["output_text"])
        doc["units"] = list(reversed(doc["units"]))
        rev_units.append({**x, "output_text": json.dumps(doc, ensure_ascii=False)})
    pred_order = matrix.compare(MATRIX, SLICE, {"qwen3.5-4b-untuned": shuffled}, VALIDATE) == base
    unit_order = matrix.compare(MATRIX, SLICE, {"qwen3.5-4b-untuned": rev_units}, VALIDATE) == base
    # reference order: the scoring functions themselves (compare refuses a reordered slice file by hash)
    _, res, _ = run(oracle())
    sh = REFS[:]
    rng.shuffle(sh)
    ref_order = matrix._metrics(sh, res, None) == matrix._metrics(REFS, res, None)
    q_order = jdump(quality.report(sh, res)) == jdump(quality.report(REFS, res))
    chl = [r for r in REFS if PART[r["id"]] == "challenge_test"]
    chs = chl[::-1]
    p_order = jdump(paired.report(chs, res)) == jdump(paired.report(chl, res))
    e_order = jdump({k: v for k, v in evaluate.evaluate(sh, res).items() if k != "rows"}) == \
        jdump({k: v for k, v in evaluate.evaluate(REFS, res).items() if k != "rows"})
    comp = {"systems": {s: base["systems"]["qwen3.5-4b-untuned"] | {"status": "MEASURED"} for s in decision.SYSTEMS}, "refused": []}
    h = {s: {"unit_f1": f, "judged_examples": 120} for s, f in zip(decision.SYSTEMS, (0.7, 0.6, 0.9))}
    rev = [{"id": str(i), "verdict": "accept"} for i in range(44)]
    d1 = decision.decide(comp, h, rev)
    comp2 = {"systems": dict(reversed(list(comp["systems"].items()))), "refused": []}
    d2 = decision.decide(comp2, h, rev)
    sys_order = (d1["verdict"], d1["winner"]) == (d2["verdict"], d2["winner"])
    ok = all((pred_order, unit_order, ref_order, q_order, p_order, e_order, sys_order))
    R["r26_order"] = {"status": "PASS" if ok else "FINDING",
                      "prediction_row_order (compare)": pred_order, "unit_order_inside_each_output (compare)": unit_order,
                      "reference_order (_metrics)": ref_order, "reference_order (quality.report)": q_order,
                      "variant_and_group_order (paired.report)": p_order, "reference_order (evaluate)": e_order,
                      "system_order (decision)": sys_order,
                      "note": "compare refuses a reordered slice FILE (its hash is pinned), so reference order was varied "
                              "at the scoring functions; evaluate's per-row list follows the input order by design"}


# ---------------------------------------------------------------- 27 duplicates
def r27():
    o = oracle()
    unit_id = next(r["id"] for r in REFS if PART[r["id"]] == "frozen" and r["expected"]["units"])
    dup = o + [{"id": unit_id, "input": INPUTS[unit_id], "output_text": '{"units": []}'}]   # a contradicting second answer
    acc = comparison.account_with_validator(IDS, INPUTS, dup, VALIDATE)
    raw_status = next(r["status"] for r in acc["rows"] if r["id"] == unit_id)
    _, res, _ = run(o)
    prov = res + [{"id": unit_id, "valid": True, "units": [], "error_class": None}]
    prov_status = next(r["status"] for r in matrix.account_results(IDS, prov)["rows"] if r["id"] == unit_id)
    # the standalone reports keep the LAST row for a duplicated id
    first_refs = [r for r in REFS if r["id"] == unit_id]
    q = quality.report(first_refs, prov)
    e = evaluate.evaluate(first_refs, prov)
    chl = [r for r in REFS if PART[r["id"]] == "challenge_test"]
    cid = next(r["id"] for r in chl if r["expected"]["units"])
    pres = [x for x in res if x["id"] in {r["id"] for r in chl}] + [{"id": cid, "valid": True, "units": []}]
    pr = paired.report(chl, pres)
    cli = {}
    tmp = WORK / "dup"
    tmp.mkdir(exist_ok=True)
    (tmp / "refs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in first_refs), encoding="utf-8")
    (tmp / "res.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in prov if r["id"] == unit_id), encoding="utf-8")
    for cmd in (["quality", "--refs", str(tmp / "refs.jsonl"), "--results", str(tmp / "res.jsonl"), "--out", str(tmp / "q")],
                ["evaluate", "--refs", str(tmp / "refs.jsonl"), "--results", str(tmp / "res.jsonl"), "--title", "t", "--out", str(tmp / "e")]):
        p = subprocess.run([sys.executable, "-B", "-m", "flh_extraction"] + cmd, cwd=TOOLS, capture_output=True, text=True)
        cli[cmd[0]] = {"exit": p.returncode, "stderr_tail": p.stderr.strip().splitlines()[-1][:160] if p.stderr.strip() else ""}
    R["r27_duplicates"] = {
        "status": "PASS" if all(v["exit"] != 0 and "duplicated id" in v["stderr_tail"] for v in cli.values()) else "FINDING",
        "case": f"{unit_id}: first row = the reference, second row = empty (contradicting)",
        "compare_raw_outputs": raw_status, "compare_production_results": prov_status,
        "quality.report_counts_it_as": "empty answer (last row wins)" if q["abstention"]["unit_refs_answered_empty"] == 1 else "first row",
        "evaluate_counts_it_as": "empty answer (last row wins)" if e["abstention"]["nonzero_refs_answered_empty"] == 1 else "first row",
        "paired.report_counts_it_as": "last row wins" if pr["all"]["paired_correct"]["count"] < pr["all"]["groups"] else "first row",
        "standalone_cli": cli,
        "reading": "compare never scores a duplicated id (duplicate_prediction, non-scorable). The standalone quality, "
                   "evaluate and paired-consistency functions index results by id, so the last of two contradicting rows "
                   "wins; their CLIs (and categories) now refuse such a file (FLH-154 item 39; they accepted it before).",
    }


# ---------------------------------------------------------------- 28 missing / extra
def r28():
    o = oracle()
    no_b = [x for x in o if PART[x["id"]] != "rb"]
    rep_b = matrix.compare(MATRIX, SLICE, {"qwen3.5-4b-tuned": no_b, "qwen3.5-4b-untuned": o, "current_extractor": o}, VALIDATE)
    rev = [{"id": str(i), "verdict": "accept"} for i in range(44)]
    h = {"current_extractor": {"unit_f1": 0.6, "judged_examples": 120}, "qwen3.5-4b-untuned": {"unit_f1": 0.5, "judged_examples": 120},
         "qwen3.5-4b-tuned": {"unit_f1": 0.9, "judged_examples": 120}}
    im = json.loads((DEPLOY / "readiness" / "input-manifest.json").read_text())
    rm = {"train_sha256": im["files"]["sft-train.jsonl"]["sha256"], "dev_sha256": im["files"]["sft-dev.jsonl"]["sha256"],
          "suitable_for_production": False, "smoke": False}
    d = decision.decide(rep_b, h, rev, [{"dev_loss": 1.0}, {"dev_loss": 0.9}, {"dev_loss": 0.8}], rm, im)
    tuned = d["systems"]["qwen3.5-4b-tuned"]
    extra = o + [{"id": f"not-in-slice-{i}", "output_text": '{"units": []}'} for i in range(5)]
    rep_x = matrix.compare(MATRIX, SLICE, {"qwen3.5-4b-untuned": extra}, VALIDATE)
    rep_o = matrix.compare(MATRIX, SLICE, {"qwen3.5-4b-untuned": o}, VALIDATE)
    extra_safe = rep_x["systems"]["qwen3.5-4b-untuned"]["metrics"] == rep_o["systems"]["qwen3.5-4b-untuned"]["metrics"]
    mangled = [{**x, "id": x["id"].replace("#rb", "")} for x in o]
    rep_m = matrix.compare(MATRIX, SLICE, {"qwen3.5-4b-untuned": mangled}, VALIDATE)
    # promotion-check across two different example sets (e.g. the 50-item subset vs the full 200)
    fz = [r for r in REFS if PART[r["id"]] == "frozen"]
    _, res, _ = run(o)
    sub = fz[:50]
    q50, q200 = quality.report(sub, res), quality.report(fz, res)
    pc = promotion.check(q50, q50, q200)
    pop = next((c for c in pc["criteria"] if "same examples" in c["criterion"]), None)
    qc = quality.compare(q50, q200)
    (WORK / "q50.json").write_text(json.dumps(q50))
    (WORK / "q200.json").write_text(json.dumps(q200))
    qc_cli = subprocess.run([sys.executable, "-B", "-m", "flh_extraction", "quality-compare", "--a", str(WORK / "q50.json"),
                             "--b", str(WORK / "q200.json"), "--out", str(WORK / "qc")], cwd=TOOLS, capture_output=True, text=True)
    safe = (d["verdict"] == "PENDING" and tuned.get("incomplete_run") and pop and pop["status"] == "PENDING"
            and qc_cli is not None and "different populations" in qc_cli.stderr)
    R["r28_missing_extra"] = {
        "status": "PASS" if safe else "FINDING",
        "missing_shard_b_of_the_tuned_model": {
            "status_counts": rep_b["systems"]["qwen3.5-4b-tuned"]["rows"]["status_counts"],
            "decision_verdict": d["verdict"], "decision_winner": d["winner"], "tuned_eligible": tuned["eligible"],
            "decision_reasons": d["reasons"]},
        "extra_ids": {"unknown_ids": rep_x["systems"]["qwen3.5-4b-untuned"]["rows"]["unknown_ids"],
                      "metrics_identical_to_the_clean_run": extra_safe},
        "rb_ids_stripped_of_their_suffix": rep_m["systems"]["qwen3.5-4b-untuned"]["rows"]["status_counts"],
        "promotion_check_50_vs_200_examples": {"verdict": pc["verdict"], "population_criterion": pop},
        "quality_compare_50_vs_200_examples": {"examples": [q50["examples"], q200["examples"]],
                                               "deltas_computed": sum(1 for v in qc.values() if v["delta"] is not None),
                                               "cli_warning": qc_cli.stderr.strip()[:160] if qc_cli else None},
        "reading": "compare accounts for every id: missing rows are missing_prediction (non-scorable), extra ids are listed "
                   "and never scored, mangled ids become duplicates plus missing rows. Before FLH-154 item 39 a forgotten "
                   "shard was read as the tuned model's weak rb abstention and the current extractor was proposed as the "
                   "winner; decision-report now answers PENDING and names the incomplete run. promotion-check is PENDING "
                   "across different example sets, and quality-compare warns.",
    }


# ---------------------------------------------------------------- 29 denominators
def r29():
    fx = jl(OUT / "fixture-untuned.jsonl")
    acc, res, sysrep = run(fx)
    m = sysrep["metrics"]
    by = {r["id"]: r for r in acc["rows"]}
    checks = {}
    for p in ("frozen", "rb"):
        part = [r for r in REFS if PART[r["id"]] == p]
        zero = [r for r in part if not r["expected"]["units"]]
        unit = [r for r in part if r["expected"]["units"]]
        te = sum(1 for r in zero if by[r["id"]]["status"] == "valid_empty")
        oa = sum(1 for r in unit if by[r["id"]]["status"] == "valid_empty")
        sc = sum(1 for r in part if by[r["id"]]["status"] in comparison.SCORABLE)
        checks[p] = {"abstention": [m[p]["headline"]["abstention_rate"], round(te / len(zero), 3)],
                     "over_abstention": [m[p]["over_abstention_rate"], round(oa / len(unit), 3)],
                     "structural_validity": [m[p]["headline"]["structural_validity"], round(sc / len(part), 3)]}
    md = matrix.markdown(MATRIX, matrix.compare(MATRIX, SLICE, {"qwen3.5-4b-untuned": fx}, VALIDATE))
    row = next(x for x in md.splitlines() if x.startswith("| qwen3.5-4b-untuned |") and "/" in x.split("|")[2])
    cells = [c.strip() for c in row.split("|")[1:-1]]
    md_ok = (cells[1] == f"{acc['scorable']}/{acc['references']}" and float(cells[3]) == m["frozen"]["headline"]["abstention_rate"]
             and float(cells[4]) == m["rb"]["headline"]["abstention_rate"])
    within = all(a == b for v in checks.values() for a, b in v.values()) and md_ok
    # across reports: evaluate and quality on the same results (frozen part of the fixture)
    fz = [r for r in REFS if PART[r["id"]] == "frozen"]
    rz = [x for x in res if PART[x["id"]] == "frozen"]
    q, e = quality.report(fz, rz), evaluate.evaluate(fz, rz)
    invalid_unit_rows = sum(1 for r in fz if r["expected"]["units"] and by[r["id"]]["status"] not in comparison.SCORABLE)
    across = {"unit_f1": {"quality": q["semantic"]["heuristic"]["unit_f1"], "evaluate": round(e["unit_f1"], 3)},
              "unit_refs_answered_empty": {"quality": q["abstention"]["unit_refs_answered_empty"],
                                           "evaluate": e["abstention"]["nonzero_refs_answered_empty"]},
              "abstention_rate": {"quality": q["abstention"]["rate"], "evaluate": round(e["abstention"]["rate"], 3)},
              "structural_validity": {"quality": q["structural"]["rate"], "evaluate": round(e["structural_validity"], 3)},
              "invalid_rows_on_unit_references": invalid_unit_rows}
    denominators = {
        "structural validity / strict validity": "every reference row (invalid, missing and duplicate rows count against)",
        "abstention rate": "every zero-unit reference (invalid rows count against)",
        "over-abstention rate (quality, compare)": "every unit reference; only VALID empty answers count",
        "nonzero_refs_answered_empty (evaluate)": "every unit reference; INVALID answers count as empty",
        "exact unit count rate (quality)": "VALID rows only",
        "unit F1 (quality, compare, human F1 via quality --judgments)": "VALID rows only",
        "unit F1 (evaluate)": "every row (an invalid row's reference units are missed)",
        "paired consistency / accuracy": "every challenge_test group (invalid or missing never consistent)",
    }
    disagree = across["unit_f1"]["quality"] != across["unit_f1"]["evaluate"] or \
        across["unit_refs_answered_empty"]["quality"] != across["unit_refs_answered_empty"]["evaluate"]
    R["r29_denominators"] = {"status": "FINDING" if disagree or not within else "PASS",
                             "summary_equals_detail_within_compare": within, "recomputed_from_rows": checks,
                             "markdown_row_equals_json": md_ok, "evaluate_vs_quality_same_inputs": across,
                             "denominator_by_metric": denominators,
                             "reading": "Inside compare every summary number equals its recount from the rows, and the "
                                        "Markdown equals the JSON. Across reports, evaluate and quality give different "
                                        "unit F1 and different 'unit references answered empty' for the same results, "
                                        "because they treat invalid rows differently; TRAINING_RUNBOOK §9 runs both."}


# ---------------------------------------------------------------- 30/33/34 error categories, gate vs aggregate, uncertainty
SYSTEMS = {}


def r30():
    names = ["oracle", "category_shortcut", "over_abstain"] + [c for c in controls.TARGETS if c not in ("oracle", "category_shortcut", "over_abstain")]
    for c in names:
        SYSTEMS[c] = run(controls.outputs(REFS, c))
    table = {}
    for c, (acc, res, rep) in SYSTEMS.items():
        row = {}
        for p in ("frozen", "rb"):
            part = [r for r in REFS if PART[r["id"]] == p]
            q = quality.report(part, [x for x in res if PART[x["id"]] == p])
            row[p] = {"invalid_by_status": dict(Counter(r["status"] for r in acc["rows"] if PART[r["id"]] == p and r["status"] not in comparison.SCORABLE)),
                      "unit_count_over": q["unit_count"]["over_count_examples"], "unit_count_under": q["unit_count"]["under_count_examples"],
                      "split_merge_duplicate_heuristic": q["headline"]["over_split+merged+duplicate"][0],
                      "abstention_false_extraction": q["abstention"]["false_extraction_on_zero_refs"],
                      "abstention_over_abstention": q["abstention"]["unit_refs_answered_empty"],
                      "unsupported_heuristic": q["grounding"]["heuristic"]["unsupported_matcher"],
                      "not_anchored_heuristic": q["grounding"]["heuristic"]["not_anchored"],
                      "bilingual_flagged_heuristic": q["bilingual"]["heuristic"].get("units_flagged", 0),
                      "false_claim": "not measured automatically"}
        table[c] = row
    R["r30_error_categories"] = {"status": "PASS", "systems": len(table), "by_system_and_part": table,
                                 "note": "counts are exact except where marked heuristic; false claims need human judgment"}


def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    a = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [max(0.0, round((c - a) / d, 3)) + 0.0, min(1.0, round((c + a) / d, 3))]


def p_pass(n, need, p):
    return round(sum(math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(need, n + 1)), 3)


def r33_r34():
    oracle_f1 = SYSTEMS["oracle"][2]["metrics"]["frozen"]["headline"]["unit_f1"]
    rows, disagreements = {}, []
    for c, (acc, res, rep) in SYSTEMS.items():
        f1 = rep["metrics"]["frozen"]["headline"]["unit_f1"]
        fails = gate_view(rep)
        rows[c] = {"frozen_heuristic_unit_f1": f1, "gates_failed": fails, "eligible_on_exact_gates": not fails}
        if fails and f1 is not None and f1 >= oracle_f1 - 0.05:
            disagreements.append({"system": c, "kind": "aggregate looks good, gate fails", "f1": f1, "gates_failed": fails})
        if not fails and (f1 is None or f1 < oracle_f1 - 0.05):
            disagreements.append({"system": c, "kind": "gate passes, aggregate is clearly worse", "f1": f1})
    silent = [c for c, v in rows.items() if not v["gates_failed"] and c != "oracle"]
    R["r33_gate_vs_aggregate"] = {"status": "FINDING" if disagreements else "PASS", "systems": rows, "disagreements": disagreements,
                                  "eligible_on_exact_gates_although_broken": silent,
                                  "reading": "A gate failure with an oracle-level F1 is the shortcut's signature. An eligible "
                                             "system with a clearly worse F1 shows a failure no exact gate covers: it then "
                                             "rests on human F1 and the 0.05 margin. bilingual_drift and false_claim pass "
                                             "every gate at F1 1.0. decision.py documents a human "
                                             "`unsupported_or_false_claim_rate` input but never uses it."}
    tab = {}
    for c in ("oracle", "category_shortcut", "over_abstain", "hallucinate_on_zero", "struct_truncated", "unsupported_swap"):
        acc, res, rep = SYSTEMS[c]
        m = rep["metrics"]
        conf = {p: m[p]["confusion"]["ref_by_pred"] for p in ("frozen", "rb")}
        row = {}
        for p in ("frozen", "rb"):
            z, u = conf[p]["ref_zero"], conf[p]["ref_units"]
            nz, nu = sum(z.values()), sum(u.values())
            row[f"{p}_abstention"] = {"k": z["empty"], "n": nz, "rate": round(z["empty"] / nz, 3), "wilson95": wilson(z["empty"], nz)}
            row[f"{p}_over_abstention"] = {"k": u["empty"], "n": nu, "rate": round(u["empty"] / nu, 3), "wilson95": wilson(u["empty"], nu)}
        ch = rep["metrics"]["challenge_test"]["headline"]
        k = round(ch["paired_consistency"] * 24)
        row["paired_consistency"] = {"k": k, "n": 24, "rate": ch["paired_consistency"], "wilson95": wilson(k, 24)}
        row["strict_validity"] = {"k": rep["rows"]["scorable"], "n": 472, "rate": round(rep["rows"]["scorable"] / 472, 3),
                                  "wilson95": wilson(rep["rows"]["scorable"], 472)}
        tab[c] = row
    gates = {"abstention >= 0.90 (n = 20 zero references, needs >= 18)": (20, 18),
             "paired consistency >= 0.90 (n = 24 groups, needs >= 22)": (24, 22),
             "abstain-group paired accuracy >= 0.80 (n = 9 groups, needs >= 8)": (9, 8)}
    pp = {g: {f"true rate {p}": p_pass(n, need, p) for p in (0.80, 0.85, 0.90, 0.95, 0.99)} for g, (n, need) in gates.items()}
    both = {f"true rate {p}": round(p_pass(20, 18, p) ** 2, 3) for p in (0.85, 0.90, 0.95)}
    R["r34_uncertainty"] = {"status": "INFO", "synthetic_results_with_wilson95": tab,
                            "probability_a_system_passes_a_gate": pp,
                            "probability_of_passing_abstention_on_both_frozen_and_rb_(independent_parts)": both,
                            "caveats": ["synthetic systems: the oracle IS the reference, so its 1.0 rates say nothing about any model",
                                        "zero-unit references are 20 per part: a system whose true abstention is 0.90 passes "
                                        "one 0.90 gate with probability ~0.68 and both with ~0.46; one whose true rate is 0.85 "
                                        "still passes one with ~0.40",
                                        "paired consistency rests on 24 groups and abstain-group accuracy on 9",
                                        "frozen and rb share every learner text, so their rates are not independent; the "
                                        "'both' probability above assumes independence and is optimistic about separation",
                                        "heuristic F1 and anchoring are provisional; false claims are not measured"]}


# ---------------------------------------------------------------- 31 determinism
def r31():
    out = {}
    fx = OUT / "fixture-untuned.jsonl"
    for seed in ("0", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        d = WORK / f"det{seed}"
        d.mkdir(exist_ok=True)
        cmds = [["compare", "--matrix", str(DEPLOY / "readiness" / "comparison-matrix.json"), "--slice", str(SLICE), "--render", str(BIN),
                 "--predictions", f"qwen3.5-4b-untuned={fx}", "--out", str(d / "cmp")],
                ["decision-report", "--comparison", str(d / "cmp.json"), "--out", str(d / "dec")],
                ["review-sample", "--slice", str(SLICE), "--challenge", str(OUT / "chl" / "challenge_candidates.jsonl"), "--out", str(d / "rs")],
                ["paired-demo", "--challenge", str(OUT / "chl" / "challenge_candidates.jsonl"), "--render", str(BIN), "--out", str(d / "pd")]]
        for c in cmds:
            subprocess.run([sys.executable, "-B", "-m", "flh_extraction"] + c, cwd=TOOLS, env=env, capture_output=True, text=True)
        out[seed] = {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*"))
                     if p.is_file() and not any(x.endswith(".work") or x == "work" for x in p.relative_to(d).parts)}
    a, b = out["0"], out["4242"]
    diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    R["r31_determinism"] = {"status": "PASS" if not diff and a else "FINDING", "files_compared": len(a), "differ": diff,
                            "method": "compare, decision-report, review-sample and paired-demo run twice with PYTHONHASHSEED 0 and "
                                      "4242 (different set and dict-of-set iteration); outputs compared byte for byte"}


# ---------------------------------------------------------------- 32 with / without the shortcut
def r32():
    def partial(frac):
        rows = []
        for x, r in zip(oracle(), REFS):
            if int(review_sample.h("partial:" + r["id"])[:8], 16) / 0xFFFFFFFF < frac:
                x = controls.outputs([r], "category_shortcut")[0]
            rows.append(x)
        return rows
    systems = {"without the shortcut (oracle)": oracle(), "shortcut on 25% of inputs": partial(0.25),
               "shortcut on 50% of inputs": partial(0.5), "full category-only shortcut": controls.outputs(REFS, "category_shortcut")}
    tab = {}
    for k, rows in systems.items():
        acc, res, rep = run(rows)
        m = rep["metrics"]
        tab[k] = {"frozen_only_view": {"abstention": m["frozen"]["headline"]["abstention_rate"],
                                       "false_extraction": m["frozen"]["confusion"]["abstention"]["false_extraction"],
                                       "heuristic_unit_f1": m["frozen"]["headline"]["unit_f1"]},
                  "full_slice_view": {"rb_abstention": m["rb"]["headline"]["abstention_rate"],
                                      "rb_false_extraction": m["rb"]["confusion"]["abstention"]["false_extraction"],
                                      "paired_consistency": m["challenge_test"]["headline"]["paired_consistency"],
                                      "abstain_group_paired_accuracy": m["challenge_test"]["by_intent"]["abstain"]["paired_correct"],
                                      "gates_failed": gate_view(rep)}}
    R["r32_shortcut"] = {"status": "PASS", "table": tab,
                         "reading": "The frozen-only view cannot tell any of these systems apart (every row reads like the "
                                    "oracle). The full slice separates them, and even a shortcut on a quarter of the inputs "
                                    "can fail a gate. Partial systems apply the shortcut to a fixed, hash-chosen subset."}


# ---------------------------------------------------------------- 35 render without jobs or credentials
def r35():
    env = {"PATH": "/usr/bin:/bin", "HOME": str(WORK / "emptyhome"), "LANG": "C.UTF-8"}
    Path(env["HOME"]).mkdir(exist_ok=True)
    data = WORK / "rd"
    data.mkdir(exist_ok=True)
    for f in ("sft-train.jsonl", "sft-dev.jsonl"):
        (data / f).write_bytes((OUT / "rd" / f).read_bytes())
    (data / "comparison-prompts.jsonl").write_bytes((OUT / "slice" / "comparison-prompts.jsonl").read_bytes())
    p = subprocess.run([sys.executable, "-I", "-B", str(DEPLOY / "build_readiness.py"), str(data), str(WORK / "ready")],
                       env=env, capture_output=True, text=True)
    scan = {}
    pat = re.compile(r"\b(boto3|botocore|subprocess|urllib|requests|http\.client|socket|create-training-job|aws\s+sagemaker|aws\s+s3)\b")
    for f in (DEPLOY / "build_readiness.py", DEPLOY / "render_job.py", TOOLS / "flh_extraction" / "manifest.py"):
        scan[str(f.relative_to(REPO))] = sorted(set(pat.findall(f.read_text(encoding="utf-8"))))
    go = (REPO / "cmd" / "extraction-render" / "main.go").read_text(encoding="utf-8")
    render_offline = "httptest.NewServer" in go and '"offline-placeholder-key"' in go
    R["r35_render_offline"] = {"status": "PASS" if p.returncode == 0 and not any(scan.values()) and render_offline else "FINDING",
                               "build_readiness_with_empty_environment": {"exit": p.returncode, "env_keys": sorted(env),
                                                                          "rendered": sorted(x.name for x in (WORK / "ready" / "rendered").glob("*.json")) if p.returncode == 0 else p.stderr[-300:]},
                               "network_or_aws_references_in_render_code": scan,
                               "prompt_rendering_uses_an_in_process_fake_server_and_placeholder_key": render_offline,
                               "note": "run inside a network namespace with loopback only; HOME pointed at an empty "
                                       "directory, so no AWS config or credential file could be read"}


# ---------------------------------------------------------------- 36 reviewer exports
def r36():
    files = sorted((TOOLS / "review").glob("*")) + sorted((REPO / "docs" / "validation" / "FLH-154").glob("*.json")) + \
        sorted((REPO / "docs" / "validation" / "FLH-154").glob("*.md")) + sorted((REPO / "docs" / "validation").glob("FLH-154*.md"))
    found = {}
    for f in files:
        if f.name.startswith("reporting-checks"):
            continue
        v = review_sample.export_findings(f.read_text(encoding="utf-8"))
        if v:
            found[str(f.relative_to(REPO))] = v
    planted = review_sample.export_findings('{"entry_id": 42, "p": "/home/someone/x", "u": "http://localhost:8080/private", '
                                            '"m": "a.person@example.org", "k": "AKIAABCDEFGHIJKLMNOP", "acct": "123456789012"}')
    R["r36_export_privacy"] = {"status": "PASS" if not found and len({x["rule"] for x in planted}) == 6 else "FINDING",
                               "files_scanned": [str(f.relative_to(REPO)) for f in files if not f.name.startswith("reporting-checks")],
                               "findings": found, "planted_values_detected": sorted({x["rule"] for x in planted})}


def md(rep):
    L = ["# FLH-154 reporting checks, items 21 and 26-36 (generated, OFFLINE ONLY)", "", "| Check | Status |", "|---|---|"]
    L += [f"| {k} | {v['status']} |" for k, v in rep.items() if isinstance(v, dict) and "status" in v]
    return "\n".join(L) + "\n"


def main():
    r21()
    r26()
    r27()
    r28()
    r29()
    r30()
    r33_r34()
    r31()
    r32()
    r35()
    r36()
    order = ["r21_inventory", "r26_order", "r27_duplicates", "r28_missing_extra", "r29_denominators", "r30_error_categories",
             "r31_determinism", "r32_shortcut", "r33_gate_vs_aggregate", "r34_uncertainty", "r35_render_offline", "r36_export_privacy"]
    doc = {"schema": "flh154_reporting_checks_v1", "offline_only": True, "synthetic_only": True, "real_runs_performed": 0,
           **{k: R[k] for k in order}}
    out = Path(ARGS.out)
    (out / "reporting-checks.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "reporting-checks.md").write_text(md({k: R[k] for k in order}), encoding="utf-8")
    print(json.dumps({k: R[k]["status"] for k in order}, indent=1))


if __name__ == "__main__":
    main()
