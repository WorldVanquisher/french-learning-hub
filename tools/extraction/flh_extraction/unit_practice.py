"""From learning units to practice prompts (PROTOTYPE, offline, deterministic, standard library only).

  python3 -B -m flh_extraction.unit_practice build --units UNITS.json [--sheet SHEET.json] --out PRACTICE.json
  python3 -B -m flh_extraction.unit_practice grade --practice PRACTICE.json --prompt ID --answer TEXT

``flh_unit_practice_v1`` turns approved claim units into prompts, each labelled with the recall it intends (EXT-133):

| kind | intended recall | built from |
|---|---|---|
| ``free_recall`` | cued recall: the claim with its answer blanked | the units export (``units.recall_items``) |
| ``recognition`` | recognition among the source's answers | the same |
| ``application`` | transfer: apply the rule to a new case | an authored exercise sheet (EXT-131): the rule comes from the unit's span, the instance is new |
| ``explanation`` | elaboration: explain in one's own words | a fixed template on the claim's topic (EXT-132); graded as a self-check |

* **Answer basis** (EXT-134). Every accepted answer states its basis:
  - ``verbatim``: in the span, with its evidence ID;
  - ``numeral``: a number word of the span written in digits;
  - ``rule_application``: the rule is in the span and the instance is the exercise's own.

  An answer with no basis is refused.
* **Spans that support several answers** (EXT-135). Such a span is listed with all its answers. The free-recall
  prompt pins which one it asks for; a recognition item whose options all come from that span is flagged.
* **Grading** (EXT-136). Case, punctuation, a number word against its digits, and a trailing unit word ("four",
  "4", "4 semitones") all match. Another option is ``incorrect``. Anything else is a ``self_check``, never wrong
  by default.
* **Feedback** (EXT-137). Feedback quotes the unit's own words and evidence (field, offsets). It never writes a
  new explanation or claim.
* **Drops** (EXT-138). ``drops`` lists every unit that yields no prompt, and why.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from . import practice as pr
from . import units as un

SCHEMA = "flh_unit_practice_v1"
SHEET = "flh_unit_exercise_sheet_v1"
INTENT = {"free_recall": "cued recall", "recognition": "recognition", "application": "transfer (apply the rule to a new case)",
          "explanation": "elaboration (free recall in your own words)"}
NUMBERS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}
TOPIC = un.TOPIC


def _canon_answer(s: str) -> str:
    t = un._norm(s)
    words = [NUMBERS.get(w, w) for w in t.split()]
    return " ".join(words)


def basis(answer: str, unit: dict, kind: str) -> dict | None:
    for e in unit["evidence"]:
        if e.get("verified") and un._contains(e["quote"], answer):
            return {"basis": "verbatim", "evidence_id": e["evidence_id"]}
    for e in unit["evidence"]:
        if e.get("verified") and re.fullmatch(r"\d+", answer.strip()) and _canon_answer(answer) in _canon_answer(e["quote"]).split():
            return {"basis": "numeral", "evidence_id": e["evidence_id"]}
    if kind == "application":
        for e in unit["evidence"]:
            if e.get("verified"):
                return {"basis": "rule_application", "evidence_id": e["evidence_id"]}
    return None


def multi_answer_spans(units_doc: dict) -> list[dict]:
    by = {}
    for r in units_doc["recall"]:
        if r["kind"] != "free_recall":
            continue
        k = r["source_link"].get("evidence_key") or r["supported_by"]
        by.setdefault(k, set()).add((r["answer"], r["recall_id"]))
    return [{"evidence_key": k, "answers": sorted({a for a, _ in v}), "recall_ids": sorted({i for _, i in v}),
             "note": "this span supports several answers; each free-recall prompt pins its own; recognition options from this span alone are ambiguous"}
            for k, v in sorted(by.items()) if len({a for a, _ in v}) > 1]


def build(units_doc: dict, sheet: dict | None = None) -> dict:
    units = {u["unit_id"]: u for u in units_doc["units"]}
    by_key = {u["claim_key"]: u for u in units_doc["units"] if u["state"] in un.USABLE}
    prompts, refused = [], []
    multi = multi_answer_spans(units_doc)
    multi_keys = {m["evidence_key"] for m in multi}
    for r in units_doc["recall"]:
        u = units[r["unit_id"]]
        acc = []
        for a in r["accepted"]:
            b = basis(a, u, r["kind"])
            if b:
                acc.append({"answer": a, **b})
            else:
                acc.append({"answer": a, "basis": "equivalent wording", "evidence_id": r["supported_by"],
                            "note": "a rewording of an answer that is in the span; graded as correct"})
        row = {"prompt_id": r["recall_id"], "kind": r["kind"], "intended_recall": INTENT[r["kind"]], "unit_id": u["unit_id"],
               "claim_key": u["claim_key"], "prompt": r["prompt"], "answer": r["answer"], "accepted": acc, "source_link": r["source_link"]}
        if r.get("options"):
            row["options"] = r["options"]
            if (r["source_link"].get("evidence_key") or r["supported_by"]) in multi_keys:
                row["warning"] = "the options all come from one span that supports several answers"
        prompts.append(row)
    for ex in (sheet or {}).get("exercises", []):
        u = by_key.get(ex["claim_key"])
        if u is None:
            refused.append({"exercise_id": ex.get("exercise_id"), "code": "unit_not_usable", "detail": "no approved unit with this claim key"})
            continue
        b = basis(ex["answer"], u, "application")
        if b is None or any(un._contains(ex["prompt"], a) for a in [ex["answer"], *ex.get("accepted", [])]):
            refused.append({"exercise_id": ex["exercise_id"], "code": "no_basis_or_leak", "detail": "the answer has no basis in the unit, or the prompt shows it"})
            continue
        prompts.append({"prompt_id": "ap-" + pr.sha(f"{u['unit_id']}\x1f{ex['prompt']}")[:12], "kind": "application", "intended_recall": INTENT["application"],
                        "unit_id": u["unit_id"], "claim_key": u["claim_key"], "prompt": ex["prompt"], "answer": ex["answer"],
                        "accepted": [{"answer": a, **(basis(a, u, "application") or {"basis": "rule_application", "evidence_id": b["evidence_id"]})}
                                     for a in [ex["answer"], *ex.get("accepted", [])]],
                        "options": ex.get("options"), "rule_evidence": b["evidence_id"], "instance": "new: not in the source, written in the exercise sheet"})
    for u in sorted(by_key.values(), key=lambda x: x["unit_id"]):
        if u["type"] != "claim":
            continue
        m = TOPIC.match(u.get("canonical") or "")
        topic = m.group("topic") if m else None
        if not topic:
            continue
        prompts.append({"prompt_id": "ex-" + pr.sha(f"{u['unit_id']}\x1fexplain")[:12], "kind": "explanation", "intended_recall": INTENT["explanation"],
                        "unit_id": u["unit_id"], "claim_key": u["claim_key"],
                        "prompt": f"In your own words, explain what a {topic} is, and give one example that is not in your notes.",
                        "grading": "self_check", "reference": u["text"],
                        "evidence": [{k: e[k] for k in ("evidence_id", "field", "start", "end", "quote")} for e in u["evidence"] if e.get("verified")]})
    for p in prompts:
        p.setdefault("options", None)
        if p["options"] is None:
            del p["options"]
    prompts.sort(key=lambda p: (p["unit_id"], ["free_recall", "recognition", "application", "explanation"].index(p["kind"]), p["prompt_id"]))
    return {"schema": SCHEMA, "source": {k: units_doc["source"][k] for k in ("source_id", "revision", "fingerprint", "subject", "language")},
            "prompts": prompts, "refused": refused, "multi_answer_spans": multi, "drops": drops(units_doc, prompts),
            "counts": {k: sum(1 for p in prompts if p["kind"] == k) for k in INTENT}}


def drops(units_doc: dict, prompts: list[dict]) -> list[dict]:
    """Every unit that yields no prompt, with the reason (EXT-138)."""
    have = {p["unit_id"] for p in prompts}
    refused = {}
    for r in units_doc["recall_refused"]:
        refused.setdefault(r["unit_id"], []).append(r["code"])
    out = []
    for u in sorted(units_doc["units"], key=lambda x: x["unit_id"]):
        if u["unit_id"] in have:
            continue
        if u["state"] not in un.USABLE:
            why = f"not usable ({u['state']}): " + ", ".join(r["code"] for r in u["review_reasons"])
        elif u["type"] != "claim":
            why = f"a {u['type']}: practised through the practice builder (explain, choose, produce), not as a recall prompt"
        elif u["unit_id"] in refused:
            why = "recall refused: " + ", ".join(refused[u["unit_id"]])
        else:
            why = "no recall answer and no TOPIC = VALUE canonical: nothing to ask without inventing"
        out.append({"unit_id": u["unit_id"], "type": u["type"], "text": u["text"], "why": why})
    return out


def grade(prompt: dict, text: str) -> dict:
    """Outcome of one answer, with feedback that quotes the source only."""
    fb = {"reference": None, "evidence": None}
    if prompt["kind"] == "explanation":
        return {"outcome": "self_check", "why": "an explanation in your own words is compared by you with the reference",
                "reference": prompt["reference"], "evidence": prompt["evidence"]}
    t = _canon_answer(text)
    accepted = [a["answer"] for a in prompt["accepted"]]
    unit_words = {"semitone", "semitones", "degrees", "degree", "celsius", "bits", "bit"}
    strip = lambda s: " ".join(w for w in s.split() if w not in unit_words)  # noqa: E731
    sl = prompt["source_link"] if "source_link" in prompt else None
    fb["evidence"] = sl
    fb["reference"] = prompt.get("prompt", "").replace("___", prompt["answer"]) if prompt["kind"] in ("free_recall", "recognition") else None
    if any(t == _canon_answer(a) or strip(t) == strip(_canon_answer(a)) for a in accepted):
        return {"outcome": "correct", **fb}
    for o in prompt.get("options") or []:
        if t == _canon_answer(o) and _canon_answer(o) not in {_canon_answer(a) for a in accepted}:
            return {"outcome": "incorrect", "chosen": o, **fb, "note": "the reference is your own source's words; nothing new is claimed"}
    return {"outcome": "self_check", "why": "not one of the accepted answers; it may still be right: compare it with the reference", **fb}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="flh_extraction.unit_practice")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("build"); q.add_argument("--units", required=True); q.add_argument("--sheet"); q.add_argument("--out", required=True)
    q = sub.add_parser("grade"); q.add_argument("--practice", required=True); q.add_argument("--prompt", required=True); q.add_argument("--answer", required=True)
    a = ap.parse_args(argv)

    def rd(p):
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    try:
        if a.cmd == "build":
            doc = build(rd(a.units), rd(a.sheet) if a.sheet else None)
            un.write_atomic(a.out, pr.dumps(doc))
            print(f"wrote {len(doc['prompts'])} prompts {doc['counts']}; drops {len(doc['drops'])}; refused {len(doc['refused'])}")
        else:
            doc = rd(a.practice)
            p = next(x for x in doc["prompts"] if x["prompt_id"] == a.prompt)
            print(json.dumps(grade(p, a.answer), ensure_ascii=False))
        return 0
    except (un.UnitError, OSError, ValueError, StopIteration) as e:
        print(f"refused: {e!r}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
