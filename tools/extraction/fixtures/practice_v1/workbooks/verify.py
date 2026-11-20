"""Verify the sealed synthetic Workbooks bundle (flh_practice_workbooks_bundle_v1).

  python3 verify.py [BUNDLE_DIR]      # default: the directory of this file

Standard library only; reads files, writes nothing, makes no network call. It checks the
seal (SHA256SUMS), the shape of every feed (flh_practice_review_feed_v1), and the three
cases in cases.json: a changed source, a duplicate correction and a study packet without
answers. Exit 0 when everything holds, 1 otherwise.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys

FEED = "flh_practice_review_feed_v1"
KINDS = {"explain", "choose", "produce"}
OUTCOMES = {"correct", "incorrect", "self_check", "revealed", "invalid"}
ACTIONS = {"attempt", "reveal"}
NEVER = {"due", "due_at", "due_date", "interval", "interval_days", "schedule", "next_review", "hidden", "answer", "accepted", "rubric", "text"}
PID = re.compile(r"p-[0-9a-f]{12}")
KID = re.compile(r"k-[0-9a-f]{12}")


def load(d: str, name: str):
    with open(os.path.join(d, name), encoding="utf-8") as fh:
        return json.load(fh)


def read(d: str, name: str) -> str:
    with open(os.path.join(d, name), encoding="utf-8") as fh:
        return fh.read()


def keys_anywhere(obj, found=None) -> set:
    found = set() if found is None else found
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(k)
            keys_anywhere(v, found)
    elif isinstance(obj, list):
        for v in obj:
            keys_anywhere(v, found)
    return found


def check_seal(d: str, fail) -> None:
    listed = {}
    for line in read(d, "SHA256SUMS").splitlines():
        h, name = line.split("  ", 1)
        listed[name] = h
    present = {n for n in os.listdir(d) if n != "SHA256SUMS" and os.path.isfile(os.path.join(d, n))}
    for n in sorted(present - set(listed)):
        fail(f"seal: {n} is not listed in SHA256SUMS")
    for n, h in sorted(listed.items()):
        if n not in present:
            fail(f"seal: {n} is listed but missing")
            continue
        with open(os.path.join(d, n), "rb") as fh:
            if hashlib.sha256(fh.read()).hexdigest() != h:
                fail(f"seal: {n} does not match its SHA-256")


def check_feed(name: str, f: dict, fail) -> None:
    if f.get("schema") != FEED:
        fail(f"{name}: schema is not {FEED}")
        return
    src = f.get("source") or {}
    for k in ("source_id", "revision", "revision_sha256"):
        if k not in src:
            fail(f"{name}: source.{k} is missing")
    banned = keys_anywhere(f.get("items", [])) & NEVER
    if banned:
        fail(f"{name}: keys that a feed never carries: {sorted(banned)}")
    seen = set()
    for p in f.get("items", []):
        pid = p.get("practice_id", "")
        if not PID.fullmatch(pid) or pid in seen:
            fail(f"{name}: bad or repeated practice_id {pid!r}")
        seen.add(pid)
        if p.get("kind") not in KINDS:
            fail(f"{name}: {pid} has kind {p.get('kind')!r}")
        if not p.get("knowledge_ids") or not all(KID.fullmatch(k) for k in p["knowledge_ids"]):
            fail(f"{name}: {pid} needs k-… knowledge_ids")
        for o in p.get("outcomes", []):
            if o.get("action") not in ACTIONS or o.get("outcome") not in OUTCOMES or not isinstance(o.get("seq"), int):
                fail(f"{name}: {pid} has an outcome outside the contract: {o}")
    for x in f.get("withdrawn", []):
        if x.get("practice_id") in seen:
            fail(f"{name}: {x.get('practice_id')} is both offered and withdrawn")


def main(argv: list[str]) -> int:
    d = os.path.abspath(argv[1] if len(argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
    problems: list[str] = []
    fail = problems.append
    check_seal(d, fail)
    man = load(d, "MANIFEST.json")
    if man.get("schema") != "flh_practice_workbooks_bundle_v1":
        fail("MANIFEST.json: unknown schema")
    feeds = {}
    for entry in man.get("feeds", []):
        f = feeds[entry["file"]] = load(d, entry["file"])
        check_feed(entry["file"], f, fail)
        if {p["practice_id"]: p["kind"] for p in f.get("items", [])} != entry["practice_ids"]:
            fail(f"{entry['file']}: practice IDs differ from MANIFEST.json")
        if f["source"]["revision_sha256"] != entry["revision_sha256"]:
            fail(f"{entry['file']}: revision_sha256 differs from MANIFEST.json")
    seen_outcomes = {o["outcome"] for f in feeds.values() for p in f["items"] for o in p["outcomes"]}
    if seen_outcomes != OUTCOMES:
        fail(f"attempt examples cover {sorted(seen_outcomes)}, not every outcome {sorted(OUTCOMES)}")
    cases = load(d, "cases.json")["cases"]

    c = cases["changed-source"]
    f1, f2, f3 = (feeds[n] for n in c["feeds"])
    e = c["expect"]
    if {f["source"]["source_id"] for f in (f1, f2, f3)} != {e["source_id"]}:
        fail("changed-source: the feeds are not all about one source")
    if [f["source"]["revision"] for f in (f1, f2, f3)] != e["revisions"]:
        fail("changed-source: revisions differ from the case")
    if f1["source"]["revision_sha256"] == f2["source"]["revision_sha256"]:
        fail("changed-source: the revision hash did not change")
    if len(f2["items"]) != e["r2_items"] or sorted(x["practice_id"] for x in f2.get("withdrawn", [])) != e["r2_withdrawn"]:
        fail("changed-source: revision 2 does not withdraw exactly the revision 1 items")
    if sorted(p["practice_id"] for p in f3["items"]) != sorted(p["practice_id"] for p in f1["items"]):
        fail("changed-source: re-approved items did not come back with the same practice IDs")

    c = cases["duplicate-correction"]
    pkt, props, prev = load(d, c["packet"]), load(d, c["proposals"]), load(d, c["preview"])
    e = c["expect"]
    if not (pkt["packet_id"] == props["packet_id"] == prev["packet_id"]) or prev.get("read_only") is not True:
        fail("duplicate-correction: packet, proposals and preview must name one packet, and the preview must be read-only")
    got = {r["proposal_id"]: r["class"] for r in prev["rows"]}
    if got != e["classes"]:
        fail(f"duplicate-correction: classes {got} differ from the case")
    texts = {}
    for p in props["proposals"]:
        if p.get("type") == "correction":
            texts.setdefault((p["target_id"], " ".join(p["text"].split())), []).append(p["proposal_id"])
    dups = [ids for ids in texts.values() if len(ids) > 1]
    if not dups or any(got[i] != "duplicate" for ids in dups for i in ids[1:]):
        fail("duplicate-correction: a repeated correction must be classed duplicate after its first occurrence")
    if not e["feed_unchanged_by_the_correction"] or e["feed_sha256_before_accept"] != e["feed_sha256_after_accept"]:
        fail("duplicate-correction: accepting a correction changed the feed")

    c = cases["study-packet-without-answers"]
    pkt = load(d, c["packet"])
    body = read(d, c["packet"]) + read(d, c["markdown"])
    if pkt.get("mode") != "study" or pkt.get("rubrics_included") is not False or any("rubric" in x for x in pkt["next_exercises"]):
        fail("study-packet: not a study packet without rubrics")
    leaked = [s for s in c["expect"]["forbidden_strings"] if s in body]
    if leaked or not c["expect"]["forbidden_strings"]:
        fail(f"study-packet: answer keys present: {leaked}" if leaked else "study-packet: no forbidden strings to check")

    print(f"bundle {os.path.basename(d)}: {len(feeds)} feeds, {sum(len(f['items']) for f in feeds.values())} practice items, "
          f"outcomes {', '.join(sorted(seen_outcomes))}; cases {', '.join(sorted(cases))}")
    for p in problems:
        print("FAIL " + p)
    print("verify: " + ("OK" if not problems else f"{len(problems)} problem(s)"))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
