"""Experimental decision report (DRAFT, OFFLINE ONLY): it can never issue a production GO.

  python3 -m flh_extraction experimental-report --comparison REPORT.json [--human-evidence H.json]
         [--review P.jsonl …] [--reviewer-queue Q.json --reviewer-evidence E.jsonl] --out PREFIX

It sits beside the pre-registered `decision-report` (decision.py), which it
neither replaces nor changes: it reuses `decision.gates` and `decision.reviewed`
as they are. Its only possible positive outcome is EXPERIMENTAL_PREFERENCE, a
note on which system to study next. Every report carries `production_go: false`;
there is no input, flag or value that sets it.

Verdicts (exit code):
  EXPERIMENTAL_PREFERENCE (0)  every criterion below decided, exactly one system passes
                               all of them and leads on human unit F1 by >= 0.05
                               (compared at 3 decimals)
  NO_PREFERENCE (1)            every criterion decided, but no system passes them all or
                               the lead is too small
  PENDING (3)                  a run is missing or incomplete, review is unfinished,
                               human evidence is missing or declared unavailable, or a
                               unit in the reviewer scope has no complete review
  BLOCKED (1)                  the comparison was refused, or the human review of the
                               references failed (rejected > 10 % of the items)

Human evidence (per system; every field is required, and a missing field is
PENDING, never zero):

  {"<system>": {"unit_f1": 0.0, "judged_examples": 0, "judged_objectives": 0,
                "false_claims": {"judged_units": 0, "false": 0},
                "unsupported_units": {"judged_units": 0, "unsupported": 0},
                "bilingual_mismatch": {"judged_units": 0, "mismatched": 0}}}

`false_claims` counts judged units whose statement is false or over-general
(FALSE_CLAIM). `unsupported_units` counts units the interaction did not raise.
They are separate questions and separate fields.

Unavailable human review: `{"<system>": {"unavailable": {"reason": "…"}}}` (or the
top-level key `"unavailable": {"reason": "…"}` for all systems). The report
records the reason and stays PENDING: it never substitutes a verdict, a default
rate or the heuristic numbers. Exact-gate failures are still reported, because
they need no human judgment; a positive preference always does.

Per-unit reviewer evidence (reviewer_evidence.py, FLH-154 part 4): the automatic
metrics accept a plausible unit linked to the wrong source, a false claim and a
drifted Chinese statement (fixtures/one_record_v1). Every measured system
therefore also needs the criterion "reviewer evidence: every in-scope unit
reviewed, no explicit failure", computed from a reviewer queue (built from the
same matrix and predictions) and the evidence rows bound to its units by hash:
  - no queue, a queue for another comparison, or any in-scope unit without one
    complete bound review: PENDING (a missing review is never a pass);
  - any explicit `no` (source not raised, claim false, Chinese different): the
    system is excluded, whatever its sample rates or F1; it can never be the
    preference.
The aggregate rates above are sample estimates; the per-unit evidence is a hard
check on the records in the review scope. Both are required.

Thresholds are DRAFT values for the owner to confirm before any real run.
"""

import json

from . import decision, reviewer_evidence

SCHEMA = "flh_extractor_experimental_report_v1"
STATUS = "DRAFT, offline only, not pre-registered; never a production decision"
VERDICTS = ("EXPERIMENTAL_PREFERENCE", "NO_PREFERENCE", "PENDING", "BLOCKED")
EXIT = {"EXPERIMENTAL_PREFERENCE": 0, "NO_PREFERENCE": 1, "PENDING": 3, "BLOCKED": 1}
DRAFT = {"judged_examples_min": 100, "judged_objectives_min": 45, "judged_units_min": 100,
         "false_claim_rate_max": 0.02, "unsupported_rate_max": 0.05, "bilingual_mismatch_rate_max": 0.10,
         "f1_lead_min": 0.05, "review_reject_max": 0.10}
FIELDS = ("unit_f1", "judged_examples", "judged_objectives", "false_claims", "unsupported_units", "bilingual_mismatch")


def _c(name, basis, status, evidence):
    return {"criterion": name, "basis": basis, "status": status, "evidence": evidence}


def _rate(name, ev, num, max_rate):
    if not isinstance(ev, dict) or "judged_units" not in ev or num not in ev:
        return _c(f"{name} rate <= {max_rate}", "human", "PENDING", "missing evidence")
    n, k = ev["judged_units"], ev[num]
    if n < DRAFT["judged_units_min"]:
        return _c(f"{name} rate <= {max_rate}", "human", "PENDING", f"{n} judged units < {DRAFT['judged_units_min']}")
    r = round(k / n, 3)
    return _c(f"{name} rate <= {max_rate}", "human", "PASS" if r <= max_rate else "FAIL", {"rate": r, "judged_units": n, num: k})


def human_criteria(h):
    """Criteria for one system's human evidence; missing evidence is PENDING."""
    if not isinstance(h, dict):
        return [_c("human evidence present", "human", "PENDING", "missing evidence")], None
    if "unavailable" in h:
        return [_c("human evidence present", "human", "PENDING",
                   {"unavailable": h["unavailable"].get("reason", "no reason given"), "verdict": "none invented"})], None
    out = []
    ex, ob = h.get("judged_examples"), h.get("judged_objectives")
    f1 = h.get("unit_f1")
    ok = f1 is not None and ex is not None and ob is not None and ex >= DRAFT["judged_examples_min"] and ob >= DRAFT["judged_objectives_min"]
    out.append(_c(f"human unit F1 recorded (>= {DRAFT['judged_examples_min']} examples over >= {DRAFT['judged_objectives_min']} objectives)",
                  "human", "PASS" if ok else "PENDING", {k: h.get(k) for k in ("unit_f1", "judged_examples", "judged_objectives")}))
    out.append(_rate("human false-claim", h.get("false_claims"), "false", DRAFT["false_claim_rate_max"]))
    out.append(_rate("human unsupported-unit", h.get("unsupported_units"), "unsupported", DRAFT["unsupported_rate_max"]))
    out.append(_rate("human bilingual-mismatch", h.get("bilingual_mismatch"), "mismatched", DRAFT["bilingual_mismatch_rate_max"]))
    return out, (round(f1, 3) if ok else None)


def review_state(review):
    """References' human review: PENDING until every item counts (decision.reviewed:
    a disputed item needs accept / edit / reject and a position); FAIL above the
    reject limit."""
    if not review:
        return _c("reference review finished", "human", "PENDING", "no review packets given")
    done = [r for r in review if decision.reviewed(r)]
    rej = sum(r["verdict"] == "reject" for r in done)
    open_disputes = [r.get("id") for r in review if (r.get("dispute") or {}).get("status") == "disputed" and not decision.reviewed(r)]
    no_verdict = [r.get("id") for r in review if not r.get("verdict")]
    ev = {"items": len(review), "counted": len(done), "rejected": rej, "open_disputes": open_disputes, "no_verdict": len(no_verdict)}
    if done and rej / len(done) > DRAFT["review_reject_max"]:
        return _c(f"reference review: <= {DRAFT['review_reject_max']:.0%} rejected", "human", "FAIL", ev)
    if len(done) < len(review):
        return _c("reference review finished", "human", "PENDING", ev)
    return _c(f"reference review: <= {DRAFT['review_reject_max']:.0%} rejected", "human", "PASS", ev)


def report(comparison, human=None, review=None, reviewer_queue=None, reviewer_evidence_rows=None):
    human = human or {}
    rep = {"schema": SCHEMA, "status": STATUS, "production_go": False,
           "allowed_use": "choose what to study next; never routes traffic; never replaces decision-report",
           "draft_thresholds": DRAFT, "systems": {}, "preference": None, "reasons": []}
    if comparison.get("refused"):
        rep.update(verdict="BLOCKED", reasons=["comparison refused: " + "; ".join(comparison["refused"])])
        return rep
    all_unavailable = human.get("unavailable") if isinstance(human.get("unavailable"), dict) else None
    systems = comparison["systems"]
    missing, incomplete = [], {}
    for s, sr in systems.items():
        if sr.get("status") != "MEASURED":
            missing.append(s)
            rep["systems"][s] = {"status": sr.get("status", "NOT_PERFORMED"), "exact": None, "human": None, "eligible": None}
            continue
        sc = (sr.get("rows") or {}).get("status_counts") or {}
        gap = {k: sc[k] for k in decision.INCOMPLETE_STATUSES if sc.get(k)}
        exact = decision.gates(sr)
        h = {"unavailable": all_unavailable} if all_unavailable else human.get(s)
        hc, f1 = human_criteria(h)
        rc = reviewer_evidence.system_criterion(reviewer_queue, reviewer_evidence_rows, comparison, s)
        exact_fail = [c["criterion"] for c in exact if c["status"] == "FAIL"]
        human_fail = [c["criterion"] for c in hc if c["status"] == "FAIL"]
        reviewer_fail = [f"{x['id']}#{x['unit']}: " + ", ".join(x["answered_no"]) for x in rc["evidence"]["failed"]] if rc["status"] == "FAIL" else []
        pending = [c["criterion"] for c in exact + hc + [rc] if c["status"] == "PENDING"]
        eligible = None if gap else (False if exact_fail or human_fail or reviewer_fail else (None if pending else True))
        rep["systems"][s] = {"status": "MEASURED", "incomplete_run": gap or None, "exact": exact, "human": hc, "reviewer": rc,
                             "excluded_by_exact_gates": exact_fail, "excluded_by_human_evidence": human_fail,
                             "excluded_by_reviewer_evidence": reviewer_fail,
                             "pending": pending, "human_unit_f1": f1, "eligible": eligible}
        if gap:
            incomplete[s] = gap
    rv = review_state(review)
    rep["reference_review"] = rv
    rep["reviewer_scope"] = ({k: reviewer_queue["scope"][k] for k in ("source", "records")} | {"matrix_sha256": reviewer_queue.get("matrix_sha256")}
                             if reviewer_queue else None)
    for s, v in rep["systems"].items():
        if v.get("excluded_by_exact_gates"):
            rep["reasons"].append(f"{s} excluded (exact, needs no human): " + "; ".join(v["excluded_by_exact_gates"]))
        if v.get("excluded_by_human_evidence"):
            rep["reasons"].append(f"{s} excluded (human evidence): " + "; ".join(v["excluded_by_human_evidence"]))
        if v.get("excluded_by_reviewer_evidence"):
            rep["reasons"].append(f"{s} excluded (explicit reviewer failure): " + "; ".join(v["excluded_by_reviewer_evidence"]))
    if rv["status"] == "FAIL":
        rep["verdict"] = "BLOCKED"
        rep["reasons"].insert(0, "reference review failed: too many references rejected; no recommendation until they are fixed")
        return rep
    if missing:
        rep["reasons"].insert(0, "runs not performed: " + ", ".join(missing))
    for s, gap in incomplete.items():
        rep["reasons"].insert(0, f"incomplete run: {s} " + ", ".join(f"{n} {k}" for k, n in gap.items()))
    unavailable = [s for s, v in rep["systems"].items() if v.get("human") and any(
        isinstance(c["evidence"], dict) and "unavailable" in c["evidence"] for c in v["human"])]
    if unavailable:
        rep["reasons"].append("human review unavailable for " + ", ".join(unavailable) + ": no verdict is invented")
    undecided = [s for s, v in rep["systems"].items() if v["status"] == "MEASURED" and v["eligible"] is None]
    if missing or incomplete or rv["status"] == "PENDING" or undecided:
        rep["verdict"] = "PENDING"
        if rv["status"] == "PENDING":
            rep["reasons"].append("reference review unfinished: " + json.dumps(rv["evidence"], ensure_ascii=False))
        if undecided:
            rep["reasons"].append("undecided: " + ", ".join(undecided))
        return rep
    eligible = sorted(((s, v["human_unit_f1"]) for s, v in rep["systems"].items() if v["eligible"]), key=lambda x: -x[1])
    if not eligible:
        rep["verdict"] = "NO_PREFERENCE"
        rep["reasons"].append("no system passes every exact gate and every human criterion")
        return rep
    if len(eligible) > 1 and round(eligible[0][1] - eligible[1][1], 3) < DRAFT["f1_lead_min"]:
        rep["verdict"] = "NO_PREFERENCE"
        rep["reasons"].append(f"lead below {DRAFT['f1_lead_min']} human unit F1: {eligible[0][0]} vs {eligible[1][0]}")
        return rep
    rep["verdict"], rep["preference"] = "EXPERIMENTAL_PREFERENCE", eligible[0][0]
    rep["reasons"].append(f"{eligible[0][0]} is the experimental preference (not a production GO)")
    return rep


def markdown(rep):
    L = [f"# Experimental report (DRAFT, OFFLINE ONLY): **{rep['verdict']}**" + (f" — `{rep['preference']}`" if rep.get("preference") else ""),
         "", f"> {rep['status']}. production_go: **{str(rep['production_go']).lower()}**. {rep['allowed_use']}.", ""]
    L += [f"- {r}" for r in rep["reasons"]] + [""]
    for s, v in rep["systems"].items():
        L += [f"## {s}: {v['status']}, eligible: {v['eligible']}" + (f", INCOMPLETE `{json.dumps(v['incomplete_run'])}`" if v.get("incomplete_run") else ""), ""]
        rows = (v.get("exact") or []) + (v.get("human") or []) + ([v["reviewer"]] if v.get("reviewer") else [])
        if rows:
            L += ["| Criterion | Basis | Status | Evidence |", "|---|---|---|---|"]
            L += [f"| {c['criterion']} | {c['basis']} | {c['status']} | `{json.dumps(c['evidence'], ensure_ascii=False)}` |" for c in rows]
            L.append("")
    if "reference_review" in rep:
        r = rep["reference_review"]
        L += [f"Reference review: {r['status']} `{json.dumps(r['evidence'], ensure_ascii=False)}`", ""]
    return "\n".join(L)
