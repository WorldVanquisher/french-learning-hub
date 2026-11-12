"""A short, prioritized human review packet for the extraction data.

  python3 -m flh_extraction review-packet --base T.jsonl --increment I.jsonl --probe P.jsonl --out PREFIX

Deterministic selection (25 items) in priority order: the decisions behind
many labels first, then the newest labels most likely to hold an authoring
error, then splitting boundaries. Nothing here is a verdict: every item is
machine-authored and unreviewed until a reviewer fills `verdict`
(accept / edit / reject / quarantine, ANNOTATION_POLICY.md §5).
"""

import json

from . import audit

SESSION_UNDER_SPLIT = {
    "tr.feminin_eur": "« elle est une » → « c'est une » looks like a second objective (c'est / il est + noun)",
    "tr.conditionnel_politesse": "the added « s'il vous plaît » may be a second objective or part of politeness",
}

RUBRIC = ("decision right? · per unit: grounded / true / atomic / granularity / kind / canonical / EN–ZH agree / example "
          "· verdict: accept / edit / reject / quarantine")


def _item(priority, r, source, question):
    i = r["input"]
    expl = i["effective_explanation"]
    return {"priority": priority, "id": r["id"], "source": source, "question": question,
            "input": i["original_input"], "context": i["original_context"], "category": i["effective_category"],
            "explanation": expl if len(expl) <= 180 else expl[:179] + "…", "resolution": i["resolution"],
            "expected": [{"kind": u["kind"], "canonical": u["canonical"], "statement": u["statement"],
                          "statement_zh": u["statement_zh"], "example": u["example"]} for u in r["expected"]["units"]],
            "rationale": r["meta"].get("rationale"), "label_status": r["meta"].get("label_status"),
            "verdict": None, "reviewer": None, "date": None, "notes": None}


def _first(rs, pred, n, seen):
    out = []
    for r in sorted(rs, key=lambda x: x["id"]):
        if len(out) == n:
            break
        if r["id"] not in seen and pred(r):
            out.append(r)
            seen.add(r["id"])
    return out


def build(base, inc, probe):
    seen, items = set(), []
    mode = lambda m: (lambda r: r["meta"].get("style") == m)  # noqa: E731
    # P1: the cue decision. Zero-unit labels under a production category, and
    # inherited references under the production analyzer.
    for r in _first(inc, lambda r: mode("zero_production_cues")(r) and r["input"]["effective_category"] != "grammar", 2, seen):
        items.append(_item(1, r, "increment", "Is zero units right although the production analyzer gives a non-`other` category?"))
    for r in _first(inc, lambda r: mode("zero_production_cues")(r) and r["input"]["resolution"] == "unreviewed"
                    and r["input"]["effective_category"] == "grammar" and "Journal" not in r["input"]["original_context"], 1, seen):
        items.append(_item(1, r, "increment", "Is zero units right for this input under the rule-based fallback category?"))
    for r in _first(probe, lambda r: not r["expected"]["units"] and r["meta"].get("case_type") == "insufficient", 1, seen):
        items.append(_item(1, r, "probe-rb", "Does the inherited zero-unit reference still hold with the production analyzer's view?"))
    for r in _first(probe, lambda r: r["meta"].get("case_type") == "wrong_explanation", 1, seen):
        items.append(_item(1, r, "probe-rb", "With the wrong explanation replaced by the analyzer's, is the inherited unit still the objective?"))
    for r in _first(probe, lambda r: r["meta"].get("style") == "question_zh", 1, seen):
        items.append(_item(1, r, "probe-rb", "A Chinese question with only the analyzer's fallback explanation: is the inherited unit still right?"))
    # P2: new false-premise labels, one per kind, then wrong explanations.
    kinds_done = set()
    for r in sorted(inc, key=lambda x: x["id"]):
        k = r["expected"]["units"][0]["kind"] if r["expected"]["units"] else None
        if mode("misconception")(r) and k not in kinds_done and len(kinds_done) < 6:
            kinds_done.add(k)
            seen.add(r["id"])
            items.append(_item(2, r, "increment", "Is the premise really false, and does the unit correct it without repeating it?"))
    for r in _first(inc, mode("wrong_explanation"), 3, seen):
        items.append(_item(2, r, "increment", "Is the explanation really wrong, and is the unit the correct rule?"))
    # P3: splitting boundaries.
    for r in _first(inc, mode("two_errors"), 3, seen):
        items.append(_item(3, r, "increment", "Are there exactly two distinct objectives (no third error, no shared rule)?"))
    for r in _first(inc, mode("several_edits_one_objective"), 2, seen):
        items.append(_item(3, r, "increment", "Are the edits one objective (one unit), not two?"))
    for r in _first(inc, mode("fragmentation"), 1, seen):
        items.append(_item(3, r, "increment", "Several forms of one rule: is one unit the right granularity?"))
    # P4: base labels the audit flags as possibly under-split.
    # The audit flags 30 such records; the two points below are the authoring
    # session's reading of that list (a judgment, not a metric).
    for pid, note in SESSION_UNDER_SPLIT.items():
        for r in _first(base, lambda r, pid=pid: r["meta"]["points"] == [pid]
                        and any(audit.edit_regions(a, b) >= 2 for a, b in audit.correction_pairs(r)), 1, seen):
            items.append(_item(4, r, "base", "The correction makes two edits but the label has one unit: is a second "
                                             f"objective missing? (session reading: {note})"))
    # P5: explanation adds rules the learner did not raise.
    for r in _first(inc, mode("explanation_extra"), 2, seen):
        items.append(_item(5, r, "increment", "Is it right to extract only the raised objective and ignore the explanation's extra rule?"))
    return items


def markdown(items):
    L = ["# Extraction review packet (prioritized, 25 items)", "",
         "Every label below is **machine-authored and unreviewed**. Fill `verdict` in the JSONL twin of this file; "
         "only `accept` (or a re-checked `edit`) may move a label to `human_reviewed`.", "",
         f"Rubric: {RUBRIC}.", "",
         "| Priority | Meaning |", "|---|---|",
         "| 1 | Decisions behind many labels: zero units under production categories; inherited probe references |",
         "| 2 | New false-premise and wrong-explanation labels (highest authoring risk) |",
         "| 3 | Splitting boundaries (two errors, several edits of one rule, fragmentation) |",
         "| 4 | Base labels flagged by the audit as possibly under-split |",
         "| 5 | Explanations that add rules the learner did not raise |", ""]
    for n, it in enumerate(items, 1):
        L += [f"## {n}. P{it['priority']} · `{it['id']}` ({it['source']})", "", f"**Question:** {it['question']}", "",
              f"- input: {it['input']}", f"- context: {it['context'] or '—'}",
              f"- category / resolution: `{it['category']}` / `{it['resolution']}`", f"- explanation: {it['explanation']}"]
        if it["expected"]:
            for u in it["expected"]:
                L += [f"- expected unit ({u['kind']}) **{u['canonical']}**: {u['statement']}", f"  - zh: {u['statement_zh']}",
                      f"  - example: {u['example'] or '—'}"]
        else:
            L.append("- expected: **zero units**")
        L += [f"- rationale: {it['rationale'] or '—'}", "- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____", ""]
    return "\n".join(L)


def jsonl(items):
    return "".join(json.dumps(i, ensure_ascii=False, sort_keys=True) + "\n" for i in items)
