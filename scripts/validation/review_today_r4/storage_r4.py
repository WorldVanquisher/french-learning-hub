#!/usr/bin/env python3
"""The R4 practice storage proposal on a populated scratch database: upgrade, links, rollback.

    python3 -I scripts/validation/review_today_r4/storage_r4.py WORK --db PROFILE_DB --binary SERVER [--old-binary SERVER]

WORK must be absolute, outside the repository, and new or empty. PROFILE_DB is a stopped database
seeded with the R4 profile (its directory holds profile.json); it is only copied. The SQL comes from
docs/plans/R4-PRACTICE-STORAGE-PROPOSAL.md (between the r4-forward and r4-rollback markers); no
repository migration exists or is created.

  upgrade   forward SQL on a copy; the original tables' digests unchanged (inventory --expect)
  links     outcomes, defers and a retention decision written for the profile's queue items; foreign
            keys hold; item_key cannot disagree with its record; unknown records are refused;
            append-only triggers refuse an update and a delete (R4-WB-037, R4-WB-038)
  serve     the current server on the upgraded copy reads Review Today, the notebook and the
            Speaking exercise exactly as before; so does --old-binary (start tree)
  rollback  the rows that cannot survive are counted; rollback SQL leaves the pre-upgrade schema
            and the same logical digest (R4-WB-039)
Writes WORK/storage_r4.json. Exit 0 when every check passes, 1 otherwise, 2 refused.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
from restore_learning import Server, call  # noqa: E402

DOC = REPO / "docs/plans/R4-PRACTICE-STORAGE-PROPOSAL.md"
INV = REPO / "scripts/validation/migration/inventory.py"
RESULTS, FAILED = [], []


def check(name, ok, detail=""):
    RESULTS.append({"check": name, "pass": bool(ok), "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name} {'' if ok else detail}".rstrip(), flush=True)
    if not ok:
        FAILED.append(name)


def block(marker):
    s = DOC.read_text(encoding="utf-8")
    m = re.search(rf"<!-- {marker}:start -->\s*```sql\n(.*?)```\s*<!-- {marker}:end -->", s, re.S)
    return m.group(1)


def schema(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return sorted(con.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall())
    finally:
        con.close()


def inventory(src, out, expect=None):
    cmd = [sys.executable, "-I", "-B", str(INV), str(src), "--out", str(out)] + (["--expect", str(expect)] if expect else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, json.loads((out / "inventory.json").read_text())


def reads(binary, db, d, facts):
    s = Server(binary, db, d)
    try:
        _, today = call(s.url, "GET", "/review-today?zone=Europe/Paris")
        _, nb = call(s.url, "GET", "/mistake-notebook/items")
        _, ex = call(s.url, "GET", f"/speaking/exercises/{facts['speaking_exercise']}")
        return s.ok, {"today": [(it["key"], it["reason"]) for it in today["items"]], "notebook": [(it["entry_id"], it["retry"]["marked"]) for it in nb["items"]],
                      "speaking": [(t["take_id"], t["version"], t["origin"]) for t in ex["transcripts"]]}
    finally:
        s.stop()


def main():
    args = sys.argv[1:]
    opts = {"--db": None, "--binary": None, "--old-binary": None}
    for k in list(opts):
        if k in args:
            i = args.index(k)
            opts[k] = args[i + 1]
            args = args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isabs(args[0]) or not opts["--db"] or not opts["--binary"]:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    w = Path(os.path.realpath(args[0]))
    if w == REPO or REPO in w.parents or (w.exists() and any(w.iterdir())):
        print("refused: WORK must be outside the repository and new or empty", file=sys.stderr)
        return 2
    src = Path(opts["--db"])
    facts = json.loads((src.parent / "profile.json").read_text())
    data = w / "data"
    data.mkdir(parents=True)
    for sfx in ("", "-wal", "-shm"):
        if Path(str(src) + sfx).exists():
            shutil.copy2(str(src) + sfx, data / ("app.db" + sfx))
    db = data / "app.db"
    _, before_reads = reads(Path(opts["--binary"]), db, w / "run-before", facts)
    code, base = inventory(data, w / "inv-before")
    before_schema = schema(db)

    # upgrade
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(block("r4-forward"))
    con.commit()
    code, up = inventory(data, w / "inv-up", w / "inv-before" / "inventory.json")
    check("upgrade: the original tables keep their digests and rows", not up["expect"]["missing"] and not up["expect"]["content_differs"], up["expect"])
    # links
    now, zone, day = "2026-11-20T09:00:00Z", "Europe/Paris", "2026-11-20"
    queue = [q["key"] for q in facts["queue"]]
    n = 0
    for k in queue:
        kind, ident = k.split(":")[0], int(k.split(":")[2])
        col = "entry_id" if kind == "notebook" else "speaking_exercise_id"
        con.execute(f"INSERT INTO review_outcomes (operation_key, item_key, {col}, outcome, local_day, zone, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (f"op-{n}", k, ident, "completed" if n % 2 == 0 else "missed", day, zone, now))
        n += 1
    con.execute("INSERT INTO review_defers (operation_key, item_key, action, defer_until_day, zone, created_at) VALUES ('d1', ?, 'defer', '2026-11-22', ?, ?)", (queue[0], zone, now))
    con.execute("INSERT INTO review_defers (operation_key, item_key, action, refers_to, zone, created_at) VALUES ('d2', ?, 'undo', 1, ?, ?)", (queue[0], zone, now))
    con.execute("INSERT INTO practice_text_retention (operation_key, keep_text, zone, created_at) VALUES ('t1', 0, ?, ?)", (zone, now))
    con.commit()
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    linked = con.execute("""SELECT count(*) FROM review_outcomes o
        LEFT JOIN learning_entries e ON e.id = o.entry_id LEFT JOIN speaking_exercises s ON s.id = o.speaking_exercise_id
        WHERE (o.entry_id IS NOT NULL AND e.id IS NOT NULL) OR (o.speaking_exercise_id IS NOT NULL AND s.id IS NOT NULL)""").fetchone()[0]
    check("links: every outcome names an existing record; no foreign-key violation", not fk and linked == len(queue), {"fk": fk, "linked": linked, "queue": len(queue)})
    refusals = {}
    for name, sql, params in (
        ("unknown record", "INSERT INTO review_outcomes (operation_key, item_key, entry_id, outcome, local_day, zone, created_at) VALUES ('x1', 'notebook:entry:999999', 999999, 'completed', ?, ?, ?)", (day, zone, now)),
        ("key disagrees with record", "INSERT INTO review_outcomes (operation_key, item_key, entry_id, outcome, local_day, zone, created_at) VALUES ('x2', 'notebook:entry:2', 1, 'completed', ?, ?, ?)", (day, zone, now)),
        ("replayed operation key", "INSERT INTO review_outcomes (operation_key, item_key, entry_id, outcome, local_day, zone, created_at) VALUES ('op-0', 'notebook:entry:1', 1, 'missed', ?, ?, ?)", (day, zone, now)),
        ("update", "UPDATE review_outcomes SET outcome = 'missed' WHERE id = 1", ()),
        ("delete", "DELETE FROM review_outcomes WHERE id = 1", ()),
        ("second undo", "INSERT INTO review_defers (operation_key, item_key, action, refers_to, zone, created_at) VALUES ('d3', ?, 'undo', 1, ?, ?)", (queue[0], zone, now)),
    ):
        try:
            con.execute(sql, params)
            con.commit()
            refusals[name] = "accepted"
        except sqlite3.DatabaseError as e:
            con.rollback()
            refusals[name] = str(e)[:80]
    con.close()
    check("links: unknown records, disagreeing keys, replays, updates, deletes and a second undo are refused", all(v != "accepted" for v in refusals.values()), refusals)
    # serve
    ok, cur = reads(Path(opts["--binary"]), db, w / "run-up", facts)
    check("serve: the current server reads the upgraded copy exactly as before", ok and cur == before_reads, [cur, before_reads])
    if opts["--old-binary"]:
        ok, old = reads(Path(opts["--old-binary"]), db, w / "run-old", facts)
        check("serve: the start tree's server also starts and reads the same (the new tables stay unread)",
              ok and old["notebook"] == before_reads["notebook"] and old["speaking"] == before_reads["speaking"] and [k for k, _ in old["today"]] != [], {"old": old})
    # rollback
    con = sqlite3.connect(db)
    lost = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("review_outcomes", "review_defers", "practice_text_retention")}
    con.executescript(block("r4-rollback"))
    con.commit()
    con.close()
    code, down = inventory(data, w / "inv-down", w / "inv-before" / "inventory.json")
    check("rollback: the pre-upgrade schema and the same logical digest", schema(db) == before_schema and down["expect"]["same_logical_digest"] and code == 0,
          {"verdict": down["verdict"], "same": down["expect"]["same_logical_digest"]})
    check("rollback: what could not survive is counted (the new tables' rows only)", sum(lost.values()) == len(queue) + 3, lost)
    out = {"queue": queue, "refusals": refusals, "lost_on_rollback": lost, "checks": RESULTS}
    (w / "storage_r4.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"{'PASS' if not FAILED else 'FAIL'}: {len(RESULTS) - len(FAILED)}/{len(RESULTS)}; lost on rollback {lost}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
