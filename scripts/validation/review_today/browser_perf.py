#!/usr/bin/env python3
"""Review Today at a larger synthetic scale: endpoint latency, payload size, page rendering and
repeated navigation, in real Chromium.

    python3 -I scripts/validation/review_today/browser_perf.py WORK_DIR [--extra N] [--requests R] [--cycles C]

WORK_DIR must be absolute, outside the repository, and new or empty. Runs `npm run typecheck`,
builds the server and the workbench from this tree, starts the server on a fresh WORK_DIR
database (127.0.0.1, empty environment, providers disabled) and seeds it through the API only:
the load.py workload (every authored script question saved and marked for retry, every Speaking
prompt at its maximum of typed takes) plus N (default 600) further notebook records marked for
retry, saved through the API against cloned lessons (see below). That is larger than the earlier
123-item run. Then:
  endpoint   R (default 30) sequential GET /review-today: size, median, p95, max;
  browser    perf.mjs in a disposable node:22-bookworm-slim container (Playwright 1.49.1):
             per load, the request's own duration and size (Resource Timing) apart from the
             time to render the queue after the response arrived; then C (default 15) cycles of
             leaving Review Today and coming back (with the practice panel opened and a concept
             entered once per cycle), counting /review-today requests per visit and the net
             window/document event listeners.
Writes WORK_DIR/perf.json and prints it. Exit 0 when the browser checks pass (one request per
visit; listeners return to their first-visit level), 1 otherwise, 2 when refused.
"""
import json
import os
import signal
import sqlite3
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.dont_write_bytecode = True  # never write __pycache__ into the repository
sys.path.insert(0, str(HERE))
from load import call, free_port, ok  # noqa: E402


def main():
    args = sys.argv[1:]
    opts = {"--extra": 600, "--requests": 30, "--cycles": 15}
    for k in list(opts):
        if k in args:
            i = args.index(k)
            opts[k] = int(args[i + 1])
            args = args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isabs(args[0]):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    work = Path(os.path.realpath(args[0]))
    if work == REPO or REPO in work.parents:
        print("refused: WORK_DIR must be outside the repository", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        print("refused: WORK_DIR must be new or empty", file=sys.stderr)
        return 2
    subprocess.run(["npm", "run", "--silent", "typecheck"], cwd=REPO / "web", check=True)
    binary, dist = work / "bin" / "server", work / "web-dist"
    subprocess.run(["go", "build", "-trimpath", "-o", str(binary), "./cmd/server"], cwd=REPO, env=dict(os.environ, GOFLAGS="-buildvcs=false"), check=True)
    subprocess.run(["npx", "vite", "build", "--outDir", str(dist), "--emptyOutDir"], cwd=REPO / "web", check=True, stdout=subprocess.DEVNULL)
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {"PATH": "/usr/bin:/bin", "HOME": str(work), "LISTEN_HOST": "127.0.0.1", "PORT": str(port), "DB_PATH": str(work / "app.db"),
           "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "disabled", "SPEAKING_PROVIDER": "disabled",
           "SPEAKING_TRANSCRIPTION_PROVIDER": "disabled", "LISTENING_PROVIDER": "disabled"}
    log = open(work / "server.log", "ab")
    proc = subprocess.Popen([str(binary), "-web-dir", str(dist)], cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        for _ in range(300):
            try:
                if urllib.request.urlopen(base + "/readyz", timeout=2).status == 200:
                    break
            except OSError:
                time.sleep(0.1)
        t0 = time.time()
        records = 0
        for sc in ok(base, "GET", "/listening/scripts")["scripts"]:
            lesson = ok(base, "POST", f"/listening/scripts/{sc['id']}")
            for item in range(1, sc["questions"] + 1):
                doc = {"schema_version": "learning_capture_v1", "capture_id": f"perf-{sc['id']}-{item}", "source": "manual",
                       "original_input": f"Question {item} de {sc['title']} : je me suis trompé.", "original_context": "Synthetic load test",
                       "source_ref": {"type": "listening_item", "record_id": lesson["current_exercise_id"], "item": item}}
                ok(base, "PUT", f"/mistake-notebook/items/{ok(base, 'POST', '/captures', doc)['entry_id']}/retry", {"marked": True})
                records += 1
        # More notebook records than the packs allow: a Mistake Notebook record must name a stored
        # item, and each item can be saved once. So the stored lessons are cloned in the scratch
        # database (the same rows the import wrote, under synthetic script IDs the pack does not
        # have, so their pack status reads "missing"), and records are saved against the clones
        # through the API, which validates every item as usual.
        clones = 0
        con = sqlite3.connect(work / "app.db", timeout=30)
        src = con.execute("""SELECT m.id, m.title, t.segments, e.content FROM listening_materials m
            JOIN listening_transcripts t ON t.material_id = m.id JOIN listening_exercises e ON e.transcript_id = t.id
            WHERE m.source_kind = 'authored_script' AND e.status = 'completed' ORDER BY m.id""").fetchall()
        made = []
        k = 0
        while records < 120 + opts["--extra"]:
            mid, title, segs, content = src[k % len(src)]
            now = "2026-11-19T08:00:00Z"
            with con:
                cur = con.execute("INSERT INTO listening_materials (source_kind, pack_script_id, title, created_at) VALUES ('authored_script', ?, ?, ?)",
                                  (f"flh_listening_script_pack_v1/ls-perf-{k:04d}", f"{title} (copie {k})", now))
                m2 = cur.lastrowid
                t2 = con.execute("INSERT INTO listening_transcripts (material_id, version, segments, has_timestamps, created_at) VALUES (?, 1, ?, 0, ?)", (m2, segs, now)).lastrowid
                e2 = con.execute("INSERT INTO listening_exercises (material_id, transcript_id, status, generator, content, created_at) VALUES (?, ?, 'completed', 'authored:flh_listening_script_pack_v1', ?, ?)",
                                 (m2, t2, content, now)).lastrowid
            n_items = len(json.loads(content).get("items", json.loads(content).get("questions", [])))
            for item in range(1, n_items + 1):
                if records >= 120 + opts["--extra"]:
                    break
                doc = {"schema_version": "learning_capture_v1", "capture_id": f"perf-clone-{k}-{item}", "source": "manual",
                       "original_input": f"Question {item} (copie {k}) : je me suis trompé.", "original_context": "Synthetic load test (cloned lesson)",
                       "source_ref": {"type": "listening_item", "record_id": e2, "item": item}}
                ok(base, "PUT", f"/mistake-notebook/items/{ok(base, 'POST', '/captures', doc)['entry_id']}/retry", {"marked": True})
                records += 1
            clones += 1
            k += 1
        con.close()
        prompts = ok(base, "GET", "/speaking/prompts")
        takes = 0
        for p in prompts["prompts"]:
            view = ok(base, "POST", f"/speaking/prompts/{p['id']}")
            for k in range(prompts["limits"]["max_takes"]):
                take = ok(base, "POST", f"/speaking/exercises/{view['exercise']['id']}/takes", {"audio_source": "none"})["take_id"]
                ok(base, "POST", f"/speaking/takes/{take}/transcripts", {"text": f"Prise {k + 1} : Bonjour, je réponds à « {p['title']} »."})
                takes += 1
        seed_s = time.time() - t0
        lat, size, items = [], 0, 0
        for _ in range(opts["--requests"]):
            t = time.perf_counter()
            s, raw = call(base, "GET", "/review-today?zone=Europe/Paris")
            lat.append((time.perf_counter() - t) * 1000)
            size, items = len(raw), len(json.loads(raw)["items"])
        lat.sort()
        endpoint = {"requests": len(lat), "items": items, "bytes": size, "median_ms": round(statistics.median(lat), 1),
                    "p95_ms": round(lat[max(0, int(0.95 * len(lat)) - 1)], 1), "max_ms": round(lat[-1], 1)}
        uid, gid = os.getuid(), os.getgid()
        cmd = ["docker", "run", "--rm", "--network", "host", "-v", f"{HERE / 'perf.mjs'}:/src/perf.mjs:ro", "-v", f"{work}:/out",
               "-v", "flh-listening-workbook-pw:/opt/pw", "-e", "PLAYWRIGHT_BROWSERS_PATH=/opt/pw/browsers", "-e", f"URL={base}",
               "-e", f"CYCLES={opts['--cycles']}", "-e", f"ITEMS={items}", "-w", "/opt/pw", "node:22-bookworm-slim", "bash", "-c",
               "set -e; cp /src/perf.mjs /opt/pw/review_today_perf.mjs; "
               "[ -d node_modules/playwright ] || npm i --no-audit --no-fund --silent playwright@1.49.1 >/dev/null; "
               "npx playwright install --with-deps chromium > /tmp/install.log 2>&1 || { tail -20 /tmp/install.log; exit 1; }; "
               f"rc=0; node review_today_perf.mjs || rc=$?; chown {uid}:{gid} /out/browser.json 2>/dev/null; exit $rc"]
        rc = subprocess.run(cmd, timeout=1200).returncode
        browser = json.loads((work / "browser.json").read_text()) if (work / "browser.json").exists() else None
        out = {"workload": {"notebook_records_marked": records, "cloned_lessons": clones, "speaking_takes": takes, "seed_seconds": round(seed_s, 1)}, "endpoint": endpoint, "browser": browser}
        (work / "perf.json").write_text(json.dumps(out, indent=1))
        print(json.dumps(out, indent=1))
        return rc
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=20)
        log.close()


if __name__ == "__main__":
    sys.exit(main())
