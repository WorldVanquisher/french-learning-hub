"""Promotion decision across the three compared systems (pre-registered).

  python3 -m flh_extraction decision-report --comparison REPORT.json [--human HUMAN.json]
         [--review V2.jsonl V3.jsonl …] [--losses losses.jsonl] [--run-manifest M] [--input-manifest M] --out PREFIX

REPORT.json is `compare` output for current_extractor, qwen3.5-4b-untuned and
qwen3.5-4b-tuned. HUMAN.json maps each system to its human-judged numbers on
the frozen evaluation: {"<system>": {"unit_f1": x, "judged_examples": n,
"unsupported_or_false_claim_rate": r}}.

Verdicts (exit code):
  WINNER_FOR_OWNER_DECISION (0)  every run measured, every criterion decided,
                                  and exactly one eligible system leads on
                                  human unit F1 by at least WIN_MARGIN
  PENDING (3)                     a run or a human judgment is missing: no winner
  NO_WINNER (1)                   no eligible system, or the lead is too small
  REFUSED (1)                     the comparison itself was refused

A system is eligible only when every exact gate passes. Weak abstention (on
the frozen evaluation, the production-input probe or the challenge's abstain
groups) or a cue-dependent decision makes it ineligible however good its F1.
"Winner" means only: proposed to the owner in a separate, owner-approved
integration task. Nothing here routes production traffic.
"""

import json

VERSION = "flh_extractor_decision_v1 (pre-registered 2026-11-12)"
SYSTEMS = ("current_extractor", "qwen3.5-4b-untuned", "qwen3.5-4b-tuned")
STRICT_VALIDITY_MIN = 0.98
ABSTENTION_MIN = 0.90
OVER_ABSTENTION_MAX = 0.10
PAIRED_CONSISTENCY_MIN = 0.90
ABSTAIN_GROUP_ACCURACY_MIN = 0.80
HUMAN_EXAMPLES_MIN = 100
WIN_MARGIN = 0.05
REVIEW_MIN, REVIEW_REJECT_MAX = 25, 0.10


def _g(name, basis, ok, evidence):
    return {"criterion": name, "basis": basis, "status": "PENDING" if ok is None else "PASS" if ok else "FAIL", "evidence": evidence}


def gates(sysrep):
    """Exact eligibility gates for one measured system."""
    rows, m = sysrep["rows"], sysrep["metrics"]
    fz, rb, ch = m["frozen"]["headline"], m["rb"]["headline"], m["challenge_test"]
    sv = rows["scorable"] / rows["references"] if rows["references"] else None
    out = [_g(f"strict structural validity >= {STRICT_VALIDITY_MIN} (scorable rows / slice rows)", "exact",
              None if sv is None else sv >= STRICT_VALIDITY_MIN, {"scorable": rows["scorable"], "references": rows["references"]})]
    for label, h in (("frozen", fz), ("rb probe", rb)):
        a = h["abstention_rate"]
        out.append(_g(f"abstention on {label} >= {ABSTENTION_MIN}", "exact", None if a is None else a >= ABSTENTION_MIN, a))
    for label, part in (("frozen", m["frozen"]), ("rb probe", m["rb"])):
        o = part["over_abstention_rate"]
        out.append(_g(f"over-abstention on {label} <= {OVER_ABSTENTION_MAX}", "exact", None if o is None else o <= OVER_ABSTENTION_MAX, o))
    pc = ch["headline"]["paired_consistency"]
    out.append(_g(f"challenge paired consistency >= {PAIRED_CONSISTENCY_MIN}", "exact",
                  None if pc is None else pc >= PAIRED_CONSISTENCY_MIN, pc))
    ab = ch["by_intent"]["abstain"]["paired_correct"]
    out.append(_g(f"challenge abstain-group paired accuracy >= {ABSTAIN_GROUP_ACCURACY_MIN}", "exact",
                  None if ab is None else ab >= ABSTAIN_GROUP_ACCURACY_MIN, ab))
    return out


def decide(comparison, human=None, review=None, losses=None, run_manifest=None, input_manifest=None):
    human = human or {}
    rep = {"schema": "flh_extractor_decision_report_v1", "criteria_version": VERSION, "systems": {}, "winner": None,
           "reasons": []}
    if comparison.get("refused"):
        rep.update(verdict="REFUSED", reasons=list(comparison["refused"]))
        return rep
    missing = [s for s in SYSTEMS if comparison["systems"].get(s, {}).get("status") != "MEASURED"]
    for s in SYSTEMS:
        sr = comparison["systems"].get(s, {"status": "NOT_PERFORMED"})
        if sr.get("status") != "MEASURED":
            rep["systems"][s] = {"status": sr.get("status", "NOT_PERFORMED"), "eligible": None, "criteria": []}
            continue
        cs = gates(sr)
        h = human.get(s)
        hf = None if not h or h.get("judged_examples", 0) < HUMAN_EXAMPLES_MIN else h.get("unit_f1")
        cs.append(_g(f"human-judged unit F1 recorded (>= {HUMAN_EXAMPLES_MIN} judged examples)", "human",
                     None if hf is None else True, h))
        exact_fail = any(c["status"] == "FAIL" for c in cs if c["basis"] == "exact")
        weak = [c["criterion"] for c in cs if c["status"] == "FAIL" and ("abstention" in c["criterion"] or "abstain" in c["criterion"]
                                                                         or "consistency" in c["criterion"])]
        rep["systems"][s] = {"status": "MEASURED", "eligible": False if exact_fail else (None if hf is None else True),
                             "weak_abstention_or_cue_dependence": weak, "human_unit_f1": hf, "criteria": cs}
    tuned = rep["systems"]["qwen3.5-4b-tuned"]
    if tuned["status"] == "MEASURED":
        extra = []
        if losses is None:
            extra.append(_g("tuned: dev loss never rises at two consecutive evaluations", "exact", None, "no losses.jsonl"))
        else:
            dev = [e["dev_loss"] for e in losses if "dev_loss" in e]
            rises = any(dev[k] > dev[k - 1] > dev[k - 2] for k in range(2, len(dev)))
            extra.append(_g("tuned: dev loss never rises at two consecutive evaluations", "exact", None if len(dev) < 3 else not rises, dev))
        if run_manifest is None or input_manifest is None:
            extra.append(_g("tuned: training data = readiness manifest; suitable_for_production false", "exact", None, "manifests missing"))
        else:
            f = input_manifest["files"]
            ok = (run_manifest.get("train_sha256") == f["sft-train.jsonl"]["sha256"] and run_manifest.get("dev_sha256") == f["sft-dev.jsonl"]["sha256"]
                  and run_manifest.get("suitable_for_production") is False and run_manifest.get("smoke") is False)
            extra.append(_g("tuned: training data = readiness manifest; suitable_for_production false", "exact", ok,
                            {k: run_manifest.get(k) for k in ("train_sha256", "dev_sha256", "suitable_for_production", "smoke")}))
        tuned["criteria"] += extra
        if any(c["status"] == "FAIL" for c in extra):
            tuned["eligible"] = False
        elif any(c["status"] == "PENDING" for c in extra) and tuned["eligible"]:
            tuned["eligible"] = None
    done = [r for r in (review or []) if r.get("verdict")]
    rej = sum(r["verdict"] == "reject" for r in done)
    need = len(review or [])
    rev = _g(f"review packets: every item has a verdict (>= {REVIEW_MIN}), <= {REVIEW_REJECT_MAX:.0%} rejected", "human",
             None if not review or len(done) < max(REVIEW_MIN, need) else rej / len(done) <= REVIEW_REJECT_MAX,
             {"items": need, "verdicts": len(done), "rejected": rej})
    rep["review"] = rev
    if missing:
        rep["verdict"] = "PENDING"
        rep["reasons"].append(f"runs not performed: {', '.join(missing)}")
    eligible = {s: v for s, v in rep["systems"].items() if v.get("eligible") is True}
    undecided = [s for s, v in rep["systems"].items() if v["status"] == "MEASURED" and v.get("eligible") is None]
    for s, v in rep["systems"].items():
        if v.get("weak_abstention_or_cue_dependence"):
            rep["reasons"].append(f"{s} ineligible: " + "; ".join(v["weak_abstention_or_cue_dependence"]))
    if missing:
        return rep
    if rev["status"] == "PENDING" or undecided:
        rep["verdict"] = "PENDING"
        rep["reasons"].append("human criteria missing: " + ", ".join(undecided + (["review packets"] if rev["status"] == "PENDING" else [])))
        return rep
    if rev["status"] == "FAIL":
        rep["verdict"] = "NO_WINNER"
        rep["reasons"].append("review packets: too many labels rejected; the references need fixing first")
        return rep
    if not eligible:
        rep["verdict"] = "NO_WINNER"
        rep["reasons"].append("no system passes every gate")
        return rep
    ranked = sorted(eligible.items(), key=lambda kv: -kv[1]["human_unit_f1"])
    best = ranked[0]
    if len(ranked) > 1 and best[1]["human_unit_f1"] - ranked[1][1]["human_unit_f1"] < WIN_MARGIN:
        rep["verdict"] = "NO_WINNER"
        rep["reasons"].append(f"lead below {WIN_MARGIN} human unit F1: {best[0]} vs {ranked[1][0]}")
        return rep
    rep["verdict"], rep["winner"] = "WINNER_FOR_OWNER_DECISION", best[0]
    rep["reasons"].append(f"{best[0]} is the only eligible system leading on human unit F1 by >= {WIN_MARGIN}")
    return rep


def markdown(rep):
    L = [f"# Extractor decision: **{rep['verdict']}**" + (f" — `{rep['winner']}`" if rep.get("winner") else ""), "",
         f"Criteria: {rep['criteria_version']}. A winner is only proposed to the owner; nothing is routed to production.", ""]
    L += [f"- {r}" for r in rep["reasons"]] + [""]
    for s, v in rep["systems"].items():
        L += [f"## {s}: {v['status']}" + ("" if v["status"] != "MEASURED" else f", eligible: {v['eligible']}"), ""]
        if v["criteria"]:
            L += ["| Criterion | Basis | Status | Evidence |", "|---|---|---|---|"]
            L += [f"| {c['criterion']} | {c['basis']} | {c['status']} | `{json.dumps(c['evidence'], ensure_ascii=False)}` |"
                  for c in v["criteria"]]
            L.append("")
    if "review" in rep:
        r = rep["review"]
        L += [f"Review packets: {r['status']} `{json.dumps(r['evidence'])}`", ""]
    return "\n".join(L)
