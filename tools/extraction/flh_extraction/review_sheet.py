"""A spreadsheet for the reviewer sample (OFFLINE ONLY): intent, evidence and wording apart.

  python3 -m flh_extraction review-sheet export --packet review/review-sample-v1.jsonl --out SHEET.csv
  python3 -m flh_extraction review-sheet import --packet review/review-sample-v1.jsonl --sheet SHEET.csv --out FILLED.jsonl

One row per reference unit (a zero-unit item has one row with unit 0). Fixed
columns describe the item and its reference and must not be edited; the import
refuses a sheet whose fixed columns differ from the packet. Fill:

  A_ intent (item level, first row of the item)   is « units » vs « zero » right; are the objectives right
  B_ evidence (per unit)                           raised by the learner's text? is the claim true?
  C_ wording (per unit)                            canonical, Chinese, example
  D_ verdict (item level, first row of the item)   accept / edit / reject / quarantine, position on a dispute

Answers are `yes`, `no` or blank. The packet file itself is never changed: the
import writes a filled copy. Labels in the import report and in the filled copy:

  NO VERDICT     no verdict yet (never counted)
  OPEN DISPUTE   a disputed item without accept / edit / reject and a written position (never counted)
  COUNTED        a verdict, every answer the verdict needs, and for a dispute the position taken

A verdict whose answers are missing (intent, or evidence and wording of a unit
for accept / edit) is refused, never imported with a guessed answer.
"""

import csv
import io
import json

from .review_sample import _line, review_label

FIXED = ["item", "item_id", "part", "dispute", "learner_text", "context", "cues", "reference_decision",
         "unit", "kind", "canonical", "statement", "statement_zh", "example"]
ITEM = ["A_intent_decision_ok", "A_intent_objectives_ok", "A_intent_missing_objective", "A_intent_extra_objective",
        "D_verdict", "D_dispute_position", "D_note", "D_reviewer", "D_date"]
UNIT = ["B_evidence_raised_by_learner", "B_evidence_claim_true", "C_wording_canonical_ok", "C_wording_zh_same",
        "C_wording_example_ok", "C_wording_fix"]
HEADER = FIXED + ITEM[:4] + UNIT + ITEM[4:]
YESNO = {"yes": True, "no": False, "": None}
VERDICTS = ("accept", "edit", "reject", "quarantine", "")
OPEN = "OPEN DISPUTE"


def _fixed(item):
    d = item["dispute"]
    cues = " | ".join(f"{c['variant']}: {c['category']}/{c['resolution']} — {_line(c['explanation'])}" for c in item["cues"])
    base = {"item": str(item["n"]), "item_id": item["id"], "part": item["part"],
            "dispute": f"{OPEN} (raised by {', '.join(d['raised_by'])}): " + " || ".join(d["positions"]) if d["status"] == "disputed" else "",
            "learner_text": _line(item["input"]["original_input"]), "context": _line(item["input"]["original_context"]),
            "cues": cues, "reference_decision": item["reference"]["decision"]}
    units = item["reference"]["units"]
    if not units:
        return [dict(base, unit="0", kind="", canonical="(zero units)", statement="", statement_zh="", example="")]
    return [dict(base, unit=str(i), kind=u["kind"], canonical=u["canonical"], statement=u["statement"],
                 statement_zh=u["statement_zh"], example=u["example"] or "") for i, u in enumerate(units, 1)]


def export(packet):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADER, lineterminator="\n")
    w.writeheader()
    for item in packet:
        for row in _fixed(item):
            w.writerow({k: row.get(k, "") for k in HEADER})
    return buf.getvalue()


def _yn(v, where, problems):
    v = (v or "").strip().lower()
    if v not in YESNO:
        problems.append(f"{where}: '{v}' is not yes, no or blank")
        return None
    return YESNO[v]


def label(item):
    return review_label(item)


def load(packet, sheet_text):
    """Returns (filled packet, report). Raises ValueError listing every problem
    when the sheet cannot be imported as it is."""
    rows = list(csv.DictReader(io.StringIO(sheet_text.lstrip("﻿"))))
    problems = []
    if not rows or list(rows[0].keys()) != HEADER:
        raise ValueError("the sheet's columns differ from the review-sheet export (do not add, remove or reorder columns)")
    expect = [r for item in packet for r in _fixed(item)]
    if len(rows) != len(expect):
        problems.append(f"{len(rows)} rows, expected {len(expect)} (do not add or delete rows)")
    for k, (got, want) in enumerate(zip(rows, expect), 2):
        for c in FIXED:
            if (got.get(c) or "") != want[c]:
                problems.append(f"line {k}: fixed column {c} was changed")
                break
    if problems:
        raise ValueError("; ".join(problems))
    filled = json.loads(json.dumps(packet))
    by_item = {}
    for k, r in enumerate(rows, 2):
        by_item.setdefault(r["item_id"], []).append((k, r))
    for item in filled:
        lines = by_item[item["id"]]
        k0, first = lines[0]
        for k, r in lines[1:]:
            if any((r.get(c) or "").strip() for c in ITEM):
                problems.append(f"line {k}: item-level answers (A_, D_) go on the item's first row only")
        rv = item["review"]
        rv["intent"].update(decision_ok=_yn(first["A_intent_decision_ok"], f"line {k0} A_intent_decision_ok", problems),
                            objectives_ok=_yn(first["A_intent_objectives_ok"], f"line {k0} A_intent_objectives_ok", problems),
                            missing_objective=first["A_intent_missing_objective"].strip(),
                            extra_objective=first["A_intent_extra_objective"].strip())
        verdict = first["D_verdict"].strip().lower()
        if verdict not in VERDICTS:
            problems.append(f"line {k0}: D_verdict '{verdict}' is not accept, edit, reject, quarantine or blank")
            verdict = ""
        rv["dispute_position"] = first["D_dispute_position"].strip()
        rv["note"] = first["D_note"].strip()
        evidence = []
        for (k, r), w in zip(lines if item["reference"]["units"] else [], rv["wording"]):
            claim = _yn(r["B_evidence_claim_true"], f"line {k} B_evidence_claim_true", problems)
            evidence.append({"canonical": w["canonical"],
                             "raised_by_learner": _yn(r["B_evidence_raised_by_learner"], f"line {k} B_evidence_raised_by_learner", problems),
                             "claim_true": claim})
            w.update(statement_true=claim, canonical_ok=_yn(r["C_wording_canonical_ok"], f"line {k} C_wording_canonical_ok", problems),
                     statement_zh_same=_yn(r["C_wording_zh_same"], f"line {k} C_wording_zh_same", problems),
                     example_ok=_yn(r["C_wording_example_ok"], f"line {k} C_wording_example_ok", problems),
                     fix=r["C_wording_fix"].strip())
        if not item["reference"]["units"] and any((first.get(c) or "").strip() for c in UNIT):
            problems.append(f"line {k0}: a zero-unit item has no evidence or wording to judge")
        rv["evidence"] = evidence
        item.update(verdict=verdict or None, reviewer=first["D_reviewer"].strip(), date=first["D_date"].strip())
        if item["verdict"]:
            need = [rv["intent"]["decision_ok"], rv["intent"]["objectives_ok"]]
            if item["verdict"] in ("accept", "edit"):
                need += [e[f] for e in evidence for f in ("raised_by_learner", "claim_true")]
                need += [w[f] for w in rv["wording"] for f in ("canonical_ok", "statement_zh_same", "example_ok")]
            if any(v is None for v in need):
                problems.append(f"line {k0}: item {item['id']} has verdict '{item['verdict']}' but unanswered questions "
                                "(a verdict is never imported with a guessed answer)")
            if item["verdict"] == "edit" and not (rv["note"] or any(w["fix"] for w in rv["wording"])):
                problems.append(f"line {k0}: item {item['id']} is 'edit' without a fix or note")
        item["review_label"] = label(item)
    if problems:
        raise ValueError("; ".join(problems))
    labels = {i["id"]: i["review_label"] for i in filled}
    rep = {"schema": "flh_extraction_review_sheet_import_v1", "items": len(filled),
           "labels": {k: sorted(i for i, v in labels.items() if v == k) for k in ("COUNTED", OPEN, "NO VERDICT")},
           "counted": sum(v == "COUNTED" for v in labels.values())}
    return filled, rep
