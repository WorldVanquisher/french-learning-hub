"""French grounding quality (R4; offline, deterministic, standard library only).

  python3 -B -m flh_extraction.grounding_quality [--json OUT] [--md OUT] [--window N]

A located quote is the learner's own words; it is not yet evidence *for* the claim. The R4
cases (``fixtures/r4_v1/quality``) put the shipped grounding in front of four French
difficulties: paraphrase, negation, accent and case errors, and deceptive lexical overlap.
``annotations.json`` (``flh_grounding_reference_v1``) was written and hashed before any
candidate check existed. For each item it records:
- **location**: where the quoted words are (verbatim, case variant, accent variant,
  paraphrase, absent);
- **relation**: what they say about the claim. Contradictory evidence (the words say the
  opposite) is kept apart from unrelated evidence (shared words, no bearing).

Every system maps an item to one outcome: ``supported`` (it would be batch-approved),
``review`` (the learner must look) or ``unsupported``. The annotation gives the acceptable
outcomes; a miss is one of these error categories:

  false_support_contradiction  supported, but the quoted words contradict the claim
  false_support_unrelated      supported, but the quoted words have no bearing on it
  false_support_paraphrase     supported from words the learner never wrote
  variant_accepted_silently    supported although the learner's words differ in case or accents
  missed_variant               unsupported although the learner wrote these words with other case or accents
  over_flag                    review where the verbatim words support the claim
  false_rejection              unsupported where the verbatim words support the claim

Systems (all deterministic):

* ``exact_v1``: the shipped rules. It uses ``practice.draft`` grounding (exact after NFC and
  apostrophe unification) and the 2.2 review (``review2``: word cues, paraphrases). This is
  the baseline, unchanged.
* ``folded_v1``: the obvious alternative, a case- and accent-insensitive search. One hit is
  supported, several are review, none is unsupported.
* ``lexical_v1``: the existing ``evidence_review`` anchoring heuristic that the draft already
  records (``heuristic_class``). Claims only; other item types are not scored.
* ``exact_v1+checks_v2``: the R4 proposal. It is the baseline plus two checks that can only add
  a review, never a support:
  - ``negated_quote``: a negation word within ``window`` tokens before a form the claim
    names in « », inside one clause, while the claim itself is not negated. ``window`` is
    3 for « ne + verb + pas ».
  - ``spelling_variant``: a quote not found exactly occurs once when case and accents are
    ignored. The learner's actual words and the difference are shown for review.

The same author wrote the cases and the checks, so the counts show reproducible behaviour on
this fixture; they are not an accuracy estimate. ``--window`` reports the sensitivity.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata

from . import practice as pr
from . import review2 as rv

SCHEMA = "flh_grounding_quality_report_v1"
CHECKS = "flh_grounding_checks_v2"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUALITY = os.path.join(HERE, "fixtures", "r4_v1", "quality")
SOURCES = ("q_negation.json", "q_accents.json", "q_paraphrase.json")
OUTCOMES = ("supported", "review", "unsupported")
SYSTEMS = ("exact_v1", "folded_v1", "lexical_v1", "exact_v1+checks_v2")
CATEGORIES = ("correct", "false_support_contradiction", "false_support_unrelated", "false_support_paraphrase", "variant_accepted_silently",
              "missed_variant", "over_flag", "false_rejection")
WINDOW = 3
NEG_FR = {"ne", "n'", "pas", "jamais", "plus", "rien", "personne", "aucun", "aucune", "non", "sans", "guère"}
NEG_CLAIM = {"not", "never", "no", "cannot", "ne", "n'", "pas", "jamais"}
TOKEN = re.compile(r"[^\W\d_]+'|[^\W\d_]+|[:;.!?]")
BOUNDARY = set(":;.!?")
QUOTED = re.compile(r"«\s*([^»]*?)\s*»")


def _load(name: str):
    with open(os.path.join(QUALITY, name), encoding="utf-8") as fh:
        return json.load(fh)


def tokens(s: str) -> list[str]:
    s = pr.fold(s).lower().replace("n't", " n't")
    return TOKEN.findall(s) + (["n't"] if "n't" in s else [])


def strip_marks(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def loose(s: str) -> tuple[str, list[int]]:
    """Case- and accent-free text with, for each output character, its index in the input."""
    out, idx = [], []
    for i, ch in enumerate(pr.fold(s)):
        for c in strip_marks(ch).casefold():
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def find_all(hay: str, needle: str) -> list[int]:
    hits, i = [], hay.find(needle) if needle else -1
    while i >= 0:
        hits.append(i)
        i = hay.find(needle, i + 1)
    return hits


# ---- the R4 proposal: two checks that can only ask for review ----

def negated_quote(claim_text: str, quote: str, window: int = WINDOW) -> dict | None:
    """A negation word right before a form the claim names, inside one clause of the quote, and an unnegated claim."""
    if NEG_CLAIM & set(tokens(QUOTED.sub(" ", claim_text))):
        return None
    q = tokens(quote)
    for form in QUOTED.findall(pr.fold(claim_text)):
        f = [t for t in tokens(form) if t not in BOUNDARY]
        if not f:
            continue
        for i in range(len(q) - len(f) + 1):
            if q[i:i + len(f)] != f:
                continue
            before = []
            for t in reversed(q[:i]):
                if t in BOUNDARY or len(before) == window:
                    break
                before.append(t)
            neg = [t for t in before if t in NEG_FR]
            if neg:
                return {"check": "negated_quote", "form": form, "negation": sorted(set(neg)),
                        "detail": f"in « {quote} », « {form} » follows « {' '.join(reversed(before))} »: the quoted words may deny what the "
                                  "claim asserts (a word check, not proof)"}
    return None


def spelling_variant(src: dict, quote: str) -> dict | None:
    """A quote that is not the learner's exact words but occurs once when case and accents are ignored."""
    lq, _ = loose(quote)
    hits = []
    for f in pr.LEARNER_FIELDS:
        text = pr.fold(src["capture"][f])
        lt, idx = loose(text)
        for i in find_all(lt, lq):
            a, b = idx[i], idx[i + len(lq) - 1] + 1
            hits.append((f, text[a:b]))
    if len(hits) != 1:
        return None
    f, words = hits[0]
    q = pr.fold(quote)
    kind = "case" if words.lower() == q.lower() else "accents" if strip_marks(words) == strip_marks(q) else "case and accents"
    diff = [[a, b] for a, b in zip(q.split(), words.split()) if a != b]
    return {"check": "spelling_variant", "field": f, "learner_words": words, "differs_in": kind, "words": diff,
            "detail": f"not the learner's exact words: the learner wrote « {words} » ({kind} differ); review before using it"}


# ---- outcomes per system ----

def _exact(src: dict) -> dict:
    drf = pr.draft(src)
    res = rv.resolve2({src["revision"]: drf}, [], {src["revision"]: src})
    out = {}
    for it in res["items"]:
        if it["support"] in ("unsupported", "no_evidence"):
            o = "unsupported"
        elif it["support"] == "uncertain" or it["cues"] or it["paraphrases"]:
            o = "review"
        else:
            o = "supported"
        out[it["proposal_ref"]] = {"outcome": o, "support": it["support"], "cues": [c["cue"] for c in it["cues"]],
                                   "groundings": [g["status"] for g in it["groundings"]], "heuristic_class": it.get("heuristic_class")}
    return out


def _folded(src: dict) -> dict:
    texts = [loose(src["capture"][f])[0] for f in pr.LEARNER_FIELDS]
    out = {}
    for it in src["proposal"]["items"]:
        st = []
        for q in it.get("quotes", []):
            n = sum(len(find_all(t, loose(q)[0])) for t in texts)
            st.append("supported" if n == 1 else "review" if n > 1 else "unsupported")
        o = "unsupported" if not st or "unsupported" in st else "review" if "review" in st else "supported"
        out[it["ref"]] = {"outcome": o}
    return out


def _lexical(exact: dict) -> dict:
    m = {"anchored": "supported", "explanation_only": "review", "conflicting_evidence": "review"}
    return {ref: ({"outcome": m.get(v["heuristic_class"], "unsupported"), "heuristic_class": v["heuristic_class"]}
                  if v["heuristic_class"] is not None else {"outcome": None, "note": "not a claim: the heuristic does not score it"})
            for ref, v in exact.items()}


def _candidate(src: dict, exact: dict, window: int) -> dict:
    items = {i["ref"]: i for i in src["proposal"]["items"]}
    drf = pr.draft(src)
    out = {}
    for it in drf["items"]:
        ref = it["proposal_ref"]
        base = exact[ref]
        checks = []
        main = it["content"][pr.MAIN_TEXT[it["type"]]]
        for g in it["groundings"]:
            if g["status"] == "located":
                c = negated_quote(main, g["quote"], window)
            elif g["status"] == "not_found":
                c = spelling_variant(src, g["quote"])
            else:
                c = None
            if c:
                checks.append(c)
        o = base["outcome"]
        if checks and o in ("supported", "unsupported"):
            o = "review"
        out[ref] = {"outcome": o, "checks": checks, "proposal_type": items[ref]["type"]}
    return out


def category(outcome: str | None, ann: dict, acceptable: list[str]) -> str | None:
    if outcome is None:
        return None
    if outcome in acceptable:
        return "correct"
    rel, loc = ann["relation"], ann["location"]
    if outcome == "supported":
        if rel == "contradicts":
            return "false_support_contradiction"
        if rel == "unrelated":
            return "false_support_unrelated"
        if loc == "paraphrase":
            return "false_support_paraphrase"
        return "variant_accepted_silently"
    if loc in ("case_variant", "accent_variant") and rel == "supports":
        return "missed_variant"
    return "over_flag" if outcome == "review" else "false_rejection"


def acceptable_for(ref_doc: dict, ann: dict) -> list[str]:
    key = f"supports+{ann['location']}" if ann["relation"] == "supports" else ann["relation"]
    if ann["location"] == "absent":
        key = "absent"
    return ref_doc["acceptable"][key]


def evaluate(window: int = WINDOW) -> dict:
    ref = _load("annotations.json")
    srcs = {s["source_id"]: s for s in (_load(n) for n in SOURCES)}
    per = {}
    for sid, src in srcs.items():
        ex = _exact(src)
        per[sid] = {"exact_v1": ex, "folded_v1": _folded(src), "lexical_v1": _lexical(ex), "exact_v1+checks_v2": _candidate(src, ex, window)}
    rows = []
    for ann in ref["items"]:
        acc = acceptable_for(ref, ann)
        row = {k: ann[k] for k in ("source_id", "ref", "phenomenon", "location", "relation")}
        row["acceptable"] = acc
        for sysname in SYSTEMS:
            r = per[ann["source_id"]][sysname][ann["ref"]]
            row[sysname] = {"outcome": r["outcome"], "category": category(r["outcome"], ann, acc)}
            if r.get("checks"):
                row[sysname]["checks"] = [{k: c[k] for k in ("check", "detail")} for c in r["checks"]]
            if r.get("cues"):
                row[sysname]["cues"] = r["cues"]
        rows.append(row)
    summary = {}
    for sysname in SYSTEMS:
        cats = [r[sysname]["category"] for r in rows if r[sysname]["category"] is not None]
        by_ph = {}
        for r in rows:
            c = r[sysname]["category"]
            if c is not None:
                d = by_ph.setdefault(r["phenomenon"], {"items": 0, "correct": 0})
                d["items"] += 1
                d["correct"] += c == "correct"
        summary[sysname] = {"scored": len(cats), "correct": cats.count("correct"),
                            "errors": {c: cats.count(c) for c in CATEGORIES[1:] if cats.count(c)}, "by_phenomenon": dict(sorted(by_ph.items()))}
    return {"schema": SCHEMA, "checks": CHECKS, "window": window, "items": rows, "summary": summary,
            "reference_sha256": pr.sha(json.dumps(ref, ensure_ascii=False, sort_keys=True)),
            "note": "same author for cases and checks: reproducible behaviour on this fixture, not an accuracy estimate"}


def markdown(rep: dict, sensitivity: dict | None = None) -> str:
    L = ["# French grounding quality (R4)", "",
         f"Reference `flh_grounding_reference_v1` (frozen before the candidate). Candidate checks `{CHECKS}`, window {rep['window']}.",
         rep["note"] + ".", "", "| System | Correct | Errors |", "|---|---|---|"]
    for s in SYSTEMS:
        v = rep["summary"][s]
        L.append(f"| `{s}` | {v['correct']}/{v['scored']} | " + (", ".join(f"{k} {n}" for k, n in v["errors"].items()) or "none") + " |")
    L += ["", "| Item | Phenomenon | Location | Relation | Acceptable | " + " | ".join(f"`{s}`" for s in SYSTEMS) + " |",
          "|---|---|---|---|---|" + "---|" * len(SYSTEMS)]
    for r in rep["items"]:
        cells = []
        for s in SYSTEMS:
            v = r[s]
            cells.append("n/a" if v["outcome"] is None else (v["outcome"] + ("" if v["category"] == "correct" else f" **{v['category']}**")))
        L.append(f"| {r['ref']} | {r['phenomenon']} | {r['location']} | {r['relation']} | {', '.join(r['acceptable'])} | " + " | ".join(cells) + " |")
    L += ["", "Checks raised by the candidate:", ""]
    for r in rep["items"]:
        for c in r["exact_v1+checks_v2"].get("checks", []):
            L.append(f"- {r['ref']} `{c['check']}`: {c['detail']}")
    if sensitivity:
        L += ["", "Window sensitivity (candidate only):", ""]
        for w, v in sorted(sensitivity.items()):
            L.append(f"- window {w}: correct {v['correct']}/{v['scored']}; " + (", ".join(f"{k} {n}" for k, n in v["errors"].items()) or "no error"))
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="flh_extraction.grounding_quality")
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--window", type=int, default=WINDOW)
    a = ap.parse_args(argv)
    rep = evaluate(a.window)
    sens = {w: evaluate(w)["summary"]["exact_v1+checks_v2"] for w in (2, 3, 4, 6)}
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(pr.dumps({**rep, "window_sensitivity": {str(k): v for k, v in sens.items()}}))
    md = markdown(rep, sens)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(md)
    print(md, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
