#!/usr/bin/env python3
"""FLH-079 controlled failure probe for run.py (local and CI).

    python3 -B scripts/validation/flh079/failure_probe.py --work /abs/new/dir [--port 18992] [--npm-cache DIR]

Runs run.py twice, each in its own new directory under WORK, without changing
any production source:

  assertion  run.py --probe assertion-failure: once the demo server is up, the
             harness asserts a deliberately wrong expectation (that the private
             /demo.db is served; the boundary correctly answers 404). The probe
             PASSES only if run.py exits 1, reports overall FAIL with exactly that
             one failed check, and left no server process and a free port.
  interrupt  run.py --probe interrupt-hold: once the server is up, this script
             sends SIGTERM to the run.py process it started itself. The probe
             PASSES only if run.py exits 143, records the interruption, and the
             server it had started is gone and the port is free.

Writes WORK/probe-summary.json (schema flh079_failure_probe_v1). Exit 0 only if
both probes behaved as described; a probe that "passes" here demonstrates that
run.py FAILS and cleans up correctly.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as harness  # noqa: E402  (same directory; pure helpers only)

SCHEMA = "flh079_failure_probe_v1"


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def leftover(run_dir):
    """Processes whose command line is this run's server (via the shared proc_guard)."""
    r = subprocess.run([sys.executable, "-B", harness.PROC_GUARD, "scan", run_dir],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip()


def load_summary(work):
    try:
        return json.load(open(os.path.join(work, "diagnostics", "summary.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None


def base_cmd(work, port, npm_cache, probe):
    cmd = [sys.executable, "-B", os.path.join(HERE, "run.py"), "--work", work, "--port", str(port), "--probe", probe]
    return cmd + (["--npm-cache", npm_cache] if npm_cache else [])


def assertion_probe(work, port, npm_cache, log):
    with open(log, "wb") as out:
        rc = subprocess.run(base_cmd(work, port, npm_cache, "assertion-failure"), stdout=out,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=900).returncode
    s = load_summary(work) or {}
    failed = [c["id"] for c in s.get("failed_checks", [])]
    serve = next((st for st in s.get("stages", []) if st["name"] == "serve-http"), {})
    facts = {
        "exit_code": rc,
        "overall": s.get("overall"),
        "failed_checks": failed,
        "serve_stage": serve.get("status"),
        "cleanup_reported_ok": s.get("cleanup", {}).get("server_stopped_and_port_free"),
        "server_was_started": any(c["id"] == "process.server_1_ready" and c["status"] == "PASS"
                                  for c in s.get("checks", [])),
        "leftover_processes": leftover(os.path.join(work, "run")),
        "port_in_use_after": harness.port_in_use(port),
    }
    ok = (rc == 1 and facts["overall"] == "FAIL" and failed == ["probe.deliberate_wrong_expectation"]
          and facts["serve_stage"] == "FAIL" and facts["cleanup_reported_ok"] is True and facts["server_was_started"]
          and not facts["leftover_processes"] and not facts["port_in_use_after"])
    return ok, facts


def interrupt_probe(work, port, npm_cache, log):
    state_file = os.path.join(work, "diagnostics", "state.json")
    with open(log, "wb") as out:
        proc = subprocess.Popen(base_cmd(work, port, npm_cache, "interrupt-hold"), stdout=out,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    facts = {"reached_hold": False}
    server_pid = None
    try:
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                st = json.load(open(state_file))
            except (OSError, ValueError):
                st = {}
            if st.get("stage") == "probe-hold":
                server_pid = st.get("server_pid")
                facts["reached_hold"] = True
                break
            time.sleep(0.2)
        facts["server_listening_before_signal"] = harness.port_in_use(port)
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)  # our own direct child only
        rc = proc.wait(timeout=90)
    except subprocess.TimeoutExpired:
        proc.kill()  # our own child; its server is then cleaned below and the probe FAILS
        rc = proc.wait()
        facts["harness_killed_after_timeout"] = True
    s = load_summary(work) or {}
    run_dir = os.path.join(work, "run")
    facts.update({
        "exit_code": rc,
        "overall": s.get("overall"),
        "interrupted_by_signal": s.get("interrupted_by_signal"),
        "server_pid": server_pid,
        "server_alive_after": bool(server_pid) and pid_alive(server_pid),
        "cleanup_reported_ok": s.get("cleanup", {}).get("server_stopped_and_port_free"),
        "leftover_processes": leftover(run_dir),
        "port_in_use_after": harness.port_in_use(port),
    })
    if facts["leftover_processes"] and os.path.isdir(run_dir):  # last-resort verified stop
        subprocess.run([sys.executable, "-B", harness.PROC_GUARD, "stop", run_dir], timeout=30)
    ok = (facts["reached_hold"] and facts["server_listening_before_signal"] and rc == 128 + signal.SIGTERM
          and facts["overall"] == "FAIL" and facts["interrupted_by_signal"] == signal.SIGTERM
          and facts["cleanup_reported_ok"] is True and not facts["server_alive_after"]
          and not facts["leftover_processes"] and not facts["port_in_use_after"])
    return ok, facts


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--work", required=True)
    p.add_argument("--port", type=int, default=18992)
    p.add_argument("--npm-cache")
    a = p.parse_args(sys.argv[1:] if argv is None else argv)
    why = harness.refuse_work(a.work)
    if why:
        print(f"refused: {why}", file=sys.stderr)
        return 2
    if harness.port_in_use(a.port):
        print(f"refused: port {a.port} is in use", file=sys.stderr)
        return 2
    os.makedirs(a.work)
    results = []
    for name, fn in (("assertion", assertion_probe), ("interrupt", interrupt_probe)):
        work = os.path.join(a.work, name)
        t0 = time.monotonic()
        try:
            ok, facts = fn(work, a.port, a.npm_cache, os.path.join(a.work, f"{name}.log"))
        except Exception as e:  # a crashed probe is a FAIL
            ok, facts = False, {"error": f"{type(e).__name__}: {e}"}
        results.append({"probe": name, "status": "PASS" if ok else "FAIL",
                        "duration_s": round(time.monotonic() - t0, 1), "facts": facts})
        print(f"{'PASS' if ok else 'FAIL'} probe {name}: {json.dumps(facts)}", flush=True)
    overall = "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL"
    with open(os.path.join(a.work, "probe-summary.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": SCHEMA, "overall": overall, "probes": results,
                   "meaning": "PASS means run.py failed (nonzero exit) and cleaned up as required"}, f, indent=2)
        f.write("\n")
    print(f"FAILURE PROBE {overall}; summary {os.path.join(a.work, 'probe-summary.json')}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
