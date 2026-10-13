"""Shared fixtures: synthetic demo databases built from the repository migrations."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from flh_aws.snapshot import REPO  # noqa: E402

# Synthetic values copied from the reused demo sources (the gate checks them).
ENTRIES = ["Why do we say « il faut que je fasse » and not « il faut que je fais »?",
           "How do I say « I miss you » in French?"]
CONCEPTS = ["subjunctive after « il faut que »", "tu me manques: saying you miss someone",
            "depuis for something still going on"]
NOW = "2026-10-13T00:00:00Z"


def apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, "
                 "applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
    for f in sorted((REPO / "migrations").glob("*.sql")):
        conn.executescript(f.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (f.name,))
    conn.commit()


def add_entry(conn, text):
    conn.execute("INSERT INTO learning_entries (original_input, original_context, created_at, updated_at) "
                 "VALUES (?, '', ?, ?)", (text, NOW, NOW))


def add_concept(conn, target, n):
    conn.execute("INSERT INTO knowledge_concepts (identity_schema_version, target, pedagogical_intent, signature, "
                 "created_at, updated_at) VALUES ('fr_l2_concept_identity_v1', ?, 'grammar', ?, ?, ?)",
                 (target, f"sig-{n}", NOW, NOW))


def make_demo(root: Path, kind: str = "flh034", extra_entry: str | None = None) -> tuple[Path, Path]:
    demo = root / f"demo-{kind}"
    demo.mkdir()
    if kind == "flh034":
        (demo / ".flh034-demo").touch()
        db = demo / "demo.db"
    else:
        (demo / ".flh060-demo").touch()
        (demo / "flh034").mkdir()
        db = demo / "flh034" / "demo.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    apply_migrations(conn)
    for t in ENTRIES:
        add_entry(conn, t)
    for i, c in enumerate(CONCEPTS):
        add_concept(conn, c, i)
    if extra_entry:
        add_entry(conn, extra_entry)
    conn.commit()
    conn.close()
    return demo, db


class TempDir:
    def __enter__(self) -> Path:
        self.d = Path(tempfile.mkdtemp(prefix="flh063-test-")).resolve()
        return self.d

    def __exit__(self, *a):
        shutil.rmtree(self.d, ignore_errors=True)


def run_cli(*argv) -> tuple[int, dict | None, str]:
    from flh_aws.cli import main
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(a) for a in argv])
    try:
        data = json.loads(out.getvalue()) if out.getvalue().strip() else None
    except ValueError:
        data = None
    return code, data, err.getvalue()
