#!/usr/bin/env python3
"""Check that a restored data directory can take the service's first write.

    python3 -I scripts/release/restore_write_check.py DATA_DIR [--uid N --gid N]

Run it after the RELEASE.md Restore block has moved the restored files into
place and before the service starts again. `/readyz` cannot catch this case:
SQLite opens a database file it may not write in read-only mode without an
error, so the server starts, reads work and `/readyz` passes, while the first
write answers 500. A backup made read-only (or owned by another user) is
restored that way by `cp -a`.

Checks, for the service's uid and gid (`--uid`/`--gid`, else FLH_UID/FLH_GID,
else the current user):

  file       DATA_DIR/app.db is a regular file the service may write
  sidecars   app.db-wal and app.db-shm, when present, are regular files it may write
  directory  DATA_DIR is a directory it may write and enter (SQLite creates
             and removes the sidecars there; without them it cannot even read)
  write      run as that uid only: open app.db read-write, create a temporary
             probe table and write one row inside BEGIN IMMEDIATE. A lock-only
             probe (BEGIN IMMEDIATE) is not enough: it succeeds on a read-only
             file. The service must be stopped; a lock held by another process
             fails the check instead of waiting.
  cleanup    the probe is rolled back: no probe table is left, app.db is
             byte-identical (digest), no rollback journal remains; the sidecars
             before and after are listed (SQLite may create -wal/-shm, as the
             service does).

Limitations: when run as another user (for example root), the write probe is
skipped and permissions are judged from mode bits for the given uid/gid only
(supplementary groups and ACLs are not evaluated). The probe may create or
remove the empty -wal/-shm sidecars, as the service does. It does not detect a
full disk.

Exit status: 0 every check passed, 1 a check failed, 2 usage.
"""

import argparse
import hashlib
import os
import sqlite3
import stat
import sys

PROBE = "flh_restore_write_probe"


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sidecars(data):
    """Which SQLite sidecar files exist beside app.db, with their sizes."""
    return {f: os.path.getsize(os.path.join(data, f)) for f in ("app.db-wal", "app.db-shm", "app.db-journal")
            if os.path.isfile(os.path.join(data, f))}


def allowed(path, want, uid, gid, as_target):
    """Whether uid/gid may access path with the rights in want ('w', 'wx')."""
    if as_target:
        mode = (os.W_OK if "w" in want else 0) | (os.X_OK if "x" in want else 0)
        return os.access(path, mode)
    st = os.stat(path)
    if uid == 0:
        return True
    shift = 6 if st.st_uid == uid else 3 if st.st_gid == gid else 0
    bits = (st.st_mode >> shift) & 7
    return all(bits & {"w": 2, "x": 1}[c] for c in want)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_dir")
    ap.add_argument("--uid", type=int)
    ap.add_argument("--gid", type=int)
    a = ap.parse_args(argv)
    try:
        uid = a.uid if a.uid is not None else int(os.environ.get("FLH_UID", os.geteuid()))
        gid = a.gid if a.gid is not None else int(os.environ.get("FLH_GID", os.getegid()))
    except ValueError:
        print("FLH_UID and FLH_GID must be numbers", file=sys.stderr)
        return 2
    data = os.path.abspath(a.data_dir)
    db = os.path.join(data, "app.db")
    as_target = os.geteuid() == uid
    results = []

    def report(name, ok, detail):
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}\t{name}\t{detail}", flush=True)

    print(f"INFO\tuser\tchecking for uid {uid} gid {gid}; running as uid {os.geteuid()}"
          + ("" if as_target else " (another user: write probe skipped, mode bits only)"))
    if not os.path.isdir(data):
        report("directory", False, f"{data} is not a directory")
        return 1
    if not os.path.isfile(db) or os.path.islink(db):
        report("file", False, f"{db} is missing or not a regular file")
        return 1
    st = os.stat(db)
    report("file", allowed(db, "w", uid, gid, as_target),
           f"app.db mode {stat.filemode(st.st_mode)} owner {st.st_uid}:{st.st_gid}")
    for suffix in ("-wal", "-shm"):
        p = db + suffix
        if os.path.lexists(p):
            ps = os.lstat(p)
            ok = stat.S_ISREG(ps.st_mode) and allowed(p, "w", uid, gid, as_target)
            report("sidecars", ok, f"app.db{suffix} mode {stat.filemode(ps.st_mode)} owner {ps.st_uid}:{ps.st_gid}")
    dst = os.stat(data)
    report("directory", allowed(data, "wx", uid, gid, as_target),
           f"{os.path.basename(data) or data} mode {stat.filemode(dst.st_mode)} owner {dst.st_uid}:{dst.st_gid}")
    if as_target and all(results):
        before = digest(db)
        side_before = sidecars(data)
        try:
            con = sqlite3.connect(f"file:{db}?mode=rw", uri=True, timeout=0.5, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                con.execute(f"CREATE TABLE {PROBE} (x INTEGER)")
                con.execute(f"INSERT INTO {PROBE} VALUES (1)")
                seen = con.execute(f"SELECT COUNT(*) FROM {PROBE}").fetchone()[0]
                con.execute("ROLLBACK")
                left = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = ?", (PROBE,)).fetchone()[0]
            finally:
                con.close()
            report("write", seen == 1, "created a probe table and wrote one row inside BEGIN IMMEDIATE"
                   if seen == 1 else f"the probe row was not visible inside the transaction ({seen})")
            same = digest(db) == before
            side_after = sidecars(data)
            made = sorted(set(side_after) - set(side_before))
            gone = sorted(set(side_before) - set(side_after))
            journal = "app.db-journal" in side_after
            report("cleanup", left == 0 and same and not journal,
                   f"rolled back: probe table left {left}, app.db unchanged {same}, rollback journal left {journal}; "
                   f"sidecars before {side_before or 'none'}, after {side_after or 'none'}"
                   + (f" (created {made}, as the service does)" if made else "") + (f" (removed {gone})" if gone else ""))
        except sqlite3.Error as e:
            hint = " (is the service still running? stop it first)" if "locked" in str(e) else ""
            report("write", False, f"{e}{hint}")
    elif as_target:
        print("INFO\twrite\tnot attempted: fix the failures above first")
    ok = all(results)
    print(f"{'PASS' if ok else 'FAIL'}\tsummary\t"
          + ("the service can write this database" if ok else
             "the service would start and pass /readyz but fail its first write: make app.db, its -wal/-shm "
             "and the directory writable by the service user (for example chmod 600 on the files and chown "
             "them to FLH_UID:FLH_GID), then run this check again"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
