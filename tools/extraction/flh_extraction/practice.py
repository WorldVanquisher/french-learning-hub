"""Extraction 2.0 prototype (PROTOTYPE, offline, standard library only): from one French
question and its evidence to knowledge the learner approves, then to practice.

  source (flh_practice_source_v1)  ->  draft (flh_practice_draft_v1)
      -> learner decisions (flh_practice_decision_v1, append-only JSONL)
      -> resolved knowledge -> practice (flh_practice_items_v1) -> attempts (flh_practice_attempt_v1)

* A **source** is a ``learning_capture_v1``-shaped question, an optional learner goal,
  and a **proposal**: claims, contrasts, worked examples and common errors written by a
  proposer. In this lane the proposer is a hand-written synthetic fixture; nothing calls a
  provider. Each proposed item cites **quotes**: exact words of the source that support it.
* The **draft** grounds every quote against the learner's own text (original input and
  context), as Writing v1 grounds feedback: ``located`` (exactly once, with a position),
  ``ambiguous`` (repeated, no position), ``explanation_only`` (only in the machine
  explanation shown to the learner) or ``not_found``. An item is ``supported``,
  ``uncertain``, ``unsupported`` or ``generated`` (a new practice example the source never
  claimed). The existing heuristic (``evidence_review``) is recorded beside it.
* IDs are stable: an item ID hashes the source ID, the type and the item's content key,
  never the revision, so an unchanged item keeps its ID when the source is revised.
  Evidence IDs hash the source ID, field, quote and occurrence. Every evidence entry names
  the source revision it was located in.
* **Decisions** belong to the learner: approve, reject, or edit (a learner correction,
  kept beside the proposed text). Each one records the item hash it was made on. When
  the source is revised, a decision carries forward only while the item hash (its content
  and the grounding status of each quote) is unchanged; otherwise the item asks for review again.
* **Practice** is built from approved items only: explain from memory (self-check),
  choose between confusable forms (exact), and produce an answer in a new sentence
  (accepted variants; anything else is a self-check, a listed common error is incorrect).
  Answers, explanations and excerpts stay hidden until an attempt or an explicit reveal.

* **Batch review** (Extraction 2.1) groups the pending items: the ones whose every quote
  is located (``supported``) or that are new practice examples (``generated``) can be
  approved together under a batch ID that hashes exactly those items and their hashes;
  everything else (unsupported, uncertain, no evidence, changed since a decision) is
  listed apart and is never in a batch. A batch approval writes one ordinary learner
  decision per item, so evidence links and later revisions behave exactly as before.

Nothing here changes FLH's database, routes or providers.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

from . import evidence_review
from .textnorm import norm

SOURCE_SCHEMA = "flh_practice_source_v1"
DRAFT_SCHEMA = "flh_practice_draft_v1"
DECISION_SCHEMA = "flh_practice_decision_v1"
PRACTICE_SCHEMA = "flh_practice_items_v1"
ATTEMPT_SCHEMA = "flh_practice_attempt_v1"
DRAFTER = "flh_practice_drafter_v1"
TYPES = ("claim", "contrast", "worked_example", "common_error")
LEARNER_FIELDS = ("original_input", "original_context")
MAIN_TEXT = {"claim": "statement", "contrast": "distinction", "worked_example": "explanation", "common_error": "why"}
REQUIRED = {"claim": ("statement",), "contrast": ("a", "b", "distinction"),
            "worked_example": ("question", "answer", "explanation"), "common_error": ("wrong", "right", "why")}
ACTIONS = ("approve", "reject", "edit")
BATCH_SCHEMA = "flh_practice_batch_review_v1"
BATCH_SUPPORT = ("supported", "generated")
EXCERPT = 30
_APOS = str.maketrans({"’": "'", "‘": "'", "ʼ": "'"})


def fold(s: str) -> str:
    """The text evidence is located in: NFC, apostrophe variants unified (offsets index this text)."""
    return unicodedata.normalize("NFC", s or "").translate(_APOS)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


# ---- source ----

def validate_source(src: dict) -> None:
    if not isinstance(src, dict) or src.get("schema") != SOURCE_SCHEMA:
        raise ValueError(f"a source must be {SOURCE_SCHEMA}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", str(src.get("source_id", ""))):
        raise ValueError("source_id: 2-64 lowercase letters, digits or hyphens")
    if not isinstance(src.get("revision"), int) or src["revision"] < 1:
        raise ValueError("revision must be an integer >= 1")
    cap = src.get("capture") or {}
    if cap.get("schema_version") != "learning_capture_v1" or not all(isinstance(cap.get(f), str) for f in LEARNER_FIELDS):
        raise ValueError("capture must be learning_capture_v1 with original_input and original_context")
    items = (src.get("proposal") or {}).get("items")
    if not isinstance(items, list):
        raise ValueError("proposal.items must be a list")
    refs = set()
    for k, it in enumerate(items):
        t = it.get("type")
        if t not in TYPES:
            raise ValueError(f"proposal item {k}: type must be one of {TYPES}")
        for f in REQUIRED[t]:
            if not it.get(f):
                raise ValueError(f"proposal item {k} ({t}) needs {f!r}")
        if not isinstance(it.get("ref"), str) or it["ref"] in refs:
            raise ValueError(f"proposal item {k}: a unique string 'ref' is required")
        refs.add(it["ref"])
        if not isinstance(it.get("quotes", []), list):
            raise ValueError(f"proposal item {k}: quotes must be a list")
    for k, it in enumerate(items):
        for r in it.get("applies", []):
            if r not in refs:
                raise ValueError(f"proposal item {k}: applies to unknown ref {r!r}")


def revision_sha256(src: dict) -> str:
    return sha(canon({"capture": src["capture"], "proposal": src["proposal"], "learner_goal": src.get("learner_goal", "")}))


def source_text(src: dict) -> str:
    return " ".join(fold(src["capture"][f]) for f in LEARNER_FIELDS)


# ---- draft ----

def ground(src: dict, quote: str) -> dict:
    """Where one quote occurs in the learner's own text, or why it does not."""
    q = fold(quote)
    hits = []
    for f in LEARNER_FIELDS:
        t = fold(src["capture"][f])
        i = t.find(q)
        while q and i >= 0:
            hits.append((f, i, i + len(q), t))
            i = t.find(q, i + 1)
    expl = fold((src["capture"].get("analysis") or {}).get("explanation", ""))
    if len(hits) == 1:
        f, a, b, t = hits[0]
        return {"quote": q, "status": "located", "field": f, "start": a, "end": b, "excerpt": _excerpt(t, a, b)}
    if hits:
        return {"quote": q, "status": "ambiguous", "occurrences": [{"field": f, "start": a, "end": b} for f, a, b, _ in hits],
                "excerpt": q, "note": f"the quote occurs {len(hits)} times; no single position supports it"}
    if q and q in expl:
        a = expl.find(q)
        return {"quote": q, "status": "explanation_only", "field": "analysis_explanation", "excerpt": _excerpt(expl, a, a + len(q)),
                "note": "only the machine explanation contains it: the learner did not write it"}
    return {"quote": q, "status": "not_found", "note": "these words are not in the learner's question or context"}


def _excerpt(t: str, a: int, b: int) -> str:
    lo, hi = max(0, a - EXCERPT), min(len(t), b + EXCERPT)
    return ("…" if lo else "") + t[lo:a] + "[" + t[a:b] + "]" + t[b:hi] + ("…" if hi < len(t) else "")


def content_of(it: dict) -> dict:
    keep = {"claim": ("statement", "statement_zh", "kind", "canonical"), "contrast": ("a", "b", "distinction"),
            "worked_example": ("question", "answer", "accepted", "wrong", "cloze", "choices", "target", "explanation", "instruction"),
            "common_error": ("wrong", "right", "why")}[it["type"]]
    return {k: it[k] for k in keep if k in it}


def content_key(t: str, c: dict) -> str:
    if t == "claim":
        return norm(c["statement"])
    if t == "contrast":
        return f"{norm(c['a']['form'])}|{norm(c['b']['form'])}"
    if t == "worked_example":
        return f"{norm(c['question'])}|{norm(c['answer'])}"
    return f"{norm(c['wrong'])}|{norm(c['right'])}"


def item_support(t: str, groundings: list[dict], generated: bool) -> str:
    st = [g["status"] for g in groundings]
    if generated and not st:
        return "generated"
    if not st:
        return "no_evidence"
    if "not_found" in st:
        return "unsupported"
    return "supported" if all(s == "located" for s in st) else "uncertain"


def heuristic(src: dict, it: dict) -> str | None:
    """The existing evidence_review class for a claim (lexical anchoring), for comparison."""
    if it["type"] != "claim":
        return None
    ref = {"id": src["source_id"], "input": {**{f: src["capture"][f] for f in LEARNER_FIELDS},
                                            "effective_explanation": (src["capture"].get("analysis") or {}).get("explanation", "")}}
    unit = {"kind": it.get("kind", "grammar"), "canonical": it.get("canonical", ""), "statement": it["statement"],
            "statement_zh": it.get("statement_zh", ""), "example": "", "confidence": it.get("confidence", 0.5)}
    rec = evidence_review.review_record(ref, {"units": [unit]})
    return rec["units"][0]["cls"] if rec.get("units") else rec.get("class")


def draft(src: dict) -> dict:
    """The deterministic draft: the same source gives byte-identical output."""
    validate_source(src)
    sid, rev = src["source_id"], src["revision"]
    text = source_text(src)
    evidence, items, ids_by_ref = {}, [], {}
    for it in src["proposal"]["items"]:
        c = content_of(it)
        iid = "k-" + sha(f"{sid}\x1f{it['type']}\x1f{content_key(it['type'], c)}")[:12]
        ids_by_ref[it["ref"]] = iid
    for it in src["proposal"]["items"]:
        c, groundings, ev_ids = content_of(it), [], []
        for q in it.get("quotes", []):
            g = ground(src, q)
            if g["status"] in ("located", "ambiguous", "explanation_only"):
                occ = g.get("start", "*") if g["status"] == "located" else "*"
                eid = "ev-" + sha(f"{sid}\x1f{g.get('field', 'multiple')}\x1f{g['quote']}\x1f{occ}")[:10]
                evidence[eid] = {"evidence_id": eid, "source_id": sid, "source_revision": rev,
                                 **{k: g[k] for k in ("quote", "status", "field", "start", "end", "excerpt", "occurrences") if k in g}}
                g = {**g, "evidence_id": eid}
                ev_ids.append(eid)
            groundings.append({k: g[k] for k in ("quote", "status", "evidence_id", "note") if k in g})
        generated = bool(it.get("generated"))
        sup = item_support(it["type"], groundings, generated)
        new_sentence = None
        if it["type"] == "worked_example":
            new_sentence = not (norm(it["question"]) in norm(text) or norm(it["answer"]) in norm(text))
        iid = ids_by_ref[it["ref"]]
        h = sha(canon({"type": it["type"], "content": c, "grounding": [(g["quote"], g["status"]) for g in groundings]}))
        items.append({
            "item_id": iid, "type": it["type"], "content": c, "origin": "generated" if generated else "source",
            "support": sup, "uncertain": sup not in ("supported", "generated"), "groundings": groundings, "evidence_ids": ev_ids,
            "applies": [ids_by_ref[r] for r in it.get("applies", [])], "heuristic_class": heuristic(src, it),
            "new_sentence": new_sentence, "confidence": it.get("confidence"), "item_hash": h, "proposal_ref": it["ref"],
        })
    rsha = revision_sha256(src)
    return {"schema": DRAFT_SCHEMA, "drafter": DRAFTER, "draft_id": "d-" + sha(f"{sid}\x1f{rsha}\x1f{DRAFTER}")[:12],
            "source": {"source_id": sid, "revision": rev, "revision_sha256": rsha, "capture_id": src["capture"].get("capture_id"),
                       "proposer": src["proposal"].get("proposer", "")},
            "learner_goal": src.get("learner_goal", ""), "evidence": [evidence[k] for k in sorted(evidence)], "items": items,
            "counts": {s: sum(1 for i in items if i["support"] == s) for s in ("supported", "uncertain", "unsupported", "no_evidence", "generated")}}


# ---- learner decisions ----

def decision(drf: dict, item_id: str, action: str, seq: int, text: str | None = None, reason: str = "",
             batch: dict | None = None, via: dict | None = None) -> dict:
    items = {i["item_id"]: i for i in drf["items"]}
    if item_id not in items:
        raise ValueError(f"unknown item {item_id!r}")
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    if action == "edit" and not (text or "").strip():
        raise ValueError("an edit needs the corrected text")
    d = {"schema": DECISION_SCHEMA, "seq": seq, "item_id": item_id, "action": action, "reason": reason,
         "based_on": {"source_revision": drf["source"]["revision"], "item_hash": items[item_id]["item_hash"]}}
    if action == "edit":
        d["text"] = text.strip()
    if batch:
        d["batch"] = batch
    if via:
        d["via"] = via
    return d


def read_decisions(lines) -> list[dict]:
    out, seqs = [], set()
    for k, line in enumerate(lines, 1):
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("schema") != DECISION_SCHEMA or d.get("action") not in ACTIONS or not isinstance(d.get("seq"), int) or d["seq"] in seqs:
            raise ValueError(f"decision line {k}: not a valid {DECISION_SCHEMA} record (or a repeated seq)")
        seqs.add(d["seq"])
        out.append(d)
    return sorted(out, key=lambda d: d["seq"])


def resolve(drf: dict, decisions: list[dict]) -> dict:
    """Each item's state under the learner's latest decision: pending | approved | corrected | rejected | needs_review."""
    last = {}
    for d in sorted(decisions, key=lambda d: d["seq"]):
        last[d["item_id"]] = d
    rev = drf["source"]["revision"]
    items = []
    for it in drf["items"]:
        d = last.get(it["item_id"])
        r = {**it, "state": "pending", "effective": dict(it["content"])}
        if d:
            same = d["based_on"]["item_hash"] == it["item_hash"]
            carried = d["based_on"]["source_revision"] != rev
            if not same:
                r["state"] = "needs_review"
                r["review_reason"] = (f"you decided '{d['action']}' on revision {d['based_on']['source_revision']}; "
                                      f"this item's content or evidence changed in revision {rev}")
            else:
                r["state"] = {"approve": "approved", "reject": "rejected", "edit": "corrected"}[d["action"]]
                if d["action"] == "edit":
                    f = MAIN_TEXT[it["type"]]
                    r["effective"][f] = d["text"]
                    r["proposed_text"] = it["content"][f]
                if carried:
                    r["carried_from_revision"] = d["based_on"]["source_revision"]
            r["decision_seq"] = d["seq"]
            r["decided_on_revision"] = d["based_on"]["source_revision"]
            if d.get("via") and r["state"] in ("approved", "corrected"):
                r["accepted_from"] = {k: d["via"][k] for k in ("agent", "packet_id", "proposal_id") if k in d["via"]}
            if d.get("batch") and r["state"] == "approved":
                r["batch_id"] = d["batch"]["batch_id"]
        r["origin_effective"] = "learner" if r["state"] == "corrected" else it["origin"]
        items.append(r)
    out = {k: v for k, v in drf.items() if k != "items"}
    out["items"] = items
    out["states"] = {s: sum(1 for i in items if i["state"] == s) for s in ("pending", "approved", "corrected", "rejected", "needs_review")}
    return out


def approved(res: dict) -> list[dict]:
    return [i for i in res["items"] if i["state"] in ("approved", "corrected")]


# ---- batch review (Extraction 2.1) ----

def changes(old: dict, new: dict) -> list[str]:
    """What changed in one item between two drafts: content fields and each quote's grounding."""
    out = [f"{k} changed" for k in sorted(set(old["content"]) | set(new["content"])) if old["content"].get(k) != new["content"].get(k)]
    og = {g["quote"]: g["status"] for g in old["groundings"]}
    ng = {g["quote"]: g["status"] for g in new["groundings"]}
    out += [f"quote « {q} »: {og.get(q, 'absent')} in revision {old.get('_rev', '?')} -> {ng.get(q, 'absent')} now"
            for q in sorted(set(og) | set(ng)) if og.get(q) != ng.get(q)]
    return out


def _why(it: dict) -> str:
    bad = [g for g in it["groundings"] if g["status"] != "located"]
    if it["support"] == "unsupported":
        return "UNSUPPORTED: " + "; ".join(f"« {g['quote']} » is not in your question or context" for g in bad if g["status"] == "not_found")
    if it["support"] == "uncertain":
        return "UNCERTAIN: " + "; ".join(f"« {g['quote']} » " + ("occurs more than once" if g["status"] == "ambiguous" else "is only in the machine explanation")
                                         for g in bad)
    if it["support"] == "no_evidence":
        return "NO EVIDENCE: the proposer cited no words of your source"
    return it["support"].upper()


def batch_review(res: dict, drafts: dict | None = None) -> dict:
    """Pending items split into one batch the learner may approve together (supported or generated)
    and the items the learner must decide one by one. ``drafts`` maps a revision number to its draft,
    to say what changed in an item decided on an earlier revision."""
    drafts = drafts or {}
    members, left, done = [], [], []
    for it in res["items"]:
        st = it["state"]
        if st == "pending" and it["support"] in BATCH_SUPPORT:
            members.append({"item_id": it["item_id"], "type": it["type"], "support": it["support"], "text": it["content"][MAIN_TEXT[it["type"]]],
                            "evidence_ids": it["evidence_ids"], "applies": it["applies"], "new_sentence": it["new_sentence"]})
        elif st in ("pending", "needs_review"):
            row = {"item_id": it["item_id"], "type": it["type"], "support": it["support"], "state": st,
                   "text": it["content"][MAIN_TEXT[it["type"]]]}
            if st == "needs_review":
                rev = it["decided_on_revision"]
                old = next((i for i in drafts.get(rev, {}).get("items", []) if i["item_id"] == it["item_id"]), None)
                row["why"] = f"CHANGED IN REVISION {res['source']['revision']}: you decided on revision {rev}; a decision carries only while the item is unchanged"
                row["changes"] = changes({**old, "_rev": rev}, it) if old else ["the earlier draft is not in this work directory"]
            else:
                row["why"] = _why(it)
            left.append(row)
        else:
            done.append({"item_id": it["item_id"], "state": st, **({"carried_from_revision": it["carried_from_revision"]} if it.get("carried_from_revision") else {})})
    bid = "b-" + sha(canon([res["draft_id"], [(m["item_id"], next(i["item_hash"] for i in res["items"] if i["item_id"] == m["item_id"])) for m in members]]))[:12] \
        if members else None
    return {"schema": BATCH_SCHEMA, "draft_id": res["draft_id"], "source": res["source"], "batch_id": bid, "members": members,
            "left_for_you": left, "already_decided": done,
            "rule": "only pending items whose every quote is located once in your text, or new practice examples, can be approved together"}


def batch_decisions(drf: dict, res: dict, batch_id: str, seq: int, except_ids=(), reason: str = "") -> list[dict]:
    """One ordinary approve decision per batch member, refused unless ``batch_id`` is the batch shown now."""
    rv = batch_review(res)
    if rv["batch_id"] is None:
        raise ValueError("nothing can be approved together: every remaining item needs its own decision")
    if batch_id != rv["batch_id"]:
        raise ValueError(f"batch {batch_id} is not the batch shown now ({rv['batch_id']}): the draft or your decisions changed; review again")
    ids = [m["item_id"] for m in rv["members"]]
    extra = sorted(set(except_ids) - set(ids))
    if extra:
        raise ValueError(f"--except names items that are not in batch {batch_id}: {', '.join(extra)}")
    chosen = [i for i in ids if i not in set(except_ids)]
    if not chosen:
        raise ValueError("every batch member was excepted: nothing to approve")
    meta = {"batch_id": batch_id, "size": len(chosen), "excepted": sorted(set(except_ids))}
    return [decision(drf, iid, "approve", seq + k, reason=reason, batch=meta) for k, iid in enumerate(chosen)]


def render_review(rv: dict) -> str:
    def short(t):
        return t if len(t) <= 90 else t[:89] + "…"
    s = rv["source"]
    L = [f"Review of draft {rv['draft_id']} (source {s['source_id']} revision {s['revision']})", ""]
    if rv["batch_id"]:
        L.append(f"Approve together: batch {rv['batch_id']}, {len(rv['members'])} items, each shown above beside its evidence")
        for m in rv["members"]:
            ref = (f"evidence {', '.join(m['evidence_ids'])}" if m["evidence_ids"]
                   else f"new practice example; applies to {', '.join(m['applies'])}" + ("; sentence not in your source" if m["new_sentence"] else ""))
            L.append(f"  [{m['item_id']}] {m['type']:14} {m['support']:9} {ref}")
            L.append(f"      {short(m['text'])}")
        L.append(f"  -> practice decide --work W --approve-batch {rv['batch_id']}   (add --except k-… to leave one out)")
    else:
        L.append("Approve together: nothing (no pending supported item or new practice example)")
    L.append("")
    L.append(f"Decide yourself, one by one ({len(rv['left_for_you'])}): never part of a batch")
    for r in rv["left_for_you"]:
        L.append(f"  [{r['item_id']}] {r['type']:14} {r['why']}")
        L.append(f"      {short(r['text'])}")
        L += [f"      what changed: {c}" for c in r.get("changes", [])]
    if not rv["left_for_you"]:
        L.append("  (none)")
    states: dict = {}
    for d in rv["already_decided"]:
        k = d["state"] + (f" (carried from revision {d['carried_from_revision']})" if d.get("carried_from_revision") else "")
        states[k] = states.get(k, 0) + 1
    L.append("")
    L.append("Already decided: " + (", ".join(f"{k} {v}" for k, v in sorted(states.items())) or "none"))
    return "\n".join(L) + "\n"


# ---- practice ----

def build_practice(res: dict) -> dict:
    """Three practice types from approved knowledge only. Hidden fields stay under ``hidden``."""
    ok = {i["item_id"]: i for i in approved(res)}
    ev = {e["evidence_id"]: e for e in res["evidence"]}
    errors = [i for i in ok.values() if i["type"] == "common_error"]
    out = []

    def pid(*parts):
        return "p-" + sha("\x1f".join(parts))[:12]

    def excerpts(ids):
        return [{"evidence_id": e, "excerpt": ev[e]["excerpt"]} for e in ids if e in ev]

    claims = [i for i in ok.values() if i["type"] == "claim"]
    for c in (i for i in ok.values() if i["type"] == "contrast"):
        a, b = c["effective"]["a"]["form"], c["effective"]["b"]["form"]
        rel = [x for x in claims if x["item_id"] in c["applies"]] or claims
        refs = sorted({e for x in [c] + rel for e in x["evidence_ids"]})
        out.append({"practice_id": pid(c["item_id"], "explain"), "kind": "explain", "measures": "unaided recall of the rule",
                    "prompt": f"From memory, without looking: when do you use « {a} » and when « {b} »? Give one example of each.",
                    "knowledge_ids": [c["item_id"]] + [x["item_id"] for x in rel], "evidence_ids": refs, "new_sentence": None,
                    "grading": "self_check",
                    "hidden": {"reference": [c["effective"]["distinction"]] + [x["effective"]["statement"] for x in rel],
                               "explanation": c["effective"]["distinction"], "excerpts": excerpts(refs)}})
        for w in sorted((i for i in ok.values() if i["type"] == "worked_example" and c["item_id"] in i["applies"]), key=lambda i: i["item_id"]):
            e = w["effective"]
            refs_w = sorted(set(w["evidence_ids"]) | {x for x in c["evidence_ids"]})
            known = [x["effective"]["wrong"] for x in errors if x["item_id"] in w["applies"] or c["item_id"] in x["applies"]]
            known += list(e.get("wrong") or [])
            options = list(e.get("choices") or [a, b])
            if e.get("cloze") and e.get("target") in options:
                out.append({"practice_id": pid(w["item_id"], "choose"), "kind": "choose", "measures": "recognition between confusable forms",
                            "prompt": f"{e['question']} — {e['cloze']}", "options": options, "knowledge_ids": [w["item_id"], c["item_id"]],
                            "evidence_ids": refs_w, "new_sentence": w["new_sentence"], "grading": "exact",
                            "hidden": {"answer": e["target"], "explanation": e["explanation"], "excerpts": excerpts(refs_w)}})
            if e.get("accepted"):
                out.append({"practice_id": pid(w["item_id"], "produce"), "kind": "produce", "measures": "production in a new sentence",
                            "prompt": f"{e['question']} {e.get('instruction', '')}".strip(), "knowledge_ids": [w["item_id"], c["item_id"]],
                            "evidence_ids": refs_w, "new_sentence": w["new_sentence"], "grading": "accepted_variants_else_self_check",
                            "hidden": {"answer": e["answer"], "accepted": e["accepted"], "known_errors": sorted(set(known)),
                                       "explanation": e["explanation"], "excerpts": excerpts(refs_w)}})
    order = {"explain": 0, "choose": 1, "produce": 2}
    out.sort(key=lambda p: (order[p["kind"]], p["practice_id"]))
    return {"schema": PRACTICE_SCHEMA, "draft_id": res["draft_id"], "source": res["source"], "items": out,
            "counts": {k: sum(1 for p in out if p["kind"] == k) for k in order},
            "note": "built from approved and learner-corrected items only; hidden fields stay hidden until an attempt or reveal"}


def public(p: dict) -> dict:
    return {k: v for k, v in p.items() if k != "hidden"}


def fr_norm(s: str) -> str:
    s = fold(s).lower()
    s = re.sub(r"[.,!?;:«»\"()…]", " ", s)
    return " ".join(s.split())


def grade(p: dict, text: str) -> dict:
    """The outcome of one attempt. Exact only where the answer set is closed."""
    t = fr_norm(text)
    h = p["hidden"]
    if p["kind"] == "explain":
        return {"outcome": "self_check", "why": "free recall is never graded automatically: compare with the reference and decide"}
    if p["kind"] == "choose":
        opts = {fr_norm(o): o for o in p["options"]}
        if t not in opts:
            return {"outcome": "invalid", "why": f"choose one of {p['options']}"}
        return {"outcome": "correct" if opts[t] == h["answer"] else "incorrect", "chosen": opts[t]}
    for v in h["accepted"]:
        if t == fr_norm(v):
            return {"outcome": "correct", "matched": v}
    for w in h.get("known_errors", []):
        if fr_norm(w) and f" {fr_norm(w)} " in f" {t} ":
            return {"outcome": "incorrect", "known_error": w}
    return {"outcome": "self_check", "why": "not one of the accepted variants; it may still be correct French, so compare it with "
                                           "the reference answer and decide yourself"}


def attempt(prac: dict, practice_id: str, seq: int, text: str | None = None, reveal: bool = False) -> tuple[dict, dict]:
    """(attempt record, feedback). A reveal without an attempt is recorded as such."""
    items = {p["practice_id"]: p for p in prac["items"]}
    if practice_id not in items:
        raise ValueError(f"unknown practice item {practice_id!r}")
    p = items[practice_id]
    if reveal:
        rec = {"schema": ATTEMPT_SCHEMA, "seq": seq, "practice_id": practice_id, "action": "reveal", "outcome": "revealed"}
    else:
        if not (text or "").strip():
            raise ValueError("an attempt needs an answer (or use reveal)")
        g = grade(p, text)
        rec = {"schema": ATTEMPT_SCHEMA, "seq": seq, "practice_id": practice_id, "action": "attempt", "text": text.strip(), **g}
    return rec, {"practice_id": practice_id, "kind": p["kind"], **{k: v for k, v in rec.items() if k not in ("schema", "seq")},
                 "revealed": p["hidden"]}


# ---- rendering (text only from the JSON) ----

def render_preview(res: dict) -> str:
    """Each statement beside its evidence, with its support and the learner's state."""
    s = res["source"]
    L = [f"Draft {res['draft_id']}  source {s['source_id']} revision {s['revision']} ({s['revision_sha256'][:12]})",
         f"proposer: {s['proposer']}", f"goal: {res['learner_goal'] or '(none given)'}",
         "support: supported = every quote is in your own words exactly once; uncertain = repeated or only in the machine "
         "explanation; unsupported = a quote is not in your text; generated = a new practice example (the source never said it)", ""]
    for it in res["items"]:
        f = MAIN_TEXT[it["type"]]
        flag = f"  <-- {it['support'].upper()}: still a draft, decide explicitly" if it["uncertain"] and it.get("state", "pending") in ("pending", "needs_review") \
            else (f"  ({it['support']})" if it["uncertain"] else "")
        L.append(f"[{it['item_id']}] {it['type']}  support {it['support']}  state {it.get('state', 'pending')}"
                 + (f" (carried from revision {it['carried_from_revision']})" if it.get("carried_from_revision") else "") + flag)
        c = it.get("effective", it["content"])
        if it["type"] == "contrast":
            L.append(f"  says      « {c['a']['form']} »: {c['a'].get('use', '')} / « {c['b']['form']} »: {c['b'].get('use', '')}")
        elif it["type"] == "worked_example":
            L.append(f"  says      {c['question']} — {c['answer']}" + ("  (sentence not in your source)" if it["new_sentence"] else ""))
        elif it["type"] == "common_error":
            L.append(f"  says      not « {c['wrong']} » but « {c['right']} »")
        L.append(f"  {f:9} {c[f]}")
        if it.get("proposed_text"):
            L.append(f"  proposed  {it['proposed_text']}  (your correction replaces it; the proposal is kept)")
        ev = {x["evidence_id"]: x for x in res["evidence"]}
        for g in it["groundings"]:
            L.append(f"  evidence  {g.get('evidence_id', '-'):13} {g['status']:16} « {g['quote']} »" + (f"  {g['note']}" if g.get("note") else ""))
            if g.get("evidence_id") in ev and ev[g["evidence_id"]]["status"] != "ambiguous":
                L.append(f"            {ev[g['evidence_id']]['excerpt']}")
        if it["heuristic_class"]:
            L.append(f"  existing evidence-review heuristic: {it['heuristic_class']}")
        if it.get("review_reason"):
            L.append(f"  review    {it['review_reason']}")
        L.append("")
    if "states" in res:
        L.append("states: " + ", ".join(f"{k} {v}" for k, v in res["states"].items()))
    L.append("counts: " + ", ".join(f"{k} {v}" for k, v in res["counts"].items()))
    return "\n".join(L) + "\n"


def render_practice(prac: dict) -> str:
    L = [f"Practice for {prac['source']['source_id']} revision {prac['source']['revision']}: "
         + ", ".join(f"{k} {v}" for k, v in prac["counts"].items()), "(answers stay hidden until you answer or reveal)"]
    for p in prac["items"]:
        L.append(f"[{p['practice_id']}] {p['kind']} ({p['measures']}; grading {p['grading']})"
                 + ("  new sentence" if p["new_sentence"] else ""))
        L.append(f"  {p['prompt']}" + (f"   options: {' / '.join(p['options'])}" if p.get("options") else ""))
        L.append(f"  evidence {', '.join(p['evidence_ids'])}")
    return "\n".join(L) + "\n"


def render_feedback(fb: dict) -> str:
    h = fb["revealed"]
    head = {"correct": "correct", "incorrect": "not this time", "self_check": "check it yourself", "revealed": "revealed without an attempt",
            "invalid": "not an answer"}[fb["outcome"]]
    L = [f"[{fb['practice_id']}] {fb['kind']}: {head}" + (f"  (your answer: {fb['text']})" if fb.get("text") else "")]
    if fb.get("why"):
        L.append(f"  {fb['why']}")
    if fb.get("known_error"):
        L.append(f"  « {fb['known_error']} » is a known confusion for this item")
    if "answer" in h:
        L.append(f"  answer    {h['answer']}")
    if h.get("accepted"):
        L.append(f"  accepted  {' | '.join(h['accepted'])}")
    if h.get("reference"):
        L += [f"  reference {r}" for r in h["reference"]]
    L.append(f"  why       {h['explanation']}")
    L += [f"  source    {x['evidence_id']}: {x['excerpt']}" for x in h["excerpts"]]
    return "\n".join(L) + "\n"
