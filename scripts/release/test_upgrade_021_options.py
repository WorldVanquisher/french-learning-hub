"""Tests for the 020 -> 021 rehearsal's old-server option and summary lines
(stdlib only; no network, no Docker, no build).

  python3 -B -m unittest discover -s scripts/release -p 'test_*.py'
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REHEARSE = os.path.join(HERE, "upgrade_021", "rehearse.py")
spec = importlib.util.spec_from_file_location("rehearse_021", REHEARSE)
rehearse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rehearse)

# `go version -m` output of a synthetic build (same shape as a real one).
GO_VERSION_M = (
    "/x/old-server: go1.24.0\n"
    "\tpath\tfrench-learning-app/cmd/server\n"
    "\tmod\tfrench-learning-app\t(devel)\t\n"
    "\tbuild\t-buildmode=exe\n"
    "\tbuild\t-trimpath=true\n"
    "\tbuild\tCGO_ENABLED=1\n"
    "\tbuild\tGOARCH=amd64\n"
    "\tbuild\tGOOS=linux\n"
    "\tbuild\tvcs=git\n"
    "\tbuild\tvcs.revision=0123456789abcdef0123456789abcdef01234567\n"
    "\tbuild\tvcs.modified=false\n"
)


class OldServerOption(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_problem_names_missing_directory_and_non_executable(self):
        missing = os.path.join(self.tmp, "nope")
        self.assertIn("no such file", rehearse.old_server_problem(missing))
        self.assertIn("not a regular file", rehearse.old_server_problem(self.tmp))
        plain = os.path.join(self.tmp, "server")
        with open(plain, "w") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(plain, 0o644)
        self.assertIn("not executable", rehearse.old_server_problem(plain))
        os.chmod(plain, 0o755)
        self.assertIsNone(rehearse.old_server_problem(plain))

    def test_build_info_names_revision_platform_and_flags(self):
        info = rehearse.parse_build_info(GO_VERSION_M)
        self.assertEqual(info["go"], "go1.24.0")
        self.assertEqual(info["path"], "french-learning-app/cmd/server")
        b = info["build"]
        self.assertEqual((b["GOOS"], b["GOARCH"], b["-trimpath"], b["CGO_ENABLED"]), ("linux", "amd64", "true", "1"))
        self.assertEqual((b["vcs.revision"], b["vcs.modified"]), ("0123456789abcdef0123456789abcdef01234567", "false"))
        self.assertEqual(rehearse.parse_build_info("")["build"], {})

    def test_identity_names_both_binaries_by_file_and_never_by_package_path(self):
        info = rehearse.parse_build_info(GO_VERSION_M)
        ident = rehearse.old_server_identity("/w/old-server", "a" * 64, info, "/w/rehearsal/bin/server", "b" * 64)
        self.assertEqual(ident["old_server"]["binary"], "/w/old-server")
        self.assertEqual(ident["new_server"]["binary"], "/w/rehearsal/bin/server")
        self.assertEqual(ident["old_server"]["go_build"]["path"], "french-learning-app/cmd/server")
        self.assertNotIn("path", ident["old_server"])
        self.assertNotEqual(ident["old_server"]["sha256"], ident["new_server"]["sha256"])

    def test_optional_mode_is_not_run_and_says_only_the_fixture_was_checked(self):
        status, detail = rehearse.old_server_skip(requested=False, rolled=True)
        self.assertEqual(status, "NOT RUN")
        self.assertIn("optional, not requested", detail)
        self.assertIn("only fixture compatibility was checked", detail)
        self.assertIn("no pre-021 binary was started", detail)
        self.assertIn("--old-server BINARY", detail)
        self.assertEqual(rehearse.old_server_skip(False, False)[0], "NOT RUN")
        # With --fixture-db the fixture stage checks the ledger and integrity, not a pristine schema.
        status, detail = rehearse.old_server_skip(requested=False, rolled=True, fixture_db=True)
        self.assertEqual(status, "NOT RUN")
        self.assertIn("--fixture-db copy's ledger ends at 020", detail)
        self.assertNotIn("pristine 001-020 database", detail)
        self.assertIn("no pre-021 binary was started", detail)

    def test_required_mode_runs_or_fails_never_not_run(self):
        self.assertIsNone(rehearse.old_server_skip(requested=True, rolled=True))
        status, detail = rehearse.old_server_skip(requested=True, rolled=False)
        self.assertEqual(status, "FAIL")
        self.assertIn("required", detail)

    @unittest.skipUnless(all(shutil.which(t) for t in ("go", "sqlite3", "sha256sum", "bash")), "rehearsal tools missing")
    def test_unusable_old_server_is_refused_before_anything_runs(self):
        plain = os.path.join(self.tmp, "old-server")
        with open(plain, "w") as fh:
            fh.write("not a binary\n")
        os.chmod(plain, 0o644)
        for i, given in enumerate((os.path.join(self.tmp, "absent"), plain)):
            work = os.path.join(self.tmp, f"work{i}")
            out = subprocess.run([sys.executable, "-I", "-B", REHEARSE, work, "--old-server", given],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 2, out.stderr)
            self.assertIn("refused: --old-server", out.stderr)
            self.assertIn("required", out.stderr)
            self.assertEqual(os.listdir(work), [], "nothing may run or be written")


if __name__ == "__main__":
    unittest.main()
