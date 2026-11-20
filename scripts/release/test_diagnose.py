#!/usr/bin/env python3
"""Tests for scripts/release/diagnose.py: each startup failure on a synthetic data directory."""
import ast
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "diagnose.py")
MIGRATIONS = sorted(f for f in os.listdir(os.path.join(HERE, "..", "..", "migrations")) if f.endswith(".sql"))
# The stable codes (item 076). Renaming or removing one breaks scripts and docs that match it.
CODES = ["settings-missing", "settings-readable", "data-missing", "data-owner", "data-mode", "db-readonly",
         "db-corrupt", "db-newer", "port-busy", "disk-low"]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipIf(os.geteuid() == 0, "permission checks need a non-root user")
class Diagnose(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.data = os.path.join(self.td, "data dir")
        os.mkdir(self.data, 0o700)
        con = sqlite3.connect(os.path.join(self.data, "app.db"))
        con.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY)")
        con.executemany("INSERT INTO schema_migrations VALUES (?)", [(m,) for m in MIGRATIONS])
        con.commit()
        con.close()
        os.chmod(os.path.join(self.data, "app.db"), 0o600)
        self.port = free_port()

    def tearDown(self):
        os.chmod(self.data, 0o700) if os.path.isdir(self.data) else None
        shutil.rmtree(self.td)

    def run_tool(self, *extra):
        r = subprocess.run([sys.executable, "-I", "-B", TOOL, "--data", self.data, "--port", str(self.port),
                            "--uid", str(os.getuid()), "--gid", str(os.getgid()), *extra],
                           capture_output=True, text=True, timeout=60)
        return r

    def code(self, r):
        line = [l for l in r.stdout.splitlines() if l.startswith("DIAGNOSIS")]
        return line[0].split("[", 1)[1].split("]", 1)[0] if line else None

    def test_healthy_data_has_no_diagnosis(self):
        r = self.run_tool()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("nothing found", r.stdout)

    def test_each_cause_gets_its_code_and_recovery(self):
        os.chmod(os.path.join(self.data, "app.db"), 0o400)
        r = self.run_tool()
        self.assertEqual((r.returncode, self.code(r)), (1, "db-readonly"))
        self.assertIn("RECOVER chmod 600", r.stdout)
        os.chmod(os.path.join(self.data, "app.db"), 0o600)
        os.chmod(self.data, 0o755)
        self.assertEqual(self.code(self.run_tool()), "data-mode")
        os.chmod(self.data, 0o700)
        con = sqlite3.connect(os.path.join(self.data, "app.db"))
        con.execute("INSERT INTO schema_migrations VALUES ('099_from_a_newer_release.sql')")
        con.commit()
        con.close()
        r = self.run_tool()
        self.assertEqual(self.code(r), "db-newer")
        self.assertIn("unknown ['099_from_a_newer_release.sql']", r.stdout)
        self.assertEqual(self.code(self.run_tool("--migrations", "30")), None)     # a release that knows 30
        with socket.socket() as s:
            s.bind(("127.0.0.1", self.port))
            s.listen(1)
            r = self.run_tool("--migrations", "30")
            self.assertEqual(self.code(r), "port-busy")
            self.assertIn(f"ss -ltnp 'sport = :{self.port}'", r.stdout)
            self.assertEqual(self.run_tool("--migrations", "30", "--running").returncode, 0)

    def test_corrupt_and_missing_data(self):
        with open(os.path.join(self.data, "app.db"), "r+b") as fh:
            fh.write(b"not a database" * 10)
        self.assertEqual(self.code(self.run_tool()), "db-corrupt")
        shutil.rmtree(self.data)
        r = self.run_tool()
        self.assertEqual(self.code(r), "data-missing")
        self.assertIn(f"mkdir -m 700 {self.data}", r.stdout)

    def test_settings_file_values_stay_private(self):
        env = os.path.join(self.td, "daily env")
        with open(env, "w") as fh:
            fh.write(f"FLH_DATA_DIR='{self.data}'\nFLH_HOST_PORT={self.port}\nFLH_UID={os.getuid()}\n"
                     f"FLH_GID={os.getgid()}\nOPENAI_API_KEY=sk-SYNTHETIC-NEVER-PRINTED\n")
        os.chmod(env, 0o644)
        r = subprocess.run([sys.executable, "-I", "-B", TOOL, "--env", env, "--json"], capture_output=True, text=True)
        d = json.loads(r.stdout)
        self.assertEqual(d["diagnosis"]["code"], "settings-readable")
        self.assertNotIn("SYNTHETIC-NEVER-PRINTED", r.stdout + r.stderr)
        os.chmod(env, 0o600)
        r = subprocess.run([sys.executable, "-I", "-B", TOOL, "--env", env], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)           # FLH_DATA_DIR and the port came from the file
        r = subprocess.run([sys.executable, "-I", "-B", TOOL, "--env", os.path.join(self.td, "absent")],
                           capture_output=True, text=True)
        self.assertEqual(self.code(r), "settings-missing")


    def test_run_from_a_bundle_copy_uses_the_bundles_manifest(self):
        """Found by the first-run walkthrough (item 071): a bundle's repo/ has no migrations/, so the
        tool must read the bundle's MANIFEST.json instead of reporting every migration as unknown."""
        b = os.path.join(self.td, "flh-staging-0123456789ab")
        os.makedirs(os.path.join(b, "repo", "scripts", "release"))
        shutil.copy(TOOL, os.path.join(b, "repo", "scripts", "release", "diagnose.py"))
        copy = os.path.join(b, "repo", "scripts", "release", "diagnose.py")
        for count, want in ((len(MIGRATIONS), 0), (len(MIGRATIONS) - 1, 1)):
            with open(os.path.join(b, "MANIFEST.json"), "w") as fh:
                json.dump({"migrations": {"count": count}}, fh)
            r = subprocess.run([sys.executable, "-I", "-B", copy, "--data", self.data, "--port", str(self.port),
                                "--uid", str(os.getuid()), "--gid", str(os.getgid())], capture_output=True, text=True)
            self.assertEqual(r.returncode, want, r.stdout)
            self.assertIn(f"this release knows {count}", r.stdout)
        os.unlink(os.path.join(b, "MANIFEST.json"))
        r = subprocess.run([sys.executable, "-I", "-B", copy, "--data", self.data, "--port", str(self.port),
                            "--uid", str(os.getuid()), "--gid", str(os.getgid())], capture_output=True, text=True)
        self.assertIn("not checked: give --bundle DIR or --migrations N", r.stdout)


class Reasons(unittest.TestCase):
    def test_codes_are_stable_and_each_has_a_recovery(self):
        r = subprocess.run([sys.executable, "-I", "-B", TOOL, "--reasons"], capture_output=True, text=True)
        rows = [l.split("\t") for l in r.stdout.splitlines()]
        self.assertEqual([x[0] for x in rows], CODES)
        self.assertTrue(all(len(x) == 3 and x[1] and x[2] for x in rows))

    def test_parses_as_python39(self):
        with open(TOOL) as fh:
            ast.parse(fh.read(), feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
