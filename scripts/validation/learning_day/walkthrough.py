#!/usr/bin/env python3
"""A synthetic learner's day in real Chromium: note → practice → Review Today →
Speaking → revision studio, with accessibility and narrow-screen checks.

    python3 -I scripts/validation/learning_day/walkthrough.py WORK_DIR [--from-db DB --facts FACTS.json]

WORK_DIR must be absolute, outside the repository, and new or empty. Builds the
server (go build -trimpath) and the workbench (vite build) from this tree into
WORK_DIR, then per combination (desktop 1280x900 English; phone 320x640
Simplified Chinese; phone 320x640 English, the longest labels) starts the server on a fresh WORK_DIR database (127.0.0.1,
a free port, empty environment, every provider disabled, no .env), seeds it
with scripts/demo/learning_day/seed.py and runs walkthrough.mjs in a
disposable node:22-bookworm-slim container (--rm, host network; Playwright
1.49.1 from the volume flh-listening-workbook-pw), with reduced motion
emulated. Writes WORK_DIR/results.json, WORK_DIR/shots/<combo>/*.png and logs.
Every server it started is stopped. Exit status is the browser's (0 all PASS),
2 when refused.

--from-db DB --facts FACTS.json: instead of seeding, each combination starts on
its own COPY of DB (with any -wal/-shm sidecar; DB itself is never opened), and
the browser uses FACTS.json as the seed's output. Use it with a database that
the same seed built and that went through a backup and restore
(scripts/validation/migration/rehearse.py), to run the same journey on restored
data.
"""
import json
import os
import shutil
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
    args = sys.argv[1:]
    opts = {}
    for flag in ("--from-db", "--facts"):
        if flag in args:
            i = args.index(flag)
            opts[flag] = args[i + 1]
            args = args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isabs(args[0]) or (("--from-db" in opts) != ("--facts" in opts)):
        print("usage: walkthrough.py /abs/new/empty/dir [--from-db DB --facts FACTS.json]", file=sys.stderr)
        return 2
    from_db = Path(os.path.realpath(opts["--from-db"])) if "--from-db" in opts else None
    work = Path(os.path.realpath(args[0]))
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
        for tag, locale, phone in (("desktop-en", "en", False), ("phone320-zh", "zh-CN", True), ("phone320-en", "en", True)):
            d = work / tag
            d.mkdir()
            if from_db:
                for side in ("", "-wal", "-shm"):
                    if Path(str(from_db) + side).exists():
                        shutil.copyfile(str(from_db) + side, d / f"app.db{side}")
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
            if from_db:
                facts = json.loads(Path(opts["--facts"]).read_text())
                combos.append({"tag": tag, "locale": locale, "phone": phone, "url": url, "seed": facts})
                continue
            seed = subprocess.run([sys.executable, "-I", "-B", str(REPO / "scripts/demo/learning_day/seed.py"), url, str(d / "app.db")], capture_output=True, text=True)
            (d / "seed.txt").write_text(seed.stdout + seed.stderr)
            if seed.returncode != 0:
                print(f"seed failed for {tag}: {seed.stderr}", file=sys.stderr)
                return 1
            combos.append({"tag": tag, "locale": locale, "phone": phone, "url": url, "seed": json.loads(seed.stdout.strip().splitlines()[-1])})
        uid, gid = os.getuid(), os.getgid()
        cmd = ["docker", "run", "--rm", "--network", "host",
               "-v", f"{HERE / 'walkthrough.mjs'}:/src/walk.mjs:ro", "-v", f"{REPO / 'web/src/i18n'}:/i18n:ro",
               "-v", f"{work}:/out", "-v", "flh-listening-workbook-pw:/opt/pw",
               "-e", "PLAYWRIGHT_BROWSERS_PATH=/opt/pw/browsers", "-e", f"COMBOS={json.dumps(combos)}", "-e", "OUT=/out",
               "-w", "/opt/pw", "node:22-bookworm-slim", "bash", "-c",
               "set -e; cp /src/walk.mjs /opt/pw/learning_day_walk.mjs; "
               "[ -d node_modules/playwright ] || npm i --no-audit --no-fund --silent playwright@1.49.1 >/dev/null; "
               "npx playwright install --with-deps chromium > /tmp/install.log 2>&1 || { tail -20 /tmp/install.log; exit 1; }; "
               "rc=0; node learning_day_walk.mjs || rc=$?; "
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
