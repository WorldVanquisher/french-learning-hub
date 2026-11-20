"""The test entry point (scripts/run_tests.py): standard library only, so it runs offline too."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PKG = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("speaking_run_tests", PKG / "scripts" / "run_tests.py")
run_tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_tests)


def sample_suite():
    """One passing and one skipped test, built here so that discovery never sees them."""
    class Sample(unittest.TestCase):
        def test_passes(self):
            self.assertTrue(True)

        @unittest.skip("needs numpy")
        def test_needs_numpy(self):
            pass
    return unittest.TestLoader().loadTestsFromTestCase(Sample)


class EntryPoint(unittest.TestCase):
    def test_a_skip_fails_require_deps_but_not_offline(self):
        out = io.StringIO()
        ok, s = run_tests.run_suite(sample_suite(), require=True, stream=out)
        self.assertFalse(ok)
        self.assertEqual((s["ran"], s["skipped"], s["skips_by_reason"]), (2, 1, {"needs numpy": 1}))
        self.assertIn("--require-deps requires every test to run", out.getvalue())
        ok, s = run_tests.run_suite(sample_suite(), require=False, stream=io.StringIO())
        self.assertTrue(ok)
        self.assertEqual(s["mode"], "offline")

    def fake_fixture(self, tok):
        """Two small files and pins that match them (git blob, like the real pins)."""
        Path(tok, "config.json").write_text('{"d_model": 16}')
        Path(tok, "tokenizer.json").write_text('{"model": {}}')
        return {f: (os.path.getsize(os.path.join(tok, f)), ("gitblob", self.fetch.file_digest(os.path.join(tok, f), "gitblob")))
                for f in ("config.json", "tokenizer.json")}

    def setUp(self):
        self.fetch = run_tests.fetch

    def test_preflight_names_missing_modules_and_the_fixture(self):
        missing, _ = run_tests.preflight(modules=("flh_no_such_module_for_test",), env={})
        self.assertEqual(len(missing), 2)
        self.assertIn("module flh_no_such_module_for_test", missing)
        self.assertIn(f"{run_tests.FIXTURE_ENV} is not set", missing[1])
        with tempfile.TemporaryDirectory() as tok:
            pinned = self.fake_fixture(tok)
            with mock.patch.object(run_tests, "fixture_files", return_value=pinned):
                missing, versions = run_tests.preflight(modules=("json",), env={run_tests.FIXTURE_ENV: tok})
        self.assertEqual(missing, [])
        self.assertIn("json", versions)

    def test_fixture_with_a_missing_or_wrong_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tok:
            pinned = self.fake_fixture(tok)
            with mock.patch.object(run_tests, "fixture_files", return_value=pinned):
                self.assertEqual(run_tests.fixture_problems(tok), [])
                Path(tok, "tokenizer.json").write_text('{"model": []}')  # same size, other content
                bad = run_tests.fixture_problems(tok)
                self.assertEqual(len(bad), 1)
                self.assertTrue(bad[0].startswith("tokenizer.json: gitblob"), bad)
                Path(tok, "tokenizer.json").write_text("{}")  # truncated
                self.assertTrue(run_tests.fixture_problems(tok)[0].startswith("tokenizer.json: size"))
                os.remove(os.path.join(tok, "config.json"))
                self.assertIn("config.json: missing", run_tests.fixture_problems(tok))

    def test_the_real_contract_is_the_ten_pinned_non_weight_files(self):
        files = run_tests.fixture_files()
        self.assertEqual(len(files), 10)
        self.assertNotIn("model.safetensors", files)
        self.assertTrue({"config.json", "tokenizer.json", "vocab.json", "merges.txt"} <= set(files))
        self.assertEqual(run_tests.fixture_contract()["contract_sha256"], "55f3d55eaaa4291c715c37cb8f18e2dd8ecb379bad2041593d6ca6bb9826ecc2")

    def test_incomplete_fixture_fails_before_discovery_and_still_writes_json(self):
        real = run_tests.preflight
        with tempfile.TemporaryDirectory() as tok:
            pinned = self.fake_fixture(tok)
            os.remove(os.path.join(tok, "tokenizer.json"))
            out = os.path.join(tok, "summary.json")
            with mock.patch.object(run_tests, "fixture_files", return_value=pinned), \
                    mock.patch.object(run_tests, "preflight", lambda: real(modules=("json",), env={run_tests.FIXTURE_ENV: tok})), \
                    mock.patch.object(unittest.TestLoader, "discover") as discover, mock.patch("sys.stderr", io.StringIO()):
                self.assertEqual(run_tests.main(["--require-deps", "--json", out]), 2)
            discover.assert_not_called()
            doc = json.loads(Path(out).read_text())
        self.assertEqual(doc["mode"], "require-deps")
        self.assertIn("tokenizer.json: missing", doc["missing"][0])

    def test_json_keeps_failures_errors_and_skips_apart_and_the_exit_status(self):
        def mixed():
            class Mixed(unittest.TestCase):
                def test_ok(self):
                    pass

                def test_fails(self):
                    self.fail("wrong value")

                def test_errors(self):
                    raise RuntimeError("broken")

                @unittest.skip("needs torch")
                def test_skips(self):
                    pass
            return unittest.TestLoader().loadTestsFromTestCase(Mixed)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "summary.json")
            with mock.patch.object(unittest.TestLoader, "discover", lambda *a, **k: mixed()), mock.patch("sys.stderr", io.StringIO()):
                self.assertEqual(run_tests.main(["--json", out]), 1)  # offline: the failure and the error still fail the run
            doc = json.loads(Path(out).read_text())
        self.assertEqual((doc["ran"], doc["failures"], doc["errors"], doc["skipped"]), (4, 1, 1, 1))
        self.assertEqual(doc["skips_by_reason"], {"needs torch": 1})
        self.assertEqual(len(doc["skipped_tests"]), 1)

    def test_fixture_fetch_can_skip_the_weights(self):
        import sys
        sys.path.insert(0, str(PKG))
        from flh_speaking import fetch, pins
        got = []
        with mock.patch.object(fetch, "fetch_one", lambda dest, src, path, dataset, log: got.append(path)):
            fetch.fetch("unused", ["whisper-tiny"], log=lambda *_: None, weights=False)
        self.assertEqual(sorted(got), sorted(p for p in pins.MODELS["whisper-tiny"]["files"] if not p.endswith(".safetensors")))
        self.assertIn("config.json", got)
        self.assertIn("tokenizer.json", got)

    def test_missing_dependency_exits_2_before_any_test_runs(self):
        with mock.patch.object(run_tests, "preflight", return_value=(["module numpy"], {})), \
                mock.patch.object(run_tests, "run_suite") as ran, mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(run_tests.main(["--require-deps"]), 2)
        ran.assert_not_called()


    def test_expect_offline_refuses_a_reachable_network_before_any_test(self):
        class Conn:
            def close(self):
                pass
        with mock.patch("socket.create_connection", return_value=Conn()), mock.patch.object(unittest.TestLoader, "discover") as discover, \
                mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(run_tests.main(["--expect-offline"]), 2)
        discover.assert_not_called()
        with mock.patch("socket.create_connection", side_effect=OSError("unreachable")):
            self.assertEqual(run_tests.network_reachable(), [])

    def test_summary_counts_match_what_ran(self):
        ok, s = run_tests.run_suite(sample_suite(), require=False, stream=io.StringIO())
        self.assertTrue(s["counts_consistent"])
        self.assertEqual(sum(s["tests_by_class"].values()), s["ran"])
        self.assertEqual(len(s["skipped_tests"]), s["skipped"])


if __name__ == "__main__":
    unittest.main()
