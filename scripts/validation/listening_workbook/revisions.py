"""Real-browser walkthrough of a workbook script revision: an OLD server (its
embedded pack predates a correction) imports a script and saves a mistake in
its own UI; then a NEW server opens the same database and the learner walks
old mistake -> update preview -> update -> reopen the old mistake. See README.md.

- Four combinations, each on its own fresh scratch database: phone (390x844,
  touch) and desktop (1280x900), English and Simplified Chinese (the old
  server's part is always in English: it is only the setup).
- Loopback only, providers off, an empty working directory (no .env), a clean
  environment. The daily instance and its data are never touched.
- One disposable node:22-bookworm-slim container (--rm, host network) drives
  Chromium for all four. The harness swaps the servers between the old and
  new parts; the two sides signal each other through files in OUT/run-TAG/ctl.
  npm and the browser stay in the named volume flh-listening-workbook-pw.

Usage: python3 -I revisions.py OLD_BIN OLD_WEB NEW_BIN NEW_WEB OUT TAG
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
old_bin, old_web, new_bin, new_web, out = (os.path.abspath(a) for a in sys.argv[1:6])
tag = sys.argv[6]
COMBOS = ["phone-en", "desktop-en", "phone-zh", "desktop-zh"]
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


def start(binary, web, combo, side):
    d = os.path.join(run, combo)
    os.makedirs(d, exist_ok=True)
    port = free_port()
    env = {"PATH": "/usr/bin:/bin", "HOME": d, "DB_PATH": os.path.join(d, "scratch.db"), "PORT": str(port), "LISTEN_HOST": "127.0.0.1"}
    proc = subprocess.Popen([binary, "-web-dir", web], cwd=d, env=env, stdout=open(os.path.join(d, side + "-server.log"), "w"), stderr=subprocess.STDOUT)
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=1)
            return proc, f"http://127.0.0.1:{port}"
        except Exception:
            time.sleep(0.1)
    proc.terminate()
    raise SystemExit(f"{side} server for {combo} did not become ready")


def wait_for(path, browser, limit=300):
    for _ in range(limit * 10):
        if os.path.exists(path):
            return True
        if browser.poll() is not None:
            return False
        time.sleep(0.1)
    return False


uid, gid = os.getuid(), os.getgid()
cmd = ["docker", "run", "--rm", "--network", "host",
       "-v", f"{os.path.join(HERE, 'revisions.mjs')}:/src/revisions.mjs:ro", "-v", f"{out}:/out",
       "-v", "flh-listening-workbook-pw:/opt/pw",
       "-e", "PLAYWRIGHT_BROWSERS_PATH=/opt/pw/browsers", "-e", f"TAG={tag}", "-e", "OUT=/out", "-e", f"CTL=/out/run-{tag}/ctl",
       "-e", "COMBOS=" + ",".join(COMBOS),
       "-w", "/opt/pw", "node:22-bookworm-slim", "bash", "-c",
       "set -e; cp /src/revisions.mjs /opt/pw/revisions.mjs; "
       "[ -d node_modules/playwright ] || npm i --no-audit --no-fund --silent playwright@1.49.1 >/dev/null; "
       "npx playwright install --with-deps chromium > /tmp/install.log 2>&1 || { tail -20 /tmp/install.log; exit 1; }; "
       "npx playwright --version; rc=0; node revisions.mjs || rc=$?; "
       f"chown -R {uid}:{gid} /out/shots-{tag} /out/results-{tag}.json /out/run-{tag}/ctl 2>/dev/null; exit $rc"]
browser = subprocess.Popen(cmd)
rc = 1
try:
    for combo in COMBOS:
        old, url = start(old_bin, old_web, combo, "old")
        try:
            open(os.path.join(ctl, combo + ".old"), "w").write(url)
            ok = wait_for(os.path.join(ctl, combo + ".old-done"), browser)
        finally:
            old.terminate()
            old.wait(timeout=10)
        if not ok:
            print(f"{combo}: the browser did not finish the old part")
            break
        new, url = start(new_bin, new_web, combo, "new")
        try:
            open(os.path.join(ctl, combo + ".new"), "w").write(url)
            ok = wait_for(os.path.join(ctl, combo + ".new-done"), browser)
        finally:
            new.terminate()
            new.wait(timeout=10)
        if not ok:
            print(f"{combo}: the browser did not finish the new part")
            break
    rc = browser.wait(timeout=600)
    print("browser container rc", rc)
finally:
    if browser.poll() is None:
        browser.terminate()
sys.exit(rc)
