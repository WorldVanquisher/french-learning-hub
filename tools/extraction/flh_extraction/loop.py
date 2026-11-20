"""Learning loop over reviewed knowledge (R4; PROTOTYPE, offline, synthetic, standard library only).

``flh_learning_loop_v1`` is one learner's loop over one practice item built from reviewed
units. It records five kinds of event in order, append-only, each with a ``seq``:

  read     the reviewed units and their evidence, shown from the learner's own source text
  recall   an answer from memory, before anything is revealed (graded as practice grades it).
           ``retrieval`` is ``unaided``, or ``after_reading`` when the loop showed the units first
           (experiment r4-retrieval-leakage: reading first shows every explain item's reference),
           so the learner is offered recall before read
  reveal   the reference answer and the evidence it rests on; never before a recall unless
           the learner asks for it (then it is recorded as a reveal without a recall)
  retry    another answer after the reveal (same grading)
  revisit  a later return the learner starts; nothing schedules it. The loop re-checks its
           pointer against the current review: each unit, each evidence quote and the
           practice item is ``current``, ``moved``, ``changed`` (the unit needs review),
           ``rejected``, ``absent`` or ``withdrawn`` (with the feed's reason code)

**The pointer** (``pointer``) ties the exercise to what the learner approved and where it
came from. It holds:
- ``unit_ids``: the reviewed units, approved or corrected;
- for each evidence ID: the source revision, field, character span and quote.

``resolve`` slices the source revision's own text at that span. It returns the evidence only
when the words there are still the quote (``verified``). A pointer from an older revision is
still resolved against that revision's source, so the learner can always go back to what
they wrote.

**Answer retention** (``retention``) is the learner's choice:
- ``keep`` (the default, as practice attempts today) stores answer texts in the loop;
- ``discard`` stores outcomes only. Each answer is graded in memory and dropped.

Switching to ``discard`` later (``set_retention``) also removes every answer kept so far, and
a ``retention`` event records how many were removed. Feeds never carry answer texts in either
mode.

Nothing here schedules, scores mastery or calls a model. The loop document is a value: the
caller (Workbooks) decides whether and where to keep it.
"""

from __future__ import annotations

import copy

from . import feed2
from . import practice as pr

SCHEMA = "flh_learning_loop_v1"
EVENTS = ("read", "recall", "reveal", "retry", "revisit", "retention")
RETENTION = ("keep", "discard")
USABLE = ("approved", "corrected")


class LoopError(ValueError):
    pass


def _src_text(sources: dict, rev: int, field: str) -> str:
    return pr.fold(sources[rev]["capture"][field])


def pointer(res: dict, prac: dict, practice_id: str) -> dict:
    """The exercise's pointer back to its reviewed units and their evidence (refused if a unit is not approved)."""
    p = next((x for x in prac["items"] if x["practice_id"] == practice_id), None)
    if p is None:
        raise LoopError(f"{practice_id} is not offered in revision {res['source']['revision']}")
    states = {i["item_id"]: i for i in res["items"]}
    bad = [k for k in p["knowledge_ids"] if states.get(k, {}).get("state") not in USABLE]
    if bad:
        raise LoopError(f"{practice_id} rests on units that are not approved: {bad}")
    ev = {e["evidence_id"]: e for e in res["evidence"]}
    evidence = []
    for eid in p["evidence_ids"]:
        e = ev.get(eid)
        if e and e["status"] == "located":
            evidence.append({k: e[k] for k in ("evidence_id", "source_id", "source_revision", "field", "start", "end", "quote")})
    return {"practice_id": practice_id, "kind": p["kind"], "unit_ids": list(p["knowledge_ids"]), "evidence": evidence,
            "source": {k: res["source"][k] for k in ("source_id", "revision", "revision_sha256")}}


def resolve(ptr: dict, sources: dict) -> list[dict]:
    """Each evidence entry with the learner's words sliced from its own revision; ``verified`` when they equal the quote."""
    out = []
    for e in ptr["evidence"]:
        text = _src_text(sources, e["source_revision"], e["field"]) if e["source_revision"] in sources else None
        words = text[e["start"]:e["end"]] if text is not None else None
        lo, hi = (max(0, e["start"] - pr.EXCERPT), min(len(text), e["end"] + pr.EXCERPT)) if text is not None else (0, 0)
        out.append({**e, "verified": words == e["quote"], "excerpt": (text[lo:e["start"]] + "[" + words + "]" + text[e["end"]:hi]) if words else None})
    return out


def start(res: dict, prac: dict, practice_id: str, retention: str = "keep", session: str = "1") -> dict:
    """A new loop. ``session`` is the caller's own label for this loop (Workbooks: a UUID); it keeps two loops on
    the same item apart and makes the ID reproducible for the same inputs."""
    if retention not in RETENTION:
        raise LoopError(f"retention must be one of {RETENTION}")
    if not isinstance(session, str) or not session or len(session) > 64:
        raise LoopError("session: a non-empty label of at most 64 characters")
    ptr = pointer(res, prac, practice_id)
    lid = "lp-" + pr.sha("\x1f".join((ptr["source"]["source_id"], str(ptr["source"]["revision"]), practice_id, session)))[:12]
    return {"schema": SCHEMA, "loop_id": lid, "session": session, "pointer": ptr, "retention": retention, "events": []}


def _add(loop: dict, ev: dict) -> dict:
    out = copy.deepcopy(loop)
    ev = {"seq": len(out["events"]) + 1, **ev}
    out["events"].append(ev)
    return out


def _kinds(loop: dict) -> list[str]:
    return [e["event"] for e in loop["events"]]


def read(loop: dict, res: dict, sources: dict) -> dict:
    units = {i["item_id"]: i for i in res["items"]}
    shown = [{"unit_id": u, "type": units[u]["type"], "state": units[u]["state"],
              "text": units[u].get("effective", units[u]["content"])[pr.MAIN_TEXT[units[u]["type"]]]} for u in loop["pointer"]["unit_ids"]]
    return _add(loop, {"event": "read", "units": shown, "evidence": resolve(loop["pointer"], sources)})


def _answer(loop: dict, prac: dict, kind: str, text: str) -> dict:
    if not (text or "").strip():
        raise LoopError("an answer is needed (or reveal)")
    p = next(x for x in prac["items"] if x["practice_id"] == loop["pointer"]["practice_id"])
    g = pr.grade(p, text)
    # R4 experiment r4-retrieval-leakage, branch A: an answer given after reading the units in this loop is not unaided
    retrieval = "after_reveal" if kind == "retry" else "after_reading" if "read" in _kinds(loop) else "unaided"
    ev = {"event": kind, "outcome": g["outcome"], "retrieval": retrieval}
    if loop["retention"] == "keep":
        ev["answer"] = text.strip()
    else:
        ev["answer"] = None
        ev["answer_withheld"] = "learner_opt_out"
    return _add(loop, ev)


def recall(loop: dict, prac: dict, text: str) -> dict:
    if "reveal" in _kinds(loop):
        raise LoopError("recall comes before the reveal; after it, use retry")
    return _answer(loop, prac, "recall", text)


def reveal(loop: dict, prac: dict, sources: dict) -> dict:
    p = next(x for x in prac["items"] if x["practice_id"] == loop["pointer"]["practice_id"])
    h = p["hidden"]
    ref = {k: h[k] for k in ("answer", "accepted", "reference", "explanation") if k in h}
    return _add(loop, {"event": "reveal", "after_recall": "recall" in _kinds(loop), "reference": ref,
                       "evidence": resolve(loop["pointer"], sources), "note": "the reference is what you approved; the evidence is your own text"})


def retry(loop: dict, prac: dict, text: str) -> dict:
    if "reveal" not in _kinds(loop):
        raise LoopError("retry comes after the reveal; before it, use recall")
    return _answer(loop, prac, "retry", text)


def revisit(loop: dict, res: dict, prac: dict, sources: dict) -> dict:
    """A learner-started return: the pointer re-checked against the current review, the original evidence shown again."""
    if not {"recall", "reveal"} & set(_kinds(loop)):
        raise LoopError("revisit follows a recall or a reveal")
    states = {i["item_id"]: i for i in res["items"]}
    units = []
    for u in loop["pointer"]["unit_ids"]:
        it = states.get(u)
        st = "absent" if it is None else "current" if it["state"] in USABLE else "changed" if it["state"] in ("needs_review", "pending") else it["state"]
        units.append({"unit_id": u, "status": st})
    cur = {(e["field"], e["quote"]): e for e in res["evidence"] if e["status"] == "located"}
    ev = []
    for e in loop["pointer"]["evidence"]:
        c = cur.get((e["field"], e["quote"]))
        st = "absent" if c is None else "current" if c["evidence_id"] == e["evidence_id"] else "moved"
        ev.append({"evidence_id": e["evidence_id"], "status": st, **({"now": {k: c[k] for k in ("evidence_id", "source_revision", "start", "end")}}
                                                                      if st == "moved" else {})})
    offered = {x["practice_id"] for x in prac["items"]}
    pid = loop["pointer"]["practice_id"]
    if pid in offered:
        item = {"status": "offered"}
    else:
        code, why = feed2.reason_code(res, loop["pointer"]["unit_ids"], "source")
        item = {"status": "withdrawn", "reason_code": code, "reason": why}
    return _add(loop, {"event": "revisit", "revision": res["source"]["revision"], "units": units, "evidence_status": ev, "practice": item,
                       "original_evidence": resolve(loop["pointer"], sources),
                       "can_practise": item["status"] == "offered" and all(u["status"] == "current" for u in units)})


def set_retention(loop: dict, retention: str) -> dict:
    if retention not in RETENTION:
        raise LoopError(f"retention must be one of {RETENTION}")
    out = copy.deepcopy(loop)
    removed = 0
    if retention == "discard":
        for e in out["events"]:
            if e.get("answer"):
                e["answer"], e["answer_withheld"] = None, "learner_opt_out"
                removed += 1
    out["retention"] = retention
    return _add(out, {"event": "retention", "retention": retention, "answers_removed": removed})


def validate(loop: dict) -> list[str]:
    """Contract checks a consumer can run on a loop document."""
    out = []
    if loop.get("schema") != SCHEMA:
        return [f"not a {SCHEMA} document"]
    if loop.get("retention") not in RETENTION:
        out.append("retention must be keep or discard")
    seqs = [e.get("seq") for e in loop.get("events", [])]
    if seqs != list(range(1, len(seqs) + 1)):
        out.append("events must be numbered 1, 2, 3, … in order")
    seen = []
    discard_from = None
    for e in loop.get("events", []):
        k = e.get("event")
        if k not in EVENTS:
            out.append(f"event {e.get('seq')}: unknown kind {k!r}")
        if k == "recall" and "reveal" in seen:
            out.append(f"event {e['seq']}: recall after a reveal")
        if k == "recall" and e.get("retrieval") == "unaided" and "read" in seen:
            out.append(f"event {e['seq']}: a recall after a read cannot be unaided")
        if k == "retry" and "reveal" not in seen:
            out.append(f"event {e['seq']}: retry before any reveal")
        if k == "revisit" and not {"recall", "reveal"} & set(seen):
            out.append(f"event {e['seq']}: revisit before any recall or reveal")
        if k == "retention" and e.get("retention") == "discard":
            discard_from = e["seq"]
        seen.append(k)
    if loop.get("retention") == "discard":
        kept = [e["seq"] for e in loop.get("events", []) if e.get("answer")]
        if kept:
            out.append(f"retention is discard but events {kept} keep an answer")
    if discard_from and any(e.get("answer") for e in loop["events"]):
        out.append("answers kept after the learner chose discard")
    ptr = loop.get("pointer") or {}
    if not ptr.get("unit_ids"):
        out.append("pointer: no reviewed unit")
    for e in ptr.get("evidence", []):
        if not all(k in e for k in ("evidence_id", "source_revision", "field", "start", "end", "quote")):
            out.append(f"pointer: evidence {e.get('evidence_id')} lacks its location")
    return out


def render(loop: dict) -> str:
    L = [f"Loop {loop['loop_id']} on {loop['pointer']['practice_id']} ({loop['pointer']['kind']}); answers: {loop['retention']}"]
    for e in loop["events"]:
        k = e["event"]
        if k == "read":
            L.append(f"  {e['seq']} read     " + "; ".join(f"{u['unit_id']} ({u['state']})" for u in e["units"]))
            L += [f"             evidence {x['evidence_id']} r{x['source_revision']} {x['field']}: {x['excerpt']}  verified {x['verified']}" for x in e["evidence"]]
        elif k in ("recall", "retry"):
            L.append(f"  {e['seq']} {k:8} {e['outcome']} ({e['retrieval']})" + (f"  « {e['answer']} »" if e.get("answer") else "  (answer not kept)"))
        elif k == "reveal":
            L.append(f"  {e['seq']} reveal   {'after a recall' if e['after_recall'] else 'without a recall'}: " + str(e["reference"].get("answer", "reference")))
        elif k == "revisit":
            L.append(f"  {e['seq']} revisit  r{e['revision']}: units " + ", ".join(f"{u['unit_id']} {u['status']}" for u in e["units"])
                     + "; evidence " + ", ".join(f"{x['evidence_id']} {x['status']}" for x in e["evidence_status"])
                     + f"; practice {e['practice']['status']}" + (f" ({e['practice']['reason_code']})" if e["practice"].get("reason_code") else "")
                     + f"; can practise: {e['can_practise']}")
        elif k == "retention":
            L.append(f"  {e['seq']} retention {e['retention']}: {e['answers_removed']} earlier answer(s) removed")
    return "\n".join(L) + "\n"


def next_step(loop: dict) -> str:
    """What the loop offers next: recall before read (attempt first), then reveal, read, retry; revisit later."""
    k = _kinds(loop)
    if "recall" not in k and "reveal" not in k:
        return "recall"
    if "reveal" not in k:
        return "reveal"
    if "read" not in k:
        return "read"
    return "retry" if "retry" not in k else "revisit"
