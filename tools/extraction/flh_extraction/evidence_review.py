"""Local evidence review of extraction outputs (offline, standard library only).

  python3 -B -m flh_extraction evidence-review --refs R.jsonl --a A.jsonl [--b B.jsonl] [--limit 50] [--page 1] [--json OUT] [--md OUT]

Each predicted unit is placed beside its source evidence, and each finding is
one of these classes:

* ``malformed``: the output does not parse or does not match the unit contract.
  This is a record-level finding.
* ``missing_evidence``: the unit has no term that can be located in a text
  (``audit.anchor_terms`` is empty).
* ``unsupported``: the unit's terms occur neither in the learner's text nor in
  the explanation shown with it.
* ``explanation_only``: the terms occur only in the explanation. That is weaker
  evidence: the learner did not raise it.
* ``anchored``: the terms occur in the learner's text.
* ``conflicting_evidence``: two units of one record share an anchor term but
  claim different things (kind or canonical). The evidence they rest on then
  supports competing readings, and a person must decide.

Locating evidence is a HEURISTIC (lexical anchoring, as in ``quality.py``).
Whether a claim is TRUE is never measured here; that needs a human
(``reviewer_evidence.py``). Reports carry short excerpts (``EXCERPT`` chars
around the match) and the SHA-256 of each source text, never the full corpus.

With ``--b``, the comparison of two result files is deterministic. Units are
keyed by kind and normalized canonical, and the report lists added, removed and
reclassified units; a move to a worse class is a regression. The known FLH-154
F1 expected failure is reported apart, in ``known_issues``: it is never counted
as a new regression.
"""

from __future__ import annotations

import hashlib
import json
import os

from . import audit
from .quality import parse_diagnostic
from .records import KINDS, UNIT_FIELDS, load_jsonl
from .textnorm import norm

SCHEMA = "flh_extraction_evidence_review_v1"
EXCERPT = 40
CLASSES = ("anchored", "explanation_only", "missing_evidence", "unsupported", "conflicting_evidence")
RANK = {"anchored": 0, "explanation_only": 1, "conflicting_evidence": 2, "missing_evidence": 3, "unsupported": 3, "malformed": 4, "absent": 4}
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWN_ISSUES = [{
    "id": "FLH-154-F1", "test": "tests/test_reporting.py::CrossReportDenominators::test_quality_and_evaluate_count_invalid_rows_alike",
    "status": "expected failure (unittest.expectedFailure), documented in FLH-154 part 4",
    "what": "quality.report leaves invalid rows out of unit F1 while evaluate counts them: the two reports' denominators differ",
}]


def known_issue_still_marked() -> bool:
    """The FLH-154 F1 test is still declared as an expected failure (read from the test source)."""
    path = os.path.join(HERE, "tests", "test_reporting.py")
    try:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
    except OSError:
        return False
    i = src.find("def test_quality_and_evaluate_count_invalid_rows_alike")
    return i > 0 and "@unittest.expectedFailure" in src[max(0, i - 80):i]


def contract_errors(obj) -> list[str]:
    if not isinstance(obj, dict) or not isinstance(obj.get("units"), list):
        return ["not an object with a units list"]
    out = []
    for k, u in enumerate(obj["units"]):
        if not isinstance(u, dict) or set(u) != UNIT_FIELDS:
            out.append(f"unit {k}: fields differ from the contract")
        elif u["kind"] not in KINDS:
            out.append(f"unit {k}: unknown kind {u['kind']!r}")
    return out


def locate(text: str, terms) -> tuple[int, int] | None:
    """Position (start, end) in ``text`` of the first anchor term found, or None."""
    low = text.lower()
    stems, phrases = terms
    best = None
    for p in sorted(phrases, key=len, reverse=True):
        i = low.find(p.lower())
        if i >= 0 and (best is None or i < best[0]):
            best = (i, i + len(p))
    if best is None:
        for s in sorted(stems):
            i = low.find(s.lower())
            if i >= 0 and (best is None or i < best[0]):
                best = (i, i + len(s))
    return best


def excerpt(text: str, span) -> str:
    a, b = max(0, span[0] - EXCERPT), min(len(text), span[1] + EXCERPT)
    return ("…" if a else "") + text[a:span[0]] + "[" + text[span[0]:span[1]] + "]" + text[span[1]:b] + ("…" if b < len(text) else "")


def unit_key(u: dict) -> str:
    return f"{u.get('kind')}|{norm(str(u.get('canonical', '')))}"


def review_record(ref: dict, output) -> dict:
    """Findings for one record. ``output`` is the raw text or the parsed object."""
    learner, visible = audit.learner_text(ref), audit.visible_text(ref)
    rec = {"id": ref["id"], "source_sha256": hashlib.sha256(learner.encode("utf-8")).hexdigest(), "units": []}
    obj = output
    if isinstance(output, str):
        diag = parse_diagnostic(output)
        if diag != "parses":
            return {**rec, "class": "malformed", "reason": diag}
        obj = json.loads(output)
    bad = contract_errors(obj)
    if bad:
        return {**rec, "class": "malformed", "reason": "; ".join(bad)}
    lt, vt = norm(learner), norm(visible)
    for k, u in enumerate(obj["units"]):
        terms = audit.anchor_terms(u)
        entry = {"index": k, "key": unit_key(u), "kind": u["kind"], "canonical": u["canonical"], "claim": u["statement"][:200]}
        if not (terms[0] or terms[1]):
            entry.update(cls="missing_evidence", evidence=None, basis="heuristic: no locatable term in the unit")
        elif audit.is_anchored(lt, terms):
            span = locate(learner, terms)
            entry.update(cls="anchored", evidence=excerpt(learner, span) if span else None, basis="heuristic: term found in the learner's text")
        elif audit.is_anchored(vt, terms):
            exp = ref["input"]["effective_explanation"]
            span = locate(exp, terms)
            entry.update(cls="explanation_only", evidence=excerpt(exp, span) if span else None, basis="heuristic: term found only in the explanation")
        else:
            entry.update(cls="unsupported", evidence=None, basis="heuristic: no term found in the learner's text or the explanation")
        entry["_terms"] = terms[0] | terms[1]
        rec["units"].append(entry)
    located = [e for e in rec["units"] if e["cls"] in ("anchored", "explanation_only")]
    for x in located:
        for y in located:
            if x is not y and x["_terms"] & y["_terms"] and (x["kind"], norm(x["canonical"])) != (y["kind"], norm(y["canonical"])):
                x["cls"] = "conflicting_evidence"
                x["basis"] = "heuristic: another unit shares an anchor term with a different claim; a person must decide"
    for e in rec["units"]:
        terms = e.pop("_terms")
        e["shared_terms"] = sorted(terms)[:6] if e["cls"] == "conflicting_evidence" else []
    rec["class"] = "units" if rec["units"] else "zero_units"
    return rec


def review(refs: list[dict], outputs: dict) -> dict:
    recs = []
    for r in sorted(refs, key=lambda r: r["id"]):
        if r["id"] not in outputs:
            recs.append({"id": r["id"], "class": "absent", "reason": "no output for this record", "units": []})
        else:
            recs.append(review_record(r, outputs[r["id"]]))
    per_class, per_kind = {}, {}
    for rec in recs:
        if rec["class"] in ("malformed", "absent"):
            per_class[rec["class"]] = per_class.get(rec["class"], 0) + 1
        for u in rec["units"]:
            per_class[u["cls"]] = per_class.get(u["cls"], 0) + 1
            k = per_kind.setdefault(u["kind"], {c: 0 for c in CLASSES} | {"units": 0})
            k["units"] += 1
            k[u["cls"]] += 1
    for k in per_kind.values():
        k["anchored_share"] = round(k["anchored"] / k["units"], 4) if k["units"] else None
    return {"records": recs, "counts": {"records": len(recs), "units": sum(len(r["units"]) for r in recs), "by_class": dict(sorted(per_class.items())),
                                         "coverage_by_kind": dict(sorted(per_kind.items()))}}


def compare(a: dict, b: dict) -> dict:
    """Deterministic: per record and unit key, A's class vs B's (absent when missing)."""
    ra, rb = {r["id"]: r for r in a["records"]}, {r["id"]: r for r in b["records"]}
    changes = []
    for i in sorted(set(ra) | set(rb)):
        x, y = ra.get(i, {"class": "absent", "units": []}), rb.get(i, {"class": "absent", "units": []})
        if (x["class"] in ("malformed", "absent")) or (y["class"] in ("malformed", "absent")):
            if x["class"] != y["class"]:
                changes.append({"id": i, "key": None, "a": x["class"], "b": y["class"],
                                "regression": RANK.get(y["class"], 0) > RANK.get(x["class"], 0)})
            continue
        ua, ub = {u["key"]: u for u in x["units"]}, {u["key"]: u for u in y["units"]}
        for key in sorted(set(ua) | set(ub)):
            ca, cb = ua.get(key, {}).get("cls", "absent"), ub.get(key, {}).get("cls", "absent")
            if ca == cb:
                continue
            if ca == "absent":
                kind, reg = "added", cb in ("unsupported", "missing_evidence", "conflicting_evidence")
            elif cb == "absent":
                kind, reg = "removed", ca in ("anchored", "explanation_only")
            else:
                kind, reg = "reclassified", RANK[cb] > RANK[ca]
            changes.append({"id": i, "key": key, "change": kind, "a": ca, "b": cb, "regression": reg,
                            "improvement": kind == "reclassified" and RANK[cb] < RANK[ca],
                            "evidence_a": ua.get(key, {}).get("evidence"), "evidence_b": ub.get(key, {}).get("evidence")})
        continue
    for c in changes:
        c.setdefault("change", "record")
        c.setdefault("improvement", c["change"] == "record" and not c["regression"])
    return {"changes": changes, "regressions": sum(1 for c in changes if c["regression"]), "improvements": sum(1 for c in changes if c["improvement"])}


def page(items: list, limit: int, number: int) -> dict:
    if limit < 1 or number < 1:
        raise ValueError("limit and page are 1 or more")
    start = (number - 1) * limit
    return {"page": number, "limit": limit, "total": len(items), "pages": max(1, -(-len(items) // limit)), "items": items[start:start + limit]}


def file_sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load_outputs(path: str) -> dict:
    """JSONL rows {"id", "output": raw text or object}."""
    return {r["id"]: r["output"] for r in load_jsonl(path)}


def build(refs_path: str, a_path: str, b_path: str | None = None, limit: int = 50, number: int = 1) -> dict:
    refs = load_jsonl(refs_path)
    ra = review(refs, load_outputs(a_path))
    out = {"schema": SCHEMA, "basis": "heuristic evidence location; claim truth is not measured (needs a human)",
           "inputs": {os.path.basename(p): file_sha256(p) for p in (refs_path, a_path, b_path) if p},
           "a": {"counts": ra["counts"], "units_page": page([dict(u, id=r["id"]) for r in ra["records"] for u in r["units"]], limit, number),
                 "record_findings": [{k: r[k] for k in ("id", "class", "reason")} for r in ra["records"] if r["class"] in ("malformed", "absent")]},
           "known_issues": [dict(k, still_marked_expected_failure=known_issue_still_marked()) for k in KNOWN_ISSUES]}
    if b_path:
        rb = review(refs, load_outputs(b_path))
        out["b"] = {"counts": rb["counts"], "record_findings": [{k: r[k] for k in ("id", "class", "reason")} for r in rb["records"] if r["class"] in ("malformed", "absent")]}
        cmp = compare(ra, rb)
        out["comparison"] = {"regressions": cmp["regressions"], "improvements": cmp["improvements"], "changes_page": page(cmp["changes"], limit, number),
                             "note": "new regressions only; the FLH-154 F1 known issue is listed under known_issues and never counted here"}
    return out


def markdown(rep: dict) -> str:
    lines = [f"# Extraction evidence review ({rep['schema']})", "", f"Basis: {rep['basis']}.", ""]
    for side in ("a", "b"):
        if side not in rep:
            continue
        c = rep[side]["counts"]
        lines += [f"## {side.upper()}: {c['records']} records, {c['units']} units", "", "| class | count |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in c["by_class"].items()]
        lines += ["", "| kind | units | anchored | explanation only | missing evidence | unsupported | conflicting |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {k} | {v['units']} | {v['anchored']} | {v['explanation_only']} | {v['missing_evidence']} | {v['unsupported']} | {v['conflicting_evidence']} |"
                  for k, v in c["coverage_by_kind"].items()]
        for f in rep[side]["record_findings"]:
            lines.append(f"- {f['id']}: **{f['class']}** ({f['reason']})")
        lines.append("")
    pg = rep["a"]["units_page"]
    lines += [f"## Units of A, page {pg['page']} of {pg['pages']} ({pg['total']} units)", ""]
    for u in pg["items"]:
        lines.append(f"- `{u['id']}` #{u['index']} **{u['cls']}** {u['kind']} / {u['canonical']}: evidence {u['evidence'] or '(none)'}")
    if "comparison" in rep:
        cp = rep["comparison"]
        lines += ["", f"## A → B: {cp['regressions']} regressions, {cp['improvements']} improvements", ""]
        for ch in cp["changes_page"]["items"]:
            lines.append(f"- `{ch['id']}` {ch['key'] or '(record)'} [{ch['change']}]: {ch['a']} → {ch['b']}"
                         + (" **regression**" if ch["regression"] else " improvement" if ch["improvement"] else ""))
    lines += ["", "## Known issues (not new regressions)", ""]
    lines += [f"- {k['id']}: {k['what']} — {k['status']}; still marked: {k['still_marked_expected_failure']}" for k in rep["known_issues"]]
    return "\n".join(lines) + "\n"
