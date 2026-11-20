"""Compatibility check for flh_practice_review_feed_v1 feeds (standard library only; no package imports).

  python3 -I -B check_feed_compat.py FEED.json [FEED.json …] [--replay CASES.json] [--json]

It is copied byte for byte into the sealed Workbooks bundle as ``check_feed_compat.py`` so the
Workbooks verification runner can call it without the extraction lane's code. Three checks:

1. **contract**: the extraction lane's v1 contract and its compatible 2.2 additions
   (``flh_practice_feed_additions_v1``): stable ID patterns, known kinds and outcomes, a reveal
   is ``revealed``, nothing a feed must never carry (due dates, intervals, answers, attempt
   texts), per-item source revision equal to the feed's, and withdrawn / restored / added lists
   that agree with the items.
2. **consumer**: the rules of the Workbooks consumer as sealed in its increment-4 handoff
   (``web/src/prototype/practiceFeed.ts``, ``parseFeed``). A feed can satisfy the contract and
   still be refused there (an all-withdrawn feed has no items); that is reported apart.
3. **replay** (with ``--replay``): a reference client applies feed sequences; a feed already
   applied (same ``feed_id``) changes nothing, an older one is ignored, a withdrawn ID stops
   being offered and keeps its history, a restored ID is offered again.

Exit 0 when every contract and replay check holds; consumer refusals are listed and only make
the exit 1 with ``--strict-consumer``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys

FEED = "flh_practice_review_feed_v1"
ADDITIONS = "flh_practice_feed_additions_v1"
KINDS = {"explain", "choose", "produce"}
OUTCOMES = {"correct", "incorrect", "self_check", "revealed", "invalid"}
RECALL = {"unassisted_recall", "assisted_recall", "transfer"}
NEVER = {"due", "due_at", "due_date", "interval", "interval_days", "schedule", "next_review", "hidden", "answer", "accepted", "rubric", "text"}
CONSUMER_BANNED = ["answer", "accepted", "hidden", "rubric", "due", "due_at", "interval", "text"]  # practiceFeed.ts, increment 4
PID, KID, EID = re.compile(r"p-[0-9a-f]{12}"), re.compile(r"k-[0-9a-f]{12}"), re.compile(r"ev-[0-9a-f]{10}")
REASONS = {"knowledge_changed", "awaiting_confirmation", "rejected", "rule_not_approved", "absent"}


def canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def feed_id(f: dict) -> str:
    return "f-" + hashlib.sha256(canon({k: v for k, v in f.items() if k != "feed_id"}).encode("utf-8")).hexdigest()[:12]


def _keys(obj, out=None) -> set:
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def contract_issues(f: dict) -> list[str]:
    out = []
    if f.get("schema") != FEED:
        return [f"schema is not {FEED}"]
    src = f.get("source") or {}
    for k in ("source_id", "revision", "revision_sha256"):
        if k not in src:
            out.append(f"source.{k} is missing")
    banned = _keys(f.get("items", [])) & NEVER
    if banned:
        out.append(f"items carry what a feed never carries: {sorted(banned)}")
    seen = set()
    for p in f.get("items", []):
        pid = p.get("practice_id", "")
        if not PID.fullmatch(pid) or pid in seen:
            out.append(f"bad or repeated practice_id {pid!r}")
        seen.add(pid)
        if p.get("kind") not in KINDS:
            out.append(f"{pid}: unknown kind {p.get('kind')!r}")
        if not p.get("knowledge_ids") or not all(KID.fullmatch(k) for k in p["knowledge_ids"]):
            out.append(f"{pid}: knowledge_ids must be k-… IDs")
        if not all(EID.fullmatch(e) for e in p.get("evidence_ids", [])):
            out.append(f"{pid}: evidence_ids must be ev-… IDs")
        for o in p.get("outcomes", []):
            if o.get("action") not in ("attempt", "reveal") or o.get("outcome") not in OUTCOMES or not isinstance(o.get("seq"), int):
                out.append(f"{pid}: outcome outside the contract: {o}")
            elif o["action"] == "reveal" and o["outcome"] != "revealed":
                out.append(f"{pid}: a reveal must be recorded as revealed")
        if f.get("contract_additions") == ADDITIONS:
            sr = p.get("source_revision") or {}
            if (sr.get("revision"), sr.get("revision_sha256")) != (src.get("revision"), src.get("revision_sha256")):
                out.append(f"{pid}: source_revision differs from the feed's source")
            if p.get("recall_type") not in RECALL:
                out.append(f"{pid}: recall_type must be one of {sorted(RECALL)}")
            if p.get("origin") not in ("source", "agent_proposal"):
                out.append(f"{pid}: origin must be source or agent_proposal")
    wd = [x.get("practice_id") for x in f.get("withdrawn", [])]
    if set(wd) & seen:
        out.append(f"offered and withdrawn at once: {sorted(set(wd) & seen)}")
    if f.get("contract_additions") == ADDITIONS:
        for x in f.get("withdrawn", []):
            if x.get("reason_code") not in REASONS:
                out.append(f"{x.get('practice_id')}: withdrawn reason_code must be one of {sorted(REASONS)}")
        for k in ("restored", "added"):
            extra = set(f.get(k, [])) - seen
            if extra:
                out.append(f"{k} names IDs that are not offered: {sorted(extra)}")
        if set(f.get("restored", [])) & set(f.get("added", [])):
            out.append("an ID cannot be both restored and added")
        if f.get("feed_id") != feed_id(f):
            out.append("feed_id does not match the feed's content")
        if not isinstance(f.get("feed_seq"), int) or f["feed_seq"] < 1:
            out.append("feed_seq must be a positive integer")
    return out


def consumer_issues(f: dict) -> list[str]:
    """What the Workbooks increment-4 parseFeed would refuse (mirrored rules, not their code)."""
    out = []
    if f.get("schema") != FEED:
        return [f"not a {FEED} document"]
    src = f.get("source") if isinstance(f.get("source"), dict) else None
    if src is None:
        return ["feed: source missing"]
    if not isinstance(src.get("revision"), int) or src["revision"] < 1:
        out.append("source.revision must be a positive integer")
    if not re.fullmatch(r"[0-9a-f]{64}", str(src.get("revision_sha256", ""))):
        out.append("source.revision_sha256 must be 64 hex characters")
    for k in ("source_id", "capture_id", "proposer"):
        if not isinstance(src.get(k), str) or not src[k]:
            out.append(f"source.{k} must be a non-empty string")
    items = f.get("items")
    if not isinstance(items, list) or not items:
        out.append("items must be a non-empty list (an all-withdrawn feed is refused)")
        return out
    for i, raw in enumerate(items, 1):
        for b in CONSUMER_BANNED:
            if b in raw:
                out.append(f"item {i}: carries {b!r}")
        for k in ("practice_id", "kind", "measures", "prompt", "grading"):
            if not isinstance(raw.get(k), str) or not raw[k]:
                out.append(f"item {i}: {k} must be a non-empty string")
        if raw.get("kind") == "choose" and not (isinstance(raw.get("options"), list) and len(raw["options"]) >= 2):
            out.append(f"item {i}: a choose item needs options")
        for k in ("knowledge_ids", "evidence_ids"):
            if not isinstance(raw.get(k), list) or not all(isinstance(x, str) for x in raw[k]):
                out.append(f"item {i}: {k} must be a list of strings")
        for o in raw.get("outcomes", []) if isinstance(raw.get("outcomes"), list) else [None]:
            if not isinstance(o, dict) or o.get("outcome") not in OUTCOMES or o.get("action") not in ("attempt", "reveal"):
                out.append(f"item {i}: an outcome outside seq / action / known outcome")
    return out


def client_apply(state: dict, f: dict) -> str:
    """The reference client: returns what it did (applied, replay, stale, other_source)."""
    if state.get("source_id") not in (None, f["source"]["source_id"]):
        return "other_source"
    fid = f.get("feed_id") or feed_id(f)
    if fid in state.setdefault("seen", []):
        return "replay"
    key = (f["source"]["revision"], f.get("feed_seq", 0))
    if state.get("key") and tuple(state["key"]) > key:
        return "stale"
    state["source_id"], state["key"] = f["source"]["source_id"], list(key)
    state["seen"].append(fid)
    items = state.setdefault("items", {})
    now = {p["practice_id"] for p in f["items"]}
    for p in f["items"]:
        it = items.setdefault(p["practice_id"], {"offered": True, "history": []})
        it["offered"] = True
        it.pop("withdrawn_reason", None)
        have = {o["seq"] for o in it["history"]}
        it["history"] += [o for o in p.get("outcomes", []) if o["seq"] not in have]
        it["history"].sort(key=lambda o: o["seq"])
    for x in f.get("withdrawn", []):
        if x["practice_id"] not in now:
            it = items.setdefault(x["practice_id"], {"offered": False, "history": []})
            it["offered"] = False
            it["withdrawn_reason"] = x.get("reason_code", "unspecified")
    return "applied"


def run_replay(cases: dict, load) -> list[str]:
    out = []
    for name, c in sorted(cases["cases"].items()):
        state: dict = {}
        did = [client_apply(state, load(n)) for n in c["deliver"]]
        if did != c["expect"]["actions"]:
            out.append(f"replay {name}: actions {did}, expected {c['expect']['actions']}")
        got = {pid: {"offered": v["offered"], "history": len(v["history"]), **({"reason": v["withdrawn_reason"]} if "withdrawn_reason" in v else {})}
               for pid, v in sorted(state.get("items", {}).items())}
        if got != c["expect"]["items"]:
            out.append(f"replay {name}: final state {got}, expected {c['expect']['items']}")
    return out


def main(argv: list[str]) -> int:
    import os
    args, files, replay, as_json, strict = argv[1:], [], None, False, False
    while args:
        a = args.pop(0)
        if a == "--replay":
            replay = args.pop(0)
        elif a == "--json":
            as_json = True
        elif a == "--strict-consumer":
            strict = True
        else:
            files.append(a)

    def load(p):
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)

    report = {"files": {}, "replay": []}
    for p in files:
        f = load(p)
        report["files"][p] = {"contract": contract_issues(f), "consumer_increment_4": consumer_issues(f)}
    if replay:
        base = os.path.dirname(os.path.abspath(replay))
        report["replay"] = run_replay(load(replay), lambda n: load(os.path.join(base, n)))
    bad = any(r["contract"] for r in report["files"].values()) or bool(report["replay"])
    refused = any(r["consumer_increment_4"] for r in report["files"].values())
    if as_json:
        print(json.dumps(report, indent=1, sort_keys=True))
    else:
        for p, r in report["files"].items():
            name = os.path.basename(p)
            print(f"{name}: contract {'OK' if not r['contract'] else 'FAIL'}; Workbooks consumer (increment 4) "
                  f"{'accepts' if not r['consumer_increment_4'] else 'REFUSES'}")
            for x in r["contract"]:
                print(f"  contract: {x}")
            for x in r["consumer_increment_4"]:
                print(f"  consumer: {x}")
        if replay:
            print("replay: " + ("OK" if not report["replay"] else f"{len(report['replay'])} problem(s)"))
            for x in report["replay"]:
                print(f"  {x}")
    return 1 if bad or (strict and refused) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
