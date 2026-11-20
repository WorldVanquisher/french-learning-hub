"""Migration-free check of extraction rows against the Workbooks storage proposal (standard library only).

  python3 -I -B check_storage_rows.py [BUNDLE_DIR]

Copied byte for byte into the sealed Workbooks bundle as ``check_storage_rows.py``. It reads
``storage-proposed-0NN.sql`` (a pinned copy of the Workbooks proposal) and
``storage-rows.json`` (rows the extraction lane derived from its synthetic work directory),
builds an in-memory SQLite database twice (the SQL as proposed, and with the extraction
lane's amendment), inserts every row, and checks against the expectations in the rows file:

* which rows the constraints refuse (as proposed: the agent-exercise decisions);
* that every stored row reads back unchanged, column by column;
* that resending a row with the same ``operation_key`` is refused (idempotency);
* that no ``answer_text`` is stored for a reveal.

Nothing is written to disk and no migration file is involved. Exit 0 when every expectation holds.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys


def run(sql: str, rows: dict) -> dict:
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(sql)
        refused, stored = [], {}
        for table, rs in sorted(rows.items()):
            for r in rs:
                cols = sorted(r)
                try:
                    db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [r[c] for c in cols])
                    stored.setdefault(table, []).append(r)
                except sqlite3.IntegrityError as e:
                    refused.append({"table": table, "operation_key": r["operation_key"], "error": str(e)})
        db.commit()
        mismatched = []
        for table, rs in stored.items():
            for r in rs:
                cols = sorted(r)
                got = db.execute(f"SELECT {', '.join(cols)} FROM {table} WHERE operation_key = ?", [r["operation_key"]]).fetchone()
                if list(got) != [r[c] for c in cols]:
                    mismatched.append(r["operation_key"])
        resend_stored = []
        for table, rs in stored.items():
            r = rs[0]
            cols = sorted(r)
            try:
                db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [r[c] for c in cols])
                resend_stored.append(table)
            except sqlite3.IntegrityError:
                pass
        reveal_text = db.execute("SELECT COUNT(*) FROM practice_attempts WHERE action = 'reveal' AND answer_text IS NOT NULL").fetchone()[0]
    finally:
        db.close()
    return {"refused": refused, "stored": {t: len(v) for t, v in stored.items()}, "read_back_mismatches": mismatched,
            "resend_stored": resend_stored, "reveal_rows_with_text": reveal_text}


def main(argv: list[str]) -> int:
    d = os.path.abspath(argv[1] if len(argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(d, "storage-proposed-0NN.sql"), encoding="utf-8") as fh:
        sql = fh.read()
    with open(os.path.join(d, "storage-rows.json"), encoding="utf-8") as fh:
        spec = json.load(fh)
    problems = []
    for variant in ("as_proposed", "amended"):
        s = sql
        if variant == "amended":
            for old, new in spec["amendment"]:
                if old not in s:
                    problems.append(f"amendment: the SQL no longer contains {old!r}")
                s = s.replace(old, new)
        rep = run(s, spec["rows"][variant])
        exp = spec["expect"][variant]
        print(f"{variant}: stored {rep['stored']}; refused {len(rep['refused'])}; read-back mismatches {len(rep['read_back_mismatches'])}; "
              f"resend stored {rep['resend_stored'] or 'never'}; reveal rows with text {rep['reveal_rows_with_text']}")
        for r in rep["refused"]:
            print(f"  refused {r['table']} {r['operation_key']}: {r['error']}")
        if len(rep["refused"]) != exp["refused"]:
            problems.append(f"{variant}: {len(rep['refused'])} rows refused, expected {exp['refused']}")
        if rep["read_back_mismatches"] or rep["resend_stored"] or rep["reveal_rows_with_text"]:
            problems.append(f"{variant}: read-back, idempotency or reveal-text check failed")
    for p in problems:
        print("FAIL " + p)
    print("storage check: " + ("OK" if not problems else f"{len(problems)} problem(s)"))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
