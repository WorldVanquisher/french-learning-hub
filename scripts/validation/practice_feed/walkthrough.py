#!/usr/bin/env python3
"""The practice prototype in real Chromium on the SEALED Extraction 2.1 fixtures (walkthrough.mjs).

    python3 -I scripts/validation/practice_feed/walkthrough.py WORK_DIR --handoff H [--tree TREE] [--combos a,b] [--script measure.mjs]

WORK_DIR must be absolute, outside the repository, and new or empty. H is the extraction lane's
sealed handoff directory (handoff-2.1).

Before anything is built, the fixtures are checked (exit 2, nothing run, when they fail):
H/SHA256SUMS and the bundle's SHA256SUMS must verify, the sealed code must reproduce the lane's
outputs, and web/src/prototype/extractionPracticeFixture.ts must equal a fresh rebuild from H
(build_fixture.py --handoff H --check). The page then re-hashes every document again.

Runs the real web typecheck (npm run typecheck, tsc -b; exit 2 when it fails), then builds the
server (go build -trimpath) and the workbench (vite build) from TREE (default: this
tree) into WORK_DIR, then per combination starts the server on a fresh empty WORK_DIR database
(127.0.0.1, a free port, empty environment, every provider disabled, no .env) and runs
walkthrough.mjs in a disposable node:22-bookworm-slim container (--rm, host network; Playwright
1.49.1 from the volume flh-listening-workbook-pw), reduced motion emulated and the clipboard
granted. Combinations: desktop-en 1280x900; phone320-en and phone320-zh 320x640 (touch);
zoom200-en 640x450 at device scale 2 (1280 px at 200 %); largetext-en with a 32 px default font.
The last two run the first part only. Nothing is added to the database or stored.
Writes WORK_DIR/results.json, trace-<combo>.json, counts-<combo>.json, shots/<combo>/*.png,
fixture-check.out and logs. --script measure.mjs runs measure.mjs instead (interactions from
Review Today to the first graded answer, per path; use --tree to measure an older tree). Every server it started is stopped. Exit status is the browser's
(0 all PASS), 2 when refused.
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
ALL = {
    "desktop-en": {"locale": "en", "phone": False},
    "phone320-en": {"locale": "en", "phone": True},
    "phone320-zh": {"locale": "zh-CN", "phone": True},
    "zoom200-en": {"locale": "en", "phone": False, "zoom": True},
    "largetext-en": {"locale": "en", "phone": False, "largeText": True},
}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def forbidden_strings() -> list:
    text = (REPO / "web/src/prototype/extractionPracticeFixture.ts").read_text(encoding="utf-8")
    marker = "export const FIXTURE_DOCUMENTS: readonly FixtureDocument[] = "
    docs = json.loads(text[text.index(marker) + len(marker):].rstrip().rstrip(";"))
    cases = json.loads(next(d["text"] for d in docs if d["name"] == "cases.json"))
    return cases["cases"]["study-packet-without-answers"]["expect"]["forbidden_strings"]


def main():
    args = sys.argv[1:]
    opts = {}
    for flag in ("--handoff", "--tree", "--combos", "--script"):
        if flag in args:
            i = args.index(flag)
            opts[flag] = args[i + 1]
            args = args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isabs(args[0]) or "--handoff" not in opts:
        print("usage: walkthrough.py /abs/new/empty/dir --handoff HANDOFF_2_1 [--tree TREE] [--combos a,b]", file=sys.stderr)
        return 2
    work = Path(os.path.realpath(args[0]))
    tree = Path(os.path.realpath(opts.get("--tree", str(REPO))))
    combos = opts.get("--combos", ",".join(ALL)).split(",")
    if opts.get("--script", "walkthrough.mjs") not in ("walkthrough.mjs", "measure.mjs"):
        print("--script is walkthrough.mjs or measure.mjs", file=sys.stderr)
        return 2
    if any(c not in ALL for c in combos):
        print(f"unknown combination; choose from {', '.join(ALL)}", file=sys.stderr)
        return 2
    if work == REPO or REPO in work.parents:
        print("refused: WORK_DIR must be outside the repository", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        print("refused: WORK_DIR must be new or empty", file=sys.stderr)
        return 2
    # The fixtures first: a missing or altered checksum stops the run before anything is built.
    chk = subprocess.run([sys.executable, "-I", "-B", str(REPO / "scripts/validation/extraction_practice/build_fixture.py"), "--handoff", opts["--handoff"], "--check"],
                         capture_output=True, text=True)
    (work / "fixture-check.out").write_text(chk.stdout + chk.stderr)
    if chk.returncode != 0:
        print(f"refused: the sealed fixtures do not check out (build_fixture.py exit {chk.returncode}):\n{(chk.stdout + chk.stderr)[-600:]}", file=sys.stderr)
        return 2
    print(chk.stdout.strip().splitlines()[-1])
    # The real web typecheck (tsc -b) first: vite build alone does not check types.
    tc = subprocess.run(["npm", "run", "--silent", "typecheck"], cwd=tree / "web", capture_output=True, text=True)
    (work / "typecheck.out").write_text(tc.stdout + tc.stderr + f"exit {tc.returncode}\n")
    if tc.returncode != 0:
        print(f"refused: npm run typecheck failed in {tree / 'web'} (exit {tc.returncode})", file=sys.stderr)
        return 2
    server = work / "bin" / "server"
    dist = work / "web-dist"
    env_build = dict(os.environ, GOFLAGS="-buildvcs=false")
    subprocess.run(["go", "build", "-trimpath", "-o", str(server), "./cmd/server"], cwd=tree, env=env_build, check=True)
    subprocess.run(["npx", "vite", "build", "--outDir", str(dist), "--emptyOutDir"], cwd=tree / "web", check=True, stdout=subprocess.DEVNULL)
    procs, run = [], []
    rc = 1
    try:
        for tag in combos:
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
            run.append({"tag": tag, "url": url, **ALL[tag]})
        uid, gid = os.getuid(), os.getgid()
        cmd = ["docker", "run", "--rm", "--network", "host",
               "-v", f"{HERE / opts.get('--script', 'walkthrough.mjs')}:/src/walk.mjs:ro", "-v", f"{tree / 'web/src/i18n'}:/i18n:ro",
               "-v", f"{work}:/out", "-v", "flh-listening-workbook-pw:/opt/pw",
               "-e", "PLAYWRIGHT_BROWSERS_PATH=/opt/pw/browsers", "-e", f"COMBOS={json.dumps(run)}", "-e", "OUT=/out",
               "-e", f"FORBIDDEN={json.dumps(forbidden_strings())}",
               "-w", "/opt/pw", "node:22-bookworm-slim", "bash", "-c",
               "set -e; cp /src/walk.mjs /opt/pw/practice_feed_walk.mjs; "
               "[ -d node_modules/playwright ] || npm i --no-audit --no-fund --silent playwright@1.49.1 >/dev/null; "
               "npx playwright install --with-deps chromium > /tmp/install.log 2>&1 || { tail -20 /tmp/install.log; exit 1; }; "
               "rc=0; node practice_feed_walk.mjs || rc=$?; "
               f"chown -R {uid}:{gid} /out 2>/dev/null; exit $rc"]
        rc = subprocess.run(cmd, timeout=1800).returncode
    finally:
        for proc, log in procs:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=20)
            log.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
