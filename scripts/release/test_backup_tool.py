#!/usr/bin/env python3
"""Tests for scripts/release/backup_tool.py on synthetic SQLite backups (standard library + sqlite3 CLI)."""
import gzip
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "backup_tool.py")
MIGRATIONS = sorted(f for f in os.listdir(os.path.join(HERE, "..", "..", "migrations")) if f.endswith(".sql"))
SECRET = "SYNTHETIC-ROW-VALUE-NEVER-PRINTED"


def run(*args):
    return subprocess.run([sys.executable, "-I", "-B", TOOL, *args], capture_output=True, text=True, timeout=120)


def make_backup(d, rows=2, ledger=None, wal=True):
    os.makedirs(d)
    con = sqlite3.connect(os.path.join(d, "app.db"), isolation_level=None)
    if wal:
        con.execute("PRAGMA journal_mode = WAL")
    con.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT)")
    con.executemany("INSERT INTO schema_migrations VALUES (?, 'x')", [(m,) for m in (ledger or MIGRATIONS)])
    con.execute("CREATE TABLE learning_entries (id INTEGER PRIMARY KEY, original_input TEXT)")
    con.executemany("INSERT INTO learning_entries (original_input) VALUES (?)", [(f"{SECRET}-{i}",) for i in range(rows)])
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)") if wal else None
    con.close()
    seal(d)
    return d


def seal(d):
    with open(os.path.join(d, "SHA256SUMS"), "w") as fh:
        for f in sorted(x for x in os.listdir(d) if x.startswith("app.db")):
            with open(os.path.join(d, f), "rb") as data:
                fh.write(f"{hashlib.sha256(data.read()).hexdigest()}  {f}\n")


class BackupTool(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.td)

    def p(self, *parts):
        return os.path.join(self.td, *parts)

    def test_inspect_states_and_no_values(self):
        b = make_backup(self.p("flh-1"))
        r = run("inspect", b)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("flh-1: COMPLETE", r.stdout)
        self.assertIn(f"ledger {len(MIGRATIONS)} migrations, last {MIGRATIONS[-1]}; this checkout has {len(MIGRATIONS)}", r.stdout)
        self.assertNotIn(SECRET, r.stdout)
        unsealed = shutil.copytree(b, self.p("flh-2"))
        os.unlink(os.path.join(unsealed, "SHA256SUMS"))
        self.assertIn("UNSEALED", run("inspect", unsealed).stdout)
        bad = shutil.copytree(b, self.p("flh-3"))
        with open(os.path.join(bad, "app.db"), "ab") as fh:
            fh.write(b"\0")
        r = run("inspect", bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn("CORRUPT", r.stdout)
        self.assertIn("app.db: MISMATCH in SHA256SUMS", r.stdout)
        inc = shutil.copytree(b, self.p("flh-4.incomplete"))
        self.assertIn("INCOMPLETE", run("inspect", inc).stdout)
        os.makedirs(self.p("empty"))
        self.assertIn("NOT_A_BACKUP", run("inspect", self.p("empty")).stdout)

    def test_a_backup_newer_than_this_checkout_is_named(self):
        b = make_backup(self.p("newer"), ledger=MIGRATIONS + ["099_from_the_future.sql"])
        r = run("inspect", b, "--json")
        j = json.loads(r.stdout)
        self.assertEqual(j["compatibility"]["unknown_to_this_checkout"], ["099_from_the_future.sql"])
        self.assertIn("do not restore it on this release", run("inspect", b).stdout)

    def test_compare_tells_same_from_different_without_values(self):
        a = make_backup(self.p("a"))
        b = shutil.copytree(a, self.p("b"))
        r = run("compare", a, b)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("logical content: SAME", r.stdout)
        c = make_backup(self.p("c"), rows=3)
        r = run("compare", a, c, "--json")
        self.assertEqual(r.returncode, 1)
        t = {x["table"]: x for x in json.loads(r.stdout)["tables"]}
        self.assertEqual((t["learning_entries"]["rows"], t["learning_entries"]["rows_a"], t["learning_entries"]["rows_b"]),
                         ("different", 2, 3))
        self.assertEqual(t["schema_migrations"]["rows"], "same")
        self.assertEqual(json.loads(r.stdout)["restore_a_over_b_discards"], {"tables": ["learning_entries"], "ledger_back_to": None})
        text = run("compare", a, c).stdout                     # R2-055: what a rollback to A would lose, by table
        self.assertIn("restoring A over B DISCARDS the changes in 1 table(s) listed above (every write made after A)", text)
        self.assertNotIn("DISCARDS", run("compare", a, b).stdout)
        self.assertNotIn(SECRET, r.stdout)
        self.assertNotIn(hashlib.sha256(SECRET.encode()).hexdigest()[:12], r.stdout)

    def test_next_action_after_an_interrupted_backup(self):
        active = self.p("data", "app")
        make_backup(active)
        r = run("next-action", active)
        self.assertIn("NEXT [no-backup]", r.stdout)
        make_backup(self.p("data", "app.backups", "flh-20261119T000000Z"))
        self.assertIn("NEXT [ok]", run("next-action", active).stdout)
        os.makedirs(self.p("data", "app.backups", "flh-20261119T010000Z.incomplete"))
        shutil.copy(os.path.join(active, "app.db"), self.p("data", "app.backups", "flh-20261119T010000Z.incomplete"))
        r = run("next-action", active)
        self.assertEqual(r.returncode, 1)
        self.assertIn("NEXT [rerun-backup]", r.stdout)
        self.assertIn("the latest restorable backup is flh-20261119T000000Z", r.stdout)
        self.assertTrue(os.path.isdir(self.p("data", "app.backups", "flh-20261119T010000Z.incomplete")))  # nothing deleted

    def test_restore_state_and_record(self):
        active = make_backup(self.p("data", "app"))
        self.assertIn("app: CLEAN", run("restore-state", active).stdout)
        make_backup(self.p("data", "app.restore-20261119T010000Z"), rows=5)
        rec = self.p("state.json")
        r = run("restore-state", active, "--record", rec)
        self.assertEqual(r.returncode, 1)
        with open(rec) as fh:
            j = json.load(fh)
        self.assertEqual(j["state"], "PREPARE-INTERRUPTED")
        self.assertIn("app.restore-20261119T010000Z", j["next_action"])
        self.assertEqual(os.stat(rec).st_mode & 0o777, 0o600)
        os.rename(active, self.p("data", "app.before-restore-20261119T010000Z"))
        r = run("restore-state", active)
        self.assertIn("SWAP-INTERRUPTED", r.stdout)
        self.assertIn("mv app.before-restore-20261119T010000Z app", r.stdout)
        os.rename(self.p("data", "app.restore-20261119T010000Z"), active)
        r = run("restore-state", active)
        self.assertEqual(r.returncode, 0)
        self.assertIn("app: RESTORED", r.stdout)

    def test_latest_resolves_the_newest_complete_backup(self):
        d = self.p("app dir.backups")
        make_backup(os.path.join(d, "flh-20261119T000000Z"))
        newest = make_backup(os.path.join(d, "flh-20261119T020000Z"))
        broken = make_backup(os.path.join(d, "flh-20261119T030000Z"))
        os.unlink(os.path.join(broken, "SHA256SUMS"))               # unsealed: never picked
        r = run("latest", d)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, newest))
        os.makedirs(self.p("empty dir"))
        self.assertEqual(run("latest", self.p("empty dir")).returncode, 1)

    def test_pack_unpack_and_damaged_archives(self):
        b = make_backup(self.p("flh-x"))
        dest = self.p("dest")
        os.makedirs(dest)
        for name in ("flh-x.tar.gz", "flh-x.tar"):
            out = self.p(name)
            self.assertEqual(run("pack", b, out).returncode, 0)
            with open(out + ".sha256") as fh:
                digest = fh.read().split()[0]
            cut = self.p("cut-" + name)
            with open(out, "rb") as src, open(cut, "wb") as dst:
                dst.write(src.read()[: os.path.getsize(out) // 2])
            with open(cut, "rb") as fh:
                cut_sha = hashlib.sha256(fh.read()).hexdigest()
            r = run("unpack", cut, "--sha256", cut_sha, dest)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("DAMAGED", r.stdout)
            self.assertIn("Nothing was unpacked", r.stdout)
            self.assertEqual(os.listdir(dest), [])
            r = run("unpack", cut, "--sha256", digest, dest)
            self.assertIn("REFUSED cut-", r.stdout)
            self.assertIn("compare its size with the sender's", r.stdout)
            r = run("unpack", out, "--sha256", digest, dest)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn("unpacked flh-x: COMPLETE", r.stdout)
            shutil.rmtree(os.path.join(dest, "flh-x"))
        with open(self.p("flh-x.tar.gz"), "rb") as fh:
            self.assertEqual(gzip.decompress(fh.read())[:5], b"flh-x")   # deterministic: no gzip name, mtime 0

    def test_a_second_unpack_after_an_early_stop(self):
        b = make_backup(self.p("flh-y"))
        out = self.p("flh-y.tar")
        run("pack", b, out)
        with open(out + ".sha256") as fh:
            digest = fh.read().split()[0]
        dest = self.p("dest")
        os.makedirs(os.path.join(dest, ".unpack-killed", "flh-y"))          # what a killed unpack leaves
        r = run("unpack", out, "--sha256", digest, dest)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("an earlier unpack stopped early and left .unpack-killed", r.stdout)
        self.assertEqual(sorted(os.listdir(dest)), [".unpack-killed", "flh-y"])   # reported, never used or removed

    def test_unsafe_members_are_refused(self):
        evil = self.p("evil.tar")
        with tarfile.open(evil, "w") as tf:
            ti = tarfile.TarInfo("../escape")
            ti.size = 1
            tf.addfile(ti, io.BytesIO(b"x"))
        with open(evil, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        os.makedirs(self.p("dest"))
        r = run("unpack", evil, "--sha256", digest, self.p("dest"))
        self.assertIn("REFUSED evil.tar: unsafe member", r.stdout)
        self.assertFalse(os.path.exists(self.p("escape")))

    def test_receipt(self):
        b = make_backup(self.p("flh-b"))
        active = shutil.copytree(b, self.p("data", "app"))
        wc = self.p("wc.txt")
        with open(wc, "w") as fh:
            fh.write("PASS\twrite\tok\nPASS\tcleanup\tok\nPASS\tsummary\tok\n")
        out = self.p("receipt.json")
        r = run("receipt", "--backup", b, "--active", active, "--write-check", wc, "--out", out)
        self.assertEqual(r.returncode, 0, r.stdout)
        with open(out) as fh:
            j = json.load(fh)
        self.assertEqual((j["format"], j["verdict"], j["active"]["equals_backup"]), ("flh-recovery-receipt/v1", "RECOVERED", True))
        self.assertNotIn(SECRET, json.dumps(j))
        other = make_backup(self.p("other"), rows=7)
        r = run("receipt", "--backup", other, "--active", active, "--out", out)
        self.assertEqual(r.returncode, 1)
        with open(out) as fh:
            self.assertIn("the active data is not the backup", json.load(fh)["next_action"])


if __name__ == "__main__":
    unittest.main()
