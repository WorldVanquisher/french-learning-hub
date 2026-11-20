#!/usr/bin/env python3
"""An aborted NAS -> AWS cutover and its recovery, then a completed one rolled back after AWS writes
(items 054-058, 060). Every verdict comes from scripts/release/cutover_check.py on recorded evidence.

  aborted_cutover_rehearsal.py BUNDLE.tar SHA256 FIXTURE_DIR WORK_DIR

Two stand-in hosts (standin_lib: "nas" in the daily instance's role, "aws" in the staging host's),
each its own Compose project on a free loopback port, synthetic data only.
  A  attempt 1: boundary, final backup, transfer, AWS restore; AWS then fails its health check
     (container paused) -> DO-NOT-SWITCH before the traffic change; recovery = rollback case A:
     the NAS settings back, NAS started; nothing lost (N-check == boundary); a new NAS write works
  B  attempt 2: a new boundary, every check passes (HOLD until T1), switch (SWITCHED), the first
     write and two more on AWS; at the rollback decision (AWS stopped) -> ROLLBACK-B with the
     discard warning and the divergent window; procedure B: AWS backup, AWS guarded, transfer,
     NAS restore -> ROLLED-BACK; the AWS-only captures read back on the NAS
The daily instance is never touched (fingerprint before and after).
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import standin_lib as L  # noqa: E402

REPO = os.path.realpath(os.path.join(HERE, "..", "..", "..", "..", ".."))
CC = os.path.join(REPO, "scripts", "release", "cutover_check.py")
TAR, SHA, FIX, WORK = sys.argv[1:5]
TAR, FIX = os.path.realpath(TAR), os.path.realpath(FIX)
rec = L.Recorder(WORK)
WORK = rec.work
fp_before = L.daily_fingerprint()
rec.save("daily-fingerprint-before.txt", fp_before + "\n")
hosts = []


def cc(*args, log):
    r = subprocess.run([sys.executable, "-I", "-B", CC, *args], capture_output=True, text=True)
    rec.save(log, f"$ cutover_check.py {' '.join(os.path.basename(x) if os.sep in x else x for x in args)}\n"
                  f"exit {r.returncode}\n{r.stdout}{r.stderr}")
    return r.returncode, r.stdout + r.stderr


def record(ev, step, host, **kw):
    args = ["record", ev, "--step", step, "--host", host]
    for k, v in kw.items():
        args += [f"--{k.replace('_', '-')}", str(v)]
    return cc(*args, log=f"{os.path.basename(ev)[:-6]}-{step}.txt")[0] == 0


def verdict(ev, label):
    rc, out = cc("check", ev, log=f"{os.path.basename(ev)[:-6]}-check-{label}.txt")
    last = [l for l in out.splitlines() if l and l.split(":")[0] in ("HOLD", "DO-NOT-SWITCH", "SWITCHED", "ROLLBACK-A",
                                                                     "ROLLBACK-B", "ROLLED-BACK", "DIVERGED")]
    return (last[-1].split(":")[0] if last else None), out


def capture(cid, text):
    return {"schema_version": "learning_capture_v1", "capture_id": cid, "source": "manual", "original_input": text,
            "original_context": "FIXTURE-PRIVATE-CUTOVER: écriture synthétique de répétition.",
            "discussion_summary": "FIXTURE-PRIVATE-SUMMARY: répétition de bascule."}


def move_aside(path, label):
    dest = f"{path}.{label}-{L.RUN}"
    os.rename(path, dest)
    return dest


def ready_url(h):
    return f"http://127.0.0.1:{h.port}/readyz"


def boundary_to_aws(ev, nas, aws, label):
    """C1-C5: AWS emptied, NAS frozen and guarded, final backup, transfer, AWS restore."""
    rc, _, _ = aws.stg("stop", log=f"{label}-C1-stop")
    move_aside(aws.data, f"{label}-aside")
    os.makedirs(aws.data, mode=0o700)
    ok = rc == 0 and record(ev, "C1-aws-empty", "aws", db=os.path.join(aws.data, "app.db"))
    w = nas.call("POST", "/captures", capture(f"{label}-nas-last-write", f"Dernière écriture NAS ({label})."))[0]
    rc, _, _ = nas.stg("stop", log=f"{label}-C2-stop")
    moved = move_aside(nas.env_file, f"{label}-moved-to-aws")
    guard = nas.stg("status", log=f"{label}-C2-guard")[0]
    ok = ok and w == 201 and rc == 0 and guard == 2 and record(ev, "C2-boundary", "nas", db=os.path.join(nas.data, "app.db"))
    rc, _, _ = nas.stg("backup", log=f"{label}-C3-backup", extra_env={"FLH_DAILY_ENV": moved})
    bdir = os.path.join(nas.data + ".backups", sorted(os.listdir(nas.data + ".backups"))[-1])
    ok = ok and rc == 0 and record(ev, "C3-backup", "nas", db=os.path.join(bdir, "app.db"))
    tar, digest = L.transfer(bdir, WORK, f"{label}-final-{os.path.basename(bdir)}")
    ok = ok and record(ev, "C4-sent", "nas", file=tar)
    fetched, path = L.fetch(tar, digest, os.path.join(aws.root, "transfer"))
    ok = ok and fetched and record(ev, "C4-received", "aws", file=os.path.join(aws.root, "transfer", os.path.basename(tar)))
    rc, _, secs = aws.stg("restore", path, log=f"{label}-C5-restore")
    return ok and rc == 0, moved


try:
    nas, aws = L.Host(rec, "nas"), L.Host(rec, "aws")
    hosts += [nas, aws]
    for h in hosts:
        ok, _ = h.render_settings()
        rc, text, _ = h.tool("install", TAR, "--sha256", SHA, log="install")
        okf, path = L.fetch(*L.transfer(FIX, WORK, f"seed-{h.name}"), os.path.join(h.root, "transfer"))
        rc2, _, _ = h.stg("restore", path, log="seed-restore")
        rec.record(f"P-{h.name}", ok and rc == 0 and okf and rc2 == 0 and h.ready(30), f"{h.name}: bundle installed, fixture restored, ready", "")
    rec.record("P-aws-pass", aws.call("POST", "/captures", capture("staging-pass-write", "Passage de staging."))[0] == 201,
               "AWS holds data from its staging pass (to be moved aside, never deleted)", "")

    # ---- A: attempt 1, aborted before the traffic change -------------------------------------------------
    ev1 = os.path.join(WORK, "attempt1.jsonl")
    ok, moved = boundary_to_aws(ev1, nas, aws, "a1")
    rec.record("A1", ok, "attempt 1: C1-C5 recorded (AWS emptied, boundary, backup, transfer, restore)", "")
    subprocess.run(["docker", "pause", aws.container()], capture_output=True)
    record(ev1, "C5-restored", "aws", db=os.path.join(aws.data, "app.db"), ready_url=ready_url(aws))
    v, out = verdict(ev1, "after-health-failure")
    rec.record("A2", v == "DO-NOT-SWITCH" and "C5-restored" in out and "keep private access on the NAS" in out,
               "AWS health check fails before T1 -> DO-NOT-SWITCH, NAS stays the writer (item 054)", v)
    subprocess.run(["docker", "unpause", aws.container()], capture_output=True)
    rc, _, _ = aws.stg("stop", log="a1-aws-stop")
    os.rename(moved, nas.env_file)                                # rollback case A: settings back, NAS started
    rc2, _, _ = nas.stg("start", log="a1-nas-start")
    record(ev1, "N-check", "nas", db=os.path.join(nas.data, "app.db"))
    v, out = verdict(ev1, "after-rollback-a")
    same = "writes on the NAS after its boundary" not in out
    w = nas.call("POST", "/captures", capture("a1-after-abort", "Écriture NAS après abandon."))[0]
    rec.record("A3", rc == 0 and rc2 == 0 and nas.ready(30) and same and w == 201,
               "rollback before any target write (case A): NAS started, == its boundary (nothing lost), new write 201 (item 055)",
               f"verdict {v}; NAS unchanged {same}; write {w}")

    # ---- B: attempt 2, completed, then rolled back after AWS writes --------------------------------------
    ev2 = os.path.join(WORK, "attempt2.jsonl")
    ok, moved = boundary_to_aws(ev2, nas, aws, "a2")
    record(ev2, "C5-restored", "aws", db=os.path.join(aws.data, "app.db"), ready_url=ready_url(aws))
    v_hold, _ = verdict(ev2, "before-smoke")
    # replay the last capture written before the boundary, byte for byte: 200, nothing new
    replay = aws.call("POST", "/captures", capture("a2-nas-last-write", "Dernière écriture NAS (a2)."))[0]
    record(ev2, "C6-smoke", "aws", db=os.path.join(aws.data, "app.db"), ready_url=ready_url(aws), http_code=replay or 0)
    v_ready, _ = verdict(ev2, "before-switch")
    record(ev2, "C7-switch", "client", note="private access -> aws (stand-in port)")
    v_sw, out_sw = verdict(ev2, "after-switch")
    rec.record("B1", ok and v_hold == "HOLD" and replay == 200 and v_ready == "HOLD" and v_sw == "SWITCHED"
               and "freeze window (T1 - T0)" in out_sw,
               "attempt 2: every check passes; HOLD until T1, then SWITCHED; freeze window measured", f"{v_hold}/{v_ready}/{v_sw}, replay {replay}")
    codes = [aws.call("POST", "/captures", capture(f"a2-aws-write-{i}", f"Écriture AWS {i}."))[0] for i in range(3)]
    record(ev2, "C8-first-write", "aws", http_code=codes[0])
    time.sleep(1.1)
    rc, _, _ = aws.stg("stop", log="a2-R0-stop")
    record(ev2, "A-check", "aws", db=os.path.join(aws.data, "app.db"))
    v, out = verdict(ev2, "rollback-decision")
    rec.record("B2", codes == [201, 201, 201] and v == "ROLLBACK-B" and "WARNING: restarting the NAS now would discard" in out
               and "divergent writes on AWS since the boundary" in out,
               "rollback decision after AWS writes: ROLLBACK-B, plain-language discard warning, divergent window (056-058)",
               next((l for l in out.splitlines() if l.startswith("divergent")), "")[:110])
    rc, _, _ = aws.stg("backup", log="a2-R1-aws-backup")
    abk = os.path.join(aws.data + ".backups", sorted(os.listdir(aws.data + ".backups"))[-1])
    move_aside(aws.env_file, "a2-rolled-back-to-nas")
    guard = aws.stg("start", log="a2-R1-aws-guard")[0]
    okf, path = L.fetch(*L.transfer(abk, WORK, f"a2-aws-{os.path.basename(abk)}"), os.path.join(nas.root, "transfer"))
    os.rename(moved, nas.env_file)
    rc2, _, _ = nas.stg("restore", path, log="a2-R1-nas-restore")
    record(ev2, "R-restored", "nas", db=os.path.join(nas.data, "app.db"))
    v, out = verdict(ev2, "after-procedure-b")
    st = nas.call("GET", "/captures/a2-aws-write-2")[0]
    rec.record("B3", rc == 0 and guard == 2 and okf and rc2 == 0 and v == "ROLLED-BACK" and nas.ready(30) and st == 200,
               "procedure B: AWS backup, AWS guarded (refused), transfer, NAS restore -> ROLLED-BACK; AWS-only capture on the NAS",
               f"guard {guard}, restore {rc2}, verdict {v}, GET capture {st}")
finally:
    for h in hosts:  # put moved settings files back so the stand-ins can be torn down
        for n in sorted(os.listdir(h.root)):
            if n.startswith("staging.env.") and not os.path.exists(h.env_file):
                os.rename(os.path.join(h.root, n), h.env_file)
        c = h.container()
        if c:
            subprocess.run(["docker", "unpause", c], capture_output=True)
    sys.exit(L.finish(rec, hosts, fp_before))
