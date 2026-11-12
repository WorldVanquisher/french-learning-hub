"""Pre-registered acceptance criteria for promoting a trained extractor
candidate, evaluated mechanically (PASS / FAIL / PENDING).

  python3 -m flh_extraction promotion-check --candidate-frozen Q.json --candidate-probe Q.json
         --baseline-frozen Q.json [--baseline-probe Q.json] [--losses losses.jsonl]
         [--run-manifest run_manifest.json] [--input-manifest input-manifest.json]
         [--review verdicts.jsonl] --out PREFIX

Inputs are `quality` reports (frozen evaluation and the `rb` production-input
probe), the training run's losses and manifest, the readiness input manifest
and the filled review packet. "Promotion" means only: eligible to be proposed
to the owner as the extractor candidate in a separate, owner-approved
integration task. Nothing here routes production traffic, and every
run_manifest keeps suitable_for_production false.

A criterion that needs human judgments is PENDING without them; heuristic
metrics (split/merge, grounding, bilingual) are reported and never gate. The
overall verdict is ELIGIBLE_FOR_OWNER_DECISION only when every criterion
passes; any FAIL makes it NOT_ELIGIBLE; otherwise PENDING.
"""

import json

CRITERIA_VERSION = "flh_extractor_promotion_v1 (pre-registered 2026-11-12)"
STRUCTURAL_MIN = 0.98
ABSTENTION_MIN = 0.90
PROBE_ABSTENTION_DROP_MAX = 0.10
PROBE_OVER_ABSTENTION_EXTRA_MAX = 0.05
COUNT_MARGIN = 0.05
F1_MARGIN = 0.05
HUMAN_EXAMPLES_MIN = 100
REVIEW_MIN, REVIEW_REJECT_MAX = 25, 0.10


def _h(rep, k):
    return rep["headline"][k][0]


def _c(name, basis, status, evidence):
    return {"criterion": name, "basis": basis, "status": status, "evidence": evidence}


def check(cand_frozen, cand_probe, base_frozen, base_probe=None, losses=None, run_manifest=None,
          input_manifest=None, review=None):
    out = []
    for label, rep in (("frozen", cand_frozen), ("probe", cand_probe)):
        v = _h(rep, "structural_validity")
        out.append(_c(f"structural_validity_{label} >= {STRUCTURAL_MIN}", "exact",
                      "PENDING" if v is None else "PASS" if v >= STRUCTURAL_MIN else "FAIL", v))
        v = _h(rep, "abstention_rate")
        out.append(_c(f"abstention_rate_{label} >= {ABSTENTION_MIN}", "exact",
                      "PENDING" if v is None else "PASS" if v >= ABSTENTION_MIN else "FAIL", v))
    fa, pa = _h(cand_frozen, "abstention_rate"), _h(cand_probe, "abstention_rate")
    units = cand_frozen["abstention"]["unit_refs"] or 1
    fe, pe = _h(cand_frozen, "unit_refs_answered_empty"), _h(cand_probe, "unit_refs_answered_empty")
    ok = None if fa is None or pa is None else (fa - pa <= PROBE_ABSTENTION_DROP_MAX and (pe - fe) / units <= PROBE_OVER_ABSTENTION_EXTRA_MAX)
    out.append(_c("production-input robustness: probe abstention drop <= 0.10 and extra over-abstention <= 5% of unit refs",
                  "exact", "PENDING" if ok is None else "PASS" if ok else "FAIL",
                  {"abstention_frozen": fa, "abstention_probe": pa, "unit_refs_empty_frozen": fe, "unit_refs_empty_probe": pe}))
    c, b = _h(cand_frozen, "exact_unit_count_rate"), _h(base_frozen, "exact_unit_count_rate")
    out.append(_c(f"exact_unit_count_rate >= baseline - {COUNT_MARGIN}", "exact",
                  "PENDING" if c is None or b is None else "PASS" if c >= b - COUNT_MARGIN else "FAIL",
                  {"candidate": c, "baseline": b}))
    ch, bh = cand_frozen["semantic"]["human"], base_frozen["semantic"]["human"]
    if ch["examples"] < HUMAN_EXAMPLES_MIN or bh["examples"] < HUMAN_EXAMPLES_MIN or ch["unit_f1"] is None or bh["unit_f1"] is None:
        st = "PENDING"
    else:
        st = "PASS" if ch["unit_f1"] >= bh["unit_f1"] - F1_MARGIN else "FAIL"
    out.append(_c(f"human-judged unit F1 >= baseline - {F1_MARGIN} (>= {HUMAN_EXAMPLES_MIN} judged examples each)", "human", st,
                  {"candidate": ch["unit_f1"], "baseline": bh["unit_f1"], "judged": [ch["examples"], bh["examples"]]}))
    cu, bu = cand_frozen["grounding"]["human"], base_frozen["grounding"]["human"]
    st = "PENDING" if not cu["judged"] or not bu["judged"] else ("PASS" if cu["unsupported"] / cu["judged"] <= bu["unsupported"] / bu["judged"] else "FAIL")
    out.append(_c("human-judged unsupported/false-claim rate <= baseline", "human", st,
                  {"candidate": [cu["unsupported"], cu["judged"]], "baseline": [bu["unsupported"], bu["judged"]]}))
    if losses is None:
        out.append(_c("dev loss never rises at two consecutive evaluations", "exact", "PENDING", "no losses.jsonl"))
    else:
        dev = [e["dev_loss"] for e in losses if "dev_loss" in e]
        rises = [dev[k] > dev[k - 1] and dev[k - 1] > dev[k - 2] for k in range(2, len(dev))]
        out.append(_c("dev loss never rises at two consecutive evaluations", "exact",
                      "PENDING" if len(dev) < 3 else "FAIL" if any(rises) else "PASS", dev))
    if run_manifest is None or input_manifest is None:
        out.append(_c("training data = readiness manifest; suitable_for_production false", "exact", "PENDING", "manifests missing"))
    else:
        files = input_manifest["files"]
        ok = (run_manifest.get("train_sha256") == files["sft-train.jsonl"]["sha256"]
              and run_manifest.get("dev_sha256") == files["sft-dev.jsonl"]["sha256"]
              and run_manifest.get("suitable_for_production") is False and run_manifest.get("smoke") is False)
        out.append(_c("training data = readiness manifest; suitable_for_production false", "exact", "PASS" if ok else "FAIL",
                      {k: run_manifest.get(k) for k in ("train_sha256", "dev_sha256", "suitable_for_production", "smoke")}))
    if not review:
        out.append(_c(f"review packet: >= {REVIEW_MIN} verdicts, <= {REVIEW_REJECT_MAX:.0%} rejected", "human", "PENDING", "no verdicts"))
    else:
        done = [r for r in review if r.get("verdict")]
        rej = sum(r["verdict"] == "reject" for r in done)
        st = "PENDING" if len(done) < REVIEW_MIN else "PASS" if rej / len(done) <= REVIEW_REJECT_MAX else "FAIL"
        out.append(_c(f"review packet: >= {REVIEW_MIN} verdicts, <= {REVIEW_REJECT_MAX:.0%} rejected", "human", st,
                      {"verdicts": len(done), "rejected": rej}))
    statuses = {c["status"] for c in out}
    verdict = "NOT_ELIGIBLE" if "FAIL" in statuses else "ELIGIBLE_FOR_OWNER_DECISION" if statuses == {"PASS"} else "PENDING"
    info = {"heuristic_reported_not_gating": {k: (_h(cand_frozen, k), _h(base_frozen, k)) for k in
                                              ("over_split+merged+duplicate", "not_anchored_units", "unsupported_units",
                                               "bilingual_flagged_units", "unit_f1")}}
    if base_probe is not None:
        info["baseline_probe_abstention"] = _h(base_probe, "abstention_rate")
    return {"schema": "flh_extractor_promotion_check_v1", "criteria_version": CRITERIA_VERSION, "verdict": verdict,
            "criteria": out, **info}


def markdown(rep):
    L = [f"# Promotion check: **{rep['verdict']}**", "", f"Criteria: {rep['criteria_version']}. Promotion means only "
         "eligibility for an owner decision; nothing is routed to production.", "",
         "| Criterion | Basis | Status | Evidence |", "|---|---|---|---|"]
    for c in rep["criteria"]:
        L.append(f"| {c['criterion']} | {c['basis']} | {c['status']} | `{json.dumps(c['evidence'], ensure_ascii=False)}` |")
    L += ["", "Heuristic metrics (candidate, baseline), reported and not gating: "
          f"`{json.dumps(rep['heuristic_reported_not_gating'])}`", ""]
    return "\n".join(L)
