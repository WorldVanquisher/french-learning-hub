#!/usr/bin/env python3
"""Deployment controls on a stand-in host (items 081-087).

  deploy_controls_rehearsal.py OLD.tar OLD_SHA NEW.tar NEW_SHA FIXTURE_DIR WORK_DIR

  P   the OLD bundle installed with --expect-target matching this host; the fixture restored
  D1  plan NEW: target, current, proposed, what differs, image, ledger, rollback target, steps;
      exit 0 and nothing changed (current, previous, bundles/ and the data identical before and after)
  D2  plan and install with a mismatched target (another BUCKET): REFUSED before anything
  D3  install NEW: INSTALLED; status names the candidate (bundle, tree, image, server, readyz)
  D4  a readiness that never becomes healthy (app.db made read-only, install OLD --no-backup): the
      install fails, writes redacted diagnostics (readyz 503, storage_read_only, logs) and the
      diagnosis tool names db-readonly; after chmod 600 the service is back on NEW with its identity
  D5  cleanup: a stale bundle, an interrupted unpack and old transfer files are listed, then removed
      with --yes; the data, backups, settings, current and previous are untouched
The daily instance is never touched (fingerprint before and after).
"""
import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import standin_lib as L  # noqa: E402

REPO = os.path.realpath(os.path.join(HERE, "..", "..", "..", "..", ".."))
OLD, OLD_SHA, NEW, NEW_SHA, FIX, WORK = sys.argv[1:7]
OLD, NEW, FIX = os.path.realpath(OLD), os.path.realpath(NEW), os.path.realpath(FIX)
rec = L.Recorder(WORK)
WORK = rec.work
fp_before = L.daily_fingerprint()
rec.save("daily-fingerprint-before.txt", fp_before + "\n")
hosts = []


def tree_digest(path):
    """Names, sizes and contents of everything under path (symlinks by target)."""
    h = hashlib.sha256()
    for dp, dns, fns in sorted(os.walk(path)):
        dns.sort()
        for n in sorted(fns + [d for d in dns if os.path.islink(os.path.join(dp, d))]):
            p = os.path.join(dp, n)
            h.update(os.path.relpath(p, path).encode())
            if os.path.islink(p):
                h.update(os.readlink(p).encode())
            elif os.path.isfile(p):
                with open(p, "rb") as fh:
                    h.update(hashlib.sha256(fh.read()).digest())
    return h.hexdigest()


def state(h):
    keep = [os.path.join(h.root, n) for n in ("bundles", "data")]
    return [os.path.realpath(os.path.join(h.root, "current")) if os.path.islink(os.path.join(h.root, "current")) else None,
            os.path.realpath(os.path.join(h.root, "previous")) if os.path.islink(os.path.join(h.root, "previous")) else None] + \
        [tree_digest(k) for k in keep]


try:
    h = L.Host(rec, "dc")
    hosts.append(h)
    conf = os.path.join(h.root, "staging.conf")
    with open(conf, "w") as fh:
        fh.write(f"REGION=us-east-1\nBUCKET=flh-stg-standin\nPARAM_DIR=/flh/staging\nROOT={h.root}\nPORT={h.port}\n")
    os.environ["FLH_STAGING_CONF"] = conf                  # read by every flh-staging-bundle run below
    ok, _ = h.render_settings()
    match = ["--expect-target", "BUCKET=flh-stg-standin", "--expect-target", "REGION=us-east-1",
             "--expect-target", f"PROJECT={h.project}"]
    rc, text, _ = h.tool("install", OLD, "--sha256", OLD_SHA, *match, log="P-install-old")
    okf, path = L.fetch(*L.transfer(FIX, WORK, "seed"), os.path.join(h.root, "transfer"))
    rc2, _, _ = h.stg("restore", path, log="P-restore")
    rec.record("P", ok and rc == 0 and "INSTALLED" in text and rc2 == 0 and h.ready(30),
               "OLD installed with a matching --expect-target; the fixture restored; ready", f"install {rc}, restore {rc2}")

    before = state(h)
    rc, text, _ = h.tool("plan", NEW, "--sha256", NEW_SHA, *match, log="D1-plan")
    after = state(h)
    want = ["target:", "current:", "previous:", "proposed:", "differs from current: tree", "image:", "data:     ledger 21",
            "rollback target after install:", "steps:", "PLAN: install would proceed"]
    missing = [w for w in want if w not in text]
    rec.record("D1", rc == 0 and not missing and before == after,
               "plan NEW: target, current, previous, proposed, differences, image, ledger, rollback target, steps; nothing changed",
               f"exit {rc}; missing {missing or 'none'}; host state unchanged {before == after}")

    bad = ["--expect-target", "BUCKET=flh-stg-someone-else"]
    rc_p, text_p, _ = h.tool("plan", NEW, "--sha256", NEW_SHA, *bad, log="D2-plan-mismatch")
    rc_i, text_i, _ = h.tool("install", NEW, "--sha256", NEW_SHA, *bad, log="D2-install-mismatch")
    rec.record("D2", rc_p == 1 and rc_i == 1 and "target identity mismatch: BUCKET is 'flh-stg-standin'" in text_i
               and state(h) == after,
               "a mismatched target identity (BUCKET): plan and install REFUSED before anything; nothing changed",
               f"plan {rc_p}, install {rc_i}")

    rc, text, _ = h.tool("install", NEW, "--sha256", NEW_SHA, *match, log="D3-install-new")
    rc_s, st, _ = h.tool("status", log="D3-status")
    name = os.path.basename(NEW)[:-4]
    rec.record("D3", rc == 0 and f"INSTALLED {name}" in text and f'"bundle": "{name}"' in st and "IDENTITY OK" in st
               and '"server_matches": true' in st and '"readyz": 200' in st,
               "install NEW; the health check names the candidate (bundle, tree, image, server, readyz 200)",
               next((l for l in st.splitlines() if "IDENTITY" in l), "")[:150])

    db = os.path.join(h.data, "app.db")
    os.chmod(db, 0o444)
    rc, text, _ = h.tool("install", OLD, "--sha256", OLD_SHA, "--no-backup", *match, log="D4-install-unhealthy")
    diag_dir = os.path.join(h.root, "diagnostics")
    diags = sorted(os.listdir(diag_dir)) if os.path.isdir(diag_dir) else []
    dtext = open(os.path.join(diag_dir, diags[-1])).read() if diags else ""
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(REPO, "scripts", "release", "diagnose.py"), "--env",
                        h.env_file, "--running"], capture_output=True, text=True)
    rec.save("D4-diagnose.txt", r.stdout + r.stderr)
    rec.record("D4", rc != 0 and diags and "readyz 503" in dtext and h.root not in dtext and "[db-readonly]" in r.stdout
               and oct(os.stat(os.path.join(diag_dir, diags[-1])).st_mode & 0o777) == "0o600",
               "readiness never healthy: install fails, redacted diagnostics (readyz 503, no ROOT path), diagnose names db-readonly",
               f"install exit {rc}; diagnostics {diags[-1] if diags else 'none'}; diagnose {r.stdout.splitlines()[-2] if r.stdout else ''}"[:200])
    for f in os.listdir(h.data):                         # the RECOVER line exactly: chmod 600 app.db*, then restart
        if f.startswith("app.db"):
            os.chmod(os.path.join(h.data, f), 0o600)
    rc_up, _, _ = h.stg("restart", log="D4-restart-after-fix")
    rc_s, st, _ = h.tool("status", log="D4-status-after-fix")
    rec.record("D4b", "then restart" in r.stdout and rc_up == 0 and "IDENTITY OK" in st and f'"bundle": "{name}"' in st,
               "following RECOVER (chmod 600 app.db*, restart): the service runs NEW again with its identity checked",
               f"restart {rc_up}")

    os.makedirs(os.path.join(h.root, "bundles", "flh-staging-000000000000", "repo"))
    os.makedirs(os.path.join(h.root, "bundles", ".partial-flh-staging-000000000000-x"))
    tdir = os.path.join(h.root, "transfer")
    for i, n in enumerate(("flh-staging-aaaaaaaaaaaa", "flh-staging-bbbbbbbbbbbb", "flh-staging-cccccccccccc")):
        for suf in (".tar", ".tar.sha256"):
            with open(os.path.join(tdir, n + suf), "w") as fh:
                fh.write("synthetic")
            os.utime(os.path.join(tdir, n + suf), (1700000000 + i, 1700000000 + i))
    keep = [h.data, h.data + ".backups", h.env_file]
    before = [tree_digest(p) if os.path.isdir(p) else open(p, "rb").read() for p in keep] + state(h)[:2]
    rc, dry, _ = h.tool("cleanup", log="D5-cleanup-dry")
    rc2, wet, _ = h.tool("cleanup", "--yes", log="D5-cleanup-yes")
    after = [tree_digest(p) if os.path.isdir(p) else open(p, "rb").read() for p in keep] + state(h)[:2]
    gone = not os.path.exists(os.path.join(h.root, "bundles", "flh-staging-000000000000")) and \
        not os.path.exists(os.path.join(tdir, "flh-staging-aaaaaaaaaaaa.tar"))
    rec.record("D5", rc == 0 and rc2 == 0 and "would remove bundles/flh-staging-000000000000" in dry and "nothing removed" in dry
               and "removing transfer/flh-staging-aaaaaaaaaaaa.tar" in wet and gone and before == after
               and os.path.exists(os.path.join(tdir, "flh-staging-cccccccccccc.tar")),
               "cleanup lists then removes stale bundles, unpacks and old transfers; data, backups, settings, current, previous untouched",
               f"{dry.strip().splitlines()[-1][-90:]}")
finally:
    os.environ.pop("FLH_STAGING_CONF", None)
    for h in hosts:
        db = os.path.join(h.data, "app.db")
        if os.path.exists(db):
            os.chmod(db, 0o600)
    sys.exit(L.finish(rec, hosts, fp_before))
