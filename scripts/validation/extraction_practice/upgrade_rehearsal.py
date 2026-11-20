#!/usr/bin/env python3
"""Rehearse the PROPOSED practice migration (0NN) on a throwaway database with the real server.

    python3 -I -B scripts/validation/extraction_practice/upgrade_rehearsal.py WORK_DIR

WORK_DIR must be absolute, outside the repository, and new or empty. No migration file is
added: the proposed SQL is read from docs/plans/PRACTICE-STORAGE-DECISION.md. The server is
built from this tree (it knows migrations 001-021 only) and runs on 127.0.0.1, a free port, an
empty environment and every provider disabled. Stages:

  populate   scripts/demo/learning_day/seed.py fills a fresh database through the API; the
             authored script ls-wb1-u05 is then revised BY THE SERVER (script-update preview,
             confirmation): an already-revised exercise, revision 2, with mistakes saved from 1;
  before     the reads a learner depends on (lesson, its revisions, Review Today, the learning
             week) and a history export are recorded; the server stops;
  backup     as docs/RELEASE.md: copy, integrity_check, SHA-256;
  upgrade    the proposed SQL and its ledger row in one transaction, as the server migrates;
             only the new objects appear;
  after      the same server (older than 0NN) starts on the upgraded database: every read is
             identical, the revised exercise is still revision 2, the export before the
             upgrade is inspected by import-preview (complete, 0 new, 0 conflicts) and a new
             export equals it (R2-057);
  writes     rows a 0NN server would write go into the four tables, and a learner capture is
             added through the API (data written after the backup);
  rollback   the backup is restored: ledger 021, reads identical to before, and exactly the
             post-backup writes are gone (the documented data-loss boundary, R2-056).
Writes WORK_DIR/results.json; prints one PASS/FAIL line per check. Exit 0 when all pass.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.dont_write_bytecode = True  # never write __pycache__ into the repository
sys.path.insert(0, str(REPO / "scripts/validation/compat"))
sys.path.insert(0, str(HERE))
from older_fixtures import Server, call, ledger, sha  # noqa: E402
from storage_prototype import connect, migrate, proposed_sql, snapshot  # noqa: E402

VOLATILE = {"generated_at", "exported_at", "now", "today"}


def strip(x):
    if isinstance(x, dict):
        return {k: strip(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [strip(v) for v in x]
    return x


def ndjson(body: bytes):
    return [strip(json.loads(line)) for line in body.decode("utf-8").splitlines() if line.strip()]


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
    results = []

    def check(name, ok, detail=""):
        results.append({"name": name, "pass": bool(ok), "detail": str(detail)[:400]})
        print("PASS" if ok else "FAIL", name, "" if ok else str(detail)[:400])

    binary = work / "bin" / "server"
    subprocess.run(["go", "build", "-trimpath", "-o", str(binary), "./cmd/server"], cwd=REPO, env=dict(os.environ, GOFLAGS="-buildvcs=false"), check=True)
    d = work / "live"
    d.mkdir()
    db = d / "app.db"

    def reads(base, mid):
        out = {}
        for path in (f"/listening/materials/{mid}", f"/listening/materials/{mid}/revisions", "/review-today?zone=Europe/Paris",
                     "/learning-week?zone=Europe/Paris", "/mistake-notebook/items"):
            s, body = call(base, "GET", path)
            out[path] = [s, strip(body)]
        s, exp = call(base, "GET", "/learning-history/export?transcripts=true&notes=true", raw=True)
        return out, exp

    # populate
    srv = Server(binary, d, db)
    assert srv.ready(), "server did not start"
    try:
        seed = subprocess.run([sys.executable, "-I", str(REPO / "scripts/demo/learning_day/seed.py"), srv.url, str(db)], capture_output=True, text=True)
        check("populate: the learning-day seed fills the fresh database through the API", seed.returncode == 0, seed.stdout[-300:] + seed.stderr[-300:])
        s, mats = call(srv.url, "GET", "/listening/materials")
        items = mats if isinstance(mats, list) else mats.get("items", mats.get("materials", []))
        mats = [m.get("material", m) for m in items]
        mid = next(m["id"] for m in mats if (m.get("pack_script_id") or "").endswith("/ls-wb1-u05"))
        s, pv = call(srv.url, "GET", f"/listening/materials/{mid}/script-update")
        check("populate: the server offers the pack update for revision 1", s == 200 and pv.get("current_revision") == 1 and pv.get("next_revision") == 2, (s, pv if s != 200 else {k: pv.get(k) for k in ("current_revision", "next_revision", "pack_status")}))
        s, up = call(srv.url, "POST", f"/listening/materials/{mid}/script-update", {"from_revision": 1, "pack_fingerprint": pv["pack_fingerprint"]})
        s2, lesson = call(srv.url, "GET", f"/listening/materials/{mid}")
        rev = (lesson.get("script_revision") or {}).get("revision") if s2 == 200 else None
        check("populate: the server appended revision 2 (an already-revised exercise; mistakes stay on revision 1)", s in (200, 201) and rev == 2, (s, rev))
        before, exp_before = reads(srv.url, mid)
        check("before: every read answers 200 and the export is non-empty", all(v[0] == 200 for v in before.values()) and len(ndjson(exp_before)) > 1, {k: v[0] for k, v in before.items()})
        (work / "export-before.ndjson").write_bytes(exp_before)
    finally:
        srv.stop()

    # backup (docs/RELEASE.md: cp -a app.db and its sidecars, integrity_check, SHA256SUMS)
    backup = work / "backup"
    backup.mkdir(mode=0o700)
    for suffix in ("", "-wal", "-shm"):
        if (d / f"app.db{suffix}").exists():
            shutil.copy2(d / f"app.db{suffix}", backup / f"app.db{suffix}")
    led, ok = ledger(backup / "app.db")
    backup_sha = sha(backup / "app.db")
    check(f"backup: integrity {ok}, ledger ends at {led[-1]}, SHA-256 {backup_sha[:12]}…", ok == "ok" and led[-1] == "021_listening_authored_scripts.sql")

    # upgrade
    con = connect(db)
    pre = snapshot(con)
    migrate(con, "0NN_practice_state.sql", proposed_sql())
    post = snapshot(con)
    added = sorted({o[1] for o in post[0]} - {o[1] for o in pre[0]})
    kept = [o for o in post[0] if o[1] in {b[1] for b in pre[0]}]
    check(f"upgrade: only the proposed objects are added ({len(added)}), every existing object and row unchanged",
          len(added) == 12 and kept == pre[0] and all(post[1][t] == pre[1][t] for t in pre[1] if t != "schema_migrations"), added)
    con.close()

    # after: the server that does not know 0NN
    srv = Server(binary, d, db)
    started = srv.ready()
    check("after: the current server (without 0NN) starts on the upgraded database", started)
    try:
        after, exp_after = reads(srv.url, mid)
        diff = [k for k in before if before[k] != after[k]]
        check("after: lesson, revisions, Review Today, the week and the notebook read exactly as before", not diff, diff)
        s, lesson = call(srv.url, "GET", f"/listening/materials/{mid}")
        check("after: the revised exercise is still revision 2", (lesson.get("script_revision") or {}).get("revision") == 2)
        s, p = call(srv.url, "POST", "/learning-history/import-preview", body=exp_before)
        check("R2-057 the export made before the upgrade is inspected on the upgraded server: complete, 0 new, 0 conflicts",
              s == 200 and p["integrity"] == "complete" and p["new"] == 0 and p["conflicts"] == 0, p if s == 200 else s)
        check("R2-057 a new export equals the one made before the upgrade (volatile header fields aside)", ndjson(exp_after) == ndjson(exp_before))
        # writes after the backup: a capture through the API, and rows a 0NN server would write
        s, cap = call(srv.url, "POST", "/captures", {"schema_version": "learning_capture_v1", "capture_id": "after-backup-1", "source": "manual",
                                                     "original_input": "Après la sauvegarde : j'en reviens.", "original_context": "synthetic"})
        check("writes: a learner capture added after the backup", s in (200, 201), (s, cap))
    finally:
        srv.stop()
    con = connect(db)
    now = "2026-11-19T12:00:00Z"
    con.execute("INSERT INTO practice_attempts (operation_key, practice_id, source_id, source_revision_sha256, action, outcome, local_day, zone, created_at) "
                "VALUES ('u1', 'p-664f7533a19d', 'y-en-demo', ?, 'attempt', 'correct', '2026-11-19', 'Europe/Paris', ?)", ("a" * 64, now))
    con.execute("INSERT INTO review_defers (operation_key, item_key, action, defer_until_day, zone, created_at) VALUES ('u2', 'practice:p-664f7533a19d', 'defer', '2026-11-21', 'Europe/Paris', ?)", (now,))
    counts_after = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("learning_entries", "learning_captures", "practice_attempts", "review_defers")}
    con.close()

    # rollback: restore the backup
    for suffix in ("", "-wal", "-shm"):
        p = d / f"app.db{suffix}"
        if p.exists():
            p.unlink()
    for suffix in ("", "-wal", "-shm"):
        if (backup / f"app.db{suffix}").exists():
            shutil.copy2(backup / f"app.db{suffix}", d / f"app.db{suffix}")
    led, ok = ledger(db)
    check("rollback: the restored database ends at 021 again, integrity ok", led[-1] == "021_listening_authored_scripts.sql" and ok == "ok", led[-1])
    con = sqlite3.connect(db)
    counts_back = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("learning_entries", "learning_captures")}
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    con.close()
    lost = {"learning_entries": counts_after["learning_entries"] - counts_back["learning_entries"], "learning_captures": counts_after["learning_captures"] - counts_back["learning_captures"],
            "practice_attempts": counts_after["practice_attempts"], "review_defers": counts_after["review_defers"]}
    check("R2-056 rollback loses exactly what was written after the backup: 1 capture (+ its entry) and every practice row; the four tables are gone",
          lost == {"learning_entries": 1, "learning_captures": 1, "practice_attempts": 1, "review_defers": 1} and not ({"practice_attempts", "review_defers"} & tables), lost)
    srv = Server(binary, d, db)
    check("rollback: the server starts on the restored database", srv.ready())
    try:
        back, exp_back = reads(srv.url, mid)
        check("rollback: every read equals the pre-upgrade reads, and the export too", back == before and ndjson(exp_back) == ndjson(exp_before),
              [k for k in before if before[k] != back.get(k)])
    finally:
        srv.stop()
    (work / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    failed = [r for r in results if not r["pass"]]
    print(f"{len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
