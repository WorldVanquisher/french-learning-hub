#!/usr/bin/env python3
"""Install, verify, roll back and fail bundles on a stand-in host (items 8-10).

  bundle_rehearsal.py OLD.tar OLD_SHA NEW.tar NEW_SHA BROKEN.tar BROKEN_SHA BACKUP_DIR WORK_DIR

OLD and NEW are two verified bundles of different revisions; BROKEN is a bundle
built through the same builder from a tree with a deliberately failing
migration (rehearsal only). BACKUP_DIR is a synthetic NAS-shaped backup.
Steps (results in WORK_DIR/results.tsv, timings in timings.json):
  V   verification on real bundles: wrong SHA-256, an altered file, an added
      file, a missing file, inconsistent identity, a swapped image; each is
      refused before anything is unpacked into bundles/ or the service changes
  I   first install of OLD, restore the backup, first write W1
  U   install NEW: pre-install backup, switch, identity; W1 kept, write W2
  R   rollback to OLD (re-verified), identity checked; W1 and W2 kept; and back
  F1  install interrupted halfway (SIGKILL during unpack/verify/load): current,
      service and identity unchanged; the partial unpack is cleaned next run
  F2  install of BROKEN fails after the switch: automatic switch back, the
      previous identity verified, data and ledger unchanged
  F3  the SSM session drops (SIGHUP, closed output) right after the switch:
      the install continues and finishes with a verified identity
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import standin_lib as L  # noqa: E402

OLD, OLD_SHA, NEW, NEW_SHA, BROKEN, BROKEN_SHA, BACKUP, WORK = sys.argv[1:9]
OLD, NEW, BROKEN, BACKUP = (os.path.realpath(x) for x in (OLD, NEW, BROKEN, BACKUP))
rec = L.Recorder(WORK)
WORK = rec.work
fp_before = L.daily_fingerprint()
rec.save("daily-fingerprint-before.txt", fp_before + "\n")
hosts = []


def stem(tar):
    return os.path.basename(tar)[:-4]


def unpacked_identity(tar):
    d = os.path.join(WORK, "peek")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    with tarfile.open(tar) as tf:
        for name in (f"{stem(tar)}/MANIFEST.json", f"{stem(tar)}/BUILD.json"):
            tf.extract(name, d)
    m = json.load(open(os.path.join(d, stem(tar), "MANIFEST.json")))
    b = json.load(open(os.path.join(d, stem(tar), "BUILD.json")))
    return m, b


def tamper(src_tar, label, change):
    """Unpack a copy, apply change(dir), re-tar; returns (tar, its own SHA-256): the
    operator is given the altered file's real hash, so only content checks can catch it."""
    d = os.path.join(WORK, "tamper", label)
    os.makedirs(d)
    with tarfile.open(src_tar) as tf:
        kw = {"filter": "tar"} if hasattr(tarfile, "data_filter") else {}
        tf.extractall(d, **kw)
    for dp, dns, fns in os.walk(d):
        for x in dns + fns:
            os.chmod(os.path.join(dp, x), 0o755 if os.path.isdir(os.path.join(dp, x)) else 0o644)
    name = change(os.path.join(d, stem(src_tar))) or stem(src_tar)
    out = os.path.join(WORK, "tamper", f"{label}", f"{name}.tar")
    if name != stem(src_tar):
        os.rename(os.path.join(d, stem(src_tar)), os.path.join(d, name))
    with tarfile.open(out, "w") as tf:
        tf.add(os.path.join(d, name), arcname=name)
    return out, L.sha256(out)


def reseal(bdir):
    lines = []
    for dp, _, fns in os.walk(bdir):
        for f in fns:
            p = os.path.relpath(os.path.join(dp, f), bdir)
            if p != "SHA256SUMS":
                lines.append(f"{L.sha256(os.path.join(bdir, p))}  {p}")
    open(os.path.join(bdir, "SHA256SUMS"), "w").write("\n".join(sorted(lines, key=lambda l: l[66:])) + "\n")


def identity_line(text):
    return next((l for l in text.splitlines() if "IDENTITY" in l), "")[:220]


def write(h, cid, text):
    body = {"schema_version": "learning_capture_v1", "capture_id": cid, "source": "manual", "original_input": text,
            "original_context": "FIXTURE-PRIVATE-STAGING: écriture de répétition, données synthétiques.",
            "discussion_summary": "FIXTURE-PRIVATE-SUMMARY: répétition de staging."}
    st, raw = h.call("POST", "/captures", body)
    return st, L.js(raw).get("entry_id")


def read_entry(h, eid):
    return h.call("GET", f"/entries/{eid}")[0]


try:
    m_old, b_old = unpacked_identity(OLD)
    m_new, b_new = unpacked_identity(NEW)
    h = L.Host(rec, "stg")
    hosts.append(h)
    ok, mode = h.render_settings()
    rec.record("H", ok, "settings rendered from parameters by flh-staging-env (0600, values never printed)", f"mode {oct(mode or 0)}")

    # ---- V. verification on real bundles (item 8) ----------------------------------------------------
    rc, text, _ = h.tool("verify", NEW, "--sha256", NEW_SHA, "--scratch", os.path.join(WORK), log="V0-verify")
    rec.record("V0", rc == 0 and "VERIFIED" in text, "the real bundle verifies", text.strip().splitlines()[-1][:200])
    cases = []
    cases.append(("V1", "wrong SHA-256 (the operator's value, not the file's)", NEW, "0" * 64, "is not the expected"))

    def alter(d):
        p = os.path.join(d, "repo", "scripts", "daily", "flh-daily.sh")
        open(p, "a").write("\n# altered\n")
    cases.append(("V2", "an altered script (SHA256SUMS left as is)", *tamper(NEW, "altered", alter), "altered file"))

    def alter_resealed(d):
        alter(d)
        reseal(d)
    cases.append(("V3", "an altered script with SHA256SUMS recomputed", *tamper(NEW, "resealed", alter_resealed), "MANIFEST files differ"))

    def add(d):
        open(os.path.join(d, "repo", "extra.sh"), "w").write("echo extra\n")
    cases.append(("V4", "an added file", *tamper(NEW, "added", add), "added"))

    def drop(d):
        os.unlink(os.path.join(d, "repo", "scripts", "release", "restore_write_check.py"))
    cases.append(("V5", "a missing file", *tamper(NEW, "missing", drop), "missing file"))

    def rename(d):
        return "flh-staging-" + "f" * 12
    cases.append(("V6", "inconsistent identity (renamed to another tree)", *tamper(NEW, "renamed", rename), "identity mismatch"))

    def swap_image(d):
        shutil.copyfile(os.path.join(os.path.dirname(OLD), stem(OLD), "image.tar"), os.path.join(d, "image.tar"))
        b = json.load(open(os.path.join(d, "BUILD.json")))
        b["image_tar_sha256"] = L.sha256(os.path.join(d, "image.tar"))
        b["image_id"] = b_old["image_id"]
        json.dump(b, open(os.path.join(d, "BUILD.json"), "w"))
        reseal(d)
    cases.append(("V7", "the image swapped for another revision's (BUILD.json and sums rewritten)",
                  *tamper(NEW, "swapped", swap_image), "image.tar tag"))
    for step, what, tar, sha, needle in cases:
        before = sorted(os.listdir(os.path.join(h.root, "bundles")))
        rc, text, _ = h.tool("install", tar, "--sha256", sha, log=f"{step}-install")
        after = sorted(os.listdir(os.path.join(h.root, "bundles")))
        rec.record(step, rc == 1 and needle in text and before == after and h.current() is None,
                   f"refused before install: {what}", f"exit {rc}; {needle!r} in message: {needle in text}; bundles/ unchanged {before == after}")

    # ---- I. first install of OLD, restore, first write ----------------------------------------------------
    rc, text, secs = h.tool("install", OLD, "--sha256", OLD_SHA, log="I1-install-old")
    rec.time("first_install_s", secs)
    rec.record("I1", rc == 0 and "IDENTITY OK" in text and h.running_image() == b_old["image_id"],
               "first install of OLD: verified, loaded, switched, started, identity OK", f"exit {rc}, {secs:.1f} s; {identity_line(text)}")
    t0 = time.time()
    rc, text, _ = h.stg("restore", BACKUP, log="I2-restore")
    ready = rc == 0 and h.ready()
    rec.time("restore_to_ready_s", time.time() - t0)
    rec.record("I2", ready, "restore the synthetic NAS-shaped backup with flh-daily.sh, ready", f"exit {rc}")
    st1, w1 = write(h, "bundle-rehearsal-w1", "W1 avant la mise à jour")
    rec.record("I3", st1 == 201 and w1, "first write W1 on OLD", f"{st1}, entry {w1}")

    # ---- U. install NEW ---------------------------------------------------------------------------------
    rc, text, secs = h.tool("install", NEW, "--sha256", NEW_SHA, log="U1-install-new")
    rec.time("upgrade_install_s", secs)
    log = open(os.path.join(h.root, "deploy.log")).read()
    rec.record("U1", rc == 0 and "IDENTITY OK" in text and h.running_image() == b_new["image_id"] and "\tbackup\t" in log
               and os.path.basename(os.path.realpath(os.path.join(h.root, "previous"))) == stem(OLD),
               "install NEW: pre-install backup recorded, switch, identity OK; previous = OLD",
               f"exit {rc}, {secs:.1f} s; {identity_line(text)}")
    st_r1 = read_entry(h, w1)
    st2, w2 = write(h, "bundle-rehearsal-w2", "W2 après la mise à jour")
    rec.record("U2", st_r1 == 200 and st2 == 201, "W1 still readable on NEW; write W2", f"W1 {st_r1}, W2 {st2} entry {w2}")

    # ---- R. rollback (item 9) ---------------------------------------------------------------------------
    rc, text, secs = h.tool("rollback", log="R1-rollback")
    rec.time("rollback_s", secs)
    rec.record("R1", rc == 0 and "verified again" in text and "IDENTITY OK" in text and h.running_image() == b_old["image_id"]
               and stem(OLD) in identity_line(text),
               "rollback: previous bundle re-verified from its files, switched, identity OK (OLD image, labels, server)",
               f"exit {rc}, {secs:.1f} s; {identity_line(text)}")
    rec.record("R2", read_entry(h, w1) == 200 and read_entry(h, w2) == 200,
               "after rollback, W1 and W2 (accepted on NEW) are both present: same database, no migration", "")
    rc, text, secs = h.tool("rollback", log="R3-rollback-again")
    rec.record("R3", rc == 0 and h.running_image() == b_new["image_id"], "roll forward again (rollback of the rollback): NEW verified and running",
               f"exit {rc}, {secs:.1f} s")
    rc, text, _ = h.tool("status", log="R4-status")
    rec.record("R4", rc == 0 and "IDENTITY OK" in text and stem(NEW) in text, "status reports current NEW, previous OLD, identity OK",
               identity_line(text))

    # ---- F1. install interrupted halfway (item 10) --------------------------------------------------------
    img_before = h.running_image()
    env = h.env()
    p = subprocess.Popen([sys.executable, "-I", L.BUNDLE_TOOL, "install", BROKEN, "--sha256", BROKEN_SHA], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    partial_seen = False
    end = time.time() + 30
    while time.time() < end and p.poll() is None:
        if any(n.startswith(".partial-") for n in os.listdir(os.path.join(h.root, "bundles"))):
            partial_seen = True
            time.sleep(0.2)
            break
        time.sleep(0.02)
    os.killpg(p.pid, signal.SIGKILL)
    p.wait()
    left = [n for n in os.listdir(os.path.join(h.root, "bundles")) if n.startswith(".partial-")]
    cur_ok = os.path.basename(h.current() or "") == stem(NEW)
    rc, text, _ = h.tool("status", log="F1-status-after-kill")
    rec.record("F1a", partial_seen and cur_ok and h.running_image() == img_before and "IDENTITY OK" in text,
               "install killed halfway (SIGKILL while unpacking/verifying): current, running image and identity unchanged",
               f"partial seen {partial_seen}, left {left}, current {os.path.basename(h.current() or '')}; {identity_line(text)}")
    rec.record("F1b", "interrupted unpack" in text or not left, "status names the interrupted unpack; the next run removes it",
               f"left after kill: {left}")

    # ---- F2. a bundle that fails after the switch -----------------------------------------------------
    led_before = L.ledger(os.path.join(h.data, "app.db"))
    t0 = time.time()
    rc, text, secs = h.tool("install", BROKEN, "--sha256", BROKEN_SHA, log="F2-install-broken")
    rec.time("failed_install_with_auto_switch_back_s", secs)
    left = [n for n in os.listdir(os.path.join(h.root, "bundles")) if n.startswith(".partial-")]
    log = open(os.path.join(h.root, "deploy.log")).read()
    rec.record("F2a", rc == 1 and "FAILED: switching back" in text and text.count("IDENTITY OK") >= 1
               and h.running_image() == b_new["image_id"] and os.path.basename(h.current()) == stem(NEW)
               and os.path.basename(os.path.realpath(os.path.join(h.root, "previous"))) == stem(OLD) and not left
               and "\trestored\t" in log,
               "install of a bundle whose migration fails: started, identity failed, switched back automatically, previous verified",
               f"exit {rc}, {secs:.1f} s; running {str(h.running_image())[:19]}; partial left {left}")
    rec.record("F2b", L.ledger(os.path.join(h.data, "app.db")) == led_before and read_entry(h, w1) == 200 and read_entry(h, w2) == 200,
               "the failed migration left the ledger and the data unchanged (one transaction per migration)",
               f"ledger {led_before} -> {L.ledger(os.path.join(h.data, 'app.db'))}")

    # ---- F3. SSM session drop right after the switch ----------------------------------------------------
    rc, text, _ = h.tool("rollback", log="F3-prep-rollback")  # current OLD, previous NEW: F3 installs NEW again
    p = subprocess.Popen([sys.executable, "-I", L.BUNDLE_TOOL, "install", NEW, "--sha256", NEW_SHA], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    switched = False
    end = time.time() + 60
    lines0 = open(os.path.join(h.root, "deploy.log")).read().count("\tswitch\t")
    while time.time() < end and p.poll() is None:
        if open(os.path.join(h.root, "deploy.log")).read().count("\tswitch\t") > lines0:
            switched = True
            break
        time.sleep(0.05)
    p.stdout.close()                      # the terminal is gone
    if p.poll() is None:
        os.killpg(p.pid, signal.SIGHUP)   # and the session's hangup reaches the whole group
    rc = p.wait(timeout=300)
    rc2, text2, _ = h.tool("status", log="F3-status-after-hangup")
    log = open(os.path.join(h.root, "deploy.log")).read()
    rec.record("F3", switched and rc == 0 and "IDENTITY OK" in text2 and h.running_image() == b_new["image_id"]
               and log.rstrip().splitlines()[-1].split("\t")[1] == "ok",
               "session dropped (output closed + SIGHUP) right after the switch: the install continued and verified NEW",
               f"switched {switched}, install exit {rc}; last log event {log.rstrip().splitlines()[-1].split(chr(9))[1]}; {identity_line(text2)}")
    shutil.copyfile(os.path.join(h.root, "deploy.log"), os.path.join(rec.evidence, "deploy.log"))
except Exception as e:  # an unexpected error is a failure, never a silent pass
    import traceback
    rec.record("ERR", False, "no unexpected error", repr(e)[:300])
    rec.save("error.txt", traceback.format_exc())
finally:
    code = L.finish(rec, hosts, fp_before)
sys.exit(code)
