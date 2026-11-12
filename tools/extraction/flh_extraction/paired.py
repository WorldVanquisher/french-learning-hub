"""Paired-consistency metric on the cue challenge slice.

  python3 -m flh_extraction paired-consistency --challenge C.jsonl --results V.jsonl [--outputs O.jsonl] --out PREFIX
  python3 -m flh_extraction paired-demo --challenge C.jsonl --render BIN --out DIR
        (oracle, category-only and constant-empty systems through the production validator)

A group's variants share the learner text and the reference; only the cues
differ. Per group (exact unless marked):

  decision_consistent   every variant got the same decision (units / empty);
                        an invalid or missing output is never consistent
  count_consistent      every variant got the same number of units
  objective_consistent  same unit count and the same matched reference units
                        in every variant (HEURISTIC: evaluate.similarity matching)
  paired_correct        every variant has the reference decision and unit count
  cue_flip              aligned and conflicting got different valid decisions

Headline: paired consistency (decision_consistent rate) and paired accuracy
(paired_correct rate). Consistency alone rewards a constant answer, so both are
reported, with per-variant accuracy and the aggregate quality numbers (unit
F1, abstention, structural validity) alongside, never folded into one score.
"""

from . import challenge, comparison, controls, evaluate, quality

VARIANTS = challenge.VARIANTS


def matched(ref_units, pred_units):
    if not ref_units or not pred_units:
        return frozenset()
    sim = [[evaluate.similarity(p, r) for r in ref_units] for p in pred_units]
    return frozenset(r for _, r in evaluate.best_assignment(sim))


def _rate(n, d):
    return round(n / d, 3) if d else None


def report(chl, results, outputs=None):
    res = {r["id"]: r for r in results}
    groups = challenge.groups_of(chl)
    rows = []
    for gid, rs in groups.items():
        by = {r["meta"]["challenge"]["variant"]: r for r in rs}
        ref = rs[0]["expected"]["units"]
        want = "units" if ref else "empty"
        dec, cnt, obj, ok = {}, {}, {}, {}
        for v, r in by.items():
            x = res.get(r["id"])
            dec[v] = comparison.decision(x)
            valid = dec[v] in ("units", "empty")
            cnt[v] = len(x["units"]) if valid else None
            obj[v] = matched(ref, x["units"]) if valid else None
            ok[v] = dec[v] == want and cnt[v] == len(ref)
        bad = any(d in ("invalid", "missing") for d in dec.values())
        a, c = dec.get("aligned"), dec.get("conflicting")
        rows.append({"group_id": gid, "intent": rs[0]["meta"]["challenge"]["intent"], "split": rs[0]["meta"]["split_group"],
                     "decisions": dec, "counts": cnt,
                     "decision_consistent": not bad and len(set(dec.values())) == 1,
                     "count_consistent": not bad and len(set(cnt.values())) == 1,
                     "objective_consistent": not bad and len(set(cnt.values())) == 1 and len(set(obj.values())) == 1,
                     "paired_correct": all(ok.values()) and len(ok) == len(VARIANTS),
                     "cue_flip": a in ("units", "empty") and c in ("units", "empty") and a != c,
                     "invalid_or_missing": bad})

    def comp(rs):
        n = len(rs)
        return {"groups": n, **{k: {"count": sum(r[k] for r in rs), "rate": _rate(sum(r[k] for r in rs), n)}
                               for k in ("decision_consistent", "count_consistent", "objective_consistent", "paired_correct",
                                         "cue_flip", "invalid_or_missing")}}
    rep = {"schema": "flh_extraction_paired_consistency_v1", "scoring_version": comparison.scoring_version()["sha256"],
           "basis": {"decision_consistent": "exact", "count_consistent": "exact", "objective_consistent": "heuristic",
                     "paired_correct": "exact", "cue_flip": "exact"},
           "all": comp(rows), "by_intent": {i: comp([r for r in rows if r["intent"] == i]) for i in ("extract", "abstain")},
           "by_split": {s: comp([r for r in rows if r["split"] == s]) for s in challenge.SPLITS}}
    per_variant = {}
    for v in VARIANTS:
        ex = [r for r in rows if r["intent"] == "extract"]
        ab = [r for r in rows if r["intent"] == "abstain"]
        per_variant[v] = {"decision_accuracy": _rate(sum(r["decisions"][v] == ("units" if r["intent"] == "extract" else "empty")
                                                         for r in rows), len(rows)),
                          "abstention_on_abstain_groups": _rate(sum(r["decisions"][v] == "empty" for r in ab), len(ab)),
                          "over_abstention_on_extract_groups": _rate(sum(r["decisions"][v] == "empty" for r in ex), len(ex)),
                          "invalid_or_missing": sum(r["decisions"][v] in ("invalid", "missing") for r in rows)}
    rep["per_variant"] = per_variant
    q = quality.report(chl, results, outputs=outputs)
    rep["aggregate"] = {"heuristic_unit_f1": q["headline"]["unit_f1"][0], "abstention_rate": q["headline"]["abstention_rate"][0],
                        "over_abstention_rate": q["abstention"]["over_abstention_rate"],
                        "structural_validity": q["headline"]["structural_validity"][0],
                        "exact_unit_count_rate": q["headline"]["exact_unit_count_rate"][0]}
    rep["headline"] = {"paired_consistency": rep["all"]["decision_consistent"]["rate"],
                       "paired_accuracy": rep["all"]["paired_correct"]["rate"],
                       "cue_flip_rate": rep["all"]["cue_flip"]["rate"], **rep["aggregate"]}
    rep["groups"] = rows
    return rep


def demo(chl, validate):
    """{system: report} for the three synthetic systems."""
    out = {}
    for name, control in comparison.SYSTEMS.items():
        rows = controls.outputs(chl, control)
        out[name] = report(chl, validate(rows), outputs=rows)
    return out


def markdown(reports, title="Paired consistency on the cue challenge slice"):
    L = [f"# {title}", "",
         "Exact unless marked. Paired consistency = every variant of a group got the same decision; paired accuracy = "
         "every variant got the reference decision and unit count. Aggregate numbers are reported beside them, "
         "never combined.", "",
         "| System | Paired consistency | Paired accuracy | Cue flips | Count consistent | Objective consistent (heuristic) "
         "| Aggregate F1 (heuristic) | Abstention | Over-abstention | Validity |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in reports.items():
        a, h = r["all"], r["headline"]
        L.append(f"| {name} | {a['decision_consistent']['count']}/{a['groups']} ({h['paired_consistency']}) "
                 f"| {a['paired_correct']['count']}/{a['groups']} ({h['paired_accuracy']}) | {a['cue_flip']['count']} "
                 f"| {a['count_consistent']['count']} | {a['objective_consistent']['count']} | {h['heuristic_unit_f1']} "
                 f"| {h['abstention_rate']} | {h['over_abstention_rate']} | {h['structural_validity']} |")
    L += ["", "## By intent (paired consistency / paired accuracy)", "", "| System | extract groups | abstain groups |", "|---|---|---|"]
    for name, r in reports.items():
        e, b = r["by_intent"]["extract"], r["by_intent"]["abstain"]
        L.append(f"| {name} | {e['decision_consistent']['count']}/{e['groups']} / {e['paired_correct']['count']}/{e['groups']} "
                 f"| {b['decision_consistent']['count']}/{b['groups']} / {b['paired_correct']['count']}/{b['groups']} |")
    L += ["", "## Per variant (decision accuracy · abstention on abstain groups · over-abstention on extract groups)", "",
          "| System | aligned | conflicting | rb |", "|---|---|---|---|"]
    for name, r in reports.items():
        cells = [f"{p['decision_accuracy']} · {p['abstention_on_abstain_groups']} · {p['over_abstention_on_extract_groups']}"
                 for p in (r["per_variant"][v] for v in VARIANTS)]
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(L) + "\n"
