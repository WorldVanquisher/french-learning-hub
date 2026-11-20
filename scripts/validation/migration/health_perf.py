#!/usr/bin/env python3
"""Health and performance of the daily read path on scratch databases (R3-061 to R3-068).

    python3 -I scripts/validation/migration/health_perf.py WORK [--sizes 0,600,2400] [--marked 30]
                                                                [--binary SERVER] [--label NAME] [--requests R] [--per-client C]

WORK must be absolute, outside the repository, and new or empty. Without --binary the server is built
from this tree into WORK/bin. For each size N, a fresh scratch database is seeded through the API only:
every authored listening script imported, every Speaking prompt at its maximum of typed takes, and N
Mistake Notebook records saved against cloned lessons (the clones are inserted into the scratch
database the way review_today/browser_perf.py does), of which only the first --marked (default 30) are
marked for retry. The queue therefore stays small while saved history grows, as in daily use.

Per size:
  endpoint     R (default 20) sequential GET /review-today and GET /mistake-notebook/items: items, bytes,
               median/p95/max ms (R3-061, R3-062).
  plans        EXPLAIN QUERY PLAN of the notebook queries on the read path. Each SQL text is checked to
               still occur in the Go source, so the plan is that of the shipped query (R3-063).
  concurrency  1, 4 and 8 clients (C requests each, default 10) reading Review Today at once, with and without a writer toggling a
               retry mark: p95 latency and any non-2xx (R3-064). The server is one process with one
               SQLite connection, used by one learner; 8 clients is the bound tested, not a promise.
  counters     five reads without writes give the same keys and history counts; a mark then an unmark
               returns them to the same values (R3-066).
On the smallest size only:
  errors       documented failures answer with a JSON {"error": …} that says what to do, and no body
               holds a path, a stack, a driver message or learner text (R3-067).
  busy         an outside connection holds SQLite's write lock (BEGIN IMMEDIATE): for 1.5 s (within the
               server's 5 s busy timeout) and for 6.5 s (beyond it). Records each request's status and
               time during the hold: a write, a read and /readyz (R3-068).
Writes WORK/health_perf.json. Exit 0 when every check passes, 1 otherwise, 2 when refused.
"""
import json
import os
import re
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "review_today"))
from load import call, ok  # noqa: E402
from rehearse import Server  # noqa: E402

# The read-path SQL, copied from the Go source and checked against it at run time.
PLANS = {
    "notebook ListSources": ("internal/storage/sqlite/notebook_repository.go",
                             "FROM learning_capture_sources s JOIN learning_captures c ON c.id = s.capture_row_id ORDER BY s.capture_row_id DESC",
                             "SELECT s.entry_id FROM learning_capture_sources s JOIN learning_captures c ON c.id = s.capture_row_id ORDER BY s.capture_row_id DESC"),
    "notebook CurrentMarks": ("internal/storage/sqlite/notebook_repository.go",
                              "WHERE m.id = (SELECT MAX(id) FROM mistake_retry_marks WHERE entry_id = m.entry_id)",
                              "SELECT m.entry_id, m.marked, m.created_at FROM mistake_retry_marks m WHERE m.id = (SELECT MAX(id) FROM mistake_retry_marks WHERE entry_id = m.entry_id)"),
    "notebook GetSourceByEntry": ("internal/storage/sqlite/notebook_repository.go",
                                  "FROM learning_capture_sources s JOIN learning_captures c ON c.id = s.capture_row_id WHERE s.entry_id = ?",
                                  "SELECT s.entry_id FROM learning_capture_sources s JOIN learning_captures c ON c.id = s.capture_row_id WHERE s.entry_id = 1"),
}

FAILED = []
PER_CLIENT = 10


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'} {name} {detail}".rstrip(), flush=True)
    if not cond:
        FAILED.append(name)
    return cond


def timed(base, method, path, body=None):
    t = time.perf_counter()
    s, raw = call(base, method, path, body)
    return s, raw, (time.perf_counter() - t) * 1000


def stats(lat):
    if not lat:
        return {"n": 0, "median_ms": None, "p95_ms": None, "max_ms": None}
    lat = sorted(lat)
    return {"n": len(lat), "median_ms": round(statistics.median(lat), 1), "p95_ms": round(lat[max(0, int(0.95 * len(lat)) - 1)], 1), "max_ms": round(lat[-1], 1)}


def seed(base, db, n, marked):
    t0 = time.time()
    scripts = ok(base, "GET", "/listening/scripts")["scripts"]
    for sc in scripts:
        ok(base, "POST", f"/listening/scripts/{sc['id']}")
    prompts = ok(base, "GET", "/speaking/prompts")
    takes = 0
    for p in prompts["prompts"]:
        view = ok(base, "POST", f"/speaking/prompts/{p['id']}")
        for k in range(prompts["limits"]["max_takes"]):
            take = ok(base, "POST", f"/speaking/exercises/{view['exercise']['id']}/takes", {"audio_source": "none"})["take_id"]
            ok(base, "POST", f"/speaking/takes/{take}/transcripts", {"text": f"Prise {k + 1} : je réponds à « {p['title']} »."})
            takes += 1
    con = sqlite3.connect(db, timeout=30)
    src = con.execute("""SELECT m.id, m.title, t.segments, e.content FROM listening_materials m
        JOIN listening_transcripts t ON t.material_id = m.id JOIN listening_exercises e ON e.transcript_id = t.id
        WHERE m.source_kind = 'authored_script' AND e.status = 'completed' ORDER BY m.id""").fetchall()
    records, k, entries = 0, 0, []
    while records < n:
        mid, title, segs, content = src[k % len(src)]
        now = "2026-11-19T08:00:00Z"
        with con:
            m2 = con.execute("INSERT INTO listening_materials (source_kind, pack_script_id, title, created_at) VALUES ('authored_script', ?, ?, ?)",
                             (f"flh_listening_script_pack_v1/ls-hp-{k:05d}", f"{title} (copie {k})", now)).lastrowid
            t2 = con.execute("INSERT INTO listening_transcripts (material_id, version, segments, has_timestamps, created_at) VALUES (?, 1, ?, 0, ?)", (m2, segs, now)).lastrowid
            e2 = con.execute("INSERT INTO listening_exercises (material_id, transcript_id, status, generator, content, created_at) VALUES (?, ?, 'completed', 'authored:flh_listening_script_pack_v1', ?, ?)",
                             (m2, t2, content, now)).lastrowid
        c = json.loads(content)
        for item in range(1, len(c.get("items", c.get("questions", []))) + 1):
            if records >= n:
                break
            doc = {"schema_version": "learning_capture_v1", "capture_id": f"hp-{k}-{item}", "source": "manual",
                   "original_input": f"Question {item} (copie {k}) : je me suis trompé.", "original_context": "Synthetic load test (cloned lesson)",
                   "source_ref": {"type": "listening_item", "record_id": e2, "item": item}}
            eid = ok(base, "POST", "/captures", doc)["entry_id"]
            entries.append(eid)
            if records < marked:
                ok(base, "PUT", f"/mistake-notebook/items/{eid}/retry", {"marked": True})
            records += 1
        k += 1
    con.close()
    return {"notebook_records": records, "marked": min(marked, records), "cloned_lessons": k, "speaking_takes": takes, "seed_s": round(time.time() - t0, 1)}, entries


def endpoint(base, path, r):
    lat, size, items = [], 0, 0
    for _ in range(r):
        s, raw, ms = timed(base, "GET", path)
        if s != 200:
            check(f"GET {path} answers 200", False, str(s))
            break
        lat.append(ms)
        size, items = len(raw), len(json.loads(raw)["items"])
    return {"items": items, "bytes": size, **stats(lat)}


def plans(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = {}
    for name, (go, needle, sql) in PLANS.items():
        shipped = needle in (REPO / go).read_text(encoding="utf-8")
        check(f"plan {name}: the SQL is the shipped one", shipped, go)
        out[name] = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql)]
    con.close()
    return out


def concurrency(base, entries, per_client=PER_CLIENT):
    res = {}
    for writer in (False, True):
        for k in (1, 4, 8):
            lat, bad, stop = [], [], threading.Event()

            def reader():
                for _ in range(per_client):
                    try:
                        s, _, ms = timed(base, "GET", "/review-today?zone=Europe/Paris")
                    except OSError as e:  # e.g. the 60 s client timeout
                        bad.append(f"no answer ({type(e).__name__})")
                        continue
                    lat.append(ms)
                    if s != 200:
                        bad.append(s)

            def write():
                i = 0
                while not stop.is_set():
                    try:
                        s, _, _ = timed(base, "PUT", f"/mistake-notebook/items/{entries[-1]}/retry", {"marked": i % 2 == 0})
                    except OSError as e:
                        bad.append(f"no answer ({type(e).__name__})")
                        s = 200
                    if s not in (200, 201):
                        bad.append(s)
                    i += 1

            ws = threading.Thread(target=write) if writer and entries else None
            if ws:
                ws.start()
            ts = [threading.Thread(target=reader) for _ in range(k)]
            t0 = time.perf_counter()
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            wall = (time.perf_counter() - t0) * 1000
            stop.set()
            if ws:
                ws.join()
            res[f"{k} readers{' + 1 writer' if writer else ''}"] = {**stats(lat), "wall_ms": round(wall), "non_2xx": bad}
            check(f"concurrency: {k} readers{' with a writer' if writer else ''}: every request 2xx", not bad, str(bad[:5]))
    if entries:
        ok(base, "PUT", f"/mistake-notebook/items/{entries[-1]}/retry", {"marked": False})
    return res


def counters(base, entries):
    def snap():
        d = ok(base, "GET", "/review-today?zone=Europe/Paris")
        return [i["key"] for i in d["items"]], d["history"]

    first = snap()
    same = all(snap() == first for _ in range(4))
    check("counters: five reads without a write give the same keys and history counts", same)
    if entries:
        ok(base, "PUT", f"/mistake-notebook/items/{entries[-1]}/retry", {"marked": True})
        mid = snap()
        ok(base, "PUT", f"/mistake-notebook/items/{entries[-1]}/retry", {"marked": False})
        back = snap()
        check("counters: a mark adds exactly that record to the queue", len(mid[0]) == len(first[0]) + 1 and f"notebook:entry:{entries[-1]}" in mid[0])
        check("counters: the unmark returns keys and counts to their earlier values", back == first)
    return {"queue": len(first[0]), "history": first[1]}


LEAK = re.compile(r"/home/|/tmp/|goroutine|panic|sqlite|SQL|\.go:\d+|database is locked|je me suis trompé", re.I)


def errors(base, entries):
    probes = [
        ("unknown record", "GET", "/entries/999999", None, 404),
        ("malformed JSON", "POST", "/captures", "{", 400),
        ("unknown time zone", "GET", "/review-today?zone=Mars/Olympus", None, 400),
        ("capture without input", "POST", "/captures", {"schema_version": "learning_capture_v1", "capture_id": "hp-bad", "source": "manual", "original_input": ""}, None),
        ("source item saved twice", "POST", "/captures", {"schema_version": "learning_capture_v1", "capture_id": "hp-dup", "source": "manual",
                                                          "original_input": "x", "source_ref": None}, None),
        ("unknown notebook record", "PUT", "/mistake-notebook/items/999999/retry", {"marked": True}, 404),
        ("extraction disabled", "POST", f"/entries/{entries[0] if entries else 1}/extractions", {}, 503),
        ("unknown route", "GET", "/no-such-route", None, 404),  # net/http's own plain-text 404: no JSON required
    ]
    out = []
    for name, m, path, body, want in probes:
        if name == "source item saved twice" and entries:
            src = ok(base, "GET", f"/mistake-notebook/items?skill=listening")["items"]
            ref = src[0]["source"] if src else None
            body = dict(body, source_ref={k: ref[k] for k in ("type", "record_id", "item")} if ref else None)
            want = 409
        data = body if isinstance(body, (dict, type(None))) else None
        if isinstance(body, str):
            import urllib.request
            req = urllib.request.Request(base + path, data=body.encode(), method=m, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    s, raw = r.status, r.read()
            except urllib.error.HTTPError as e:
                s, raw = e.code, e.read()
        else:
            s, raw = call(base, m, path, data)
        try:
            j = json.loads(raw)
        except ValueError:
            j = None
        msg = (j or {}).get("error") if isinstance(j, dict) else None
        text = raw.decode("utf-8", "replace")
        good = (isinstance(msg, str) and len(msg) >= 12 or (name == "unknown route" and text.strip() != "")) and not LEAK.search(text)
        status_ok = (want is None and 400 <= s < 500) or s == want
        check(f"error '{name}': {s} with an actionable JSON message and no leak", good and status_ok, f"{s} {msg!r}")
        out.append({"probe": name, "status": s, "error": msg, "code": (j or {}).get("code") if isinstance(j, dict) else None})
    return out


def busy(base, db, entries):
    out = {}
    for hold in (1.5, 6.5):
        con = sqlite3.connect(db, timeout=1, isolation_level=None)
        con.execute("BEGIN IMMEDIATE")
        res = {}

        def req(name, m, path, body=None):
            s, raw, ms = timed(base, m, path, body)
            try:
                msg = json.loads(raw).get("error") if raw else None
            except (ValueError, AttributeError):
                msg = None
            # a successful read carries learner text by design: only error bodies are checked for leaks
            res[name] = {"status": s, "ms": round(ms), "error": msg, "leak": s >= 400 and bool(LEAK.search(raw.decode("utf-8", "replace")))}

        ts = [threading.Thread(target=req, args=("write (retry mark)", "PUT", f"/mistake-notebook/items/{entries[0]}/retry", {"marked": True})),
              threading.Thread(target=req, args=("read (review today)", "GET", "/review-today?zone=Europe/Paris")),
              threading.Thread(target=req, args=("readyz", "GET", "/readyz"))]
        t0 = time.perf_counter()
        for i, t in enumerate(ts):
            t.start()
            time.sleep(0.05)
        time.sleep(max(0, hold - (time.perf_counter() - t0)))
        con.execute("ROLLBACK")
        con.close()
        for t in ts:
            t.join()
        out[f"lock held {hold} s"] = res
        w = res["write (retry mark)"]
        if hold < 5:
            check(f"busy {hold} s: the write waits for the lock and succeeds", w["status"] in (200, 201) and w["ms"] >= (hold - 0.2) * 1000, json.dumps(w))
        else:
            check(f"busy {hold} s: the write fails after the busy timeout with a non-leaking 5xx message", w["status"] >= 500 and not w["leak"] and bool(w["error"]), json.dumps(w))
        check(f"busy {hold} s: every request answered, none hangs", all(r["status"] for r in res.values()), json.dumps(res))
    ok(base, "PUT", f"/mistake-notebook/items/{entries[0]}/retry", {"marked": True})
    return out


def main():
    args = sys.argv[1:]
    opts = {"--sizes": "0,600,2400", "--marked": "30", "--binary": None, "--label": "current", "--requests": "20", "--per-client": "10"}
    for k in list(opts):
        if k in args:
            i = args.index(k)
            opts[k] = args[i + 1]
            args = args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isabs(args[0]):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    work = Path(os.path.realpath(args[0]))
    if work == REPO or REPO in work.parents or (work.exists() and any(work.iterdir())):
        print("refused: WORK must be outside the repository and new or empty", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    binary = Path(opts["--binary"]) if opts["--binary"] else work / "bin" / "server"
    if not opts["--binary"]:
        subprocess.run(["go", "build", "-trimpath", "-o", str(binary), "./cmd/server"], cwd=REPO, env=dict(os.environ, GOFLAGS="-buildvcs=false"), check=True)
    sizes = [int(x) for x in opts["--sizes"].split(",")]
    global PER_CLIENT
    PER_CLIENT = int(opts["--per-client"])
    r = int(opts["--requests"])
    result = {"label": opts["--label"], "marked": int(opts["--marked"]), "sizes": {}}
    for idx, n in enumerate(sizes):
        d = work / f"n{n}"
        db = d / "app.db"
        srv = Server(binary, db, d)
        try:
            if not check(f"n={n}: server ready", srv.ok):
                continue
            wl, entries = seed(srv.url, db, n, int(opts["--marked"]))
            print(f"n={n}: seeded {json.dumps(wl)}", flush=True)
            row = {"workload": wl,
                   "review_today": endpoint(srv.url, "/review-today?zone=Europe/Paris", r),
                   "notebook_list": endpoint(srv.url, "/mistake-notebook/items", max(3, r // 4)),
                   "plans": plans(db),
                   "counters": counters(srv.url, entries),
                   "concurrency": concurrency(srv.url, entries)}
            if idx == 0:
                row["errors"] = errors(srv.url, entries)
                if entries:
                    row["busy"] = busy(srv.url, str(db), entries)
            rt = row["review_today"]
            print(f"n={n}: review-today {rt['items']} items {rt['bytes']} B median {rt['median_ms']} ms p95 {rt['p95_ms']} ms; "
                  f"notebook list {row['notebook_list']['items']} items median {row['notebook_list']['median_ms']} ms", flush=True)
            result["sizes"][str(n)] = row
        finally:
            srv.stop()
    (work / "health_perf.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(f"{'PASS' if not FAILED else 'FAIL'}: {len(FAILED)} failed check(s)")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
