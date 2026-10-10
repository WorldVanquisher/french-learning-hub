#!/usr/bin/env python3
"""Process and listener ownership for the FLH-034 demo (used by demo.sh).

A demo process is identified by three facts recorded when demo.sh starts it:
its PID, its kernel start time, and its command line, which must name this demo
directory (server: WORK/server; stub: stub_extractor.py ... WORK). A PID alone,
or a marker directory, is never enough to send a signal: a stale or reused PID
whose start time or command differs is left alone.

Supported platforms: Linux (/proc) and macOS (ps, lsof). Others are refused.

  proc_guard.py port-free PORT             exit 1 if anything accepts on 127.0.0.1/::1:PORT
  proc_guard.py record ROLE WORK           record identity of the PID in WORK/ROLE.pid
  proc_guard.py wait-listener ROLE WORK PORT SECONDS
                                           wait until that owned process itself listens on
                                           PORT, only on loopback addresses
  proc_guard.py stop WORK                  signal only verified demo processes, then check
                                           that no demo process for WORK is still running
  proc_guard.py scan WORK                  list running demo processes for WORK
"""

import ipaddress
import json
import os
import signal
import socket
import subprocess
import sys
import time

ROLES = ("server", "stub")
HERE = os.path.dirname(os.path.abspath(__file__))
STUB = os.path.join(HERE, "stub_extractor.py")
PLATFORM = sys.platform


def die(msg, code=1):
    print(f"proc_guard: {msg}", file=sys.stderr)
    sys.exit(code)


if not (PLATFORM.startswith("linux") or PLATFORM == "darwin"):
    die(f"unsupported platform {PLATFORM}; process ownership needs Linux /proc or macOS ps/lsof", 2)


def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def identity(pid):
    """(start_time, command) of a live PID, or None if it does not exist."""
    if PLATFORM.startswith("linux"):
        try:
            with open(f"/proc/{pid}/stat") as f:
                start = f.read().rsplit(")", 1)[1].split()[19]  # field 22: starttime
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().rstrip(b"\0").replace(b"\0", b" ").decode(errors="replace")
        except (OSError, IndexError):
            return None
        return (start, cmd) if cmd else None
    start = run(["ps", "-p", str(pid), "-o", "lstart="])
    cmd = run(["ps", "-ww", "-p", str(pid), "-o", "command="])
    if not start or not cmd:
        return None
    return (start.strip(), cmd.strip())


def role_matches(role, work, cmd):
    if role == "server":
        exe = os.path.join(work, "server")
        return cmd == exe or cmd.startswith(exe + " ")
    return STUB in cmd and cmd.endswith(" " + work)


def all_pids():
    return [int(p) for p in os.listdir("/proc") if p.isdigit()]


def listeners(pid, port):
    """Addresses on which PID itself holds a TCP LISTEN socket on PORT."""
    if PLATFORM.startswith("linux"):
        try:
            fds = os.listdir(f"/proc/{pid}/fd")
        except OSError:
            return []
        inodes = set()
        for fd in fds:
            try:
                link = os.readlink(f"/proc/{pid}/fd/{fd}")
            except OSError:
                continue
            if link.startswith("socket:["):
                inodes.add(link[8:-1])
        found = []
        for name, width in (("/proc/net/tcp", 4), ("/proc/net/tcp6", 16)):
            try:
                with open(name) as f:
                    rows = f.read().splitlines()[1:]
            except OSError:
                continue
            for row in rows:
                cols = row.split()
                if len(cols) < 10 or cols[3] != "0A" or cols[9] not in inodes:
                    continue
                hexaddr, hexport = cols[1].split(":")
                if int(hexport, 16) != port:
                    continue
                raw = bytes.fromhex(hexaddr)
                # /proc stores each 32-bit word in host (little-endian) order.
                raw = b"".join(raw[i:i + 4][::-1] for i in range(0, width, 4))
                found.append(str(ipaddress.ip_address(raw)))
        return found
    out = run(["lsof", "-nP", "-a", "-p", str(pid), f"-iTCP:{port}", "-sTCP:LISTEN", "-Fn"]) or ""
    found = []
    for line in out.splitlines():
        if line.startswith("n"):
            host = line[1:].rsplit(":", 1)[0].strip("[]")
            found.append(host)
    return found


def is_loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # "*" (wildcard) or anything unexpected


def paths(work, role):
    return os.path.join(work, f"{role}.pid"), os.path.join(work, f"{role}.id")


def owned_pid(role, work):
    """The recorded PID if, and only if, it is still the process demo.sh started."""
    pid_file, id_file = paths(work, role)
    try:
        pid = int(open(pid_file).read().strip())
        rec = json.load(open(id_file))
    except (OSError, ValueError):
        return None
    live = identity(pid)
    if rec.get("pid") != pid or live is None or [rec.get("start"), rec.get("command")] != list(live):
        return None
    return pid if role_matches(role, work, live[1]) else None


def cmd_port_free(port):
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        s = socket.socket(family, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect((host, port))
        except OSError:
            continue
        finally:
            s.close()
        die(f"port {port} is already in use on {host}; choose another port", 1)


def cmd_record(role, work):
    pid_file, id_file = paths(work, role)
    pid = int(open(pid_file).read().strip())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:  # wait for the launcher's exec to land
        live = identity(pid)
        if live is None:
            die(f"{role} (pid {pid}) exited during startup; see {work}/{role}.log")
        if role_matches(role, work, live[1]):
            with open(id_file + ".tmp", "w") as f:
                json.dump({"pid": pid, "start": live[0], "command": live[1]}, f)
            os.replace(id_file + ".tmp", id_file)
            return
        time.sleep(0.05)
    die(f"pid {pid} never became this demo's {role}")


def cmd_wait_listener(role, work, port, seconds):
    deadline = time.monotonic() + seconds
    while True:
        pid = owned_pid(role, work)
        if pid is None:
            die(f"{role} is not running as recorded (exited or replaced); see {work}/{role}.log")
        hosts = listeners(pid, port)
        if hosts:
            bad = [h for h in hosts if not is_loopback(h)]
            if bad:
                die(f"{role} pid {pid} listens on non-loopback {', '.join(bad)} port {port}")
            print(f"{role} pid {pid} listens on {', '.join(sorted(set(hosts)))} port {port} (loopback only)")
            return
        if time.monotonic() >= deadline:
            die(f"{role} pid {pid} is not listening on port {port}; see {work}/{role}.log")
        time.sleep(0.1)


def commands():
    """(pid, command) for every visible process."""
    if PLATFORM.startswith("linux"):
        for pid in all_pids():
            live = identity(pid)
            if live is not None:
                yield pid, live[1]
        return
    for line in (run(["ps", "-axww", "-o", "pid=,command="]) or "").splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if pid.isdigit():
            yield int(pid), cmd.strip()


def scan(work):
    me = os.getpid()
    return [(pid, role) for pid, cmd in commands() if pid != me
            for role in ROLES if role_matches(role, work, cmd)]


def cmd_stop(work):
    for role in ROLES:
        pid_file, id_file = paths(work, role)
        if not os.path.exists(pid_file):
            continue
        pid = owned_pid(role, work)
        if pid is None:
            raw = open(pid_file).read().strip()
            alive = raw.isdigit() and identity(int(raw)) is not None
            if alive:
                print(f"{role}: pid {raw} is not this demo's {role} (start time or command differs, "
                      f"or no identity record); NOT signalled")
            else:
                print(f"{role}: recorded pid {raw or '?'} is not running; stale record removed")
        else:
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 10
            while owned_pid(role, work) == pid and time.monotonic() < deadline:
                time.sleep(0.1)
            if owned_pid(role, work) == pid:
                die(f"{role} pid {pid} did not exit after SIGTERM; record kept")
            print(f"{role}: stopped pid {pid}")
        for f in (pid_file, id_file):
            if os.path.exists(f):
                os.remove(f)
    left = scan(work)
    if left:
        die("demo processes for this directory are still running and were not signalled "
            "(no matching record): " + ", ".join(f"{r} pid {p}" for p, r in left))


def main():
    a = sys.argv[1:]
    if a[:1] == ["port-free"] and len(a) == 2:
        cmd_port_free(int(a[1]))
    elif a[:1] == ["record"] and len(a) == 3 and a[1] in ROLES:
        cmd_record(a[1], a[2])
    elif a[:1] == ["wait-listener"] and len(a) == 5 and a[1] in ROLES:
        cmd_wait_listener(a[1], a[2], int(a[3]), float(a[4]))
    elif a[:1] == ["stop"] and len(a) == 2:
        cmd_stop(a[1])
    elif a[:1] == ["scan"] and len(a) == 2:
        for pid, role in scan(a[1]):
            print(f"{role} pid {pid}")
    else:
        die(__doc__.split("\n\n", 2)[2], 2)


if __name__ == "__main__":
    main()
