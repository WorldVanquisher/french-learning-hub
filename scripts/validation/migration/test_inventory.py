#!/usr/bin/env python3
"""Tests for inventory.py on small synthetic databases (standard library only).

    python3 -I -B scripts/validation/migration/test_inventory.py

Each case builds a 001-021 database from migrations/ in a temporary directory, adds a few
synthetic rows, damages a copy in one way, and checks that the inventory reports exactly that,
with the documented exit code, without leaking any row text and without changing the source.
"""
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SECRET = "Je suis allé à la boulangerie (TEXTE-PRIVÉ-7f3a)"
NOW = "2026-11-19T10:00:00Z"


def build(path: Path, upto: str = "999"):
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("CREATE TABLE IF NOT EXISTS schema_migrations (\n\t\tname       TEXT PRIMARY KEY,\n\t\tapplied_at TEXT NOT NULL DEFAULT (datetime('now'))\n\t)")
    for f in sorted((REPO / "migrations").glob("*.sql")):
        if f.name[:3] > upto:
            break
        con.executescript(f"BEGIN;\n{f.read_text()}\n;INSERT INTO schema_migrations (name) VALUES ('{f.name}');\nCOMMIT;")
    con.execute("INSERT INTO learning_entries (original_input, original_context, created_at, updated_at) VALUES (?, 'contexte privé', ?, ?)", (SECRET, NOW, NOW))
    cols = [r[1] for r in con.execute("PRAGMA table_info(learning_captures)")]
    vals = {"capture_id": "inv-test-1", "entry_id": 1, "content_fingerprint": "f" * 64, "created_at": NOW, "source": "manual", "schema_version": "learning_capture_v1", "discussion_summary": ""}
    use = [c for c in cols if c in vals]
    con.execute(f"INSERT INTO learning_captures ({', '.join(use)}) VALUES ({', '.join('?' for _ in use)})", [vals[c] for c in use])
    kind = ("source_kind, ", "'youtube', ") if "source_kind" in [r[1] for r in con.execute("PRAGMA table_info(listening_materials)")] else ("", "")
    con.execute(f"INSERT INTO listening_materials ({kind[0]}video_id, source_url, title, created_at) VALUES ({kind[1]}'abcdefghijk', 'https://www.youtube.com/watch?v=abcdefghijk', 'Test', ?)", (NOW,))
    con.execute("INSERT INTO listening_transcripts (material_id, version, segments, has_timestamps, created_at) VALUES (1, 1, '[{\"index\":1,\"start_seconds\":null,\"text\":\"Bonjour.\"}]', 0, ?)", (NOW,))
    con.execute("INSERT INTO listening_exercises (material_id, transcript_id, status, generator, content, created_at) VALUES (1, 1, 'completed', 'openai:m:listening_exercise_v1', '{\"items\":[{},{}]}', ?)", (NOW,))
    con.execute("INSERT INTO learning_capture_sources (capture_row_id, entry_id, source_type, record_id, item, attempt, created_at) VALUES (1, 1, 'listening_item', 1, 2, NULL, ?)", (NOW,))
    con.execute("INSERT INTO mistake_retry_marks (entry_id, marked, created_at) VALUES (1, 1, ?)", (NOW,))
    con.close()


def run(src: Path, out: Path, *extra):
    r = subprocess.run([sys.executable, "-I", "-B", str(HERE / "inventory.py"), str(src), "--out", str(out), *extra], capture_output=True, text=True)
    rec = json.loads((out / "inventory.json").read_text()) if (out / "inventory.json").exists() else {}
    return r.returncode, rec, (out / "summary.txt").read_text() if (out / "summary.txt").exists() else ""


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="flh-inv-test-"))
        self.data = self.t / "data"
        self.data.mkdir()
        build(self.data / "app.db")

    def tearDown(self):
        for p in self.t.rglob("*"):
            try:
                os.chmod(p, 0o700 if p.is_dir() else 0o600)
            except OSError:
                pass
        shutil.rmtree(self.t, ignore_errors=True)

    def sql(self, *stmts, fk=False):
        con = sqlite3.connect(self.data / "app.db", isolation_level=None)
        con.execute(f"PRAGMA foreign_keys = {'ON' if fk else 'OFF'}")
        for s in stmts:
            con.execute(*s) if isinstance(s, tuple) else con.execute(s)
        con.close()

    def test_clean_database_is_ready_and_leaks_nothing(self):
        code, rec, summary = run(self.data, self.t / "o")
        self.assertEqual((code, rec["verdict"]), (0, "READY"))
        self.assertEqual(rec["ledger"]["parity"], "EQUAL")
        self.assertEqual(rec["learner_records"]["notebook_by_source_type"], {"listening_item": 1})
        self.assertEqual(rec["learner_records"]["notebook_marked_for_retry"], 1)
        self.assertEqual(rec["versions_by_source"]["listening_transcripts"], {"v1": 1})
        blob = (self.t / "o" / "inventory.json").read_text() + summary
        for private in (SECRET, "contexte privé", "Bonjour."):
            self.assertNotIn(private, blob)
        self.assertEqual(rec["time"]["weeks_first_last"]["learning_entries"], ["2026-W47", "2026-W47"])

    def test_dangling_references_and_out_of_range_items_are_problems(self):
        self.sql("UPDATE learning_capture_sources SET item = 9", "DELETE FROM listening_transcripts")
        code, rec, summary = run(self.data, self.t / "o")
        self.assertEqual((code, rec["verdict"]), (1, "PROBLEMS"))
        self.assertIn("listening_exercises", rec["references"]["foreign_key_violations"])
        self.assertEqual(rec["references"]["logical"], {"listening_item: item out of range": 1})
        self.sql("DELETE FROM listening_exercises")
        code, rec, _ = run(self.data, self.t / "o2")
        self.assertEqual(rec["references"]["logical"], {"listening_item: record missing": 1})

    def test_workbook_invariants_are_problems(self):
        code, rec, _ = run(self.data, self.t / "o0")
        self.assertEqual(rec["invariants"], {})
        self.sql(("INSERT INTO listening_transcripts (material_id, version, segments, has_timestamps, created_at) VALUES (1, 3, '[]', 0, ?)", (NOW,)))
        self.sql(("INSERT INTO exam_sessions (operation_id, kind, form_id, form_title, forms_sha256, pack_sha256, duration_seconds, started_at, deadline_at) "
                  "VALUES ('4f6d1c3e-8a7b-4c2d-9e1f-0a1b2c3d4e5f', 'exam', 'f1', 'Form', 'f', 'p', 1800, ?, '2026-11-19T08:30:00Z')", (NOW,)))
        self.sql("INSERT INTO exam_answers (session_id, position, choice, saved_at) VALUES (1, 1, 1, '2026-11-19T08:31:00Z')")
        code, rec, summary = run(self.data, self.t / "o")
        self.assertEqual((code, rec["verdict"]), (1, "PROBLEMS"))
        self.assertEqual(rec["invariants"], {"listening_transcripts: versions not 1..N per material_id": 1, "exam answers saved after their session's deadline": 1})
        self.assertIn("invariants:", summary)

    def test_encoding_control_characters_and_identifier_forms(self):
        self.sql(("UPDATE learning_entries SET original_context = CAST(? AS TEXT)", (b"\xff\xfe bad",)),
                 "UPDATE learning_entries SET original_input = 'a' || char(7) || 'b'",
                 ("UPDATE learning_captures SET capture_id = ?", ("café id",)))
        code, rec, _ = run(self.data, self.t / "o")
        self.assertEqual(code, 1)
        self.assertEqual(rec["encoding"], {"learning_entries.original_context: invalid UTF-8": 1, "learning_entries.original_input: control character": 1})
        self.assertEqual(rec["identifiers"], {"learning_captures.capture_id: not NFC": 1, "learning_captures.capture_id: unexpected format": 1})

    def test_unparseable_and_future_times(self):
        self.sql("UPDATE learning_entries SET created_at = 'yesterday', updated_at = '2999-01-01T00:00:00Z'")
        code, rec, _ = run(self.data, self.t / "o")
        self.assertEqual(code, 1)
        self.assertEqual(rec["time"]["unparseable"], {"learning_entries.created_at": 1})
        self.assertEqual(rec["time"]["future"], {"learning_entries.updated_at": 1})

    def test_duplicates_are_reported_and_kept(self):
        self.sql(("INSERT INTO learning_entries (original_input, original_context, created_at, updated_at) VALUES (?, 'contexte privé', ?, ?)", (SECRET, NOW, NOW)),
                 ("INSERT INTO mistake_retry_marks (entry_id, marked, created_at) VALUES (1, 1, ?)", (NOW,)))
        code, rec, _ = run(self.data, self.t / "o")
        self.assertEqual(code, 0)
        self.assertEqual(rec["duplicates"]["identical_entries"], 1)
        self.assertEqual(rec["duplicates"]["identical_consecutive_retry_marks"], 1)
        self.assertTrue(any("duplicates" in w for w in rec["warnings"]))

    def test_parity_with_the_destination(self):
        older = self.t / "old"
        older.mkdir()
        build(older / "app.db", upto="020")
        code, rec, _ = run(older, self.t / "o1")
        self.assertEqual((code, rec["ledger"]["parity"]), (0, "BEHIND"))
        self.sql("INSERT INTO schema_migrations (name) VALUES ('099_future.sql')")
        code, rec, summary = run(self.data, self.t / "o2")
        self.assertEqual((code, rec["verdict"], rec["ledger"]["parity"]), (4, "REFUSE", "AHEAD"))
        self.assertIn("do not copy", summary)

    def test_partial_inputs_have_actionable_exit_codes(self):
        empty = self.t / "empty"
        empty.mkdir()
        self.assertEqual(run(empty, self.t / "o1")[0], 3)
        (empty / "app.db-wal").write_bytes(b"x")
        code, rec, _ = run(empty, self.t / "o2")
        self.assertEqual(code, 3)
        bk = self.t / "flh-20261119T100000Z"
        bk.mkdir()
        shutil.copy(self.data / "app.db", bk / "app.db")
        code, rec, summary = run(bk, self.t / "o3")
        self.assertEqual((code, rec["verdict"]), (3, "PARTIAL"))
        self.assertIn("without SHA256SUMS", summary)
        (bk / "SHA256SUMS").write_text("0" * 64 + "  app.db\n")
        code, rec, summary = run(bk, self.t / "o4")
        self.assertEqual(code, 3)
        self.assertIn("checksums do not match", summary)
        broken = self.t / "broken"
        broken.mkdir()
        raw = bytearray((self.data / "app.db").read_bytes())
        raw[5000:9000] = b"\x00" * 4000
        (broken / "app.db").write_bytes(bytes(raw))
        code, rec, summary = run(broken, self.t / "o5")
        self.assertEqual((code, rec["verdict"]), (3, "PARTIAL"))
        self.assertIn("restore the latest COMPLETE backup", summary)

    def test_read_only_source_is_never_changed(self):
        os.chmod(self.data / "app.db", 0o400)
        os.chmod(self.data, 0o500)
        before = sorted(os.listdir(self.data))
        code, rec, _ = run(self.data, self.t / "o")
        self.assertEqual(code, 0)
        self.assertTrue(rec["source_unchanged"])
        self.assertEqual(sorted(os.listdir(self.data)), before)
        self.assertEqual(stat.S_IMODE(os.stat(self.data / "app.db").st_mode), 0o400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
