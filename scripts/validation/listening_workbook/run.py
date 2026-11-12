"""Real-browser walkthrough of the workbook listening flow, against a disposable
server. See README.md in this directory.

- Fresh scratch DB in OUT/run-TAG, loopback only, empty working directory (no
  .env), clean environment. The daily instance and its data are never touched.
- LISTENING_PROVIDER=openai points at fake_openai.py on a random loopback port:
  no network, no key, no billing. It is only called by the probes that test the
  preparation boundary.
- Chromium runs in a disposable node:22-bookworm-slim container (--rm, host
  network so it reaches the loopback server). npm and the browser stay in the
  named volume flh-listening-workbook-pw, never in the repository. Only
  screenshots and results-TAG.json come back to OUT.

Usage: python3 -I run.py SERVER_BIN WEB_DIST OUT TAG
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
server_bin, web_dist, out, tag = (os.path.abspath(a) if i < 3 else a for i, a in enumerate(sys.argv[1:5]))
run = os.path.join(out, "run-" + tag)
shutil.rmtree(run, ignore_errors=True)
os.makedirs(run)
port_file, fake_log = os.path.join(run, "fake.port"), os.path.join(run, "fake.log")
fake = subprocess.Popen([sys.executable, "-I", os.path.join(HERE, "fake_openai.py"), port_file, fake_log])
for _ in range(50):
    if os.path.exists(port_file) and open(port_file).read().strip():
        break
    time.sleep(0.1)
fake_port = open(port_file).read().strip()

s = socket.socket()
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()
env = {"PATH": "/usr/bin:/bin", "HOME": run, "DB_PATH": os.path.join(run, "scratch.db"), "PORT": str(port), "LISTEN_HOST": "127.0.0.1",
       "LISTENING_PROVIDER": "openai", "OPENAI_API_KEY": "local-fake-key-not-a-secret", "OPENAI_MODEL": "local-fake-model",
       "OPENAI_BASE_URL": f"http://127.0.0.1:{fake_port}"}
server = subprocess.Popen([server_bin, "-web-dir", web_dist], cwd=run, env=env,
                          stdout=open(os.path.join(run, "server.log"), "w"), stderr=subprocess.STDOUT)
rc = 1
try:
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    uid, gid = os.getuid(), os.getgid()
    cmd = ["docker", "run", "--rm", "--network", "host",
           "-v", f"{os.path.join(HERE, 'walkthrough.mjs')}:/src/walkthrough.mjs:ro", "-v", f"{out}:/out",
           "-v", "flh-listening-workbook-pw:/opt/pw",
           "-e", "PLAYWRIGHT_BROWSERS_PATH=/opt/pw/browsers", "-e", f"BASE_URL=http://127.0.0.1:{port}", "-e", f"TAG={tag}", "-e", "OUT=/out",
           "-w", "/opt/pw", "node:22-bookworm-slim", "bash", "-c",
           "set -e; cp /src/walkthrough.mjs /opt/pw/walkthrough.mjs; "
           "[ -d node_modules/playwright ] || npm i --no-audit --no-fund --silent playwright@1.49.1 >/dev/null; "
           "npx playwright install --with-deps chromium > /tmp/install.log 2>&1 || { tail -20 /tmp/install.log; exit 1; }; "
           "npx playwright --version; rc=0; node walkthrough.mjs || rc=$?; "
           f"chown -R {uid}:{gid} /out/shots-{tag} /out/results-{tag}.json 2>/dev/null; exit $rc"]
    rc = subprocess.call(cmd)
    print("browser container rc", rc)
finally:
    server.terminate()
    server.wait(timeout=10)
    fake.terminate()
    fake.wait(timeout=10)
print("fake provider calls:", open(fake_log).read().strip() if os.path.exists(fake_log) else "none")
sys.exit(rc)
