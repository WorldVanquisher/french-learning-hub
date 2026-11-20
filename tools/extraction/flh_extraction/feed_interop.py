"""Feed interoperability with the merged Workbooks consumer (R4; offline, standard library only).

  python3 -B -m flh_extraction.feed_interop [--workbooks-results RESULTS.json] [--json OUT] [--md OUT]

``feed_compat.consumer_issues`` mirrors the Workbooks parser as sealed in its increment-4
handoff. It is kept unchanged because sealed outputs depend on it. In that version an
all-withdrawn feed was refused. The merged parser at base ``58c0ba8b``
(``web/src/prototype/practiceFeed.ts`` ``parseFeed``) accepts an empty ``items`` list.
``merged_consumer_issues`` mirrors that merged rule set.

The report runs every feed sample in ``fixtures/`` through:
- the contract (``feed_compat.contract_issues``);
- both consumer mirrors;
- the reference client (``feed_compat.client_apply``) on the R4 lifecycle replay cases, a feed
  with an unknown reason code and one with no reason code.

With ``--workbooks-results`` it also compares the mirrors with an actual run of the merged
TypeScript parser and client over the same files (the scratch harness described in
``docs/validation/EXTRACTION-R4.md``).

Forward-compatible rule for reason codes (``flh_practice_feed_additions_v1``, R4):
``reason_code`` is an open set.
- **Producer:** may add codes, and never reuses a code with another meaning.
- **Consumer:** must
  - accept any non-empty string;
  - keep it verbatim with the withdrawn ID;
  - show a general sentence for a code it does not know;
  - never refuse a feed or drop an item because of it.
- **Absent code:** means ``unspecified``.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys

from . import feed_compat as fc

SCHEMA = "flh_feed_interop_report_v1"
WORKBOOKS_BASE = "58c0ba8b"
WORKBOOKS_KNOWN_CODES = ("awaiting_confirmation", "rule_not_approved")  # web/src/prototype/reasonCodes.ts at the base
BANNED = ("answer", "accepted", "hidden", "rubric", "due", "due_at", "interval", "text")
PID = re.compile(r"p-[0-9a-f]{12}")
KINDS = ("explain", "choose", "produce")
REASON_RULE = ("reason_code is an open set: a consumer accepts any non-empty string, keeps it verbatim, shows a general sentence "
               "for a code it does not know and never refuses a feed for it; an absent code means unspecified")
OMISSIONS = [
    ("attempt texts and free-text answers", "the feed carries outcomes (seq, action, outcome) only"),
    ("answer keys, accepted variants, rubrics, hidden reference", "they stay in the practice items behind reveal"),
    ("due dates, intervals, schedules", "when an item is due is the consumer's decision; nothing schedules"),
    ("skipped items and missing observations", "a feed records attempts and reveals only (listed in not_included)"),
    ("prompts and options of withdrawn items", "a withdrawn entry names the practice ID, kind, knowledge IDs, reason and since_revision"),
    ("evidence excerpts and the learner's question", "items cite evidence and knowledge IDs; excerpts stay with the review"),
]
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(HERE, "fixtures")


def merged_consumer_issues(f: dict) -> list[str]:
    """What the merged Workbooks parseFeed (base 58c0ba8b) refuses: mirrored rules, not its code."""
    if not isinstance(f, dict) or f.get("schema") != fc.FEED:
        return [f"not a {fc.FEED} document"]
    src = f.get("source")
    if not isinstance(src, dict):
        return ["feed: source missing"]
    out = []
    if not isinstance(src.get("revision"), int) or src["revision"] < 1:
        out.append("source.revision must be a positive integer")
    if not re.fullmatch(r"[0-9a-f]{64}", str(src.get("revision_sha256", ""))):
        out.append("source.revision_sha256 must be 64 hex characters")
    for k in ("source_id", "capture_id", "proposer"):
        if not isinstance(src.get(k), str) or not src[k]:
            out.append(f"source.{k} must be a non-empty string")
    items = f.get("items")
    if not isinstance(items, list):
        return out + ["items must be a list (an empty list is valid)"]
    seen = set()
    for i, raw in enumerate(items, 1):
        if not isinstance(raw, dict):
            out.append(f"item {i}: not an object")
            continue
        out += [f"item {i}: carries {b!r}" for b in BANNED if b in raw]
        pid = raw.get("practice_id")
        if not isinstance(pid, str) or not PID.fullmatch(pid) or pid in seen:
            out.append(f"item {i}: practice_id malformed or repeated")
        seen.add(pid)
        if raw.get("kind") not in KINDS:
            out.append(f"item {i}: unknown kind")
        if "options" in raw and not (isinstance(raw["options"], list) and all(isinstance(x, str) for x in raw["options"])):
            out.append(f"item {i}: options must be a list of strings")
        if raw.get("kind") == "choose" and not (isinstance(raw.get("options"), list) and len(raw["options"]) >= 2):
            out.append(f"item {i}: a choose item needs options")
        if not isinstance(raw.get("outcomes"), list):
            out.append(f"item {i}: outcomes must be a list")
        else:
            for o in raw["outcomes"]:
                if not (isinstance(o, dict) and isinstance(o.get("seq"), (int, float)) and not isinstance(o.get("seq"), bool)
                        and o.get("action") in ("attempt", "reveal") and o.get("outcome") in fc.OUTCOMES) \
                        or (o.get("action") == "reveal" and o.get("outcome") != "revealed"):
                    out.append(f"item {i}: an outcome outside seq / action / known outcome")
        for k in ("measures", "prompt", "grading"):
            if not isinstance(raw.get(k), str) or not raw[k]:
                out.append(f"item {i}: {k} must be a non-empty string")
        for k in ("knowledge_ids", "evidence_ids"):
            if not isinstance(raw.get(k), list) or not all(isinstance(x, str) for x in raw[k]):
                out.append(f"item {i}: {k} must be a list of strings")
    if "previous" in f:
        p = f["previous"]
        if not isinstance(p, dict) or not isinstance(p.get("revision"), int) or p["revision"] < 1 \
                or not re.fullmatch(r"[0-9a-f]{64}", str(p.get("revision_sha256", ""))):
            out.append("previous needs a revision and a 64-hex revision_sha256")
    if "withdrawn" in f:
        if not isinstance(f["withdrawn"], list):
            out.append("withdrawn must be a list")
        else:
            for i, w in enumerate(f["withdrawn"], 1):
                if not isinstance(w, dict):
                    out.append(f"withdrawn {i}: not an object")
                    continue
                pid = w.get("practice_id")
                if not isinstance(pid, str) or not PID.fullmatch(pid) or pid in seen:
                    out.append(f"withdrawn {i}: malformed, repeated or still offered")
                seen.add(pid)
                if w.get("kind") not in KINDS:
                    out.append(f"withdrawn {i}: unknown kind")
                if not isinstance(w.get("reason"), str) or not w["reason"]:
                    out.append(f"withdrawn {i}: reason must be a non-empty string")
    return out


def samples(root: str = FIX) -> dict:
    out = {}
    for dp, _, fs in sorted(os.walk(root)):
        for n in sorted(fs):
            if not n.endswith(".json"):
                continue
            p = os.path.join(dp, n)
            with open(p, encoding="utf-8") as fh:
                try:
                    x = json.load(fh)
                except ValueError:
                    continue
            feed = x if isinstance(x, dict) and x.get("schema") == fc.FEED else ((x.get("body") or {}).get("feed") if isinstance(x, dict) else None)
            if isinstance(feed, dict) and feed.get("schema") == fc.FEED:
                out[os.path.relpath(p, root)] = feed
    return out


def _apply_all(docs: list[dict]) -> tuple[list[str], dict]:
    st: dict = {}
    acts = [fc.client_apply(st, copy.deepcopy(d)) for d in docs]
    return acts, st


def report(root: str = FIX, workbooks: dict | None = None) -> dict:
    sm = samples(root)
    rows = {}
    codes = set()
    for rel, f in sm.items():
        rows[rel] = {"items": len(f.get("items", [])), "withdrawn": len(f.get("withdrawn") or []), "contract": fc.contract_issues(f),
                     "increment_4_mirror": fc.consumer_issues(f), "merged_mirror": merged_consumer_issues(f)}
        codes |= {w.get("reason_code") for w in f.get("withdrawn") or [] if w.get("reason_code")}
    lc = os.path.join(root, "r4_v1", "lifecycle")
    with open(os.path.join(lc, "replay-cases.json"), encoding="utf-8") as fh:
        cases = json.load(fh)
    def load(n):
        with open(os.path.join(lc, n), encoding="utf-8") as fh:
            return json.load(fh)
    replay = fc.run_replay(cases, load)
    f1, f2, f3 = load("feed-1-r1.json"), load("feed-2-r2-withdrawn.json"), load("feed-3-r3-awaiting.json")
    unk = copy.deepcopy(f3)
    unk["withdrawn"][0]["reason_code"] = "future_code_v9"
    unk.pop("feed_id", None)
    acts, st = _apply_all([f1, f2, unk])
    miss = copy.deepcopy(f3)
    miss["withdrawn"][0].pop("reason_code")
    miss.pop("feed_id", None)
    acts2, st2 = _apply_all([f1, f2, miss])
    pid = f3["withdrawn"][0]["practice_id"]
    rep = {"schema": SCHEMA, "workbooks_base": WORKBOOKS_BASE, "samples": rows,
           "summary": {"samples": len(rows), "contract_ok": sum(not r["contract"] for r in rows.values()),
                       "increment_4_mirror_refuses": sorted(k for k, r in rows.items() if r["increment_4_mirror"]),
                       "merged_mirror_refuses": sorted(k for k, r in rows.items() if r["merged_mirror"]),
                       "empty_feeds_with_withdrawals": sorted(k for k, r in rows.items() if r["items"] == 0 and r["withdrawn"] > 0)},
           "replay_cases": {"cases": sorted(cases["cases"]), "issues": replay},
           "reason_codes": {"producer": sorted(fc.REASONS), "seen_in_samples": sorted(codes), "workbooks_known": list(WORKBOOKS_KNOWN_CODES),
                            "workbooks_general_sentence": sorted(set(fc.REASONS) - set(WORKBOOKS_KNOWN_CODES)), "rule": REASON_RULE},
           "unknown_reason_code": {"contract_issues": fc.contract_issues(unk), "merged_mirror": merged_consumer_issues(unk), "client": acts,
                                   "kept": st["items"][pid].get("withdrawn_reason")},
           "missing_reason_code": {"merged_mirror": merged_consumer_issues(miss), "client": acts2, "kept": st2["items"][pid].get("withdrawn_reason")},
           "omissions": [{"not_in_feed": a, "why": b} for a, b in OMISSIONS]}
    if workbooks:
        agree = {}
        for rel, r in rows.items():
            w = workbooks.get("samples", {}).get(rel)
            if w is not None:
                agree[rel] = w["parsed"] == (not r["merged_mirror"])
        ts_replay = {k: v["actions"] == cases["cases"][k]["expect"]["actions"] and
                     json.dumps(v["items"], sort_keys=True) == json.dumps(cases["cases"][k]["expect"]["items"], sort_keys=True)
                     for k, v in workbooks.get("replay", {}).items()}
        rep["workbooks_run"] = {"samples_compared": len(agree), "mirror_agrees": sum(agree.values()), "disagreements": sorted(k for k, v in agree.items() if not v),
                                "replay_equal": ts_replay, "unknown_reason_code": workbooks.get("unknown_reason_code"),
                                "missing_reason_code": workbooks.get("missing_reason_code"),
                                "reason_codes_known": {k: v["known"] for k, v in workbooks.get("reason_codes", {}).items()}}
    rep["ok"] = (rep["summary"]["contract_ok"] == len(rows) and not rep["summary"]["merged_mirror_refuses"] and not replay
                 and rep["unknown_reason_code"]["kept"] == "future_code_v9" and rep["missing_reason_code"]["kept"] == "unspecified"
                 and (not workbooks or (not rep["workbooks_run"]["disagreements"] and all(rep["workbooks_run"]["replay_equal"].values()))))
    return rep


def markdown(rep: dict) -> str:
    s = rep["summary"]
    L = ["# Feed interoperability (R4)", "",
         f"{s['samples']} feed samples; contract OK {s['contract_ok']}; refused by the merged Workbooks parser mirror: "
         f"{len(s['merged_mirror_refuses'])}; by the increment-4 mirror (historical): {len(s['increment_4_mirror_refuses'])} "
         f"({', '.join(s['increment_4_mirror_refuses']) or 'none'}).", "",
         f"Empty feeds with withdrawals: {', '.join(s['empty_feeds_with_withdrawals'])}.", "",
         f"Replay cases {', '.join(rep['replay_cases']['cases'])}: " + ("all hold" if not rep["replay_cases"]["issues"] else "; ".join(rep["replay_cases"]["issues"])), ""]
    rc_ = rep["reason_codes"]
    L += [f"Reason codes: producer {', '.join(rc_['producer'])}; Workbooks names {', '.join(rc_['workbooks_known'])}; shown with the "
          f"general sentence: {', '.join(rc_['workbooks_general_sentence'])}.", "", f"Rule: {rc_['rule']}.", "",
          f"Unknown code: client {rep['unknown_reason_code']['client']}, kept `{rep['unknown_reason_code']['kept']}`. "
          f"Missing code: client {rep['missing_reason_code']['client']}, kept `{rep['missing_reason_code']['kept']}`.", ""]
    if "workbooks_run" in rep:
        w = rep["workbooks_run"]
        L += [f"Merged TypeScript parser and client (scratch run): {w['mirror_agrees']}/{w['samples_compared']} samples agree with the mirror; "
              f"replay equal {w['replay_equal']}; unknown code {w['unknown_reason_code']}; missing code {w['missing_reason_code']}.", ""]
    L += ["Intentional, non-breaking omissions:", ""] + [f"- {o['not_in_feed']}: {o['why']}" for o in rep["omissions"]]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="flh_extraction.feed_interop")
    ap.add_argument("--workbooks-results")
    ap.add_argument("--json")
    ap.add_argument("--md")
    a = ap.parse_args(argv)
    wb = None
    if a.workbooks_results:
        with open(a.workbooks_results, encoding="utf-8") as fh:
            wb = json.load(fh)
    rep = report(workbooks=wb)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(rep, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    md = markdown(rep)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(md)
    print(md, end="")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
