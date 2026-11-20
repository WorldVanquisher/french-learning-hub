#!/usr/bin/env python3
"""One offline index over stand-in run evidence (R4-REL-056 to R4-REL-060). Standard library only.

  evidence_index.py RUN_DIR [RUN_DIR ...] --out INDEX.md [--approve RUN_ID]

A run directory holds results.jsonl (one row per gate: item, step, status, expected, actual, run_id,
source_commit, artifact, artifact_sha256, collected_at) and, when the run finished, summary.json
(flh-r4-rehearsal/v1: run_id, start/end, candidate, rollback, rows_sha256). The index:
- lists every gate with its item, status, source commit, artifact and collection time;
- marks a run PARTIAL when summary.json is missing, its rows_sha256 does not match results.jsonl, a
  results.jsonl line is unreadable, or results.tsv (the stand-in recorder's step log) is missing, and
  names the recovery (re-run into a NEW directory: evidence is never edited);
- redacts home paths and private endpoints (private IPv4 ranges, *.ts.net names, e-mail) in everything
  it writes;
- keeps runs apart: a row whose run_id differs from its directory's summary is refused.
--approve RUN_ID answers APPROVABLE only when exactly that run is COMPLETE with every gate PASS, and
refuses evidence that mixes runs. Exit 0 index written (and approvable when asked), 1 refused, 2 unreadable.
"""
import argparse
import hashlib
import json
import os
import re
import sys

FORMAT = "flh-r4-rehearsal/v1"
REDACT = [
    (re.compile(r"/(?:home|Users)/[^/\s\"']+"), "~"),
    (re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"), "<private-ip>"),
    (re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"), "<cgnat-ip>"),
    (re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.ts\.net\b"), "<tailnet-name>"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<e-mail>"),
]


def redact(text):
    for rx, rep in REDACT:
        text = rx.sub(rep, text)
    return text


def load_run(d):
    run = {"dir": d, "rows": [], "problems": [], "summary": None}
    rp = os.path.join(d, "results.jsonl")
    if not os.path.isfile(rp):
        run["problems"].append("results.jsonl missing: no gate was recorded")
        return run
    raw = open(rp, "rb").read()
    for i, line in enumerate(raw.decode().splitlines(), 1):
        try:
            run["rows"].append(json.loads(line))
        except ValueError:
            run["problems"].append(f"results.jsonl line {i} unreadable (an interrupted write)")
    sp = os.path.join(d, "summary.json")
    if os.path.isfile(sp):
        s = json.load(open(sp))
        run["summary"] = s
        if s.get("format") != FORMAT:
            run["problems"].append(f"summary format {s.get('format')!r}")
        if s.get("rows_sha256") != hashlib.sha256(raw).hexdigest():
            run["problems"].append("results.jsonl changed after summary.json was written (rows_sha256 differs)")
    else:
        run["problems"].append("summary.json missing: the run did not finish")
    ids = {r.get("run_id") for r in run["rows"]}
    want = (run["summary"] or {}).get("run_id") or (sorted(ids)[0] if ids else None)
    run["run_id"] = want
    foreign = sorted(i for i in ids if i != want)
    if foreign:
        run["problems"].append(f"rows of other runs mixed in: {', '.join(foreign)}")
    for need in ("results.tsv",):
        if not os.path.isfile(os.path.join(d, need)):
            run["problems"].append(f"{need} missing (the stand-in recorder's log of every step)")
    run["state"] = "COMPLETE" if not run["problems"] else "PARTIAL"
    return run


def render(runs):
    out = ["# Stand-in evidence index (offline)", "",
           "Each run below is a separate body of evidence. An approval names exactly one run_id; rows of "
           "different runs never add up to one approval.", ""]
    for run in runs:
        s = run["summary"] or {}
        out.append(f"## Run `{run['run_id']}`: {run['state']}")
        out.append("")
        out.append(f"- directory: `{os.path.basename(run['dir'].rstrip('/'))}`")
        if s:
            out.append(f"- candidate: `{s.get('artifact')}` sha256 `{s.get('artifact_sha256')}` (source commit `{s.get('source_commit')}`)")
            out.append(f"- rollback: `{s.get('rollback')}`; started {s.get('started_at')}, ended {s.get('ended_at')}")
            out.append(f"- counts: {s.get('counts')}")
        for p in run["problems"]:
            out.append(f"- **PARTIAL:** {p}")
        if run["problems"]:
            out.append("- **recovery:** keep this directory as it is (evidence is never edited); re-run the rehearsal into a "
                       "NEW directory; approve only a COMPLETE run.")
        out.append("")
        out.append("| Item | Step | Status | Source commit | Artifact | Collected | Expected | Actual |")
        out.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for r in run["rows"]:
            cells = [r.get("item"), r.get("step"), r.get("status"), (r.get("source_commit") or "")[:12],
                     (r.get("artifact_sha256") or "")[:12], r.get("collected_at"), r.get("expected"), r.get("actual")]
            out.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in cells) + " |")
        out.append("")
    return redact("\n".join(out) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--approve")
    a = ap.parse_args()
    try:
        runs = [load_run(d) for d in a.runs]
    except (OSError, ValueError) as e:
        print(f"evidence_index: unreadable: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    with open(a.out, "w") as fh:
        fh.write(render(runs))
    for run in runs:
        print(f"{run['state']:8} {run['run_id']}: {len(run['rows'])} row(s)"
              + "".join(f"\n         - {redact(p)}" for p in run["problems"]))
    if a.approve:
        mine = [r for r in runs if r["run_id"] == a.approve]
        others = [r for r in runs if r["run_id"] != a.approve]
        if len(mine) != 1:
            print(f"REFUSED: {len(mine)} run(s) with run_id {a.approve}; an approval names exactly one")
            return 1
        run = mine[0]
        fails = [r for r in run["rows"] if r.get("status") != "PASS"]
        if run["state"] != "COMPLETE" or fails:
            print(f"REFUSED: run {a.approve} is {run['state']} with {len(fails)} failing gate(s)")
            return 1
        if others:
            print(f"NOTE: {len(others)} other run(s) indexed alongside; they are not part of this approval")
        print(f"APPROVABLE: run {a.approve} is COMPLETE, {len(run['rows'])} gates PASS, candidate "
              f"{run['summary'].get('artifact')} sha256 {run['summary'].get('artifact_sha256')}")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
