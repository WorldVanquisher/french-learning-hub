"""Fast stdlib safety/recovery checks; no application build or Docker needed."""
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import run
from fake_provider import Provider


class HarnessSafety(unittest.TestCase):
    def fixture(self, parent):
        active = parent / "active"
        active.mkdir(mode=0o700)
        with sqlite3.connect(active / "app.db") as conn:
            conn.execute("CREATE TABLE marker(value TEXT)")
            conn.execute("INSERT INTO marker VALUES('A')")
        return active

    def test_no_inherited_configuration(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-propagate", "DOCKER_HOST": "tcp://personal",
                                     "HTTP_PROXY": "http://personal", "GOENV": "/secret"}):
            env = run.clean_env(Path("/tmp/fixture-home"))
        self.assertEqual(env["OPENAI_API_KEY"], "flh026-fake-only")
        self.assertEqual(env["DOCKER_HOST"], "unix:///var/run/docker.sock")
        self.assertEqual(env["GOENV"], "off")
        self.assertNotIn("HTTP_PROXY", env)
        self.assertNotIn("FRENCH_HUB_URL", env)

    def test_names_independent_of_underscore_directory(self):
        with tempfile.TemporaryDirectory(prefix="flh033-_suffix-") as directory:
            owned = Path(directory) / "flh026-_aditmt8"
            owned.mkdir()
            with patch.object(run.tempfile, "mkdtemp", return_value=str(owned)):
                harness = run.Harness("container")
            try:
                self.assertRegex(harness.project, r"^flh026-[0-9a-f]{32}$")
                self.assertEqual(harness.image, harness.project + ":local")
            finally:
                self.assertEqual(harness.cleanup(), [])

    def test_compiler_uses_isolated_path_and_explicit_selection(self):
        with tempfile.TemporaryDirectory(prefix="flh033-compiler-") as directory:
            compiler = Path(directory) / "go"
            compiler.write_text("#!/bin/sh\nexit 0\n")
            compiler.chmod(0o700)
            env = run.clean_env(Path(directory))
            with patch.dict(os.environ, {"PATH": directory}), patch.object(
                    run.shutil, "which", return_value="/usr/bin/go") as lookup:
                self.assertEqual(run.native_compiler(env), str(Path("/usr/bin/go").resolve()))
                lookup.assert_called_once_with("go", path=env["PATH"])
                self.assertEqual(run.native_compiler(env, compiler), str(compiler))
                self.assertEqual(lookup.call_count, 1)
            with self.assertRaisesRegex(AssertionError, "absolute executable"):
                run.native_compiler(env, Path("relative-go"))

    def test_restore_checksum_failure_leaves_active(self):
        with tempfile.TemporaryDirectory(prefix="flh026-test-") as directory:
            root = Path(directory)
            active = self.fixture(root)
            run.backup(active, root / "backup")
            before = run.snapshot(active / "app.db")
            with (root / "backup/app.db").open("ab") as output:
                output.write(b"corruption")
            with self.assertRaisesRegex(AssertionError, "checksum mismatch"):
                run.restore(active, root / "backup")
            self.assertEqual(run.snapshot(active / "app.db"), before)
            self.assertFalse((root / "active-preserved").exists())

    def test_non_ok_integrity_fails_even_without_sqlite_error(self):
        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def execute(self, *_):
                return self

            def fetchall(self):
                return [("corrupt",)]

        with patch.object(run.sqlite3, "connect", return_value=Connection()):
            with self.assertRaisesRegex(AssertionError, "exactly one ok"):
                run.integrity(Path("/tmp/unused"))

    def test_copy_failure_leaves_active_and_removes_stage(self):
        with tempfile.TemporaryDirectory(prefix="flh026-test-") as directory:
            root = Path(directory)
            active = self.fixture(root)
            run.backup(active, root / "backup")
            before = run.snapshot(active / "app.db")
            with patch.object(run.shutil, "copy2", side_effect=OSError("controlled copy failure")):
                with self.assertRaises(OSError):
                    run.restore(active, root / "backup")
            self.assertEqual(run.snapshot(active / "app.db"), before)
            self.assertFalse((root / "active-stage").exists())

    def test_assertion_failure_cleans_owned_process_provider_and_files(self):
        harness = run.Harness("native")
        directory = harness.run_dir
        harness.provider = Provider(("127.0.0.1", 0))
        provider_port = harness.provider.server_address[1]
        harness.provider_thread = threading.Thread(target=harness.provider.serve_forever, daemon=True)
        harness.provider_thread.start()
        harness.process = subprocess.Popen([
            "python3", "-B", "-c",
            "import signal,time; signal.signal(signal.SIGTERM,lambda *_:exit(0)); print('ready',flush=True); time.sleep(300)"],
            env=harness.env, cwd=directory, stdout=subprocess.PIPE, start_new_session=True)
        process = harness.process
        self.assertEqual(process.stdout.readline(), b"ready\n")
        try:
            raise AssertionError("controlled workflow failure")
        except AssertionError:
            errors = harness.cleanup()
        process.stdout.close()
        self.assertEqual(errors, [])
        self.assertIsNotNone(process.poll())
        self.assertFalse(harness.provider_thread.is_alive())
        self.assertFalse(directory.exists())
        with socket.socket() as probe:
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", provider_port)), 0)

    def test_unowned_http_target_refused_before_connection(self):
        harness = run.Harness("native")
        try:
            with patch.object(harness, "http", side_effect=AssertionError("should not connect")) as request:
                with self.assertRaisesRegex(AssertionError, "unowned HTTP target"):
                    harness.request("GET", "/entries")
                request.assert_not_called()
        finally:
            self.assertEqual(harness.cleanup(), [])


if __name__ == "__main__":
    unittest.main()
