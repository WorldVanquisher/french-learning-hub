"""FLH-065: detached supervisor for one `python -m flh_e5 serve` run.

flh-e5.ps1 starts this file with the Conda environment's python.exe through
WMI (outside the SSH session's job object). It reads one JSON launch spec,
starts the service as its child with the spec's exact argument list, working
directory and environment additions, sends the child's stdout/stderr straight
to files, and waits. A stop request file asks for a graceful stop
(CTRL_BREAK_EVENT on Windows, SIGINT elsewhere); after the graceful timeout the
child is terminated. The supervisor never touches any other process.

Records written in the run directory (atomically):
  runner.json  supervisor and child PIDs, state
  exit.json    child exit code and reason
  runner.log   the supervisor's own log lines

Stdlib only; Python 3.8+. Usage: python -B -I runner.py --spec <launch.json>
"""

import argparse
import datetime
import json
import os
import signal
import subprocess
import sys
import time

SCHEMA = "flh065_e5_launch_v1"
POLL_S = 0.25
IS_WINDOWS = os.name == "nt"


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def write_json_atomic(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def read_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:  # PowerShell 5.1 may write a BOM
        return json.load(f)


class RunLog:
    def __init__(self, path):
        self.path = path

    def __call__(self, msg):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("%s runner[%d]: %s\n" % (utc_now(), os.getpid(), msg))


def load_spec(path):
    spec = read_json(path)
    if spec.get("schema") != SCHEMA:
        raise ValueError("launch spec schema must be %s" % SCHEMA)
    for key in ("run_id", "run_dir", "python", "args", "cwd", "stdout_log", "stderr_log", "stop_request"):
        if key not in spec:
            raise ValueError("launch spec is missing %r" % key)
    if not isinstance(spec["args"], list) or not all(isinstance(a, str) for a in spec["args"]):
        raise ValueError("launch spec 'args' must be a list of strings")
    for key in ("run_dir", "python", "cwd", "stdout_log", "stderr_log", "stop_request"):
        if not os.path.isabs(spec[key]):
            raise ValueError("launch spec %r must be an absolute path" % key)
    spec.setdefault("env_set", {})
    spec.setdefault("env_path_prepend", [])
    spec.setdefault("graceful_timeout_s", 30)
    return spec


def child_env(spec):
    env = dict(os.environ)
    for k, v in spec["env_set"].items():
        env[str(k)] = str(v)
    if spec["env_path_prepend"]:
        env["PATH"] = os.pathsep.join(list(spec["env_path_prepend"]) + [env.get("PATH", "")])
    return env


def ensure_console(log):
    """CTRL_BREAK_EVENT needs a console shared with the child. A WMI-created
    console process normally has one; allocate one if it does not."""
    if not IS_WINDOWS:
        return
    import ctypes
    k32 = ctypes.windll.kernel32
    if k32.GetConsoleWindow() == 0 and k32.AllocConsole():
        log("allocated a console for graceful stop")


def request_graceful(child, log):
    try:
        if IS_WINDOWS:
            child.send_signal(signal.CTRL_BREAK_EVENT)  # only the child's own process group
        else:
            child.send_signal(signal.SIGINT)
        log("graceful stop signal sent to child %d" % child.pid)
        return True
    except (OSError, ValueError) as e:
        log("graceful stop signal failed: %s" % e)
        return False


def supervise(spec):
    run_dir = spec["run_dir"]
    log = RunLog(os.path.join(run_dir, "runner.log"))
    runner_json = os.path.join(run_dir, "runner.json")
    exit_json = os.path.join(run_dir, "exit.json")
    state = {"schema": "flh065_e5_runner_v1", "run_id": spec["run_id"], "runner_pid": os.getpid(),
             "child_pid": None, "started_utc": utc_now(), "state": "launching"}
    write_json_atomic(runner_json, state)
    ensure_console(log)
    argv = [spec["python"]] + spec["args"]
    log("launch: %s (cwd %s)" % (subprocess.list2cmdline(argv), spec["cwd"]))
    kwargs = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        with open(spec["stdout_log"], "ab") as out, open(spec["stderr_log"], "ab") as err:
            child = subprocess.Popen(argv, cwd=spec["cwd"], env=child_env(spec), stdin=subprocess.DEVNULL,
                                     stdout=out, stderr=err, close_fds=True, **kwargs)
    except OSError as e:
        log("launch failed: %s" % e)
        state.update(state="launch_failed")
        write_json_atomic(runner_json, state)
        write_json_atomic(exit_json, {"run_id": spec["run_id"], "child_exit_code": None, "reason": "launch_failed",
                                      "error": str(e), "finished_utc": utc_now()})
        return 1
    state.update(child_pid=child.pid, child_started_utc=utc_now(), state="running")
    write_json_atomic(runner_json, state)
    log("child pid %d" % child.pid)

    reason = "exited"
    stop_deadline = None
    while True:
        code = child.poll()
        if code is not None:
            break
        if stop_deadline is None and os.path.exists(spec["stop_request"]):
            try:
                req = read_json(spec["stop_request"])
            except (OSError, ValueError):
                req = {}
            force = req.get("mode") == "force"
            timeout = float(req.get("graceful_timeout_s", spec["graceful_timeout_s"]))
            log("stop requested (mode %s, graceful timeout %ss)" % ("force" if force else "graceful", timeout))
            state.update(state="stopping")
            write_json_atomic(runner_json, state)
            if force or not request_graceful(child, log):
                timeout = 0.0
            stop_deadline = time.monotonic() + timeout
            reason = "stop_requested_graceful"
        if stop_deadline is not None and time.monotonic() >= stop_deadline:
            log("graceful timeout reached; terminating child %d" % child.pid)
            child.kill()
            reason = "stop_requested_forced"
            code = child.wait()
            break
        time.sleep(POLL_S)
    log("child exited with code %s (%s)" % (code, reason))
    state.update(state="exited")
    write_json_atomic(runner_json, state)
    write_json_atomic(exit_json, {"run_id": spec["run_id"], "child_exit_code": code, "reason": reason,
                                  "finished_utc": utc_now()})
    return 0


def main(argv):
    ap = argparse.ArgumentParser(prog="runner.py", description="FLH-065 E5 service supervisor")
    ap.add_argument("--spec", required=True, help="absolute path of the run's launch.json")
    args = ap.parse_args(argv)
    try:
        spec = load_spec(args.spec)
    except (OSError, ValueError) as e:
        print("runner: invalid launch spec: %s" % e, file=sys.stderr)
        return 2
    return supervise(spec)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
