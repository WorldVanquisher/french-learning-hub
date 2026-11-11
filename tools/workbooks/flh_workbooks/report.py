"""Coverage/inventory report and machine-critique heuristics for the
reading/listening workbook. Heuristics flag items for a reader; they do not
judge correctness."""

import re
import unicodedata
from collections import Counter

from . import model

WORD = re.compile(r"[A-Za-zÀ-ÿœŒæÆ'-]+")
STOP = set("""le la les l un une des de du d à au aux en et ou mais pour par sur dans avec sans ce cet cette ces
il elle ils elles on nous vous je j tu se s sa son ses leur leurs lui y ne n pas plus que qu qui est sont a ont
être avoir fait faire c ça très tout tous toute toutes même aussi si comme""".split())


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if not unicodedata.combining(c))


def toks(s):
    return {fold(w).strip("'-") for w in WORD.findall(s) if fold(w).strip("'-") not in STOP and len(w) > 2}


def words(s):
    return len(WORD.findall(s))


def inventory(doc):
    units, tot = [], Counter()
    for u in doc["units"]:
        row = {"unit": u["id"], "theme": u["theme"], "band": u["band"],
               "reading_words": sum(words(s["text"]) for s in u["reading"]["segments"]),
               "listening_words": sum(words(t["text"]) for t in u["listening"]["turns"]),
               "listening_turns": len(u["listening"]["turns"]), "speakers": len(u["listening"]["speakers"]),
               "vocabulary": len(u["vocabulary"]), "follow_up": u["follow_up"]["type"]}
        for sec in ("reading", "listening"):
            qs = u[sec]["questions"]
            row[f"{sec}_questions"] = len(qs)
            row[f"{sec}_kinds"] = dict(sorted(Counter(q["kind"] for q in qs).items()))
            cited = {e["ref"] for q in qs for e in q["evidence"]}
            refs = [x["id"] for x in (u[sec].get("segments") or u[sec]["turns"])]
            row[f"{sec}_untested_refs"] = [r for r in refs if r not in cited]
            for q in qs:
                tot[(sec, q["type"], q["kind"])] += 1
        units.append(row)
    qs = model.all_questions(doc)
    sc = [q for q in qs if q["type"] == "single_choice"]
    lens = [(len(next(o for o in q["options"] if o["correct"])["text"]), [len(o["text"]) for o in q["options"] if not o["correct"]]) for q in sc]
    return {
        "workbook_id": doc["workbook_id"], "status": doc["status"],
        "units": units,
        "totals": {"units": len(doc["units"]), "questions": len(qs), "single_choice": len(sc),
                   "short_answer": len(qs) - len(sc),
                   "by_section_type_kind": {" / ".join(k): v for k, v in sorted(tot.items())},
                   "bands": dict(sorted(Counter(u["band"] for u in doc["units"]).items())),
                   "vocabulary_items": sum(len(u["vocabulary"]) for u in doc["units"]),
                   "reading_words": sum(r["reading_words"] for r in units),
                   "listening_words": sum(r["listening_words"] for r in units)},
        "answer_positions": model.position_stats(qs),
        "length_clue": {"correct_strictly_longest": sum(c > max(w) for c, w in lens),
                        "correct_strictly_shortest": sum(c < min(w) for c, w in lens), "single_choice": len(sc)},
    }


def critique(doc):
    """Heuristic flags for a reader. Each flag names the item and the reason."""
    flags = []
    for u in doc["units"]:
        for sec in ("reading", "listening"):
            s = u[sec]
            texts = {x["id"]: x["text"] for x in (s.get("segments") or s["turns"])}
            full = " ".join(texts.values())
            for q in s["questions"]:
                ev = " ".join(e["excerpt"] for e in q["evidence"])
                if re.search(r"\bne\b.*\bpas\b|\bn'.*\bpas\b", q["stem"]):
                    flags.append((q["id"], "negative stem: check it reads clearly"))
                if q["type"] != "single_choice":
                    continue
                correct = next(o for o in q["options"] if o["correct"])
                wrong = [o for o in q["options"] if not o["correct"]]
                c_sup = len(toks(correct["text"]) & toks(ev))
                for o in wrong:
                    w_sup = len(toks(o["text"]) & toks(ev))
                    if w_sup > c_sup and w_sup >= 2:
                        flags.append((q["id"], f"distractor {o['key']} overlaps the evidence more than the key ({w_sup}>{c_sup})"))
                    if len(o["text"]) > 12 and fold(o["text"]).rstrip(".") in fold(full):
                        flags.append((q["id"], f"distractor {o['key']} appears verbatim in the text: confirm it is wrong in context"))
                ends = {o["text"].rstrip()[-1:] in ".?!»" for o in q["options"]}
                if len(ends) > 1:
                    flags.append((q["id"], "options end inconsistently (punctuation)"))
                if c_sup == 0 and q["kind"] != "inference":
                    flags.append((q["id"], "key shares no content word with its evidence: check the paraphrase"))
    return flags
