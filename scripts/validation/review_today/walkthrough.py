#!/usr/bin/env python3
"""Review Today browser walkthrough on synthetic data.

    python3 -I scripts/validation/review_today/walkthrough.py WORK_DIR

WORK_DIR must be absolute, outside the repository, and new or empty. Builds the
server (go build -trimpath) and the workbench (vite build) from this tree into
WORK_DIR, then per combination (desktop English, phone 390x844 Simplified
Chinese) starts the server on a fresh WORK_DIR database (127.0.0.1, a free
port, empty environment, every provider disabled, no .env), seeds it with
scripts/demo/review_today/seed.py and runs walkthrough.mjs in a disposable
node:22-bookworm-slim container (--rm, host network; Playwright 1.49.1 from
the volume flh-listening-workbook-pw). Writes WORK_DIR/results.json,
WORK_DIR/shots/<combo>/*.png and logs. Every server it started is stopped.
Exit status is the browser's (0 all PASS), 2 when refused.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    if len(sys.argv) != 2 or not os.path.isabs(sys.argv[1]):
        print("usage: walkthrough.py /abs/new/empty/dir", file=sys.stderr)
        return 2
    work = Path(os.path.realpath(sys.argv[1]))
    if work == REPO or REPO in work.parents:
        print("refused: WORK_DIR must be outside the repository", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        print("refused: WORK_DIR must be new or empty", file=sys.stderr)
        return 2
    server = work / "bin" / "server"
    dist = work / "web-dist"
    env_build = dict(os.environ, GOFLAGS="-buildvcs=false")
    subprocess.run(["go", "build", "-trimpath", "-o", str(server), "./cmd/server"], cwd=REPO, env=env_build, check=True)
    subprocess.run(["npx", "vite", "build", "--outDir", str(dist), "--emptyOutDir"], cwd=REPO / "web", check=True,
                   stdout=subprocess.DEVNULL)
    procs, combos = [], []
    rc = 1
    try:
        for tag, locale, phone in (("desktop-en", "en", False), ("phone-zh", "zh-CN", True)):
            d = work / tag
            d.mkdir()
            port = free_port()
            env = {"PATH": "/usr/bin:/bin", "HOME": str(d), "LISTEN_HOST": "127.0.0.1", "PORT": str(port), "DB_PATH": str(d / "app.db"),
                   "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "disabled", "SPEAKING_PROVIDER": "disabled",
                   "SPEAKING_TRANSCRIPTION_PROVIDER": "disabled", "LISTENING_PROVIDER": "disabled"}
            log = open(d / "server.log", "ab")
            proc = subprocess.Popen([str(server), "-web-dir", str(dist)], cwd=d, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            procs.append((proc, log))
            url = f"http://127.0.0.1:{port}"
            for _ in range(300):
                try:
                    if urllib.request.urlopen(url + "/readyz", timeout=2).status == 200:
                        break
                except OSError:
                    time.sleep(0.1)
            seed = subprocess.run([sys.executable, "-I", "-B", str(REPO / "scripts/demo/review_today/seed.py"), url], capture_output=True, text=True)
            (d / "seed.txt").write_text(seed.stdout + seed.stderr)
            if seed.returncode != 0:
                print(f"seed failed for {tag}: {seed.stderr}", file=sys.stderr)
                return 1
            combos.append({"tag": tag, "locale": locale, "phone": phone, "url": url})
        uid, gid = os.getuid(), os.getgid()
        cmd = ["docker", "run", "--rm", "--network", "host",
               "-v", f"{HERE / 'walkthrough.mjs'}:/src/walk.mjs:ro", "-v", f"{REPO / 'web/src/i18n'}:/i18n:ro",
               "-v", f"{work}:/out", "-v", "flh-listening-workbook-pw:/opt/pw",
               "-e", "PLAYWRIGHT_BROWSERS_PATH=/opt/pw/browsers", "-e", f"COMBOS={json.dumps(combos)}", "-e", "OUT=/out",
               "-w", "/opt/pw", "node:22-bookworm-slim", "bash", "-c",
               "set -e; cp /src/walk.mjs /opt/pw/review_today_walk.mjs; "
               "[ -d node_modules/playwright ] || npm i --no-audit --no-fund --silent playwright@1.49.1 >/dev/null; "
               "npx playwright install --with-deps chromium > /tmp/install.log 2>&1 || { tail -20 /tmp/install.log; exit 1; }; "
               "rc=0; node review_today_walk.mjs || rc=$?; "
               f"chown -R {uid}:{gid} /out/shots /out/results.json 2>/dev/null; exit $rc"]
        rc = subprocess.run(cmd, timeout=1200).returncode
    finally:
        for proc, log in procs:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=20)
            log.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
