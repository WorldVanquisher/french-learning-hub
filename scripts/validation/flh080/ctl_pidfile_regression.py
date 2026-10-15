#!/usr/bin/env python3
"""FLH-080 D3 regression: a failed `ctl.sh start` must not leave a server running.

    python3 -B scripts/validation/flh080/ctl_pidfile_regression.py --work "/abs/new/work dir" \
        [--ctl PATH] [--port-base 19880]

Run from the repository root on Linux. It builds the host server and the
FLH-073 `prepare` tool, then lays out a minimal package around the ctl.sh under
test (default: scripts/demo/flh076/deploy/ctl.sh) in a directory whose path
contains spaces. That package holds the real mechanical artifact, a tiny web
directory and a `bin/server` wrapper. The wrapper appends one line to a launch
log and then execs either the real server or a never-ready stand-in that keeps
the same arguments. Cases:

  prelaunch-dir      The pid path is a directory (the FLH-078 reproducer).
                     start must fail with nothing launched.
  prelaunch-ro       The runtime directory is not writable. start must fail with
                     nothing launched. This is NOT RUN as root.
  postlaunch-mv-fail A PATH shim makes `mv` fail (as on ENOSPC) only for ctl.sh's
                     own commands. The launched server must be stopped.
  postlaunch-mv-noop A PATH shim makes `mv` exit 0 without renaming, so the
                     read-back check fails. The launched server must be stopped.
  interrupt-term     SIGTERM to ctl.sh while it waits for readiness. The launched
                     process must be stopped and the pid file removed.
  interrupt-int      The same with SIGINT.
  control-ok         A normal start, then stop. It must still work.

After every case it checks:
- no process runs whose argv holds `-public-demo-artifact <this run's
  package>/artifact`;
- the port is closed;
- no pid file and no `.flh-public-demo.pid.*` temporary file is left.

Run against an older ctl.sh with `--ctl`, it reports which checks that
version fails. Any server that version leaks is then stopped by this test.
The test identifies such a server by the exact argv pair naming the unique
package directory this run created, and by a kernel start time after this
run began. It never selects a process by port or name.

Results go to WORK/results.tsv and WORK/summary.json. Exit 0 only if no check
FAILED.
"""

import argparse
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time

REPO = os.getcwd()
CTL_DEFAULT = os.path.join(REPO, "scripts", "demo", "flh076", "deploy", "ctl.sh")
CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def boot_time():
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("btime "):
                return int(line.split()[1])
    raise RuntimeError("no btime in /proc/stat")


def proc_start_epoch(pid):
    with open(f"/proc/{pid}/stat") as f:
        ticks = int(f.read().rsplit(")", 1)[1].split()[19])
    return boot_time() + ticks / CLK_TCK


def proc_argv(pid):
    with open(f"/proc/{pid}/cmdline", "rb") as f:
        return [a.decode(errors="replace") for a in f.read().split(b"\0") if a]


def port_open(port):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


class Regression:
    def __init__(self, a):
        self.work, self.ctl_src, self.pb = a.work, a.ctl, a.port_base
        self.root = os.path.join(self.work, "package root with spaces")
        self.artifact = os.path.join(self.root, "artifact")
        self.ctl = os.path.join(self.root, "deploy", "ctl.sh")
        self.launches = os.path.join(self.work, "launches.log")
        self.mode_file = os.path.join(self.work, "server-mode")
        self.results, self.leaks_stopped = [], []
        self.t0 = time.time()

    def rec(self, status, case, name, detail=""):
        self.results.append({"status": status, "case": case, "check": name, "detail": str(detail)[:300]})
        line = f"{status}\t{case}\t{name}\t{detail}"
        print(line, flush=True)
        with open(os.path.join(self.work, "results.tsv"), "a") as f:
            f.write(line + "\n")

    def check(self, case, name, ok, detail=""):
        self.rec("PASS" if ok else "FAIL", case, name, detail)

    # ---- setup -----------------------------------------------------------
    def setup(self):
        b = os.path.join(self.work, "build")
        os.makedirs(b)
        for out, pkg in (("server", "./cmd/server"), ("prepare", "./scripts/demo/flh073/prepare")):
            subprocess.run(["go", "build", "-o", os.path.join(b, out), pkg], check=True, timeout=600)
        subprocess.run([os.path.join(b, "prepare"), "build", "-out", self.artifact, "-fixtures",
                        "scripts/demo/flh073/fixtures/catalog.json"], check=True, stdout=subprocess.DEVNULL, timeout=120)
        os.makedirs(os.path.join(self.root, "deploy"))
        shutil.copy2(self.ctl_src, self.ctl)
        os.chmod(self.ctl, 0o755)
        os.makedirs(os.path.join(self.root, "web", "assets"))
        with open(os.path.join(self.root, "web", "index.html"), "w") as f:
            f.write("<!doctype html><title>t</title>\n")
        with open(os.path.join(self.root, "web", "assets", "app.js"), "w") as f:
            f.write("void 0\n")
        os.makedirs(os.path.join(self.root, "bin"))
        real = os.path.join(b, "server")
        wrapper = os.path.join(self.root, "bin", "server")
        # Records every launch; keeps the demo arguments in argv either way.
        with open(wrapper, "w") as f:
            f.write("#!/bin/sh\n"
                    f"echo \"$$ $(date +%s)\" >> '{self.launches}'\n"
                    f"if [ \"$(cat '{self.mode_file}' 2>/dev/null)\" = never-ready ]; then\n"
                    "  exec python3 -c 'import time; time.sleep(3600)' \"$@\"\n"
                    "fi\n"
                    f"exec '{real}' \"$@\"\n")
        os.chmod(wrapper, 0o755)
        self.shims = os.path.join(self.work, "shims")
        for name, body in (("mv-fail", 'echo "mv: cannot move: No space left on device" >&2; exit 1'),
                           ("mv-noop", "exit 0")):
            d = os.path.join(self.shims, name)
            os.makedirs(d)
            with open(os.path.join(d, "mv"), "w") as f:
                f.write(f"#!/bin/sh\n{body}\n")
            os.chmod(os.path.join(d, "mv"), 0o755)

    # ---- helpers ---------------------------------------------------------
    def task_servers(self):
        """PIDs whose argv holds exactly ['-public-demo-artifact', <this run's artifact>]."""
        found = []
        for p in os.listdir("/proc"):
            if not p.isdigit():
                continue
            try:
                argv = proc_argv(int(p))
            except OSError:
                continue
            for i, a in enumerate(argv[:-1]):
                if a == "-public-demo-artifact" and argv[i + 1] == self.artifact:
                    found.append(int(p))
                    break
        return found

    def stop_leaks(self, case):
        """Stops servers leaked by the ctl.sh under test: exact argv naming this run's unique
        package directory, started after this run began. Never by port or name."""
        for pid in self.task_servers():
            try:
                if proc_start_epoch(pid) + 1 < self.t0:
                    self.rec("NOTE", case, "matching process predates this run; not signalled", pid)
                    continue
                os.kill(pid, signal.SIGTERM)
            except OSError:
                continue
            for _ in range(50):
                if pid not in self.task_servers():
                    break
                time.sleep(0.1)
            self.leaks_stopped.append({"case": case, "pid": pid})
            self.rec("NOTE", case, "leaked server stopped by the test (verified argv + start time)", pid)

    def launch_count(self):
        try:
            return sum(1 for _ in open(self.launches))
        except OSError:
            return 0

    def ctl_env(self, port, shim=None, ready_timeout=30):
        path = os.environ["PATH"]
        if shim:
            path = os.path.join(self.shims, shim) + os.pathsep + path
        return {**os.environ, "PATH": path, "PORT": str(port), "ALLOW_MECHANICAL": "1",
                "SERVER_BIN": os.path.join(self.root, "bin", "server"), "READY_TIMEOUT": str(ready_timeout)}

    def ctl_run(self, action, run, env, timeout=90):
        p = subprocess.Popen([self.ctl, action, run], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=True)
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)  # ctl.sh's own session, which it was started in
            out, err = p.communicate()
            return 124, out, err
        return p.returncode, out, err

    def after(self, case, run, port, want_pidfile_absent=True):
        servers = self.task_servers()
        self.check(case, "no task server left running", not servers, f"pids {servers}" if servers else "")
        self.check(case, "port closed", not port_open(port), port)
        left = [n for n in os.listdir(run) if n.startswith(".flh-public-demo.pid.")] if os.path.isdir(run) else []
        self.check(case, "no temporary pid file left", not left, left)
        if want_pidfile_absent:
            pf = os.path.join(run, "flh-public-demo.pid")
            self.check(case, "no pid file left", not os.path.isfile(pf), open(pf).read().strip() if os.path.isfile(pf) else "")
        self.stop_leaks(case)

    def set_mode(self, mode):
        with open(self.mode_file, "w") as f:
            f.write(mode)

    # ---- cases -----------------------------------------------------------
    def case_prelaunch_dir(self):
        case, port = "prelaunch-dir", self.pb + 1
        run = os.path.join(self.work, "run dir pidpath")
        os.makedirs(os.path.join(run, "flh-public-demo.pid"))
        n0 = self.launch_count()
        rc, _, err = self.ctl_run("start", run, self.ctl_env(port))
        self.check(case, "start fails", rc == 1, f"rc {rc}: {err.strip()[:200]}")
        self.check(case, "nothing launched", self.launch_count() == n0, f"{self.launch_count() - n0} launches")
        self.after(case, run, port, want_pidfile_absent=False)

    def case_prelaunch_ro(self):
        case, port = "prelaunch-ro", self.pb + 2
        if os.geteuid() == 0:
            self.rec("NOT RUN", case, "read-only runtime directory", "running as root ignores permissions")
            return
        run = os.path.join(self.work, "run read only")
        os.makedirs(run)
        open(os.path.join(run, "flh-public-demo.log"), "w").close()
        os.chmod(run, 0o555)
        try:
            n0 = self.launch_count()
            rc, _, err = self.ctl_run("start", run, self.ctl_env(port))
            self.check(case, "start fails", rc == 1, f"rc {rc}: {err.strip()[:200]}")
            self.check(case, "nothing launched", self.launch_count() == n0, f"{self.launch_count() - n0} launches")
            self.after(case, run, port)
        finally:
            os.chmod(run, 0o755)

    def case_postlaunch(self, shim):
        case, port = f"postlaunch-{shim}", self.pb + (3 if shim == "mv-fail" else 4)
        run = os.path.join(self.work, f"run {shim}")
        n0 = self.launch_count()
        rc, _, err = self.ctl_run("start", run, self.ctl_env(port, shim=shim))
        self.check(case, "server was launched (post-launch failure path exercised)", self.launch_count() == n0 + 1,
                   f"{self.launch_count() - n0} launches")
        self.check(case, "start fails", rc == 1, f"rc {rc}: {err.strip()[:200]}")
        self.check(case, "failure names the pid bookkeeping", "could not record pid" in err, err.strip()[:200])
        self.after(case, run, port)

    def case_interrupt(self, sig):
        name = {signal.SIGTERM: "term", signal.SIGINT: "int"}[sig]
        case, port = f"interrupt-{name}", self.pb + (5 if sig == signal.SIGTERM else 6)
        run = os.path.join(self.work, f"run interrupt {name}")
        self.set_mode("never-ready")
        try:
            n0 = self.launch_count()
            p = subprocess.Popen([self.ctl, "start", run], env=self.ctl_env(port), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, start_new_session=True)
            deadline = time.time() + 20
            while time.time() < deadline and not (self.launch_count() > n0 and self.task_servers()
                                                  and os.path.isfile(os.path.join(run, "flh-public-demo.pid"))):
                time.sleep(0.1)
            launched = self.launch_count() > n0 and bool(self.task_servers())
            self.check(case, "launched process running before the signal", launched)
            time.sleep(0.5)
            p.send_signal(sig)  # only to ctl.sh, our own direct child
            try:
                _, err = p.communicate(timeout=30)
                rc = p.returncode
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.communicate()
                rc = 124
            self.check(case, "start exits nonzero", rc != 0, f"rc {rc}")
            self.after(case, run, port)
        finally:
            self.set_mode("real")

    def case_control_ok(self):
        case, port = "control-ok", self.pb + 7
        run = os.path.join(self.work, "run control ok")
        rc, out, err = self.ctl_run("start", run, self.ctl_env(port))
        self.check(case, "start succeeds", rc == 0, (out + err).strip()[:200])
        pid = open(os.path.join(run, "flh-public-demo.pid")).read().strip() if rc == 0 else ""
        self.check(case, "pid file names the running server", pid.isdigit() and int(pid) in self.task_servers(), pid)
        rc2, out2, _ = self.ctl_run("start", run, self.ctl_env(port))
        self.check(case, "repeated start keeps the pid", rc2 == 0 and "already running" in out2, out2.strip())
        rc3, _, _ = self.ctl_run("stop", run, self.ctl_env(port))
        self.check(case, "stop", rc3 == 0, f"rc {rc3}")
        self.after(case, run, port)

    def execute(self):
        self.set_mode("real")
        self.case_prelaunch_dir()
        self.case_prelaunch_ro()
        self.case_postlaunch("mv-fail")
        self.case_postlaunch("mv-noop")
        self.case_interrupt(signal.SIGTERM)
        self.case_interrupt(signal.SIGINT)
        self.case_control_ok()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--work", required=True)
    p.add_argument("--ctl", default=CTL_DEFAULT)
    p.add_argument("--port-base", type=int, default=19880)
    a = p.parse_args()
    if not sys.platform.startswith("linux"):
        print("BLOCKED: this regression uses /proc (Linux only)", file=sys.stderr)
        return 3
    if not os.path.isfile(CTL_DEFAULT):
        print("run from the repository root", file=sys.stderr)
        return 2
    a.ctl = os.path.abspath(a.ctl)
    real = os.path.realpath(a.work)
    if not os.path.isabs(a.work) or real == REPO or real.startswith(REPO + os.sep) or os.path.lexists(a.work):
        print("refused: --work must be a new absolute path outside the repository", file=sys.stderr)
        return 2
    busy = [a.port_base + i for i in range(1, 8) if port_open(a.port_base + i)]
    if busy:
        print(f"refused: ports in use: {busy}", file=sys.stderr)
        return 2
    os.makedirs(a.work)
    r = Regression(a)
    try:
        r.setup()
        r.execute()
    except Exception as e:  # a harness error is a FAIL
        r.rec("FAIL", "harness", "completed", f"{type(e).__name__}: {e}")
    finally:
        r.stop_leaks("final")
        for dirpath, dirs, _ in os.walk(a.work):  # leave nothing read-only behind
            for d in dirs:
                full = os.path.join(dirpath, d)
                if not os.path.islink(full):
                    os.chmod(full, os.stat(full).st_mode | stat.S_IWUSR)
    counts = {k: sum(x["status"] == k for x in r.results) for k in ("PASS", "FAIL", "NOT RUN", "NOTE")}
    summary = {"schema": "flh080_ctl_pidfile_regression_v1", "ctl_under_test": a.ctl,
               "ctl_sha256": subprocess.run(["sha256sum", a.ctl], capture_output=True, text=True).stdout.split()[0],
               "counts": counts, "leaks_stopped_by_test": r.leaks_stopped,
               "failed": [x for x in r.results if x["status"] == "FAIL"]}
    with open(os.path.join(a.work, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")
    print(json.dumps({"counts": counts, "leaks_stopped_by_test": len(r.leaks_stopped)}))
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
