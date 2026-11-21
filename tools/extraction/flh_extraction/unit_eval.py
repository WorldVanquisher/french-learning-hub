"""Quality of evidence-bearing units against a gold set (PROTOTYPE, offline, deterministic, standard library only).

  python3 -B -m flh_extraction.unit_eval [--gold fixtures/xsubject_v1/gold/gold_v1.json] [--json OUT] [--md OUT]

Two systems produce units for every gold document through the normal draft and review. A system's **accepted**
units are the ones the review's batch would approve: supported, no word cue, no conflict.

* ``authored``: the proposal written with the source (hand-written, synthetic).
* ``sentence_baseline``: a language-agnostic, deterministic extractor. It takes each sentence of the context that
  holds a digit or a number word and makes it a claim, quoting the sentence itself. It is the floor any extractor
  must beat.

Matching (EXT-051, EXT-052). For an accepted unit *u* and a gold claim *g*:
- **Covered.** A gold span is covered when spans of *u* in the same field cover at least half of its characters.
  *g* is covered when one of its spans is covered (``require: any``), or every one is (``require: all``, the
  cross-paragraph case).
- **States the value.** The gold value occurs in the unit's words; for a contrast, it may occur in the words it
  quotes.
- **Classes:**

  correct            covers g and states its value: evidence-supported
  wrong_claim        covers g but does not state its value (a claim the cited words do not support)
  bad_span           states g's value and names its topic, but cites other words (or only part of a required set)
  extra              relates to no gold claim (a false accept)

Per gold claim (EXT-054): ``matched`` (one correct unit or more), ``duplicate`` (correct units beyond the first,
EXT-053), ``bad_span_only`` (mentioned, but never with its evidence) or ``missing`` (never mentioned). Missing
claims and bad spans are counted apart.

Every rate is ``[count, denominator]`` with the rate beside it (EXT-058). The report states its sample size and its
known biases (EXT-059). ``scorecard`` is a compact JSON for trend comparison (EXT-060), keyed by the gold and input
digests.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from . import practice as pr
from . import review2 as rv
from . import units as un

SCHEMA = "flh_units_eval_v1"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD = os.path.join(HERE, "fixtures", "xsubject_v1", "gold", "gold_v1.json")
SOURCES = os.path.join(HERE, "fixtures", "xsubject_v1", "sources")
NUMBER = re.compile(r"\d|\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|hundred|thousand)\b", re.I)
SENTENCE = re.compile(r"[^.!?\n]+[.!?]")
COVER = 0.5


def _read(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_source(name: str) -> dict:
    v1, _ = un.read_source(_read(os.path.join(SOURCES, name)))
    return v1


def sentence_baseline(src: dict) -> list[dict]:
    """Every context sentence with a number in it becomes a claim quoting itself."""
    out = []
    for k, m in enumerate(SENTENCE.finditer(pr.fold(src["capture"]["original_context"]))):
        sent = m.group(0).strip()
        if NUMBER.search(sent):
            out.append({"ref": f"s{k:02d}", "type": "claim", "kind": "concept", "statement": sent, "quotes": [sent], "confidence": 0.5})
    return out


LABEL = re.compile(r"^\s*(#|.*\b(part|chapter|week|lesson|section)\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b)", re.I)


def sentence_baseline_v2(src: dict) -> list[dict]:
    """The R4 targeted change (EXT-120), chosen on the dev split only: headings and section labels are not claims.
    A sentence that starts a Markdown heading or names a part, chapter, week, lesson or section with a number is
    skipped; everything else is as ``sentence_baseline``."""
    return [it for it in sentence_baseline(src) if not LABEL.match(it["statement"])]


def accepted_units(src: dict, items: list[dict]) -> tuple[dict, list[dict]]:
    """(units export with every proposed item, the accepted ones) for ``src`` with ``items`` as its proposal."""
    s = json.loads(json.dumps(src))
    s["proposal"] = {"proposer": s["proposal"].get("proposer", ""), "items": items}
    drf = pr.draft(s)
    res = rv.resolve2({s["revision"]: drf}, [], {s["revision"]: s})
    plan = rv.plan(res)
    decs = []
    for k, iid in enumerate(plan["selected"] or []):
        d = pr.decision(drf, iid, "approve", k + 1)
        d["based_on"]["draft_id"] = drf["draft_id"]
        d["based_on"]["material_hash"] = next(x["material_hash"] for x in res["items"] if x["item_id"] == iid)
        decs.append(d)
    res = rv.resolve2({s["revision"]: drf}, decs, {s["revision"]: s})
    doc = un.export(res, {s["revision"]: s})
    return doc, [u for u in doc["units"] if u["state"] in un.USABLE and u["type"] in ("claim", "contrast")]


def _covered(u: dict, gs: dict) -> float:
    best = 0.0
    for e in u["evidence"]:
        if "start" not in e or e["field"] != gs["field"]:
            continue
        lo, hi = max(e["start"], gs["start"]), min(e["end"], gs["end"])
        best = max(best, max(0, hi - lo) / (gs["end"] - gs["start"]))
    return best


def _span_stats(u: dict, g: dict) -> dict:
    """Best gold coverage and the precision of the unit's own spans against the gold spans (same field)."""
    cov = [_covered(u, gs) for gs in g["spans"]]
    inside = total = 0
    for e in u["evidence"]:
        if "start" not in e:
            continue
        total += e["end"] - e["start"]
        inside += max((max(0, min(e["end"], gs["end"]) - max(e["start"], gs["start"])) for gs in g["spans"] if gs["field"] == e["field"]), default=0)
    return {"gold_coverage": round(min(cov) if g.get("require") == "all" else max(cov), 4), "precision": round(inside / total, 4) if total else 0.0}


def _covers(u: dict, g: dict) -> bool:
    fr = [_covered(u, gs) >= COVER for gs in g["spans"]]
    return all(fr) if g.get("require") == "all" else any(fr)


def _states(u: dict, g: dict) -> bool:
    if un._contains(u["text"], g["value"]):
        return True
    return u["type"] == "contrast" and any(un._contains(e["quote"], g["value"]) for e in u["evidence"])


def _mentions(u: dict, g: dict) -> bool:
    return _states(u, g) and all(w in un._norm(u["text"]).split() for w in un._norm(g["topic"]).split())


def score_document(doc_gold: dict, units: list[dict], candidates: list[dict] | None = None) -> dict:
    gold = doc_gold["claims"]
    rows = []
    candidates = candidates if candidates is not None else units
    for u in sorted(units, key=lambda x: x["unit_id"]):
        cov = [g["gold_id"] for g in gold if _covers(u, g)]
        ok = [gid for gid in cov if _states(u, next(g for g in gold if g["gold_id"] == gid))]
        if ok:
            cls = "correct"
        elif cov:
            cls = "wrong_claim"
        elif any(_mentions(u, g) for g in gold):
            cls = "bad_span"
        else:
            cls = "extra"
        rel = ok or cov or [g["gold_id"] for g in gold if _mentions(u, g)]
        errs = []
        for gid in rel:
            g = next(x for x in gold if x["gold_id"] == gid)
            st = _span_stats(u, g)
            if st["gold_coverage"] == 0:
                errs.append({"gold_id": gid, "kind": "evidence_selection", **st})
            elif st["gold_coverage"] < COVER or st["precision"] < COVER:
                errs.append({"gold_id": gid, "kind": "boundary", **st})
        rows.append({"unit_id": u["unit_id"], "type": u["type"], "class": cls, "gold": rel, "text": u["text"], "span_errors": errs,
                     "span_accuracy": [_span_stats(u, next(x for x in gold if x["gold_id"] == gid)) | {"gold_id": gid} for gid in ok]})
    per_gold = []
    byid = {u["unit_id"]: u for u in units}
    for g in gold:
        correct = [r["unit_id"] for r in rows if r["class"] == "correct" and g["gold_id"] in r["gold"]]
        # a unit that names g and states its value without covering its evidence, whatever else it matched
        mention = [r["unit_id"] for r in rows if _mentions(byid[r["unit_id"]], g) and not (_covers(byid[r["unit_id"]], g) and _states(byid[r["unit_id"]], g))]
        per_gold.append({"gold_id": g["gold_id"], "topic": g["topic"], "require": g.get("require", "any"),
                         "status": "matched" if correct else "bad_span_only" if mention else "missing", "units": correct or mention,
                         "duplicates": max(0, len(correct) - 1)})
    accepted_ids = {u["unit_id"] for u in units}
    cand_cov = [g["gold_id"] for g in gold if any((_covers(c, g) and _states(c, g)) or _mentions(c, g) for c in candidates)]
    false_rejects = [{"unit_id": c["unit_id"], "gold_id": g["gold_id"], "state": c["state"], "reasons": [r["code"] for r in c["review_reasons"]] or ["not accepted"]}
                     for c in candidates if c["unit_id"] not in accepted_ids for g in gold if _covers(c, g) and _states(c, g)]
    return {"source_id": doc_gold["source_id"], "topic_area": doc_gold["topic_area"], "gold": len(gold), "candidates": len(candidates),
            "accepted": len(rows), "units": rows, "per_gold": per_gold, "candidate_coverage": _rate(len(cand_cov), len(gold)),
            "false_rejects": false_rejects}


def _rate(c: int, d: int) -> dict:
    return {"count": c, "of": d, "rate": round(c / d, 4) if d else None}


def totals(docs: list[dict]) -> dict:
    rows = [r for d in docs for r in d["units"]]
    pg = [g for d in docs for g in d["per_gold"]]
    acc = len(rows)
    return {"coverage": _rate(sum(1 for g in pg if g["status"] == "matched"), len(pg)),
            "evidence_supported": _rate(sum(1 for r in rows if r["class"] == "correct"), acc),
            "duplicate_rate": _rate(sum(g["duplicates"] for g in pg), acc),
            "missing_claims": _rate(sum(1 for g in pg if g["status"] == "missing"), len(pg)),
            "bad_span_claims": _rate(sum(1 for g in pg if g["status"] == "bad_span_only"), len(pg)),
            "classes": {c: sum(1 for r in rows if r["class"] == c) for c in ("correct", "wrong_claim", "bad_span", "extra")},
            "accepted_units": acc, "gold_claims": len(pg)}


def evaluate(gold_path: str = GOLD, systems=("authored", "sentence_baseline")) -> dict:
    gold = _read(gold_path)
    out = {"schema": SCHEMA, "gold_sha256": pr.sha(json.dumps(gold, ensure_ascii=False, sort_keys=True)), "systems": {}}
    inputs = {}
    for name in systems:
        docs = []
        for dg in gold["documents"]:
            src = load_source(dg["source_file"])
            inputs[dg["source_file"]] = un.source_fingerprint(src)
            items = SYSTEMS[name](src)
            doc, acc = accepted_units(src, items)
            docs.append(score_document(dg, acc, [u for u in doc["units"] if u["type"] in ("claim", "contrast")]))
        out["systems"][name] = {"documents": docs, "totals": totals(docs),
                                "by_topic_area": {d["topic_area"]: totals([d]) for d in docs}}
    out["inputs"] = dict(sorted(inputs.items()))
    out["sample"] = {"documents": len(gold["documents"]), "gold_claims": sum(len(d["claims"]) for d in gold["documents"]),
                     "languages": ["en"], "subjects": sorted({d["topic_area"] for d in gold["documents"]})}
    out["known_biases"] = [
        "the same author wrote the sources, the gold claims and the authored proposals: authored scores are an upper bound, not an estimate",
        "4 short synthetic English documents (2 subjects); no learner data; the French control is not in the gold set",
        "the sentence baseline favours numeric facts by design; descriptive claims are its blind spot",
        "matching is lexical (span overlap >= 50% and the gold value as words): a correct paraphrase of the value counts as wrong_claim"]
    return out


GOLD2 = os.path.join(HERE, "fixtures", "xsubject_v1", "gold", "gold_v2.json")
SYSTEMS = {"authored": lambda src: src["proposal"]["items"], "sentence_baseline": sentence_baseline, "sentence_baseline_v2": sentence_baseline_v2}
NARRATIVE = re.compile(r"\b(today|tomorrow|yesterday|i|my|we)\b", re.I)


def _signature(r: dict) -> str:
    if r["class"] == "wrong_claim":
        return "a value the cited words do not state"
    if LABEL.match(r["text"]):
        return "a heading or section label with a number"
    if NARRATIVE.search(r["text"]):
        return "a narrative sentence (diary, schedule), not a rule"
    return "other sentence with a number"


def analyze(gold_path: str = GOLD2, split: str | None = "eval", systems=tuple(SYSTEMS), model_proposals: dict | None = None) -> dict:
    """Failure analysis on one split of gold v2 (EXT-111 to EXT-118). ``model_proposals`` maps a source file to items
    from an optional model run; without it the model system is reported unavailable, never imitated."""
    gold = _read(gold_path)
    keep = set(gold["split"][split]) if split else {d["source_id"] for d in gold["documents"]}
    out = {"schema": SCHEMA + ".analysis", "gold_sha256": pr.sha(json.dumps(gold, ensure_ascii=False, sort_keys=True)), "split": split,
           "documents": sorted(keep), "systems": {}}
    run = dict(SYSTEMS)
    if model_proposals:
        run["model"] = lambda src: model_proposals[src["source_id"]]
    for name in list(systems) + (["model"] if model_proposals else []):
        docs = []
        for dg in gold["documents"]:
            if dg["source_id"] not in keep:
                continue
            src = load_source(dg["source_file"])
            doc, acc = accepted_units(src, run[name](src))
            docs.append(score_document(dg, acc, [u for u in doc["units"] if u["type"] in ("claim", "contrast")]))
        rows = [r for d in docs for r in d["units"]]
        topics = {}
        for d in docs:
            acc_rows = [x for r in d["units"] for x in r["span_accuracy"]]
            t = topics.setdefault(d["topic_area"], {"correct_units": 0, "exact_spans": 0, "coverage_sum": 0.0, "precision_sum": 0.0})
            t["correct_units"] += len(acc_rows)
            t["exact_spans"] += sum(1 for x in acc_rows if x["gold_coverage"] == 1 and x["precision"] == 1)
            t["coverage_sum"] += sum(x["gold_coverage"] for x in acc_rows)
            t["precision_sum"] += sum(x["precision"] for x in acc_rows)
        span_acc = {k: {"correct_units": v["correct_units"], "exact_spans": _rate(v["exact_spans"], v["correct_units"]),
                        "mean_gold_coverage": round(v["coverage_sum"] / v["correct_units"], 4) if v["correct_units"] else None,
                        "mean_precision": round(v["precision_sum"] / v["correct_units"], 4) if v["correct_units"] else None}
                    for k, v in sorted(topics.items())}
        fa, fr = {}, {}
        for r in rows:
            if r["class"] in ("extra", "wrong_claim"):
                fa.setdefault(_signature(r), []).append(r["text"])
        for d in docs:
            for x in d["false_rejects"]:
                key = ", ".join(sorted(set(x["reasons"])))
                fr.setdefault(key, []).append(f"{d['source_id']}:{x['gold_id']}")
        errs = [e for r in rows for e in r["span_errors"]]
        pg = [g for d in docs for g in d["per_gold"]]
        amb = {g["gold_id"]: g["status"] for d, dg in ((d, next(x for x in gold["documents"] if x["source_id"] == d["source_id"])) for d in docs)
               for g in d["per_gold"] if next(c for c in dg["claims"] if c["gold_id"] == g["gold_id"]).get("ambiguity")}
        out["systems"][name] = {
            "totals": totals(docs),
            "missed_vs_unsupported": {"missed_gold": sum(1 for g in pg if g["status"] == "missing"),
                                      "unsupported_accepted": sum(1 for r in rows if r["class"] in ("wrong_claim", "extra"))},
            "span_errors": {"boundary": sum(1 for e in errs if e["kind"] == "boundary"), "evidence_selection": sum(1 for e in errs if e["kind"] == "evidence_selection"),
                            "cases": errs},
            "candidate_coverage_per_document": {d["source_id"]: d["candidate_coverage"] for d in docs},
            "accepted_span_accuracy_per_topic": span_acc,
            "false_accepts": sorted(({"pattern": k, "count": len(v), "examples": v[:3]} for k, v in fa.items()), key=lambda x: (-x["count"], x["pattern"])),
            "false_rejects": sorted(({"reasons": k, "count": len(v), "cases": v} for k, v in fr.items()), key=lambda x: (-x["count"], x["reasons"])),
            "ambiguity_tagged_gold": dict(sorted(amb.items())), "documents": docs}
    if not model_proposals:
        out["systems"]["model"] = {"status": "unavailable", "reason": "the pinned Qwen3.5-4B files are absent (EXT-074) and no model output exists for "
                                   "these sources; the comparison is not imitated with a stand-in"}
    return out


def scorecard(rep: dict) -> dict:
    """Compact, stable JSON for trends: one line per system, counts with denominators, keyed by the inputs."""
    return {"schema": SCHEMA + ".scorecard", "gold_sha256": rep["gold_sha256"],
            "inputs_sha256": pr.sha(json.dumps(rep["inputs"], sort_keys=True))[:16],
            "systems": {n: {k: [v["count"], v["of"]] for k, v in s["totals"].items() if isinstance(v, dict) and "count" in v}
                        | {"classes": s["totals"]["classes"]} for n, s in rep["systems"].items()}}


def scorecard_v2(dev: dict, ev: dict) -> dict:
    """Compact scorecard for both splits of gold v2 with every failed case named (EXT-149)."""
    out = {"schema": SCHEMA + ".scorecard_v2", "gold_sha256": ev["gold_sha256"], "splits": {}}
    for name, rep in (("dev", dev), ("eval", ev)):
        sys_rows = {}
        for n, s in rep["systems"].items():
            if "totals" not in s:
                sys_rows[n] = {"status": s["status"]}
                continue
            t = s["totals"]
            failed = [{"document": d["source_id"], "unit": r["unit_id"], "class": r["class"], "text": r["text"][:80]}
                      for d in s["documents"] for r in d["units"] if r["class"] != "correct"]
            failed += [{"document": d["source_id"], "gold": g["gold_id"], "class": g["status"]} for d in s["documents"] for g in d["per_gold"]
                       if g["status"] != "matched"]
            sys_rows[n] = {k: [t[k]["count"], t[k]["of"]] for k in ("coverage", "evidence_supported", "duplicate_rate", "missing_claims", "bad_span_claims")}
            sys_rows[n].update({"classes": t["classes"], "span_errors": {k: v for k, v in s["span_errors"].items() if k != "cases"}, "failed_cases": failed})
        out["splits"][name] = {"documents": rep["documents"], "systems": sys_rows}
    return out


def markdown(rep: dict) -> str:
    L = ["# Unit quality against gold v1", "", f"Sample: {rep['sample']['documents']} documents, {rep['sample']['gold_claims']} gold claims, "
         f"subjects {', '.join(rep['sample']['subjects'])}.", "",
         "| System | Coverage | Evidence-supported | Duplicates | Missing claims | Bad-span claims | correct / wrong_claim / bad_span / extra |",
         "|---|---|---|---|---|---|---|"]
    f = lambda r: f"{r['count']}/{r['of']} ({'n/a' if r['rate'] is None else format(r['rate'], '.0%')})"  # noqa: E731
    for n, s in rep["systems"].items():
        t = s["totals"]
        c = t["classes"]
        L.append(f"| `{n}` | {f(t['coverage'])} | {f(t['evidence_supported'])} | {f(t['duplicate_rate'])} | {f(t['missing_claims'])} | "
                 f"{f(t['bad_span_claims'])} | {c['correct']} / {c['wrong_claim']} / {c['bad_span']} / {c['extra']} |")
    L += ["", "Per document:", ""]
    for n, s in rep["systems"].items():
        for d in s["documents"]:
            st = ", ".join(f"{g['gold_id']} {g['status']}" for g in d["per_gold"]) or "no gold claim"
            ex = [r for r in d["units"] if r["class"] != "correct"]
            L.append(f"- `{n}` {d['source_id']}: accepted {d['accepted']}; {st}" + ("; " + "; ".join(f"{r['class']}: {r['text'][:60]}" for r in ex) if ex else ""))
    L += ["", "Known biases:", ""] + [f"- {b}" for b in rep["known_biases"]]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="flh_extraction.unit_eval")
    ap.add_argument("--gold", default=GOLD)
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--scorecard")
    ap.add_argument("--analyze", choices=("dev", "eval", "all"), help="failure analysis on a split of gold v2")
    ap.add_argument("--scorecard-v2", help="write the compact two-split scorecard with failed cases")
    a = ap.parse_args(argv)
    if a.scorecard_v2:
        sc = scorecard_v2(analyze(split="dev"), analyze(split="eval"))
        un.write_atomic(a.scorecard_v2, pr.dumps(sc))
        for sp, v in sc["splits"].items():
            print(sp, {n: (r.get("coverage"), len(r.get("failed_cases", []))) for n, r in v["systems"].items()})
        return 0
    if a.analyze:
        rep = analyze(split=None if a.analyze == "all" else a.analyze)
        text = pr.dumps(rep)
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                fh.write(text)
        for n, sy in rep["systems"].items():
            t = sy.get("totals")
            print(f"{n:22} " + (sy["reason"] if not t else f"coverage {t['coverage']['count']}/{t['coverage']['of']} supported "
                                f"{t['evidence_supported']['count']}/{t['evidence_supported']['of']} classes {t['classes']}"))
        return 0
    rep = evaluate(a.gold)
    for path, text in ((a.json, pr.dumps(rep) if a.json else None), (a.md, markdown(rep)), (a.scorecard, pr.dumps(scorecard(rep)))):
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
    sys.stdout.write(markdown(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
