#!/usr/bin/env python3
"""Staging stand-in rehearsal: install, restore, verify, persist, back up, fail (items 12-15).

  standin_rehearsal.py BUNDLE.tar SHA256 FIXTURE_DIR FIXTURE_JSON WORK_DIR [OLD_WRAPPER_BUNDLE.tar OLD_SHA256]

Runs the RUNBOOK's host steps (§5-7) on two stand-in hosts (stg, dr) with the
real image and the bundle's own flh-daily.sh; S3 is a tar + SHA-256 copy and
SSM a parameters file read by the same renderer.
  D   settings from parameters; flh-staging-bundle install (verify, load,
      switch, identity) on stg and dr
  12  restore FIXTURE_DIR (made by make_fixture_backup.py) on stg: ready;
      logical dump and table counts equal the fixture; /readyz writes
      nothing; entries, workbook revision 2, retry marks and Speaking
      metadata read back; first supported write (POST /captures 201, replay 200)
  13  restart: the write and the restored data persist; stg backup ->
      transfer -> restore into dr: snapshot and dump equal, dr runs the bundle
  14  timings and data size (timings.json): restore, ready after restore,
      restart, backup, transfer, dr restore
  15  failures on the running service, with the bundle's wrapper and, when
      OLD_WRAPPER_BUNDLE is given, with that older wrapper on a third host for
      comparison: a read-only restore destination, a disk that fills during
      the restore copy, an interrupted backup (SIGHUP mid-copy: an SSM
      session drop); each must leave data intact and show the recovery
The daily instance is never touched (fingerprint before and after).
"""
import json
import os
import resource
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import standin_lib as L  # noqa: E402

TAR, SHA, FIX, FIXJ, WORK = sys.argv[1:6]
OLD = sys.argv[6:8] if len(sys.argv) >= 8 else None
TAR, FIX, FIXJ = (os.path.realpath(x) for x in (TAR, FIX, FIXJ))
rec = L.Recorder(WORK)
WORK = rec.work
fixture = json.load(open(FIXJ))
fp_before = L.daily_fingerprint()
rec.save("daily-fingerprint-before.txt", fp_before + "\n")
hosts = []


def setup(name, tar, sha):
    h = L.Host(rec, name)
    hosts.append(h)
    ok, mode = h.render_settings()
    rc, text, secs = h.tool("install", tar, "--sha256", sha, log="install")
    return h, ok, rc, text, secs


def capture(cid, text):
    return {"schema_version": "learning_capture_v1", "capture_id": cid, "source": "manual", "original_input": text,
            "original_context": "FIXTURE-PRIVATE-STAGING: écriture de répétition, données synthétiques.",
            "discussion_summary": "FIXTURE-PRIVATE-SUMMARY: répétition de staging."}


def fetch_backup(h, src_dir, label):
    """operator: tar + sha256 -> 's3'; host: download into transfer/, check, unpack."""
    tar, digest = L.transfer(src_dir, WORK, label)
    ok, path = L.fetch(tar, digest, os.path.join(h.root, "transfer"))
    return ok, path, os.path.getsize(tar)


def failure_suite(h, tag):
    """Item 15 on a running service; records X-* results with tag. With tag "older-wrapper"
    the expected outcome is the GAP (the service is taken down) plus a working recovery."""
    older = tag == "older-wrapper"
    data_parent = os.path.dirname(h.data)
    dump0 = L.dump_hash(os.path.join(h.data, "app.db"))
    ok, path, _ = fetch_backup(h, FIX, f"x-{tag}-fixture")
    # X1 read-only restore destination (the directory that holds FLH_DATA_DIR)
    img0 = h.running_image()
    os.chmod(data_parent, 0o555)
    try:
        rc, text, _ = h.stg("restore", path, log=f"X1-{tag}-restore-readonly-dest")
    finally:
        os.chmod(data_parent, 0o700)
    running = h.running_image() == img0 and h.ready(5)
    stages = [n for n in os.listdir(data_parent) if ".restore-" in n]
    intact = L.dump_hash(os.path.join(h.data, "app.db")) == dump0
    rec.record(f"X1-{tag}", (rc != 0 and intact) and ((not running) if older else (running and not stages)),
               f"[{tag}] read-only restore destination: " + ("GAP REPRODUCED: refused only after the stop, service down"
                                                              if older else "refused, data intact, service still running, no partial copy"),
               f"exit {rc}; running {running}; partial {stages}; message: {text.strip().splitlines()[-1][:150] if text.strip() else ''}")
    if not running:
        rc2, _, secs = h.stg("start", log=f"X1-{tag}-recover-start")
        rec.note(f"X1-{tag}", f"recovery: flh-daily.sh start exit {rc2} in {secs:.1f} s, ready {h.ready(30)}")
    for n in stages:
        rec.note(f"X1-{tag}", f"left behind: {n}")
    # X2 the disk fills during the restore copy (RLIMIT_FSIZE stops the copy as ENOSPC would)
    def limit():
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024, 64 * 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    img0 = h.running_image()
    rc, text, _ = h.stg("restore", path, log=f"X2-{tag}-restore-disk-full", preexec=limit)
    running = h.running_image() == img0 and h.ready(5)
    stages = [n for n in os.listdir(data_parent) if ".restore-" in n]
    intact = L.dump_hash(os.path.join(h.data, "app.db")) == dump0
    rec.record(f"X2-{tag}", (rc != 0 and intact) and ((not running and bool(stages)) if older else (running and not stages)),
               f"[{tag}] disk full during the restore copy: " + ("GAP REPRODUCED: service down and a partial copy left"
                                                                 if older else "refused, data intact, service still running, partial copy removed"),
               f"exit {rc}; running {running}; partial {stages}; message: {text.strip().splitlines()[-1][:150] if text.strip() else ''}")
    if not running:
        rc2, _, secs = h.stg("start", log=f"X2-{tag}-recover-start")
        rec.note(f"X2-{tag}", f"recovery: flh-daily.sh start exit {rc2} in {secs:.1f} s, ready {h.ready(30)}")
    # X3 interrupted backup: SIGHUP to the wrapper's process group in the middle of the copy
    shim = os.path.join(WORK, f"shim-{tag}")
    os.makedirs(shim, exist_ok=True)
    marker = os.path.join(shim, "copy-started")
    with open(os.path.join(shim, "cp"), "w") as fh:
        fh.write(f"#!/bin/sh\ntouch '{marker}'\nsleep 3\nexec /usr/bin/cp \"$@\"\n")
    os.chmod(os.path.join(shim, "cp"), 0o755)
    b = h.current()
    env = h.env()
    env.update(FLH_DAILY_ENV=h.env_file, FLH_COMPOSE_PROJECT=h.project,
               FLH_COMPOSE_OVERRIDE=os.path.join(b, "staging.override.yaml"), PATH=shim + ":" + os.environ["PATH"])
    p = subprocess.Popen(["bash", os.path.join(b, "repo", "scripts", "daily", "flh-daily.sh"), "backup"], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    end = time.time() + 60
    while time.time() < end and not os.path.exists(marker) and p.poll() is None:
        time.sleep(0.05)
    os.killpg(p.pid, signal.SIGHUP)
    out = p.communicate(timeout=60)[0].decode(errors="replace")
    rec.save(f"stg-X3-{tag}-backup-sighup.log", out)
    inc = [n for n in os.listdir(h.data + ".backups") if n.endswith(".incomplete")] if os.path.isdir(h.data + ".backups") else []
    stopped = h.container() is None
    rc2, _, secs = h.stg("start", log=f"X3-{tag}-recover-start")
    ready = h.ready(30)
    rec.record(f"X3-{tag}", bool(inc) and "backup FAILED" in out and L.dump_hash(os.path.join(h.data, "app.db")) == dump0 and ready,
               f"[{tag}] backup interrupted by a session hangup mid-copy: partial copy kept only as .incomplete, data intact; "
               "the service was left stopped (documented) and `start` recovers it",
               f"incomplete {inc}; service stopped after hangup {stopped}; start exit {rc2} {secs:.1f} s, ready {ready}")


try:
    # ---- D. two stand-in hosts with the bundle ----------------------------------------------------
    stg, ok, rc, text, secs = setup("stg", TAR, SHA)
    m, b = L.bundle_identity(stg.current())
    rec.record("D-stg", ok and rc == 0 and "IDENTITY OK" in text and stg.running_image() == b["image_id"],
               "stg: settings from parameters (0600), bundle installed and identity-checked", f"exit {rc}, {secs:.1f} s")
    rec.time("install_s", secs)
    dr, ok2, rc2, text2, _ = setup("dr", TAR, SHA)
    rec.record("D-dr", ok2 and rc2 == 0 and "IDENTITY OK" in text2, "dr: the same bundle installed and identity-checked", f"exit {rc2}")

    # ---- 12. restore the synthetic NAS-shaped backup ---------------------------------------------------
    t0 = time.time()
    ok, path, tar_bytes = fetch_backup(stg, FIX, "nas-fixture")
    rec.time("fixture_transfer_s", time.time() - t0)
    rec.record("12a", ok, "fixture backup arrives with its SHA-256 (tar + checksum)", f"{tar_bytes} bytes")
    t0 = time.time()
    rc, text, secs = stg.stg("restore", path, log="12-restore")
    restore_s = secs
    t1 = time.time()
    ready = rc == 0 and stg.ready(30)
    rec.time("restore_command_s", restore_s)
    rec.time("ready_after_restore_s", time.time() - t1)
    rec.time("restore_to_ready_s", time.time() - t0)
    rec.record("12b", ready, "flh-daily.sh restore of the fixture, ready", f"exit {rc}, {restore_s:.1f} s")
    db = os.path.join(stg.data, "app.db")
    d_active = L.dump_hash(db)
    for _ in range(5):
        stg.call("GET", "/readyz")
    counts = L.table_counts(db)
    rec.record("12c", d_active == fixture["dump_sha256"] == L.dump_hash(db) and counts == fixture["tables"],
               "restored dump == fixture dump; table counts == fixture; 5 /readyz calls write nothing",
               f"dump {str(d_active)[:12]} vs {fixture['dump_sha256'][:12]}; tables equal {counts == fixture['tables']}")
    f = fixture["facts"]
    st_e = stg.call("GET", f"/captures/{f['entries']['contract']}")[0]
    st_f = stg.call("GET", f"/captures/{f['entries']['fixture']}")[0]
    lesson = L.js(stg.call("GET", f"/listening/materials/{f['workbook']['material_id']}")[1])
    st_r1 = stg.call("GET", f"/listening/materials/{f['workbook']['material_id']}/revisions/1")[0]
    items = L.js(stg.call("GET", "/mistake-notebook/items")[1]).get("items", [])
    marked = [i for i in items if (i.get("retry") or {}).get("marked") is True]  # the fixture marks its one mistake
    practice = L.js(stg.call("GET", "/speaking/practice")[1])
    rec.save("12-speaking-practice.json", practice)
    rev = (lesson.get("script_revision") or {}).get("revision")
    rec.record("12d", st_e == 200 and st_f == 200 and rev == 2 and st_r1 == 200 and len(marked) == 1 and practice,
               "read back: contract entry, fixture entry, workbook revision 2 (revision 1 kept), retry mark, Speaking practice",
               f"entries {st_e}/{st_f}; revision {rev}, rev1 {st_r1}; marked {len(marked)}; practice keys {sorted(practice)[:4]}")
    st_r, st_h = stg.call("GET", "/readyz")[0], stg.call("GET", "/healthz")[0]
    first = capture("staging-first-write-001", "Première écriture sur la cible de staging : « je me souviens de ».")
    st_w, raw = stg.call("POST", "/captures", first)
    wid = L.js(raw).get("entry_id")
    st_w2 = stg.call("POST", "/captures", first)[0]
    st_g = stg.call("GET", f"/entries/{wid}")[0] if wid else None
    rec.record("12e", st_r == 200 and st_h == 200 and st_w == 201 and st_w2 == 200 and st_g == 200,
               "health: /readyz 200, /healthz 200; first supported write POST /captures 201, replay 200, readable",
               f"{st_r}/{st_h}; POST {st_w}, replay {st_w2}, GET {st_g}, entry {wid}")

    # ---- 13. restart persistence; backup -> another target ----------------------------------------------
    rc, _, secs = stg.stg("restart", log="13-restart")
    rec.time("restart_to_healthy_s", secs)
    ok = rc == 0 and stg.ready(30)
    rec.record("13a", ok and stg.call("GET", f"/entries/{wid}")[0] == 200 and stg.call("GET", f"/captures/{f['entries']['fixture']}")[0] == 200,
               "after flh-daily.sh restart: the first write and the restored data persist", f"restart exit {rc}, {secs:.1f} s")
    snap_stg = os.path.join(rec.evidence, "snapshot-stg.json")
    subprocess.run([sys.executable, "-I", "-B", os.path.join(stg.current(), "repo", "scripts", "validation", "v1_rehearsal", "snapshot.py"),
                    f"http://127.0.0.1:{stg.port}", snap_stg], capture_output=True)
    rc, text, secs = stg.stg("backup", log="13-backup")
    rec.time("backup_s", secs)
    bpath = next((l.split("backup written to ", 1)[1].split(" (copy", 1)[0] for l in text.splitlines() if "backup written to" in l), None)
    rec.record("13b", rc == 0 and bpath and stg.ready(30), "flh-daily.sh backup on stg: verified copy, service back up",
               f"exit {rc}, {secs:.1f} s, {os.path.basename(str(bpath))}")
    t0 = time.time()
    ok, path2, size2 = fetch_backup(dr, bpath, "stg-backup")
    rec.time("backup_transfer_s", time.time() - t0)
    t0 = time.time()
    rc, text, secs = dr.stg("restore", path2, log="13-dr-restore")
    ready = rc == 0 and dr.ready(30)
    rec.time("dr_restore_to_ready_s", time.time() - t0)
    snap_dr = os.path.join(rec.evidence, "snapshot-dr.json")
    subprocess.run([sys.executable, "-I", "-B", os.path.join(dr.current(), "repo", "scripts", "validation", "v1_rehearsal", "snapshot.py"),
                    f"http://127.0.0.1:{dr.port}", snap_dr], capture_output=True)
    same = os.path.exists(snap_stg) and os.path.exists(snap_dr) and open(snap_stg, "rb").read() == open(snap_dr, "rb").read()
    rc_id, text_id, _ = dr.tool("identity", log="13-dr-identity")
    rec.record("13c", ok and ready and same and L.dump_hash(os.path.join(dr.data, "app.db")) == L.dump_hash(os.path.join(bpath, "app.db"))
               and dr.call("GET", f"/entries/{wid}")[0] == 200 and rc_id == 0,
               "stg backup -> transfer -> restore into dr: ready, snapshot and dump equal, the first write present, dr identity OK",
               f"transfer {ok} ({size2} B), restore exit {rc}, snapshot equal {same}, identity exit {rc_id}")

    # ---- 14. data size ------------------------------------------------------------------------------
    rec.time("fixture_app_db_bytes", fixture["app_db_bytes"])
    rec.time("fixture_backup_bytes", fixture["backup_bytes"])
    rec.time("fixture_transfer_tar_bytes", tar_bytes)
    rec.note("14", f"timings and sizes: {json.dumps(rec.timings, sort_keys=True)}")

    # ---- 15. failure rehearsals on a running service ---------------------------------------------------
    failure_suite(stg, "bundle")
    if OLD:
        old, ok3, rc3, text3, _ = setup("oldwrapper", os.path.realpath(OLD[0]), OLD[1])
        rc, _, _ = old.stg("restore", path, log="15-old-restore")
        rec.record("15-old-setup", rc3 == 0 and rc == 0 and old.ready(30), "comparison host with the older wrapper, fixture restored", "")
        failure_suite(old, "older-wrapper")
except Exception as e:  # an unexpected error is a failure, never a silent pass
    import traceback
    rec.record("ERR", False, "no unexpected error", repr(e)[:300])
    rec.save("error.txt", traceback.format_exc())
finally:
    code = L.finish(rec, hosts, fp_before)
sys.exit(code)
