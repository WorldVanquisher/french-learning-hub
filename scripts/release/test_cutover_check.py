#!/usr/bin/env python3
"""Tests for scripts/release/cutover_check.py on synthetic databases (standard library only)."""
import ast
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "cutover_check.py")
SECRET = "SYNTHETIC-CUTOVER-VALUE"


def run(*args):
    return subprocess.run([sys.executable, "-I", "-B", TOOL, *args], capture_output=True, text=True, timeout=60)


def make_db(path, rows=2):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY)")
    con.executemany("INSERT INTO schema_migrations VALUES (?)", [("001",), ("002",)])
    con.execute("CREATE TABLE learning_entries (id INTEGER PRIMARY KEY, original_input TEXT)")
    con.executemany("INSERT INTO learning_entries (original_input) VALUES (?)", [(f"{SECRET}-{i}",) for i in range(rows)])
    con.commit()
    con.close()
    return path


def add_row(path, text="later"):
    con = sqlite3.connect(path)
    con.execute("INSERT INTO learning_entries (original_input) VALUES (?)", (f"{SECRET}-{text}",))
    con.commit()
    con.close()


class CutoverCheck(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.ev = os.path.join(self.td, "ev.jsonl")
        self.nas = make_db(os.path.join(self.td, "nas", "app.db"))
        self.tar = os.path.join(self.td, "final.tar")
        with open(self.tar, "wb") as fh:
            fh.write(b"archive")

    def tearDown(self):
        shutil.rmtree(self.td)

    def rec(self, step, host, **kw):
        args = ["record", self.ev, "--step", step, "--host", host]
        for k, v in kw.items():
            args += [f"--{k.replace('_', '-')}", str(v)]
        r = run(*args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def check(self):
        r = run("check", self.ev)
        line = [l for l in r.stdout.splitlines() if ":" in l and l.split(":")[0].isupper() and " " not in l.split(":")[0]][-1]
        return line.split(":")[0], r

    def up_to_restore(self, ready=True):
        self.rec("C1-aws-empty", "aws", db=os.path.join(self.td, "aws", "app.db"))
        self.rec("C2-boundary", "nas", db=self.nas)
        backup = shutil.copytree(os.path.dirname(self.nas), os.path.join(self.td, "backup"))
        self.rec("C3-backup", "nas", db=os.path.join(backup, "app.db"))
        self.rec("C4-sent", "nas", file=self.tar)
        self.rec("C4-received", "aws", file=self.tar)
        self.aws = shutil.copytree(os.path.dirname(self.nas), os.path.join(self.td, "aws"), dirs_exist_ok=True)
        self.aws_db = os.path.join(self.aws, "app.db")
        r = self.rec("C5-restored", "aws", db=self.aws_db)
        self.patch_last(ready=ready)            # no live server here: readiness as the operator measured it
        return r

    def patch_last(self, **kw):
        with open(self.ev) as fh:
            lines = fh.read().splitlines()
        last = json.loads(lines[-1])
        last.update(kw)
        with open(self.ev, "w") as fh:
            fh.write("\n".join(lines[:-1] + [json.dumps(last)]) + "\n")

    def smoke_and_switch(self):
        self.rec("C6-smoke", "aws", db=self.aws_db, http_code=200)
        self.patch_last(ready=True)
        self.assertEqual(self.check()[0], "HOLD")
        self.rec("C7-switch", "client")
        self.assertEqual(self.check()[0], "SWITCHED")

    def test_hold_then_boundary_and_no_values_printed(self):
        self.rec("C1-aws-empty", "aws", db=os.path.join(self.td, "aws", "app.db"))
        r = self.rec("C2-boundary", "nas", db=self.nas)
        v, out = self.check()
        self.assertEqual(v, "HOLD")
        self.assertIn("final write boundary: T0", out.stdout)
        self.assertIn("learning_entries 2", out.stdout)
        with open(self.ev) as fh:
            digest = json.loads(fh.read().splitlines()[-1])["db"]["digest"]
        self.assertNotIn(digest, out.stdout + r.stdout)
        self.assertNotIn(SECRET, out.stdout + r.stdout)
        self.assertEqual(os.stat(self.ev).st_mode & 0o777, 0o600)

    def test_failed_health_check_before_the_switch(self):
        self.up_to_restore(ready=False)
        v, r = self.check()
        self.assertEqual(v, "DO-NOT-SWITCH")
        self.assertIn("FAIL     C5-restored", r.stdout)
        self.assertIn("keep private access on the NAS", r.stdout)

    def test_rollback_before_any_target_write_is_case_a(self):
        self.up_to_restore()
        self.smoke_and_switch()
        self.rec("A-check", "aws", db=self.aws_db)
        v, r = self.check()
        self.assertEqual(v, "ROLLBACK-A")
        self.assertIn("nothing is lost", r.stdout)

    def test_rollback_after_target_writes_warns_and_measures_the_window(self):
        self.up_to_restore()
        self.smoke_and_switch()
        self.rec("C8-first-write", "aws", http_code=201)
        add_row(self.aws_db, "a")
        add_row(self.aws_db, "b")
        self.rec("A-check", "aws", db=self.aws_db)
        v, r = self.check()
        self.assertEqual(v, "ROLLBACK-B")
        self.assertIn("divergent writes on AWS since the boundary", r.stdout)
        self.assertIn("learning_entries +2", r.stdout)
        self.assertIn("WARNING: restarting the NAS now would discard 2 new row(s) in 1 table(s)", r.stdout)
        nas2 = shutil.copytree(self.aws, os.path.join(self.td, "nas-restored"))
        self.rec("R-restored", "nas", db=os.path.join(nas2, "app.db"))
        self.assertEqual(self.check()[0], "ROLLED-BACK")
        self.assertEqual(run("check", self.ev).returncode, 0)

    def test_writes_on_both_sides_are_diverged(self):
        self.up_to_restore()
        self.smoke_and_switch()
        self.rec("C8-first-write", "aws", http_code=201)
        add_row(self.aws_db, "aws")
        add_row(self.nas, "nas")
        self.rec("N-check", "nas", db=self.nas)
        self.rec("A-check", "aws", db=self.aws_db)
        v, r = self.check()
        self.assertEqual(v, "DIVERGED")
        self.assertIn("Never merge", r.stdout)
        self.assertIn("writes on the NAS after its boundary: learning_entries +1", r.stdout)

    def test_a_nas_write_after_the_boundary_before_the_switch(self):
        self.up_to_restore()
        add_row(self.nas, "habit")
        self.rec("N-check", "nas", db=self.nas)
        self.assertEqual(self.check()[0], "DO-NOT-SWITCH")

    def test_a_record_cut_short_is_ignored_and_the_next_one_starts_a_new_line(self):
        """Item 079: a second run after an early stop. A record killed mid-write leaves a partial line."""
        self.rec("C1-aws-empty", "aws", db=os.path.join(self.td, "aws", "app.db"))
        with open(self.ev, "a") as fh:
            fh.write('{"format": "flh-cutover-evidence/v1", "step": "C2-bou')       # the interrupted record
        self.rec("C2-boundary", "nas", db=self.nas)                                # the same step, run again
        v, r = self.check()
        self.assertEqual(v, "HOLD")
        self.assertIn("WARNING ignored 1 incomplete line(s) [2]", r.stdout)
        self.assertIn("PASS     C2-boundary", r.stdout)

    def test_loopback_only_and_template(self):
        r = run("record", self.ev, "--step", "C5-restored", "--host", "aws", "--ready-url", "http://203.0.113.5:8080/readyz")
        self.assertEqual(r.returncode, 2)
        out = os.path.join(self.td, "t.md")
        self.assertEqual(run("template", "--out", out).returncode, 0)
        with open(out) as fh:
            text = fh.read()
        self.assertIn("OWNER-ONLY", text)
        self.assertIn("dig +short A <PUBLIC_DEMO_NAME>", text)
        self.assertIn("{{.Id}}", text)
        self.assertEqual(os.stat(out).st_mode & 0o777, 0o600)

    def test_host_side_tools_parse_as_python39(self):
        for f in ("cutover_check.py", "backup_tool.py"):
            with open(os.path.join(HERE, f)) as fh:
                ast.parse(fh.read(), feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
