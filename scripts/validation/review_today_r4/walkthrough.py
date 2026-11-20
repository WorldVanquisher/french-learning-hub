#!/usr/bin/env python3
"""Review Today R4 in real Chromium on the synthetic R4 profile.

    python3 -I scripts/validation/review_today_r4/walkthrough.py WORK_DIR [--tree TREE] [--baseline] [--from-db DB]

WORK_DIR must be absolute, outside the repository, and new or empty. Builds the server (go build
-trimpath) and the workbench (vite build) from TREE (default: this repository; give the extracted
start tree with --baseline to record the baseline), then per combination (desktop 1280x900 English;
phone 320x640 Simplified Chinese; phone 320x640 English) starts the server on a fresh database in
WORK_DIR (127.0.0.1, a free port, empty environment, every provider disabled, no .env), seeds it with
scripts/demo/review_today_r4/profile.py (always from this repository: it uses the API only), and runs
walkthrough.mjs in a disposable node:22-bookworm-slim container (Playwright 1.49.1 from the volume
flh-listening-workbook-pw), reduced motion emulated.

--from-db DB: instead of seeding, each combination starts on its own COPY of DB (a restored profile
database; DB itself is never opened) and reads the profile facts from DB's directory (profile.json).
--baseline: the browser only records what the baseline does (screenshots and observations), no
pass/fail for R4 behaviour.

Writes WORK_DIR/results.json, WORK_DIR/shots/<combo>/*.png, WORK_DIR/<combo>/profile.json and logs.
Every server it started is stopped. Exit status is the browser's (0 all PASS), 2 when refused.
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
sys.dont_write_bytecode = True


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    args = sys.argv[1:]
    opts = {"--tree": str(REPO), "--from-db": None}
    baseline = "--baseline" in args
    args = [a for a in args if a != "--baseline"]
    for k in list(opts):
        if k in args:
            i = args.index(k)
            opts[k] = args[i + 1]
            args = args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isabs(args[0]):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    work, tree = Path(os.path.realpath(args[0])), Path(os.path.realpath(opts["--tree"]))
    if work == REPO or REPO in work.parents or (work.exists() and any(work.iterdir())):
        print("refused: WORK_DIR must be outside the repository and new or empty", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    server, dist = work / "bin" / "server", work / "web-dist"
    subprocess.run(["go", "build", "-trimpath", "-o", str(server), "./cmd/server"], cwd=tree, env=dict(os.environ, GOFLAGS="-buildvcs=false"), check=True)
    web = tree / "web"
    if not (web / "node_modules").exists():
        os.symlink(REPO / "web" / "node_modules", web / "node_modules")
    subprocess.run(["npx", "vite", "build", "--outDir", str(dist), "--emptyOutDir"], cwd=web, check=True, stdout=subprocess.DEVNULL)
    procs, combos, rc = [], [], 1
    try:
        for tag, locale, phone in (("desktop-en", "en", False), ("phone320-zh", "zh-CN", True), ("phone320-en", "en", True)):
            d = work / tag
            d.mkdir()
            db = d / "app.db"
            if opts["--from-db"]:
                src = Path(opts["--from-db"])
                for sfx in ("", "-wal", "-shm"):
                    if Path(str(src) + sfx).exists():
                        shutil.copy2(str(src) + sfx, str(db) + sfx)
                shutil.copy2(src.parent / "profile.json", d / "profile.json")
            port = free_port()
            env = {"PATH": "/usr/bin:/bin", "HOME": str(d), "LISTEN_HOST": "127.0.0.1", "PORT": str(port), "DB_PATH": str(db),
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
            if not opts["--from-db"]:
                seed = subprocess.run([sys.executable, "-I", "-B", str(REPO / "scripts/demo/review_today_r4/profile.py"), url, str(db)], capture_output=True, text=True)
                if seed.returncode != 0:
                    print(f"seed failed for {tag}: {seed.stderr}", file=sys.stderr)
                    return 1
                (d / "profile.json").write_text(seed.stdout.strip().splitlines()[-1])
            combos.append({"tag": tag, "locale": locale, "phone": phone, "url": url, "facts": json.loads((d / "profile.json").read_text())})
        uid, gid = os.getuid(), os.getgid()
        cmd = ["docker", "run", "--rm", "--network", "host",
               "-v", f"{HERE / 'walkthrough.mjs'}:/src/walk.mjs:ro", "-v", f"{tree / 'web/src/i18n'}:/i18n:ro",
               "-v", f"{work}:/out", "-v", "flh-listening-workbook-pw:/opt/pw",
               "-e", "PLAYWRIGHT_BROWSERS_PATH=/opt/pw/browsers", "-e", f"COMBOS={json.dumps(combos)}", "-e", "OUT=/out",
               "-e", f"MODE={'baseline' if baseline else 'r4'}",
               "-w", "/opt/pw", "node:22-bookworm-slim", "bash", "-c",
               "set -e; cp /src/walk.mjs /opt/pw/review_today_r4_walk.mjs; "
               "[ -d node_modules/playwright ] || npm i --no-audit --no-fund --silent playwright@1.49.1 >/dev/null; "
               "npx playwright install --with-deps chromium > /tmp/install.log 2>&1 || { tail -20 /tmp/install.log; exit 1; }; "
               "rc=0; node review_today_r4_walk.mjs || rc=$?; "
               f"chown -R {uid}:{gid} /out/shots /out/results.json 2>/dev/null; exit $rc"]
        rc = subprocess.run(cmd, timeout=1500).returncode
    finally:
        for proc, log in procs:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=20)
            log.close()
        if (tree / "web" / "node_modules").is_symlink():
            (tree / "web" / "node_modules").unlink()
    return rc


if __name__ == "__main__":
    sys.exit(main())
