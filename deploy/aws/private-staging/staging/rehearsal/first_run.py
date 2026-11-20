#!/usr/bin/env python3
"""First-run walkthrough from a fresh fixture, as a new operator types it (items 071-073, 080).

  first_run.py BUNDLE.tar SHA256 WORK_DIR

1. A fresh fixture: a stand-in "seed" host starts the bundle on an EMPTY data directory (the
   server creates the database and applies every migration), takes three synthetic captures
   through the API, and `flh-daily.sh backup` seals them. That backup is the fixture.
2. A second stand-in "first" host is set up the way RUNBOOK §5-§7 describe, every command
   typed through one bash session that starts with `eval "$(flh-staging-bundle shell)"`:
   no setting is copied by hand except the bundle's SHA-256, which the operator types on
   purpose (it must come from the operator machine, never from the host or S3).
3. Every step is logged as typed, with its exit status and time, then counted: the steps, the
   values typed by hand, and the owner-only steps that only a real AWS run can show.
Stand-ins only (standin_lib: own Compose projects on free loopback ports, synthetic data); the
daily instance is never touched (fingerprint before and after).
"""
import json
import os
import shlex
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import standin_lib as L  # noqa: E402

TAR, SHA, WORK = sys.argv[1:4]
TAR = os.path.realpath(TAR)
rec = L.Recorder(WORK)
WORK = rec.work
fp_before = L.daily_fingerprint()
rec.save("daily-fingerprint-before.txt", fp_before + "\n")
hosts = []
steps = []          # (section, typed command, exit, seconds)
BIN = os.path.join(WORK, "bin")
os.makedirs(BIN)
for name, target in (("flh-staging-bundle", f"exec python3 -I {shlex.quote(L.BUNDLE_TOOL)} \"$@\""),
                     ("flh-staging-env", f"exec bash {shlex.quote(L.RENDER_ENV)} \"$@\"")):
    with open(os.path.join(BIN, name), "w") as fh:
        fh.write(f"#!/bin/sh\n{target}\n")
    os.chmod(os.path.join(BIN, name), 0o755)


def capture(cid, text):
    return {"schema_version": "learning_capture_v1", "capture_id": cid, "source": "manual", "original_input": text,
            "original_context": "FIXTURE-PRIVATE-FIRST-RUN: écriture synthétique.",
            "discussion_summary": "FIXTURE-PRIVATE-SUMMARY: premier passage."}


def session(h):
    """The operator's shell on host h: PATH with the host tools, the stand-in's settings file and root."""
    conf = os.path.join(h.root, "staging.conf")
    with open(conf, "w") as fh:
        fh.write(f"REGION=us-east-1\nBUCKET=flh-stg-standin\nPARAM_DIR=/flh/staging\nROOT={h.root}\nPORT={h.port}\n")
    env = h.env()
    env.update(PATH=BIN + os.pathsep + env.get("PATH", ""), FLH_STAGING_CONF=conf)
    return env


def typed(h, section, command, env):
    """Run one typed command in a session that starts with the shell helper, as the operator would."""
    script = 'eval "$(flh-staging-bundle shell)"\n' + command
    t0 = time.time()
    r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=600)
    secs = time.time() - t0
    steps.append({"section": section, "command": command, "exit": r.returncode, "seconds": round(secs, 2)})
    rec.save(f"{h.name}-{len(steps):02d}.log", f"$ {command}\nexit {r.returncode} ({secs:.1f} s)\n{r.stdout}{r.stderr}")
    return r.returncode, r.stdout + r.stderr


try:
    # ---- 1. a fresh fixture ------------------------------------------------------------------------
    seed = L.Host(rec, "seed")
    hosts.append(seed)
    ok, _ = seed.render_settings()
    rc, text, _ = seed.tool("install", TAR, "--sha256", SHA, log="install")
    ready = seed.ready(60)
    codes = [seed.call("POST", "/captures", capture(f"first-run-fixture-{i}", f"Phrase de départ {i}."))[0] for i in range(3)]
    rc_b, _, _ = seed.stg("backup", log="seed-backup")
    fixture = os.path.join(seed.data + ".backups", sorted(os.listdir(seed.data + ".backups"))[-1])
    rec.record("F1", ok and rc == 0 and ready and codes == [201] * 3 and rc_b == 0,
               "fresh fixture: empty data dir -> created and migrated by the server, 3 captures, sealed backup",
               f"install {rc}, captures {codes}, backup {rc_b}")
    seed.down()

    # ---- 2. the first run, as typed ------------------------------------------------------------------
    first = L.Host(rec, "first")
    hosts.append(first)
    env = session(first)
    pj = os.path.join(WORK, "ssm-first.json")
    with open(pj, "w") as fh:
        json.dump({"Parameters": [{"Name": f"/flh/staging/{k}", "Value": v} for k, v in
                                  [("FLH_DATA_DIR", first.data), ("FLH_HOST_PORT", str(first.port)),
                                   ("FLH_UID", str(os.getuid())), ("FLH_GID", str(os.getgid()))] + L.PARAMS]}, fh)
    os.chmod(pj, 0o600)
    env["FLH_STAGING_PARAMS_JSON"] = pj        # the stand-in for SSM Parameter Store (same renderer)
    shutil_copy = __import__("shutil").copyfile
    tname = os.path.basename(TAR)
    shutil_copy(TAR, os.path.join(first.root, "transfer", tname))                       # stands for `aws s3 cp`
    tar_fix, dig_fix = L.transfer(fixture, WORK, os.path.basename(fixture))
    shutil_copy(tar_fix, os.path.join(first.root, "transfer", os.path.basename(tar_fix)))
    plan = [
        ("§5 settings", 'flh-staging-env "$REGION" "$PARAM_DIR" "$ROOT/staging.env"'),
        ("§5 install", f'flh-staging-bundle install "$ROOT/transfer/{tname}" --sha256 {SHA}'),
        ("§5 status", "flh-staging-bundle status && stg status"),
        ("§6 unpack", f'bt unpack "$ROOT/transfer/{os.path.basename(tar_fix)}" --sha256 {dig_fix} "$ROOT/transfer"'),
        ("§6 restore", 'stg restore "$(bt latest "$ROOT/transfer")"'),
        ("§7 diagnose", 'dx --env "$ROOT/staging.env" --running'),
        ("§7 ready", 'curl -fsS "http://127.0.0.1:$PORT/readyz"; echo'),
        ("§7 first write", 'curl -fsS -o /dev/null -w "%{http_code}\\n" -H "Content-Type: application/json" '
                           f'-d {shlex.quote(json.dumps(capture("first-run-write-001", "Première écriture.")))} '
                           '"http://127.0.0.1:$PORT/captures"'),
        ("§8 backup", "stg backup && bt inspect \"$(bt latest \"$ROOT/data/app.backups\")\""),
        ("§8 next", 'bt next-action "$ROOT/data/app"; bt restore-state "$ROOT/data/app"'),
    ]
    results = {}
    for section, command in plan:
        rc, out = typed(first, section, command, env)
        results[section] = (rc, out)
    ok = all(results[s][0] == 0 for s in results if s != "§8 next")
    rec.record("W1", ok, "first run: every typed step exits 0 (settings, install, status, unpack, restore, diagnose, "
               "ready, first write, backup)", ", ".join(f"{s} {results[s][0]}" for s in results))
    rec.record("W2", '"status":"ready"' in results["§7 ready"][1].replace(" ", "") and
               results["§7 first write"][1].strip().endswith("201") and "nothing found" in results["§7 diagnose"][1],
               "ready, first write 201, diagnose finds nothing", "")
    rec.record("W3", "NEXT [ok]" in results["§8 next"][1] and ": RESTORED" in results["§8 next"][1],
               "after the run: every backup complete; restore-state RESTORED (previous data kept)", "")

    # ---- 3. what a fresh operator still does ----------------------------------------------------------
    typed_values = [s["command"] for s in steps if SHA in s["command"] or dig_fix in s["command"]]
    owner_only = ["§0 authorization (budget, region, window)", "§1 build from a commit (git; build_bundle.sh --git)",
                  "§2 IAM policies (administrator)", "§3 terraform init/plan/apply", "§4 SSM parameters (aws ssm put-parameter)",
                  "§5 S3 upload and download, SSM session", "§9 teardown (terraform destroy) and billable checks"]
    lines = ["| Measure (this walkthrough, measured) | Count |", "| --- | --- |",
             f"| typed steps on the host (§5-§8, stand-in: S3 and SSM excluded) | {len(steps)} |",
             "| settings copied by hand | 0: one `eval \"$(flh-staging-bundle shell)\"` defines ROOT, PORT, REGION, BUCKET, PARAM_DIR, stg, bt, cc, dx |",
             f"| values typed by hand | {len(typed_values)}: the bundle's and the backup's SHA-256, on purpose |",
             "| timestamped paths typed | 0: `bt latest` resolves the newest complete backup |",
             f"| owner-only sections left (need real AWS) | {len(owner_only)} |"]
    rec.save("operator-steps.md", "\n".join(lines) + "\n\nOwner-only:\n" + "\n".join(f"- {o}" for o in owner_only) +
             "\n\nTyped steps:\n" + "\n".join(f"- {s['section']}: `{s['command'][:110]}` -> exit {s['exit']} ({s['seconds']} s)" for s in steps) + "\n")
    with open(os.path.join(WORK, "steps.json"), "w") as fh:
        json.dump(steps, fh, indent=1)
    rec.note("COUNT", f"{len(steps)} typed steps, {len(typed_values)} with a typed SHA-256, {len(owner_only)} owner-only sections")
finally:
    sys.exit(L.finish(rec, hosts, fp_before))
