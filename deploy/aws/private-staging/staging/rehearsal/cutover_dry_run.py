#!/usr/bin/env python3
"""NAS -> AWS cutover dry run and its rollback dry run on stand-ins (items 17-19).

  cutover_dry_run.py BUNDLE.tar SHA256 FIXTURE_DIR WORK_DIR

Two stand-in hosts run the same bundle: "nas" (the daily instance's role,
holding the fixture as its current data) and "aws" (the staging host after its
staging pass). Private access is modelled as the port the learner's client
uses. Follows CUTOVER_DRY_RUN.md step by step:
  E   endpoint checklist rows that can run without AWS (identity, readiness,
      first write, logs without a failed request, loopback-only listener)
  C1  AWS ready and emptied of staging data (moved aside, never deleted)
  C2  T0: learner writes on the NAS, then the write freeze (stop) and the
      second-writer guard (settings file moved: every wrapper command refused);
      DUMP and COUNTS recorded
  C3  final NAS backup through the moved settings file; DUMP(backup) == T0
  C4  transfer (tar + SHA-256, verified on arrival)
  C5  restore on AWS; DUMP and COUNTS == T0; integrity ok; ready
  C6  smoke without new data: search, replay of a stored capture; DUMP unchanged
  C7  T1: private access switched to AWS (freeze window measured)
  C8  first real write on AWS; the NAS stays stopped, intact and guarded
  R0  rollback decision: AWS stopped, DUMP measured != T0 -> case B (AWS
      accepted writes); a naive restart of the NAS would lose the listed records
  R1  procedure B: AWS backup -> transfer -> NAS settings restored -> NAS
      restore (its T0 data kept aside); migration compatibility checked first
  R2  NAS DUMP == AWS backup DUMP, the AWS-only write present, ready;
      private access back to the NAS; AWS guarded (settings moved), stopped,
      its volume data and backup kept
The daily instance is never touched (fingerprint before and after).
"""
import json
import os
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import standin_lib as L  # noqa: E402

TAR, SHA, FIX, WORK = sys.argv[1:5]
TAR, FIX = os.path.realpath(TAR), os.path.realpath(FIX)
rec = L.Recorder(WORK)
WORK = rec.work
fp_before = L.daily_fingerprint()
rec.save("daily-fingerprint-before.txt", fp_before + "\n")
hosts = []
COUNT_TABLES = ("learning_entries", "learning_captures", "knowledge_units", "listening_materials", "speaking_takes")


def counts(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        out = {t: list(con.execute(f"SELECT count(*), coalesce(max(id), 0) FROM {t}").fetchone()) for t in COUNT_TABLES}
        out["schema_migrations"] = con.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
        return out
    finally:
        con.close()


def integrity(db):
    r = subprocess.run(["sqlite3", "-readonly", db, "PRAGMA integrity_check;"], capture_output=True, text=True)
    return r.stdout.strip() == "ok"


def capture(cid, text):
    return {"schema_version": "learning_capture_v1", "capture_id": cid, "source": "manual", "original_input": text,
            "original_context": "FIXTURE-PRIVATE-CUTOVER: écriture synthétique de répétition.",
            "discussion_summary": "FIXTURE-PRIVATE-SUMMARY: répétition de bascule."}


def capture_ids(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {r[0] for r in con.execute("SELECT capture_id FROM learning_captures")}
    finally:
        con.close()


def move_aside(path, label):
    dest = f"{path}.{label}-{L.RUN}"
    os.rename(path, dest)
    return dest


try:
    nas, aws = L.Host(rec, "nas"), L.Host(rec, "aws")
    hosts += [nas, aws]
    for h in hosts:
        ok, _ = h.render_settings()
        rc, text, _ = h.tool("install", TAR, "--sha256", SHA, log="install")
        rec.record(f"P-{h.name}", ok and rc == 0 and "IDENTITY OK" in text, f"{h.name}: same bundle installed, identity OK", f"exit {rc}")
    m, b = L.bundle_identity(aws.current())
    # the NAS holds its current data (the fixture); AWS holds data from its staging pass
    for h in hosts:
        ok, path = L.fetch(*L.transfer(FIX, WORK, f"seed-{h.name}"), os.path.join(h.root, "transfer"))
        rc, _, _ = h.stg("restore", path, log="seed-restore")
        rec.record(f"P-{h.name}-data", rc == 0 and h.ready(30), f"{h.name}: data in place (fixture)", f"exit {rc}")
    stg_write = aws.call("POST", "/captures", capture("staging-pass-write-001", "Écriture du passage de staging (à écarter)."))[0]
    rec.record("P2", nas.running_image() == aws.running_image() == b["image_id"],
               "precondition P2: the same release on both hosts (image identity)", f"{b['image_id'][:19]}")

    # ---- E. endpoint checklist rows that need no AWS (item 17) ---------------------------------------------
    rc, text, _ = aws.tool("status", log="E2-status")
    rec.record("E2", rc == 0 and "IDENTITY OK" in text and '"server_matches": true' in text, "E2 identity: running image, labels, /app/server == bundle", "")
    st_r, st_h = aws.call("GET", "/readyz"), aws.call("GET", "/healthz")[0]
    rec.record("E3", st_r[0] == 200 and L.js(st_r[1]).get("status") == "ready" and st_h == 200, "E3 /readyz ready, /healthz 200", "")
    rec.record("E4", stg_write == 201, "E4 first supported write POST /captures 201", f"{stg_write}")
    rc, logs, _ = aws.stg("logs", "--since", "30m", log="E5-logs")
    failed_lines = [l for l in logs.splitlines() if "request failed:" in l]
    rec.record("E5", rc == 0 and not failed_lines and "FIXTURE-PRIVATE" not in logs, "E5 logs: no failed request, no learning content",
               f"{len(failed_lines)} failed-request lines")
    bind = subprocess.run(["docker", "port", aws.container(), "8080/tcp"], capture_output=True, text=True).stdout.split()
    rec.record("E6", bind and all(x.startswith("127.0.0.1:") for x in bind), "E6 published only on loopback", " ".join(bind))

    # ---- C1. AWS ready, emptied of staging data -------------------------------------------------------
    rc, _, _ = aws.stg("stop", log="C1-stop")
    aside = move_aside(aws.data, "staging-pass")
    os.makedirs(aws.data, mode=0o700)
    rec.record("C1", rc == 0 and os.path.isdir(aside), "AWS stopped; staging-pass data moved aside (kept, not deleted)", os.path.basename(aside))

    # ---- C2. T0: final NAS writes, freeze, guard ----------------------------------------------------------
    w_nas = [nas.call("POST", "/captures", capture(f"nas-before-t0-{i}", f"Écriture NAS avant T0 n°{i}."))[0] for i in (1, 2)]
    t_freeze = time.time()
    rc, _, _ = nas.stg("stop", log="C2-stop")
    nas_env_moved = move_aside(nas.env_file, "moved-to-aws")
    rc_guard, guard_text, _ = nas.stg("status", log="C2-guard-status")
    rc_guard2, _, _ = nas.stg("start", log="C2-guard-start")
    db_nas = os.path.join(nas.data, "app.db")
    dump_t0, counts_t0 = L.dump_hash(db_nas), counts(db_nas)
    rec.save("T0.json", {"dump": dump_t0, "counts": counts_t0})
    rec.record("C2", w_nas == [201, 201] and rc == 0 and rc_guard == 2 and rc_guard2 == 2 and "settings file not found" in guard_text,
               "T0: writes until the freeze, NAS stopped; guard: every wrapper command refused (no second writer)",
               f"writes {w_nas}; stop {rc}; status {rc_guard}, start {rc_guard2}; T0 dump {dump_t0[:12]}")

    # ---- C3. final backup through the moved settings file ---------------------------------------------------
    rc, text, secs = nas.stg("backup", log="C3-final-backup", extra_env={"FLH_DAILY_ENV": nas_env_moved})
    bpath = next((l.split("backup written to ", 1)[1].split(" (copy", 1)[0] for l in text.splitlines() if "backup written to" in l), None)
    sums = subprocess.run(["sha256sum", "--quiet", "-c", "SHA256SUMS"], cwd=bpath, capture_output=True).returncode if bpath else 1
    rec.time("final_backup_s", secs)
    rec.record("C3", rc == 0 and sums == 0 and L.dump_hash(os.path.join(bpath, "app.db")) == dump_t0 and nas.container() is None,
               "final backup (service stays stopped); SHA256SUMS verify; DUMP(backup) == T0", f"exit {rc}, {secs:.1f} s")

    # ---- C4/C5. transfer and restore on AWS ------------------------------------------------------------------
    t0 = time.time()
    tar, digest = L.transfer(bpath, WORK, "final-nas")
    ok, path = L.fetch(tar, digest, os.path.join(aws.root, "transfer"))
    rec.time("final_transfer_s", time.time() - t0)
    rec.record("C4", ok, "transfer: tar + SHA-256 verified on arrival", f"{os.path.getsize(tar)} bytes")
    t0 = time.time()
    rc, text, secs = aws.stg("restore", path, log="C5-restore")
    ready = rc == 0 and aws.ready(30)
    rec.time("aws_restore_to_ready_s", time.time() - t0)
    db_aws = os.path.join(aws.data, "app.db")
    rec.record("C5", ready and L.dump_hash(db_aws) == dump_t0 and counts(db_aws) == counts_t0 and integrity(db_aws),
               "restore on AWS: ready; DUMP and COUNTS == T0; integrity ok", f"exit {rc}, {secs:.1f} s")

    # ---- C6. smoke without new data --------------------------------------------------------------------------
    st_s = aws.call("GET", "/learning-records?q=parte")[0]
    st_rep = aws.call("POST", "/captures", capture("nas-before-t0-1", "Écriture NAS avant T0 n°1."))[0]
    rec.record("C6", st_s == 200 and st_rep == 200 and L.dump_hash(db_aws) == dump_t0,
               "smoke without new data: search 200, replay of a stored capture 200, DUMP unchanged", f"search {st_s}, replay {st_rep}")

    # ---- C7/C8. switch and first AWS write -------------------------------------------------------------------
    client_port = aws.port
    t1 = time.time()
    rec.time("write_freeze_window_s", t1 - t_freeze)
    st_w, raw = L.call(client_port, "POST", "/captures", capture("aws-after-t1-1", "Première vraie écriture sur AWS après T1."))
    rec.record("C7-C8", st_w == 201 and nas.container() is None and L.dump_hash(db_nas) == dump_t0,
               "T1: private access on AWS; first real write 201; the NAS stays stopped and intact (DUMP == T0)",
               f"freeze window {t1 - t_freeze:.1f} s (stand-in)")

    # ---- R0. rollback decision: measure ----------------------------------------------------------------------
    rc, _, _ = aws.stg("stop", log="R0-stop")
    dump_aws = L.dump_hash(db_aws)
    lost = sorted(capture_ids(db_aws) - capture_ids(db_nas))
    rec.save("R0-naive-rollback-would-lose.json", lost)
    rec.record("R0", rc == 0 and dump_aws != dump_t0 and integrity(db_aws) and lost == ["aws-after-t1-1"],
               "rollback decision: DUMP(AWS) != T0 and healthy -> case B; restarting the NAS as it was would lose the listed records",
               f"would lose {lost}")

    # ---- R1. procedure B ---------------------------------------------------------------------------------
    t_rb = time.time()
    rc, text, secs = aws.stg("backup", log="R1-aws-backup")
    abpath = next((l.split("backup written to ", 1)[1].split(" (copy", 1)[0] for l in text.splitlines() if "backup written to" in l), None)
    rec.record("R1a", rc == 0 and abpath and L.dump_hash(os.path.join(abpath, "app.db")) == dump_aws and aws.container() is None,
               "AWS backup taken while stopped; DUMP(backup) == DUMP(AWS)", f"exit {rc}")
    aws_env_moved = move_aside(aws.env_file, "rolled-back-to-nas")
    rc_g = aws.stg("start", log="R1-aws-guard")[0]
    tar, digest = L.transfer(abpath, WORK, "aws-final")
    ok, path = L.fetch(tar, digest, os.path.join(nas.root, "transfer"))
    os.rename(nas_env_moved, nas.env_file)
    nas_knows = json.load(open(os.path.join(nas.current(), "MANIFEST.json")))["migrations"]["count"]
    aws_ledger = counts(os.path.join(abpath, "app.db"))["schema_migrations"]
    rec.record("R1b", ok and rc_g == 2 and nas_knows >= aws_ledger,
               "AWS guarded (settings moved: refused); transfer verified; NAS settings restored; NAS release knows every AWS migration",
               f"NAS bundle knows {nas_knows}, AWS ledger {aws_ledger}")
    rc, text, secs = nas.stg("restore", path, log="R1-nas-restore")
    ready = rc == 0 and nas.ready(30)
    kept = [n for n in os.listdir(os.path.dirname(nas.data)) if n.startswith("app.before-restore-")]
    rec.time("rollback_b_total_s", time.time() - t_rb)

    # ---- R2. verify and switch back -------------------------------------------------------------------------
    st_g = nas.call("GET", "/captures/aws-after-t1-1")[0]
    rec.record("R2", ready and L.dump_hash(db_nas) == dump_aws and st_g == 200 and integrity(db_nas) and kept and aws.container() is None,
               "NAS restored from the AWS backup: DUMP == AWS, the AWS-only write present, ready; NAS T0 data kept aside; AWS stopped",
               f"restore exit {rc}; T0 data kept as {kept}")
    client_port = nas.port
    rec.note("R2", f"private access back on the NAS port; AWS data and backup kept: {os.path.basename(aws.data)}, {os.path.basename(abpath)}")
    rec.note("TIMINGS", json.dumps(rec.timings, sort_keys=True))
except Exception as e:  # an unexpected error is a failure, never a silent pass
    import traceback
    rec.record("ERR", False, "no unexpected error", repr(e)[:300])
    rec.save("error.txt", traceback.format_exc())
finally:
    for h in hosts:  # put a moved settings file back so the stand-in can be torn down
        for n in os.listdir(h.root):
            if n.startswith("staging.env.") and not os.path.exists(h.env_file):
                os.rename(os.path.join(h.root, n), h.env_file)
    code = L.finish(rec, hosts, fp_before)
sys.exit(code)
