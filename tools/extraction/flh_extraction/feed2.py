"""Feed additions for Workbooks (Extraction 2.2; PROTOTYPE, offline).

The documented ``flh_practice_review_feed_v1`` (``packet.workbooks_feed``) is unchanged and
its sealed 2.1 bundle stays byte-identical. ``feed`` adds only optional fields, marked by
``contract_additions: flh_practice_feed_additions_v1``, that a v1 reader ignores:

* per item: ``source_revision`` (the revision and its SHA-256), ``recall_type``
  (``recall.TYPES``), ``origin`` (``source`` or ``agent_proposal``) and, for an agent
  exercise, ``provenance``;
* per feed: ``feed_seq`` and ``feed_id`` (a hash of the feed) so a client can recognise a
  replay; with a previous feed, ``withdrawn`` (with a ``reason_code``), ``restored`` and
  ``added``.

``withdrawn`` stays listed in every later feed until the ID is offered again, so a client
that missed a feed still converges. A withdrawn ID keeps its outcome history. Reason codes:
``knowledge_changed``, ``awaiting_confirmation`` (the evidence came back; the learner has not
confirmed it), ``rejected``, ``rule_not_approved`` (an agent exercise) and ``absent``.
Nothing schedules: when an item is due stays Workbooks' decision.
"""

from __future__ import annotations

from . import feed_compat as fc
from . import packet as pk
from . import practice as pr

RECALL = {"explain": "unassisted_recall", "choose": "assisted_recall", "produce": "transfer"}


def reason_code(res: dict, knowledge_ids: list[str], origin: str) -> tuple[str, str]:
    states = {i["item_id"]: i for i in res["items"]}
    for k in knowledge_ids:
        it = states.get(k)
        if it is None:
            return "absent", f"{k} is not in revision {res['source']['revision']}"
        if it["state"] == "needs_review":
            if it.get("review_kind") == "restored":
                return "awaiting_confirmation", f"{k}: its evidence is back in revision {res['source']['revision']}; the learner has not confirmed it yet"
            return ("rule_not_approved" if origin == "agent_proposal" else "knowledge_changed"), f"{k} changed in revision {res['source']['revision']}"
        if it["state"] == "rejected":
            return "rejected", f"{k} was rejected by the learner"
        if it["state"] == "pending":
            return ("rule_not_approved" if origin == "agent_proposal" else "knowledge_changed"), f"{k} is not decided in revision {res['source']['revision']}"
    return "knowledge_changed", "its knowledge changed"


def feed(res: dict, prac: dict, attempts: list[dict], seq: int, previous: dict | None = None) -> dict:
    base = pk.workbooks_feed(prac, attempts)
    src = prac["source"]
    rev = {"revision": src["revision"], "revision_sha256": src["revision_sha256"]}
    origin = {p["practice_id"]: p for p in prac["items"]}
    for it in base["items"]:
        p = origin[it["practice_id"]]
        it["source_revision"] = rev
        it["recall_type"] = RECALL[it["kind"]] if it["kind"] != "produce" or it.get("new_sentence") else "assisted_recall"
        it["origin"] = p.get("origin", "source")
        if p.get("provenance"):
            it["provenance"] = {k: p["provenance"][k] for k in ("agent", "packet_id", "proposal_id", "accepted_by")}
        it.pop("support", None)
    base["contract_additions"] = fc.ADDITIONS
    base["feed_seq"] = seq
    if previous is not None:
        if previous.get("schema") != pk.FEED_SCHEMA or previous["source"]["source_id"] != src["source_id"]:
            raise ValueError("the previous feed must be an earlier feed of the same source")
        now = {p["practice_id"] for p in base["items"]}
        was = {p["practice_id"]: p for p in previous["items"]}
        was_w = {x["practice_id"]: x for x in previous.get("withdrawn", [])}
        base["previous"] = {"feed_id": previous.get("feed_id"), "revision": previous["source"]["revision"],
                            "revision_sha256": previous["source"]["revision_sha256"]}
        wd = []
        for pid in sorted((set(was) | set(was_w)) - now):
            old = was.get(pid) or was_w[pid]
            code, why = reason_code(res, old["knowledge_ids"], old.get("origin", "source"))
            wd.append({"practice_id": pid, "kind": old["kind"], "knowledge_ids": old["knowledge_ids"], "reason_code": code, "reason": why,
                       "since_revision": was_w[pid]["since_revision"] if pid in was_w else src["revision"]})
        base["withdrawn"] = wd
        base["restored"] = sorted(now & set(was_w))
        base["added"] = sorted(now - set(was) - set(was_w))
    base["not_included"] = base["not_included"] + ["skipped items and missing observations (a feed records attempts and reveals only)"]
    base["feed_id"] = fc.feed_id(base)
    return base
