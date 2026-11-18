#!/usr/bin/env python3
"""FLH-152: rehearse upgrading a pre-revision database to the script-revision
build on disposable synthetic databases (see README.md in this directory).

    python3 -I scripts/validation/listening_workbook/upgrade_rehearsal.py \
        --old-server OLD_BIN --new-server NEW_BIN [--variant-server BIN] WORK_DIR

OLD_BIN: a server built from a commit before script revisions whose embedded
pack predates the 2026-11-11 evidence-audit corrections (c53b42c was used).
NEW_BIN: the build under test. VARIANT: the build under test with a synthetic
pack that only rotates the options of one question per script; without
--variant-server it is built from a copy of this repository's sources inside
WORK_DIR (go build -buildvcs=false), so the repository is never modified.

WORK_DIR must be absolute, outside the repository, and new or empty. Nothing
outside it is written. Each server runs with an empty environment plus
explicit settings, from a directory inside WORK_DIR (no .env), on 127.0.0.1.
Every provider is disabled except listening, which points at a loopback fake
Responses endpoint with a fake key: no real provider is ever contacted.

Stages (WORK_DIR/summary.tsv: STAGE<TAB>PASS|FAIL<TAB>detail; details in
WORK_DIR/evidence/):

  binaries  build info of the three servers; the migration ledger and schema a
            fresh database gets from the old and the new server.
  seed      old server: imports every script, saves mistakes on u05 questions 4
            and 2, prepares a YouTube lesson through the fake and saves a
            mistake on it.
  snapshot  the RELEASE.md Backup block; the backup is made read-only and
            described (checksums, row counts, ids) in snapshot-manifest.json.
  run-a     a copy of the snapshot is upgraded and exercised: checks numbered
            by FLH-152 item (5-14), see checks-run-a.json.
  restore   the RELEASE.md Restore block from the snapshot over run A's
            database; the restored file is byte-identical to the snapshot.
  run-b     the same flow on the restored database; every check and
            observation must equal run A's.
  untouched the snapshot still verifies against its SHA256SUMS.

Exit status: 0 when every stage passed, 1 otherwise, 2 for a refused call.
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
PACK = Path("internal/listening/pack/listening_scripts_v1.json")
FAKE_KEY = "local-fake-key-not-a-credential"
MAIN = "ls-wb1-u05"  # its question 4 (u05-l04) was corrected by the evidence audit

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


def check(cond, message):
    if not cond:
        raise Failed(message)


# --- SQLite (read-only) ---------------------------------------------------------

def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def table_digest(db, table):
    h = hashlib.sha256()
    n = 0
    for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
        h.update(json.dumps([[type(v).__name__, v.hex() if isinstance(v, bytes) else v] for v in row],
                            ensure_ascii=False).encode())
        n += 1
    return {"rows": n, "sha256": h.hexdigest()}


def state(path):
    with ro(path) as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                           "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {
            "ledger": [r[0] for r in db.execute("SELECT name FROM schema_migrations ORDER BY name")],
            "integrity": [r[0] for r in db.execute("PRAGMA integrity_check")],
            "foreign_key_check": [list(r) for r in db.execute("PRAGMA foreign_key_check")],
            "sequence": dict(db.execute("SELECT name, seq FROM sqlite_sequence ORDER BY name").fetchall()),
            "schema": [list(r) for r in db.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name <> 'sqlite_sequence' "
                "AND name NOT LIKE 'sqlite_stat%' ORDER BY type, name")],
            "tables": {t: table_digest(db, t) for t in tables},
        }


def tables(path):
    return state(path)["tables"]


def delta(before, after):
    """Tables whose content changed, with their row-count difference."""
    return {t: after[t]["rows"] - before.get(t, {"rows": 0})["rows"]
            for t in sorted(after) if after[t] != before.get(t)}


def versions(path, material_id):
    with ro(path) as db:
        return [r[0] for r in db.execute("SELECT version FROM listening_transcripts WHERE material_id = ? "
                                         "ORDER BY version", (material_id,))]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_db(src_dir, dst_dir):
    dst_dir.mkdir(parents=True, mode=0o700)
    for suffix in ("", "-wal", "-shm"):
        s = src_dir / f"app.db{suffix}"
        if s.exists():
            shutil.copyfile(s, dst_dir / s.name)
            os.chmod(dst_dir / s.name, 0o600)
    return dst_dir / "app.db"


# --- processes and HTTP ---------------------------------------------------------

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(method, url, body=None, headers=None):
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw, status, rh = resp.read(), resp.status, resp.headers
    except urllib.error.HTTPError as e:
        raw, status, rh = e.read(), e.code, e.headers
    try:
        payload = json.loads(raw) if raw else None
    except ValueError:
        payload = raw.decode(errors="replace")
    return status, rh, payload


class FakeResponses:
    """Loopback stand-in for the OpenAI Responses API (fake key only)."""

    def __init__(self):
        outer = self
        self.calls = 0

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.calls += 1
                if self.path != "/v1/responses" or self.headers.get("Authorization") != f"Bearer {FAKE_KEY}":
                    self.send_response(404)
                    self.end_headers()
                    return
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
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.env = {"LISTENING_PROVIDER": "openai", "OPENAI_API_KEY": FAKE_KEY, "OPENAI_MODEL": "fake-model",
                    "OPENAI_BASE_URL": f"http://127.0.0.1:{self.httpd.server_address[1]}/v1",
                    "OPENAI_TIMEOUT": "10s"}

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Server:
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

    def __enter__(self):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        check(not (self.run_dir / ".env").exists(), f"{self.run_dir} holds a .env")
        self.port = free_port()
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.run_dir), "LISTEN_HOST": "127.0.0.1",
               "PORT": str(self.port), "DB_PATH": str(self.db_path)}
        env.update(self.BASE_ENV)
        env.update(self.extra)
        self.log = open(self.log_path, "ab")
        self.proc = subprocess.Popen([str(self.binary)], cwd=self.run_dir, env=env, stdout=self.log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                self.log.close()
                raise Failed(f"server exited with {self.proc.returncode}; see {self.log_path}")
            try:
                if call("GET", self.url("/readyz"))[0] == 200:
                    return self
            except OSError:
                pass
            time.sleep(0.2)
        self.__exit__()
        raise Failed("server not ready within 30 s")

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def call(self, method, path, body=None, headers=None):
        return call(method, self.url(path), body, headers)

    def expect(self, method, path, status, body=None, headers=None):
        got, _, payload = self.call(method, path, body, headers)
        check(got == status, f"{method} {path}: HTTP {got}, want {status}: {str(payload)[:300]}")
        return payload

    def __exit__(self, *exc):
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.log.close()
        return False


# --- small helpers --------------------------------------------------------------

def capture(capture_id, text, ref):
    return {"schema_version": "learning_capture_v1", "capture_id": capture_id, "source": "manual",
            "original_input": text, "original_context": "FLH-152 upgrade rehearsal (synthetic fixture)",
            "source_ref": ref}


def current_exercise(lesson):
    if "current_exercise_id" not in lesson:  # builds before the field: a script has exactly one exercise
        check(len(lesson["exercises"]) == 1, "lesson without current_exercise_id has several exercises")
        return lesson["exercises"][0]
    return next(e for e in lesson["exercises"] if e["id"] == lesson["current_exercise_id"])


def item(exercise, n):
    return exercise["content"]["items"][n - 1]


def wrong_choice(it):
    return next(c for c in it["choices"] if c != it["expected_answer"])


QUESTION_FIELDS = ("id", "kind", "question", "choices", "expected_answer", "wrong_answers", "rationale_en",
                   "rationale_zh", "segments", "evidence")


def question(it):
    return {k: it.get(k) for k in QUESTION_FIELDS}


def grounded(transcript, it):
    """Every evidence excerpt occurs in the line it cites, in this transcript."""
    text = {s["index"]: s["text"] for s in transcript["segments"]}
    ev = it.get("evidence") or []
    return bool(ev) and all(e["excerpt"] in text.get(e["segment"], "") for e in ev)


def notebook(s):
    out = {}
    for it in s.expect("GET", "/mistake-notebook/items", 200)["items"]:
        out[it["entry_id"]] = it
    return out


def without(d, *keys):
    return {k: v for k, v in d.items() if k not in keys}


def build_info(binary):
    out = subprocess.run(["go", "version", "-m", str(binary)], capture_output=True, text=True)
    keep = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == "path":
            keep["path"] = parts[1]
        if len(parts) >= 2 and parts[0] == "build" and parts[1].split("=")[0] in (
                "vcs.revision", "vcs.modified", "vcs.time", "-buildvcs"):
            k, _, v = parts[1].partition("=")
            keep[k] = v
    keep["go"] = out.stdout.splitlines()[0].split(": ", 1)[-1] if out.stdout else out.stderr.strip()[:200]
    keep["sha256"] = sha256_file(binary)
    return keep


def rotate_one_question(script):
    """The synthetic correction: rotate the options of question 2 (or the first
    later question with options) one place, keeping everything else."""
    qs = script["questions"]
    for q in qs[1:] + qs[:1]:
        if len(q.get("choices") or []) >= 2:
            q["choices"] = q["choices"][-1:] + q["choices"][:-1]
            return q["id"]
    return None


LINE_SCRIPT = "ls-wb1-u03"
LINE_SUFFIX = " Bon, d'accord."


def change_one_line(script):
    """The synthetic line correction: append a short sentence to the first line
    no question cites (as a line or as evidence)."""
    cited = set()
    for q in script["questions"]:
        cited.update(f"s{n}" for n in q.get("segments") or [])
        cited.update(f"s{e['segment']}" for e in q.get("evidence") or [])
    line = next((l for l in script["lines"] if l["id"] not in cited), script["lines"][-1])
    line["text"] += LINE_SUFFIX
    return line["id"]


def build_variant(work):
    src = work / "variant-src"
    for part in ("cmd", "internal", "migrations", "go.mod", "go.sum"):
        p = REPO / part
        if p.is_dir():
            shutil.copytree(p, src / part)
        else:
            src.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, src / part)
    pack_path = src / PACK
    pack = json.loads(pack_path.read_text())
    rotated = {s["id"]: rotate_one_question(s) for s in pack["scripts"]}
    line = change_one_line(next(s for s in pack["scripts"] if s["id"] == LINE_SCRIPT))
    pack_path.write_text(json.dumps(pack, ensure_ascii=False, indent=1) + "\n")
    out = work / "bin" / "variant-server"
    out.parent.mkdir(exist_ok=True)
    env = dict(os.environ)
    res = subprocess.run(["go", "build", "-buildvcs=false", "-trimpath", "-o", str(out), "./cmd/server"], cwd=src,
                         env=env, capture_output=True, text=True)
    check(res.returncode == 0, f"variant build failed: {res.stderr.strip()[:400]}")
    return out, {"rotated_question_per_script": rotated, "changed_line": {LINE_SCRIPT: line},
                 "pack_sha256": sha256_file(pack_path),
                 "baseline_pack_sha256": sha256_file(REPO / PACK)}


# --- RELEASE.md Backup and Restore blocks (service stop/start owned here) --------

BACKUP = r'''
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

RESTORE = r'''
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


def block(script, *args):
    out = subprocess.run(["bash", "-c", script, "block", *map(str, args)], capture_output=True, text=True)
    check(out.returncode == 0, f"block failed: {out.stderr.strip()[:300]}")
    return Path(out.stdout.strip().splitlines()[-1])


# --- stages ---------------------------------------------------------------------

def fresh(binary, work, name):
    d = work / "fresh" / name
    d.mkdir(parents=True)
    with Server(binary, d / "app.db", d / "run", work / "logs" / f"fresh-{name}.log"):
        pass
    st = state(d / "app.db")
    return {"ledger": st["ledger"], "schema": st["schema"]}


def seed(work, old_bin, db):
    fake = FakeResponses()
    try:
        with Server(old_bin, db, work / "run" / "seed", work / "logs" / "seed.log", fake.env) as s:
            ids = [r["id"] for r in s.expect("GET", "/listening/scripts", 200)["scripts"]]
            lessons = {sid: s.expect("POST", f"/listening/scripts/{sid}", 201) for sid in ids}
            main = lessons[MAIN]
            ex1 = current_exercise(main)
            q4, q2 = item(ex1, 4), item(ex1, 2)
            check(q4["id"] == "u05-l04" and q2["id"] == "u05-l02", "u05 questions are not where expected")
            e1 = s.expect("POST", "/captures", 201, capture("flh152-u05-q4-rev1", "Pourquoi le cours du soir ?", {
                "type": "listening_item", "record_id": ex1["id"], "item": 4, "attempt": wrong_choice(q4)}))["entry_id"]
            e2 = s.expect("POST", "/captures", 201, capture("flh152-u05-q2-rev1", "Le niveau de Mei", {
                "type": "listening_item", "record_id": ex1["id"], "item": 2, "attempt": wrong_choice(q2)}))["entry_id"]
            y = s.expect("POST", "/listening/materials", 201, {
                "source_url": "https://www.youtube.com/watch?v=FLH152rehrs", "title": "Répétition FLH-152",
                "transcript": f"{LINE1}\n{LINE2}"})
            yid = y["material"]["id"]
            prep = s.expect("POST", f"/listening/materials/{yid}/exercises", 201, {},
                            {"Idempotency-Key": str(uuid.uuid4())})
            yex = prep["exercise"]["id"]
            e3 = s.expect("POST", "/captures", 201, capture("flh152-youtube-q1", "bibliothèque", {
                "type": "listening_item", "record_id": yex, "item": 1, "attempt": "Une piscine."}))["entry_id"]
            ylesson = s.expect("GET", f"/listening/materials/{yid}", 200)
            nb = notebook(s)
            return {
                "scripts": ids,
                "materials": {sid: l["material"]["id"] for sid, l in lessons.items()},
                "exercises": {sid: current_exercise(l)["id"] for sid, l in lessons.items()},
                "main_segments": main["transcript"]["segments"],
                "old_q4": question(q4), "old_q2": question(q2),
                "entries": {"u05_q4_rev1": e1, "u05_q2_rev1": e2, "youtube_q1": e3},
                "youtube": {"material_id": yid, "exercise_id": yex, "transcript": ylesson["transcript"],
                            "exercise_ids": [e["id"] for e in ylesson["exercises"]],
                            "current_exercise_id": ylesson.get("current_exercise_id")},
                "notebook": {str(k): v for k, v in nb.items()},
                "provider_calls": fake.calls,
            }
    finally:
        fake.close()


class Rec:
    def __init__(self):
        self.checks = []
        self.obs = {}

    def ok(self, item_no, name, cond, detail=None):
        self.checks.append({"item": item_no, "check": name, "pass": bool(cond), "detail": detail})
        return bool(cond)

    def guard(self, item_no, name, fn):
        """Run one group of checks; an unexpected error fails that group only."""
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - recorded, the rehearsal continues
            self.ok(item_no, f"{name}: completed without error", False, f"{type(e).__name__}: {e}"[:400])


def flow(label, work, new_bin, variant_bin, db, facts, migrations, fresh_new):
    rec = Rec()
    fake = FakeResponses()
    logs = work / "logs"
    mid = facts["materials"][MAIN]
    ex1 = facts["exercises"][MAIN]
    e1id, e2id, e3id = (facts["entries"][k] for k in ("u05_q4_rev1", "u05_q2_rev1", "youtube_q1"))
    ctx = {}
    try:
        # 5. upgrade: start the new build on the copy, read once, stop; nothing may change.
        pre = state(db)
        with Server(new_bin, db, work / "run" / label / "start", logs / f"{label}-start.log", fake.env) as s:
            s.expect("GET", "/listening/scripts", 200)
        post = state(db)
        rec.ok(5, "migration ledger unchanged by the new build (no migration)", pre["ledger"] == post["ledger"],
               post["ledger"][-1:])
        rec.ok(5, "ledger is exactly the repository's migrations", post["ledger"] == migrations)
        rec.ok(5, "schema unchanged and equal to a fresh install by the new build",
               pre["schema"] == post["schema"] == fresh_new["schema"])
        rec.ok(5, "every table byte-identical after start and a read", pre["tables"] == post["tables"],
               delta(pre["tables"], post["tables"]))
        rec.ok(5, "sqlite_sequence unchanged", pre["sequence"] == post["sequence"])
        rec.ok(5, "integrity_check ok", post["integrity"] == ["ok"], post["integrity"][:3])
        rec.ok(5, "foreign_key_check empty", post["foreign_key_check"] == [], post["foreign_key_check"][:3])
        rec.obs["5.rows"] = {t: v["rows"] for t, v in post["tables"].items()}

        with Server(new_bin, db, work / "run" / label / "new", logs / f"{label}-new.log", fake.env) as s:
            calls0 = fake.calls

            def item6():
                rows = {r["id"]: r for r in s.expect("GET", "/listening/scripts", 200)["scripts"]}
                ctx["rows"] = rows
                rec.obs["6.catalog"] = {k: [r.get("imported_revision"), r.get("pack_status")] for k, r in rows.items()}
                rec.ok(6, "script list: u05 imported revision 1, update available",
                       rec.obs["6.catalog"][MAIN] == [1, "update_available"], rec.obs["6.catalog"][MAIN])
                changed = sorted(k for k, r in rows.items() if r.get("pack_status") == "update_available" and k != MAIN)
                ctx["unchanged"] = sorted(k for k, r in rows.items() if r.get("pack_status") == "up_to_date")
                check(len(changed) >= 2, f"need two more outdated scripts, have {changed}")
                ctx["B"], ctx["D"] = changed[0], changed[1]
                lesson = s.expect("GET", f"/listening/materials/{mid}", 200)
                sr = lesson["script_revision"]
                rec.ok(6, "lesson: revision 1, update available, old exercise still current",
                       sr["revision"] == 1 and sr["pack_status"] == "update_available"
                       and lesson["current_exercise_id"] == ex1, sr)
                rec.ok(6, "lesson keeps the old wording until the learner confirms",
                       question(item(current_exercise(lesson), 4)) == facts["old_q4"])
                t0 = tables(db)
                prev = s.expect("GET", f"/listening/materials/{mid}/script-update", 200)
                rec.ok(6, "lesson read and preview wrote nothing", tables(db) == t0)
                qs = {q["item_id"]: q["fields"] for q in prev["changes"]["questions"]}
                rec.obs["6.preview"] = {"from": prev["current_revision"], "to": prev["next_revision"],
                                        "pack_status": prev["pack_status"], "questions": qs,
                                        "lines": [l["line"] for l in prev["changes"]["lines"]],
                                        "pack_fingerprint": prev["pack_fingerprint"]}
                rec.ok(6, "preview: revision 1 -> 2, u05-l04 among the changes",
                       prev["current_revision"] == 1 and prev["next_revision"] == 2 and "u05-l04" in qs, qs)
                body = {"from_revision": prev["current_revision"], "pack_fingerprint": prev["pack_fingerprint"]}
                ctx["main_body"] = body
                t0 = tables(db)
                st, _, up = s.call("POST", f"/listening/materials/{mid}/script-update", body)
                d = delta(t0, tables(db))
                rec.ok(6, "confirm: 201, revision 2, not a replay",
                       st == 201 and up["revision"] == 2 and up["replayed"] is False, [st, str(up)[:200]])
                rec.ok(6, "confirm appended one transcript version and one exercise, nothing else",
                       d == {"listening_exercises": 1, "listening_transcripts": 1}, d)
                lesson2 = up["lesson"]
                ctx["ex2"] = lesson2["current_exercise_id"]
                ctx["new_q4"] = question(item(current_exercise(lesson2), 4))
                rec.ok(6, "lesson now revision 2, up to date, new exercise current, corrected question 4",
                       lesson2["script_revision"]["revision"] == 2
                       and lesson2["script_revision"]["pack_status"] == "up_to_date"
                       and ctx["ex2"] != ex1 and ctx["new_q4"] != facts["old_q4"]
                       and ctx["new_q4"]["id"] == "u05-l04", lesson2["script_revision"])
                rec.obs["6.ids"] = {"ex1": ex1, "ex2": ctx["ex2"], "versions": versions(db, mid)}
            rec.guard(6, "preview and confirm", item6)

            def item7():
                nb = notebook(s)
                e1, old = nb[e1id], facts["notebook"][str(e1id)]
                rec.ok(7, "old mistake identical to what the old build showed, apart from latest_version",
                       without(e1, "latest_version") == without(old, "latest_version"))
                rec.ok(7, "old mistake still links revision 1: exercise, item 4, transcript version 1",
                       e1["source"]["record_id"] == ex1 and e1["source"]["item"] == 4
                       and e1["link"].get("listening_exercise_id") == ex1
                       and e1["link"].get("listening_transcript_version") == 1, e1["link"])
                rec.ok(7, "old mistake keeps the old question, reference and explanation",
                       e1["prompt"] == facts["old_q4"]["question"]
                       and e1["reference"] == facts["old_q4"]["expected_answer"]
                       and e1["explanation_en"] == facts["old_q4"]["rationale_en"], e1["explanation_en"])
                rec.ok(7, "old mistake flags the newer revision (latest_version 2) and resolves",
                       e1["latest_version"] == 2 and e1["source_status"] == "resolved",
                       [e1["latest_version"], e1["source_status"]])
                src = s.expect("GET", f"/entries/{e1id}/source", 200)
                rec.ok(7, "entry source read resolves to the same item", src["linked"] and src["item"] == e1)
                r1 = s.expect("GET", f"/listening/materials/{mid}/revisions/1", 200)
                rq4 = item(r1["exercise"], 4)
                rec.ok(7, "revision 1 read: the old exercise and the old build's question 4",
                       r1["exercise"]["id"] == ex1 and question(rq4) == facts["old_q4"])
                rec.ok(7, "revision 1 read: the old build's lines",
                       r1["transcript"]["segments"] == facts["main_segments"] and r1["current_revision"] == 2)
                rec.ok(7, "old question 4's evidence is in revision 1's cited lines",
                       grounded(r1["transcript"], rq4), rq4.get("evidence"))
            rec.guard(7, "old mistake", item7)

            def item8():
                ex2 = ctx["ex2"]
                st, _, cap = s.call("POST", "/captures", capture("flh152-u05-q4-rev2", "Pourquoi le soir ?", {
                    "type": "listening_item", "record_id": ex2, "item": 4,
                    "attempt": wrong_choice(ctx["new_q4"])}))
                rec.ok(8, "new mistake on revision 2: 201", st == 201, [st, str(cap)[:200]])
                e4id = ctx["e4"] = cap["entry_id"]
                nb = notebook(s)
                e4 = nb[e4id]
                rec.ok(8, "new mistake links revision 2: exercise, item 4, transcript version 2",
                       e4["source"]["record_id"] == ex2 and e4["link"].get("listening_exercise_id") == ex2
                       and e4["link"].get("listening_transcript_version") == 2, e4["link"])
                rec.ok(8, "new mistake shows the corrected question and explanation, no newer revision",
                       e4["prompt"] == ctx["new_q4"]["question"]
                       and e4["explanation_en"] == ctx["new_q4"]["rationale_en"] and e4["latest_version"] is None,
                       e4["explanation_en"])
                r2 = s.expect("GET", f"/listening/materials/{mid}/revisions/2", 200)
                rec.ok(8, "corrected question 4's evidence is in revision 2's cited lines",
                       grounded(r2["transcript"], item(r2["exercise"], 4)))
                rec.ok(8, "old mistake unchanged by the new one",
                       without(nb[e1id], "latest_version") == without(facts["notebook"][str(e1id)], "latest_version"))
                st, _, dup = s.call("POST", "/captures", capture("flh152-u05-q4-rev1-again", "encore", {
                    "type": "listening_item", "record_id": ex1, "item": 4}))
                rec.ok(8, "saving revision 1's question 4 again: 409 source_already_saved naming the old entry",
                       st == 409 and dup.get("code") == "source_already_saved" and dup.get("entry_id") == e1id,
                       [st, dup])
                rec.obs["8.entries"] = {"e1": e1id, "e4": e4id}
            rec.guard(8, "new mistake", item8)

            def item9():
                t0 = tables(db)
                st, rh, again = s.call("POST", f"/listening/materials/{mid}/script-update", ctx["main_body"])
                rec.ok(9, "the same confirmation again: 200 replay, revision 2, Idempotency-Replayed",
                       st == 200 and again["replayed"] is True and again["revision"] == 2
                       and rh.get("Idempotency-Replayed") == "true", [st, str(again)[:120]])
                rec.ok(9, "the replay wrote nothing; history is versions 1 and 2",
                       tables(db) == t0 and versions(db, mid) == [1, 2], versions(db, mid))
            rec.guard(9, "repeated confirmation", item9)

            def item10():
                bid = facts["materials"][ctx["B"]]
                pb = s.expect("GET", f"/listening/materials/{bid}/script-update", 200)
                body = {"from_revision": pb["current_revision"], "pack_fingerprint": pb["pack_fingerprint"]}
                t0 = tables(db)
                barrier, results = threading.Barrier(2), []

                def go():
                    barrier.wait()
                    results.append(s.call("POST", f"/listening/materials/{bid}/script-update", body))
                threads = [threading.Thread(target=go) for _ in range(2)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                statuses = sorted(r[0] for r in results)
                d = delta(t0, tables(db))
                rec.ok(10, f"two simultaneous confirmations of one preview ({ctx['B']}): one 201, one 200",
                       statuses == [200, 201], statuses)
                rec.ok(10, "both answer revision 2 with the same exercise",
                       {r[2]["revision"] for r in results} == {2}
                       and len({r[2]["lesson"]["current_exercise_id"] for r in results}) == 1)
                rec.ok(10, "exactly one revision appended", d == {"listening_exercises": 1, "listening_transcripts": 1}
                       and versions(db, bid) == [1, 2], d)
                st, _, third = s.call("POST", f"/listening/materials/{bid}/script-update", body)
                rec.ok(10, "a third, later confirmation of the same preview: 200 replay",
                       st == 200 and third["replayed"] is True and versions(db, bid) == [1, 2], st)
                rec.obs["10"] = {"script": ctx["B"], "statuses": statuses}
            rec.guard(10, "two confirmations", item10)

            def item11():
                did = facts["materials"][ctx["D"]]
                t0 = tables(db)
                st, _, r = s.call("POST", f"/listening/materials/{did}/script-update",
                                  {"from_revision": 1, "pack_fingerprint": "sha256:" + "0" * 64})
                rec.ok(11, f"preview of another pack ({ctx['D']}): 409 stale_preview with a fresh preview",
                       st == 409 and r.get("code") == "stale_preview" and r["preview"]["current_revision"] == 1
                       and r["preview"]["pack_status"] == "update_available", [st, str(r)[:160]])
                fp = r["preview"]["pack_fingerprint"]
                st2, _, r2 = s.call("POST", f"/listening/materials/{did}/script-update",
                                    {"from_revision": 2, "pack_fingerprint": fp})
                rec.ok(11, "preview claiming a revision the lesson does not have: 409 stale_preview",
                       st2 == 409 and r2.get("code") == "stale_preview", st2)
                st3, _, _ = s.call("GET", f"/listening/materials/{did}/revisions/2")
                rec.ok(11, "stale confirmations wrote nothing; history is version 1 only; revision 2 is 404",
                       tables(db) == t0 and versions(db, did) == [1] and st3 == 404, [versions(db, did), st3])
                ctx["pd"] = s.expect("GET", f"/listening/materials/{did}/script-update", 200)
            rec.guard(11, "stale preview (same build)", item11)

            def item12():
                t0 = tables(db)
                st, rh, imp = s.call("POST", f"/listening/scripts/{MAIN}")
                rec.ok(12, "re-import of the updated script: 200 replay on the same lesson",
                       st == 200 and rh.get("Idempotency-Replayed") == "true" and imp["material"]["id"] == mid, st)
                outcome = {}
                for sid in sorted(ctx["rows"]):
                    st, _, b = s.call("POST", f"/listening/scripts/{sid}")
                    outcome[sid] = [st, b.get("code") if st != 200 else None]
                updated = {MAIN, ctx["B"]}
                want = {sid: ([200, None] if sid in updated or sid in ctx["unchanged"] else [409, "script_conflict"])
                        for sid in ctx["rows"]}
                rec.ok(12, "whole-catalog replay: updated and unchanged scripts 200, outdated ones 409 script_conflict",
                       outcome == want, outcome)
                st, _, c = s.call("POST", f"/listening/scripts/{ctx['D']}")
                rec.ok(12, "the 409 names the lesson, its revision and the update",
                       c.get("material_id") == facts["materials"][ctx["D"]] and c.get("current_revision") == 1
                       and c.get("pack_status") == "update_available", c)
                pm = s.expect("GET", f"/listening/materials/{mid}/script-update", 200)
                rec.ok(12, "preview of the updated lesson: up to date, nothing to change",
                       pm["pack_status"] == "up_to_date" and pm["next_revision"] is None
                       and pm["changes"] == {"lines": [], "questions": [], "annotations_changed": False}, pm["changes"])
                st, _, rp = s.call("POST", f"/listening/materials/{mid}/script-update",
                                   {"from_revision": 2, "pack_fingerprint": pm["pack_fingerprint"]})
                rec.ok(12, "confirming the up-to-date preview: 200 replay", st == 200 and rp["replayed"] is True, st)
                rec.ok(12, "catalog replay and up-to-date confirmation wrote nothing", tables(db) == t0,
                       delta(t0, tables(db)))
                rec.obs["12"] = {"catalog": outcome, "unchanged": ctx["unchanged"]}
            rec.guard(12, "unchanged catalog replay", item12)

            def item14():
                y = facts["youtube"]
                yid = y["material_id"]
                rec.ok(14, "no provider call during any script read, update or replay", fake.calls == calls0,
                       fake.calls - calls0)
                ly = s.expect("GET", f"/listening/materials/{yid}", 200)
                rec.ok(14, "YouTube lesson: no script revision; transcript and exercises as the old build left them",
                       ly["script_revision"] is None and ly["transcript"] == y["transcript"]
                       and [e["id"] for e in ly["exercises"]] == y["exercise_ids"]
                       and ly["current_exercise_id"] == y["exercise_id"])
                t0 = tables(db)
                codes = []
                for method, path, body in (("GET", f"/listening/materials/{yid}/script-update", None),
                                           ("POST", f"/listening/materials/{yid}/script-update", ctx["main_body"]),
                                           ("GET", f"/listening/materials/{yid}/revisions/1", None)):
                    st, _, b = s.call(method, path, body)
                    codes.append([st, b.get("code") if isinstance(b, dict) else None])
                rec.ok(14, "script-update preview, confirm and revision read on YouTube: 409 not_authored_script",
                       codes == [[409, "not_authored_script"]] * 3, codes)
                rec.ok(14, "those refusals wrote nothing", tables(db) == t0)
                nb = notebook(s)
                rec.ok(14, "YouTube mistake identical to what the old build showed",
                       nb[e3id] == facts["notebook"][str(e3id)])
                before = fake.calls
                prep = s.expect("POST", f"/listening/materials/{yid}/exercises", 201, {},
                                {"Idempotency-Key": str(uuid.uuid4())})
                yex2 = prep["exercise"]["id"]
                rec.ok(14, "explicit YouTube preparation still works through the fake: one call, a new exercise",
                       fake.calls == before + 1 and yex2 not in y["exercise_ids"], fake.calls - before)
                st, _, cap = s.call("POST", "/captures", capture("flh152-youtube-q2-new", "justificatif", {
                    "type": "listening_item", "record_id": yex2, "item": 2}))
                nb = notebook(s)
                rec.ok(14, "a mistake on the new YouTube exercise links it",
                       st == 201 and nb[cap["entry_id"]]["link"].get("listening_exercise_id") == yex2, st)
                ly2 = s.expect("GET", f"/listening/materials/{yid}", 200)
                rec.ok(14, "YouTube lesson still has no script revision and one transcript version",
                       ly2["script_revision"] is None and versions(db, yid) == [1])
            rec.guard(14, "YouTube lesson", item14)

        # The server now runs the variant pack (options of one question per script rotated).
        with Server(variant_bin, db, work / "run" / label / "variant", logs / f"{label}-variant.log", fake.env) as v:
            def item11b():
                did = facts["materials"][ctx["D"]]
                pd = ctx["pd"]
                t0 = tables(db)
                st, _, r = v.call("POST", f"/listening/materials/{did}/script-update",
                                  {"from_revision": pd["current_revision"], "pack_fingerprint": pd["pack_fingerprint"]})
                rec.ok(11, "preview taken before the pack changed, confirmed after: 409 stale_preview, fresh preview",
                       st == 409 and r.get("code") == "stale_preview"
                       and r["preview"]["pack_fingerprint"] != pd["pack_fingerprint"]
                       and r["preview"]["current_revision"] == 1, [st, str(r)[:160]])
                pv = v.expect("GET", f"/listening/materials/{mid}/script-update", 200)
                ctx["pv"] = pv
                st2, _, r2 = v.call("POST", f"/listening/materials/{mid}/script-update",
                                    {"from_revision": 1, "pack_fingerprint": pv["pack_fingerprint"]})
                rec.ok(11, "preview from revision 1 after the lesson moved to revision 2: 409 stale_preview",
                       st2 == 409 and r2.get("code") == "stale_preview" and r2["preview"]["current_revision"] == 2, st2)
                rec.ok(11, "neither stale confirmation changed the revision history",
                       tables(db) == t0 and versions(db, did) == [1] and versions(db, mid) == [1, 2],
                       [versions(db, did), versions(db, mid)])
            rec.guard(11, "stale preview (pack changed)", item11b)

            def item13():
                pv = ctx["pv"]
                qs = pv["changes"]["questions"]
                rec.ok(13, "variant preview of u05: only u05-l02's options changed, same position, no line change",
                       [(q["item_id"], q["change"], q["fields"], q["before_position"], q["after_position"]) for q in qs]
                       == [("u05-l02", "changed", ["choices"], 2, 2)] and pv["changes"]["lines"] == [],
                       [(q["item_id"], q["fields"]) for q in qs])
                st, _, up = v.call("POST", f"/listening/materials/{mid}/script-update",
                                   {"from_revision": 2, "pack_fingerprint": pv["pack_fingerprint"]})
                rec.ok(13, "confirm: 201, revision 3", st == 201 and up["revision"] == 3, st)
                ex3 = up["lesson"]["current_exercise_id"]
                revs = {n: v.expect("GET", f"/listening/materials/{mid}/revisions/{n}", 200) for n in (1, 2, 3)}
                ids = {n: [it["id"] for it in r["exercise"]["content"]["items"]] for n, r in revs.items()}
                rec.ok(13, "question ids and positions identical in revisions 1, 2 and 3",
                       ids[1] == ids[2] == ids[3], ids[3])
                q2 = {n: item(r["exercise"], 2) for n, r in revs.items()}
                pos = {n: q2[n]["choices"].index(q2[n]["expected_answer"]) + 1 for n in q2}
                rec.ok(13, "u05-l02: same reference answer and options, new order, the answer moved",
                       q2[3]["expected_answer"] == q2[2]["expected_answer"]
                       and sorted(q2[3]["choices"]) == sorted(q2[2]["choices"])
                       and q2[3]["choices"] != q2[2]["choices"] and pos[3] != pos[2], pos)
                rec.ok(13, "u05-l02: why-wrong notes, explanation and evidence unchanged by the reordering",
                       all(q2[3][k] == q2[2][k] for k in ("wrong_answers", "rationale_en", "rationale_zh", "evidence")))
                rec.ok(13, "revision 1 keeps the old build's option order for u05-l02",
                       question(q2[1]) == facts["old_q2"])
                nb = notebook(v)
                e2 = nb[e2id]
                rec.ok(13, "old mistake on u05-l02 still links revision 1: exercise, item 2, its attempt",
                       e2["source"]["record_id"] == ex1 and e2["source"]["item"] == 2
                       and e2["source"]["attempt"] == wrong_choice(facts["old_q2"])
                       and e2["link"].get("listening_exercise_id") == ex1
                       and e2["link"].get("listening_transcript_version") == 1 and e2["latest_version"] == 3,
                       [e2["source"], e2["link"], e2["latest_version"]])
                rec.ok(13, "old mistake's question and reference are revision 1's",
                       e2["prompt"] == q2[1]["question"] and e2["reference"] == q2[1]["expected_answer"])
                st, _, cap = v.call("POST", "/captures", capture("flh152-u05-q2-rev3", "le niveau", {
                    "type": "listening_item", "record_id": ex3, "item": 2, "attempt": wrong_choice(q2[3])}))
                nb = notebook(v)
                e5 = nb[cap["entry_id"]] if st == 201 else {}
                rec.ok(13, "new mistake on revision 3's u05-l02 links that exercise, item 2, transcript version 3",
                       st == 201 and e5["source"]["record_id"] == ex3 and e5["source"]["item"] == 2
                       and e5["link"].get("listening_transcript_version") == 3 and e5["latest_version"] is None, st)
                rec.ok(13, "earlier mistakes keep their revisions and now flag revision 3",
                       [nb[e1id]["link"].get("listening_transcript_version"),
                        nb[ctx["e4"]]["link"].get("listening_transcript_version"),
                        nb[e1id]["latest_version"], nb[ctx["e4"]]["latest_version"]] == [1, 2, 3, 3])
                rec.obs["13"] = {"ids": ids[3], "answer_position": pos, "ex3": ex3}
            rec.guard(13, "choice reordering", item13)

            def item13_line():
                lid = facts["materials"][LINE_SCRIPT]
                p = v.expect("GET", f"/listening/materials/{lid}/script-update", 200)
                changed = [l["line"] for l in p["changes"]["lines"]]
                st, _, up = v.call("POST", f"/listening/materials/{lid}/script-update",
                                   {"from_revision": 1, "pack_fingerprint": p["pack_fingerprint"]})
                r1 = v.expect("GET", f"/listening/materials/{lid}/revisions/1", 200)
                r2 = v.expect("GET", f"/listening/materials/{lid}/revisions/2", 200)
                t1 = {x["index"]: x["text"] for x in r1["transcript"]["segments"]}
                t2 = {x["index"]: x["text"] for x in r2["transcript"]["segments"]}
                diff = sorted(f"s{i}" for i in t2 if t1.get(i) != t2[i])
                rec.ok(13, f"extra: a synthetic line correction ({LINE_SCRIPT}) is previewed, confirmed (201) "
                           "and only revision 2 has the new line",
                       len(changed) == 1 and st == 201 and up["revision"] == 2 and diff == changed
                       and t2[int(changed[0][1:])] == t1[int(changed[0][1:])] + LINE_SUFFIX
                       and all(grounded(r2["transcript"], it) for it in r2["exercise"]["content"]["items"]
                               if it.get("evidence")), [changed, st, diff])
                rec.obs["13.line"] = {"changed": changed, "diff": diff}
            rec.guard(13, "line correction", item13_line)

        final = state(db)
        rec.ok(0, "final integrity_check ok and foreign_key_check empty",
               final["integrity"] == ["ok"] and final["foreign_key_check"] == [])
        rec.obs["final.rows"] = {t: v["rows"] for t, v in final["tables"].items()}
        rec.obs["final.versions"] = {sid: versions(db, m) for sid, m in sorted(facts["materials"].items())}
        rec.obs["final.versions"]["youtube"] = versions(db, facts["youtube"]["material_id"])
    finally:
        fake.close()
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old-server", required=True)
    ap.add_argument("--new-server", required=True)
    ap.add_argument("--variant-server")
    ap.add_argument("work_dir")
    a = ap.parse_args()
    work = Path(a.work_dir)
    if not work.is_absolute() or REPO in work.resolve().parents or work.resolve() == REPO:
        print("WORK_DIR must be absolute and outside the repository", file=sys.stderr)
        return 2
    if work.exists() and any(work.iterdir()):
        print("WORK_DIR must be new or empty", file=sys.stderr)
        return 2
    for d in ("logs", "evidence", "run", "bin"):
        (work / d).mkdir(parents=True, exist_ok=True)
    ev = work / "evidence"
    summary = work / "summary.tsv"
    summary.write_text("")
    failed = False

    def stage(name, ok, detail=""):
        nonlocal failed
        failed |= not ok
        line = f"{name}\t{'PASS' if ok else 'FAIL'}\t{detail}"
        print(line, flush=True)
        with summary.open("a") as fh:
            fh.write(line + "\n")

    def dump(name, obj):
        (ev / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n")

    old_bin, new_bin = Path(a.old_server).resolve(), Path(a.new_server).resolve()
    migrations = sorted(p.name for p in (REPO / "migrations").glob("*.sql"))
    try:
        if a.variant_server:
            variant_bin, variant = Path(a.variant_server).resolve(), {"prebuilt": True}
        else:
            variant_bin, variant = build_variant(work)
        info = {"old": build_info(old_bin), "new": build_info(new_bin), "variant": build_info(variant_bin),
                "variant_pack": variant}
        f_old, f_new = fresh(old_bin, work, "old"), fresh(new_bin, work, "new")
        info["ledger"] = {"old": f_old["ledger"], "new": f_new["ledger"], "repository": migrations}
        info["schema_equal_old_new"] = f_old["schema"] == f_new["schema"]
        dump("binaries.json", info)
        stage("binaries", f_old["ledger"] == f_new["ledger"] == migrations and info["schema_equal_old_new"],
              f"old {info['old'].get('vcs.revision', '?')[:7]} new {info['new'].get('vcs.revision', '?')[:7]}; "
              f"ledger {len(migrations)} migrations, last {migrations[-1]}; schemas equal {info['schema_equal_old_new']}")
    except Failed as e:
        stage("binaries", False, str(e))
        return 1

    seed_dir = work / "seed"
    seed_dir.mkdir(mode=0o700)
    try:
        facts = seed(work, old_bin, seed_dir / "app.db")
        dump("seed-facts.json", facts)
        stage("seed", True, f"{len(facts['scripts'])} scripts, u05 material {facts['materials'][MAIN]} exercise "
                            f"{facts['exercises'][MAIN]}, entries {facts['entries']}, youtube {facts['youtube']['material_id']}")
    except Failed as e:
        stage("seed", False, str(e))
        return 1

    snap = block(BACKUP, seed_dir, work / "backups")
    snap_state = state(snap / "app.db")
    files = sorted(p.name for p in snap.iterdir())
    for p in snap.iterdir():
        os.chmod(p, 0o444)
    os.chmod(snap, 0o555)
    manifest = {"path": str(snap), "files": {f: sha256_file(snap / f) for f in files},
                "ledger_last": snap_state["ledger"][-1], "integrity": snap_state["integrity"],
                "foreign_key_check": snap_state["foreign_key_check"], "sequence": snap_state["sequence"],
                "rows": {t: v["rows"] for t, v in snap_state["tables"].items()},
                "table_sha256": {t: v["sha256"] for t, v in snap_state["tables"].items()},
                "ids": {"materials": facts["materials"], "exercises": facts["exercises"], "entries": facts["entries"],
                        "youtube": {k: facts["youtube"][k] for k in ("material_id", "exercise_id")}}}
    dump("snapshot-manifest.json", manifest)
    stage("snapshot", snap_state["integrity"] == ["ok"] and not snap_state["foreign_key_check"],
          f"{snap.name}: {', '.join(files)} (read-only); rows {sum(manifest['rows'].values())} in "
          f"{len(manifest['rows'])} tables")

    runs = {}
    active = work / "active"
    for label in ("run-a", "run-b"):
        if label == "run-a":
            db = copy_db(snap, active)
        else:
            moved = block(RESTORE, active, snap)
            same = sha256_file(active / "app.db") == manifest["files"]["app.db"]
            rstate = state(active / "app.db")
            # The Restore block copies with cp -a, so it keeps the backup's
            # mode: this harness made the snapshot read-only, and a read-only
            # app.db passes /readyz but answers every write with a 500. Make
            # the restored files writable, as an operator must.
            modes = {p.name: oct(p.stat().st_mode & 0o777) for p in sorted(active.iterdir())}
            for p in active.iterdir():
                os.chmod(p, 0o600)
            stage("restore", same and rstate["tables"] == snap_state["tables"] and rstate["integrity"] == ["ok"],
                  f"restored app.db byte-identical to the snapshot: {same}; run A's database kept at {moved.name}; "
                  f"restored modes {modes} (cp -a keeps the backup's), set to 0o600")
            db = active / "app.db"
        f_new = fresh(new_bin, work, f"{label}-new")
        rec = flow(label, work, new_bin, variant_bin, db, facts, migrations, f_new)
        runs[label] = rec
        dump(f"checks-{label}.json", rec.checks)
        dump(f"observations-{label}.json", rec.obs)
        bad = [c for c in rec.checks if not c["pass"]]
        stage(label, not bad, f"{len(rec.checks) - len(bad)}/{len(rec.checks)} checks pass"
                              + (f"; failing: {[(c['item'], c['check']) for c in bad][:6]}" if bad else ""))

    a_, b_ = runs["run-a"], runs["run-b"]
    same_checks = [(c["item"], c["check"], c["pass"]) for c in a_.checks] == \
                  [(c["item"], c["check"], c["pass"]) for c in b_.checks]
    same_obs = a_.obs == b_.obs
    stage("repeat", same_checks and same_obs,
          f"run B equals run A: checks {same_checks}, observations {same_obs}"
          + ("" if same_obs else f"; differing keys {[k for k in a_.obs if a_.obs.get(k) != b_.obs.get(k)]}"))

    res = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=snap, capture_output=True, text=True)
    stage("untouched", res.returncode == 0 and all(sha256_file(snap / f) == h for f, h in manifest["files"].items()),
          res.stdout.strip().replace("\n", "; "))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
