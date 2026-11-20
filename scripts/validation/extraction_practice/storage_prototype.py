#!/usr/bin/env python3
"""Check the PROPOSED practice storage schema on a scratch database.

    python3 -I -B scripts/validation/extraction_practice/storage_prototype.py WORK_DIR [--compare-with SERVER_DB] [--visit-export FILE]

WORK_DIR must be absolute, outside the repository, and new or empty. Nothing
is added to migrations/: the proposed SQL is read from the decision record
(docs/plans/PRACTICE-STORAGE-DECISION.md, between the proposed-sql markers).

  1. Build a scratch database with migrations/001-021 in the server's order
     (each file and its ledger row in one transaction, foreign keys on).
  2. Write synthetic rows into existing tables (a capture with a notebook
     source and a retry mark, a Speaking exercise, take and transcript).
  3. Back the database up (the RELEASE.md rollback point).
  4. Apply the proposed SQL as migration 0NN would run.
  5. Check that every existing schema object and row is unchanged.
  6. Check every constraint: valid rows insert; invalid rows are refused.
  7. Run the documented current-state queries on synthetic rows.
  8. Increment 5 (R2-044..048, R2-053..055): outcome without answer text and
     the explicit opt-in; duplicate submits; defer and undo as independent
     events; a personal correction becoming due practice; an interrupted
     write between approval and attempt; weekly counts; a fixture practice
     session (--visit-export: the JSON the prototype exports, e.g. from the
     browser walkthrough) loaded, backed up as RELEASE.md does and restored.
  9. Roll back by restoring the backup: the schema, ledger and rows equal
     the pre-migration database.
With --compare-with, the scratch database's 021 schema must equal that
database's (one the server created on first start: read only), so the
scratch build is the server's.
Prints one PASS/FAIL line per check and writes WORK_DIR/results.json.
Exit 0 when every check passes.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SHA_A = "a" * 64


def proposed_sql():
    text = (REPO / "docs/plans/PRACTICE-STORAGE-DECISION.md").read_text(encoding="utf-8")
    m = re.search(r"<!-- proposed-sql:start -->\s*```sql\n(.*?)```\s*<!-- proposed-sql:end -->", text, re.S)
    if not m:
        raise SystemExit("no proposed SQL found between the markers")
    return m.group(1)


def connect(p):
    con = sqlite3.connect(p, isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def migrate(con, name, sql):
    # The whole file and its ledger row in one transaction, as the server does
    # (internal/storage/sqlite/db.go): statements run as written, comments
    # included, so sqlite_master keeps the same text.
    name_sql = name.replace("'", "''")
    try:
        con.executescript(f"BEGIN;\n{sql}\n;INSERT INTO schema_migrations (name) VALUES ('{name_sql}');\nCOMMIT;")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise


def snapshot(con):
    objs = sorted(con.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall(), key=lambda r: (r[0], r[1]))
    rows = {}
    for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"):
        data = con.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
        rows[name] = hashlib.sha256(repr(data).encode()).hexdigest()
    return objs, rows


WEEK = """SELECT local_day, count(*) FILTER (WHERE action = 'attempt'), count(*) FILTER (WHERE action = 'reveal')
           FROM practice_attempts WHERE local_day BETWEEN ? AND ? GROUP BY local_day ORDER BY local_day"""


def insert_once(con, table, row):
    """The application's idempotent write (FLH-029 pattern): a resend with the same
    operation_key and the same payload replays; a different payload is a conflict."""
    cols = list(row)
    try:
        con.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [row[c] for c in cols])
        return "created"
    except sqlite3.IntegrityError:
        old = con.execute(f"SELECT {', '.join(cols)} FROM {table} WHERE operation_key = ?", (row["operation_key"],)).fetchone()
        if old is None:
            raise
        return "replayed" if list(old) == [row[c] for c in cols] else "conflict"


def increment5(con, check, work, visit, now):
    """R2-044..048 and R2-053..055 on the scratch database (after the proposed SQL)."""
    att = lambda key, pid, outcome, day, text=None, kept=0, action="attempt": {
        "operation_key": key, "practice_id": pid, "source_id": "savoir-connaitre-demo", "source_revision_sha256": "b" * 64,
        "action": action, "outcome": outcome, "answer_text": text, "answer_kept": kept, "local_day": day, "zone": "Europe/Paris", "created_at": now}
    # R2-044: outcome without answer text.
    r = [insert_once(con, "practice_attempts", att(f"w{i}", pid, o, d)) for i, (pid, o, d) in
         enumerate([("p-3ca128617083", "correct", "2026-11-17"), ("p-e61b319d2129", "incorrect", "2026-11-18"), ("p-baa71166205b", "invalid", "2026-11-18")])]
    no_text = con.execute("SELECT count(*) FROM practice_attempts WHERE operation_key LIKE 'w%' AND answer_text IS NULL").fetchone()[0]
    feed = con.execute("SELECT practice_id, outcome FROM practice_attempts WHERE operation_key LIKE 'w%' ORDER BY id").fetchall()
    check("R2-044 outcome only: rows store no answer text, and the feed outcomes and week counts come out the same",
          r == ["created"] * 3 and no_text == 3 and feed == [("p-3ca128617083", "correct"), ("p-e61b319d2129", "incorrect"), ("p-baa71166205b", "invalid")], (r, no_text, feed))
    # R2-045: explicit opt-in to keep an answer.
    try:
        con.execute("INSERT INTO practice_attempts (operation_key, practice_id, source_id, source_revision_sha256, action, outcome, answer_text, local_day, zone, created_at) "
                    "VALUES ('w-text', 'p-3ac3b47e483a', 's', ?, 'attempt', 'self_check', 'Oui, je le connais bien.', '2026-11-18', 'UTC', ?)", ("b" * 64, now))
        refused = False
    except sqlite3.IntegrityError:
        refused = True
    kept = insert_once(con, "practice_attempts", att("w-opt", "p-3ac3b47e483a", "self_check", "2026-11-18", "Oui, je le connais bien.", 1))
    check("R2-045 an answer text is refused unless the learner opted in for that attempt (answer_kept = 1)", refused and kept == "created")
    # R2-046: duplicate submits do not inflate reviews.
    before = con.execute(WEEK, ("2026-11-16", "2026-11-22")).fetchall()
    dup = [insert_once(con, "practice_attempts", att("w0", "p-3ca128617083", "correct", "2026-11-17")) for _ in range(3)]
    other = insert_once(con, "practice_attempts", att("w0", "p-3ca128617083", "incorrect", "2026-11-17"))
    after = con.execute(WEEK, ("2026-11-16", "2026-11-22")).fetchall()
    check("R2-046 three resends of one submit replay and a changed payload is a conflict; the week's counts do not move",
          dup == ["replayed"] * 3 and other == "conflict" and before == after, (dup, other, after))
    # R2-047: defer and undo as independent events.
    D = lambda key, item, action, day=None, ref=None: {"operation_key": key, "item_key": item, "action": action, "defer_until_day": day, "zone": "Europe/Paris", "refers_to": ref, "created_at": now}
    insert_once(con, "review_defers", D("x1", "practice:p-3ca128617083", "defer", "2026-11-21"))
    insert_once(con, "review_defers", D("x2", "practice:p-e61b319d2129", "defer", "2026-11-21"))
    a = con.execute("SELECT id FROM review_defers WHERE operation_key = 'x1'").fetchone()[0]
    insert_once(con, "review_defers", D("x3", "practice:p-3ca128617083", "undo", ref=a))
    insert_once(con, "review_defers", D("x4", "practice:p-3ca128617083", "defer", "2026-11-20"))
    hidden = lambda day: [r[0] for r in con.execute("""SELECT DISTINCT d.item_key FROM review_defers d WHERE d.action = 'defer'
        AND NOT EXISTS (SELECT 1 FROM review_defers u WHERE u.action = 'undo' AND u.refers_to = d.id) AND d.defer_until_day > ? AND d.item_key LIKE 'practice:%'
        ORDER BY 1""", (day,))]
    events = con.execute("SELECT count(*) FROM review_defers WHERE item_key LIKE 'practice:%'").fetchone()[0]
    check("R2-047 defer A, defer B, undo A, defer A again: four events kept; B hidden to the 21st, A to the 20th",
          events == 4 and hidden("2026-11-19") == ["practice:p-3ca128617083", "practice:p-e61b319d2129"] and hidden("2026-11-20") == ["practice:p-e61b319d2129"],
          (events, hidden("2026-11-19"), hidden("2026-11-20")))
    # R2-048: a personal correction becomes a due practice item.
    C = lambda key, action, text=None, ref=None: {"operation_key": key, "action": action, "subject_kind": "extraction_item" if action == "add" else None,
                                                   "subject_ref": "p-e61b319d2129" if action == "add" else None, "subject_version": 1 if action == "add" else None,
                                                   "original_text": None, "corrected_text": text, "refers_to": ref, "created_at": now}
    insert_once(con, "personal_corrections", C("k1", "add", "Oui, je sais nager."))
    cid = con.execute("SELECT id FROM personal_corrections WHERE operation_key = 'k1'").fetchone()[0]
    DUE = """SELECT c.id, c.corrected_text FROM personal_corrections c WHERE c.action = 'add'
        AND NOT EXISTS (SELECT 1 FROM personal_corrections r WHERE r.action = 'retire' AND r.refers_to = c.id)
        AND NOT EXISTS (SELECT 1 FROM review_defers d WHERE d.item_key = 'correction:' || c.id AND d.action = 'defer'
                        AND NOT EXISTS (SELECT 1 FROM review_defers u WHERE u.action = 'undo' AND u.refers_to = d.id) AND d.defer_until_day > ?)
        AND c.subject_ref = 'p-e61b319d2129'"""
    due_now = con.execute(DUE, ("2026-11-19",)).fetchall()
    insert_once(con, "review_defers", D("x5", f"correction:{cid}", "defer", "2026-11-20"))
    due_deferred, due_next = con.execute(DUE, ("2026-11-19",)).fetchall(), con.execute(DUE, ("2026-11-20",)).fetchall()
    insert_once(con, "personal_corrections", C("k2", "retire", ref=cid))
    due_retired = con.execute(DUE, ("2026-11-20",)).fetchall()
    check("R2-048 a personal correction is due at once, hidden while deferred, due again the next day, gone once retired",
          due_now == [(cid, "Oui, je sais nager.")] and due_deferred == [] and due_next == due_now and due_retired == [], (due_now, due_deferred, due_next, due_retired))
    # R2-053/054: a failure between the approval and the attempt.
    week0 = con.execute(WEEK, ("2026-11-16", "2026-11-22")).fetchall()
    decisions0 = con.execute("SELECT count(*) FROM practice_decisions").fetchone()[0]
    con.execute("BEGIN")
    con.execute("INSERT INTO practice_decisions (operation_key, subject_kind, subject_id, source_id, source_revision_sha256, item_hash, action, created_at) "
                "VALUES ('f1', 'extraction_item', 'k-e38255f7d2c0', 'savoir-connaitre-demo', ?, 'h', 'approve', ?)", ("b" * 64, now))
    con.execute("COMMIT")  # the approval is its own write
    try:
        con.execute("BEGIN")
        con.execute("INSERT INTO practice_attempts (operation_key, practice_id, source_id, source_revision_sha256, action, outcome, local_day, zone, created_at) "
                    "VALUES ('f2', 'p-3ca128617083', 'savoir-connaitre-demo', ?, 'attempt', 'correct', '2026-11-19', 'Europe/Paris', ?)", ("b" * 64, now))
        raise RuntimeError("simulated crash before COMMIT")
    except RuntimeError:
        con.execute("ROLLBACK")
    week1 = con.execute(WEEK, ("2026-11-16", "2026-11-22")).fetchall()
    # the same two writes in one transaction: neither survives the crash
    try:
        con.execute("BEGIN")
        con.execute("INSERT INTO practice_decisions (operation_key, subject_kind, subject_id, source_id, source_revision_sha256, item_hash, action, created_at) "
                    "VALUES ('f3', 'extraction_item', 'k-156a01f08b5a', 'savoir-connaitre-demo', ?, 'h', 'approve', ?)", ("b" * 64, now))
        con.execute("INSERT INTO practice_attempts (operation_key, practice_id, source_id, source_revision_sha256, action, outcome, local_day, zone, created_at) "
                    "VALUES ('f4', 'p-baa71166205b', 'savoir-connaitre-demo', ?, 'attempt', 'correct', '2026-11-19', 'Europe/Paris', ?)", ("b" * 64, now))
        raise RuntimeError("simulated crash before COMMIT")
    except RuntimeError:
        con.execute("ROLLBACK")
    decisions1 = con.execute("SELECT count(*) FROM practice_decisions").fetchone()[0]
    check("R2-053 a crash between the approval and the attempt keeps the approval (its own write) and no attempt; one transaction keeps neither",
          decisions1 == decisions0 + 1 and con.execute("SELECT count(*) FROM practice_attempts WHERE operation_key IN ('f2', 'f4')").fetchone()[0] == 0
          and con.execute("SELECT count(*) FROM practice_decisions WHERE operation_key = 'f3'").fetchone()[0] == 0)
    check("R2-054 the week's counts read committed attempts only: an approval or an interrupted write adds nothing",
          week0 == week1 == con.execute(WEEK, ("2026-11-16", "2026-11-22")).fetchall(), (week0, week1))
    # R2-055: a fixture practice session, backed up and restored.
    if visit is None:
        check("R2-055 fixture session backup and restore: run with --visit-export", False, "no --visit-export given")
        return
    n = 0
    for a in visit["attempts"]:
        row = {"operation_key": "visit:" + a["op"], "practice_id": a["practice_id"], "source_id": a["source_id"], "source_revision_sha256": a["revision_sha256"],
               "action": a["action"], "outcome": a["outcome"], "self_check": a.get("self_check") if a["outcome"] in ("self_check", "revealed") else None,
               "answer_text": a.get("answer_text"), "answer_kept": 1 if a.get("answer_text") else 0, "local_day": a["local_day"], "zone": visit["zone"], "created_at": a["at"]}
        n += insert_once(con, "practice_attempts", row) == "created"
    check(f"R2-055 the browser walkthrough's exported visit loads as {n} attempts (schema {visit['schema']}, answer texts {'in' if visit['answer_texts_included'] else 'out'})",
          n == len(visit["attempts"]) and n > 0, n)
    backup = work / "backup-after-session"
    backup.mkdir(mode=0o700)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(work / "scratch.db", backup / "app.db")  # RELEASE.md: cp -a app.db (and its -wal/-shm when present)
    for suffix in ("-wal", "-shm"):
        if (work / f"scratch.db{suffix}").exists():
            shutil.copy2(work / f"scratch.db{suffix}", backup / f"app.db{suffix}")
    b = sqlite3.connect(f"file:{backup / 'app.db'}?mode=ro", uri=True)
    ok_backup = b.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    b.close()
    sums = hashlib.sha256((backup / "app.db").read_bytes()).hexdigest()
    session = snapshot(con)
    con.execute("DELETE FROM practice_attempts WHERE operation_key LIKE 'visit:%'")  # the loss to recover from
    lost = con.execute("SELECT count(*) FROM practice_attempts WHERE operation_key LIKE 'visit:%'").fetchone()[0]
    stage = work / "restored.db"
    shutil.copy2(backup / "app.db", stage)
    r = connect(stage)
    restored = snapshot(r)
    check("R2-055 backup (integrity ok, SHA-256 recorded) and restore give back the session row for row",
          ok_backup and lost == 0 and restored == session and r.execute("PRAGMA integrity_check").fetchone()[0] == "ok", sums[:12])
    r.close()


def main():
    args = sys.argv[1:]
    compare = visit = None
    if "--compare-with" in args:
        i = args.index("--compare-with")
        compare, args = args[i + 1], args[:i] + args[i + 2:]
    if "--visit-export" in args:
        i = args.index("--visit-export")
        visit, args = json.loads(Path(args[i + 1]).read_text(encoding="utf-8")), args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isabs(args[0]):
        print("usage: storage_prototype.py /abs/new/empty/dir [--compare-with SERVER_DB]", file=sys.stderr)
        return 2
    work = Path(os.path.realpath(args[0]))
    if work == REPO or REPO in work.parents:
        print("refused: WORK_DIR must be outside the repository", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        print("refused: WORK_DIR must be new or empty", file=sys.stderr)
        return 2
    results = []

    def check(name, ok, detail=""):
        results.append({"name": name, "pass": bool(ok), "detail": str(detail)[:300]})

    db = work / "scratch.db"
    con = connect(db)
    # The ledger exactly as internal/storage/sqlite/db.go creates it.
    con.execute("CREATE TABLE IF NOT EXISTS schema_migrations (\n\t\tname       TEXT PRIMARY KEY,\n\t\tapplied_at TEXT NOT NULL DEFAULT (datetime('now'))\n\t)")
    files = sorted(p for p in (REPO / "migrations").glob("*.sql"))
    for f in files:
        migrate(con, f.name, f.read_text(encoding="utf-8"))
    ledger = [r[0] for r in con.execute("SELECT name FROM schema_migrations ORDER BY name")]
    check(f"scratch database at ledger {ledger[-1]} ({len(ledger)} migrations)", ledger[-1] == "021_listening_authored_scripts.sql")

    # Synthetic rows in existing tables.
    now = "2026-11-19T10:00:00Z"
    con.execute("INSERT INTO learning_entries (original_input, original_context, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ("Je me suis trompé : j'en vais.", "Synthetic", now, now))
    entry = con.execute("SELECT max(id) FROM learning_entries").fetchone()[0]
    cap_cols = [r[1] for r in con.execute("PRAGMA table_info(learning_captures)")]
    vals = {"capture_id": "storage-proto-1", "entry_id": entry, "content_fingerprint": "f" * 64, "created_at": now, "analysis_id": None,
            "source": "manual", "schema_version": "learning_capture_v1", "discussion_summary": ""}
    cols = [c for c in cap_cols if c in vals]
    con.execute(f"INSERT INTO learning_captures ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [vals[c] for c in cols])
    cap = con.execute("SELECT max(id) FROM learning_captures").fetchone()[0]
    con.execute("INSERT INTO learning_capture_sources (capture_row_id, entry_id, source_type, record_id, item, attempt, created_at) VALUES (?, ?, 'listening_item', 1, 2, NULL, ?)",
                (cap, entry, now))
    con.execute("INSERT INTO mistake_retry_marks (entry_id, marked, created_at) VALUES (?, 1, ?)", (entry, now))
    check("synthetic rows written to existing tables (entry, capture, notebook source, retry mark)", True)

    if compare:
        q = "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        theirs = sqlite3.connect(f"file:{os.path.realpath(compare)}?mode=ro", uri=True).execute(q).fetchall()
        check(f"the scratch 021 schema equals the server-built database ({len(theirs)} objects)", con.execute(q).fetchall() == theirs)
    shutil.copy(db, work / "backup-before-0NN.db")
    before = snapshot(con)

    sql = proposed_sql()
    migrate(con, "0NN_practice_state.sql", sql)
    after = snapshot(con)
    new = sorted({o[1] for o in after[0]} - {o[1] for o in before[0]})
    check("the migration only adds objects: four tables, six indexes and two triggers",
          new == sorted(["practice_decisions", "practice_attempts", "review_defers", "personal_corrections",
                         "idx_practice_decisions_subject", "idx_practice_attempts_item", "idx_review_defers_item", "idx_personal_corrections_subject",
                         "idx_review_defers_one_undo", "idx_personal_corrections_one_retire",
                         "review_defers_undo_targets_defer", "personal_corrections_retire_targets_add"]), new)
    kept = [o for o in after[0] if o[1] in {b[1] for b in before[0]}]
    check("every existing table and index is byte-identical", kept == before[0])
    check("every existing row is unchanged (ledger aside)", all(after[1][t] == before[1][t] for t in before[1] if t != "schema_migrations"))
    check("integrity_check ok, foreign_key_check empty",
          con.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and not con.execute("PRAGMA foreign_key_check").fetchall())

    def ok(stmt, args):
        try:
            con.execute(stmt, args)
            return True
        except sqlite3.IntegrityError:
            return False

    D = "INSERT INTO practice_decisions (operation_key, subject_kind, subject_id, source_id, source_revision_sha256, item_hash, action, edited_text, reason, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
    A = "INSERT INTO practice_attempts (operation_key, practice_id, source_id, source_revision_sha256, action, outcome, self_check, answer_text, local_day, zone, created_at, answer_kept) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
    R = "INSERT INTO review_defers (operation_key, item_key, action, defer_until_day, zone, refers_to, created_at) VALUES (?,?,?,?,?,?,?)"
    C = "INSERT INTO personal_corrections (operation_key, action, subject_kind, subject_ref, subject_version, original_text, corrected_text, refers_to, created_at) VALUES (?,?,?,?,?,?,?,?,?)"
    cases = [
        ("decision: approve", D, ("d1", "extraction_item", "k-0d3281b28da6", "y-en-demo", SHA_A, "h1", "approve", None, None, now), True),
        ("decision: edit with text", D, ("d2", "extraction_item", "k-6c4760ebee9d", "y-en-demo", SHA_A, "h2", "edit", "« y » remplace un lieu introduit par « à ».", None, now), True),
        ("decision: notebook draft, second version", D, ("d3", "notebook_draft", f"notebook:entry:{entry}#2", "notebook", SHA_A, "h3", "edit", "Où étudie Hélène ?", None, now), True),
        ("decision: edit without text refused", D, ("d4", "extraction_item", "k-1", "y-en-demo", SHA_A, "h", "edit", None, None, now), False),
        ("decision: approve with text refused", D, ("d5", "extraction_item", "k-1", "y-en-demo", SHA_A, "h", "approve", "x", None, now), False),
        ("decision: unknown action refused", D, ("d6", "extraction_item", "k-1", "y-en-demo", SHA_A, "h", "maybe", None, None, now), False),
        ("decision: short revision hash refused", D, ("d7", "extraction_item", "k-1", "y-en-demo", "abc", "h", "approve", None, None, now), False),
        ("decision: repeated operation key refused", D, ("d1", "extraction_item", "k-2", "y-en-demo", SHA_A, "h", "approve", None, None, now), False),
        ("attempt: outcome only, no answer text (the default)", A, ("a0", "p-664f7533a19d", "y-en-demo", SHA_A, "attempt", "incorrect", None, None, "2026-11-19", "Europe/Paris", now, 0), True),
        ("attempt: answer text without the opt-in refused", A, ("a0b", "p-664f7533a19d", "y-en-demo", SHA_A, "attempt", "incorrect", None, "Oui, j'y reviens.", "2026-11-19", "Europe/Paris", now, 0), False),
        ("attempt: correct with answer (explicit opt-in)", A, ("a1", "p-8d5cabf2ab59", "y-en-demo", SHA_A, "attempt", "correct", None, "Oui, on y va !", "2026-11-19", "Europe/Paris", now, 1), True),
        ("attempt: self-check with got", A, ("a2", "p-2ea892e5eaa0", "y-en-demo", SHA_A, "attempt", "self_check", "got", "y après à", "2026-11-19", "Europe/Paris", now, 1), True),
        ("reveal: revealed, no answer", A, ("a3", "p-22a947cd7f5c", "y-en-demo", SHA_A, "reveal", "revealed", None, None, "2026-11-19", "Europe/Paris", now, 0), True),
        ("reveal recorded as correct refused", A, ("a4", "p-1", "y-en-demo", SHA_A, "reveal", "correct", None, None, "2026-11-19", "UTC", now, 0), False),
        ("attempt recorded as revealed refused", A, ("a5", "p-1", "y-en-demo", SHA_A, "attempt", "revealed", None, "x", "2026-11-19", "UTC", now, 1), False),
        ("reveal with an answer refused", A, ("a6", "p-1", "y-en-demo", SHA_A, "reveal", "revealed", None, "x", "2026-11-19", "UTC", now, 1), False),
        ("self-check on a correct attempt refused", A, ("a7", "p-1", "y-en-demo", SHA_A, "attempt", "correct", "got", "x", "2026-11-19", "UTC", now, 1), False),
        ("defer with a day", R, ("r1", "speaking:exercise:3", "defer", "2026-11-21", "Europe/Paris", None, now), True),
        ("defer without a day refused", R, ("r2", "speaking:exercise:3", "defer", None, "Europe/Paris", None, now), False),
        ("undo of defer 1", R, ("r3", "speaking:exercise:3", "undo", None, "Europe/Paris", 1, now), True),
        ("undo of an undo refused (trigger)", R, ("r3b", "speaking:exercise:3", "undo", None, "Europe/Paris", 3, now), False),
        ("a second undo of defer 1 refused (one undo per defer)", R, ("r3c", "speaking:exercise:3", "undo", None, "Europe/Paris", 1, now), False),
        ("undo of another item's defer refused (trigger)", R, ("r3d", "notebook:entry:9", "undo", None, "Europe/Paris", 1, now), False),
        ("undo without a target refused", R, ("r4", "speaking:exercise:3", "undo", None, "Europe/Paris", None, now), False),
        ("undo of an unknown defer refused (foreign key)", R, ("r5", "speaking:exercise:3", "undo", None, "Europe/Paris", 999, now), False),
        ("defer of a notebook item", R, ("r6", f"notebook:entry:{entry}", "defer", "2026-11-22", "Europe/Paris", None, now), True),
        ("correction: add", C, ("c1", "add", "speaking_transcript", "speaking:transcript:21", 2, "je viens samedi", "je viendrai samedi", None, now), True),
        ("correction: add without text refused", C, ("c2", "add", "speaking_transcript", "speaking:transcript:21", 2, "x", None, None, now), False),
        ("correction: retire of add 1", C, ("c3", "retire", None, None, None, None, None, 1, now), True),
        ("correction: a second retire of add 1 refused", C, ("c3b", "retire", None, None, None, None, None, 1, now), False),
        ("correction: retire of a retire refused (trigger)", C, ("c3c", "retire", None, None, None, None, None, 3, now), False),
        ("correction: second add", C, ("c4", "add", "extraction_item", "k-6c4760ebee9d", 1, None, "« y » : un lieu avec « à ».", None, now), True),
        ("correction: unknown subject refused", C, ("c5", "add", "chat", "x", 1, None, "y", None, now), False),
    ]
    for name, stmt, args, want in cases:
        got = ok(stmt, args)
        check(f"{name}: {'accepted' if want else 'refused'}", got == want, f"got {'accepted' if got else 'refused'}")

    # The documented current-state queries.
    latest = con.execute("""SELECT d.subject_id, d.action, d.item_hash FROM practice_decisions d
        WHERE d.id = (SELECT max(id) FROM practice_decisions x WHERE x.subject_kind = d.subject_kind AND x.subject_id = d.subject_id)
        ORDER BY d.subject_id""").fetchall()
    current_hash = {"k-0d3281b28da6": "h1", "k-6c4760ebee9d": "changed"}
    states = {s: ("current" if current_hash.get(s, h) == h else "needs_review") for s, _, h in latest}
    check("approval state: a decision counts only while its item hash is current", states.get("k-0d3281b28da6") == "current" and states.get("k-6c4760ebee9d") == "needs_review", states)
    deferred = [r[0] for r in con.execute("""SELECT d.item_key FROM review_defers d WHERE d.action = 'defer'
        AND NOT EXISTS (SELECT 1 FROM review_defers u WHERE u.action = 'undo' AND u.refers_to = d.id)
        AND d.defer_until_day > ? ORDER BY d.item_key""", ("2026-11-19",))]
    check("deferred today: the undone defer is not hidden; the notebook defer is", deferred == [f"notebook:entry:{entry}"], deferred)
    open_corr = [r[0] for r in con.execute("""SELECT c.subject_ref FROM personal_corrections c WHERE c.action = 'add'
        AND NOT EXISTS (SELECT 1 FROM personal_corrections r WHERE r.action = 'retire' AND r.refers_to = c.id)""")]
    check("open corrections: the retired one is gone, the other stays", open_corr == ["k-6c4760ebee9d"], open_corr)
    outcomes = con.execute("SELECT practice_id, action, outcome FROM practice_attempts ORDER BY id").fetchall()
    check("attempt outcomes read as the feed reports them (reveal kept apart from correct)",
          outcomes == [("p-664f7533a19d", "attempt", "incorrect"), ("p-8d5cabf2ab59", "attempt", "correct"), ("p-2ea892e5eaa0", "attempt", "self_check"),
                       ("p-22a947cd7f5c", "reveal", "revealed")], outcomes)
    increment5(con, check, work, visit, now)
    con.close()

    # Rollback: restore the pre-migration backup at the same path.
    os.replace(work / "backup-before-0NN.db", db)
    con = connect(db)
    restored = snapshot(con)
    check("rollback restores the pre-migration schema, ledger and rows exactly", restored == before)
    check("after the rollback the ledger ends at 021 again",
          con.execute("SELECT max(name) FROM schema_migrations").fetchone()[0] == "021_listening_authored_scripts.sql")
    con.close()

    (work / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    failed = [r for r in results if not r["pass"]]
    print(f"{len(results) - len(failed)}/{len(results)} PASS")
    for r in results:
        print("PASS" if r["pass"] else "FAIL", r["name"], "" if r["pass"] else r["detail"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
