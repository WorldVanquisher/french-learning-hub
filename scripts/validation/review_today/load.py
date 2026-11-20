#!/usr/bin/env python3
"""Measure GET /review-today on a larger synthetic workload.

    python3 -I scripts/validation/review_today/load.py WORK_DIR [REQUESTS]

WORK_DIR must be absolute, outside the repository, and new or empty. Builds
the server from this tree into WORK_DIR and runs it on a fresh WORK_DIR
database (127.0.0.1, a free port, empty environment, every provider
disabled). Through the API only, it creates the largest workload the
authored packs allow: every listening script imported, every one of their
questions saved as a Mistake Notebook record and marked for retry, and every
Speaking prompt started with the maximum number of typed takes, each with a
confirmed transcript. Then it times REQUESTS (default 30) sequential reads of
/review-today, /learning-week and the history export preview, and reports
item counts, response sizes and latency (median, p95, max). Synthetic text
only; no provider is called. Writes WORK_DIR/load.json.
"""
import json
import os
import signal
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(base, method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def ok(base, method, path, body=None, statuses=(200, 201)):
    s, raw = call(base, method, path, body)
    if s not in statuses:
        raise SystemExit(f"{method} {path}: {s} {raw[:300]!r}")
    return json.loads(raw or b"null")


def main():
    if len(sys.argv) not in (2, 3) or not os.path.isabs(sys.argv[1]):
        print("usage: load.py /abs/new/empty/dir [REQUESTS]", file=sys.stderr)
        return 2
    work = Path(os.path.realpath(sys.argv[1]))
    n = int(sys.argv[2]) if len(sys.argv) == 3 else 30
    if work == REPO or REPO in work.parents:
        print("refused: WORK_DIR must be outside the repository", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        print("refused: WORK_DIR must be new or empty", file=sys.stderr)
        return 2
    binary = work / "bin" / "server"
    subprocess.run(["go", "build", "-trimpath", "-o", str(binary), "./cmd/server"], cwd=REPO, env=dict(os.environ, GOFLAGS="-buildvcs=false"), check=True)
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {"PATH": "/usr/bin:/bin", "HOME": str(work), "LISTEN_HOST": "127.0.0.1", "PORT": str(port), "DB_PATH": str(work / "app.db"),
           "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "disabled", "SPEAKING_PROVIDER": "disabled",
           "SPEAKING_TRANSCRIPTION_PROVIDER": "disabled", "LISTENING_PROVIDER": "disabled"}
    log = open(work / "server.log", "ab")
    proc = subprocess.Popen([str(binary)], cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
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
            ex = lesson["current_exercise_id"]
            for item in range(1, sc["questions"] + 1):
                doc = {"schema_version": "learning_capture_v1", "capture_id": f"load-{sc['id']}-{item}", "source": "manual",
                       "original_input": f"Question {item} de {sc['title']} : je me suis trompé.", "original_context": "Synthetic load test",
                       "source_ref": {"type": "listening_item", "record_id": ex, "item": item}}
                entry = ok(base, "POST", "/captures", doc)["entry_id"]
                ok(base, "PUT", f"/mistake-notebook/items/{entry}/retry", {"marked": True})
                records += 1
        prompts = ok(base, "GET", "/speaking/prompts")
        max_takes = prompts["limits"]["max_takes"]
        takes = 0
        for p in prompts["prompts"]:
            view = ok(base, "POST", f"/speaking/prompts/{p['id']}")
            for k in range(max_takes):
                take = ok(base, "POST", f"/speaking/exercises/{view['exercise']['id']}/takes", {"audio_source": "none"})["take_id"]
                ok(base, "POST", f"/speaking/takes/{take}/transcripts", {"text": f"Prise {k + 1} : Bonjour, je réponds à « {p['title']} »."})
                takes += 1
        seed_s = time.time() - t0

        def measure(path):
            lat, size, body = [], 0, None
            for _ in range(n):
                t = time.perf_counter()
                s, raw = call(base, "GET", path)
                lat.append((time.perf_counter() - t) * 1000)
                if s != 200:
                    raise SystemExit(f"GET {path}: {s}")
                size, body = len(raw), raw
            lat.sort()
            return {"path": path, "requests": n, "bytes": size, "median_ms": round(statistics.median(lat), 1),
                    "p95_ms": round(lat[max(0, int(0.95 * n) - 1)], 1), "max_ms": round(lat[-1], 1)}, json.loads(body)

        today, rt = measure("/review-today?zone=Europe/Paris")
        today["items"] = len(rt["items"])
        today["by_source"] = {s: sum(1 for it in rt["items"] if it["source"] == s) for s in ("speaking", "notebook")}
        week, _ = measure("/learning-week?zone=Europe/Paris")
        export, _ = measure("/learning-history/export-preview")
        out = {"workload": {"notebook_records_marked": records, "speaking_takes": takes, "speaking_exercises": len(prompts["prompts"]), "seed_seconds": round(seed_s, 1)},
               "review_today": today, "learning_week": week, "export_preview": export}
        (work / "load.json").write_text(json.dumps(out, indent=1))
        print(json.dumps(out, indent=1))
        return 0
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=20)
        log.close()


if __name__ == "__main__":
    sys.exit(main())
