"""Evidence-bearing learning units for any subject (PROTOTYPE, offline, standard library only).

  python3 -B -m flh_extraction.units export --work DIR --out UNITS.json [--include-source-text]
  python3 -B -m flh_extraction.units inspect --units UNITS.json --source SOURCE.json [--md OUT.md]
  python3 -B -m flh_extraction.units compare --old A.json --new B.json [--json OUT]
  python3 -B -m flh_extraction.units inbox --units UNITS.json --out INBOX.json
  python3 -B -m flh_extraction.units validate --units UNITS.json
  python3 -B -m flh_extraction.units convert --source V1_OR_V2.json --out V1.json [--strict]

``flh_learning_units_v1`` exports, from a normal 2.2 work directory (``practice2`` commands),
every reviewed unit with:
- its exact evidence spans (field, character offsets, quote) and the source fingerprint;
- its review state and why it needs review, if it does;
- recall prompts derived from the claim and its evidence.

Nothing here is specific to French. The subject and language come from the source; a source
without them is read as the French v1 fixtures always were.

* **Source fingerprint** (``sf-…``): the source ID and the learner's own text (NFC, apostrophes
  unified, line endings as LF), nothing else. A rerun of the same text has the same fingerprint whatever the
  revision number or the proposal.
* **Run key** (``rk-…``): the fingerprint, the revision's SHA-256 (text, proposal, goal) and the
  drafter version. An **identical rerun** is one with the same run key; it gives byte-identical
  units, and every learner decision carries over unchanged.
* **Claim key** (``ck-…``): the source ID and the proposer's ``canonical`` for a claim, the two
  forms for a contrast. A prose edit of the statement keeps the claim key and changes the unit;
  a changed canonical is a changed claim.
* **Spans** are half-open ``[start, end)`` offsets into the field's folded text. ``check_span``
  refuses coordinates that are outside the text, empty, reversed, or not equal to the quote.
  Overlapping spans are never merged. They are ordered by (field, start, end, evidence ID), and
  each pair is reported with the characters it shares.
* **Recall.** A claim with ``recall.answer`` gets a free-recall cloze: the statement with the
  answer blanked. It also gets a recognition item whose options are the answer and the other
  claims' answers. The answer must occur in one of the claim's own evidence spans (that span is
  named), and nowhere in what the prompt shows; otherwise the prompt is refused with its reason.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from . import practice as pr
from . import review2 as rv

SCHEMA = "flh_learning_units_v1"
OPTIONAL_UNIT_KEYS = ("canonical", "duplicate_of")
COMPARE = "flh_learning_units_compare_v1"
USABLE = ("approved", "corrected")
DEFAULT_LANGUAGE = "fr"
DEFAULT_SUBJECT = "french"


class UnitError(ValueError):
    pass


def write_atomic(path: str, text: str) -> None:
    """Write next to the target, then replace it in one step: an interrupted run leaves the previous file whole."""
    d = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(d, f".{os.path.basename(path)}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ---- identities ----

def identity_text(s: str) -> str:
    """The text a fingerprint hashes: NFC, apostrophes unified, and CRLF or CR line endings as LF (not content)."""
    return pr.fold(s).replace("\r\n", "\n").replace("\r", "\n")


def source_fingerprint(src: dict) -> str:
    body = {"source_id": src["source_id"], "text": {f: identity_text(src["capture"][f]) for f in pr.LEARNER_FIELDS}}
    return "sf-" + pr.sha(pr.canon(body))[:16]


def run_key(src: dict) -> str:
    return "rk-" + pr.sha("\x1f".join((source_fingerprint(src), pr.revision_sha256(src), pr.DRAFTER)))[:16]


def claim_key(sid: str, it: dict) -> str:
    c = it["content"]
    if it["type"] == "claim":
        basis = c.get("canonical") or pr.content_key("claim", c)
    elif it["type"] == "contrast":
        basis = f"{c['a']['form']}|{c['b']['form']}"
    else:
        basis = pr.content_key(it["type"], c)
    return "ck-" + pr.sha(f"{sid}\x1f{it['type']}\x1f{pr.fold(basis).casefold()}")[:12]


def evidence_key(sid: str, field: str, quote: str, nth: int) -> str:
    """Position-free identity of cited words: the nth occurrence of this quote in this field. An unrelated edit
    elsewhere moves the offsets (and the offset-based evidence ID) but keeps this key."""
    return "ek-" + pr.sha(f"{sid}\x1f{field}\x1f{pr.fold(quote)}\x1f{nth}")[:12]


def meta(src: dict) -> dict:
    return {"subject": src.get("subject", DEFAULT_SUBJECT), "language": src.get("language", DEFAULT_LANGUAGE),
            "data_scope": src.get("data_scope", "synthetic"), "extensions": src.get("extensions", {})}


ID_PATTERNS = {"evidence_key": r"ek-[0-9a-f]{12}", "unit_id": r"k-[0-9a-f]{12}", "claim_key": r"ck-[0-9a-f]{12}", "evidence_id": r"ev-[0-9a-f]{10}", "recall_id": r"r[cr]-[0-9a-f]{12}",
               "fingerprint": r"sf-[0-9a-f]{16}", "run_key": r"rk-[0-9a-f]{16}", "draft_id": r"d-[0-9a-f]{12}"}


def validate_units(doc: dict) -> list[str]:
    """A units export carries every stable identifier, well formed; anything else is refused (EXT-024)."""
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return [f"not a {SCHEMA} document"]
    out = []

    def need(obj, key, where):
        v = obj.get(key) if isinstance(obj, dict) else None
        if not isinstance(v, str) or not re.fullmatch(ID_PATTERNS[key], v):
            out.append(f"{where}: {key} missing or malformed ({v!r})")
    for k in ("fingerprint", "run_key", "draft_id"):
        need(doc.get("source", {}), k, "source")
    for u in doc.get("units", []):
        need(u, "unit_id", "unit")
        need(u, "claim_key", f"unit {u.get('unit_id')}")
        for e in u.get("evidence", []):
            need(e, "evidence_id", f"unit {u.get('unit_id')} evidence")
            if "start" in e:
                need(e, "evidence_key", f"unit {u.get('unit_id')} evidence {e.get('evidence_id')}")
    for r in doc.get("recall", []):
        need(r, "recall_id", "recall")
        need(r, "unit_id", f"recall {r.get('recall_id')}")
        need({"evidence_id": r.get("supported_by")}, "evidence_id", f"recall {r.get('recall_id')} supported_by")
    ids = [u.get("unit_id") for u in doc.get("units", [])]
    if len(ids) != len(set(ids)):
        out.append("unit IDs repeat")
    return out


# ---- source contract v2 (subject-agnostic) ----

SOURCE_V2 = "flh_practice_source_v2"
V2_REQUIRED = ("schema", "source_id", "revision", "subject", "language", "data_scope", "text", "proposal")
V2_OPTIONAL = ("learner_goal", "capture", "extensions")
DATA_SCOPES = ("synthetic", "public", "approved", "private")
LANG = re.compile(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})*")


def read_source(doc: dict, strict: bool = False) -> tuple[dict, dict]:
    """(a v1 source the normal pipeline reads, information) for a v1 or v2 document.

    v1 (``flh_practice_source_v1``) is returned unchanged: the French fixtures and every earlier record read as before.
    A v2 item without a valid span is refused alone, with a code (``missing_required_evidence``, ``invalid_span``,
    ``invalid_evidence``) in ``refused_items``; ``strict=True`` raises on the first instead.
    v2 is checked:
    - the required fields;
    - BCP-47 language;
    - data scope;
    - one span or more per non-generated item.
    Every span must slice its quote out of the text. The v2 document is then converted to v1: quotes are the spans'
    words, and subject, language, scope and extensions are kept as top-level fields, which v1 ignores. Unknown top-level
    fields are refused (put them under ``extensions``); anything under ``extensions`` is kept and passed through.
    """
    if not isinstance(doc, dict):
        raise UnitError("a source is a JSON object")
    schema = doc.get("schema")
    if schema == pr.SOURCE_SCHEMA:
        pr.validate_source(doc)
        return doc, {"version": 1, "subject": doc.get("subject", DEFAULT_SUBJECT), "language": doc.get("language", DEFAULT_LANGUAGE),
                     "extensions": doc.get("extensions", {}), "declared_spans": {}, "refused_items": []}
    if schema != SOURCE_V2:
        raise UnitError(f"unsupported source schema {schema!r}: this reader reads {pr.SOURCE_SCHEMA} and {SOURCE_V2}")
    missing = [k for k in V2_REQUIRED if k not in doc]
    if missing:
        raise UnitError(f"{SOURCE_V2}: missing required field(s) {missing}")
    extra = sorted(set(doc) - set(V2_REQUIRED) - set(V2_OPTIONAL))
    if extra:
        raise UnitError(f"{SOURCE_V2}: unknown field(s) {extra}; optional metadata goes under 'extensions'")
    if not isinstance(doc["language"], str) or not LANG.fullmatch(doc["language"]):
        raise UnitError("language must be a BCP-47 tag such as en, fr or de-CH")
    if doc["data_scope"] not in DATA_SCOPES:
        raise UnitError(f"data_scope must be one of {DATA_SCOPES}")
    if not isinstance(doc.get("extensions", {}), dict):
        raise UnitError("extensions must be an object")
    text = doc["text"]
    if not isinstance(text, dict) or not all(isinstance(text.get(f), str) for f in pr.LEARNER_FIELDS):
        raise UnitError(f"text needs {pr.LEARNER_FIELDS} as strings")
    cap = {"schema_version": "learning_capture_v1", "source": (doc.get("capture") or {}).get("source", "manual"),
           **{f: text[f] for f in pr.LEARNER_FIELDS}}
    if (doc.get("capture") or {}).get("capture_id"):
        cap["capture_id"] = doc["capture"]["capture_id"]
    v1 = {"schema": pr.SOURCE_SCHEMA, "source_id": doc["source_id"], "revision": doc["revision"], "learner_goal": doc.get("learner_goal", ""),
          "capture": cap, "proposal": {"proposer": doc["proposal"].get("proposer", ""), "items": []},
          "subject": doc["subject"], "language": doc["language"], "data_scope": doc["data_scope"], "extensions": doc.get("extensions", {})}
    declared, refused = {}, []
    for k, it in enumerate(doc["proposal"].get("items", [])):
        if not isinstance(it, dict):
            raise UnitError(f"proposal item {k}: not an object")
        spans = it.get("evidence", [])
        why = None
        if not isinstance(spans, list):
            why = ("invalid_evidence", "evidence must be a list of spans")
        elif not it.get("generated") and not spans:
            why = ("missing_required_evidence", "a non-generated item needs at least one span of the learner's text")
        else:
            try:
                checked = [check_span(v1, sp) for sp in spans]
            except UnitError as e:
                why = ("invalid_span", str(e))
        if why:
            if strict:
                raise UnitError(f"proposal item {k} ({it.get('ref')}): {why[0]}: {why[1]}")
            refused.append({"ref": it.get("ref"), "type": it.get("type"), "code": why[0], "detail": why[1]})
            continue
        out = {kk: vv for kk, vv in it.items() if kk != "evidence"}
        if "evidence" in it:
            out["quotes"] = [c["quote"] for c in checked]
        declared[it.get("ref")] = checked
        v1["proposal"]["items"].append(out)
    pr.validate_source(v1)
    return v1, {"version": 2, "subject": doc["subject"], "language": doc["language"], "extensions": doc.get("extensions", {}),
                "declared_spans": declared, "refused_items": refused}


def to_v2(v1: dict, subject: str, language: str, data_scope: str = "synthetic", extensions: dict | None = None) -> dict:
    """A v1 source as v2: every located quote becomes an explicit span (the first occurrence; a repeated quote is kept
    as written and marked in extensions for review)."""
    doc = {"schema": SOURCE_V2, "source_id": v1["source_id"], "revision": v1["revision"], "subject": subject, "language": language,
           "data_scope": data_scope, "text": {f: v1["capture"][f] for f in pr.LEARNER_FIELDS},
           "capture": {k: v1["capture"][k] for k in ("capture_id", "source") if k in v1["capture"]},
           "proposal": {"proposer": v1["proposal"].get("proposer", ""), "items": []}}
    if v1.get("learner_goal"):
        doc["learner_goal"] = v1["learner_goal"]
    if extensions:
        doc["extensions"] = extensions
    for it in v1["proposal"]["items"]:
        out = {k: v for k, v in it.items() if k != "quotes"}
        ev = []
        for q in it.get("quotes", []):
            g = pr.ground(v1, q)
            if g["status"] == "located":
                ev.append({"field": g["field"], "start": g["start"], "end": g["end"], "quote": g["quote"]})
        if ev or it.get("quotes"):
            out["evidence"] = ev
        doc["proposal"]["items"].append(out)
    return doc


# ---- spans ----

def field_text(src: dict, field: str) -> str:
    if field not in pr.LEARNER_FIELDS:
        raise UnitError(f"span field must be one of {pr.LEARNER_FIELDS}, not {field!r}")
    return pr.fold(src["capture"][field])


def check_span(src: dict, span: dict) -> dict:
    """Validate one span's coordinates against the source; returns it with the exact words, or raises UnitError."""
    if not isinstance(span, dict):
        raise UnitError("a span is an object with field, start, end")
    text = field_text(src, span.get("field"))
    a, b = span.get("start"), span.get("end")
    if not (isinstance(a, int) and isinstance(b, int)) or isinstance(a, bool) or isinstance(b, bool):
        raise UnitError("start and end must be integers")
    if not 0 <= a < b <= len(text):
        raise UnitError(f"span [{a}, {b}) is outside [0, {len(text)}) of {span['field']} or empty or reversed")
    words = text[a:b]
    if "quote" in span and pr.fold(span["quote"]) != words:
        raise UnitError(f"span [{a}, {b}) of {span['field']} reads « {words} », not the quote « {span['quote']} »")
    return {"field": span["field"], "start": a, "end": b, "quote": words}


def overlaps(spans: list[dict]) -> list[dict]:
    """Every overlapping pair (same field), deterministic order; spans are never merged."""
    s = sorted(spans, key=lambda x: (x["field"], x["start"], x["end"], x.get("evidence_id", "")))
    out = []
    for i, x in enumerate(s):
        for y in s[i + 1:]:
            if y["field"] != x["field"] or y["start"] >= x["end"]:
                continue
            lo, hi = max(x["start"], y["start"]), min(x["end"], y["end"])
            if (x["start"], x["end"]) == (y["start"], y["end"]):
                rel, outer = "same", None
            elif x["start"] <= y["start"] and y["end"] <= x["end"]:
                rel, outer = "contains", x.get("evidence_id")
            elif y["start"] <= x["start"] and x["end"] <= y["end"]:
                rel, outer = "contains", y.get("evidence_id")
            else:
                rel, outer = "overlaps", None
            out.append({"a": x.get("evidence_id"), "b": y.get("evidence_id"), "field": x["field"], "shared": [lo, hi], "relation": rel, "outer": outer})
    return out


# ---- review reasons ----

def review_reasons(it: dict) -> list[dict]:
    """Why an item is not (yet) usable, as stable codes with a sentence each. Empty for approved/corrected items."""
    out = []
    st = it["state"]
    if st in USABLE:
        return out
    if st == "rejected":
        return [{"code": "rejected_by_learner", "detail": "you rejected it; it stays in the history"}]
    if it["support"] == "unsupported":
        missing = [g["quote"] for g in it["groundings"] if g["status"] == "not_found"]
        out.append({"code": "unsupported_claim", "detail": "these words are not in your text: " + " | ".join(f"« {q} »" for q in missing)})
    elif it["support"] == "no_evidence":
        out.append({"code": "no_evidence", "detail": "it cites no words of your text"})
    elif it["support"] == "uncertain":
        out.append({"code": "uncertain_evidence", "detail": "a quote occurs more than once or only in the machine explanation"})
    out += [{"code": f"word_cue:{c['cue']}", "detail": c["detail"]} for c in it.get("cues", [])]
    if it.get("conflicts"):
        out.append({"code": "conflict", "detail": "another item presents as correct what this one lists as wrong (or the reverse)"})
    if it.get("paraphrases"):
        out.append({"code": "paraphrase", "detail": "it restates a quote in other words; approving it needs your attestation"})
    if st == "needs_review":
        out.append({"code": "restored_awaiting_confirmation" if it.get("review_kind") == "restored" else "changed_since_decision",
                    "detail": "its evidence came back after a revision; confirm it" if it.get("review_kind") == "restored"
                    else "it changed materially since you decided it"})
    if st == "pending" and not out:
        out.append({"code": "undecided", "detail": "supported and waiting for your decision (it can join the batch)"})
    return out


# ---- recall ----

def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", pr.fold(s).casefold()).split())


def _contains(hay: str, needle: str) -> bool:
    return bool(_norm(needle)) and f" {_norm(needle)} " in f" {_norm(hay)} "


def recall_items(unit: dict, recall: dict | None, siblings: list[str]) -> tuple[list[dict], list[dict]]:
    """(prompts, refusals) for one claim unit. ``siblings`` are the other claims' answers (recognition options)."""
    if unit["type"] != "claim" or not recall or not recall.get("answer"):
        return [], []
    ans = recall["answer"]
    refusals = []
    m = re.search(rf"(?<!\w){re.escape(ans)}(?!\w)", unit["text"], re.I)
    if not m:
        return [], [{"code": "answer_not_in_claim", "detail": f"« {ans} » is not a word of the claim, so no cloze can be made from it"}]
    prompt = unit["text"][:m.start()] + "___" + unit["text"][m.end():]
    support = [e["evidence_id"] for e in unit["evidence"] if e.get("verified") and _contains(e["quote"], ans)]
    if not support:
        refusals.append({"code": "answer_not_in_evidence", "detail": f"« {ans} » occurs in none of the claim's own evidence spans"})
    accepted = sorted({ans, *recall.get("accepted", [])}, key=lambda s: (len(s), s))
    if any(_contains(prompt, a) for a in accepted):
        refusals.append({"code": "prompt_reveals_answer", "detail": "the prompt still shows the answer (or an accepted variant)"})
    if refusals:
        return [], refusals
    rid = "rc-" + pr.sha("\x1f".join((unit["unit_id"], prompt, ans)))[:12]
    ev = next(e for e in unit["evidence"] if e["evidence_id"] == support[0])
    link = {k: ev[k] for k in ("evidence_id", "evidence_key", "field", "start", "end", "source_revision") if k in ev}
    base = {"unit_id": unit["unit_id"], "claim_key": unit["claim_key"], "prompt": prompt, "answer": ans, "accepted": accepted,
            "supported_by": support[0], "evidence_ids": support, "source_link": link}
    out = [{"recall_id": rid, "kind": "free_recall", "measures": "recall without options", **base}]
    opts = sorted({ans, *[s for s in siblings if s and _norm(s) != _norm(ans)]}, key=str.casefold)
    if len(opts) >= 2:
        out.append({"recall_id": "rr-" + rid[3:], "kind": "recognition", "measures": "recognition among the source's answers", **base,
                    "options": opts})
    return out, []


# ---- export ----

def export(res: dict, sources: dict, include_source_text: bool = False) -> dict:
    """Units of the current revision. ``sources`` maps revision -> source document."""
    rev = res["source"]["revision"]
    src = sources[rev]
    sid = src["source_id"]
    ev = {e["evidence_id"]: e for e in res["evidence"]}
    props = {i["ref"]: i for i in src["proposal"]["items"]}
    units = []
    for it in sorted(res["items"], key=lambda i: i["item_id"]):
        evidence = []
        for eid in it["evidence_ids"]:
            e = ev[eid]
            row = {k: e[k] for k in ("evidence_id", "status", "quote", "source_revision") if k in e}
            if e["status"] == "located":
                text = field_text(sources[e["source_revision"]], e["field"])
                row.update({"field": e["field"], "start": e["start"], "end": e["end"], "verified": text[e["start"]:e["end"]] == e["quote"],
                            "evidence_key": evidence_key(sid, e["field"], e["quote"], text.count(e["quote"], 0, e["start"]))})
            else:
                row["verified"] = False
            evidence.append(row)
        reasons = review_reasons(it)
        units.append({"unit_id": it["item_id"], "claim_key": claim_key(sid, it), "type": it["type"], "origin": it["origin"],
                      **({"canonical": it["content"]["canonical"]} if it["content"].get("canonical") else {}),
                      "text": it.get("effective", it["content"])[pr.MAIN_TEXT[it["type"]]],
                      "proposed_text": it["content"][pr.MAIN_TEXT[it["type"]]], "state": it["state"], "support": it["support"],
                      "needs_review": bool(reasons), "review_reasons": reasons, "evidence": evidence, "item_hash": it["item_hash"],
                      "proposal_ref": it["proposal_ref"]})
    groups = {}
    for u in units:
        if u["type"] == "claim" and u["state"] != "rejected":
            groups.setdefault(("key", u["claim_key"]), []).append(u["unit_id"])
            groups.setdefault(("text", _norm(u["text"])), []).append(u["unit_id"])
    dups = sorted({tuple(sorted(set(v))) for v in groups.values() if len(set(v)) > 1})
    for u in units:
        others = sorted({x for g in dups if u["unit_id"] in g for x in g} - {u["unit_id"]})
        if others:
            u["duplicate_of"] = others
            u["review_reasons"].append({"code": "ambiguous_duplicate", "detail": "another claim has the same canonical or the same words: "
                                        + ", ".join(others) + "; keep one, or say why both are needed"})
            u["needs_review"] = True
    answers = {u["unit_id"]: (props.get(u["proposal_ref"], {}).get("recall") or {}).get("answer") for u in units}
    recall, refused = [], []
    for u in units:
        if u["state"] not in USABLE:
            continue
        sib = [a for k, a in answers.items() if k != u["unit_id"] and a]
        got, why = recall_items(u, props.get(u["proposal_ref"], {}).get("recall"), sib)
        for r in got:
            r["source_link"] = {"source_id": sid, "fingerprint": source_fingerprint(src), **r["source_link"]}
        recall += got
        refused += [{"unit_id": u["unit_id"], **w} for w in why]
    spans = [{"evidence_id": e["evidence_id"], "field": e["field"], "start": e["start"], "end": e["end"]}
             for e in {x["evidence_id"]: x for u in units for x in u["evidence"] if "start" in x}.values()]
    doc = {"schema": SCHEMA, "source": {"source_id": sid, "revision": rev, "revision_sha256": res["source"]["revision_sha256"],
                                        "fingerprint": source_fingerprint(src), "run_key": run_key(src), "draft_id": res["draft_id"], **meta(src)},
           "drafter": pr.DRAFTER, "units": units, "recall": recall, "recall_refused": refused, "span_overlaps": overlaps(spans),
           "ambiguous_duplicates": [list(g) for g in dups],
           "counts": {"units": len(units), "usable": sum(1 for u in units if u["state"] in USABLE),
                      "needs_review": sum(1 for u in units if u["needs_review"]), "recall": len(recall)},
           "source_text_included": include_source_text}
    if include_source_text:
        doc["source_text"] = {f: src["capture"][f] for f in pr.LEARNER_FIELDS}
    return doc


def verify(units_doc: dict, src: dict) -> list[str]:
    """Independent check of a units file against its source file: fingerprint, every span's words, recall support."""
    out = []
    if units_doc.get("schema") != SCHEMA:
        return [f"not a {SCHEMA} document"]
    if units_doc["source"]["fingerprint"] != source_fingerprint(src):
        out.append("the source fingerprint differs: this is not the text the units were made from")
    for u in units_doc["units"]:
        for e in u["evidence"]:
            if "start" not in e:
                continue
            try:
                check_span(src, {"field": e["field"], "start": e["start"], "end": e["end"], "quote": e["quote"]})
            except UnitError as x:
                if e["source_revision"] == src.get("revision"):
                    out.append(f"{u['unit_id']} {e['evidence_id']}: {x}")
    byid = {e["evidence_id"]: e for u in units_doc["units"] for e in u["evidence"]}
    for r in units_doc["recall"]:
        e = byid.get(r["supported_by"])
        if not e or not _contains(e["quote"], r["answer"]):
            out.append(f"{r['recall_id']}: the answer is not in the span it names")
        if any(_contains(r["prompt"], a) for a in r["accepted"]):
            out.append(f"{r['recall_id']}: the prompt shows the answer")
    return out


def inspect_md(units_doc: dict, src: dict) -> str:
    """One section per unit: the claim, then each span shown in place in the learner's own text, with offsets."""
    s = units_doc["source"]
    L = [f"# Units of {s['source_id']} r{s['revision']} ({s['subject']}, {s['language']})", "",
         f"Fingerprint `{s['fingerprint']}`, run key `{s['run_key']}`, draft `{s['draft_id']}`. Check: "
         f"`python3 -B -m flh_extraction.units inspect --units UNITS.json --source SOURCE.json`.", ""]
    for u in units_doc["units"]:
        L += [f"## {u['unit_id']} ({u['type']}, {u['state']}, {u['support']})", "", u["text"], ""]
        for e in u["evidence"]:
            if "start" in e:
                t = field_text(src, e["field"]) if e["source_revision"] == src.get("revision") else None
                shown = (t[max(0, e["start"] - 30):e["start"]] + "[" + t[e["start"]:e["end"]] + "]" + t[e["end"]:e["end"] + 30]) if t else e["quote"]
                L.append(f"- {e['evidence_id']} {e['field']}[{e['start']}:{e['end']}] verified {e['verified']}: …{shown}…")
            else:
                L.append(f"- {e['evidence_id']} {e['status']}: « {e['quote']} »")
        if u["review_reasons"]:
            L.append("- needs review: " + "; ".join(f"{r['code']} ({r['detail']})" for r in u["review_reasons"]))
        for r in (x for x in units_doc["recall"] if x["unit_id"] == u["unit_id"]):
            L.append(f"- recall {r['recall_id']} ({r['kind']}): {r['prompt']}" + (f"  options: {' | '.join(r['options'])}" if r.get("options") else "")
                     + f"  answer in {r['supported_by']}")
        L.append("")
    if units_doc["span_overlaps"]:
        L += ["Overlapping spans (kept apart):", ""] + [f"- {o['a']} and {o['b']}: {o['relation']}, shared {o['shared']}" for o in units_doc["span_overlaps"]]
    return "\n".join(L) + "\n"


# ---- correction path and contradictions ----

def correction_path(units_doc: dict, recall_id: str, work: str = "WORK") -> dict:
    """From a recall prompt back to the exact words it rests on, and the two ways to correct it: the learner's edit of
    the unit (a decision; the source is untouched) or a new revision of the source text. Nothing is applied here."""
    r = next((x for x in units_doc["recall"] if x["recall_id"] == recall_id), None)
    if r is None:
        raise UnitError(f"no recall prompt {recall_id}")
    u = next(x for x in units_doc["units"] if x["unit_id"] == r["unit_id"])
    ev = [e for e in u["evidence"] if e["evidence_id"] in r["evidence_ids"]]
    return {"recall_id": recall_id, "unit_id": u["unit_id"], "claim": u["text"], "source": units_doc["source"]["source_id"],
            "revision": units_doc["source"]["revision"], "fingerprint": units_doc["source"]["fingerprint"],
            "evidence": [{k: e[k] for k in ("evidence_id", "evidence_key", "field", "start", "end", "quote") if k in e} for e in ev],
            "if_the_claim_is_wrong": f"python3 -B -m flh_extraction practice2 decide --work {work} --item {u['unit_id']} --edit \"CORRECTED TEXT\" --reason \"…\"",
            "if_the_source_is_wrong": f"edit the source text, raise its revision, then: python3 -B -m flh_extraction practice2 revise --source NEW.json --work {work}",
            "rule": "a correction is the learner's: it never invents a source claim and never changes the source by itself"}


TOPIC = re.compile(r"^\s*(?P<topic>[^=]+?)\s*=\s*(?P<value>.+?)\s*$")


def contradictions(exports: list[dict]) -> list[dict]:
    """Claims whose ``canonical`` reads ``TOPIC = VALUE`` and that give one topic different values, across or within
    sources. Each side keeps its own evidence trail; none is chosen. Deterministic order."""
    by = {}
    for d in exports:
        s = d["source"]
        for u in d["units"]:
            if u["type"] != "claim" or u["state"] == "rejected":
                continue
            m = TOPIC.match(u.get("canonical", "") or "")
            if not m:
                continue
            by.setdefault(_norm(m.group("topic")), []).append({
                "source_id": s["source_id"], "revision": s["revision"], "fingerprint": s["fingerprint"], "unit_id": u["unit_id"], "state": u["state"],
                "value": m.group("value"), "claim": u["text"],
                "evidence": [{k: e[k] for k in ("evidence_id", "evidence_key", "field", "start", "end", "quote", "verified") if k in e} for e in u["evidence"]]})
    out = []
    for topic, sides in sorted(by.items()):
        if len({_norm(x["value"]) for x in sides}) > 1:
            out.append({"topic": topic, "values": sorted({x["value"] for x in sides}),
                        "sides": sorted(sides, key=lambda x: (x["source_id"], x["unit_id"])),
                        "status": "needs_review", "rule": "both evidence trails are shown; the system does not pick a side"})
    return out


VOCAB = "flh_vocabulary_reference_v1"


def vocabulary_reference(units_doc: dict) -> dict:
    """Usable claims whose canonical reads ``TERM = VALUE``, as term entries: the definition is the reviewed claim,
    with its evidence link and recall prompts. A reference fixture for a vocabulary consumer; nothing is inferred."""
    s = units_doc["source"]
    rec = {}
    for r in units_doc["recall"]:
        rec.setdefault(r["unit_id"], []).append({k: r[k] for k in ("recall_id", "kind", "prompt") if k in r})
    out = []
    for u in units_doc["units"]:
        m = TOPIC.match(u.get("canonical", "") or "")
        if u["type"] != "claim" or u["state"] not in USABLE or not m:
            continue
        ev = [e for e in u["evidence"] if e.get("verified")]
        out.append({"term": m.group("topic"), "value": m.group("value"), "definition": u["text"], "unit_id": u["unit_id"],
                    "evidence": [{k: e[k] for k in ("evidence_id", "evidence_key", "field", "start", "end", "quote") if k in e} for e in ev],
                    "recall": rec.get(u["unit_id"], [])})
    return {"schema": VOCAB, "source": {k: s[k] for k in ("source_id", "revision", "fingerprint", "subject", "language")},
            "entries": sorted(out, key=lambda x: (x["term"].casefold(), x["unit_id"])),
            "note": "reviewed claims only; every definition cites the learner's own words"}


# ---- review inbox ----

INBOX = "flh_review_inbox_v1"
PRIORITY = ("conflict", "ambiguous_duplicate", "unsupported_claim", "changed_since_decision", "restored_awaiting_confirmation", "uncertain_evidence",
            "word_cue", "paraphrase", "no_evidence", "undecided")


def _prio(reasons: list[dict]) -> int:
    codes = [r["code"].split(":")[0] for r in reasons]
    return min((PRIORITY.index(c) for c in codes if c in PRIORITY), default=len(PRIORITY))


def inbox(units_doc: dict) -> dict:
    """What waits for the learner, most urgent first, with the reason codes and the cited words only (no full text)."""
    todo, decided = [], []
    for u in units_doc["units"]:
        row = {"unit_id": u["unit_id"], "claim_key": u["claim_key"], "type": u["type"], "text": u["text"], "state": u["state"], "support": u["support"],
               "reasons": u["review_reasons"], "evidence": [{k: e[k] for k in ("evidence_id", "status", "quote", "field", "start", "end") if k in e}
                                                             for e in u["evidence"]]}
        if u["state"] == "rejected":
            decided.append(row)
        elif u["needs_review"]:
            todo.append({**row, "priority": _prio(u["review_reasons"])})
    todo.sort(key=lambda r: (r["priority"], r["unit_id"]))
    counts = {}
    for r in todo:
        for x in r["reasons"]:
            counts[x["code"].split(":")[0]] = counts.get(x["code"].split(":")[0], 0) + 1
    s = units_doc["source"]
    doc = {"schema": INBOX, "source": {k: s[k] for k in ("source_id", "revision", "fingerprint", "run_key", "subject", "language", "data_scope")},
           "to_review": todo, "rejected": decided, "reason_counts": dict(sorted(counts.items())), "priority_order": list(PRIORITY),
           "note": "quotes are the learner's own cited words; the full text is never in an inbox"}
    from . import packet as pk
    doc["privacy_findings"] = len(pk.privacy_findings(pr.canon(doc)))
    return doc


# ---- revision comparison ----

def _ekeys(doc: dict) -> dict:
    """evidence_key -> evidence row (located evidence only; unlocated rows keep their offset-free evidence ID as key)."""
    out = {}
    for u in doc["units"]:
        for e in u["evidence"]:
            out.setdefault(e.get("evidence_key") or e["evidence_id"], e)
    return out


def compare(old: dict, new: dict) -> dict:
    """Machine-readable comparison of two unit exports of one source (any revisions). Deterministic: rows are sorted
    by claim key, lists by value, and nothing depends on input order or time."""
    if old["source"]["source_id"] != new["source"]["source_id"]:
        raise UnitError("compare two exports of the same source")

    def by_key(doc):
        g = {}
        for u in doc["units"]:
            g.setdefault(u["claim_key"], []).append(u)
        return {k: sorted(v, key=lambda u: u["unit_id"]) for k, v in g.items()}
    o, n = by_key(old), by_key(new)
    ok, nk = _ekeys(old), _ekeys(new)
    keyed = lambda u: sorted(e.get("evidence_key") or e["evidence_id"] for e in u["evidence"])  # noqa: E731
    rows = []

    def pair(k, a, b):
        if a and not b:
            rows.append({"claim_key": k, "change": "removed", "unit_before": a["unit_id"], "state_before": a["state"], "text_before": a["text"]})
            return
        if b and not a:
            rows.append({"claim_key": k, "change": "added", "unit_after": b["unit_id"], "state_after": b["state"], "text_after": b["text"]})
            return
        ka, kb = set(keyed(a)), set(keyed(b))
        if a["unit_id"] == b["unit_id"] and a["item_hash"] == b["item_hash"]:
            ch = "state_changed" if a["state"] != b["state"] else "unchanged"
        elif a["text"] != b["text"] or a["unit_id"] != b["unit_id"]:
            ch = "prose_edit"
        else:
            ch = "evidence_changed"
        if ch == "unchanged" and ka != kb:
            ch = "evidence_changed"
        rows.append({"claim_key": k, "change": ch, "unit_before": a["unit_id"], "unit_after": b["unit_id"], "state_before": a["state"],
                     "state_after": b["state"], "evidence_added": sorted(kb - ka), "evidence_removed": sorted(ka - kb),
                     **({"text_before": a["text"], "text_after": b["text"]} if a["text"] != b["text"] else {})})
    for k in sorted(set(o) | set(n)):
        A, B = list(o.get(k, [])), list(n.get(k, []))
        for u in [x for x in A if any(y["unit_id"] == x["unit_id"] for y in B)]:  # same unit on both sides first
            v = next(y for y in B if y["unit_id"] == u["unit_id"])
            A.remove(u)
            B.remove(v)
            pair(k, u, v)
        for i in range(max(len(A), len(B))):  # then the rest in unit-ID order
            pair(k, A[i] if i < len(A) else None, B[i] if i < len(B) else None)
    moved = sorted(({"evidence_key": key, "from": [ok[key].get("field"), ok[key].get("start"), ok[key].get("end")],
                     "to": [nk[key].get("field"), nk[key].get("start"), nk[key].get("end")], "evidence_id_before": ok[key]["evidence_id"],
                     "evidence_id_after": nk[key]["evidence_id"]}
                    for key in set(ok) & set(nk) if ok[key].get("start") != nk[key].get("start")), key=lambda m: m["evidence_key"])
    return {"schema": COMPARE, "source_id": new["source"]["source_id"], "from": {k: old["source"][k] for k in ("revision", "fingerprint", "run_key")},
            "to": {k: new["source"][k] for k in ("revision", "fingerprint", "run_key")}, "identical_rerun": old["source"]["run_key"] == new["source"]["run_key"],
            "same_text": old["source"]["fingerprint"] == new["source"]["fingerprint"], "claims": rows,
            "evidence": {"kept": sorted(set(ok) & set(nk)), "added": sorted(set(nk) - set(ok)), "removed": sorted(set(ok) - set(nk)), "moved": moved},
            "rejected_kept": sorted(u["unit_id"] for u in new["units"] if u["state"] == "rejected"),
            "ambiguous_duplicates": new.get("ambiguous_duplicates", []),
            "counts": {c: sum(1 for r in rows if r["change"] == c) for c in ("added", "removed", "prose_edit", "evidence_changed", "state_changed", "unchanged")}}


RERUN = "flh_rerun_status_v1"


def rerun_status(old: dict, new_source: dict | None, new_units: dict | None = None, error: str | None = None) -> dict:
    """Tell a vanished source from a failed extraction. ``old`` is the last good export; it is never discarded.

    * ``source_disappeared``: no new source, or none of the old evidence words are in the new text.
    * ``extractor_failed``: the text is the same (same fingerprint), but the new run gave no units or an error.
    * ``identical_rerun``: the same run key.
    * ``revised``: the text or the proposal changed and units were produced.
    """
    keep = {"kept_export": {k: old["source"][k] for k in ("revision", "fingerprint", "run_key")}, "old_units_kept": len(old["units"])}
    if new_source is None:
        return {"schema": RERUN, "status": "source_disappeared", "detail": "the source is missing or unreadable", **keep,
                "recovery": "keep the last good units (marked stale); ask the learner to restore the text or retire the source"}
    fp = source_fingerprint(new_source)
    quotes = [e["quote"] for u in old["units"] for e in u["evidence"] if e.get("status") == "located"]
    text = " ".join(field_text(new_source, f) for f in pr.LEARNER_FIELDS)
    found = sum(1 for q in quotes if q in text)
    if quotes and found == 0:
        return {"schema": RERUN, "status": "source_disappeared", "detail": f"none of the {len(quotes)} cited passages is in the new text", **keep,
                "recovery": "the units stay with their old revision; review each one against the new text, or restore the passage"}
    if fp == old["source"]["fingerprint"] and (error or not new_units or not new_units.get("units")):
        return {"schema": RERUN, "status": "extractor_failed", "detail": error or "the extraction produced no units for unchanged text", **keep,
                "recovery": "nothing about the source changed: keep the last good units and rerun the extraction; never replace them with an empty result"}
    if error or new_units is None:
        return {"schema": RERUN, "status": "extractor_failed", "detail": error or "no new units", "source_changed": True, **keep,
                "recovery": "the text changed and the extraction failed: keep the last good units marked as from the older revision; rerun"}
    st = "identical_rerun" if new_units["source"]["run_key"] == old["source"]["run_key"] else "revised"
    return {"schema": RERUN, "status": st, "passages_still_present": f"{found}/{len(quotes)}", **keep}


# ---- CLI ----

def _work(path: str):
    from . import practice22 as p22
    w = p22.Work2(path)
    return w.resolved(), w.sources()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="flh_extraction.units")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("export"); q.add_argument("--work", required=True); q.add_argument("--out", required=True)
    q.add_argument("--include-source-text", action="store_true")
    q = sub.add_parser("inspect"); q.add_argument("--units", required=True); q.add_argument("--source", required=True); q.add_argument("--md")
    q = sub.add_parser("compare"); q.add_argument("--old", required=True); q.add_argument("--new", required=True); q.add_argument("--json")
    q = sub.add_parser("inbox"); q.add_argument("--units", required=True); q.add_argument("--out", required=True)
    q = sub.add_parser("validate"); q.add_argument("--units", required=True)
    q = sub.add_parser("convert", help="read a v1 or v2 source and write the v1 the normal pipeline reads; refused items listed")
    q.add_argument("--source", required=True); q.add_argument("--out", required=True); q.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "export":
            res, srcs = _work(a.work)
            doc = export(res, srcs, a.include_source_text)
            write_atomic(a.out, pr.dumps(doc))
            print(f"wrote {doc['counts']['units']} units, {doc['counts']['recall']} recall prompts ({doc['source']['run_key']})")
            return 0
        if a.cmd == "inspect":
            with open(a.units, encoding="utf-8") as fh:
                ud = json.load(fh)
            with open(a.source, encoding="utf-8") as fh:
                src = json.load(fh)
            issues = verify(ud, src)
            md = inspect_md(ud, src)
            if a.md:
                write_atomic(a.md, md)
            else:
                sys.stdout.write(md)
            print("verify: " + ("ok" if not issues else "; ".join(issues)), file=sys.stderr)
            return 0 if not issues else 1
        if a.cmd == "validate":
            with open(a.units, encoding="utf-8") as fh:
                issues = validate_units(json.load(fh))
            print("validate: " + ("ok" if not issues else "; ".join(issues)))
            return 0 if not issues else 1
        if a.cmd == "convert":
            with open(a.source, encoding="utf-8") as fh:
                v1, info = read_source(json.load(fh), a.strict)
            write_atomic(a.out, pr.dumps(v1))
            print(f"read version {info['version']} ({info['subject']}, {info['language']}); {len(v1['proposal']['items'])} items kept"
                  + "".join(f"; refused {r['ref']}: {r['code']}" for r in info["refused_items"]))
            return 0
        if a.cmd == "inbox":
            with open(a.units, encoding="utf-8") as fh:
                doc = inbox(json.load(fh))
            if doc["privacy_findings"]:
                raise UnitError("the inbox would carry private data; it is not written")
            write_atomic(a.out, pr.dumps(doc))
            print(f"wrote {len(doc['to_review'])} items to review, {len(doc['rejected'])} rejected")
            return 0
        with open(a.old, encoding="utf-8") as fh:
            old = json.load(fh)
        with open(a.new, encoding="utf-8") as fh:
            new = json.load(fh)
        rep = compare(old, new)
        text = pr.dumps(rep)
        if a.json:
            write_atomic(a.json, text)
        else:
            sys.stdout.write(text)
        return 0
    except (UnitError, OSError, ValueError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
