#!/usr/bin/env python3
"""Inspect, compare and move `flh-daily.sh backup` directories without disclosing their contents
(standard library and the sqlite3 CLI only; every database is read from a scratch copy).

  backup_tool.py inspect BACKUP_DIR [--json]
      State (COMPLETE, INCOMPLETE, UNSEALED, CORRUPT, NOT_A_BACKUP), every file with size, mode and
      SHA-256 against SHA256SUMS, SQLite integrity, the migration ledger (count, last, compared with
      this checkout's migrations/), page facts, table and row totals, and the logical digest
      (SHA-256 of `sqlite3 .dump`). No row value is printed.
  backup_tool.py compare A B [--json]
      Files, ledger and, per table, row counts and whether the rows are the same (digests are
      compared, never printed). Exit 0 same logical content, 1 different, 2 unreadable.
  backup_tool.py next-action ACTIVE_DIR
      After an interrupted or failed backup: every entry of ACTIVE_DIR.backups classified, the latest
      complete one, free space against the size a new backup needs, and the safest next step.
      Deletes nothing.
  backup_tool.py restore-state ACTIVE_DIR [--record FILE]
      What an interrupted `flh-daily.sh restore` left beside ACTIVE_DIR (.restore-<stamp> staging
      copies, .before-restore-<stamp> previous data), which known copy the active data equals, and
      the safe next step; --record writes it as flh-restore-state/v1 JSON (0600).
  backup_tool.py latest DIR
      The path of the newest COMPLETE backup directory in DIR (an ACTIVE.backups directory or a
      transfer directory), for `"$(backup_tool.py latest DIR)"` instead of a typed timestamp.
      Exit 1 when DIR holds none.
  backup_tool.py pack BACKUP_DIR OUT.tar[.gz]
      A deterministic archive of the backup (gzip when the name ends in .gz) and OUT.sha256.
  backup_tool.py unpack ARCHIVE --sha256 HEX DEST_PARENT
      Verifies the SHA-256 first, then unpacks into a temporary sibling and renames it into place
      only when every member read completely and is safe. A truncated or damaged archive gets an
      actionable diagnostic and leaves nothing behind.
  backup_tool.py receipt --backup DIR --active DIR [--previous DIR] [--write-check FILE]
                         [--timings FILE] --out FILE
      flh-recovery-receipt/v1: what was restored (backup identity), what is active now (the same
      identity, or not), the previous data, the first-write check and the timings.

Exit 0 good/same, 1 a problem was found, 2 usage or unreadable input.
"""
import argparse
import datetime
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.realpath(os.path.join(HERE, "..", ".."))
DB_FILES = ("app.db", "app.db-wal", "app.db-shm")
# Stable codes (docs/RELEASE.md "Reason codes"; scripts/release/test_reason_codes.py pins them).
BACKUP_STATES = ("COMPLETE", "INCOMPLETE", "UNSEALED", "CORRUPT", "NOT_A_BACKUP")
NEXT_CODES = ("ok", "no-backup", "free-space", "rerun-backup")
RESTORE_STATES = ("CLEAN", "PREPARE-INTERRUPTED", "SWAP-INTERRUPTED", "RESTORED", "NO-ACTIVE-DATA")
ARCHIVE_VERDICTS = ("DAMAGED", "REFUSED")
RECEIPT_VERDICTS = ("RECOVERED", "NOT RECOVERED")
STAMP = r"[0-9]{8}T[0-9]{6}Z"


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_sums(d):
    p = os.path.join(d, "SHA256SUMS")
    if not os.path.isfile(p):
        return None
    out = {}
    with open(p) as fh:
        for line in fh:
            m = re.match(r"^([0-9a-f]{64})\s+\*?(.+?)\s*$", line)
            if m:
                out[m.group(2)] = m.group(1)
    return out


def scratch_db(d, td):
    """Copy app.db and its present sidecars into td, so nothing is opened in the backup itself."""
    for f in DB_FILES:
        if os.path.isfile(os.path.join(d, f)):
            shutil.copyfile(os.path.join(d, f), os.path.join(td, f))
    return os.path.join(td, "app.db")


def sqlite_dump(db, table=None):
    """SHA-256 of the logical dump (the sqlite3 CLI, the same digest the rehearsals record)."""
    args = ["sqlite3", "-readonly", db, ".dump" + (f' "{table}"' if table else "")]
    try:
        r = subprocess.run(args, capture_output=True, timeout=600)
    except OSError:
        r = None
    if r is not None and r.returncode == 0:
        return hashlib.sha256(r.stdout).hexdigest(), "sqlite3 .dump"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        h = hashlib.sha256()
        for line in con.iterdump():
            if table is None or f'"{table}"' in line or f"TABLE {table} " in line:
                h.update(line.encode() + b"\n")
        return h.hexdigest(), "python iterdump (sqlite3 CLI unavailable: not comparable with .dump digests)"
    finally:
        con.close()


def repo_migrations():
    d = os.path.join(REPO, "migrations")
    return sorted(f for f in os.listdir(d) if re.match(r"^[0-9]{3}_.*\.sql$", f)) if os.path.isdir(d) else []


def db_facts(db, per_table=False):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        f = {"integrity": con.execute("PRAGMA integrity_check").fetchone()[0]}
        for p in ("page_size", "page_count", "freelist_count", "journal_mode", "user_version"):
            f[p] = con.execute(f"PRAGMA {p}").fetchone()[0]
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {n: con.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0] for n in names}
        led = []
        if "schema_migrations" in names:
            led = [r[0] for r in con.execute("SELECT name FROM schema_migrations ORDER BY name")]
    finally:
        con.close()
    f["tables"] = len(names)
    f["rows"] = sum(v for k, v in counts.items() if k != "schema_migrations")
    f["ledger"] = {"count": len(led), "last": led[-1] if led else None, "names": led}
    if per_table:
        f["table_counts"] = counts
    return f


def inspect(d, per_table=False):
    out = {"backup": os.path.basename(os.path.normpath(d)), "files": [], "problems": []}
    if not os.path.isdir(d):
        out.update(state="NOT_A_BACKUP", problems=[f"{d} is not a directory"])
        return out
    sums = read_sums(d)
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        st = os.lstat(p)
        e = {"name": f, "bytes": st.st_size, "mode": stat.filemode(st.st_mode)}
        if stat.S_ISREG(st.st_mode):
            e["sha256"] = sha_file(p)
            if sums is not None and f != "SHA256SUMS":
                e["sums"] = "match" if sums.get(f) == e["sha256"] else "NOT LISTED" if f not in sums else "MISMATCH"
        out["files"].append(e)
    out["bytes"] = sum(e["bytes"] for e in out["files"])
    names = {e["name"] for e in out["files"]}
    if "app.db" not in names:
        out.update(state="NOT_A_BACKUP")
        out["problems"].append("no app.db: not a backup made by flh-daily.sh")
        return out
    if sums is None:
        out["problems"].append("no SHA256SUMS: the backup stopped before it was sealed")
    else:
        for f, h in sorted(sums.items()):
            if f not in names:
                out["problems"].append(f"SHA256SUMS lists {f}, which is missing")
        for e in out["files"]:
            if e.get("sums") in ("MISMATCH", "NOT LISTED") and e["name"] in DB_FILES:
                out["problems"].append(f"{e['name']}: {e['sums']} in SHA256SUMS")
    with tempfile.TemporaryDirectory(prefix="flh-backup-inspect-") as td:
        try:
            db = scratch_db(d, td)
            out["db"] = db_facts(db, per_table)
            out["dump_sha256"], out["dump_method"] = sqlite_dump(db)
        except sqlite3.Error as e:
            out["db"] = None
            out["problems"].append(f"SQLite cannot read app.db: {e}")
    if out.get("db") and out["db"]["integrity"] != "ok":
        out["problems"].append(f"integrity_check: {out['db']['integrity'][:120]}")
    mig = repo_migrations()
    if out.get("db"):
        led = out["db"]["ledger"]["names"]
        unknown = [n for n in led if n not in mig]
        out["compatibility"] = {"checkout_migrations": len(mig), "backup_ledger": len(led),
                                "unknown_to_this_checkout": unknown,
                                "pending_on_start": [m for m in mig if m not in led]}
        out["db"]["ledger"].pop("names")
    if d.rstrip("/").endswith(".incomplete"):
        out["state"] = "INCOMPLETE"
        out["problems"].insert(0, "named .incomplete: flh-daily.sh backup failed before a verified copy existed")
    elif sums is None:
        out["state"] = "UNSEALED"
    elif out["problems"]:
        out["state"] = "CORRUPT"
    else:
        out["state"] = "COMPLETE"
    return out


def cmd_inspect(a):
    r = inspect(a.backup, per_table=a.tables)
    if a.json:
        print(json.dumps(r, indent=1, sort_keys=True))
        return 0 if r["state"] == "COMPLETE" else 1
    print(f"{r['backup']}: {r['state']} ({r.get('bytes', 0)} bytes in {len(r['files'])} files)")
    for e in r["files"]:
        print(f"  {e['name']:<12} {e['bytes']:>10}  {e['mode']}  {e.get('sha256', '-')[:16]}  {e.get('sums', '')}")
    if r.get("db"):
        db, c = r["db"], r["compatibility"]
        print(f"  integrity {db['integrity']}; {db['tables']} tables, {db['rows']} rows; page {db['page_size']} x "
              f"{db['page_count']} ({db['freelist_count']} free); journal {db['journal_mode']}")
        print(f"  ledger {db['ledger']['count']} migrations, last {db['ledger']['last']}; this checkout has "
              f"{c['checkout_migrations']}" + (f"; UNKNOWN here: {c['unknown_to_this_checkout']} (the backup is newer "
                                                "than this release: do not restore it on this release)"
                                                if c["unknown_to_this_checkout"] else "")
              + (f"; {len(c['pending_on_start'])} would apply on start" if c["pending_on_start"] else ""))
        print(f"  logical digest {r['dump_sha256'][:16]}... ({r['dump_method']})")
        if a.tables:
            for t, n in sorted(db["table_counts"].items()):
                print(f"    {t:<44} {n}")
    for p in r["problems"]:
        print(f"  PROBLEM {p}")
    return 0 if r["state"] == "COMPLETE" else 1


def table_digests(d):
    with tempfile.TemporaryDirectory(prefix="flh-backup-compare-") as td:
        db = scratch_db(d, td)
        f = db_facts(db, per_table=True)
        return f, {t: sqlite_dump(db, t)[0] for t in f["table_counts"]}, sqlite_dump(db)[0]


def cmd_compare(a):
    try:
        (fa, da, ta), (fb, db_, tb) = table_digests(a.a), table_digests(a.b)
    except (OSError, sqlite3.Error) as e:
        print(f"backup_tool: unreadable: {e}", file=sys.stderr)
        return 2
    sa, sb = read_sums(a.a) or {}, read_sums(a.b) or {}
    tables = []
    for t in sorted(set(fa["table_counts"]) | set(fb["table_counts"])):
        ca, cb = fa["table_counts"].get(t), fb["table_counts"].get(t)
        tables.append({"table": t, "rows_a": ca, "rows_b": cb,
                       "rows": "same" if da.get(t) == db_.get(t) else "only in A" if cb is None else
                       "only in B" if ca is None else "different"})
    res = {"a": os.path.basename(os.path.normpath(a.a)), "b": os.path.basename(os.path.normpath(a.b)),
           "same_logical_content": ta == tb, "same_files": sa == sb and bool(sa),
           "ledger": [fa["ledger"]["count"], fb["ledger"]["count"], fa["ledger"]["last"], fb["ledger"]["last"]],
           "tables": tables}
    lost = [t for t in tables if t["rows"] != "same"]
    # read as a rollback: restoring A over B's state discards every change made after A
    res["restore_a_over_b_discards"] = {"tables": [t["table"] for t in lost],
                                        "ledger_back_to": res["ledger"][0] if res["ledger"][0] != res["ledger"][1] else None}
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(f"A {res['a']}\nB {res['b']}")
        print(f"logical content: {'SAME' if res['same_logical_content'] else 'DIFFERENT'}; files (SHA256SUMS): "
              f"{'identical' if res['same_files'] else 'differ'}; ledger {res['ledger'][0]} vs {res['ledger'][1]}")
        for t in tables:
            if t["rows"] != "same":
                print(f"  {t['table']:<44} {t['rows']:<10} rows {t['rows_a']} -> {t['rows_b']}")
        print(f"  {sum(1 for t in tables if t['rows'] == 'same')} of {len(tables)} tables hold the same rows (values not shown)")
        if lost:
            led = res["restore_a_over_b_discards"]["ledger_back_to"]
            print(f"restoring A over B DISCARDS the changes in {len(lost)} table(s) listed above (every write made after A)"
                  + (f", and takes the ledger back to {led} migrations" if led is not None else "")
                  + ": keep B, or export what you need, before restoring")
    return 0 if res["same_logical_content"] else 1


def free_bytes(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def cmd_next_action(a):
    active = os.path.abspath(a.active).rstrip("/")
    backups = active + ".backups"
    need = sum(os.path.getsize(os.path.join(active, f)) for f in DB_FILES if os.path.isfile(os.path.join(active, f)))
    print(f"active {os.path.basename(active)}: {need} bytes of app.db files")
    entries = []
    if os.path.isdir(backups):
        for n in sorted(os.listdir(backups)):
            p = os.path.join(backups, n)
            if os.path.isdir(p):
                entries.append((n, inspect(p)))
    for n, r in entries:
        print(f"  {n:<40} {r['state']:<12} " + ("; ".join(r["problems"])[:110] if r["problems"] else f"{r.get('bytes', 0)} bytes"))
    complete = [n for n, r in entries if r["state"] == "COMPLETE"]
    bad = [(n, r) for n, r in entries if r["state"] != "COMPLETE"]
    free = free_bytes(backups if os.path.isdir(backups) else os.path.dirname(active))
    room = free > need * 1.1 + (1 << 20)
    print(f"free beside the backups: {free} bytes; a new backup needs about {need} bytes")
    if not entries:
        code, msg = "no-backup", "no backup exists yet: run `flh-daily.sh backup`"
    elif not bad:
        code, msg = "ok", f"every backup is complete; the latest is {complete[-1]}"
    elif not room:
        code, msg = "free-space", (f"{len(bad)} interrupted backup(s) and too little space for a new one: free space "
                                   f"first (an .incomplete copy can be deleted after inspection; it is never restorable)")
    else:
        latest = complete[-1] if complete else None
        code, msg = "rerun-backup", ("the last backup was interrupted (" + ", ".join(f"{n}: {r['state']}" for n, r in bad)
                                     + "); the service may be stopped (DAILY_USE.md): run `flh-daily.sh start`, then "
                                     "`flh-daily.sh backup` again" + (f"; until then the latest restorable backup is {latest}"
                                                                     if latest else "; no restorable backup exists yet"))
    print(f"NEXT [{code}] {msg}")
    print("nothing was deleted or changed")
    return 0 if code == "ok" else 1


def identity(d):
    """Logical identity of the app.db files in d: (ledger count, dump digest) from a scratch copy."""
    if not os.path.isfile(os.path.join(d, "app.db")):
        return None
    with tempfile.TemporaryDirectory(prefix="flh-restore-state-") as td:
        db = scratch_db(d, td)
        try:
            f = db_facts(db)
            return {"ledger": f["ledger"]["count"], "integrity": f["integrity"], "dump_sha256": sqlite_dump(db)[0]}
        except sqlite3.Error as e:
            return {"error": str(e)}


def cmd_restore_state(a):
    active = os.path.abspath(a.active).rstrip("/")
    parent, base = os.path.dirname(active), os.path.basename(active)
    stages, previous = [], []
    for n in sorted(os.listdir(parent)):
        m = re.fullmatch(re.escape(base) + r"\.(restore|before-restore)-(" + STAMP + ")", n)
        if m:
            (stages if m.group(1) == "restore" else previous).append({"name": n, "stamp": m.group(2),
                                                                      "identity": identity(os.path.join(parent, n))})
    act = identity(active) if os.path.isdir(active) else None
    known = {}
    for p in previous:
        known[p["name"]] = p["identity"]
    bdir = active + ".backups"
    if os.path.isdir(bdir):
        for n in sorted(os.listdir(bdir)):
            if os.path.isfile(os.path.join(bdir, n, "app.db")):
                known[f"{os.path.basename(bdir)}/{n}"] = identity(os.path.join(bdir, n))
    equals = sorted(k for k, v in known.items() if act and v and act.get("dump_sha256") and v.get("dump_sha256") == act["dump_sha256"])
    if act is None and previous:
        state, nxt = "SWAP-INTERRUPTED", (f"the active directory is missing and {previous[-1]['name']} holds the data from "
                                          f"before the restore: put it back with `mv {previous[-1]['name']} {base}` "
                                          "(in its parent directory), then start the service")
    elif act is None:
        state, nxt = "NO-ACTIVE-DATA", "no active data and no previous copy: restore a complete backup"
    elif stages and not any(p["stamp"] == s["stamp"] for s in stages for p in previous):
        state, nxt = "PREPARE-INTERRUPTED", ("a restore stopped while preparing its copy; the active data was not changed "
                                             "and the service was not stopped by it. Inspect, then delete "
                                             + ", ".join(s["name"] for s in stages) + " and run the restore again")
    elif previous:
        state, nxt = "RESTORED", (f"the last restore completed its swap ({previous[-1]['stamp']}); the previous data is "
                                  f"kept at {previous[-1]['name']}. Check the first write (restore_write_check.py), "
                                  "start, and keep the previous copy until the restored data is confirmed")
    else:
        state, nxt = "CLEAN", "no restore left anything beside the active data"
    rec = {"format": "flh-restore-state/v1", "recorded_at": now(), "active": base,
           "active_identity": act, "active_equals": equals, "staging_copies": stages, "previous_copies": previous,
           "state": state, "next_action": nxt}
    print(f"{base}: {state}")
    print(f"  active: " + ("missing" if act is None else f"ledger {act.get('ledger')}, integrity {act.get('integrity')}"
                           + (f", equals {', '.join(equals)}" if equals else ", equals no known copy")))
    for s in stages:
        print(f"  staging copy {s['name']}")
    for p in previous:
        print(f"  previous data {p['name']}")
    print(f"NEXT {nxt}")
    if a.record:
        with open(a.record, "w") as fh:
            json.dump(rec, fh, indent=1, sort_keys=True)
            fh.write("\n")
        os.chmod(a.record, 0o600)
        print(f"recorded {a.record}")
    return 0 if state in ("CLEAN", "RESTORED") else 1


def cmd_latest(a):
    d = os.path.abspath(a.dir)
    cands = []
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        p = os.path.join(d, n)
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, "app.db")):
            m = re.search(STAMP, n)
            cands.append((m.group(0) if m else "", os.path.getmtime(p), p))
    for _, _, p in sorted(cands, reverse=True):
        if inspect(p)["state"] == "COMPLETE":
            print(p)
            return 0
    print(f"backup_tool: no complete backup in {d}", file=sys.stderr)
    return 1


def cmd_pack(a):
    src = os.path.abspath(a.backup).rstrip("/")
    r = inspect(src)
    if r["state"] != "COMPLETE":
        print(f"backup_tool: refused: {os.path.basename(src)} is {r['state']}: {'; '.join(r['problems'])}", file=sys.stderr)
        return 1
    if os.path.exists(a.out):
        print(f"backup_tool: refused: {a.out} exists", file=sys.stderr)
        return 2
    name = os.path.basename(src)
    tmp = a.out + ".part"
    raw = open(tmp, "wb")
    try:
        fh = gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) if a.out.endswith(".gz") else raw
        with tarfile.open(fileobj=fh, mode="w", format=tarfile.PAX_FORMAT) as tf:
            for f in [""] + sorted(os.listdir(src)):
                ti = tf.gettarinfo(os.path.join(src, f), arcname=f"{name}/{f}".rstrip("/"))
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = ""
                ti.mtime = 0
                if ti.isfile():
                    with open(os.path.join(src, f), "rb") as data:
                        tf.addfile(ti, data)
                else:
                    tf.addfile(ti)
        if fh is not raw:
            fh.close()
    finally:
        raw.close()
    os.replace(tmp, a.out)
    digest = sha_file(a.out)
    with open(a.out + ".sha256", "w") as fh:
        fh.write(f"{digest}  {os.path.basename(a.out)}\n")
    print(f"packed {name} -> {os.path.basename(a.out)} ({os.path.getsize(a.out)} bytes) sha256 {digest}")
    return 0


def cmd_unpack(a):
    arc = a.archive
    size = os.path.getsize(arc) if os.path.isfile(arc) else None
    if size is None:
        print(f"backup_tool: {arc} is missing", file=sys.stderr)
        return 2
    got = sha_file(arc)
    if got != a.sha256.lower():
        print(f"REFUSED {os.path.basename(arc)}: SHA-256 {got[:16]}... is not the expected {a.sha256[:16]}... "
              f"({size} bytes here). The copy is incomplete or altered: compare its size with the sender's, "
              "copy it again, and unpack only when the SHA-256 matches. Nothing was unpacked.")
        return 1
    parent = os.path.abspath(a.dest)
    stale = sorted(n for n in os.listdir(parent) if n.startswith(".unpack-")) if os.path.isdir(parent) else []
    if stale:
        print(f"note: an earlier unpack stopped early and left {', '.join(stale)} in {os.path.basename(parent)}; "
              "it is never used (safe to delete after this run)")
    work = tempfile.mkdtemp(prefix=".unpack-", dir=parent)
    try:
        names = []
        try:
            with tarfile.open(arc, mode="r:*") as tf:
                for m in tf:
                    n = m.name
                    if n.startswith("/") or ".." in n.split("/") or not (m.isfile() or m.isdir()):
                        raise ValueError(f"unsafe member {n!r} ({'link' if m.issym() or m.islnk() else 'path'})")
                    names.append(n)
                    if m.isdir():
                        os.makedirs(os.path.join(work, n), exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(os.path.join(work, n)) or work, exist_ok=True)
                    src = tf.extractfile(m)
                    with open(os.path.join(work, n), "wb") as out:
                        left = m.size
                        while left:
                            blk = src.read(min(left, 1 << 20))
                            if not blk:
                                raise EOFError(f"member {n} ends after {m.size - left} of {m.size} bytes")
                            out.write(blk)
                            left -= len(blk)
                    os.chmod(os.path.join(work, n), m.mode & 0o700)
        except (EOFError, tarfile.ReadError, zlib.error, gzip.BadGzipFile, OSError) as e:
            kind = "gzip-compressed " if arc.endswith(".gz") else ""
            print(f"DAMAGED {os.path.basename(arc)}: the {kind}archive ends early or is damaged after "
                  f"{len(names)} member(s): {e}. Its SHA-256 matched what you gave, so the archive was already "
                  "truncated when it was made or checksummed: on the sending side, check the archive with "
                  f"`tar -t{'z' if kind else ''}f {os.path.basename(arc)}`, make it again from the backup directory "
                  "(backup_tool.py pack), record the new SHA-256, and copy it again. Nothing was unpacked.")
            return 1
        except ValueError as e:
            print(f"REFUSED {os.path.basename(arc)}: {e}. Nothing was unpacked.")
            return 1
        tops = sorted({n.split("/")[0] for n in names})
        if len(tops) != 1:
            print(f"REFUSED {os.path.basename(arc)}: expected one backup directory, found {tops}. Nothing was unpacked.")
            return 1
        final = os.path.join(parent, tops[0])
        if os.path.exists(final):
            print(f"REFUSED: {final} already exists; move it aside first. Nothing was unpacked.")
            return 1
        r = inspect(os.path.join(work, tops[0]))
        if r["state"] != "COMPLETE":
            print(f"REFUSED: the unpacked backup is {r['state']}: {'; '.join(r['problems'])}. Nothing was unpacked.")
            return 1
        os.chmod(os.path.join(work, tops[0]), 0o700)
        os.rename(os.path.join(work, tops[0]), final)
        print(f"unpacked {tops[0]}: {r['state']}, ledger {r['db']['ledger']['count']}, {r['bytes']} bytes")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cmd_receipt(a):
    b = inspect(a.backup)
    act = identity(a.active)
    prev = identity(a.previous) if a.previous else None
    wc = None
    if a.write_check:
        with open(a.write_check) as fh:
            lines = [l.rstrip("\n").split("\t") for l in fh if "\t" in l]
        wc = {"passed": any(l[:2] == ["PASS", "summary"] for l in lines),
              "lines": [{"status": l[0], "check": l[1], "detail": l[2] if len(l) > 2 else ""} for l in lines]}
    timings = None
    if a.timings:
        with open(a.timings) as fh:
            timings = json.load(fh)
    same = bool(act and b.get("dump_sha256") and act.get("dump_sha256") == b["dump_sha256"])
    ok = b["state"] == "COMPLETE" and same and (act or {}).get("integrity") == "ok" and (wc is None or wc["passed"])
    rec = {"format": "flh-recovery-receipt/v1", "written_at": now(), "verdict": "RECOVERED" if ok else "NOT RECOVERED",
           "backup": {"name": b["backup"], "state": b["state"], "bytes": b.get("bytes"),
                      "sha256sums_sha256": next((e["sha256"] for e in b["files"] if e["name"] == "SHA256SUMS"), None),
                      "ledger": (b.get("db") or {}).get("ledger"), "dump_sha256": b.get("dump_sha256")},
           "active": {"dir": os.path.basename(os.path.abspath(a.active)), **(act or {"missing": True}),
                      "equals_backup": same},
           "previous": ({"dir": os.path.basename(os.path.abspath(a.previous)), **(prev or {"missing": True})}
                        if a.previous else None),
           "first_write": wc, "timings": timings,
           "next_action": "start the service and keep the previous copy until the learner confirms the data" if ok else
           "do not start on this data: " + ("the active data is not the backup" if not same else
                                            "the first-write check failed" if wc and not wc["passed"] else
                                            f"the backup is {b['state']}")}
    with open(a.out, "w") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.chmod(a.out, 0o600)
    print(f"{rec['verdict']}: {rec['backup']['name']} -> {rec['active']['dir']} (same logical content: {same}); "
          f"receipt {a.out}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inspect")
    p.add_argument("backup")
    p.add_argument("--json", action="store_true")
    p.add_argument("--tables", action="store_true", help="also print row counts per table")
    p = sub.add_parser("compare")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("next-action")
    p.add_argument("active")
    p = sub.add_parser("restore-state")
    p.add_argument("active")
    p.add_argument("--record")
    p = sub.add_parser("latest")
    p.add_argument("dir")
    p = sub.add_parser("pack")
    p.add_argument("backup")
    p.add_argument("out")
    p = sub.add_parser("unpack")
    p.add_argument("archive")
    p.add_argument("--sha256", required=True)
    p.add_argument("dest")
    p = sub.add_parser("receipt")
    p.add_argument("--backup", required=True)
    p.add_argument("--active", required=True)
    p.add_argument("--previous")
    p.add_argument("--write-check")
    p.add_argument("--timings")
    p.add_argument("--out", required=True)
    a = ap.parse_args()
    return {"inspect": cmd_inspect, "compare": cmd_compare, "next-action": cmd_next_action,
            "restore-state": cmd_restore_state, "latest": cmd_latest, "pack": cmd_pack, "unpack": cmd_unpack,
            "receipt": cmd_receipt}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
