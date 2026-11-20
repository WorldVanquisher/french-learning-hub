#!/usr/bin/env python3
"""Open older fixtures with the current server: Review Today, the learning
week and the history export must work on them, including after an upgrade
that was interrupted.

    python3 -I scripts/validation/compat/older_fixtures.py WORK_DIR FIXTURE_DB [FIXTURE_DB ...]

WORK_DIR must be absolute, outside the repository, and new or empty. Each
FIXTURE_DB is only read (copied with its -wal sidecar into WORK_DIR, mode
600); its SHA-256 is checked unchanged at the end. The server is built from
this tree into WORK_DIR and runs on 127.0.0.1, a free port, an empty
environment and every provider disabled.

Per fixture:
  open        start on a copy; the ledger may gain 021 (a 020 fixture) and
              nothing else; integrity_check is ok;
  reads       GET /review-today?zone=Europe/Paris, /learning-week,
              /speaking/practice, /mistake-notebook/items: 200, and every
              Review Today notebook item resolves or says why not;
  export      export-preview, then the NDJSON export checked by
              import-preview on the same server: complete, 0 new, 0 conflicts;
  schedule    the spaced-practice prototype over the fixture's records (read
              from that export): every input gets a due day and a rule;
  interrupted (fixtures whose ledger ends before 021) for each delay in
              DELAYS: a fresh copy, the server started and killed (SIGKILL)
              after the delay, then started again: the ledger ends at 021
              exactly once, integrity ok, and the export round trip holds.
Writes WORK_DIR/results.json and prints one PASS/FAIL line per check.
Exit 0 when every check passes, 1 otherwise, 2 when refused.
"""
import hashlib
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DELAYS = (0.0, 0.02, 0.08, 0.3)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def ledger(db):
    con = sqlite3.connect(db, timeout=10)
    try:
        rows = [r[0] for r in con.execute("SELECT name FROM schema_migrations ORDER BY name")]
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    return rows, ok


def call(base, method, path, body=None, raw=False):
    data = body if isinstance(body, bytes) else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            b = r.read()
            return r.status, (b if raw else json.loads(b or b"null"))
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Server:
    def __init__(self, binary, d, db):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        env = {"PATH": "/usr/bin:/bin", "HOME": str(d), "LISTEN_HOST": "127.0.0.1", "PORT": str(self.port), "DB_PATH": str(db),
               "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "disabled", "SPEAKING_PROVIDER": "disabled",
               "SPEAKING_TRANSCRIPTION_PROVIDER": "disabled", "LISTENING_PROVIDER": "disabled", "WRITING_PROVIDER": "disabled",
               "READING_PROVIDER": "disabled"}
        self.log = open(d / "server.log", "ab")
        self.proc = subprocess.Popen([str(binary)], cwd=d, env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)

    def ready(self, seconds=30):
        end = time.time() + seconds
        while time.time() < end:
            if self.proc.poll() is not None:
                return False
            try:
                if urllib.request.urlopen(self.url + "/readyz", timeout=2).status == 200:
                    return True
            except OSError:
                time.sleep(0.1)
        return False

    def stop(self, sig=signal.SIGTERM):
        if self.proc.poll() is None:
            self.proc.send_signal(sig)
        self.proc.wait(timeout=20)
        self.log.close()


def copy_fixture(src, d):
    d.mkdir(parents=True)
    db = d / "app.db"
    shutil.copyfile(src, db)
    for side in ("-wal",):
        if os.path.exists(src + side):
            shutil.copyfile(src + side, str(db) + side)
    os.chmod(db, 0o600)
    return db


def reads_and_export(base, check, label):
    s, today = call(base, "GET", "/review-today?zone=Europe/Paris")
    ok = s == 200 and today.get("zone") == "Europe/Paris"
    bad = [it["key"] for it in (today.get("items", []) if ok else []) if it["source"] == "notebook" and it["notebook"]["source_status"] not in ("resolved", "missing", "unusable")]
    check(f"{label}: Review Today reads ({len(today.get('items', [])) if ok else '?'} items) and every notebook item resolves or says why", ok and not bad, {"status": s, "bad": bad})
    for path in ("/learning-week?zone=Europe/Paris", "/speaking/practice", "/mistake-notebook/items"):
        s, _ = call(base, "GET", path)
        check(f"{label}: GET {path} answers 200", s == 200, s)
    s, prev = call(base, "GET", "/learning-history/export-preview?transcripts=true&notes=true")
    check(f"{label}: export preview", s == 200 and prev["header"]["format"] == "learning_history_export_v1", s)
    s, body = call(base, "GET", "/learning-history/export?transcripts=true&notes=true", raw=True)
    s2, p = call(base, "POST", "/learning-history/import-preview", body=body)
    check(f"{label}: export round trip is complete with 0 new and 0 conflicts ({p.get('same') if s2 == 200 else '?'} records)",
          s == 200 and s2 == 200 and p["integrity"] == "complete" and p["new"] == 0 and p["conflicts"] == 0, p if s2 == 200 else s2)
    return body


def main():
    if len(sys.argv) < 3 or not os.path.isabs(sys.argv[1]):
        print("usage: older_fixtures.py /abs/new/empty/dir FIXTURE_DB [FIXTURE_DB ...]", file=sys.stderr)
        return 2
    work = Path(os.path.realpath(sys.argv[1]))
    if work == REPO or REPO in work.parents:
        print("refused: WORK_DIR must be outside the repository", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        print("refused: WORK_DIR must be new or empty", file=sys.stderr)
        return 2
    fixtures = [os.path.realpath(f) for f in sys.argv[2:]]
    for f in fixtures:
        if not os.path.isfile(f) or REPO in Path(f).parents:
            print(f"refused: {f} is not a fixture file outside the repository", file=sys.stderr)
            return 2
    before = {f: sha(f) for f in fixtures}
    binary = work / "bin" / "server"
    subprocess.run(["go", "build", "-trimpath", "-o", str(binary), "./cmd/server"], cwd=REPO, env=dict(os.environ, GOFLAGS="-buildvcs=false"), check=True)
    results = []

    def check(name, ok, detail=""):
        results.append({"name": name, "pass": bool(ok), "detail": detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)[:400]})

    for i, f in enumerate(fixtures):
        label = f"fixture {i + 1} ({Path(f).name})"
        d = work / f"f{i + 1}"
        db = copy_fixture(f, d / "open")
        start, _ = ledger(db)
        srv = Server(binary, d / "open", db)
        try:
            check(f"{label}: the current server starts on a copy", srv.ready(), start[-1] if start else "")
            exported = reads_and_export(srv.url, check, label)
        finally:
            srv.stop()
        # The scheduling prototype over this fixture's own records (via its export).
        (d / "export.ndjson").write_bytes(exported)
        env = dict(os.environ, GOFLAGS="-buildvcs=false", FLH_SCHEDULE_EXPORT=str(d / "export.ndjson"))
        t = subprocess.run(["go", "test", "-count=1", "-run", "TestScheduleInputsFromExport_File", "-v", "./internal/application/"], cwd=REPO, env=env, capture_output=True, text=True)
        (d / "schedule.txt").write_text(t.stdout + t.stderr)
        inputs = [l.strip() for l in t.stdout.splitlines() if " inputs from " in l]
        check(f"{label}: every scheduling input read from its records gets a due day and a rule ({inputs[0].split(': ', 1)[-1] if inputs else '?'})",
              t.returncode == 0 and "--- PASS: TestScheduleInputsFromExport_File" in t.stdout, t.stdout[-300:])
        after, ok = ledger(db)
        added = [v for v in after if v not in start]
        check(f"{label}: ledger {start[-1] if start else '?'} → {after[-1]}; only 021 may be added; integrity {ok}",
              ok == "ok" and set(added) <= {"021_listening_authored_scripts.sql"} and after[-1] == "021_listening_authored_scripts.sql", {"added": added})
        if start and start[-1] != "021_listening_authored_scripts.sql":
            for delay in DELAYS:
                dd = d / f"kill-{int(delay * 1000)}ms"
                db2 = copy_fixture(f, dd)
                srv = Server(binary, dd, db2)
                time.sleep(delay)
                srv.stop(signal.SIGKILL)
                mid, ok_mid = ledger(db2)
                srv = Server(binary, dd, db2)
                try:
                    up = srv.ready()
                    if up:
                        reads_and_export(srv.url, lambda n, o, det="": check(n, o, det) if not o else None, f"{label} killed after {int(delay * 1000)} ms")
                finally:
                    srv.stop()
                fin, ok_fin = ledger(db2)
                check(f"{label}: killed after {int(delay * 1000)} ms at ledger {mid[-1]}, restarted: ledger ends at 021 once, integrity {ok_fin}, reads and export round trip hold",
                      up and ok_mid == "ok" and ok_fin == "ok" and fin.count("021_listening_authored_scripts.sql") == 1 and fin[-1] == "021_listening_authored_scripts.sql",
                      {"mid": mid[-1], "final": fin[-1]})
    for f in fixtures:
        check(f"{Path(f).name}: the fixture itself is unchanged", sha(f) == before[f])
    (work / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    failed = [r for r in results if not r["pass"]]
    print(f"{len(results) - len(failed)}/{len(results)} PASS")
    for r in results:
        print("PASS" if r["pass"] else "FAIL", r["name"], "" if r["pass"] else r["detail"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
