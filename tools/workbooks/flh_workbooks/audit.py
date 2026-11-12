"""Evidence-sufficiency audit of the listening questions (120 in v1).

A listening question is answered from what is heard: the script lines. For
each question this checks, against its own unit's script only:
  * every evidence excerpt occurs exactly once in its cited line;
  * every wrong-option reason (English and Chinese) cites existing script lines;
  * no explanation or reason points at the reading text (p1, p2, ...);
  * no question's stem or options show another question's short answer (all
    options are on screen before reveal, so that would give the answer away);
  * numbers and clock times in the explanation and reasons occur in the script.
    A value found in the unit's reading text but not in the script means the
    question relies on reading context. A value found nowhere is reported as
    restated or computed: the script says it in words (« onze heures et
    demie », 11:30) or it follows from heard values (8:15 from 7:00 plus an
    hour and a quarter). A person checks those rows.

Answer context (answer_context): the answer itself (the correct option, or the
reference answer and every accepted alternative) must not need context the
script does not give. Its anchors are checked against the script: tokens with
a digit (numbers, codes such as A2, ordinals such as 3e), clock times, day and
month names, and capitalised words after the first (names and places). An
anchor is heard when the script says it (accents and case folded), says the
same number in words or with grouped digits (« quatre jours », « troisième »,
« 48 213 »), or says the same time. An anchor found only in the unit's reading
text, or nowhere, is an error, unless REVIEWED_ANSWER_CONTEXT records a
person's judgement for that question and anchor.

Basis per question: "script" (supported by the script alone), "script, restated
or computed value" (see above), "reading"
(relies on the reading text) or "error" (evidence or reasons are broken).
`check` fails on "reading", "error" and any answer-context error. What still
needs a person (paraphrased content words, an inference from general
knowledge with no anchor, whether a restated value is the one meant) is listed
in content/workbooks/review/listening-evidence-audit-v1.md; this module does
not claim to detect it.
"""

import json
import re
import unicodedata

from . import scan, studypack

PREF = re.compile(r"(?<![A-Za-z0-9])p\d+")

# Answer anchors a person reviewed: (question, anchor) -> the judgement. Keep
# this short; every entry is a place where the script alone is not enough.
REVIEWED_ANSWER_CONTEXT = {
    ("u04-l04", "Irlande"): "general knowledge: the script says « six mois à Dublin » (s6); Dublin is in Ireland "
                            "(reviewed 2026-11-11, listening-evidence-audit-v1.md)",
}

CALENDAR = {"lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche", "janvier", "fevrier", "mars", "avril",
            "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre", "decembre"}
TOKEN = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿŒœ]+(?:['’-][0-9A-Za-zÀ-ÖØ-öø-ÿŒœ]+)*")
UNITS = {"zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9,
         "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20, "trente": 30,
         "quarante": 40, "cinquante": 50, "soixante": 60, "cent": 100, "cents": 100, "mille": 1000}
ORDINALS = {"premier": 1, "premiere": 1, "second": 2, "seconde": 2}


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn").replace("’", "'")


def _word_number(words):
    """The value of a run of French number words (« quatre-vingt-dix », « deux cents »), or None."""
    total, current = 0, 0
    for w in words:
        if w == "et":
            continue
        if w not in UNITS:
            return None
        v = UNITS[w]
        if v == 1000:
            total, current = total + max(current, 1) * 1000, 0
        elif v == 100:
            current = max(current, 1) * 100
        elif w == "vingt" and current % 100 == 4:  # quatre-vingt(s)
            current = current - 4 + 80
        else:
            current += v
    return total + current


def heard_numbers(text):
    """Every number the text says: digits (with grouped thousands joined),
    number words and ordinals (« troisième » is 3)."""
    t = fold(text)
    out = {int(m.replace(" ", "").replace("\u202f", "")) for m in re.findall(r"\d{1,3}(?:[ \u202f]\d{3})+|\d+", t)}
    # Words, with every other mark (punctuation, digits) kept as a run breaker.
    words = re.findall(r"[a-z]+|[^a-z\s]", t.replace("-", " "))
    run = []
    for w in words + ["."]:
        base = w[:-4] if w.endswith("ieme") and len(w) > 5 else None
        if base is not None:  # an ordinal: troisième, vingtième, cinquième (cinqu-), neuvième (neuv-)
            base = {"cinqu": "cinq", "neuv": "neuf", "quatr": "quatre", "onz": "onze", "douz": "douze", "treiz": "treize",
                    "quatorz": "quatorze", "quinz": "quinze", "seiz": "seize", "trent": "trente", "quarant": "quarante",
                    "cinquant": "cinquante", "soixant": "soixante", "mill": "mille", "centi": "cent", "deux": "deux"}.get(base, base)
        if w in ORDINALS:
            out.add(ORDINALS[w])
        if w in UNITS or w == "et" and run:
            run.append(w)
            continue
        if base in UNITS:
            n = _word_number(run + [base])
            if n is not None:
                out.add(n)
            run = []
            continue
        if run:
            n = _word_number(run)
            if n is not None:
                out.add(n)
            run = []
    return out


def answer_anchors(text):
    """The anchors of one answer: (anchor, kind) with kind number, time, calendar or name."""
    out = [(f"{h} h {m}", "time") for h, m in studypack.TIME.findall(text)]
    rest = studypack.TIME.sub(" ", text)
    for i, tok in enumerate(TOKEN.findall(rest)):
        if any(c.isdigit() for c in tok):
            out.append((tok, "number"))
        elif fold(tok) in CALENDAR:
            out.append((tok, "calendar"))
        elif i > 0 and tok[0].isupper():
            out.append((tok, "name"))
    return out


def _says(text, anchor, kind):
    """Whether the text says the anchor (see answer_anchors)."""
    if kind == "time":
        return anchor in studypack._times(text)
    if re.search(r"(?<![0-9a-z])" + re.escape(fold(anchor)) + r"(?![0-9a-z])", fold(text)):
        return True
    if kind == "number":
        digits = re.findall(r"\d+", anchor)
        letters = re.sub(r"[0-9]", "", fold(anchor))
        if len(digits) == 1 and letters in ("", "e", "er", "re", "eme", "h"):
            return int(digits[0]) in heard_numbers(text)
    return False


def answer_context(doc):
    """(rows, errors): every answer anchor and where the listener hears it."""
    rows, errors = [], []
    for u in doc["units"]:
        L = u["listening"]
        lines = {t["id"]: t["text"] for t in L["turns"]}
        script = " ".join(lines.values())
        reading = " ".join(s["text"] for s in u["reading"]["segments"])
        for q in L["questions"]:
            answers = ([o["text"] for o in q["options"] if o["correct"]] if q["type"] == "single_choice"
                       else [q["reference_answer"]] + q.get("accepted_alternatives", []))
            cited = " ".join(lines.get(e["ref"], "") for e in q["evidence"])
            for a in answers:
                for anchor, kind in answer_anchors(a):
                    reviewed = REVIEWED_ANSWER_CONTEXT.get((q["id"], anchor))
                    if _says(cited, anchor, kind):
                        where = "cited line"
                    elif _says(script, anchor, kind):
                        where = "another line"
                    elif reviewed:
                        where = "reviewed"
                    elif _says(reading, anchor, kind):
                        where = "reading"
                        errors.append(f"{q['id']}: the answer « {a} » needs « {anchor} », which only the reading text gives")
                    else:
                        where = "nowhere"
                        errors.append(f"{q['id']}: the answer « {a} » needs « {anchor} » ({kind}), which the script never says")
                    rows.append({"unit": u["id"], "id": q["id"], "answer": a, "anchor": anchor, "kind": kind, "heard": where,
                                 "note": reviewed or ""})
    used = {(r["id"], r["anchor"]) for r in rows if r["heard"] == "reviewed"}
    known = {q["id"] for u in doc["units"] for q in u["listening"]["questions"]}
    errors += [f"REVIEWED_ANSWER_CONTEXT {qid} « {anchor} » is no longer needed; remove it"
               for qid, anchor in sorted(REVIEWED_ANSWER_CONTEXT) if qid in known and (qid, anchor) not in used]
    return rows, errors


def clues(questions):
    """(question, answer, other question, where) when the visible stem or options
    of one question contain another question's short answer (3+ characters)."""
    out = []
    for q in questions:
        if q["type"] != "short_answer":
            continue
        for a in [q["reference_answer"]] + q["accepted_alternatives"]:
            if len(a) < 3:
                continue
            for o in questions:
                shown = [("stem", o["stem"])] + [(f"option {x['key']}", x["text"]) for x in o.get("options", [])]
                out += [(q["id"], a, o["id"], where) for where, text in shown
                        if o is not q and scan.norm(a).lower() in scan.norm(text).lower()]
    return out


def listening_audit(doc):
    rows, errors = [], []
    anchors, anchor_errors = answer_context(doc)
    errors += anchor_errors
    by_question = {}
    for a in anchors:
        by_question.setdefault(a["id"], []).append(a)
    for u in doc["units"]:
        L = u["listening"]
        errors += [f"{qid}: « {a} » is shown in {oid} {where}, before reveal" for qid, a, oid, where in clues(L["questions"])]
        lines = {t["id"]: t["text"] for t in L["turns"]}
        reading = {s["id"]: s["text"] for s in u["reading"]["segments"]}
        errs, _, checked = studypack._check_block(u["id"], "s", lines, L["questions"], reading)
        errors += errs
        for q, r in zip(L["questions"], checked):
            texts = [q["explanation_en"], q["explanation_zh"]] + [o[f"why_wrong_{lang}"] for o in q.get("options", [])
                                                                   if not o["correct"] for lang in ("en", "zh")]
            prefs = sorted({m for t in texts for m in PREF.findall(t)})
            bad = any(n != 1 for *_, n in r["evidence"]) or not all(ok for *_, ok in r["reasons"])
            in_reading = [f for f in r["facts"] if f["found_in"]]
            heard = {a["heard"] for a in by_question.get(q["id"], [])}
            basis = ("error" if bad else "reading" if in_reading or prefs or "reading" in heard
                     else "absent context" if "nowhere" in heard
                     else "script, restated or computed value" if r["facts"] else "script")
            if basis == "reading":
                errors.append(f"{q['id']}: relies on the reading text "
                              + "; ".join([f"« {f['fact']} » ({f['field']}) only in {', '.join(f['found_in'])}" for f in in_reading]
                                          + [f"cites {p}" for p in prefs]))
            rows.append({"unit": u["id"], "id": q["id"], "kind": q["kind"], "type": q["type"],
                         "evidence": [f"{ref} ×{n}" for ref, _, n in r["evidence"]],
                         "reasons_cite_lines": None if not r["reasons"] else all(ok for *_, ok in r["reasons"]),
                         "restated_or_computed": sorted({f["fact"] for f in r["facts"] if not f["found_in"]}),
                         "reading": sorted({f["fact"] for f in in_reading}) + prefs, "basis": basis,
                         "answer_context": [f"{a['anchor']} ({a['heard']})" for a in by_question.get(q["id"], [])
                                            if a["heard"] != "cited line"]})
    return rows, errors


def report_md(rows, errors):
    counts = {}
    for r in rows:
        counts[r["basis"]] = counts.get(r["basis"], 0) + 1
    out = ["# Listening questions: evidence audit", "",
           "Generated by `python3 -m flh_workbooks audit` from content/workbooks/reading_listening_v1.json.",
           "Each question is checked against its own unit's script only (what the listener hears).",
           "Hand-made judgements are in content/workbooks/review/listening-evidence-audit-v1.md.", "",
           f"Questions: {len(rows)}. " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())), "",
           "Answer context: anchors of the answer (numbers, times, days and months, names) that the cited lines do not",
           "say literally: heard in another line, said in words, reviewed by a person, or (an error) only in the reading text or nowhere.", "",
           "| Question | Kind | Evidence (line ×occurrences) | Reasons cite lines | Restated or computed values | Reading | Answer context | Basis |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        rc = "n/a" if r["reasons_cite_lines"] is None else ("yes" if r["reasons_cite_lines"] else "NO")
        out.append(f"| {r['id']} | {r['kind']} | {'; '.join(r['evidence'])} | {rc} | {', '.join(r['restated_or_computed']) or '—'} | "
                   f"{', '.join(r['reading']) or '—'} | {', '.join(r.get('answer_context', [])) or '—'} | {r['basis']} |")
    out += ["", f"Errors: {len(errors)}"] + [f"- {e}" for e in errors]
    return "\n".join(out) + "\n"


def dumps(rows):
    return json.dumps(rows, ensure_ascii=False, indent=1) + "\n"
