#!/usr/bin/env python3
"""Check revision 3 of the PROPOSED practice storage on scratch databases only (R3-041..R3-049).

    python3 -I -B scripts/validation/extraction_practice/storage_r3.py WORK_DIR --rows STORAGE_ROWS_JSON [--scale N]

WORK_DIR must be absolute, outside the repository, and new or empty. Nothing is added to
migrations/: the three SQL blocks (minimum, optional A retention, optional B decisions) are read
from docs/plans/PRACTICE-STORAGE-DECISION.md. STORAGE_ROWS_JSON is the extraction lane's sealed
round-trip rows (Extraction 2.2 `sample/workbooks2/storage-rows.json`); its feeds beside it give
the practice IDs of a withdrawal and restore.

  minimum     on a scratch 001-021 database with synthetic rows: only its objects are added, every
              existing object and row is unchanged; attempts have no text column (R3-043); attempts
              and defers are append-only (update and delete refused)
  retention   optional A after the minimum: text refused without the learner's decision, kept while
              it says keep, refused again once it says stop, never on a reveal; erasing the text is
              the one allowed update (R3-044)
  decisions   optional B: the amended decisions (agent_exercise, provenance_json) and corrections
  round trip  the sealed rows load (12 decisions incl. agent exercises, 2 attempts with text once the
              learner keeps text, or without it); loading them again replays every row; a changed
              payload under a used key is a conflict (R3-045)
  reload      attempts, a defer and its undo, written across the 2.2 feeds' withdrawal and restore,
              read back after closing and reopening the database: the derived state is identical and
              the withdrawn item's history is kept (R3-047)
  scale       a scratch database grown to N learner entries with N notebook records and marks
              (default 100000) and 2N practice attempts after the migration: size, backup copy and
              integrity, migration and rollback (restore) times (R3-048)
  after       rows written after the backup are exactly what a restore discards (R3-049)
  rollback    restoring the pre-migration copy gives the 021 schema, ledger and rows back
Writes WORK_DIR/results.json and prints one PASS/FAIL line per check. Exit 0 when all pass.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
from storage_prototype import connect, insert_once, migrate, snapshot  # noqa: E402

DOC = REPO / "docs/plans/PRACTICE-STORAGE-DECISION.md"
SHA_A = "a" * 64
NOW = "2026-11-20T09:00:00Z"


def block(name: str) -> str:
    text = DOC.read_text(encoding="utf-8")
    m = re.search(rf"<!-- proposed-sql-{name}:start -->\s*```sql\n(.*?)```\s*<!-- proposed-sql-{name}:end -->", text, re.S)
    if not m:
        raise SystemExit(f"no proposed SQL block {name!r} in {DOC.name}")
    return m.group(1)


def build021(db: Path):
    con = connect(db)
    con.execute("CREATE TABLE IF NOT EXISTS schema_migrations (\n\t\tname       TEXT PRIMARY KEY,\n\t\tapplied_at TEXT NOT NULL DEFAULT (datetime('now'))\n\t)")
    for f in sorted((REPO / "migrations").glob("*.sql")):
        migrate(con, f.name, f.read_text(encoding="utf-8"))
    con.execute("INSERT INTO learning_entries (original_input, original_context, created_at, updated_at) VALUES ('Synthétique', '', ?, ?)", (NOW, NOW))
    return con


def refused(con, sql, args=()):
    try:
        con.execute(sql, args)
        return False
    except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
        return str(e) or True


def main():
    args = sys.argv[1:]
    opts = {"--rows": None, "--scale": "100000"}
    for k in list(opts):
        if k in args:
            i = args.index(k)
            opts[k] = args[i + 1]
            args = args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isabs(args[0]) or not opts["--rows"]:
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
    rows_doc = json.loads(Path(opts["--rows"]).read_text(encoding="utf-8"))
    feeds = sorted(Path(opts["--rows"]).parent.glob("feed-*.json"))
    scale = int(opts["--scale"])
    results = []

    def check(name, ok, detail=""):
        results.append({"name": name, "pass": bool(ok), "detail": str(detail)[:400]})
        print("PASS" if ok else "FAIL", name, "" if ok else str(detail)[:300], flush=True)

    mini, keep, deci = block("r3-minimum"), block("r3-retention"), block("r3-decisions")
    db = work / "scratch.db"
    con = build021(db)
    shutil.copy(db, work / "before-0NN.db")
    before = snapshot(con)
    migrate(con, "0NN_practice_state.sql", mini)
    after = snapshot(con)
    added = sorted({o[1] for o in after[0]} - {o[1] for o in before[0]})
    check(f"minimum: only its objects are added ({len(added)}): {', '.join(added)}",
          added == sorted(["practice_attempts", "review_defers", "idx_practice_attempts_item", "idx_practice_attempts_day", "idx_review_defers_item",
                           "idx_review_defers_one_undo", "practice_attempts_no_delete", "practice_attempts_no_update", "review_defers_undo_targets_defer",
                           "review_defers_no_change", "review_defers_no_delete"]), added)
    check("minimum: every existing object and row is unchanged", [o for o in after[0] if o[1] in {b[1] for b in before[0]}] == before[0]
          and all(after[1][t] == before[1][t] for t in before[1] if t != "schema_migrations"))
    A = "INSERT INTO practice_attempts (operation_key, practice_id, source_id, source_revision, source_revision_sha256, action, outcome, self_check, local_day, zone, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
    con.execute(A, ("k1", "p-cf2ec01246c8", "a-en-lieux-demo", 1, SHA_A, "attempt", "incorrect", None, "2026-11-20", "Europe/Paris", NOW))
    check("R3-043 minimum: an attempt has no text column at all", bool(refused(con, "INSERT INTO practice_attempts (operation_key, practice_id, source_id, source_revision_sha256, action, outcome, local_day, zone, created_at, answer_text) VALUES ('k0', 'p-cf2ec01246c8', 's', ?, 'attempt', 'correct', 'd', 'z', ?, 'x')", (SHA_A, NOW))))
    check("minimum: attempts are append-only (update and delete refused)", bool(refused(con, "UPDATE practice_attempts SET outcome = 'correct'")) and bool(refused(con, "DELETE FROM practice_attempts")))
    check("minimum: a reveal recorded as correct and a malformed practice ID are refused",
          bool(refused(con, A, ("k2", "p-cf2ec01246c8", "s", 1, SHA_A, "reveal", "correct", None, "d", "z", NOW))) and bool(refused(con, A, ("k3", "x-1", "s", 1, SHA_A, "attempt", "correct", None, "d", "z", NOW))))
    # optional A: retention
    migrate(con, "0NN_practice_state_text.sql", keep)
    AT = "INSERT INTO practice_attempts (operation_key, practice_id, source_id, source_revision, source_revision_sha256, action, outcome, self_check, local_day, zone, created_at, answer_text) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
    R = "INSERT INTO practice_text_retention (operation_key, keep_answer_text, created_at) VALUES (?,?,?)"
    no_choice = refused(con, AT, ("t1", "p-10a28f330355", "s", 1, SHA_A, "attempt", "correct", None, "2026-11-20", "Europe/Paris", NOW, "à"))
    con.execute(R, ("r1", 1, NOW))
    kept = not refused(con, AT, ("t2", "p-10a28f330355", "s", 1, SHA_A, "attempt", "correct", None, "2026-11-20", "Europe/Paris", NOW, "à"))
    reveal_text = refused(con, AT, ("t3", "p-10a28f330355", "s", 1, SHA_A, "reveal", "revealed", None, "2026-11-20", "Europe/Paris", NOW, "à"))
    con.execute(R, ("r2", 0, NOW))
    stopped = refused(con, AT, ("t4", "p-10a28f330355", "s", 1, SHA_A, "attempt", "correct", None, "2026-11-20", "Europe/Paris", NOW, "à"))
    still_outcome = not refused(con, AT, ("t5", "p-10a28f330355", "s", 1, SHA_A, "attempt", "correct", None, "2026-11-20", "Europe/Paris", NOW, None))
    erase = not refused(con, "UPDATE practice_attempts SET answer_text = NULL WHERE operation_key = 't2'")
    other = refused(con, "UPDATE practice_attempts SET outcome = 'incorrect' WHERE operation_key = 't2'")
    retention_upd = refused(con, "UPDATE practice_text_retention SET keep_answer_text = 1")
    check("R3-044 text needs the learner's own decision: refused with no decision, kept while it says keep, never on a reveal, refused once it says stop; outcomes stay recordable",
          bool(no_choice) and kept and bool(reveal_text) and bool(stopped) and still_outcome, (no_choice, kept, reveal_text, stopped))
    check("R3-044 erasing a kept text is the one allowed update; any other update, and changing a past decision, are refused",
          erase and bool(other) and bool(retention_upd) and con.execute("SELECT answer_text FROM practice_attempts WHERE operation_key = 't2'").fetchone()[0] is None)
    # optional B: decisions
    migrate(con, "0NN_practice_state_decisions.sql", deci)
    rows = rows_doc["rows"]["amended"]
    dec_cols = ["operation_key", "subject_kind", "subject_id", "source_id", "source_revision_sha256", "item_hash", "action", "edited_text", "reason", "provenance_json", "created_at"]
    loaded = [insert_once(con, "practice_decisions", {c: r.get(c) for c in dec_cols}) for r in rows["practice_decisions"]]
    kinds = sorted({r["subject_kind"] for r in rows["practice_decisions"]})
    check(f"R3-041 the sealed 2.2 decisions load under the amendment: {loaded.count('created')}/{len(loaded)} ({', '.join(kinds)}; provenance kept as JSON)",
          loaded == ["created"] * len(loaded) and "agent_exercise" in kinds and con.execute("SELECT count(*) FROM practice_decisions WHERE json_valid(provenance_json)").fetchone()[0] > 0, loaded)
    att_cols = ["operation_key", "practice_id", "source_id", "source_revision_sha256", "action", "outcome", "self_check", "local_day", "zone", "created_at", "answer_text"]
    with_text_refused = [refused(con, f"INSERT INTO practice_attempts ({', '.join(att_cols)}) VALUES ({', '.join('?' for _ in att_cols)})", [r.get(c) for c in att_cols]) for r in rows["practice_attempts"]]
    con.execute(R, ("r3", 1, NOW))
    att = [insert_once(con, "practice_attempts", {c: r.get(c) for c in att_cols}) for r in rows["practice_attempts"]]
    check("R3-045 the sealed attempts with text load only once the learner keeps text (refused before), and each keeps its outcome",
          all(with_text_refused) and att == ["created"] * len(att), (with_text_refused, att))
    replay = [insert_once(con, "practice_decisions", {c: r.get(c) for c in dec_cols}) for r in rows["practice_decisions"]] + \
             [insert_once(con, "practice_attempts", {c: r.get(c) for c in att_cols}) for r in rows["practice_attempts"]]
    changed = dict(rows["practice_attempts"][0], outcome="incorrect")
    conflict = insert_once(con, "practice_attempts", {c: changed.get(c) for c in att_cols})
    check(f"R3-045 loading the same rows again replays all {len(replay)}; a changed payload under a used key is a conflict, never an overwrite",
          set(replay) == {"replayed"} and conflict == "conflict", (set(replay), conflict))
    # reload across the 2.2 feeds
    offered = []
    for f in feeds:
        fd = json.loads(f.read_text(encoding="utf-8"))
        offered.append({"feed": f.name, "items": {i["practice_id"] for i in fd["items"]}, "withdrawn": {w["practice_id"]: w.get("reason_code") for w in fd.get("withdrawn", [])}})
    pid = "p-3e03bff58a01"
    D = "INSERT INTO review_defers (operation_key, item_key, action, defer_until_day, zone, refers_to, created_at) VALUES (?,?,?,?,?,?,?)"
    con.execute(A, ("h1", pid, "a-en-lieux-demo", 1, SHA_A, "attempt", "incorrect", None, "2026-11-20", "Europe/Paris", NOW))
    con.execute(D, ("d1", f"practice:{pid}", "defer", "2026-11-22", "Europe/Paris", None, NOW))
    did = con.execute("SELECT id FROM review_defers WHERE operation_key = 'd1'").fetchone()[0]
    con.execute(D, ("d2", f"practice:{pid}", "undo", None, "Europe/Paris", did, NOW))
    con.execute(D, ("d3", "practice:p-919b6c108284", "defer", "2026-11-22", "Europe/Paris", None, NOW))

    def state(c, feed):
        hist = c.execute("SELECT practice_id, action, outcome, source_revision FROM practice_attempts ORDER BY id").fetchall()
        deferred = sorted(r[0] for r in c.execute("""SELECT d.item_key FROM review_defers d WHERE d.action = 'defer'
            AND NOT EXISTS (SELECT 1 FROM review_defers u WHERE u.action = 'undo' AND u.refers_to = d.id) AND d.defer_until_day > '2026-11-20'"""))
        latest = {r[0]: r[1] for r in c.execute("SELECT practice_id, outcome FROM practice_attempts a WHERE id = (SELECT max(id) FROM practice_attempts b WHERE b.practice_id = a.practice_id)")}
        return {"history": hist, "deferred": deferred, "latest": latest, "offered": sorted(feed["items"] - {d[len('practice:'):] for d in deferred}),
                "withdrawn_with_history": sorted(p for p in feed["withdrawn"] if any(h[0] == p for h in hist))}

    states = [state(con, f) for f in offered]
    con.close()
    con = connect(db)  # the reload
    again = [state(con, f) for f in offered]
    by_feed = {o["feed"]: s for o, s in zip(offered, again)}
    check("R3-047 after closing and reopening the database, the derived state is identical for every 2.2 feed (history, defers and undo, latest outcomes, what is offered)", states == again)
    check(f"R3-047 the withdrawn exercise {pid} keeps its history while withdrawn (rule_not_approved, then awaiting_confirmation) and is offered again with the same history once restored",
          all(by_feed[f]["withdrawn_with_history"] == [pid] for f in ("feed-3-r2-withdrawn.json", "feed-4-r3-awaiting-confirmation.json"))
          and pid in by_feed["feed-5-r3-restored.json"]["offered"] and by_feed["feed-5-r3-restored.json"]["history"] == by_feed["feed-3-r2-withdrawn.json"]["history"],
          {k: v["withdrawn_with_history"] for k, v in by_feed.items()})
    check("R3-047 the undone defer is not hidden; the other defer hides its item until its day", by_feed["feed-5-r3-restored.json"]["deferred"] == ["practice:p-919b6c108284"])
    # post-backup writes and rollback
    con.close()
    shutil.copy(db, work / "backup-after-0NN.db")
    con = connect(db)
    con.execute(A, ("late1", "p-cf2ec01246c8", "a-en-lieux-demo", 3, SHA_A, "attempt", "correct", None, "2026-11-20", "Europe/Paris", NOW))
    con.execute(D, ("late2", "practice:p-cf2ec01246c8", "defer", "2026-11-23", "Europe/Paris", None, NOW))
    late = {t: con.execute(f"SELECT count(*) FROM {t} WHERE operation_key LIKE 'late%'").fetchone()[0] for t in ("practice_attempts", "review_defers")}
    con.close()
    shutil.copy(work / "backup-after-0NN.db", db)
    con = connect(db)
    gone = {t: con.execute(f"SELECT count(*) FROM {t} WHERE operation_key LIKE 'late%'").fetchone()[0] for t in ("practice_attempts", "review_defers")}
    check(f"R3-049 rows written after the backup are exactly what restoring it discards: {late} written, {gone} left", late == {"practice_attempts": 1, "review_defers": 1} and gone == {"practice_attempts": 0, "review_defers": 0})
    con.close()
    os.replace(work / "before-0NN.db", db)
    con = connect(db)
    check("rollback: restoring the pre-migration copy gives the 021 schema, ledger and rows back", snapshot(con) == before
          and con.execute("SELECT max(name) FROM schema_migrations").fetchone()[0] == "021_listening_authored_scripts.sql")
    con.close()
    # scale
    big = work / "big.db"
    con = build021(big)
    t = time.time()
    con.execute("BEGIN")
    cap_cols = [r[1] for r in con.execute("PRAGMA table_info(learning_captures)")]
    con.execute("INSERT INTO listening_materials (source_kind, video_id, source_url, title, created_at) VALUES ('youtube', 'abcdefghijk', 'https://www.youtube.com/watch?v=abcdefghijk', 'Synthétique', ?)", (NOW,))
    con.execute("INSERT INTO listening_transcripts (material_id, version, segments, has_timestamps, created_at) VALUES (1, 1, '[]', 0, ?)", (NOW,))
    con.execute("INSERT INTO listening_exercises (material_id, transcript_id, status, generator, content, created_at) VALUES (1, 1, 'completed', 'openai:m:listening_exercise_v1', '{\"items\":[{}]}', ?)", (NOW,))
    for i in range(scale):
        con.execute("INSERT INTO learning_entries (original_input, original_context, created_at, updated_at) VALUES (?, ?, ?, ?)", (f"Phrase synthétique {i} : j'en reviens.", "Contexte synthétique", NOW, NOW))
        eid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        vals = {"capture_id": f"scale-{i}", "entry_id": eid, "content_fingerprint": hashlib.sha256(str(i).encode()).hexdigest(), "created_at": NOW, "source": "manual",
                "schema_version": "learning_capture_v1", "discussion_summary": ""}
        use = [c for c in cap_cols if c in vals]
        con.execute(f"INSERT INTO learning_captures ({', '.join(use)}) VALUES ({', '.join('?' for _ in use)})", [vals[c] for c in use])
        cid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.execute("INSERT INTO learning_capture_sources (capture_row_id, entry_id, source_type, record_id, item, attempt, created_at) VALUES (?, ?, 'listening_item', 1, ?, NULL, ?)", (cid, eid, i + 1, NOW))
        con.execute("INSERT INTO mistake_retry_marks (entry_id, marked, created_at) VALUES (?, 1, ?)", (eid, NOW))
    con.execute("COMMIT")
    fill_s = time.time() - t
    con.close()
    size_mb = big.stat().st_size / 1e6
    t = time.time()
    shutil.copy2(big, work / "big-backup.db")
    ok_b = subprocess_ok(work / "big-backup.db")
    backup_s = time.time() - t
    con = connect(big)
    t = time.time()
    migrate(con, "0NN_practice_state.sql", mini)
    migrate(con, "0NN_practice_state_text.sql", keep)
    migrate(con, "0NN_practice_state_decisions.sql", deci)
    migrate_s = time.time() - t
    t = time.time()
    con.execute("BEGIN")
    for i in range(2 * scale):
        con.execute(A, (f"s{i}", "p-%012x" % (i % 997), "scale-demo", 1, SHA_A, "attempt", ("correct", "incorrect", "self_check")[i % 3], None, "2026-11-%02d" % (1 + i % 28), "Europe/Paris", NOW))
    con.execute("COMMIT")
    attempts_s = time.time() - t
    q = time.time()
    con.execute("SELECT local_day, count(*) FROM practice_attempts WHERE local_day BETWEEN '2026-11-16' AND '2026-11-22' GROUP BY 1").fetchall()
    week_ms = (time.time() - q) * 1000
    plan = " / ".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN SELECT local_day, count(*) FROM practice_attempts WHERE local_day BETWEEN '2026-11-16' AND '2026-11-22' GROUP BY 1"))
    con.close()
    size2_mb = big.stat().st_size / 1e6
    t = time.time()
    shutil.copy2(work / "big-backup.db", big)
    ok_r = subprocess_ok(big)
    rollback_s = time.time() - t
    measures = {"learner_entries": scale, "notebook_records": scale, "db_mb_before": round(size_mb, 1), "fill_s": round(fill_s, 1), "backup_copy_and_integrity_s": round(backup_s, 2),
                "migration_s": round(migrate_s, 3), "attempts_written": 2 * scale, "attempts_write_s": round(attempts_s, 1), "db_mb_after_attempts": round(size2_mb, 1),
                "week_count_query_ms": round(week_ms, 1), "week_count_plan": plan, "rollback_restore_and_integrity_s": round(rollback_s, 2)}
    (work / "scale.json").write_text(json.dumps(measures, indent=1))
    check(f"R3-048 at scale: {size_mb:.0f} MB database ({scale} entries and notebook records), backup copy + integrity {backup_s:.2f} s, migration {migrate_s * 1000:.0f} ms, "
          f"{2 * scale} attempts {size2_mb:.0f} MB, week count {week_ms:.0f} ms ({plan}), rollback (restore + integrity) {rollback_s:.2f} s",
          ok_b and ok_r and "idx_practice_attempts_day" in plan, measures)
    (work / "results.json").write_text(json.dumps(results, indent=1))
    failed = [r for r in results if not r["pass"]]
    print(f"{len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed else 0


def subprocess_ok(db: Path) -> bool:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
