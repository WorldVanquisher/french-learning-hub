#!/usr/bin/env python3
"""FLH-080 H1 regression: accept.sh must remove the /tmp/flh077-unit-* it creates.

    python3 -B scripts/validation/flh080/accept_tmp_regression.py --src /abs/source/tree \
        --work "/abs/new/work dir" [--accept PATH] [--modes success,failure,interrupt]
        [--port-base 19770] [--revision LABEL]

--src is a prepared source tree, outside the checkout, with web/node_modules
installed. accept.sh (default: --src's scripts/validation/flh077/accept.sh) runs
from there, exactly as FLH-077/078 ran it. Every mode is one complete accept.sh
run in WORK/<mode>. A `systemd-analyze` shim placed first in PATH records the
temporary directory accept.sh handed it (the dirname of the unit file), then
acts per mode:

  success    passes through to the real systemd-analyze
  failure    exits 1 (a failing check); accept.sh must still finish and exit 1
  interrupt  sends SIGTERM to its parent accept.sh, a catchable interruption
             while the directory exists, and exits 1

PASS for a mode requires:
- the shim was reached;
- the recorded directory matches /tmp/flh077-unit-XXXXXX and no longer exists;
- no new /tmp/flh077-unit-* exists;
- every directory of that pattern that existed before the run still exists,
  untouched (same inode and mtime);
- the expected exit code: success 0 (or 1 only if a non-H1 check failed, which
  is reported), failure 1, interrupt 143.

This test never removes a /tmp directory. A directory the accept.sh under test
leaks is reported and left in place for the human owner.

Results: WORK/results.tsv and WORK/summary.json. Exit 0 only if no check FAILED.
"""

import argparse
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys

PATTERN = re.compile(r"^/tmp/flh077-unit-[A-Za-z0-9]{6}$")
SHIM = {
    "success": 'exec "{real}" "$@"',
    "failure": "exit 1",
    "interrupt": 'kill -TERM "$PPID"; exit 1',
}
EXPECTED_RC = {"failure": 1, "interrupt": 143}


def snapshot():
    out = {}
    for d in glob.glob("/tmp/flh077-unit-*"):
        try:
            st = os.lstat(d)
            out[d] = (st.st_ino, st.st_mtime_ns)
        except OSError:
            pass
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--src", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--accept")
    p.add_argument("--modes", default="success,failure,interrupt")
    p.add_argument("--port-base", type=int, default=19770)
    p.add_argument("--revision", default=os.environ.get("FLH077_REVISION", "unlabelled-working-tree"))
    a = p.parse_args()
    accept = os.path.abspath(a.accept or os.path.join(a.src, "scripts", "validation", "flh077", "accept.sh"))
    real = shutil.which("systemd-analyze")
    if not os.path.isabs(a.work) or os.path.lexists(a.work):
        print("refused: --work must be a new absolute path", file=sys.stderr)
        return 2
    if not os.path.isfile(os.path.join(a.src, "scripts", "demo", "flh076", "package.sh")):
        print("refused: --src is not a source tree", file=sys.stderr)
        return 2
    os.makedirs(a.work)
    results = []

    def rec(status, mode, name, detail=""):
        results.append({"status": status, "mode": mode, "check": name, "detail": str(detail)[:300]})
        line = f"{status}\t{mode}\t{name}\t{detail}"
        print(line, flush=True)
        with open(os.path.join(a.work, "results.tsv"), "a") as f:
            f.write(line + "\n")

    if real is None:
        rec("NOT RUN", "all", "systemd-analyze not installed: accept.sh never creates the directory")
        modes = []
    else:
        modes = [m for m in a.modes.split(",") if m]
    for i, mode in enumerate(modes):
        shim_dir = os.path.join(a.work, f"shim-{mode}")
        os.makedirs(shim_dir)
        marker = os.path.join(a.work, f"unitdir-{mode}.txt")
        with open(os.path.join(shim_dir, "systemd-analyze"), "w") as f:
            f.write("#!/bin/sh\n"
                    f"for x in \"$@\"; do case \"$x\" in */flh-public-demo-test.service) dirname \"$x\" >> '{marker}' ;; esac; done\n"
                    + SHIM[mode].format(real=real) + "\n")
        os.chmod(os.path.join(shim_dir, "systemd-analyze"), 0o755)
        before = snapshot()
        run = os.path.join(a.work, mode)
        env = {**os.environ, "PATH": shim_dir + os.pathsep + os.environ["PATH"], "FLH077_REVISION": a.revision}
        with open(os.path.join(a.work, f"accept-{mode}.log"), "wb") as log:
            proc = subprocess.Popen(["bash", accept, run, str(a.port_base + 20 * i)], cwd=a.src, env=env,
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                rc = proc.wait(timeout=1800)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)  # accept.sh's own session
                rc = proc.wait()
                rec("FAIL", mode, "accept.sh finished within 30 min")
        after = snapshot()
        recorded = open(marker).read().split() if os.path.exists(marker) else []
        if not recorded:
            rec("FAIL", mode, "systemd-analyze step reached", f"accept.sh exit {rc}; see accept-{mode}.log")
            continue
        d = recorded[0]
        rec("PASS" if PATTERN.match(d) else "FAIL", mode, "recorded directory has the mktemp pattern", d)
        rec("PASS" if not os.path.lexists(d) else "FAIL", mode, "this run's directory removed", d)
        new = sorted(set(after) - set(before))
        rec("PASS" if not new else "FAIL", mode, "no new /tmp/flh077-unit-* left", new)
        changed = sorted(k for k, v in before.items() if after.get(k) != v)
        rec("PASS" if not changed else "FAIL", mode, f"{len(before)} pre-existing directories untouched", changed)
        if mode == "success":
            summ = open(os.path.join(run, "summary.txt")).read().split() if os.path.exists(os.path.join(run, "summary.txt")) else []
            rec("PASS" if rc == 0 else "FAIL", mode, "accept.sh exit 0", f"exit {rc}; {' '.join(summ)}")
        else:
            rec("PASS" if rc == EXPECTED_RC[mode] else "FAIL", mode, f"accept.sh exit {EXPECTED_RC[mode]}", f"exit {rc}")
    counts = {k: sum(r["status"] == k for r in results) for k in ("PASS", "FAIL", "NOT RUN")}
    with open(os.path.join(a.work, "summary.json"), "w") as f:
        json.dump({"schema": "flh080_accept_tmp_regression_v1", "accept_under_test": accept,
                   "accept_sha256": subprocess.run(["sha256sum", accept], capture_output=True, text=True).stdout.split()[0],
                   "revision_label": a.revision, "counts": counts, "results": results}, f, indent=2)
        f.write("\n")
    print(json.dumps(counts))
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
