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


# ---- v3 expansion (2026-11-12): one prioritized sample per error family ----

LABELS = {
    "OK": ("The decision and every unit pass the rubric.",
           "« Je suis allé au marché » asked about « aller » + être → one unit « aller — passé composé avec être »."),
    "OVER_SPLIT": ("One objective is spread over several units.",
                   "« Comment conjuguer vouloir au présent ? » → units « vouloir — je veux » and « vouloir — nous voulons »; "
                   "one unit « vouloir — présent » is right (rule 2)."),
    "UNDER_SPLIT": ("Two objectives share one unit, or one is missing.",
                    "« Elle est une acteuse » → « C'est une actrice » corrects « c'est / elle est » and the « -trice » "
                    "feminine; a single « -eur → -trice » unit misses the first."),
    "FALSE_PREMISE": ("A statement repeats the learner's or the explanation's false claim as true.",
                      "« depuis prend le passé composé : j'ai habité ici depuis 2019 » → a unit saying « depuis » takes the "
                      "passé composé adopts the premise; the right unit is « depuis » + présent."),
    "BILINGUAL_DRIFT": ("`statement_zh` says something different from `statement` (scope, claim or quoted forms).",
                        "EN « Grâce à » introduces a positive cause » vs ZH « grâce à » 表示原因 drops « positive »."),
    "UNSUPPORTED": ("A unit's objective was not raised by the interaction (often only the explanation names it).",
                    "A thank-you message whose explanation mentions « lui / leur » → a unit on indirect pronouns is unsupported."),
    "CUE_DEPENDENT": ("The reference would change with the category or explanation although the learner's text is the same.",
                      "« Est-ce qu'on peut décaler notre séance ? » is zero units under `other` and under `grammar`; "
                      "a label that extracts a rule only under `grammar` is cue-dependent."),
}

RUBRIC_V3 = [
    "1. Decision: is units vs zero, and the number of units, right for the learner's text alone? (yes / no)",
    "2. Label: pick ONE of OK, OVER_SPLIT, UNDER_SPLIT, FALSE_PREMISE, BILINGUAL_DRIFT, UNSUPPORTED, CUE_DEPENDENT "
    "(the worst that applies; one example per label below).",
    "3. Verdict: accept / edit (write the fix) / reject / quarantine (reasonable people disagree), reviewer and date.",
]


def _units_sim(r):
    from .evaluate import similarity
    us = r["expected"]["units"]
    return max((similarity(us[i], us[j]) for i in range(len(us)) for j in range(i + 1, len(us))), default=0.0)


def _premise_overlap(r):
    from .textnorm import norm
    lt = set(norm(audit.learner_text(r)).split())
    st = set(norm(" ".join(u["statement"] for u in r["expected"]["units"])).split())
    return len(lt & st) / len(lt | st) if lt | st else 0.0


def _zh_risk(u):
    """A drift risk score for a unit that the heuristic does not flag: the
    length ratio's distance from 1 and EN quoted forms absent from the ZH text."""
    import math
    from .textnorm import norm
    zh = norm(u["statement_zh"])
    missing = sum(1 for f in audit.quoted_forms(u["statement"]) if f not in zh)
    return missing + abs(math.log(max(1, len(u["statement_zh"])) / max(1, len(u["statement"]))))


def _x(priority, family, r, source, question, extra=None):
    it = _item(priority, r, source, question)
    it.update(packet="v3-expansion", family=family, decision_ok=None, label=None)
    if extra:
        it.update(extra)
    return it


def build_v3(base, inc, chl, exclude=()):
    """About 18 items in five priorities; ids in `exclude` (the v2 packet) are skipped."""
    from .textnorm import norm
    seen, items = set(exclude), []
    train = sorted(list(base) + list(inc), key=lambda r: r["id"])
    # P1: the challenge slice (its references gate the paired comparison).
    gs = {}
    for r in chl:
        gs.setdefault(r["meta"]["challenge"]["group_id"], {})[r["meta"]["challenge"]["variant"]] = r
    picked = {"extract": 0, "abstain": 0}
    for gid in sorted(gs, key=lambda g: (len(gs[g]["aligned"]["expected"]["units"]) < 2, g)):
        v = gs[gid]
        intent = v["aligned"]["meta"]["challenge"]["intent"]
        if picked[intent] >= (2 if intent == "extract" else 2) or v["aligned"]["meta"]["split_group"] != "challenge_dev":
            continue
        picked[intent] += 1
        cues = {k: {"category": x["input"]["effective_category"], "resolution": x["input"]["resolution"],
                    "explanation": x["input"]["effective_explanation"]} for k, x in v.items()}
        q = ("Same learner text under three cue sets: is the shared reference right under every one of them?" if intent == "extract"
             else "Zero units under three cue sets, one naming a rule the learner never raised: is zero right under each?")
        items.append(_x(1, "CUE_DEPENDENT", v["conflicting"], "challenge", q, {"group_id": gid, "variants": cues}))
        seen.update(x["id"] for x in v.values())
    # P1: grounding disagreements (the heuristic finds the unit only in the explanation).
    canon = set()
    for r in train:
        if len([i for i in items if i["family"] == "UNSUPPORTED"]) == 3:
            break
        if r["id"] in seen or len(r["expected"]["units"]) != 1:
            continue
        u = r["expected"]["units"][0]
        t = audit.anchor_terms(u)
        if (u["canonical"] not in canon and not audit.is_anchored(norm(audit.learner_text(r)), t)
                and audit.is_anchored(norm(audit.visible_text(r)), t)):
            canon.add(u["canonical"])
            seen.add(r["id"])
            items.append(_x(1, "UNSUPPORTED", r, "train", "The heuristic finds this objective only in the explanation: "
                                                          "did the learner's text raise it?"))
    # P2: false premises most at risk of echoing the premise.
    fp = sorted((r for r in train if r["id"] not in seen and r["expected"]["units"]
                 and r["meta"].get("case_type") in ("misconception", "wrong_explanation")),
                key=lambda r: (-_premise_overlap(r), r["id"]))
    for r in fp[:3]:
        seen.add(r["id"])
        items.append(_x(2, "FALSE_PREMISE", r, "train", "The statement shares many words with the false premise: does it "
                                                     "state the correct rule without repeating the claim?",
                        {"premise_overlap": round(_premise_overlap(r), 3)}))
    # P3: under-splits (most separate edits with fewer units).
    us = []
    for r in train:
        if r["id"] in seen:
            continue
        e = max((audit.edit_regions(a, b) for a, b in audit.correction_pairs(r)), default=0)
        if e >= 2 and e > len(r["expected"]["units"]):
            us.append((-e, r["id"], r))
    pts = set()
    for _, _, r in sorted(us, key=lambda x: x[:2]):
        key = tuple(r["meta"]["points"])
        if key in pts:
            continue
        pts.add(key)
        seen.add(r["id"])
        items.append(_x(3, "UNDER_SPLIT", r, "train", "The correction makes several separate edits but the label has fewer "
                                                   "units: is an objective missing?"))
        if len(pts) == 3:
            break
    # P4: over-splits (the most similar unit pair within one record).
    os_ = sorted(((-_units_sim(r), r["id"], r) for r in train if r["id"] not in seen and len(r["expected"]["units"]) >= 2),
                 key=lambda x: x[:2])
    for _, _, r in os_[:3]:
        seen.add(r["id"])
        items.append(_x(4, "OVER_SPLIT", r, "train", "These units are the most similar pair in one record: one objective or two?",
                        {"unit_similarity": round(_units_sim(r), 3)}))
    # P5: bilingual drift risk among distinct units (the heuristic flags none).
    by_canon = {}
    for r in train:
        for u in r["expected"]["units"]:
            if r["id"] not in seen and len(r["expected"]["units"]) == 1:
                by_canon.setdefault(u["canonical"], (r, u))
    for c, (r, u) in sorted(by_canon.items(), key=lambda kv: (-_zh_risk(kv[1][1]), kv[0]))[:3]:
        seen.add(r["id"])
        items.append(_x(5, "BILINGUAL_DRIFT", r, "train", "Highest drift risk score among distinct units: does the Chinese "
                                                       "statement say exactly what the English one says?",
                        {"zh_risk": round(_zh_risk(u), 3)}))
    return items


def markdown_v3(items):
    L = ["# Extraction review packet v3 (expansion: one sample per error family)", "",
         f"{len(items)} items. Every label is **machine-authored and unreviewed**; review after "
         "REVIEW_PACKET_V2.md. Fill `decision_ok`, `label` and `verdict` in `review-packet-v3.jsonl`.", "",
         "## Rubric", ""] + RUBRIC_V3 + ["", "## Labels, with one illustrative example each", "",
                                          "| Label | Meaning | Example (illustration, not from the data) |", "|---|---|---|"]
    for k, (meaning, ex) in LABELS.items():
        L.append(f"| {k} | {meaning} | {ex} |")
    L += ["", "| Priority | Family | Why first |", "|---|---|---|",
          "| 1 | CUE_DEPENDENT, UNSUPPORTED | the challenge references gate the paired comparison; grounding decides objectives |",
          "| 2 | FALSE_PREMISE | a statement that echoes a false premise teaches an error |",
          "| 3 | UNDER_SPLIT | a missing objective is invisible to unit F1 against the same reference |",
          "| 4 | OVER_SPLIT | fragmentation inflates unit counts |",
          "| 5 | BILINGUAL_DRIFT | the heuristic flags none; these are the riskiest by score |", ""]
    for n, it in enumerate(items, 1):
        L += [f"## {n}. P{it['priority']} · {it['family']} · `{it['id']}` ({it['source']})", "", f"**Question:** {it['question']}", "",
              f"- input: {it['input']}", f"- context: {it['context'] or '—'}"]
        if it.get("variants"):
            for k, v in it["variants"].items():
                L.append(f"- cues `{k}`: `{v['category']}` / `{v['resolution']}` — {v['explanation']}")
        else:
            L += [f"- category / resolution: `{it['category']}` / `{it['resolution']}`", f"- explanation: {it['explanation']}"]
        for u in it["expected"]:
            L += [f"- expected unit ({u['kind']}) **{u['canonical']}**: {u['statement']}", f"  - zh: {u['statement_zh']}",
                  f"  - example: {u['example'] or '—'}"]
        if not it["expected"]:
            L.append("- expected: **zero units**")
        L += [f"- rationale: {it['rationale'] or '—'}",
              "- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____", ""]
    return "\n".join(L)
