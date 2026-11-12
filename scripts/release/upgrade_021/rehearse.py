#!/usr/bin/env python3
"""Rehearse the 020 -> 021 upgrade and its rollback on disposable databases.

    python3 -I scripts/release/upgrade_021/rehearse.py WORK_DIR \
        [--fixture-db PATH] [--old-server BINARY] [--keep-going]

WORK_DIR must be absolute, outside the repository, and new or empty. Everything
the rehearsal writes stays in it: the built server, every database copy, the
backup, logs and summary.txt. The repository, its .env, DB_PATH and the daily
instance are never read or written: each server runs with an empty environment
plus explicit settings, from a working directory inside WORK_DIR (so no .env is
loaded), bound to 127.0.0.1 on a free port.

Stages (each one line in WORK_DIR/summary.txt: STAGE<TAB>PASS|FAIL|NOT RUN<TAB>detail):

  build      go build of the current server (it embeds 001-021).
  populate   Without --fixture-db: a fresh database written through the real
             HTTP API by the current server: captures, YouTube listening
             lessons with transcripts, exercises prepared through a LOCAL fake
             Responses endpoint (no real provider or key), a failed
             preparation, an authored reading import, Notebook records linked
             to listening and reading items, a retry mark, a writing draft and
             a submitted mock exam. The listening_materials AUTOINCREMENT
             counter is then raised by 5 to prove 021 keeps a high-water mark
             above max(id) (the app itself never deletes materials).
  fixture    The populated database converted to the exact 020 shape (the 014
             listening_materials table, 021 removed from the ledger), and its
             whole schema compared with a pristine database built by applying
             only 001-020. With --fixture-db: a COPY of that file (for example
             a validated private backup), required to be at exactly 020.
  backup     The RELEASE.md Backup block (copy app.db and sidecars into a
             mode-700 directory, integrity_check must be exactly "ok",
             SHA256SUMS), with the service stop/start replaced by this harness.
  upgrade    The current server started on the active copy applies 021.
             Every table other than listening_materials is byte-identical,
             listening_materials keeps every id/link/title/timestamp as
             source_kind youtube, sqlite_sequence is unchanged, integrity is
             ok and foreign_key_check is empty.
  notebook   GET /mistake-notebook/items and the listening lesson list after
             the upgrade equal what the same server showed before the
             conversion (populated mode); with --fixture-db, every listening
             Notebook item must still resolve.
  scripts    GET /listening/scripts, import (201, new id above the kept
             counter, no link or video id), replay (200 + Idempotency-Replayed,
             nothing written), learner transcript on the script (409
             authored_script), a Notebook record from the script's authored
             item (201, replay 200, second record for the item 409), retry
             toggle on an old listening record.
  conflict   On a separate copy whose imported script title was altered:
             import is 409 script_conflict and writes nothing.
  rollback   The RELEASE.md Restore block from the pre-upgrade backup at the
             same path (checksums, integrity, rename, old directory kept).
             The restored database is byte-identical to the backup and its
             logical state equals the pre-upgrade state (ledger ends at 020).
  old-server With --old-server: that binary (built by the owner from the
             commit before 021) starts on the restored database, is ready,
             serves the listening and Notebook reads, and records no new
             migration. Without it: NOT RUN (owner verification).
  reupgrade  The current server upgrades the restored database again and the
             script import works there too.

Exit status: 0 when every stage that ran passed (old-server may be NOT RUN);
1 when a stage failed; 2 for a refused invocation.
"""

import argparse
import hashlib
import http.server
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MIGRATIONS = REPO / "migrations"
UPGRADE = "021_listening_authored_scripts.sql"
PREVIOUS = "020_mock_exams.sql"
FAKE_KEY = "local-fake-key-not-a-credential"

# One transcript the fake exercise below is grounded in (segments 1 and 2).
LINE1 = "Bonjour à tous, la bibliothèque du quartier ouvre lundi."
LINE2 = "Pour s'inscrire, apportez un justificatif de domicile."
FAKE_OUTPUT = json.dumps({
    "items": [
        {"kind": "main_idea", "question": "De quoi parle-t-on ?", "expected_answer": "D'une bibliothèque qui ouvre.",
         "rationale_en": "Segment 1.", "rationale_zh": "第1段。", "segments": [1]},
        {"kind": "detail", "question": "Que faut-il apporter ?", "expected_answer": "Un justificatif de domicile.",
         "rationale_en": "Segment 2.", "rationale_zh": "第2段。", "segments": [2]},
    ],
    "annotations": [{"kind": "vocabulary", "segment": 2, "excerpt": "justificatif de domicile",
                     "note_en": "proof of address", "note_zh": "住址证明"}],
}, ensure_ascii=False)


class Failed(Exception):
    pass


# --- summary ------------------------------------------------------------------

class Summary:
    def __init__(self, path):
        self.path = path
        self.failed = False
        path.write_text("")

    def stage(self, name, status, detail=""):
        if status == "FAIL":
            self.failed = True
        line = f"{name}\t{status}\t{detail}"
        print(line, flush=True)
        with self.path.open("a") as fh:
            fh.write(line + "\n")


def check(cond, message):
    if not cond:
        raise Failed(message)


# --- SQLite helpers (read-only except where named) ----------------------------

def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def migration_names(before=None):
    names = sorted(p.name for p in MIGRATIONS.glob("*.sql"))
    return [n for n in names if before is None or n < before]


def build_pristine(path):
    """Apply 001-020 exactly as the runner does: one transaction per file plus
    its ledger row, foreign keys on."""
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("PRAGMA foreign_keys = ON")
    # The runner's exact statement text (internal/storage/sqlite/db.go), so the
    # stored schema compares equal.
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (\n\t\tname       TEXT PRIMARY KEY,\n"
               "\t\tapplied_at TEXT NOT NULL DEFAULT (datetime('now'))\n\t)")
    for name in migration_names(before=UPGRADE[:3]):
        sql = (MIGRATIONS / name).read_text()
        db.executescript("BEGIN;\n" + sql + "\n;INSERT INTO schema_migrations (name) VALUES ('" + name + "');\nCOMMIT;")
    db.close()


def schema(path):
    with ro(path) as db:
        return sorted(db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name <> 'sqlite_sequence' "
                                 "AND name NOT LIKE 'sqlite_stat%' ORDER BY type, name").fetchall())


def table_digest(db, table):
    h = hashlib.sha256()
    n = 0
    for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
        h.update(json.dumps([[type(v).__name__, v.hex() if isinstance(v, bytes) else v] for v in row],
                            ensure_ascii=False).encode())
        n += 1
    return n, h.hexdigest()


def state(path):
    """Logical state of a database: ledger, schema, every table's row count and
    content digest, sqlite_sequence, integrity and foreign-key checks."""
    with ro(path) as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                           "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        out = {
            "ledger": [r[0] for r in db.execute("SELECT name FROM schema_migrations ORDER BY name")],
            "integrity": [r[0] for r in db.execute("PRAGMA integrity_check")],
            "foreign_key_check": [list(r) for r in db.execute("PRAGMA foreign_key_check")],
            "sequence": dict(db.execute("SELECT name, seq FROM sqlite_sequence ORDER BY name").fetchall()),
            "tables": {},
        }
        for t in tables:
            if t == "schema_migrations":
                continue
            n, digest = table_digest(db, t)
            out["tables"][t] = {"rows": n, "sha256": digest}
        cols = [r[1] for r in db.execute("PRAGMA table_info(listening_materials)")]
        proj = hashlib.sha256()
        rows = db.execute("SELECT id, video_id, source_url, title, created_at FROM listening_materials ORDER BY id").fetchall()
        for r in rows:
            proj.update(json.dumps(list(r), ensure_ascii=False).encode())
        out["materials"] = {"columns": cols, "projection_sha256": proj.hexdigest(), "rows": len(rows),
                            "max_id": max([r[0] for r in rows], default=0)}
        if "source_kind" in cols:
            out["materials"]["kinds"] = dict(db.execute(
                "SELECT source_kind || ':' || (pack_script_id IS NULL), COUNT(*) FROM listening_materials GROUP BY 1").fetchall())
    out["schema"] = [list(r) for r in schema(path)]
    return out


def compare_upgrade(pre, post):
    problems = []
    if pre["ledger"] + [UPGRADE] != post["ledger"]:
        problems.append(f"ledger {pre['ledger'][-1:]} -> {post['ledger'][-2:]}")
    for label, s in (("pre", pre), ("post", post)):
        if s["integrity"] != ["ok"]:
            problems.append(f"{label} integrity {s['integrity'][:3]}")
        if s["foreign_key_check"]:
            problems.append(f"{label} foreign_key_check {s['foreign_key_check'][:3]}")
    if pre["sequence"] != post["sequence"]:
        problems.append(f"sqlite_sequence {pre['sequence']} -> {post['sequence']}")
    if set(pre["tables"]) != set(post["tables"]):
        problems.append(f"tables differ: {sorted(set(pre['tables']) ^ set(post['tables']))}")
    for t in pre["tables"]:
        if t == "listening_materials" or t not in post["tables"]:
            continue
        if pre["tables"][t] != post["tables"][t]:
            problems.append(f"{t} changed {pre['tables'][t]} -> {post['tables'][t]}")
    pm, qm = pre["materials"], post["materials"]
    if (pm["rows"], pm["projection_sha256"]) != (qm["rows"], qm["projection_sha256"]):
        problems.append("listening_materials ids/links/titles/timestamps changed")
    if qm["rows"] and qm.get("kinds") != {"youtube:1": qm["rows"]}:
        problems.append(f"listening_materials kinds after 021: {qm.get('kinds')}")
    pre_objs = {(o[0], o[1]): o for o in pre["schema"] if o[2] != "listening_materials"}
    post_objs = {(o[0], o[1]): o for o in post["schema"] if o[2] != "listening_materials"}
    if pre_objs != post_objs:
        problems.append(f"schema objects outside listening_materials changed: {sorted(set(pre_objs) ^ set(post_objs))[:5]}")
    return problems


def compare_identical(a, b):
    return [k for k in ("ledger", "integrity", "foreign_key_check", "sequence", "tables", "materials", "schema")
            if a[k] != b[k]]


def copy_db(src, dst):
    """Copy a database and its present sidecars by content only (mode 600), so
    a read-only source never makes the working copy read-only."""
    for suffix in ("", "-wal", "-shm"):
        s, d = Path(str(src) + suffix), Path(str(dst) + suffix)
        if s.exists():
            shutil.copyfile(s, d)
            os.chmod(d, 0o600)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def downgrade_to_020(path, pristine):
    """Convert a database the current server populated (at 021, YouTube rows
    only) to the exact 020 shape: the 014 listening_materials table with the
    same ids and AUTOINCREMENT counter, and no 021 ledger row."""
    with ro(pristine) as p:
        objects = p.execute("SELECT type, name, sql FROM sqlite_master WHERE tbl_name = 'listening_materials' "
                            "AND sql IS NOT NULL ORDER BY type DESC, name").fetchall()
    create_table = [o[2] for o in objects if o[0] == "table"]
    check(len(create_table) == 1, "pristine 020 database has no single listening_materials table")
    db = sqlite3.connect(path, isolation_level=None)
    try:
        check(db.execute("SELECT COUNT(*) FROM schema_migrations WHERE name = ?", (UPGRADE,)).fetchone()[0] == 1,
              "populated database is not at 021")
        check(db.execute("SELECT COUNT(*) FROM listening_materials WHERE source_kind <> 'youtube'").fetchone()[0] == 0,
              "populated database holds authored scripts, which 020 cannot represent")
        db.execute("PRAGMA foreign_keys = ON")
        script = ["BEGIN;", "PRAGMA defer_foreign_keys = ON;",
                  "CREATE TEMP TABLE m020 AS SELECT id, video_id, source_url, title, created_at FROM listening_materials;",
                  "CREATE TEMP TABLE s020 AS SELECT seq FROM sqlite_sequence WHERE name = 'listening_materials';",
                  "DROP TABLE listening_materials;",
                  create_table[0] + ";"]
        script += [o[2] + ";" for o in objects if o[0] != "table"]
        script += ["INSERT INTO listening_materials (id, video_id, source_url, title, created_at) "
                   "SELECT id, video_id, source_url, title, created_at FROM m020 ORDER BY id;",
                   "DELETE FROM sqlite_sequence WHERE name = 'listening_materials';",
                   "INSERT INTO sqlite_sequence (name, seq) SELECT 'listening_materials', seq FROM s020;",
                   f"DELETE FROM schema_migrations WHERE name = '{UPGRADE}';",
                   "DROP TABLE m020;", "DROP TABLE s020;", "COMMIT;"]
        db.executescript("\n".join(script))
        db.execute("VACUUM")
    finally:
        db.close()


# --- processes ----------------------------------------------------------------

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


class Server:
    """One server process owned by this harness: an empty environment plus
    explicit settings, providers disabled unless named, loopback only."""

    BASE_ENV = {
        "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "disabled", "SUGGESTION_PROVIDER": "disabled",
        "LISTENING_PROVIDER": "disabled", "READING_PROVIDER": "disabled", "WRITING_PROVIDER": "disabled",
        "SPEAKING_PROVIDER": "disabled", "SPEAKING_TRANSCRIPTION_PROVIDER": "disabled",
        "EMBEDDING_PROVIDER": "disabled", "SEMANTIC_SEARCH": "disabled", "LISTENING_PLAYLIST_SOURCE": "disabled",
        "LISTENING_AUTO_PREPARE": "disabled", "LISTENING_NOTIFY": "disabled",
    }

    def __init__(self, binary, db_path, run_dir, log_path, extra=None):
        self.binary, self.db_path, self.run_dir, self.log_path = binary, db_path, run_dir, log_path
        self.extra = extra or {}
        self.proc = None
        self.port = None

    def __enter__(self):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        check(not (self.run_dir / ".env").exists(), f"{self.run_dir} holds a .env")
        self.port = free_port()
        check(not port_open(self.port), f"port {self.port} is already in use")
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.run_dir), "LISTEN_HOST": "127.0.0.1",
               "PORT": str(self.port), "DB_PATH": str(self.db_path)}
        env.update(self.BASE_ENV)
        env.update(self.extra)
        self.log = open(self.log_path, "ab")
        self.proc = subprocess.Popen([str(self.binary)], cwd=self.run_dir, env=env, stdout=self.log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        try:
            deadline = time.time() + 30
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    raise Failed(f"server exited with {self.proc.returncode}; see logs/{self.log_path.name}")
                try:
                    status, _, _ = call("GET", self.url("/readyz"))
                    if status == 200 and self.proc.poll() is None:
                        return self
                except OSError:
                    pass
                time.sleep(0.2)
            raise Failed("server not ready within 30 s")
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.log.close()
        return False


def call(method, url, body=None, headers=None):
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw, status, rh = resp.read(), resp.status, resp.headers
    except urllib.error.HTTPError as e:
        raw, status, rh = e.read(), e.code, e.headers
    try:
        payload = json.loads(raw) if raw else None
    except ValueError:
        payload = raw.decode(errors="replace")
    return status, rh, payload


def expect(server, method, path, status, body=None, headers=None):
    got, rh, payload = call(method, server.url(path), body, headers)
    check(got == status, f"{method} {path}: HTTP {got}, want {status}: {str(payload)[:300]}")
    return rh, payload


class FakeResponses:
    """Loopback stand-in for the OpenAI Responses API: answers every POST
    /v1/responses with FAKE_OUTPUT (or a 500 when told to fail)."""

    def __init__(self):
        outer = self
        self.calls = 0
        self.fail = False

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.calls += 1
                if self.path != "/v1/responses" or self.headers.get("Authorization") != f"Bearer {FAKE_KEY}":
                    self.send_response(404)
                    self.end_headers()
                    return
                if outer.fail:
                    body = b'{"error":{"message":"fake failure"}}'
                    self.send_response(500)
                else:
                    body = json.dumps({"status": "completed", "output": [{"type": "message", "content": [
                        {"type": "output_text", "text": FAKE_OUTPUT}]}]}).encode()
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# --- stages -------------------------------------------------------------------

def capture(capture_id, text, source_ref=None):
    doc = {"schema_version": "learning_capture_v1", "capture_id": capture_id, "source": "manual",
           "original_input": text, "original_context": "upgrade rehearsal fixture (synthetic)",
           "discussion_summary": "synthetic record written by the 020 -> 021 rehearsal"}
    if source_ref:
        doc["source_ref"] = source_ref
    return doc


def populate(work, server_bin, db_path):
    fake = FakeResponses()
    facts = {}
    try:
        extra = {"LISTENING_PROVIDER": "openai", "OPENAI_API_KEY": FAKE_KEY, "OPENAI_MODEL": "fake-model",
                 "OPENAI_BASE_URL": f"http://127.0.0.1:{fake.port}/v1", "OPENAI_TIMEOUT": "10s"}
        with Server(server_bin, db_path, work / "run" / "populate", work / "logs" / "populate.log", extra) as s:
            for f in ("chatgpt-example.json", "manual-example.json"):
                expect(s, "POST", "/captures", 201, json.loads((REPO / "examples" / "captures" / f).read_text()))
            _, a = expect(s, "POST", "/listening/materials", 201, {
                "source_url": "https://www.youtube.com/watch?v=FLHrehears1", "title": "Répétition A",
                "transcript": f"{LINE1}\n{LINE2}"})
            _, b = expect(s, "POST", "/listening/materials", 201, {
                "source_url": "https://youtu.be/FLHrehears2", "title": "Répétition B (horodatée)",
                "transcript": f"[00:05] {LINE1}\n[00:12] {LINE2}"})
            _, c = expect(s, "POST", "/listening/materials", 201, {
                "source_url": "https://youtu.be/FLHrehears3", "title": "Répétition C (sans transcription)"})
            mid = {k: v["material"]["id"] for k, v in (("a", a), ("b", b), ("c", c))}
            _, prep_a = expect(s, "POST", f"/listening/materials/{mid['a']}/exercises", 201, {},
                               {"Idempotency-Key": str(uuid.uuid4())})
            _, prep_b = expect(s, "POST", f"/listening/materials/{mid['b']}/exercises", 201, {},
                               {"Idempotency-Key": str(uuid.uuid4())})
            calls = fake.calls
            _, nt = expect(s, "POST", f"/listening/materials/{mid['c']}/exercises", 409, {},
                           {"Idempotency-Key": str(uuid.uuid4())})
            check(nt.get("code") == "no_transcript" and fake.calls == calls, "no_transcript must not call the provider")
            fake.fail = True
            got, _, failed = call("POST", s.url(f"/listening/materials/{mid['b']}/exercises"), {},
                                  {"Idempotency-Key": str(uuid.uuid4())})
            fake.fail = False
            check(got == 502, f"failed preparation: HTTP {got}, want 502")
            ex_a, ex_b = prep_a["exercise"]["id"], prep_b["exercise"]["id"]
            _, examples = expect(s, "GET", "/reading/examples", 200)
            rid = examples["examples"][0]["id"]
            _, lesson = expect(s, "POST", f"/reading/examples/{rid}", 201)
            lesson_id = lesson["lesson"]["id"]
            _, lesson = expect(s, "GET", f"/reading/lessons/{lesson_id}", 200)
            reading_ex = lesson["exercises"][0]["id"]
            _, n1 = expect(s, "POST", "/captures", 201, capture("rehearsal-listening-a1", "bibliothèque",
                           {"type": "listening_item", "record_id": ex_a, "item": 1, "attempt": "Une bibliothèque."}))
            expect(s, "POST", "/captures", 201, capture("rehearsal-listening-b2", "justificatif",
                   {"type": "listening_item", "record_id": ex_b, "item": 2}))
            expect(s, "POST", "/captures", 201, capture("rehearsal-reading-1", "lecture",
                   {"type": "reading_item", "record_id": reading_ex, "item": 1, "attempt": "Je ne sais pas."}))
            entry_a1 = n1["entry_id"]
            expect(s, "PUT", f"/mistake-notebook/items/{entry_a1}/retry", 200, {"marked": True})
            expect(s, "POST", f"/listening/materials/{mid['a']}/transcripts", 201,
                   {"transcript": f"{LINE1}\n{LINE2}\nÀ lundi !"})
            _, prompts = expect(s, "GET", "/writing/prompts", 200)
            _, task = expect(s, "POST", f"/writing/prompts/{prompts['prompts'][0]['id']}", 201)
            task_id = task["task"]["id"]
            expect(s, "POST", f"/writing/tasks/{task_id}/drafts", 201,
                   {"text": "Bonjour, je vous écris pour vous demander des renseignements."})
            _, forms = expect(s, "GET", "/exam/forms", 200)
            _, sess = expect(s, "POST", "/exam/sessions", 201, {"form_id": forms["forms"][0]["id"]},
                             {"Idempotency-Key": str(uuid.uuid4())})
            n = len(sess["questions"])
            expect(s, "POST", f"/exam/sessions/{sess['session']['id']}/submit", 200,
                   {"answers": {str(i): None for i in range(1, n + 1)}})
            _, notebook = expect(s, "GET", "/mistake-notebook/items", 200)
            _, materials = expect(s, "GET", "/listening/materials", 200)
            facts = {"materials": mid, "listening_exercises": [ex_a, ex_b], "reading_exercise": reading_ex,
                     "notebook_entry_listening": entry_a1, "provider_calls": fake.calls,
                     "failed_preparation_state": failed.get("preparation", {}).get("state")}
            (work / "evidence" / "before_notebook.json").write_text(json.dumps(notebook, ensure_ascii=False, indent=1))
            (work / "evidence" / "before_materials.json").write_text(json.dumps(materials, ensure_ascii=False, indent=1))
    finally:
        fake.close()
    db = sqlite3.connect(db_path, isolation_level=None)
    db.execute("UPDATE sqlite_sequence SET seq = seq + 5 WHERE name = 'listening_materials'")
    db.close()
    return facts


def run_backup(active, backups):
    """The RELEASE.md Backup block, verbatim apart from the compose stop/start
    (this harness owns the stopped server)."""
    script = r'''
set -e
umask 077
active="$1"
backup="$2/flh-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$2"
chmod 700 "$2"
mkdir -m 700 "$backup"                     # fails if already present
cp -a "$active/app.db" "$backup/app.db"
for suffix in -wal -shm; do
  if [ -e "$active/app.db$suffix" ]; then
    cp -a "$active/app.db$suffix" "$backup/"
  fi
done
integrity=$(sqlite3 -readonly "$backup/app.db" 'PRAGMA integrity_check;')
[ "$integrity" = ok ] || { echo 'Backup integrity check failed' >&2; exit 1; }
(cd "$backup" && sha256sum app.db* > SHA256SUMS)
printf '%s\n' "$backup"
'''
    out = subprocess.run(["bash", "-c", script, "backup", str(active), str(backups)], capture_output=True, text=True)
    check(out.returncode == 0, f"backup block failed: {out.stderr.strip()[:300]}")
    return Path(out.stdout.strip().splitlines()[-1])


def run_restore(active, backup):
    """The RELEASE.md Restore block, verbatim apart from the compose stop/up."""
    script = r'''
set -e
umask 077
active="$1"
backup="$2"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
stage="$active.restore-$stamp"
old="$active.before-restore-$stamp"
test ! -e "$old"
mkdir -m 700 "$stage"
(cd "$backup" && sha256sum -c SHA256SUMS)
cp -a "$backup/app.db" "$stage/app.db"
for suffix in -wal -shm; do
  if [ -e "$backup/app.db$suffix" ]; then
    cp -a "$backup/app.db$suffix" "$stage/"
  fi
done
integrity=$(sqlite3 -readonly "$stage/app.db" 'PRAGMA integrity_check;')
[ "$integrity" = ok ] || { echo 'Restore integrity check failed' >&2; exit 1; }
mv "$active" "$old"
mv "$stage" "$active"
printf '%s\n' "$old"
'''
    out = subprocess.run(["bash", "-c", script, "restore", str(active), str(backup)], capture_output=True, text=True)
    check(out.returncode == 0, f"restore block failed: {out.stderr.strip()[:300]}")
    return Path(out.stdout.strip().splitlines()[-1])


def strip_volatile_materials(doc):
    return doc.get("materials") if isinstance(doc, dict) else doc


def script_checks(s, db_path, pre_seq, old_listening_entry):
    _, scripts = expect(s, "GET", "/listening/scripts", 200)
    check(scripts["scripts"], "the embedded pack lists no script")
    sc = scripts["scripts"][0]
    check(sc.get("imported_material_id") is None, "script reported as imported before any import")
    _, lesson = expect(s, "POST", f"/listening/scripts/{sc['id']}", 201)
    m = lesson["material"]
    check(m["id"] > pre_seq, f"new material id {m['id']} reuses an id at or below the kept counter {pre_seq}")
    check(not m.get("video_id") and not m.get("source_url"), "an authored script carries a video id or link")
    with ro(db_path) as db:
        before = [db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("listening_materials", "listening_transcripts", "listening_exercises")]
    rh, again = expect(s, "POST", f"/listening/scripts/{sc['id']}", 200)
    check(rh.get("Idempotency-Replayed") == "true", "replay lacks Idempotency-Replayed: true")
    check(again["material"]["id"] == m["id"], "replay returned another material")
    with ro(db_path) as db:
        after = [db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("listening_materials", "listening_transcripts", "listening_exercises")]
    check(before == after, f"replay wrote rows {before} -> {after}")
    _, conflict = expect(s, "POST", f"/listening/materials/{m['id']}/transcripts", 409, {"transcript": "Bonjour."})
    check(conflict.get("code") == "authored_script", f"learner transcript on a script: {conflict}")
    ex = lesson["exercises"][0]["id"]
    doc = capture("rehearsal-script-item-1", "script item", {"type": "listening_item", "record_id": ex, "item": 1})
    _, saved = expect(s, "POST", "/captures", 201, doc)
    expect(s, "POST", "/captures", 200, doc)
    _, dup = expect(s, "POST", "/captures", 409, capture("rehearsal-script-item-1b", "again",
                    {"type": "listening_item", "record_id": ex, "item": 1}))
    check(dup.get("code") == "source_already_saved" and dup.get("entry_id") == saved["entry_id"],
          f"second record for the same item: {dup}")
    _, nb = expect(s, "GET", "/mistake-notebook/items?skill=listening", 200)
    marked = [i["retry"]["marked"] for i in nb["items"] if i["entry_id"] == old_listening_entry]
    check(marked, f"old listening record {old_listening_entry} is not in the Notebook")
    _, toggled = expect(s, "PUT", f"/mistake-notebook/items/{old_listening_entry}/retry", 200,
                        {"marked": not marked[0]})
    check(toggled.get("changed") is True, "retry toggle on an old listening record did not change")
    _, nb = expect(s, "GET", "/mistake-notebook/items?skill=listening", 200)
    statuses = sorted((i["source"]["record_id"], i["source"]["item"], i["source_status"]) for i in nb["items"])
    check(all(st == "resolved" for _, _, st in statuses), f"listening Notebook items not resolved: {statuses}")
    return sc["id"], m["id"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("work")
    ap.add_argument("--fixture-db", help="a COPY of a private 020 database (read-only source)")
    ap.add_argument("--old-server", help="server binary built from the commit before 021")
    ap.add_argument("--keep-going", action="store_true", help="continue after a failed stage where possible")
    args = ap.parse_args()

    work = Path(args.work)
    if not work.is_absolute():
        print("refused: WORK_DIR must be absolute", file=sys.stderr)
        return 2
    work = Path(os.path.realpath(work))
    if work == REPO or REPO in work.parents:
        print("refused: WORK_DIR must be outside the repository", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        print("refused: WORK_DIR must be new or empty", file=sys.stderr)
        return 2
    for tool in ("go", "sqlite3", "sha256sum", "bash"):
        if not shutil.which(tool):
            print(f"refused: {tool} is required", file=sys.stderr)
            return 2
    os.umask(0o077)
    for d in ("bin", "logs", "evidence", "run", "dbs"):
        (work / d).mkdir()
    summary = Summary(work / "summary.txt")
    server_bin = work / "bin" / "server"

    def stage(name, fn):
        try:
            detail = fn() or ""
            summary.stage(name, "PASS", detail)
            return True
        except Failed as e:
            summary.stage(name, "FAIL", str(e))
            return False

    def build():
        out = subprocess.run(["go", "build", "-o", str(server_bin), "./cmd/server"], cwd=REPO,
                             capture_output=True, text=True)
        check(out.returncode == 0, out.stderr.strip()[:300])
        return f"server sha256 {sha256_file(server_bin)[:16]}…"

    if not stage("build", build):
        return 1

    pristine = work / "dbs" / "pristine-020.db"
    fixture = work / "dbs" / "fixture-020.db"
    facts = {}

    def do_populate():
        populated = work / "dbs" / "populated-021.db"
        facts.update(populate(work, server_bin, populated))
        (work / "evidence" / "populate_facts.json").write_text(json.dumps(facts, indent=1))
        copy_db(populated, fixture)
        return (f"{len(facts['materials'])} YouTube lessons, exercises {facts['listening_exercises']}, "
                f"{facts['provider_calls']} calls to the local fake only, failed attempt state "
                f"{facts['failed_preparation_state']}")

    def do_fixture():
        build_pristine(pristine)
        if args.fixture_db:
            src = Path(args.fixture_db)
            check(src.is_file(), "--fixture-db is not a file")
            copy_db(src, fixture)
        else:
            downgrade_to_020(fixture, pristine)
        st = state(fixture)
        check(st["ledger"] == migration_names(before=UPGRADE[:3]), f"fixture ledger ends at {st['ledger'][-1:]}")
        check(st["integrity"] == ["ok"] and not st["foreign_key_check"], "fixture integrity/foreign keys")
        if not args.fixture_db:
            check([list(r) for r in schema(fixture)] == [list(r) for r in schema(pristine)],
                  "converted fixture schema differs from a pristine 001-020 database")
        rows = {t: v["rows"] for t, v in st["tables"].items() if v["rows"]}
        (work / "evidence" / "fixture_rows.json").write_text(json.dumps(rows, indent=1))
        return (f"ledger ends {st['ledger'][-1]}; schema == pristine 001-020; "
                f"{sum(rows.values())} rows in {len(rows)} tables; listening_materials seq "
                f"{st['sequence'].get('listening_materials')} > max id {st['materials']['max_id']}")

    if not args.fixture_db:
        if not stage("populate", do_populate):
            return 1
    else:
        summary.stage("populate", "NOT RUN", "--fixture-db given")
    if not stage("fixture", do_fixture):
        return 1

    inst = work / "instance"
    inst.mkdir(mode=0o700)
    active = inst / "data"
    active.mkdir(mode=0o700)
    copy_db(fixture, active / "app.db")
    backups = inst / "backups"
    ctx = {}

    def do_backup():
        ctx["backup"] = run_backup(active, backups)
        ctx["pre"] = state(active / "app.db")
        (work / "evidence" / "pre_state.json").write_text(json.dumps(ctx["pre"], indent=1, ensure_ascii=False))
        mode = oct(ctx["backup"].stat().st_mode & 0o777)
        return f"{ctx['backup'].name} mode {mode}; integrity ok; SHA256SUMS written"

    if not stage("backup", do_backup):
        return 1

    def upgraded_server():
        return Server(server_bin, active / "app.db", work / "run" / "upgrade", work / "logs" / "upgrade.log")

    def do_upgrade_and_checks():
        with upgraded_server() as s:
            post = state(active / "app.db")
            (work / "evidence" / "post_state.json").write_text(json.dumps(post, indent=1, ensure_ascii=False))
            problems = compare_upgrade(ctx["pre"], post)
            check(not problems, "; ".join(problems))
            summary.stage("upgrade", "PASS",
                          f"021 applied once; {len(post['tables']) - 1} other tables byte-identical; "
                          f"{post['materials']['rows']} materials kept as youtube; sqlite_sequence unchanged; "
                          "integrity ok; foreign_key_check empty")
            try:
                _, nb = expect(s, "GET", "/mistake-notebook/items", 200)
                _, mats = expect(s, "GET", "/listening/materials", 200)
                (work / "evidence" / "after_notebook.json").write_text(json.dumps(nb, ensure_ascii=False, indent=1))
                if args.fixture_db:
                    bad = [i["entry_id"] for i in nb["items"]
                           if i["source"]["type"] == "listening_item" and i["source_status"] != "resolved"]
                    check(not bad, f"listening Notebook items not resolved after 021: {bad}")
                    detail = f"{len(nb['items'])} items; every listening item resolved"
                else:
                    before_nb = json.loads((work / "evidence" / "before_notebook.json").read_text())
                    before_m = json.loads((work / "evidence" / "before_materials.json").read_text())
                    check(nb == before_nb, "Notebook items differ from the pre-conversion view")
                    check(strip_volatile_materials(mats) == strip_volatile_materials(before_m),
                          "listening lesson list differs from the pre-conversion view")
                    linked = sorted({i["source"]["type"] for i in nb["items"]})
                    detail = (f"{len(nb['items'])} items identical to the pre-upgrade view ({', '.join(linked)}); "
                              "lesson list identical")
                summary.stage("notebook", "PASS", detail)
            except Failed as e:
                summary.stage("notebook", "FAIL", str(e))
            try:
                entry = facts.get("notebook_entry_listening")
                if entry is None:
                    _, nb = expect(s, "GET", "/mistake-notebook/items?skill=listening", 200)
                    entry = nb["items"][0]["entry_id"] if nb["items"] else None
                pre_seq = ctx["pre"]["sequence"].get("listening_materials", 0)
                script_id, mat = script_checks(s, active / "app.db", pre_seq, entry) if entry else (None, None)
                check(script_id, "no listening Notebook record to toggle")
                ctx["script"] = (script_id, mat)
                summary.stage("scripts", "PASS",
                              f"import {script_id} -> material {mat} (> kept counter {pre_seq}); replay 200 + header, "
                              "no rows; learner transcript 409 authored_script; Notebook record 201/200/409 "
                              "source_already_saved; retry toggle on an old listening record")
            except Failed as e:
                summary.stage("scripts", "FAIL", str(e))
            after_writes = state(active / "app.db")
            check(after_writes["integrity"] == ["ok"] and not after_writes["foreign_key_check"],
                  "integrity/foreign keys after the post-upgrade writes")

    try:
        do_upgrade_and_checks()
    except Failed as e:
        summary.stage("upgrade", "FAIL", str(e))
        if not args.keep_going:
            return 1

    def do_conflict():
        check("script" in ctx, "no imported script to alter")
        cdir = work / "dbs" / "conflict"
        cdir.mkdir()
        copy_db(active / "app.db", cdir / "app.db")
        db = sqlite3.connect(cdir / "app.db", isolation_level=None)
        db.execute("UPDATE listening_materials SET title = title || ' (altered)' WHERE id = ?", (ctx["script"][1],))
        db.close()
        before = state(cdir / "app.db")["tables"]
        with Server(server_bin, cdir / "app.db", work / "run" / "conflict", work / "logs" / "conflict.log") as s:
            _, body = expect(s, "POST", f"/listening/scripts/{ctx['script'][0]}", 409)
            check(body.get("code") == "script_conflict", f"conflict body {body}")
        after = state(cdir / "app.db")["tables"]
        check(before == after, "the conflicting import wrote rows")
        return "altered copy: 409 script_conflict, nothing written"

    stage("conflict", do_conflict)

    def do_rollback():
        old = run_restore(active, ctx["backup"])
        restored = active / "app.db"
        check(sha256_file(restored) == sha256_file(ctx["backup"] / "app.db"), "restored file differs from the backup")
        st = state(restored)
        diff = compare_identical(ctx["pre"], st)
        check(not diff, f"restored state differs in {diff}")
        check(UPGRADE not in st["ledger"], "restored ledger still records 021")
        check(old.is_dir() and (old / "app.db").exists(), "upgraded directory not preserved")
        ctx["old_dir"] = old
        return f"sha256 equals the backup; logical state equals pre-upgrade (ledger ends 020); kept {old.name}"

    rolled = stage("rollback", do_rollback)

    def do_old_server():
        binary = Path(args.old_server).resolve()
        check(binary.is_file() and os.access(binary, os.X_OK), "--old-server is not an executable file")
        copy = work / "dbs" / "old-server"
        copy.mkdir()
        copy_db(active / "app.db", copy / "app.db")
        with Server(binary, copy / "app.db", work / "run" / "old", work / "logs" / "old-server.log") as s:
            expect(s, "GET", "/listening/materials", 200)
            expect(s, "GET", "/mistake-notebook/items", 200)
        st = state(copy / "app.db")
        check(st["ledger"] == ctx["pre"]["ledger"], f"old server changed the ledger to end {st['ledger'][-1:]}")
        return "older binary ready on a copy of the restored database; reads 200; ledger unchanged"

    if not rolled:
        summary.stage("old-server", "NOT RUN", "rollback failed")
    elif args.old_server:
        stage("old-server", do_old_server)
    else:
        summary.stage("old-server", "NOT RUN",
                      "owner verification: rerun with --old-server built from the commit before 021")

    def do_reupgrade():
        with Server(server_bin, active / "app.db", work / "run" / "reupgrade", work / "logs" / "reupgrade.log") as s:
            post = state(active / "app.db")
            problems = compare_upgrade(ctx["pre"], post)
            check(not problems, "; ".join(problems))
            if "script" in ctx:
                expect(s, "POST", f"/listening/scripts/{ctx['script'][0]}", 201)
        return "restored database upgrades again; script import 201"

    if rolled:
        stage("reupgrade", do_reupgrade)
    return 1 if summary.failed else 0


if __name__ == "__main__":
    sys.exit(main())
