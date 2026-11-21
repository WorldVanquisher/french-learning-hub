#!/usr/bin/env python3
"""Vocabulary in real Chromium on the synthetic Vocabulary fixture (VOC).

    python3 -I scripts/validation/vocabulary/walkthrough.py WORK_DIR

WORK_DIR must be absolute, outside the repository, and new or empty. Builds the server (go build -trimpath)
and the workbench (vite build) from this tree, then per combination (desktop 1280x900 English; phone 320x640
English; phone 320x640 Simplified Chinese) starts scripts/demo/vocabulary/stub_extractor.py and the server on
a FRESH database in WORK_DIR (127.0.0.1, free ports, empty environment, the extractor pointed at the stub with
a placeholder key, every other provider disabled, no .env), seeds it with scripts/demo/vocabulary/seed.py
(API only) and runs walkthrough.mjs in a disposable node:22-bookworm-slim container (Playwright 1.49.1 from
the volume flh-listening-workbook-pw), reduced motion emulated.

Writes WORK_DIR/results.json, WORK_DIR/shots/<combo>/*.png and logs. Every process it started is stopped.
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
sys.dont_write_bytecode = True


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    if len(sys.argv) != 2 or not os.path.isabs(sys.argv[1]):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    work = Path(os.path.realpath(sys.argv[1]))
    if work == REPO or REPO in work.parents or (work.exists() and any(work.iterdir())):
        print("refused: WORK_DIR must be outside the repository and new or empty", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    server, dist = work / "bin" / "server", work / "web-dist"
    subprocess.run(["go", "build", "-trimpath", "-o", str(server), "./cmd/server"], cwd=REPO, env=dict(os.environ, GOFLAGS="-buildvcs=false"), check=True)
    subprocess.run(["npx", "vite", "build", "--outDir", str(dist), "--emptyOutDir"], cwd=REPO / "web", check=True, stdout=subprocess.DEVNULL)
    procs, combos, rc = [], [], 1
    try:
        for tag, locale, phone in (("desktop-en", "en", False), ("phone320-en", "en", True), ("phone320-zh", "zh-CN", True)):
            d = work / tag
            d.mkdir()
            sp, ap = free_port(), free_port()
            stub = subprocess.Popen([sys.executable, "-I", "-B", str(REPO / "scripts/demo/vocabulary/stub_extractor.py"), str(sp)], cwd=d,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            procs.append((stub, None))
            env = {"PATH": "/usr/bin:/bin", "HOME": str(d), "LISTEN_HOST": "127.0.0.1", "PORT": str(ap), "DB_PATH": str(d / "app.db"),
                   "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "openai", "OPENAI_API_KEY": "sk-local-demo-not-a-secret",
                   "OPENAI_BASE_URL": f"http://127.0.0.1:{sp}", "OPENAI_MODEL": "stub-model", "EMBEDDING_PROVIDER": "disabled",
                   "SPEAKING_PROVIDER": "disabled", "SPEAKING_TRANSCRIPTION_PROVIDER": "disabled", "LISTENING_PROVIDER": "disabled"}
            log = open(d / "server.log", "ab")
            proc = subprocess.Popen([str(server), "-web-dir", str(dist)], cwd=d, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            procs.append((proc, log))
            url = f"http://127.0.0.1:{ap}"
            for _ in range(300):
                try:
                    if urllib.request.urlopen(url + "/readyz", timeout=2).status == 200:
                        break
                except OSError:
                    time.sleep(0.1)
            seed = subprocess.run([sys.executable, "-I", "-B", str(REPO / "scripts/demo/vocabulary/seed.py"), url], capture_output=True, text=True)
            if seed.returncode != 0:
                print(f"seed failed for {tag}: {seed.stderr}", file=sys.stderr)
                return 1
            (d / "facts.json").write_text(seed.stdout.strip().splitlines()[-1])
            combos.append({"tag": tag, "locale": locale, "phone": phone, "url": url, "facts": json.loads((d / "facts.json").read_text())})
        uid, gid = os.getuid(), os.getgid()
        cmd = ["docker", "run", "--rm", "--network", "host",
               "-v", f"{HERE / 'walkthrough.mjs'}:/src/walk.mjs:ro", "-v", f"{REPO / 'web/src/i18n'}:/i18n:ro",
               "-v", f"{work}:/out", "-v", "flh-listening-workbook-pw:/opt/pw",
               "-e", "PLAYWRIGHT_BROWSERS_PATH=/opt/pw/browsers", "-e", f"COMBOS={json.dumps(combos)}", "-e", "OUT=/out",
               "-w", "/opt/pw", "node:22-bookworm-slim", "bash", "-c",
               "set -e; cp /src/walk.mjs /opt/pw/vocabulary_walk.mjs; "
               "[ -d node_modules/playwright ] || npm i --no-audit --no-fund --silent playwright@1.49.1 >/dev/null; "
               "npx playwright install --with-deps chromium > /tmp/install.log 2>&1 || { tail -20 /tmp/install.log; exit 1; }; "
               "rc=0; node vocabulary_walk.mjs || rc=$?; "
               f"chown -R {uid}:{gid} /out/shots /out/results.json 2>/dev/null; exit $rc"]
        rc = subprocess.run(cmd, timeout=1500).returncode
    finally:
        for proc, log in procs:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=20)
            if log:
                log.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
