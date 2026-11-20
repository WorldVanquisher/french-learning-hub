#!/usr/bin/env python3
"""Backup, restore, failed-prepare recovery, first write and restart on a disposable stand-in host
(items 045, 048, 049, 050).

  recovery_rehearsal.py BUNDLE.tar SHA256 FIXTURE_DIR WORK_DIR [--large-rows N]

One stand-in host (standin_lib: the /srv/flh-staging layout under WORK_DIR, its own Compose
project on a free loopback port, synthetic data only) runs the bundle with its own flh-daily.sh.
The release tools come from this checkout (scripts/release/backup_tool.py, restore_write_check.py).
  S   small fixture: transfer, restore, first write, backup (inspect, compare with the fixture)
  F1  a restore that fails while preparing (read-only destination): refused, the service keeps
      running (same container and start time), the active data unchanged, nothing left behind
  F2  a restore of a sealed but damaged backup: fails at the integrity check before any stop,
      leaves its staging copy; restore-state names it; the operator follows that next action
      (delete the staging copy) and resumes with the good backup
  R   receipt: stop, first-write check (write and cleanup), flh-recovery-receipt/v1, restart,
      ready, a first real write after the restart
  L   large fixture (the small one plus N synthetic entries): transfer, restore, first write,
      backup; the timings of both sizes side by side
The daily instance is never touched (fingerprint before and after).
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import standin_lib as L  # noqa: E402

REPO = os.path.realpath(os.path.join(HERE, "..", "..", "..", "..", ".."))
BT = os.path.join(REPO, "scripts", "release", "backup_tool.py")
WC = os.path.join(REPO, "scripts", "release", "restore_write_check.py")

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("bundle")
ap.add_argument("sha256")
ap.add_argument("fixture")
ap.add_argument("work")
ap.add_argument("--large-rows", type=int, default=200000)
A = ap.parse_args()
TAR, FIX = os.path.realpath(A.bundle), os.path.realpath(A.fixture)
rec = L.Recorder(A.work)
WORK = rec.work
fp_before = L.daily_fingerprint()
rec.save("daily-fingerprint-before.txt", fp_before + "\n")


def tool(*args, log):
    t0 = time.time()
    r = subprocess.run([sys.executable, "-I", "-B", *args], capture_output=True, text=True)
    rec.save(log, f"$ {os.path.basename(args[0])} {' '.join(os.path.basename(x) if os.sep in x else x for x in args[1:])}\n"
                  f"exit {r.returncode} ({time.time() - t0:.2f} s)\n{r.stdout}{r.stderr}")
    return r.returncode, r.stdout + r.stderr


def container_state(h):
    c = h.container()
    if not c:
        return None
    return subprocess.run(["docker", "inspect", "-f", "{{.Id}} {{.State.StartedAt}}", c], capture_output=True,
                          text=True).stdout.strip()


def identity(d):
    rc, out = tool(BT, "inspect", d, "--json", log=f"identity-{os.path.basename(d)}-{time.time_ns()}.json")
    try:
        j = json.loads(out[out.index("{"):])
        return j.get("dump_sha256")
    except ValueError:
        return None


def capture(cid, text):
    return {"schema_version": "learning_capture_v1", "capture_id": cid, "source": "manual", "original_input": text,
            "original_context": "FIXTURE-PRIVATE-RECOVERY: écriture synthétique de répétition.",
            "discussion_summary": "FIXTURE-PRIVATE-SUMMARY: répétition de restauration."}


def timed(name, fn):
    t0 = time.time()
    out = fn()
    rec.time(name, time.time() - t0)
    return out


def latest_backup(h):
    d = h.data + ".backups"
    names = sorted(n for n in os.listdir(d) if n.startswith("flh-") and not n.endswith(".incomplete"))
    return os.path.join(d, names[-1]) if names else None


def make_large(src, dest, rows):
    """The small fixture plus `rows` synthetic learning entries, sealed like a flh-daily.sh backup."""
    shutil.copytree(src, dest)
    con = sqlite3.connect(os.path.join(dest, "app.db"), isolation_level=None)
    try:
        con.execute("BEGIN")
        filler = "Phrase synthétique de répétition pour mesurer la restauration. " * 3
        con.executemany("INSERT INTO learning_entries (original_input, original_context, created_at, updated_at) "
                        "VALUES (?, ?, '2026-11-19T00:00:00Z', '2026-11-19T00:00:00Z')",
                        ((f"FIXTURE-SYNTHETIC-{i:07d} {filler}", "FIXTURE-SYNTHETIC context") for i in range(rows)))
        con.execute("COMMIT")
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        con.close()
    for f in ("app.db-wal", "app.db-shm"):
        p = os.path.join(dest, f)
        if not os.path.exists(p):
            open(p, "wb").close()
    with open(os.path.join(dest, "SHA256SUMS"), "w") as fh:
        for f in sorted(x for x in os.listdir(dest) if x.startswith("app.db")):
            fh.write(f"{L.sha256(os.path.join(dest, f))}  {f}\n")
    for f in os.listdir(dest):
        os.chmod(os.path.join(dest, f), 0o600)
    return sum(os.path.getsize(os.path.join(dest, f)) for f in os.listdir(dest))


def size_pass(h, label, backup_dir):
    """transfer -> restore -> ready -> first write -> backup, each timed."""
    ok, path = timed(f"{label}: transfer (tar, SHA-256, copy, verify)",
                     lambda: L.fetch(*L.transfer(backup_dir, WORK, f"{label}-seed"), os.path.join(h.root, "transfer")))
    rc, text, secs = h.stg("restore", path, log=f"{label}-restore")
    rec.time(f"{label}: flh-daily.sh restore (checksums, copy, integrity, stop, swap, write check, up, healthy)", secs)
    ready = timed(f"{label}: ready after restore", lambda: h.ready(60))
    code = timed(f"{label}: first write", lambda: h.call("POST", "/captures", capture(f"{label}-write-001", f"Écriture {label}."))[0])
    rc2, text2, secs2 = h.stg("backup", log=f"{label}-backup")
    rec.time(f"{label}: flh-daily.sh backup (stop, copy, integrity, sums, start)", secs2)
    return ok and rc == 0 and ready and code == 201 and rc2 == 0, (rc, code, rc2), path


try:
    h = L.Host(rec, "rec")
    ok, _ = h.render_settings()
    rc, text, _ = h.tool("install", TAR, "--sha256", A.sha256, log="install")
    rec.record("P1", ok and rc == 0 and "IDENTITY OK" in text, "stand-in host: settings rendered, bundle installed", f"exit {rc}")

    # ---- S: small fixture ---------------------------------------------------------------------------
    small_bytes = sum(os.path.getsize(os.path.join(FIX, f)) for f in os.listdir(FIX))
    good, codes, _ = size_pass(h, "small", FIX)
    rec.record("S1", good, "small fixture: transfer, restore, ready, first write 201, backup", f"restore/write/backup {codes}")
    b1 = latest_backup(h)
    rc, out = tool(BT, "inspect", b1, log="S2-inspect.txt")
    rec.record("S2", rc == 0 and "COMPLETE" in out, "the new backup inspects COMPLETE (ledger, sums, integrity)", out.splitlines()[0])
    rc, out = tool(BT, "compare", FIX, b1, log="S3-compare.txt")
    changed = [l.split()[0] for l in out.splitlines() if " different " in l or " only in " in l]
    rec.record("S3", rc == 1 and set(changed) <= {"learning_captures", "learning_entries", "learning_capture_sources"} and changed,
               "fixture vs new backup: only the rows of the first write differ (values not shown)", ", ".join(changed))

    # ---- F1: failed prepare, read-only destination ----------------------------------------------------
    before_c, before_id = container_state(h), identity(h.data)
    parent = os.path.dirname(h.data)
    names_before = set(os.listdir(parent))
    rc, out = tool(BT, "restore-state", h.data, log="F1-restore-state-before.txt")
    state_before = out.splitlines()[0]
    os.chmod(parent, 0o500)
    try:
        rc, text, _ = h.stg("restore", b1, log="F1-restore-readonly")
    finally:
        os.chmod(parent, 0o700)
    left = sorted(set(os.listdir(parent)) - names_before)
    rec.record("F1", rc != 0 and "while preparing the copy" in text and container_state(h) == before_c and h.ready(5)
               and identity(h.data) == before_id and not left,
               "failed prepare (read-only destination): refused, same container and start time, ready, data unchanged, "
               "nothing new left beside the data", f"exit {rc}; new entries {left or 'none'}")
    rc, out = tool(BT, "restore-state", h.data, log="F1-restore-state.txt")
    rec.record("F1b", out.splitlines()[0] == state_before, "restore-state unchanged by the failed prepare",
               f"{state_before} -> {out.splitlines()[0]}")

    # ---- F2: sealed but damaged backup: fails at the integrity check, leaves its staging copy ------------
    bad = os.path.join(WORK, "damaged-backup")
    shutil.copytree(b1, bad)
    with open(os.path.join(bad, "app.db"), "r+b") as fh:
        size = os.path.getsize(os.path.join(bad, "app.db"))
        for off in range(4096 * 3, size - 4096, 4096 * 7):
            fh.seek(off + 100)
            fh.write(b"\xff" * 900)
    with open(os.path.join(bad, "SHA256SUMS"), "w") as fh:
        for f in sorted(x for x in os.listdir(bad) if x.startswith("app.db")):
            fh.write(f"{L.sha256(os.path.join(bad, f))}  {f}\n")
    rc_i, out_i = tool(BT, "inspect", bad, log="F2-inspect-damaged.txt")
    before_c, before_id = container_state(h), identity(h.data)
    rc, text, _ = h.stg("restore", bad, log="F2-restore-damaged")
    stage = sorted(n for n in os.listdir(parent) if ".restore-" in n and ".before-" not in n)
    rec.record("F2", rc_i == 1 and "CORRUPT" in out_i and rc != 0 and "failed the integrity check" in text
               and container_state(h) == before_c and identity(h.data) == before_id and len(stage) == 1,
               "sealed damaged backup: inspect CORRUPT; restore fails before any stop, data unchanged, staging copy left",
               f"inspect {out_i.splitlines()[0][:60]}; restore exit {rc}; staging {stage}")
    state = os.path.join(WORK, "restore-state-F2.json")
    rc, out = tool(BT, "restore-state", h.data, "--record", state, log="F2-restore-state.txt")
    nxt = json.load(open(state))
    rec.record("F2b", rc == 1 and nxt["state"] == "PREPARE-INTERRUPTED" and stage[0] in nxt["next_action"]
               and oct(os.stat(state).st_mode & 0o777) == "0o600",
               "restore-state records PREPARE-INTERRUPTED and names the staging copy to delete", nxt["state"])
    shutil.rmtree(os.path.join(parent, stage[0]))          # the recorded next action, after inspection
    rc, text, secs = h.stg("restore", b1, log="F2-resume-restore")
    rec.time("small: resumed restore after the failed prepare", secs)
    rec.record("F2c", rc == 0 and h.ready(30) and identity(h.data) == identity(b1),
               "resume: the good backup restores; the active data equals it", f"exit {rc}, {secs:.1f} s")

    # ---- R: receipt, first-write check, restart --------------------------------------------------------
    rc, text, _ = h.stg("stop", log="R-stop")
    wc = os.path.join(WORK, "write-check.txt")
    r = subprocess.run([sys.executable, "-I", WC, h.data], capture_output=True, text=True)
    with open(wc, "w") as fh:
        fh.write(r.stdout)
    rec.save("R-write-check.txt", r.stdout + r.stderr)
    prev = sorted(n for n in os.listdir(parent) if ".before-restore-" in n)[-1]
    rec_path = os.path.join(WORK, "recovery-receipt.json")
    rc_r, out_r = tool(BT, "receipt", "--backup", b1, "--active", h.data, "--previous", os.path.join(parent, prev),
                       "--write-check", wc, "--timings", os.path.join(WORK, "timings.json"), "--out", rec_path,
                       log="R-receipt.txt")
    rec.record("R1", r.returncode == 0 and "PASS\twrite\t" in r.stdout and "PASS\tcleanup\t" in r.stdout and rc_r == 0
               and "RECOVERED" in out_r, "stopped: first-write check (write + cleanup) passes; receipt RECOVERED",
               out_r.strip()[:90])
    rc, text, secs = h.stg("start", log="R-start")
    rec.time("small: restart (start, healthy)", secs)
    code = h.call("POST", "/captures", capture("after-restart-write-001", "Écriture après redémarrage."))[0]
    rec.record("R2", rc == 0 and h.ready(30) and code == 201, "restart: healthy, ready, first write after the restart 201",
               f"start exit {rc}, write {code}")

    # ---- L: large fixture -----------------------------------------------------------------------------
    large = os.path.join(WORK, "large-fixture")
    large_bytes = timed("large: build the synthetic fixture", lambda: make_large(FIX, large, A.large_rows))
    good, codes, _ = size_pass(h, "large", large)
    rc, out = tool(BT, "inspect", latest_backup(h), log="L-inspect.txt")
    rec.record("L1", good and rc == 0, f"large fixture ({large_bytes} bytes, +{A.large_rows} entries): restore, write, backup",
               f"restore/write/backup {codes}")
    t = rec.timings
    rows = [("transfer", "transfer (tar, SHA-256, copy, verify)"),
            ("restore", "flh-daily.sh restore (checksums, copy, integrity, stop, swap, write check, up, healthy)"),
            ("ready", "ready after restore"), ("first write", "first write"),
            ("backup", "flh-daily.sh backup (stop, copy, integrity, sums, start)")]
    lines = [f"| step | small ({small_bytes} B) | large ({large_bytes} B) |", "| --- | --- | --- |"]
    for short, key in rows:
        lines.append(f"| {short} | {t.get('small: ' + key, '-')} s | {t.get('large: ' + key, '-')} s |")
    rec.save("recovery-times.md", "\n".join(lines) + "\n")
    rec.note("TIMES", " ; ".join(l for l in lines[2:]))
finally:
    sys.exit(L.finish(rec, [h] if "h" in dir() else [], fp_before))
