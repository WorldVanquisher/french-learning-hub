"""FLH-152 phone walk of a script update on an upgraded database (see README.md).

Each combination (phone-en, phone-zh) gets its own writable copy of the
snapshot written by upgrade_rehearsal.py (a database seeded by the pre-revision
build). The NEW build serves it with the workbench; when the browser asks, the
harness stops it and starts the VARIANT build (same database, same port), so
previews opened before the swap meet a changed pack.

- Loopback only, providers disabled, an empty working directory (no .env), a
  clean environment. The daily instance and its data are never touched.
- One disposable node:22-bookworm-slim container (--rm, host network) drives
  Chromium; npm and the browser stay in the named volume
  flh-listening-workbook-pw. The two sides signal through files in
  OUT/run-TAG/ctl.

Usage: python3 -I upgrade_walk.py SNAPSHOT_DIR NEW_BIN VARIANT_BIN WEB_DIR OUT TAG
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
snapshot, new_bin, variant_bin, web, out = (os.path.abspath(a) for a in sys.argv[1:6])
tag = sys.argv[6]
COMBOS = ["phone-en", "phone-zh"]
run = os.path.join(out, "run-" + tag)
ctl = os.path.join(run, "ctl")
shutil.rmtree(run, ignore_errors=True)
os.makedirs(ctl)
os.chmod(ctl, 0o777)  # the container writes its signals here


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start(binary, d, port, side):
    env = {"PATH": "/usr/bin:/bin", "HOME": d, "DB_PATH": os.path.join(d, "db", "app.db"), "PORT": str(port),
           "LISTEN_HOST": "127.0.0.1"}
    log = open(os.path.join(d, side + "-server.log"), "w")
    proc = subprocess.Popen([binary, "-web-dir", web], cwd=d, env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(150):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=1)
            return proc
        except Exception:
            time.sleep(0.1)
    proc.terminate()
    raise SystemExit(f"{side} server in {d} did not become ready")


def wait_for(path, browser, limit=300):
    for _ in range(limit * 10):
        if os.path.exists(path):
            return True
        if browser.poll() is not None:
            return False
        time.sleep(0.1)
    return False


def stop(proc):
    proc.terminate()
    proc.wait(timeout=10)


uid, gid = os.getuid(), os.getgid()
cmd = ["docker", "run", "--rm", "--network", "host",
       "-v", f"{os.path.join(HERE, 'upgrade_walk.mjs')}:/src/upgrade_walk.mjs:ro", "-v", f"{out}:/out",
       "-v", "flh-listening-workbook-pw:/opt/pw",
       "-e", "PLAYWRIGHT_BROWSERS_PATH=/opt/pw/browsers", "-e", f"TAG={tag}", "-e", "OUT=/out",
       "-e", f"CTL=/out/run-{tag}/ctl", "-e", "COMBOS=" + ",".join(COMBOS),
       "-w", "/opt/pw", "node:22-bookworm-slim", "bash", "-c",
       "set -e; cp /src/upgrade_walk.mjs /opt/pw/upgrade_walk.mjs; "
       "[ -d node_modules/playwright ] || npm i --no-audit --no-fund --silent playwright@1.49.1 >/dev/null; "
       "npx playwright install --with-deps chromium > /tmp/install.log 2>&1 || { tail -20 /tmp/install.log; exit 1; }; "
       "npx playwright --version; rc=0; node upgrade_walk.mjs || rc=$?; "
       f"chown -R {uid}:{gid} /out/shots-{tag} /out/results-{tag}.json /out/run-{tag}/ctl 2>/dev/null; exit $rc"]
browser = subprocess.Popen(cmd)
rc = 1
try:
    for combo in COMBOS:
        d = os.path.join(run, combo)
        os.makedirs(os.path.join(d, "db"))
        for name in os.listdir(snapshot):
            if name.startswith("app.db"):
                shutil.copyfile(os.path.join(snapshot, name), os.path.join(d, "db", name))
                os.chmod(os.path.join(d, "db", name), 0o600)
        port = free_port()
        proc = start(new_bin, d, port, "new")
        try:
            open(os.path.join(ctl, combo + ".url"), "w").write(f"http://127.0.0.1:{port}")
            ok = wait_for(os.path.join(ctl, combo + ".swap"), browser)
        finally:
            stop(proc)
        if not ok:
            print(f"{combo}: the browser did not ask for the swap")
            break
        proc = start(variant_bin, d, port, "variant")
        try:
            open(os.path.join(ctl, combo + ".swapped"), "w").write("variant")
            ok = wait_for(os.path.join(ctl, combo + ".done"), browser)
        finally:
            stop(proc)
        if not ok:
            print(f"{combo}: the browser did not finish")
            break
    rc = browser.wait(timeout=600)
    print("browser container rc", rc)
finally:
    if browser.poll() is None:
        browser.terminate()
sys.exit(rc)
