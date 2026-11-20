#!/usr/bin/env python3
"""End-to-end synthetic migration rehearsal (item 094): one candidate through every local gate.

  e2e_rehearsal.py CANDIDATE.tar CANDIDATE_SHA ROLLBACK.tar ROLLBACK_SHA SOURCE_DIR FIXTURE_DIR WORK_DIR

  1 release report: collect for local-rehearsal with the candidate, the rollback bundle and the
    candidate's source tree -> READY; the HTML dashboard and the attestation
  2 deployment controls: plan, target identity, install, a readiness failure with diagnostics,
    cleanup (deploy_controls_rehearsal.py, rollback bundle -> candidate)
  3 cutover and rollback: an aborted cutover, then one rolled back after AWS writes
    (aborted_cutover_rehearsal.py, candidate)
  4 recovery: backup, failed prepares, restore, receipt, restart at two sizes (recovery_rehearsal.py)
  5 first run from a fresh fixture, as typed (first_run.py)
Each part keeps its own evidence under WORK_DIR; the summary lists every part's result. Exit 0 only
when every part passed. Synthetic data and stand-ins only; no AWS, no network.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.realpath(os.path.join(HERE, "..", "..", "..", "..", ".."))
CAND, CSHA, RB, RSHA, SRC, FIX, WORK = sys.argv[1:8]
if os.path.exists(WORK):
    sys.exit(f"refused: {WORK} exists")
os.makedirs(WORK)
parts = []


def part(name, cmd, ok_when):
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    secs = time.time() - t0
    with open(os.path.join(WORK, f"{name}.log"), "w") as fh:
        fh.write(f"$ {' '.join(cmd)}\nexit {r.returncode} ({secs:.0f} s)\n{r.stdout}{r.stderr}")
    ok = ok_when(r)
    last = next((l for l in reversed(r.stdout.splitlines()) if l.strip()), "")
    parts.append({"part": name, "ok": ok, "exit": r.returncode, "seconds": round(secs), "last": last[:160]})
    print(f"{'PASS' if ok else 'FAIL'} {name:<22} exit {r.returncode} {secs:6.0f} s  {last[:110]}", flush=True)
    return r


py = [sys.executable, "-I", "-B"]
rep = os.path.join(WORK, "report")
part("1-release-report", py + [os.path.join(REPO, "scripts", "release", "release_report.py"), "collect", "--candidate", CAND,
                              "--candidate-sha256", CSHA, "--rollback", RB, "--rollback-sha256", RSHA, "--source", SRC,
                              "--target", "local-rehearsal", "--out", rep],
     lambda r: r.returncode == 0 and r.stdout.startswith("READY for local-rehearsal"))
part("1b-dashboard", py + [os.path.join(REPO, "scripts", "release", "release_report.py"), "html",
                          os.path.join(rep, "report.json"), "--out", os.path.join(rep, "dashboard.html")],
     lambda r: r.returncode == 0)
att = part("1c-attestation", py + [os.path.join(REPO, "scripts", "release", "release_report.py"), "attest",
                                   os.path.join(rep, "report.json"), "--source", SRC], lambda r: r.returncode == 0)
with open(os.path.join(rep, "attestation.json"), "w") as fh:
    fh.write(att.stdout)
R = os.path.join(HERE)
part("2-deploy-controls", py + [os.path.join(R, "deploy_controls_rehearsal.py"), RB, RSHA, CAND, CSHA, FIX,
                               os.path.join(WORK, "deploy-controls")], lambda r: "PASSED (0 failed)" in r.stdout)
part("3-cutover", py + [os.path.join(R, "aborted_cutover_rehearsal.py"), CAND, CSHA, FIX, os.path.join(WORK, "cutover")],
     lambda r: "PASSED (0 failed)" in r.stdout)
part("4-recovery", py + [os.path.join(R, "recovery_rehearsal.py"), CAND, CSHA, FIX, os.path.join(WORK, "recovery"),
                        "--large-rows", "200000"], lambda r: "PASSED (0 failed)" in r.stdout)
part("5-first-run", py + [os.path.join(R, "first_run.py"), CAND, CSHA, os.path.join(WORK, "first-run")],
     lambda r: "PASSED (0 failed)" in r.stdout)
with open(os.path.join(WORK, "summary.json"), "w") as fh:
    json.dump({"format": "flh-e2e-rehearsal/v1", "candidate": os.path.basename(CAND), "rollback": os.path.basename(RB),
               "parts": parts, "passed": all(p["ok"] for p in parts)}, fh, indent=1)
print(f"E2E {'PASSED' if all(p['ok'] for p in parts) else 'FAILED'}: {sum(p['ok'] for p in parts)}/{len(parts)} parts, "
      f"{sum(p['seconds'] for p in parts)} s")
sys.exit(0 if all(p["ok"] for p in parts) else 1)
