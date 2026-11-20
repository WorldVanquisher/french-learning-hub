#!/usr/bin/env python3
"""The workbench's private routes and the practice prototype stay out of a public-demo package.

    python3 -I scripts/validation/practice_feed/public_boundary.py WORK_DIR

WORK_DIR must be absolute, outside the repository, and new or empty. From this tree it builds
a public-demo package fixture (after `npm run typecheck`) the way scripts/demo/flh073/smoke.sh does: the server, the
synthetic FLH-073 artifact (mechanical vectors, local only), and the public-demo web build
(VITE_FLH_PUBLIC_DEMO=1). It also builds the workbench for comparison. Then:
  1. scans every file of the public build for markers of the private workbench and of the
     practice prototype (the same markers must be found in the workbench build: the scan works);
  2. starts the server in public-demo mode on 127.0.0.1 (empty environment, providers off) and
     requests every private route of this lane, at the root and under /api: GET must be 404,
     POST 405; the prototype's workbench chunks must be 404 under /assets/; the demo's own page,
     health and demo route must answer 200;
  3. stops the server it started.
Writes WORK_DIR/public-boundary.json and prints one line per check. Exit 0 when all pass,
1 otherwise, 2 when refused.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PRIVATE_ROUTES = [
    "/review-today", "/review-today?zone=UTC", "/learning-week", "/learning-history/export", "/learning-history/export-preview",
    "/listening/materials/1/revisions", "/listening/materials/1/revision-compare?from=1&to=2", "/listening/materials/1/restore?revision=1",
    "/notebook/items", "/listening/materials", "/speaking/exercises", "/exam/sessions", "/captures/x", "/entries",
]
MARKERS = ["flh_practice_review_feed_v1", "feedPractice", "pk-afdb387f3af6", "practice-start-", "flh_wb_practice_visit_export_v0",
           "/review-today", "today.heading", "learning-week", "learning-history/export"]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(url, method="GET"):
    req = urllib.request.Request(url, method=method, data=b"{}" if method == "POST" else None, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def scan(root: Path) -> dict:
    found = {m: [] for m in MARKERS}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            text = p.read_bytes().decode("utf-8", "ignore")
            for m in MARKERS:
                if m in text:
                    found[m].append(str(p.relative_to(root)))
    return found


def main():
    if len(sys.argv) != 2 or not os.path.isabs(sys.argv[1]):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    work = Path(os.path.realpath(sys.argv[1]))
    if work == REPO or REPO in work.parents:
        print("refused: WORK_DIR must be outside the repository", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        print("refused: WORK_DIR must be new or empty", file=sys.stderr)
        return 2
    subprocess.run(["npm", "run", "--silent", "typecheck"], cwd=REPO / "web", check=True)  # the real typecheck (tsc -b)
    env_build = dict(os.environ, GOFLAGS="-buildvcs=false")
    (work / "bin").mkdir()
    subprocess.run(["go", "build", "-trimpath", "-o", str(work / "bin/server"), "./cmd/server"], cwd=REPO, env=env_build, check=True)
    subprocess.run(["go", "build", "-trimpath", "-o", str(work / "bin/prepare"), "./scripts/demo/flh073/prepare"], cwd=REPO, env=env_build, check=True)
    with open(work / "prepare-build.json", "w") as out:
        subprocess.run([str(work / "bin/prepare"), "build", "-out", str(work / "artifact"), "-fixtures", "scripts/demo/flh073/fixtures/catalog.json"],
                       cwd=REPO, stdout=out, check=True)
    subprocess.run(["npx", "vite", "build", "--outDir", str(work / "demo-dist"), "--emptyOutDir"], cwd=REPO / "web", check=True,
                   env=dict(os.environ, VITE_FLH_PUBLIC_DEMO="1"), stdout=subprocess.DEVNULL)
    subprocess.run(["npx", "vite", "build", "--outDir", str(work / "web-dist"), "--emptyOutDir"], cwd=REPO / "web", check=True, stdout=subprocess.DEVNULL)
    checks = []

    def check(name, ok, detail=None):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})
        print("PASS" if ok else "FAIL", name, "" if ok else json.dumps(detail)[:400])

    demo, bench = scan(work / "demo-dist"), scan(work / "web-dist")
    check("the public build holds no private workbench or practice-prototype marker", all(not v for v in demo.values()), {k: v for k, v in demo.items() if v})
    check("the same markers are found in the workbench build (the scan works)", all(bench[m] for m in MARKERS), {k: len(v) for k, v in bench.items()})
    proto_chunks = sorted({f for m in ("flh_practice_review_feed_v1", "pk-afdb387f3af6") for f in bench[m] if f.startswith("assets/")})
    check("the prototype's fixture is its own lazily loaded workbench chunk", len(proto_chunks) >= 1, proto_chunks)

    port = free_port()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(work), "LISTEN_HOST": "127.0.0.1", "PORT": str(port)}
    log = open(work / "server.log", "ab")
    proc = subprocess.Popen([str(work / "bin/server"), "-public-demo-artifact", str(work / "artifact"), "-public-demo-allow-mechanical", "-web-dir", str(work / "demo-dist")],
                            cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(300):
            try:
                if urllib.request.urlopen(url + "/healthz", timeout=2).status == 200:
                    break
            except OSError:
                time.sleep(0.1)
        rows = []
        for prefix in ("", "/api"):
            for r in PRIVATE_ROUTES:
                g, _ = request(url + prefix + r)
                p, _ = request(url + prefix + r.split("?")[0], "POST")
                rows.append({"route": prefix + r, "get": g, "post": p})
        bad = [x for x in rows if x["get"] != 404 or x["post"] != 405]
        check(f"every private route is 404 for GET and 405 for POST in the public demo ({len(rows)} requests each)", not bad, bad)
        assets = [(c, request(url + "/" + c)[0]) for c in proto_chunks]
        check("the prototype's chunks are not served by the public demo", all(s == 404 for _, s in assets), assets)
        home, body = request(url + "/")
        check("the public demo page itself answers 200 and names none of the markers", home == 200 and not any(m.encode() in body for m in MARKERS), home)
        check("health and the demo route answer 200", request(url + "/healthz")[0] == 200 and request(url + "/knowledge-library/demo")[0] == 200)
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=20)
        log.close()
    (work / "public-boundary.json").write_text(json.dumps({"checks": checks, "public_build_files": len([p for p in (work / "demo-dist").rglob("*") if p.is_file()])}, indent=1))
    failed = [c for c in checks if not c["pass"]]
    print(f"{len(checks) - len(failed)}/{len(checks)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
