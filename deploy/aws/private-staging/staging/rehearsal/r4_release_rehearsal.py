#!/usr/bin/env python3
"""R4 release-candidate rehearsal on stand-in hosts: bootstrap, failed boot, restart, deployment
verification, restore, binary and database rollback, ledger refusal and teardown (synthetic data only).

  r4_release_rehearsal.py --candidate TAR --rollback TAR --broken TAR --ahead TAR \
      --fixture DIR --inventory INVENTORY_PY WORK_DIR

Each bundle's SHA-256 is read from the .sha256 file beside it; the candidate's comes from the build
machine. TAR roles:
- candidate: the release;
- rollback: the nominated previous release;
- broken: rehearsal-only, a migration that fails;
- ahead: rehearsal-only, a valid migration 022 that moves the ledger past the candidate.

Evidence format (results.jsonl + summary.json, R4-REL-056/060): every row carries the R4 item, step,
PASS/FAIL, expected, actual, the run ID, the candidate's source commit and transfer SHA-256, and its
collection time (UTC). The summary binds the run ID, the candidate, the rollback bundle, the start and
end times and the daily fingerprint. Rows of another run can never join it (evidence_index.py checks).
Stand-ins only (standin_lib: own Compose projects on free loopback ports); no AWS, no daily instance.
"""
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import standin_lib as S  # noqa: E402

FORMAT = "flh-r4-rehearsal/v1"


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha_of(tar):
    with open(tar + ".sha256") as fh:
        return fh.read().split()[0]


def manifest_of(tar):
    import tarfile
    name = os.path.basename(tar)[:-4]
    with tarfile.open(tar) as tf:
        return json.loads(tf.extractfile(f"{name}/MANIFEST.json").read())


def ledger_of_copy(src_dir, scratch):
    """The migration count of a backup, read from a scratch copy so the source files never change."""
    td = os.path.join(scratch, f"ledger-{os.urandom(3).hex()}")
    os.makedirs(td)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(os.path.join(src_dir, "app.db" + suffix)):
            shutil.copyfile(os.path.join(src_dir, "app.db" + suffix), os.path.join(td, "app.db" + suffix))
    try:
        return S.ledger(os.path.join(td, "app.db"))
    finally:
        shutil.rmtree(td, ignore_errors=True)


def drop_image(tag):
    """Remove a stand-in image tag so the next install loads it (timing); refused by Docker if a container uses it."""
    return subprocess.run(["docker", "image", "rm", tag], capture_output=True, text=True).returncode == 0


def boot(R, h, tar, label, timings):
    """Install a bundle while measuring image readiness apart from process and application readiness."""
    tag = f"flh-staging:{os.path.basename(tar)[len('flh-staging-'):-4]}"
    if h.container():
        # an upgrade: the previous release answers until the switch, so readiness offsets would describe it,
        # not the new one; only the install total (verify, load, backup, switch, identity) is meaningful
        rc, text, secs = h.tool("install", tar, "--sha256", sha_of(tar), log=f"install-{label}")
        timings[label] = {"install_total_s": round(secs, 2), "note": "upgrade: see deploy.log for the switch"}
        return rc, text, secs
    dropped = drop_image(tag)
    seen, stop = {}, threading.Event()
    t0 = time.time()
    th = threading.Thread(target=watch_ready, args=(h.port, t0, seen, stop, tag), daemon=True)
    th.start()
    rc, text, secs = h.tool("install", tar, "--sha256", sha_of(tar), log=f"install-{label}")
    stop.set()
    th.join(5)
    timings[label] = {"image_loaded_s": seen.get("image") if dropped else "already present", "first_healthz_s": seen.get("healthz"),
                      "first_readyz_s": seen.get("readyz"), "install_total_s": round(secs, 2)}
    return rc, text, secs


def workstation_inventory():
    """Everything Docker shows that is NOT this run's stand-in (R4-REL-030)."""
    def lines(*cmd):
        return sorted(subprocess.run(["docker", *cmd], capture_output=True, text=True).stdout.split())
    keep = lambda xs: [x for x in xs if f"flh-stg-{S.RUN}" not in x]
    return {"containers": keep(lines("ps", "-a", "--format", "{{.Names}}:{{.ID}}")),
            "networks": keep(lines("network", "ls", "--format", "{{.Name}}")),
            "volumes": keep(lines("volume", "ls", "--format", "{{.Name}}"))}


class Run:
    def __init__(self, work, candidate, run_id):
        self.rec = S.Recorder(work)
        self.work = work
        m = manifest_of(candidate)
        self.base = {"run_id": run_id, "source_commit": m["revision"]["commit"], "artifact": os.path.basename(candidate),
                     "artifact_sha256": sha_of(candidate)}
        self.rows = []

    def row(self, item, step, ok, expected, actual):
        r = dict(self.base, item=item, step=step, status="PASS" if ok else "FAIL", expected=expected,
                 actual=str(actual)[:400], collected_at=utc())
        self.rows.append(r)
        with open(os.path.join(self.work, "results.jsonl"), "a") as fh:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
        self.rec.record(step, ok, f"[{item}] {expected}", actual)


def watch_ready(port, t0, out, stop, tag=None):
    """Offsets from install start: the image present (loaded), first /healthz 200 (process), first /readyz 200
    (application ready: the database answers and can start a write)."""
    while not stop.is_set():
        if tag and "image" not in out and subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode == 0:
            out["image"] = round(time.time() - t0, 2)
        if "healthz" not in out and S.call(port, "GET", "/healthz", timeout=2)[0] == 200:
            out["healthz"] = round(time.time() - t0, 2)
        if "readyz" not in out and S.call(port, "GET", "/readyz", timeout=2)[0] == 200:
            out["readyz"] = round(time.time() - t0, 2)
        if "healthz" in out and "readyz" in out:
            return
        time.sleep(0.1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ("candidate", "rollback", "broken", "ahead", "fixture", "inventory"):
        ap.add_argument(f"--{k}", required=True)
    ap.add_argument("work")
    a = ap.parse_args()
    run_id = f"R4-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{os.urandom(3).hex()}"
    R = Run(a.work, a.candidate, run_id)
    started = utc()
    fp = S.daily_fingerprint()
    ws_before = workstation_inventory()
    cand, rb, brk, ahd = a.candidate, a.rollback, a.broken, a.ahead
    cand_name, rb_name = os.path.basename(cand)[:-4], os.path.basename(rb)[:-4]
    timings = {}

    # --- 026/027/041: verify the rollback bundle first, then bring up the candidate on an empty host -----------
    h = S.Host(R.rec, "r4")
    ok, mode = h.render_settings()
    R.row("R4-REL-026", "H1", ok, "stand-in host settings rendered from synthetic parameters (0600)", oct(mode) if mode else None)
    rc, text, secs = h.tool("verify", rb, "--sha256", sha_of(rb), log="verify-rollback")
    R.row("R4-REL-041", "RB0", rc == 0 and "VERIFIED" in text, "the nominated rollback bundle verifies BEFORE the candidate is installed",
          f"exit {rc}, {secs:.1f} s")
    rc, text, secs = h.tool("verify", cand, "--sha256", sha_of(cand), log="verify-candidate")
    timings["verify_candidate_s"] = round(secs, 2)
    rc, text, secs = boot(R, h, cand, "candidate-first-boot", timings)
    b = timings["candidate-first-boot"]
    R.row("R4-REL-026", "B1", rc == 0 and "IDENTITY OK" in text, "the candidate installs on an empty stand-in, identity OK",
          f"exit {rc}, {secs:.1f} s")
    R.row("R4-REL-027", "B2", b["first_healthz_s"] is not None and b["first_readyz_s"] is not None
          and isinstance(b["image_loaded_s"], (int, float)),
          "bootstrap timing: image loaded, process up (/healthz) and application ready (/readyz) measured apart",
          json.dumps(b))

    # --- 036/037/038/040: the sealed synthetic backup through the S3 hop, restored into the empty data volume --
    t = time.time()
    tar, digest = S.transfer(a.fixture, a.work, "fixture")
    got, path = S.fetch(tar, digest, os.path.join(h.root, "transfer"))
    timings["transfer_s"] = round(time.time() - t, 3)
    sums = subprocess.run(["sha256sum", "--quiet", "-c", "SHA256SUMS"], cwd=path, capture_output=True, text=True)
    R.row("R4-REL-037", "S2", got and sums.returncode == 0, "checksums verified on arrival and before restore",
          f"transfer {'OK' if got else 'FAIL'}, SHA256SUMS exit {sums.returncode}")
    led = ledger_of_copy(path, a.work)
    m = manifest_of(cand)
    R.row("R4-REL-036", "S1", led == m["migrations"]["count"], "the sealed synthetic backup is on the candidate's ledger",
          f"backup ledger {led}, candidate {m['migrations']['count']} ({m['migrations']['last']})")
    bad = path + ".corrupt"
    shutil.copytree(path, bad)
    with open(os.path.join(bad, "app.db"), "r+b") as fh:
        fh.seek(4096)
        fh.write(b"\x00" * 64)
    rc_bad, text_bad, _ = h.stg("restore", bad, log="restore-corrupt-first")
    R.row("R4-REL-037", "S3", rc_bad != 0, "a corrupted copy fails closed: refused before anything changes", f"exit {rc_bad}")
    t = time.time()
    rc, text, secs = h.stg("restore", path, log="restore")
    ok_ready = h.ready(60)
    timings["restore_to_ready_s"] = round(time.time() - t, 2)
    R.row("R4-REL-038", "S4", rc == 0 and ok_ready, "restore into the empty data volume, then ready", f"exit {rc}, {secs:.1f} s")
    rc, _, _ = h.stg("stop", log="stop-for-inventory")
    inv = {}
    for side, src in (("source", path), ("restored", h.data)):
        out = os.path.join(a.work, f"inventory-{side}")
        r = subprocess.run([sys.executable, "-I", "-B", a.inventory, src, "--out", out], capture_output=True, text=True, timeout=900)
        R.rec.save(f"inventory-{side}.txt", f"exit {r.returncode}\n{r.stdout}{r.stderr}")
        try:
            with open(os.path.join(out, "inventory.json")) as fh:
                inv[side] = (r.returncode, json.load(fh))
        except (OSError, ValueError):
            inv[side] = (r.returncode, {})
    (rs, s_doc), (rd_, d_doc) = inv["source"], inv["restored"]
    R.row("R4-REL-038", "S5", rs == 0 and rd_ == 0 and s_doc.get("logical_digest") == d_doc.get("logical_digest")
          and s_doc.get("rows_by_table") == d_doc.get("rows_by_table"),
          "Workbooks inventory.py: READY on both, equal logical_digest and rows_by_table",
          f"source {rs}, restored {rd_}, tables {len(s_doc.get('rows_by_table') or {})}")
    h.stg("start", log="start-after-inventory")
    h.ready(60)
    age_h = (time.time() - os.path.getmtime(os.path.join(a.fixture, "SHA256SUMS"))) / 3600
    R.row("R4-REL-040", "S6", True, "backup age and transfer time recorded",
          f"backup sealed {age_h:.1f} h ago; transfer {timings['transfer_s']} s; restore to ready {timings['restore_to_ready_s']} s")

    # --- 039: a failed restore while the stand-in stays available -----------------------------------------------
    st1, _ = h.call("GET", "/readyz")
    rc_bad, _, _ = h.stg("restore", bad, log="restore-corrupt-running")
    st2, _ = h.call("GET", "/readyz")
    R.row("R4-REL-039", "S7", rc_bad != 0 and st1 == 200 and st2 == 200,
          "a corrupted restore fails before any stop; the running stand-in stays ready", f"exit {rc_bad}; readyz {st1} -> {st2}")

    # --- 029: restart (crash of the container and a wrapper restart): state and identity survive ----------------
    env_sha = hashlib.sha256(open(h.env_file, "rb").read()).hexdigest()
    st, raw = h.call("POST", "/entries", {"original_input": "R4 restart probe", "original_context": "synthetic"})
    eid = S.js(raw).get("id")
    cid = h.container()
    started_before = subprocess.run(["docker", "inspect", "-f", "{{.State.StartedAt}}", cid], capture_output=True, text=True).stdout.strip()
    pid = int(subprocess.run(["docker", "inspect", "-f", "{{.State.Pid}}", cid], capture_output=True, text=True).stdout.strip() or 0)
    if pid > 1:
        os.kill(pid, 9)            # the server process dies (a crash, not a `docker stop`): the restart policy applies
    time.sleep(2)
    back = h.ready(90)
    started_after = subprocess.run(["docker", "inspect", "-f", "{{.State.StartedAt}}", cid], capture_output=True, text=True).stdout.strip()
    st3, raw3 = h.call("GET", f"/entries/{eid}") if eid else (None, b"")
    rc, text, _ = h.tool("identity", log="identity-after-crash")
    R.row("R4-REL-029", "R1", back and st3 == 200 and rc == 0 and started_after != started_before,
          "after the server process dies, the restart policy restarts the container: the entry and identity survive",
          f"POST /entries {st}, restarted {started_after != started_before}, entry {st3}, identity exit {rc}")
    rc, _, _ = h.stg("restart", log="restart")
    rc2, text2, _ = h.tool("identity", log="identity-after-restart")
    env_same = hashlib.sha256(open(h.env_file, "rb").read()).hexdigest() == env_sha
    R.row("R4-REL-029", "R2", rc == 0 and rc2 == 0 and env_same and h.call("GET", f"/entries/{eid}")[0] == 200,
          "after a wrapper restart: identity OK, settings file unchanged, data kept", f"restart {rc}, identity {rc2}, settings same {env_same}")

    # --- 031/032/033/034: deployment verification ------------------------------------------------------------------
    rc, text, _ = h.tool("identity", log="identity-served-page")
    R.row("R4-REL-031", "V1", rc == 0 and '"served_page_matches": true' in text,
          "the page served on / is the index.html inside the verified image (served SHA-256 == image file)",
          text.strip().splitlines()[-1][:300] if text.strip() else "")
    app_db = os.path.join(h.data, "app.db")
    mode_db = stat.S_IMODE(os.stat(app_db).st_mode)
    os.chmod(app_db, 0o400)                 # the open connection keeps writing; the probe sees it after a restart
    subprocess.run(["docker", "restart", h.container()], capture_output=True)
    deadline = time.time() + 30
    hz, rz, rraw = None, None, b""
    while time.time() < deadline:
        hz, _ = h.call("GET", "/healthz")
        rz, rraw = h.call("GET", "/readyz")
        if hz == 200 and rz == 503:
            break
        time.sleep(0.5)
    shm_mode = oct(stat.S_IMODE(os.stat(app_db + "-shm").st_mode)) if os.path.exists(app_db + "-shm") else None
    for suffix in ("", "-wal", "-shm"):          # the documented remedy (RELEASE.md db-readonly): chmod 600 app.db*;
        if os.path.exists(app_db + suffix):      # SQLite recreated -shm with the read-only file's mode
            os.chmod(app_db + suffix, mode_db)
    subprocess.run(["docker", "restart", h.container()], capture_output=True)
    back = h.ready(30)
    R.row("R4-REL-032", "V2", hz == 200 and rz == 503 and b"storage_read_only" in rraw and back,
          "readiness reports writability: a read-only database is 503 storage_read_only while /healthz stays 200",
          f"healthz {hz}, readyz {rz} {rraw[:60]!r}; -shm recreated as {shm_mode}; after chmod 600 app.db* ready again {back}")
    cur_link = os.path.join(h.root, "current")
    cand_dir = os.path.realpath(cur_link)
    tmp = cur_link + ".r4"
    os.symlink(os.path.join(h.root, "bundles", rb_name), tmp)
    os.replace(tmp, cur_link)
    rc_wrong, _, _ = h.tool("identity", log="identity-wrong-bundle")
    os.symlink(cand_dir, tmp)
    os.replace(tmp, cur_link)
    rc_wh, text_wh, _ = h.tool("plan", cand, "--sha256", sha_of(cand), "--expect-target", "PROJECT=flh-stg-wrong-host",
                               log="plan-wrong-host")
    R.row("R4-REL-033", "V3", rc_wrong != 0 and rc_wh != 0 and "REFUSED" in text_wh,
          "a wrong bundle (current names another release) and a wrong host (--expect-target) both fail verification",
          f"wrong bundle identity exit {rc_wrong}; wrong host plan exit {rc_wh}")
    rc, text, _ = h.tool("status", log="status-final-candidate")
    hz, hraw = h.call("GET", "/healthz")
    rz, rraw = h.call("GET", "/readyz")
    summary_v = {"healthz": [hz, S.js(hraw)], "readyz": [rz, S.js(rraw)], "identity": "IDENTITY OK" in text,
                 "bundle": cand_name, "collected_at": utc()}
    R.row("R4-REL-034", "V4", hz == 200 and rz == 200 and summary_v["identity"],
          "health, readiness and version (bundle identity) in one summary record", json.dumps(summary_v, sort_keys=True))

    h.down()

    # --- 041/042/044/045: a second host runs the nominated previous release, upgrades to the candidate, then
    # rolls the binary back, rolls the database back, and is refused a rollback across a newer ledger ---------
    g = S.Host(R.rec, "rb")
    g.render_settings()
    rc, text, secs = boot(R, g, rb, "previous-release-first-boot", timings)
    got, gpath = S.fetch(*S.transfer(a.fixture, a.work, "fixture-rb"), os.path.join(g.root, "transfer"))
    rc_r, _, _ = g.stg("restore", gpath, log="restore-on-previous")
    rc_c, text_c, secs_c = boot(R, g, cand, "candidate-upgrade", timings)
    R.row("R4-REL-041", "RB0b", rc == 0 and rc_r == 0 and rc_c == 0 and "IDENTITY OK" in text_c,
          "the previous release (verified, installed, data restored) is upgraded to the candidate",
          f"previous {rc}, restore {rc_r}, candidate {rc_c} ({secs_c:.1f} s)")
    st, raw = g.call("POST", "/entries", {"original_input": "R4 written on the candidate", "original_context": "synthetic"})
    keep_id = S.js(raw).get("id")
    t = time.time()
    rc, text, secs = g.tool("rollback", "--to", rb_name, log="rollback-binary")
    st_keep = g.call("GET", f"/entries/{keep_id}")[0] if keep_id else None
    R.row("R4-REL-042", "RB1", rc == 0 and "ROLLED BACK" in text and st_keep == 200,
          "binary rollback: the previous release on the SAME database (ledger 21 = 21), the candidate's write kept",
          f"exit {rc}, {secs:.1f} s; POST {st}, entry after rollback {st_keep}")
    decision = {"decision": "rehearsal operator: roll back the binary to the nominated release", "elapsed_s": round(time.time() - t, 2),
                "final_identity": "IDENTITY OK" in text, "target": rb_name}
    R.row("R4-REL-045", "RB2", rc == 0 and decision["final_identity"], "operator decision, elapsed time and final identity recorded",
          json.dumps(decision, sort_keys=True))
    rc, text, secs = g.tool("install", cand, "--sha256", sha_of(cand), log="roll-forward-candidate")
    bdir = os.path.join(g.root, "data", "app.backups")
    backups = sorted(d for d in os.listdir(bdir) if d.startswith("flh-")) if os.path.isdir(bdir) else []
    st, raw = g.call("POST", "/entries", {"original_input": "R4 database rollback probe", "original_context": "synthetic"})
    probe_id = S.js(raw).get("id")
    rc_db, text_db, secs_db = g.stg("restore", os.path.join(bdir, backups[-1]), log="rollback-database") if backups else (1, "", 0)
    ready = g.ready(60)
    st_probe = g.call("GET", f"/entries/{probe_id}")[0] if probe_id else None
    rc_id, _, _ = g.tool("identity", log="identity-after-database-rollback")
    R.row("R4-REL-042", "RB3", rc == 0 and rc_db == 0 and ready and st_probe == 404 and rc_id == 0,
          "database rollback: the pre-install backup restored under the SAME (candidate) binary; the later write is gone",
          f"roll forward {rc}; restore {rc_db} ({secs_db:.1f} s) from {backups[-1] if backups else None}; probe now {st_probe}; identity {rc_id}")
    rc, text, _ = g.tool("install", ahd, "--sha256", sha_of(ahd), log="install-ahead")
    led_now = ledger_of_copy(g.data, a.work)
    rc_rf, text_rf, _ = g.tool("rollback", "--to", cand_name, log="rollback-refused")
    R.row("R4-REL-044", "RB4", rc == 0 and led_now == m["migrations"]["count"] + 1 and rc_rf != 0
          and ("migration" in text_rf.lower() or "ledger" in text_rf.lower()),
          "after a migration (ledger 22) rollback to a 21-migration bundle is REFUSED with its reason",
          f"install ahead {rc}, ledger {led_now}; rollback exit {rc_rf}: {text_rf.strip().splitlines()[-1][:200] if text_rf.strip() else ''}")
    g.down()

    # --- 028: a failed initial boot on a fresh host, with its diagnostics kept ---------------------------------------
    f = S.Host(R.rec, "fresh")
    f.render_settings()
    rc, text, secs = f.tool("install", brk, "--sha256", sha_of(brk), log="install-broken-first")
    diag_dir = os.path.join(f.root, "diagnostics")
    diags = sorted(os.listdir(diag_dir)) if os.path.isdir(diag_dir) else []
    keep = os.path.join(a.work, "failed-boot-diagnostics")
    os.makedirs(keep, exist_ok=True)
    for d in diags:
        shutil.copy(os.path.join(diag_dir, d), keep)
    R.row("R4-REL-028", "F1", rc != 0 and "no previous bundle" in text and len(diags) >= 1,
          "a failed initial boot (no previous bundle) fails visibly and keeps redacted diagnostics",
          f"exit {rc}, {secs:.1f} s, diagnostics {len(diags)} file(s)")
    f.down()

    # --- 030: teardown leaves the workstation as it was ----------------------------------------------------------------
    code = S.finish(R.rec, [h, g, f], fp)
    ws_after = workstation_inventory()
    with open(os.path.join(a.work, "workstation-before-after.json"), "w") as fh:
        json.dump({"before": ws_before, "after": ws_after}, fh, indent=1, sort_keys=True)
    ours = lambda name: f"flh-stg-{S.RUN}" in name
    vanished = {k: sorted(set(ws_before[k]) - set(ws_after[k])) for k in ws_before}
    ours_vanished = [x for k in vanished for x in vanished[k] if ours(x)]
    networks_volumes_same = not vanished["networks"] and not vanished["volumes"]
    left = [x for k in ws_after for x in ws_after[k] if ours(x)]
    R.row("R4-REL-030", "T1", not ours_vanished and networks_volumes_same and not left and S.daily_fingerprint() == fp,
          "teardown: no stand-in object left; no network or volume of others changed; the daily instance unchanged; any other "
          "container that vanished during the run is named (short-lived containers of other sessions, never ours)",
          f"left {left}; networks/volumes unchanged {networks_volumes_same}; other containers gone {vanished['containers']}")
    summary = dict(R.base, format=FORMAT, started_at=started, ended_at=utc(), rollback=rb_name,
                   rollback_sha256=sha_of(rb), timings=timings, daily_fingerprint=fp,
                   counts={"PASS": sum(r["status"] == "PASS" for r in R.rows), "FAIL": sum(r["status"] == "FAIL" for r in R.rows)},
                   rows_sha256=hashlib.sha256(open(os.path.join(a.work, "results.jsonl"), "rb").read()).hexdigest())
    with open(os.path.join(a.work, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1, sort_keys=True)
    print(f"R4 REHEARSAL {run_id}: {summary['counts']['PASS']} PASS, {summary['counts']['FAIL']} FAIL")
    return 1 if summary["counts"]["FAIL"] or code else 0


if __name__ == "__main__":
    sys.exit(main())
