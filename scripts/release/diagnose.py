#!/usr/bin/env python3
"""Offline diagnosis of why the service does not start or answers /readyz with 503
(standard library, Python 3.9; no Docker, no network beyond a loopback port probe).

  diagnose.py [--env FILE] [--data DIR] [--port N] [--uid N --gid N] [--migrations N | --bundle DIR] [--json]

The migrations this release knows: --migrations, else --bundle DIR's MANIFEST.json, else this
checkout's migrations/, else (run from a bundle's repo/ copy) that bundle's MANIFEST.json.

Reads from the settings file only FLH_DATA_DIR, FLH_HOST_PORT, FLH_UID and FLH_GID (never any
other value, never printed); flags win over the file. Checks, in the order a start needs them,
and stops at nothing: every check runs, then the FIRST failure is the diagnosis.

Each cause has a stable short code (REASONS below; docs/RELEASE.md lists them) and one recovery
command. Exit 0 nothing found, 1 a cause found, 2 usage.
"""
import argparse
import json
import os
import re
import shutil
import socket
import sqlite3
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.realpath(os.path.join(HERE, "..", ".."))

# code: (what it means, how to recover). Codes are stable: tests pin them; never reuse one.
REASONS = {
    "settings-missing": ("the settings file does not exist",
                         "cp scripts/daily/daily.env.example <FILE> && chmod 600 <FILE>, then fill it in"),
    "settings-readable": ("the settings file is readable by other users", "chmod 600 <FILE>"),
    "data-missing": ("FLH_DATA_DIR does not exist (the bind mount needs it; nothing creates it)",
                     "mkdir -m 700 <DATA> && chown <UID>:<GID> <DATA>"),
    "data-owner": ("FLH_DATA_DIR is not owned by the service user", "chown -R <UID>:<GID> <DATA>"),
    "data-mode": ("FLH_DATA_DIR is readable by other users (flh-daily.sh refuses it)", "chmod 700 <DATA>"),
    "db-readonly": ("app.db (or a sidecar, or its directory) is not writable by the service user: the service "
                    "starts, reads work, /readyz answers 503 storage_read_only and the first write fails",
                    "chmod 600 <DATA>/app.db* && chown <UID>:<GID> <DATA>/app.db*, then restart the service "
                    "(flh-daily.sh restart): a running server keeps the database open read-only"),
    "db-corrupt": ("app.db fails PRAGMA integrity_check",
                   "restore the newest complete backup: flh-daily.sh restore \"$(python3 -I scripts/release/backup_tool.py "
                   "latest <DATA>.backups)\""),
    "db-newer": ("app.db holds migrations this release does not know (it was migrated by a newer release): an "
                 "older image skips them and runs on a schema it does not understand",
                 "install the newer release again, or restore a backup made by this release"),
    "port-busy": ("127.0.0.1:<PORT> is already in use, so Compose cannot publish the service there",
                  "ss -ltnp 'sport = :<PORT>' to find it; stop it or set another FLH_HOST_PORT"),
    "disk-low": ("less free space beside FLH_DATA_DIR than twice the database (WAL, backups and restores need it)",
                 "free space on that file system (old .before-restore-* copies, after their check, are the usual room)"),
}


def settings(path):
    """FLH_DATA_DIR, FLH_HOST_PORT, FLH_UID, FLH_GID only; quotes removed as Compose does."""
    out = {}
    with open(path) as fh:
        for line in fh:
            m = re.match(r"^\s*(FLH_DATA_DIR|FLH_HOST_PORT|FLH_UID|FLH_GID)\s*=\s*(.*?)\s*$", line)
            if m:
                v = m.group(2)
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                    v = v[1:-1]
                out[m.group(1)] = v
    return out


def writable(path, want, uid, gid):
    st = os.stat(path)
    if uid == 0:
        return True
    if os.geteuid() == uid:
        return os.access(path, (os.W_OK if "w" in want else 0) | (os.X_OK if "x" in want else 0))
    shift = 6 if st.st_uid == uid else 3 if st.st_gid == gid else 0
    bits = (st.st_mode >> shift) & 7
    return all(bits & {"w": 2, "x": 1}[c] for c in want)


def ledger_and_integrity(data):
    td = tempfile.mkdtemp(prefix="flh-diagnose-")
    try:
        for f in ("app.db", "app.db-wal", "app.db-shm"):
            if os.path.isfile(os.path.join(data, f)):
                shutil.copyfile(os.path.join(data, f), os.path.join(td, f))
        con = sqlite3.connect(f"file:{os.path.join(td, 'app.db')}?mode=ro", uri=True)
        try:
            integ = con.execute("PRAGMA integrity_check").fetchone()[0]
            try:
                names = [r[0] for r in con.execute("SELECT name FROM schema_migrations ORDER BY name")]
            except sqlite3.Error:
                names = []
        finally:
            con.close()
        return integ, names
    finally:
        shutil.rmtree(td, ignore_errors=True)


def known_migrations(a):
    if a.migrations is not None:
        return None, a.migrations
    if a.bundle:
        with open(os.path.join(a.bundle, "MANIFEST.json")) as fh:
            m = json.load(fh)["migrations"]
        return None, int(m["count"])
    d = os.path.join(REPO, "migrations")
    if os.path.isdir(d):
        names = sorted(f for f in os.listdir(d) if re.match(r"^[0-9]{3}_.*\.sql$", f))
        return names, len(names)
    man = os.path.join(os.path.dirname(REPO), "MANIFEST.json")     # run from a bundle's repo/ copy
    if os.path.isfile(man):
        with open(man) as fh:
            return None, int(json.load(fh)["migrations"]["count"])
    return None, None


def diagnose(a):
    rows = []

    def check(code, ok, detail):
        rows.append({"code": code, "ok": bool(ok), "detail": detail})
        return ok

    s = {}
    if a.env:
        if check("settings-missing", os.path.isfile(a.env), "present" if os.path.isfile(a.env) else "absent"):
            mode = stat.S_IMODE(os.stat(a.env).st_mode)
            check("settings-readable", not mode & 0o077, f"mode {oct(mode)}")
            s = settings(a.env)
    data = a.data or s.get("FLH_DATA_DIR")
    port = a.port or (int(s["FLH_HOST_PORT"]) if s.get("FLH_HOST_PORT", "").isdigit() else 8080)
    uid = a.uid if a.uid is not None else int(s.get("FLH_UID") or 1000)
    gid = a.gid if a.gid is not None else int(s.get("FLH_GID") or 1000)
    if data and check("data-missing", os.path.isdir(data), "present" if os.path.isdir(data) else "absent"):
        st = os.stat(data)
        check("data-owner", st.st_uid == uid, f"owner {st.st_uid}:{st.st_gid}, service {uid}:{gid}")
        check("data-mode", not stat.S_IMODE(st.st_mode) & 0o077, f"mode {oct(stat.S_IMODE(st.st_mode))}")
        db = os.path.join(data, "app.db")
        if os.path.isfile(db):
            bad = [os.path.basename(p) for p in [db] + [db + x for x in ("-wal", "-shm") if os.path.exists(db + x)]
                   if not writable(p, "w", uid, gid)]
            if not writable(data, "wx", uid, gid):
                bad.append(os.path.basename(data) + "/")
            check("db-readonly", not bad, "writable by the service user" if not bad else f"not writable: {bad}")
            try:
                integ, led = ledger_and_integrity(data)
            except sqlite3.Error as e:
                integ, led = str(e), []
            check("db-corrupt", integ == "ok", f"integrity {integ[:60]}")
            names, count = known_migrations(a)
            if count is None:
                check("db-newer", True, f"ledger {len(led)}; not checked: give --bundle DIR or --migrations N")
            else:
                unknown = [n for n in led if n not in names] if names is not None else []
                newer = unknown or (names is None and len(led) > count)
                check("db-newer", not newer, f"ledger {len(led)}, this release knows {count}"
                      + (f"; unknown {unknown}" if unknown else ""))
            size = sum(os.path.getsize(p) for p in (db, db + "-wal") if os.path.exists(p))
            free = shutil.disk_usage(data).free
            check("disk-low", free >= 2 * size, f"{free} bytes free, database {size} bytes")
    sock = socket.socket()
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        free_port = True
    except OSError:
        free_port = False
    finally:
        sock.close()
    if a.running:
        rows.append({"code": "port-busy", "ok": True, "detail": f"127.0.0.1:{port} in use (expected: --running)"})
    else:
        check("port-busy", free_port, f"127.0.0.1:{port} " + ("free" if free_port else "in use"))
    first = next((r for r in rows if not r["ok"]), None)
    subst = {"<FILE>": a.env or "<settings file>", "<DATA>": data or "<FLH_DATA_DIR>", "<UID>": str(uid),
             "<GID>": str(gid), "<PORT>": str(port)}
    out = {"format": "flh-diagnosis/v1", "checks": rows, "diagnosis": None}
    if first:
        what, how = REASONS[first["code"]]
        for k, v in subst.items():
            what, how = what.replace(k, v), how.replace(k, v)
        out["diagnosis"] = {"code": first["code"], "reason": what, "recover": how}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env")
    ap.add_argument("--data")
    ap.add_argument("--port", type=int)
    ap.add_argument("--uid", type=int)
    ap.add_argument("--gid", type=int)
    ap.add_argument("--migrations", type=int, help="how many migrations the release knows")
    ap.add_argument("--bundle", help="a bundle directory: its MANIFEST.json migration count")
    ap.add_argument("--running", action="store_true", help="the service is running: its port is expected in use")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--reasons", action="store_true", help="list every code with its recovery")
    a = ap.parse_args()
    if a.reasons:
        for k, (what, how) in REASONS.items():
            print(f"{k}\t{what}\t{how}")
        return 0
    if not (a.env or a.data):
        print("diagnose: give --env FILE or --data DIR", file=sys.stderr)
        return 2
    r = diagnose(a)
    if a.json:
        print(json.dumps(r, indent=1, sort_keys=True))
    else:
        for c in r["checks"]:
            print(f"{'PASS' if c['ok'] else 'FAIL'} {c['code']:<18} {c['detail']}")
        d = r["diagnosis"]
        print(f"DIAGNOSIS [{d['code']}] {d['reason']}\nRECOVER {d['recover']}" if d else "nothing found: every check passed")
    return 1 if r["diagnosis"] else 0


if __name__ == "__main__":
    sys.exit(main())
