"""Linux-only, task-owned lifecycle probes for the unchanged author demo."""
import http.server
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading

from integrated_checks import require


def identity(pid):
    stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    command = Path(f"/proc/{pid}/cmdline").read_bytes().rstrip(b"\0").replace(b"\0", b" ").decode()
    return {"pid": pid, "start": stat[19], "command": command}


def listener_addresses(pid, port):
    inodes = set()
    for fd in Path(f"/proc/{pid}/fd").iterdir():
        try:
            link = os.readlink(fd)
        except FileNotFoundError:
            continue
        if link.startswith("socket:["):
            inodes.add(link[8:-1])
    result = []
    for table in ("tcp", "tcp6"):
        for row in Path(f"/proc/net/{table}").read_text().splitlines()[1:]:
            fields = row.split()
            host, hexport = fields[1].split(":")
            if fields[3] == "0A" and fields[9] in inodes and int(hexport, 16) == port:
                raw = bytes.fromhex(host)
                raw = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
                result.append(str(ipaddress.ip_address(raw)))
    return sorted(result)


def verify_identity(run):
    evidence = {}
    for role, port in (("server", run.port), ("stub", run.stub_port)):
        pid = int((run.work / f"{role}.pid").read_text())
        record = json.loads((run.work / f"{role}.id").read_text())
        live = identity(pid)
        require(record == live, f"{role}: Linux PID/start-time/command record mismatch")
        addresses = listener_addresses(pid, port)
        require(addresses == ["127.0.0.1"], f"{role}: expected owned IPv4 loopback only, got {addresses}")
        evidence[role] = {"record": record, "live": live, "listener_addresses": addresses}
    run.observations.setdefault("linux_identity", []).append(evidence)
    run.passed("direct Linux socket inode, PID, kernel start-time and command verification", evidence)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def safety_probes(run):
    demo = Path(__file__).resolve().parents[2] / "demo/flh034/demo.sh"
    guard = demo.parent / "proc_guard.py"
    directory = run.parent / "identity-probe"
    directory.mkdir()
    (directory / ".flh034-demo").touch()
    sentinel = subprocess.Popen(["sleep", "120"], env=run.env)
    try:
        # PID alone, an exact non-demo identity, and either identity field mismatch
        # must all preserve our sentinel; each record is independently consumed.
        for variant in ("missing", "exact-non-demo", "start-mismatch", "command-mismatch"):
            (directory / "server.pid").write_text(str(sentinel.pid))
            record = identity(sentinel.pid)
            if variant == "start-mismatch":
                record["start"] = str(int(record["start"]) + 1)
            if variant == "command-mismatch":
                record["command"] = str(directory / "server")
            if variant != "missing":
                (directory / "server.id").write_text(json.dumps(record))
            result = run.command(["sh", str(demo), "stop", str(directory)])
            require(sentinel.poll() is None and "NOT signalled" in result.stdout,
                    f"{variant}: misattributed sentinel was signalled")
            require(not (directory / "server.pid").exists() and not (directory / "server.id").exists(),
                    "mismatched records not removed")
            run.passed("misattributed record " + variant, result.stdout)
        dead = subprocess.Popen(["true"], env=run.env)
        dead.wait(timeout=5)
        (directory / "server.pid").write_text(str(dead.pid))
        result = run.command(["sh", str(demo), "stop", str(directory)])
        require("stale record removed" in result.stdout and not (directory / "server.pid").exists(),
                "dead record not removed")
        run.passed("dead PID record removed", result.stdout)
        run.command(["sh", str(demo), "cleanup", str(directory)])
        require(sentinel.poll() is None and not directory.exists(), "cleanup signalled sentinel")
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=5)

    # A newer process with this directory's command identity must NOT be killed
    # using its predecessor's start time. Scan must prevent false stop/cleanup.
    directory = run.parent / "newer-identity"
    directory.mkdir()
    (directory / ".flh034-demo").touch()
    shutil.copy2(shutil.which("sleep", path=run.env["PATH"]), directory / "server")
    predecessor = subprocess.Popen([str(directory / "server"), "120"], env=run.env)
    old = identity(predecessor.pid)
    predecessor.terminate()
    predecessor.wait(timeout=5)
    newer = subprocess.Popen([str(directory / "server"), "120"], env=run.env)
    try:
        live = identity(newer.pid)
        record = dict(old, pid=newer.pid)
        # Kernel ticks can be equal for immediate successive starts; force an
        # older tick if needed and record that simulation explicitly.
        record["start"] = str(min(int(old["start"]), int(live["start"]) - 1))
        (directory / "server.pid").write_text(str(newer.pid))
        (directory / "server.id").write_text(json.dumps(record))
        result = run.command(["sh", str(demo), "stop", str(directory)], expected=1)
        require(newer.poll() is None and "NOT signalled" in result.stdout and "still running" in result.stdout,
                "newer identity mismatch did not refuse signalling")
        run.command(["sh", str(demo), "cleanup", str(directory)], expected=1)
        require(directory.exists() and newer.poll() is None, "unsafe deletion/signalling after mismatch")
        run.passed("newer directory identity mismatch refuses stop and cleanup",
                   {"predecessor": old, "newer": live, "stale_record": record, "output": result.stdout})
        (directory / "server.pid").write_text(str(newer.pid))
        (directory / "server.id").write_text(json.dumps(live))
        run.command(["sh", str(demo), "stop", str(directory)])
        newer.wait(timeout=5)
        require(newer.returncode == -15, "verified sentinel not stopped by SIGTERM")
        run.command(["sh", str(demo), "cleanup", str(directory)])
        run.passed("restored exact Linux identity permits normal stop")
    finally:
        if newer.poll() is None:
            newer.terminate()
        newer.wait(timeout=5)

    requests = []

    class Collision(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            requests.append(("GET", self.path))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"entries":[],"concepts":[]}')

        def do_POST(self):
            requests.append(("POST", self.path))
            self.send_response(503)
            self.end_headers()

    occupant = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Collision)
    thread = threading.Thread(target=occupant.serve_forever, daemon=True)
    thread.start()
    saved = dict(run.env)
    try:
        for role in ("app", "stub"):
            extra = run.parent / ("collision-" + role)
            collision = occupant.server_address[1]
            app, stub = (collision, free_port()) if role == "app" else (free_port(), collision)
            run.env.update(DEMO_PORT=str(app), STUB_PORT=str(stub))
            result = run.command(["sh", str(demo), "setup", str(extra)], expected=1)
            require("is in use" in result.stdout and "setup FAILED" in result.stdout,
                    "occupied-port refusal missing")
            require(requests == [], "occupied fixture received HTTP requests before refusal")
            require(not (extra / "seed.json").exists() and not (extra / "server").exists(),
                    "occupied setup built or wrote success receipt")
            require(run.command(["python3", "-B", str(guard), "scan", str(extra)]).stdout == "",
                    "occupied setup leaked children")
            run.command(["sh", str(demo), "cleanup", str(extra)])
            run.passed("occupied " + role + " port refuses before build/seed with zero fixture requests",
                       {"exit": result.returncode, "requests": list(requests), "output": result.stdout})
    finally:
        run.env = saved
        occupant.shutdown()
        occupant.server_close()
        thread.join(timeout=3)
        require(not thread.is_alive(), "collision thread leaked")

    for fault in ("partial-startup", "seed-failure"):
        extra = run.parent / fault
        saved = dict(run.env)
        app, stub = free_port(), free_port()
        run.env.update(DEMO_PORT=str(app), STUB_PORT=str(stub))
        try:
            if fault == "seed-failure":
                shim = run.parent / "seed-shim"
                shim.mkdir()
                python = shutil.which("python3", path=run.env["PATH"])
                (shim / "python3").write_text(
                    '#!/bin/sh\nfor arg do\n  case "$arg" in */scripts/demo/flh034/seed.py) exit 7;; esac\ndone\n'
                    + 'exec "' + python + '" "$@"\n')
                (shim / "python3").chmod(0o700)
                run.env["PATH"] = str(shim) + ":" + run.env["PATH"]
                run.observations["seed_failure_shim"] = (shim / "python3").read_text()
            result = run.command(["sh", str(demo), "setup", str(extra),
                                  str(run.parent / "absent-dist") if fault == "partial-startup"
                                  else str(run.web / "dist")], expected=1)
            require("setup FAILED" in result.stdout and not (extra / "seed.json").exists(),
                    fault + ": false success receipt")
            if fault == "seed-failure":
                require("seed failed" in result.stdout and (extra / "seed.partial.json").exists(),
                        "seed failure was not reached after readiness")
            else:
                require("workbench index.html" in (extra / "server.log").read_text(),
                        "partial startup failure was not reached")
            require(run.command(["python3", "-B", str(guard), "scan", str(extra)]).stdout == "",
                    fault + ": owned children leaked")
            require(not listener_addresses(os.getpid(), app), "unexpected test listener")
            from verify_integrated import listener_alive
            require(not listener_alive(None, app) and not listener_alive(None, stub),
                    fault + ": reserved listener leaked")
            run.passed(fault + " exits nonzero, no success receipt, no owned children",
                       {"output": result.stdout, "server_log": (extra / "server.log").read_text(),
                        "stub_log": (extra / "stub.log").read_text()})
        finally:
            run.env = saved
            if (extra / ".flh034-demo").exists():
                run.command(["sh", str(demo), "cleanup", str(extra)])
