"""Quality gates for the FLH workbooks (structure and consistency; meaning is
for human and machine review)."""

import re
from collections import Counter

CJK = re.compile(r"[一-鿿]")
QID = re.compile(r"^u\d\d-[rlwsgv]\d\d$")


def _text_by_ref(section):
    items = section.get("segments") or section.get("turns") or []
    return {x["id"]: x["text"] for x in items}


def check_question(q, texts, errs):
    if not QID.match(q["id"]):
        errs.append(f"{q['id']}: malformed id")
    for f in ("stem", "explanation_en", "explanation_zh"):
        if not str(q.get(f, "")).strip():
            errs.append(f"{q['id']}: empty {f}")
    if not CJK.search(q.get("explanation_zh", "")):
        errs.append(f"{q['id']}: explanation_zh has no Chinese")
    if not q["evidence"]:
        errs.append(f"{q['id']}: no evidence")
    for ev in q["evidence"]:
        t = texts.get(ev["ref"])
        if t is None:
            errs.append(f"{q['id']}: evidence ref {ev['ref']} does not exist")
        elif t.count(ev["excerpt"]) != 1:
            errs.append(f"{q['id']}: excerpt occurs {t.count(ev['excerpt'])} times in {ev['ref']}: {ev['excerpt'][:50]}")
    if q["type"] == "single_choice":
        opts = [q["correct"]] + [d["text"] for d in q["distractors"]]
        if len(set(o.strip().lower() for o in opts)) != len(opts):
            errs.append(f"{q['id']}: duplicate options")
        for d in q["distractors"]:
            if not d["why_en"].strip() or not CJK.search(d["why_zh"]):
                errs.append(f"{q['id']}: distractor without bilingual reason")
    elif q["type"] == "short_answer":
        if not q["accepted"] or not all(a.strip() for a in q["accepted"]):
            errs.append(f"{q['id']}: no accepted answer")
    else:
        errs.append(f"{q['id']}: unknown type")


def check_rl(units, expected_units=12, per_section=10):
    errs, notes = [], []
    if len(units) != expected_units:
        errs.append(f"{len(units)} units, expected {expected_units}")
    ids, stems = Counter(), Counter()
    longest = shortest = n_sc = 0
    for u in units:
        for f in ("fr", "en", "zh"):
            if not u["goal"].get(f, "").strip():
                errs.append(f"{u['id']}: goal.{f} empty")
        for sec in ("reading", "listening"):
            s = u[sec]
            texts = _text_by_ref(s)
            if len(s["questions"]) != per_section:
                errs.append(f"{u['id']} {sec}: {len(s['questions'])} questions")
            for q in s["questions"]:
                ids[q["id"]] += 1
                stems[q["stem"].strip().lower()] += 1
                check_question(q, texts, errs)
                if q["type"] == "single_choice":
                    n_sc += 1
                    lens = [len(q["correct"])] + [len(d["text"]) for d in q["distractors"]]
                    longest += lens[0] > max(lens[1:])
                    shortest += lens[0] < min(lens[1:])
        all_text = " ".join([u["reading"]["title"], u["listening"]["title"]] + list(_text_by_ref(u["reading"]).values())
                            + list(_text_by_ref(u["listening"]).values())).lower()
        for v in u["vocabulary"]:
            words = [w for w in re.findall(r"[\w'-]+", v["fr"].lower().replace("(e)", "")) if len(w) > 3]
            if words and max(words, key=len)[:5] not in all_text:
                notes.append(f"{u['id']}: vocabulary « {v['fr']} » not found verbatim in the texts")
            if not CJK.search(v["zh"]):
                errs.append(f"{u['id']}: vocabulary {v['fr']} without Chinese")
        for it in u["follow_up"]["items"]:
            if not it.get("answer"):
                errs.append(f"{u['id']}: follow-up item without answer")
    errs += [f"duplicate id {i}" for i, c in ids.items() if c > 1]
    notes += [f"repeated stem: {s}" for s, c in stems.items() if c > 1]
    stats = {"units": len(units), "questions": sum(ids.values()), "single_choice": n_sc,
             "short_answer": sum(ids.values()) - n_sc,
             "correct_option_strictly_longest": longest, "correct_option_strictly_shortest": shortest}
    if n_sc and longest / n_sc > 0.4:
        errs.append(f"correct option is the longest in {longest}/{n_sc} single-choice questions (length clue)")
    return errs, notes, stats


# ---- productive workbook ----

WORDS = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*")
PHONE = re.compile(r"\b0\d(?: \d\d){4}\b")
FICTION_PHONE = ("01 99 00", "02 61 91", "03 53 01", "04 65 71", "05 36 49", "06 39 98")


def count_words(text):
    """Python twin of domain.CountWritingWords."""
    return len(WORDS.findall(text))


def apply_corrections(draft, corrections):
    out = draft
    for c in corrections:
        out = out.replace(c["quote"], c["correction"], 1)
    return out


def _covers(uid, label, sample, n_req, errs):
    got = sorted(c["requirement"] for c in sample["covers"])
    if got != list(range(1, n_req + 1)):
        errs.append(f"{uid} {label}: sample covers requirements {got}, expected 1..{n_req}")
    for c in sample["covers"] + sample["notes"]:
        if sample["text"].count(c["excerpt"]) != 1:
            errs.append(f"{uid} {label}: excerpt occurs {sample['text'].count(c['excerpt'])} times: {c['excerpt'][:50]}")
    for n in sample["notes"]:
        if not CJK.search(n["zh"]):
            errs.append(f"{uid} {label}: note without Chinese")


def check_pw(units, expected_units=12):
    errs, notes = [], []
    if len(units) != expected_units:
        errs.append(f"{len(units)} units, expected {expected_units}")
    seen = Counter()
    for u in units:
        uid = u["id"]
        for f in ("fr", "en", "zh"):
            if not u["goal"].get(f, "").strip():
                errs.append(f"{uid}: goal.{f} empty")
        w = u["writing"]
        if len(w["title"]) > 200 or not w["title"].strip():
            errs.append(f"{uid}: writing title length")
        if not w["prompt"].strip() or len(w["prompt"]) > 1500:
            errs.append(f"{uid}: writing prompt length")
        if not 1 <= len(w["requirements"]) <= 8 or any(not r.strip() or len(r) > 200 for r in w["requirements"]):
            errs.append(f"{uid}: writing requirements")
        if not 1 <= w["word_min"] <= w["word_max"] <= 400:
            errs.append(f"{uid}: writing word range")
        n = count_words(u["writing_sample"]["text"])
        if not w["word_min"] <= n <= w["word_max"]:
            errs.append(f"{uid}: writing sample has {n} words, outside {w['word_min']}–{w['word_max']}")
        _covers(uid, "writing", u["writing_sample"], len(w["requirements"]), errs)
        s = u["speaking"]
        if not 1 <= len(s["requirements"]) <= 6 or any(not r.strip() or len(r) > 200 for r in s["requirements"]):
            errs.append(f"{uid}: speaking requirements")
        if not 1 <= s["seconds_min"] <= s["seconds_max"] <= 120:
            errs.append(f"{uid}: speaking seconds")
        if len(s["situation"]) > 1500 or len(u["speaking_sample"]["text"]) > 2000:
            errs.append(f"{uid}: speaking text length")
        _covers(uid, "speaking", u["speaking_sample"], len(s["requirements"]), errs)
        if len(u["practice"]) != 6:
            errs.append(f"{uid}: {len(u['practice'])} practice items")
        for g in u["practice"]:
            seen[g["id"]] += 1
            if not QID.match(g["id"]) or not g["id"].startswith(uid + "-g"):
                errs.append(f"{g['id']}: malformed id")
            if not g["answer"].strip() or not CJK.search(g["explanation_zh"]) or not g["explanation_en"].strip():
                errs.append(f"{g['id']}: answer or explanation missing")
        if len(u["mistakes"]) != 3:
            errs.append(f"{uid}: {len(u['mistakes'])} mistakes")
        for m in u["mistakes"]:
            if m["wrong"] == m["right"] or not CJK.search(m["why_zh"]):
                errs.append(f"{uid}: mistake entry incomplete: {m['wrong']}")
        r = u["retry"]
        if not 2 <= len(r["corrections"]) <= 8:
            errs.append(f"{uid}: retry has {len(r['corrections'])} corrections")
        spans = []
        for c in r["corrections"]:
            k = r["draft"].count(c["quote"])
            if k != 1:
                errs.append(f"{uid} retry: quote occurs {k} times: {c['quote']}")
            else:
                i = r["draft"].index(c["quote"])
                spans.append((i, i + len(c["quote"])))
            if not CJK.search(c["why_zh"]):
                errs.append(f"{uid} retry: reason without Chinese")
        spans.sort()
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            errs.append(f"{uid} retry: overlapping quotes")
        if r["draft"] in (u["writing_sample"]["text"], u["speaking_sample"]["text"]):
            errs.append(f"{uid} retry: draft equals a sample")
        alltext = " ".join([w["prompt"], s["situation"], u["writing_sample"]["text"], u["speaking_sample"]["text"], r["draft"]])
        for ph in PHONE.findall(alltext):
            if not ph.startswith(FICTION_PHONE):
                errs.append(f"{uid}: phone number {ph} is not in a range reserved for fiction")
    errs += [f"duplicate id {i}" for i, c in seen.items() if c > 1]
    stats = {"units": len(units), "practice_items": sum(seen.values()),
             "mistakes": sum(len(u["mistakes"]) for u in units),
             "retry_corrections": sum(len(u["retry"]["corrections"]) for u in units),
             "writing_sample_words": {u["id"]: count_words(u["writing_sample"]["text"]) for u in units}}
    return errs, notes, stats
