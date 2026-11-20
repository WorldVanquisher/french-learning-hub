#!/usr/bin/env python3
"""R4 cutover edges on synthetic SQLite files with scripts/release/cutover_check.py (no Docker, no network).

  r4_cutover_edges.py WORK_DIR

A  stale source snapshot (R4-REL-047): the "final backup" was taken before the NAS's last write.
   cutover_check must say DO-NOT-SWITCH; after a fresh backup (taken with the NAS stopped) it must
   no longer fail C3.
B  unexpected writes after the switch (R4-REL-048): AWS took the first write, and the NAS was written
   too. The verdict must be DIVERGED; the documented recovery is in CUTOVER_DRY_RUN.md (stop both, never
   merge, the owner picks a side, re-enter captures by capture_id).
C  only the NAS written after the switch, AWS untouched: ROLLBACK-A (point access back to the NAS).
Every verdict comes from cutover_check.py; the evidence files stay in WORK_DIR.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys

REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))
CC = os.path.join(REPO, "scripts", "release", "cutover_check.py")


def make_db(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT);"
                      "CREATE TABLE learning_entries (id INTEGER PRIMARY KEY, original_input TEXT);"
                      "CREATE TABLE learning_captures (id INTEGER PRIMARY KEY, capture_id TEXT UNIQUE);")
    con.executemany("INSERT INTO schema_migrations VALUES (?, '2026-11-20')", [(f"{i:03d}_x.sql",) for i in range(1, 22)])
    for i in range(rows):
        con.execute("INSERT INTO learning_entries (original_input) VALUES (?)", (f"synthetic entry {i}",))
    con.commit()
    con.close()


def write(path, text):
    con = sqlite3.connect(path)
    con.execute("INSERT INTO learning_entries (original_input) VALUES (?)", (text,))
    con.commit()
    con.close()


def rec(ev, step, host, db=None, **kw):
    cmd = [sys.executable, "-I", "-B", CC, "record", ev, "--step", step, "--host", host]
    if db:
        cmd += ["--db", db]
    for k, v in kw.items():
        cmd += [f"--{k.replace('_', '-')}", str(v)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"record {step} failed: {r.stderr.strip()}")


def verdict(ev):
    r = subprocess.run([sys.executable, "-I", "-B", CC, "check", ev], capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    v = next((l for l in reversed(lines) if l.startswith("VERDICT")), lines[-1] if lines else "")
    return r.returncode, v, r.stdout


def main():
    work = sys.argv[1]
    if os.path.exists(work):
        raise SystemExit(f"refused: {work} exists")
    os.makedirs(work)
    results = []

    def row(item, scen, ok, expected, actual):
        results.append({"item": item, "scenario": scen, "status": "PASS" if ok else "FAIL", "expected": expected, "actual": actual})
        print(f"{'PASS' if ok else 'FAIL'} [{item}] {scen}: {expected} -> {actual}")

    # A: a stale snapshot ------------------------------------------------------------------------------
    nas = os.path.join(work, "A", "nas", "app.db")
    make_db(nas, 5)
    stale = os.path.join(work, "A", "stale-backup", "app.db")
    os.makedirs(os.path.dirname(stale))
    shutil.copy(nas, stale)                          # a snapshot taken earlier...
    write(nas, "written after the snapshot")         # ...then the learner wrote once more before T0
    ev = os.path.join(work, "A", "evidence.jsonl")
    rec(ev, "C2-boundary", "nas", nas)
    rec(ev, "C3-backup", "nas", stale)
    rc, v, out = verdict(ev)
    row("R4-REL-047", "A stale snapshot", "DO-NOT-SWITCH" in out and "C3-backup" in out and "FAIL" in out,
        "the backup is older than the boundary: DO-NOT-SWITCH", v)
    fresh = os.path.join(work, "A", "fresh-backup", "app.db")
    os.makedirs(os.path.dirname(fresh))
    shutil.copy(nas, fresh)                          # a fresh backup with the NAS stopped (T0)
    rec(ev, "C3-backup", "nas", fresh)
    rc, v2, out2 = verdict(ev)
    c3 = next((l for l in out2.splitlines() if "C3-backup" in l), "")
    row("R4-REL-047", "A fresh backup", "PASS" in c3, "after a fresh backup C3 passes (the next steps follow)", c3.strip()[:120])

    # B: writes on both sides after the switch ------------------------------------------------------------
    nas_b = os.path.join(work, "B", "nas", "app.db")
    make_db(nas_b, 5)
    aws_b = os.path.join(work, "B", "aws", "app.db")
    os.makedirs(os.path.dirname(aws_b))
    ev = os.path.join(work, "B", "evidence.jsonl")
    rec(ev, "C2-boundary", "nas", nas_b)
    shutil.copy(nas_b, aws_b)
    rec(ev, "C3-backup", "nas", aws_b)
    rec(ev, "C5-restored", "aws", aws_b)
    rec(ev, "C7-switch", "client")
    write(aws_b, "first write on AWS")
    rec(ev, "C8-first-write", "aws", http_code=201)
    write(nas_b, "an unexpected write on the NAS after T1")
    rec(ev, "N-check", "nas", nas_b)
    rec(ev, "A-check", "aws", aws_b)
    rc, v, out = verdict(ev)
    row("R4-REL-048", "B both sides written", "DIVERGED" in v, "DIVERGED: stop both, never merge, the owner picks", v)

    # C: only the NAS written after the switch -------------------------------------------------------------
    nas_c = os.path.join(work, "C", "nas", "app.db")
    make_db(nas_c, 5)
    aws_c = os.path.join(work, "C", "aws", "app.db")
    os.makedirs(os.path.dirname(aws_c))
    ev = os.path.join(work, "C", "evidence.jsonl")
    rec(ev, "C2-boundary", "nas", nas_c)
    shutil.copy(nas_c, aws_c)
    rec(ev, "C3-backup", "nas", aws_c)
    rec(ev, "C5-restored", "aws", aws_c)
    rec(ev, "C7-switch", "client")
    write(nas_c, "the NAS kept being used by habit")
    rec(ev, "N-check", "nas", nas_c)
    rec(ev, "A-check", "aws", aws_c)
    rc, v, out = verdict(ev)
    row("R4-REL-048", "C NAS-only writes", "ROLLBACK-A" in v, "ROLLBACK-A: AWS took no write; point access back to the NAS", v)
    with open(os.path.join(work, "results.json"), "w") as fh:
        json.dump(results, fh, indent=1)
    bad = [r for r in results if r["status"] != "PASS"]
    print(f"CUTOVER EDGES: {len(results) - len(bad)} PASS, {len(bad)} FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
