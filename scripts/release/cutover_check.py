#!/usr/bin/env python3
"""Record and check the NAS -> AWS cutover from operator evidence (CUTOVER_DRY_RUN.md).
Standard library only, Python 3.9 (the AWS host runs it from the bundle's repo/ copy).

  cutover_check.py record EVIDENCE.jsonl --step STEP --host nas|aws|client
                   [--db APP_DB] [--ready-url URL] [--http-code N] [--file F] [--note TEXT]
      Appends one measurement. With --db it computes, from a scratch copy (the database is
      never opened in place): the ledger, integrity, and per table the row count, max rowid
      and a digest (sorted rows; stored, never printed). --ready-url fetches /readyz (loopback
      only); --file records a SHA-256. Nothing is copied by hand but the evidence lines.
  cutover_check.py check EVIDENCE.jsonl [--json]
      The checklist with PASS / FAIL / PENDING per step, the final write boundary, the freeze
      window, the divergent-write window and the verdict with one next action:
        HOLD            steps still pending before the switch
        DO-NOT-SWITCH   a check before the traffic change failed: the NAS stays the only writer
        SWITCHED        AWS is the writer; the NAS is unchanged since its boundary
        ROLLBACK-A      AWS accepted no write: move the NAS settings back and start it
        ROLLBACK-B      AWS accepted writes: procedure B only (a NAS restart would discard them)
        ROLLED-BACK     the NAS holds the AWS backup's data
        DIVERGED        both sides were written after the boundary: stop both, never merge
      Exit 0 for SWITCHED and ROLLED-BACK, 1 otherwise, 2 unreadable evidence.
  cutover_check.py template [--out FILE]
      The owner's validation template for DNS, identity and routing (placeholders only).

Steps: C1-aws-empty, C2-boundary (NAS stopped: T0 and the final write boundary), C3-backup,
C4-sent, C4-received, C5-restored, C6-smoke, C7-switch (T1), C8-first-write, N-check (any later
NAS measurement), A-check (AWS stopped, at a rollback decision), R-restored (NAS after
procedure B).
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request

FORMAT = "flh-cutover-evidence/v1"
STEPS = ["C1-aws-empty", "C2-boundary", "C3-backup", "C4-sent", "C4-received", "C5-restored", "C6-smoke",
         "C7-switch", "C8-first-write", "N-check", "A-check", "R-restored"]
# Stable verdicts (docs/RELEASE.md "Reason codes"; scripts/release/test_reason_codes.py pins them).
VERDICTS = ("HOLD", "DO-NOT-SWITCH", "SWITCHED", "ROLLBACK-A", "ROLLBACK-B", "ROLLED-BACK", "DIVERGED")
BEFORE_SWITCH = ["C2-boundary", "C3-backup", "C4-sent", "C4-received", "C5-restored", "C6-smoke"]


def utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def db_measure(db):
    """Ledger, integrity and per-table (rows, max rowid, digest) from a scratch copy of db."""
    src = os.path.dirname(os.path.abspath(db))
    td = tempfile.mkdtemp(prefix="flh-cutover-")
    try:
        for suffix in ("", "-wal", "-shm"):
            if os.path.isfile(db + suffix):
                shutil.copyfile(db + suffix, os.path.join(td, "app.db" + suffix))
        con = sqlite3.connect("file:" + os.path.join(td, "app.db") + "?mode=ro", uri=True)
        try:
            names = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            tables = {}
            for n in names:
                rows = con.execute('SELECT * FROM "%s"' % n.replace('"', '""')).fetchall()
                try:
                    mx = con.execute('SELECT coalesce(max(rowid), 0) FROM "%s"' % n.replace('"', '""')).fetchone()[0]
                except sqlite3.Error:
                    mx = None
                h = hashlib.sha256()
                for line in sorted(repr(r) for r in rows):
                    h.update(line.encode() + b"\n")
                tables[n] = [len(rows), mx, h.hexdigest()]
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            con.close()
    finally:
        shutil.rmtree(td, ignore_errors=True)
    whole = hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()
    return {"source": os.path.basename(src), "ledger": (tables.get("schema_migrations") or [0])[0],
            "integrity": integrity, "tables": tables, "digest": whole}


def cmd_record(a):
    m = {"format": FORMAT, "step": a.step, "host": a.host, "at": utc()}
    if a.db:
        if os.path.isfile(a.db):
            m["db"] = db_measure(a.db)
        else:
            m["db"] = None                          # no database there (C1: the target is empty)
    if a.ready_url:
        host = urllib.request.urlparse(a.ready_url).hostname
        if host not in ("127.0.0.1", "localhost", "::1"):
            print("cutover_check: --ready-url must be a loopback URL", file=sys.stderr)
            return 2
        try:
            with urllib.request.urlopen(a.ready_url, timeout=5) as r:
                m["ready"] = r.status == 200
        except (urllib.error.URLError, OSError):
            m["ready"] = False
    if a.http_code is not None:
        m["http_code"] = a.http_code
    if a.file:
        m["file"] = {"name": os.path.basename(a.file), "sha256": sha_file(a.file), "bytes": os.path.getsize(a.file)}
    if a.note:
        m["note"] = a.note
    lead = ""
    if os.path.isfile(a.evidence) and os.path.getsize(a.evidence):
        with open(a.evidence, "rb") as fh:
            fh.seek(-1, os.SEEK_END)
            lead = "" if fh.read(1) == b"\n" else "\n"     # an earlier record was cut short: start a new line
    with open(a.evidence, "a") as fh:
        fh.write(lead + json.dumps(m, sort_keys=True) + "\n")
    os.chmod(a.evidence, 0o600)
    db = m.get("db")
    print(f"recorded {a.step} on {a.host} at {m['at']}" + (f": ledger {db['ledger']}, integrity {db['integrity']}, "
                                                          f"{len(db['tables'])} tables" if db else "")
          + (f", ready {m['ready']}" if "ready" in m else "") + (f", http {m['http_code']}" if "http_code" in m else "")
          + (f", {m['file']['name']} sha256 {m['file']['sha256'][:16]}..." if "file" in m else ""))
    return 0


IGNORED = []


def load(path):
    """Records in order. A line that is not JSON (a record cut short by an interrupted run) is
    ignored and reported; a JSON line of another format or step is an error."""
    out = []
    del IGNORED[:]
    with open(path) as fh:
        for i, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                m = json.loads(line)
            except ValueError:
                IGNORED.append(i)
                continue
            if m.get("format") != FORMAT or m.get("step") not in STEPS:
                raise ValueError(f"line {i}: not a {FORMAT} record of a known step")
            out.append(m)
    return out


def delta(base, other):
    """Per table: rows added (count difference) and whether the rows differ. No value is shown."""
    out = []
    bt, ot = base["tables"], other["tables"]
    for t in sorted(set(bt) | set(ot)):
        b, o = bt.get(t), ot.get(t)
        if b == o:
            continue
        out.append({"table": t, "rows_before": b[0] if b else None, "rows_now": o[0] if o else None,
                    "added": (o[0] if o else 0) - (b[0] if b else 0)})
    return out


def describe(rows):
    return ", ".join(f"{r['table']} {r['added']:+d}" if r["added"] else f"{r['table']} changed" for r in rows)


def evaluate(ev):
    last = {}
    for m in ev:
        last[m["step"]] = m
    rows = []

    def row(step, status, what):
        rows.append({"step": step, "status": status, "check": what})
        return status

    bnd = last.get("C2-boundary")
    bdb = (bnd or {}).get("db")
    row("C1-aws-empty", "PASS" if last.get("C1-aws-empty", {}).get("db", 1) is None else
        "PENDING" if "C1-aws-empty" not in last else "FAIL", "AWS data moved aside: no database at the target path")
    row("C2-boundary", "PASS" if bdb and bdb["integrity"] == "ok" else "PENDING" if not bnd else "FAIL",
        "T0: the NAS stopped; its state recorded as the final write boundary")
    same = lambda step: (last.get(step) or {}).get("db") and bdb and last[step]["db"]["digest"] == bdb["digest"]
    for step, what in (("C3-backup", "the final NAS backup == the boundary"),
                       ("C4-transfer", "the archive's SHA-256 on arrival == when sent"),
                       ("C5-restored", "AWS after restore == the boundary, integrity ok, ready")):
        if step == "C4-transfer":
            s, r = last.get("C4-sent"), last.get("C4-received")
            row(step, "PENDING" if not (s and r) else "PASS" if s["file"]["sha256"] == r["file"]["sha256"] else "FAIL", what)
            continue
        m = last.get(step)
        ok = same(step) and m["db"]["integrity"] == "ok" and (step != "C5-restored" or m.get("ready") is True)
        row(step, "PENDING" if not m else "PASS" if ok else "FAIL", what)
    m = last.get("C6-smoke")
    row("C6-smoke", "PENDING" if not m else "PASS" if m.get("http_code") == 200 and m.get("ready") and same("C6-smoke")
        else "FAIL", "replay of a stored capture 200, ready, AWS still == the boundary (no new data)")
    gate = [x for x in rows if x["status"] == "FAIL"]
    pending = [x for x in rows if x["status"] == "PENDING"]
    t1 = last.get("C7-switch")
    row("C7-switch", "PASS" if t1 else "PENDING", "T1: private access points at AWS")
    fw = last.get("C8-first-write")
    row("C8-first-write", "PENDING" if not fw else "PASS" if fw.get("http_code") == 201 else "FAIL",
        "the owner's first real write on AWS: 201")
    facts = {"boundary": None, "freeze_seconds": None, "aws_writes": [], "nas_writes": [], "window_seconds": None}
    if bnd:
        facts["boundary"] = {"at": bnd["at"], "ledger": bdb["ledger"] if bdb else None,
                             "max_rowids": {t: v[1] for t, v in (bdb or {}).get("tables", {}).items()
                                            if t in ("learning_entries", "learning_captures", "knowledge_units",
                                                     "listening_materials", "speaking_takes")}}
    if bnd and t1:
        facts["freeze_seconds"] = int((parse_utc(t1["at"]) - parse_utc(bnd["at"])).total_seconds())
    n, a = last.get("N-check"), last.get("A-check")
    if bdb and n and n.get("db"):
        facts["nas_writes"] = delta(bdb, n["db"])
    if bdb and a and a.get("db"):
        facts["aws_writes"] = delta(bdb, a["db"])
        if t1:
            facts["window_seconds"] = int((parse_utc(a["at"]) - parse_utc(t1["at"])).total_seconds())
    rr = last.get("R-restored")
    verdict, nxt = None, None
    if facts["nas_writes"] and (facts["aws_writes"] or fw):
        verdict = "DIVERGED"
        nxt = ("both sides were written after the final write boundary (NAS: " + describe(facts["nas_writes"])
               + "; AWS: " + (describe(facts["aws_writes"]) or "the first write") + "). Stop both now and move both "
               "settings files aside. Never merge two SQLite databases: the owner picks one side, keeps the other "
               "side's backup, and re-enters that side's captures by capture_id (CUTOVER_DRY_RUN.md, case C)")
    elif facts["nas_writes"] and t1:
        verdict = "ROLLBACK-A"
        nxt = ("the NAS was written after its final write boundary (" + describe(facts["nas_writes"]) + ") while AWS "
               "took no write: the NAS holds the newest state. Stop AWS, point private access back to the NAS, and "
               "redo the cutover from step 2 with a new boundary")
    elif facts["nas_writes"]:
        verdict = "DO-NOT-SWITCH"
        nxt = ("the NAS changed after its final write boundary (" + describe(facts["nas_writes"]) + "): the backup no "
               "longer holds its newest state. Do not switch; start again from step 2 (a new boundary)")
    elif rr:
        ok = rr.get("db") and a and a.get("db") and rr["db"]["digest"] == a["db"]["digest"] and rr["db"]["integrity"] == "ok"
        verdict = "ROLLED-BACK" if ok else "ROLLBACK-B"
        nxt = ("the NAS holds the AWS backup's data, integrity ok: point private access back to the NAS and keep AWS "
               "stopped and guarded until the post-rollback check" if ok else
               "the NAS does not hold the AWS backup's data yet: finish procedure B (restore the AWS backup on the NAS)")
    elif a and t1:
        if facts["aws_writes"]:
            verdict = "ROLLBACK-B"
            nxt = (f"AWS accepted writes after T1 ({describe(facts['aws_writes'])}). WARNING: restarting the NAS now "
                   f"would discard {sum(max(r['added'], 0) for r in facts['aws_writes'])} new row(s) in "
                   f"{len(facts['aws_writes'])} table(s) written in the last {facts['window_seconds']} s. "
                   "Roll back only with procedure B: AWS backup, guard AWS, transfer, restore on the NAS")
        else:
            verdict = "ROLLBACK-A"
            nxt = ("AWS accepted no write since the boundary: nothing is lost. Move the NAS settings file back, "
                   "`flh-daily.sh start` on the NAS, point private access back, keep AWS stopped")
    elif gate and not t1:
        verdict = "DO-NOT-SWITCH"
        nxt = ("a check before the traffic change failed (" + ", ".join(x["step"] for x in gate) + "): keep private "
               "access on the NAS; AWS has taken no write. Roll back (case A): move the NAS settings file back and "
               "start the NAS; fix AWS, then begin again at step 1")
    elif gate and t1:
        verdict = "ROLLBACK-A" if not fw else "ROLLBACK-B"
        nxt = "private access was switched although a check failed (" + ", ".join(x["step"] for x in gate) + "): " + \
              "stop AWS, record A-check, and follow the rollback the check then names"
    elif pending and not t1:
        verdict = "HOLD"
        nxt = "next: " + pending[0]["step"] + " (" + pending[0]["check"] + "); do not switch before every check passes"
    elif t1:
        verdict = "SWITCHED"
        nxt = ("AWS is the only writer. Keep the NAS stopped and intact for the rollback window; record N-check to prove "
               "it, and A-check (AWS stopped) before any rollback decision")
    else:
        verdict, nxt = "HOLD", "record C1-aws-empty and C2-boundary first"
    return {"verdict": verdict, "next_action": nxt, "checklist": rows, "facts": facts}


def cmd_check(a):
    try:
        ev = load(a.evidence)
    except (OSError, ValueError) as e:
        print(f"cutover_check: unreadable evidence: {e}", file=sys.stderr)
        return 2
    r = evaluate(ev)
    r["ignored_lines"] = list(IGNORED)
    if IGNORED:
        print(f"WARNING ignored {len(IGNORED)} incomplete line(s) {IGNORED} (a record cut short by an interrupted run): "
              "record that step again if it is not listed below", file=sys.stderr if a.json else sys.stdout)
    if a.json:
        print(json.dumps(r, indent=1, sort_keys=True))
    else:
        for x in r["checklist"]:
            print(f"{x['status']:<8} {x['step']:<16} {x['check']}")
        f = r["facts"]
        if f["boundary"]:
            print(f"final write boundary: T0 {f['boundary']['at']}, ledger {f['boundary']['ledger']}, max rowids "
                  + ", ".join(f"{k} {v}" for k, v in sorted(f["boundary"]["max_rowids"].items())))
        if f["freeze_seconds"] is not None:
            print(f"freeze window (T1 - T0): {f['freeze_seconds']} s")
        if f["aws_writes"]:
            print(f"divergent writes on AWS since the boundary ({f['window_seconds']} s after T1): {describe(f['aws_writes'])}")
        if f["nas_writes"]:
            print(f"writes on the NAS after its boundary: {describe(f['nas_writes'])}")
        print(f"{r['verdict']}: {r['next_action']}")
    return 0 if r["verdict"] in ("SWITCHED", "ROLLED-BACK") else 1


TEMPLATE = """# Owner validation: DNS, identity and routing (cutover {RUN})

OWNER-ONLY. Fill in on the owner's machine; keep this file private (it names hosts and IDs).
Nothing here is run by an agent. `<...>` is a value to write down; a row without a value has not
been checked.

## Before T0 (read-only)

| Check | Command (owner) | Recorded value | Same after T1? |
| --- | --- | --- | --- |
| Public demo DNS A | `dig +short A <PUBLIC_DEMO_NAME>` | <A_RECORDS> | |
| Public demo DNS AAAA | `dig +short AAAA <PUBLIC_DEMO_NAME>` | <AAAA_RECORDS> | |
| CAA | `dig +short CAA <APEX>` | <CAA> | |
| Name servers | `dig +short NS <APEX>` | <NS> | |
| AWS identity | `aws sts get-caller-identity --query Account --output text` | <ACCOUNT_ID> (write it here only) | |
| Staging instance | `terraform output -raw instance_id` | <INSTANCE_ID> | |
| Bundle identity on AWS | `flh-staging-bundle status` (commit, tree, image) | <COMMIT> / <TREE> / <IMAGE_ID> | |
| NAS release | `docker image inspect -f '{{{{.Id}}}}' french-learning-hub:local` | <NAS_IMAGE_ID> | |

## Routing (the learner's private access)

| Check | Command (owner) | Before T1 | After T1 |
| --- | --- | --- | --- |
| Where the alias points | the SSH/SSM alias or tailnet name the browser uses: `<ALIAS>` | NAS | AWS |
| What answers there | `curl -fsS http://127.0.0.1:<LOCAL_PORT>/readyz` through the alias | <NAS ready> | <AWS ready> |
| Which data answers | the newest capture_id visible in the workbench | <CAPTURE_ID> | the same |
| No public exposure | `dig` rows above unchanged; no inbound rule (`preflight.py` public binding) | | |

## Decision

- Rollback window: <DAYS> days; decided by <WHO>.
- Verdict of `cutover_check.py check` at T1: <VERDICT>.
- Signed off: <DATE>.
"""


def cmd_template(a):
    text = TEMPLATE.format(RUN=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d"))
    if a.out:
        with open(a.out, "w") as fh:
            fh.write(text)
        os.chmod(a.out, 0o600)
        print(f"wrote {a.out} (0600)")
    else:
        print(text, end="")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("evidence")
    r.add_argument("--step", required=True, choices=STEPS)
    r.add_argument("--host", required=True, choices=["nas", "aws", "client"])
    r.add_argument("--db")
    r.add_argument("--ready-url")
    r.add_argument("--http-code", type=int)
    r.add_argument("--file")
    r.add_argument("--note")
    c = sub.add_parser("check")
    c.add_argument("evidence")
    c.add_argument("--json", action="store_true")
    t = sub.add_parser("template")
    t.add_argument("--out")
    a = ap.parse_args()
    return {"record": cmd_record, "check": cmd_check, "template": cmd_template}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
