"""Fixture-only round trip through the Workbooks storage proposal (Extraction 2.2; PROTOTYPE).

The Workbooks lane proposed four append-only tables (``fixtures/practice_v1/storage/
workbooks-proposed-0NN.sql``, a pinned copy of their sealed handoff; status PROPOSED, no
migration exists). This module maps an extraction work directory onto those tables in an
in-memory SQLite database (``sqlite3``, nothing on disk), reads the rows back, rebuilds the
decisions and attempts, and compares the learner-visible result:

* ``as_proposed``: their SQL unchanged;
* ``amended``: the smallest change the extraction lane proposes (``AMENDMENT``): an
  ``agent_exercise`` subject kind and a ``provenance_json`` column on ``practice_decisions``.

It also renders attempts for export with the answer text omitted (``export_attempts``) and a
history in which retracted evidence is labelled, never deleted (``history``).
"""

from __future__ import annotations

import json
import os
import sqlite3

from . import practice as pr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL = os.path.join(HERE, "fixtures", "practice_v1", "storage", "workbooks-proposed-0NN.sql")
AMENDMENT = [
    ("CHECK (subject_kind IN ('extraction_item', 'notebook_draft'))", "CHECK (subject_kind IN ('extraction_item', 'notebook_draft', 'agent_exercise'))"),
    ("    reason                  TEXT,\n    created_at", "    reason                  TEXT,\n    provenance_json         TEXT,\n    created_at"),
]
EXTRA_DECISION_FIELDS = ("batch", "via", "attest")
EXTRA_BASED_ON = ("draft_id", "material_hash")


def sql(amended: bool) -> str:
    with open(SQL, encoding="utf-8") as fh:
        s = fh.read()
    if amended:
        for a, b in AMENDMENT:
            if a not in s:
                raise ValueError(f"the pinned SQL no longer contains {a!r}: re-read the Workbooks proposal")
            s = s.replace(a, b)
    return s


def op_key(*parts) -> str:
    h = pr.sha("\x1f".join(map(str, parts)))
    return f"{h[:8]}-{h[8:12]}-5{h[13:16]}-8{h[17:20]}-{h[20:32]}"


def _ts(n: int) -> str:
    return f"2026-11-19T00:{n // 60:02d}:{n % 60:02d}Z"


def rows(work, amended: bool, keep_answer_text: bool = True) -> tuple[dict, list[str]]:
    """Rows for the four tables (only two are used by the extraction lane) and what cannot be stored."""
    drafts, lost = work.drafts(), []
    shas = {r: d["source"]["revision_sha256"] for r, d in drafts.items()}
    sid = work.draft()["source"]["source_id"]
    dec = []
    for d in work.decisions():
        extra = {k: d[k] for k in EXTRA_DECISION_FIELDS if k in d}
        extra.update({k: d["based_on"][k] for k in EXTRA_BASED_ON if k in d["based_on"]})
        if extra and not amended:
            lost.append(f"decision {d['seq']}: {', '.join(sorted(extra))} has no column")
        dec.append({"operation_key": op_key(sid, "decision", d["seq"]), "subject_kind": "extraction_item", "subject_id": d["item_id"],
                    "source_id": sid, "source_revision_sha256": shas[d["based_on"]["source_revision"]], "item_hash": d["based_on"]["item_hash"],
                    "action": d["action"], "edited_text": d.get("text"), "reason": d.get("reason") or None, "created_at": _ts(d["seq"]),
                    **({"provenance_json": json.dumps(extra, sort_keys=True, ensure_ascii=False) if extra else None} if amended else {})})
    for d in getattr(work, "exercise_decisions", lambda: [])():
        prov = {k: d[k] for k in ("proposal", "rule_id", "knowledge_ids", "kind", "source", "evidence_ids", "edited", "final", "practice_id")}
        dec.append({"operation_key": op_key(sid, "exercise", d["seq"]), "subject_kind": "agent_exercise", "subject_id": d["practice_id"],
                    "source_id": sid, "source_revision_sha256": d["source"]["revision_sha256"], "item_hash": d["proposal"]["content_sha256"],
                    "action": d["action"], "edited_text": None, "reason": d.get("reason") or None, "created_at": _ts(1000 + d["seq"]),
                    **({"provenance_json": json.dumps(prov, sort_keys=True, ensure_ascii=False)} if amended else {})})
    att = []
    for a in work.attempts():
        rev = a.get("source_revision")
        if rev is None:
            lost.append(f"attempt {a['seq']}: no source revision recorded (a 2.1 attempt); the current revision is assumed")
        sha = (rev or {}).get("revision_sha256") or work.draft()["source"]["revision_sha256"]
        att.append({"operation_key": op_key(sid, "attempt", a["seq"]), "practice_id": a["practice_id"], "source_id": sid,
                    "source_revision_sha256": sha, "action": a["action"], "outcome": a["outcome"], "self_check": None,
                    "answer_text": a.get("text") if keep_answer_text and a["action"] == "attempt" else None,
                    "local_day": "2026-11-19", "zone": "UTC", "created_at": _ts(2000 + a["seq"])})
        for k in ("matched", "known_error", "chosen"):
            if k in a:
                lost.append(f"attempt {a['seq']}: {k} has no column" + ("; it can be recomputed from the stored answer text" if keep_answer_text
                                                                        else "; without the answer text it is gone"))
    return {"practice_decisions": dec, "practice_attempts": att}, lost


def round_trip(work, amended: bool, keep_answer_text: bool = True) -> dict:
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(sql(amended))
        data, lost = rows(work, amended, keep_answer_text)
        refused = []
        for table, rs in data.items():
            for r in rs:
                cols = sorted(r)
                try:
                    db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [r[c] for c in cols])
                except sqlite3.IntegrityError as e:
                    refused.append(f"{table} {r.get('subject_kind', '')} {r.get('subject_id', r.get('practice_id'))}: {e}")
        db.commit()
        back = [dict(zip([c[0] for c in cur.description], row)) for cur in [db.execute("SELECT * FROM practice_decisions ORDER BY id")] for row in cur.fetchall()]
        att = [dict(zip([c[0] for c in cur.description], row)) for cur in [db.execute("SELECT * FROM practice_attempts ORDER BY id")] for row in cur.fetchall()]
        replay = []
        for table, rs in data.items():
            for r in rs[:1]:
                cols = sorted(r)
                try:
                    db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [r[c] for c in cols])
                    replay.append(f"{table}: a resend was stored twice")
                except sqlite3.IntegrityError:
                    pass
    finally:
        db.close()
    by_sha = {d["source"]["revision_sha256"]: r for r, d in work.drafts().items()}
    rebuilt = []
    for n, b in enumerate((b for b in back if b["subject_kind"] == "extraction_item"), 1):
        d = {"schema": pr.DECISION_SCHEMA, "seq": n, "item_id": b["subject_id"], "action": b["action"], "reason": b["reason"] or "",
             "based_on": {"source_revision": by_sha[b["source_revision_sha256"]], "item_hash": b["item_hash"]}}
        if b["edited_text"] is not None:
            d["text"] = b["edited_text"]
        extra = json.loads(b["provenance_json"]) if b.get("provenance_json") else {}
        for k in EXTRA_BASED_ON:
            if k in extra:
                d["based_on"][k] = extra.pop(k)
        d.update(extra)
        rebuilt.append(d)
    original = work.decisions()
    from . import review2 as rv
    res_a = rv.resolve2(work.drafts(), original, work.sources())
    res_b = rv.resolve2(work.drafts(), rebuilt, work.sources())
    view = lambda res: {i["item_id"]: (i["state"], i.get("accepted_from", {}).get("proposal_id"), bool(i.get("attested")), i.get("batch_id"))
                        for i in res["items"]}
    diff = [f"{k}: original {view(res_a)[k]} -> from the tables {view(res_b)[k]}" for k in view(res_a) if view(res_a)[k] != view(res_b)[k]]
    return {"variant": "amended" if amended else "as_proposed", "answer_text_stored": keep_answer_text,
            "rows": {"practice_decisions": len(back), "practice_attempts": len(att)}, "refused_by_constraints": refused,
            "not_representable": lost, "learner_visible_differences": diff, "resend_refused_by_operation_key": not replay,
            "exercise_decisions_stored": sum(1 for b in back if b["subject_kind"] == "agent_exercise"),
            "answer_texts_stored": sum(1 for a in att if a["answer_text"] is not None)}


def export_attempts(attempts: list[dict], include_text: bool = False) -> list[dict]:
    """Attempts for an export: the answer text is omitted unless the learner chooses to include it.
    No hash or length of the text is kept: a short answer would be guessable from either."""
    out = []
    for a in attempts:
        r = {k: v for k, v in a.items() if k not in ("text", "matched", "known_error", "chosen") or include_text}
        if a.get("text") is not None and not include_text:
            r["text_omitted"] = True
        out.append(r)
    return out


def history(work, feeds: list[dict]) -> list[dict]:
    """Every practice ID seen in the feeds with all its outcomes; a withdrawn ID is labelled with the
    revision and reason, never removed."""
    out = {}
    for f in feeds:
        for p in f["items"]:
            h = out.setdefault(p["practice_id"], {"practice_id": p["practice_id"], "kind": p["kind"], "outcomes": [], "status": "offered"})
            h["outcomes"] = sorted({o["seq"]: o for o in h["outcomes"] + p["outcomes"]}.values(), key=lambda o: o["seq"])
            h["status"] = "offered"
            h.pop("retracted", None)
        for x in f.get("withdrawn", []):
            h = out.setdefault(x["practice_id"], {"practice_id": x["practice_id"], "kind": x["kind"], "outcomes": [], "status": "withdrawn"})
            h["status"] = "withdrawn"
            h["retracted"] = {"since_revision": x.get("since_revision"), "reason_code": x.get("reason_code"), "reason": x.get("reason"),
                              "history_kept": "earlier outcomes stay; they were recorded against the evidence of their own revision"}
    return [out[k] for k in sorted(out)]


EVENTS = [  # (event, file today, survives a reload?, idempotent?, why)
    ("learner decision (approve / reject / edit)", "decisions.jsonl", "must survive", "no: a later decision on the same item is a new event",
     "the learner's authority; the latest decision wins and the earlier ones are history"),
    ("batch approval", "decisions.jsonl (one record per member, batch meta)", "must survive", "yes: the same batch ID writes only missing members",
     "a retry after an interruption must not double-approve"),
    ("accepted agent correction", "decisions.jsonl (edit with via)", "must survive", "yes: a second accept is refused as a duplicate",
     "provenance of the wording the learner adopted"),
    ("exercise decision on an agent proposal", "exercise-decisions.jsonl", "must survive", "yes: keyed by (agent, packet, proposal)",
     "an accepted exercise is practice; a rejection must not be asked again"),
    ("attempt", "attempts.jsonl", "must survive", "no: each attempt is intentionally a new event", "outcomes are the history Workbooks schedules from"),
    ("reveal", "attempts.jsonl", "must survive", "no: each reveal is intentionally a new event", "a reveal is not an attempt and is never correct"),
    ("exported packet", "packets/pk-….json + index", "should survive", "yes: the packet ID hashes its content",
     "the next session continues from it without the earlier conversation"),
    ("draft of each revision", "drafts/rN.json, sources/rN.json", "rebuildable from the sources", "yes", "needed to say what changed and to refuse silent reactivation"),
    ("practice build", "practice.json", "rebuildable", "yes", "derived from decisions and drafts"),
    ("feed", "written on request", "rebuildable", "yes: the feed ID hashes its content", "Workbooks applies it; a replay changes nothing"),
]

ID_MAP = [  # (extraction ID, meaning, Workbooks column in the proposal)
    ("k-… item_id", "a knowledge item: hashes source, type and content key, never the revision", "practice_decisions.subject_id (subject_kind extraction_item)"),
    ("item_hash", "the item's content and grounding when decided", "practice_decisions.item_hash"),
    ("material_hash, draft_id, batch, via, attest", "2.2 decision context", "none as proposed; provenance_json in the amendment"),
    ("revision_sha256", "the source revision", "practice_decisions / practice_attempts.source_revision_sha256 (the revision number is derived from the drafts)"),
    ("p-… practice_id", "an exercise: hashes the knowledge ID and kind (source) or rule, kind and prompt (agent)", "practice_attempts.practice_id; "
     "practice_decisions.subject_id for an agent exercise (amendment)"),
    ("ev-… evidence_id", "a quote at one position in one revision", "not stored: rebuilt from the source; a moved quote gets a new ID"),
    ("pk-… packet_id", "an exported packet", "not stored by Workbooks; kept in the extraction work directory"),
    ("b2-… batch_id", "a batch shown to the learner", "provenance_json (amendment); operation_key = hash(source, decision seq)"),
    ("proposal (agent, packet_id, proposal_id)", "an agent proposal", "provenance_json (amendment)"),
]
