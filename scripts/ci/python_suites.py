#!/usr/bin/env python3
"""Standard-library Python tool suites: the CI job's commands and their local entry point.

  python3 -B scripts/ci/python_suites.py                 # every suite, from any directory
  python3 -B scripts/ci/python_suites.py --suite release  # one suite (repeatable)
  python3 -B scripts/ci/python_suites.py --list
  python3 -B scripts/ci/python_suites.py --python /path/to/python3 --summary FILE.md --json FILE.json
  python3 -B scripts/ci/python_suites.py --hermetic      # no AWS settings, no home, trapped aws/terraform/docker
  python3 -B scripts/ci/python_suites.py --fail-on-skip release --require speaking

Each suite runs its normal command in its normal working directory (the ones
the suite's README documents). Before each command the runner prints a clear
label (a GitHub Actions log group in CI), the working directory and the exact
command. It checks first that the interpreter and every path the suite reads
exist, and fails with the missing path otherwise. Counts (tests run, skipped,
expected failures, failures, errors) are parsed from the suite's own unittest
output, never hard-coded. Every suite runs even after a failure, then the
runner prints a summary table and exits 1 if any suite failed or its output
had no unittest summary, 2 on a usage or setup problem.

Optional suites run only when their entry file exists, and are reported as
NOT-PRESENT otherwise: this is never counted as a pass, and `--require LABEL`
turns it into a failure. `speaking` is the standard-library offline run of
tools/speaking (scripts/run_tests.py, from the extraction lane): its dependency
tests skip with their reason here. The strict run with NumPy, PyAV, torch and
the weights-free fixture is the separate Speaking job. Test-level skips and
expected failures are counted apart from a suite that did not run;
`--fail-on-skip LABEL` makes any skip in that suite a failure.

Timings and resources per suite are structured: start time, wall seconds,
child CPU seconds and peak RSS (from wait4), next to the parsed counts.
`--hermetic` runs every suite with AWS_* removed, AWS config and credentials
files pointed at nothing, IMDS disabled, HOME set to an empty temporary
directory, the Hugging Face libraries offline, and `aws`, `terraform`,
`docker` and `session-manager-plugin` replaced by traps that record the call
and exit 97: any call fails the run.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# label: (working directory, argv after the interpreter, paths that must exist), relative to REPO
SUITES = {
    "ci-runner": ("", ["-B", "-m", "unittest", "discover", "-s", "scripts/ci", "-p", "test_python_suites.py"],
                  ["scripts/ci/test_python_suites.py", ".github/workflows/ci.yml"]),
    "release": ("", ["-B", "-m", "unittest", "discover", "-s", "scripts/release", "-p", "test_*.py"],
                ["scripts/release/test_release_tools.py"]),
    "private-staging": ("", ["-B", "-m", "unittest", "discover", "-s", "deploy/aws/private-staging/staging/tests",
                             "-p", "test_*.py"],
                        ["deploy/aws/private-staging/staging/tests/test_staging_tools.py",
                         "deploy/aws/private-staging/staging/tests/fixtures/plan-create-safe.json",
                         "deploy/aws/private-staging/staging/expected_resources.json",
                         "deploy/aws/private-staging/staging/iam/out/flh-stg-deploy-ec2-policy.json",
                         "deploy/aws/iam/flh-experiment-demo-deploy-ec2-policy.json",
                         "deploy/aws/terraform/.terraform.lock.hcl"]),
    "extraction": ("tools/extraction", ["-B", "-m", "unittest", "discover", "-s", "tests", "-t", "tests"],
                   ["tools/extraction/tests", "tools/extraction/fixtures"]),
    "workbooks": ("tools/workbooks", ["-B", "-m", "unittest", "discover", "-s", "tests"],
                  ["tools/workbooks/tests/test_workbooks.py", "tools/workbooks/tests/fixtures",
                   "internal/listening/pack/listening_scripts_v1.json"]),
}

# Optional suites: label -> the entry file whose presence enables the suite.
OPTIONAL = {"speaking": "tools/speaking/scripts/run_tests.py"}
SUITES["speaking"] = ("tools/speaking", ["-B", "scripts/run_tests.py"],
                      ["tools/speaking/scripts/run_tests.py", "tools/speaking/tests", "tools/speaking/flh_speaking/pins.py"])
SUITE_ENV = {"speaking": {"PYTHONPATH": "."}}          # relative values resolve against the suite's directory
TRAPPED = ("aws", "terraform", "docker", "session-manager-plugin")

RAN = re.compile(r"^Ran (\d+) tests? in [0-9.]+s$", re.M)
RESULT = re.compile(r"^(OK|FAILED)(?: \((.*)\))?$", re.M)


def counts(output):
    """Parse unittest's own summary lines; None when there is no summary."""
    ran = RAN.findall(output)
    res = RESULT.findall(output)
    if not ran or not res:
        return None
    c = {"ran": int(ran[-1]), "unittest": res[-1][0], "skipped": 0, "expected_failures": 0,
         "unexpected_successes": 0, "failures": 0, "errors": 0}
    for part in (res[-1][1] or "").split(","):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            c[k.strip().replace(" ", "_")] = int(v)
    return c


def in_ci():
    return os.environ.get("GITHUB_ACTIONS") == "true"


def run_suite(label, python, hermetic=None, fail_on_skip=False):
    cwd_rel, args, needs = SUITES[label]
    cwd = os.path.join(REPO, cwd_rel)
    cmd = [python] + args
    started = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = {"label": label, "started_at": started, "seconds": 0.0, "cpu_seconds": None, "max_rss_mb": None}
    gate = OPTIONAL.get(label)
    if gate and not os.path.exists(os.path.join(REPO, gate)):
        msg = f"{label}: not present in this tree ({gate} is absent); not run, not counted as a pass"
        print(f"::notice::{msg}" if in_ci() else f"\n===== {label} =====\nNOT-PRESENT {msg}", flush=True)
        return dict(base, status="NOT-PRESENT", exit=None, detail=msg)
    print(f"::group::{label}" if in_ci() else f"\n===== {label} =====", flush=True)
    print(f"suite:   {label}\ncwd:     {cwd_rel or '.'} ({cwd})\ncommand: {' '.join(cmd)}", flush=True)
    missing = [p for p in needs + [cwd_rel or "."] if not os.path.exists(os.path.join(REPO, p))]
    if missing:
        msg = f"{label}: missing path(s) the suite needs: " + ", ".join(os.path.join(REPO, p) for p in missing)
        print(f"::error::{msg}" if in_ci() else f"ERROR {msg}", flush=True)
        if in_ci():
            print("::endgroup::", flush=True)
        return dict(base, status="MISSING", exit=None, detail=msg)
    env = dict(hermetic if hermetic is not None else os.environ, PYTHONDONTWRITEBYTECODE="1")
    for k, v in SUITE_ENV.get(label, {}).items():
        env[k] = os.path.normpath(os.path.join(cwd, v)) if v.startswith(".") else v
    t0 = time.time()
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output = p.stdout.read()
    p.stdout.close()
    _, status_word, ru = os.wait4(p.pid, 0)
    p.returncode = os.waitstatus_to_exitcode(status_word)
    secs = time.time() - t0
    sys.stdout.write(output)
    c = counts(output)
    status = "PASS" if p.returncode == 0 and c and c["unittest"] == "OK" else "FAIL"
    detail = "" if c else "no unittest summary in the output"
    if status == "PASS" and fail_on_skip and c.get("skipped"):
        status, detail = "FAIL", f"{c['skipped']} test(s) skipped in a suite that must run every test (--fail-on-skip)"
    if in_ci():
        print("::endgroup::", flush=True)
        if status == "FAIL":
            print(f"::error::{label} failed (exit {p.returncode}){': ' + detail if detail else ''}", flush=True)
    rss_kb = ru.ru_maxrss if sys.platform != "darwin" else ru.ru_maxrss // 1024
    return dict(base, status=status, exit=p.returncode, seconds=secs, detail=detail,
                cpu_seconds=round(ru.ru_utime + ru.ru_stime, 2), max_rss_mb=round(rss_kb / 1024, 1), **(c or {}))


def hermetic_env(trap_dir, home):
    """The environment of a --hermetic run (see the module docstring)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_") and k not in ("HOME", "PATH")}
    env.update(HOME=home, AWS_CONFIG_FILE=os.devnull, AWS_SHARED_CREDENTIALS_FILE=os.devnull,
               AWS_EC2_METADATA_DISABLED="true", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               PATH=trap_dir + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"))
    log = os.path.join(trap_dir, "calls.log")
    for t in TRAPPED:
        with open(os.path.join(trap_dir, t), "w") as fh:
            fh.write(f'#!/bin/sh\necho "{t} $*" >> "{log}"\necho "{t}: trapped by python_suites.py --hermetic" >&2\nexit 97\n')
        os.chmod(os.path.join(trap_dir, t), 0o755)
    return env, log


def table(results):
    head = ("| Suite | Result | Exit | Ran | Skipped | Expected failures | Failures | Errors | Seconds | CPU s | Peak RSS MB |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|")
    rows = [f"| {r['label']} | {r['status']} | {r['exit']} | {r.get('ran', '-')} | {r.get('skipped', '-')} | "
            f"{r.get('expected_failures', '-')} | {r.get('failures', '-')} | {r.get('errors', '-')} | {r['seconds']:.1f} | "
            f"{r['cpu_seconds'] if r.get('cpu_seconds') is not None else '-'} | "
            f"{r['max_rss_mb'] if r.get('max_rss_mb') is not None else '-'} |"
            for r in results]
    notes = []
    skipped = [r for r in results if r.get("skipped")]
    xfail = [r for r in results if r.get("expected_failures")]
    absent = [r for r in results if r["status"] == "NOT-PRESENT"]
    if skipped:
        notes.append("Skipped tests (ran, counted apart): " + ", ".join(f"{r['label']} {r['skipped']}" for r in skipped))
    if xfail:
        notes.append("Expected failures (known, not passes): " + ", ".join(f"{r['label']} {r['expected_failures']}" for r in xfail))
    if absent:
        notes.append("Suites not run (NOT-PRESENT, not passes): " + ", ".join(r["label"] for r in absent))
    return "\n".join([head] + rows + ([""] + notes if notes else []))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", action="append", choices=sorted(SUITES), help="run only this suite (repeatable)")
    ap.add_argument("--python", default=sys.executable, help="interpreter for the suites (default: this one)")
    ap.add_argument("--summary", help="append the Markdown summary table to this file (CI: $GITHUB_STEP_SUMMARY)")
    ap.add_argument("--json", dest="json_out", help="write the per-suite results (counts parsed from output) as JSON")
    ap.add_argument("--fail-on-skip", action="append", default=[], choices=sorted(SUITES),
                    help="any skipped test in this suite fails it (repeatable)")
    ap.add_argument("--require", action="append", default=[], choices=sorted(OPTIONAL),
                    help="an optional suite that must be present (repeatable)")
    ap.add_argument("--hermetic", action="store_true", help="no AWS settings or home; aws/terraform/docker trapped")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for k, (cwd, args, _) in SUITES.items():
            print(f"{k}\tcwd={cwd or '.'}\tpython3 {' '.join(args)}" + (f"\toptional: needs {OPTIONAL[k]}" if k in OPTIONAL else ""))
        return 0
    py = a.python if os.path.sep in a.python else (shutil.which(a.python) or a.python)
    if not (os.path.isfile(py) and os.access(py, os.X_OK)):
        print(f"ERROR the interpreter does not exist or is not executable: {os.path.abspath(py)}", file=sys.stderr)
        return 2
    work = tempfile.mkdtemp(prefix="flh-suites-") if a.hermetic else None
    env, log = (None, None)
    if work:
        os.makedirs(os.path.join(work, "trap"))
        os.makedirs(os.path.join(work, "home"))
        env, log = hermetic_env(os.path.join(work, "trap"), os.path.join(work, "home"))
    try:
        results = [run_suite(s, py, env, s in a.fail_on_skip) for s in (a.suite or list(SUITES))]
        calls = []
        if log and os.path.exists(log):
            with open(log) as fh:
                calls = [l.strip() for l in fh if l.strip()]
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
    for r in results:
        if r["status"] == "NOT-PRESENT" and r["label"] in a.require:
            r["status"], r["detail"] = "FAIL", r["detail"] + " (--require)"
    summary = table(results)
    if a.hermetic:
        summary += f"\n\nHermetic run: no AWS settings, empty HOME, offline; trapped calls: {len(calls)}" + \
                   (" (" + "; ".join(sorted(set(c.split()[0] for c in calls))) + ")" if calls else "")
    print("\n" + summary)
    if a.summary:
        with open(a.summary, "a") as fh:
            fh.write("### Python tool suites\n\n" + summary + "\n")
    if a.json_out:
        with open(a.json_out, "w") as fh:
            json.dump({"format": "flh-python-suites/v1", "interpreter": py, "hermetic": a.hermetic,
                       "trapped_calls": calls if a.hermetic else None, "suites": results}, fh, indent=1, sort_keys=True)
            fh.write("\n")
    failed = [r["label"] for r in results if r["status"] not in ("PASS", "NOT-PRESENT")]
    if calls:
        failed.append(f"hermetic ({len(calls)} trapped call(s))")
    absent = [r["label"] for r in results if r["status"] == "NOT-PRESENT"]
    print(f"\n{'FAILED: ' + ', '.join(failed) if failed else 'ALL PASSED'} ({len(results) - len(absent)} suite(s) run"
          + (f", not present: {', '.join(absent)}" if absent else "") + f", interpreter {py})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
