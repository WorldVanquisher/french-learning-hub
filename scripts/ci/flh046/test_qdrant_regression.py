"""Unit tests for the FLH-046 helper's pure logic (verdict, image pin, test
list) and, since FLH-050, its endpoint-mode cleanup orchestration. They use
synthetic `go test -json` events and a loopback facade that is NOT Qdrant, and
certify nothing about Qdrant; real acceptance comes only from running the
helper against Qdrant.

Run: python3 -B -m unittest discover -s scripts/ci/flh046 -p 'test_*.py'
"""

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("qdrant_regression", HERE / "qdrant_regression.py")
qr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qr)

NAMES = ["TestQdrantIntegration_A", "TestQdrantIntegration_B"]


def ev(action, test=None, output=None):
    e = {"Action": action, "Package": "french-learning-app/internal/vectorindex"}
    if test:
        e["Test"] = test
    if output:
        e["Output"] = output
    return e


def passing():
    return [ev("run", n) for n in NAMES] + [ev("pass", n) for n in NAMES] + [ev("pass")]


class Evaluate(unittest.TestCase):
    def test_all_expected_pass(self):
        v = qr.evaluate(passing(), NAMES, NAMES, 0)
        self.assertTrue(v["ok"], v["reasons"])
        self.assertEqual(v["passed"], NAMES)

    def test_skip_fails(self):
        events = [ev("run", NAMES[0]), ev("skip", NAMES[0]), ev("run", NAMES[1]), ev("pass", NAMES[1]), ev("pass")]
        v = qr.evaluate(events, NAMES, NAMES, 0)
        self.assertFalse(v["ok"])
        self.assertTrue(any("skipped" in r for r in v["reasons"]))

    def test_all_skipped_like_missing_url_fails(self):
        events = [ev("skip", n) for n in NAMES] + [ev("pass")]
        self.assertFalse(qr.evaluate(events, NAMES, NAMES, 0)["ok"])

    def test_subtest_skip_fails(self):
        events = passing() + [ev("skip", NAMES[0] + "/gate")]
        self.assertFalse(qr.evaluate(events, NAMES, NAMES, 0)["ok"])

    def test_failure_fails(self):
        events = [ev("pass", NAMES[0]), ev("fail", NAMES[1]), ev("fail")]
        v = qr.evaluate(events, NAMES, NAMES, 1)
        self.assertFalse(v["ok"])
        self.assertTrue(any("failed" in r for r in v["reasons"]))

    def test_zero_tests_fails(self):
        v = qr.evaluate([ev("output", output="testing: warning: no tests to run\n"), ev("pass")], NAMES, NAMES, 0)
        self.assertFalse(v["ok"])
        self.assertIn("zero tests ran", v["reasons"])

    def test_missing_expected_fails(self):
        events = [ev("pass", NAMES[0]), ev("pass")]
        v = qr.evaluate(events, NAMES, NAMES, 0)
        self.assertFalse(v["ok"])
        self.assertTrue(any("not run" in r for r in v["reasons"]))

    def test_unexpected_test_fails(self):
        events = passing() + [ev("pass", "TestQdrantIntegration_New")]
        self.assertFalse(qr.evaluate(events, NAMES, NAMES, 0)["ok"])

    def test_list_drift_fails(self):
        v = qr.evaluate(passing(), NAMES, NAMES + ["TestQdrantIntegration_C"], 0)
        self.assertFalse(v["ok"])
        self.assertTrue(any("drifted" in r for r in v["reasons"]))

    def test_build_failure_fails(self):
        events = [ev("build-fail"), ev("fail")]
        self.assertFalse(qr.evaluate(events, NAMES, NAMES, 1)["ok"])

    def test_nonzero_exit_alone_fails(self):
        self.assertFalse(qr.evaluate(passing(), NAMES, NAMES, 2)["ok"])

    def test_unfinished_fails(self):
        self.assertFalse(qr.evaluate(passing(), NAMES, NAMES, None)["ok"])


class Inputs(unittest.TestCase):
    def test_compose_pin_is_exact_digest(self):
        image, tag = qr.pinned_image(qr.COMPOSE_FILE.read_text())
        self.assertRegex(image, r"^qdrant/qdrant:v[0-9.]+@sha256:[0-9a-f]{64}$")
        self.assertTrue(tag.startswith("v"))

    def test_unpinned_or_ambiguous_image_refused(self):
        with self.assertRaises(qr.EnvError):
            qr.pinned_image("    image: qdrant/qdrant:v1.19.1\n")
        pinned = "    image: qdrant/qdrant:v1@sha256:" + "a" * 64 + "\n"
        with self.assertRaises(qr.EnvError):
            qr.pinned_image(pinned * 2)

    def test_expected_list_matches_declared_tests(self):
        expected = qr.read_expected(qr.EXPECTED_FILE.read_text())
        declared = qr.declared_tests([p.read_text() for p in sorted(qr.TEST_DIR.glob("*_test.go"))])
        self.assertTrue(expected)
        self.assertEqual(sorted(expected), sorted(declared))

    def test_usage_errors(self):
        self.assertEqual(qr.main(["--endpoint", "not a url"]), qr.EXIT_USAGE)
        self.assertEqual(qr.main(["--test-timeout", "0"]), qr.EXIT_USAGE)


class Facade:
    """Loopback stand-in for the few Qdrant endpoints the helper calls.

    It is not Qdrant. `fail_lists_from` makes the Nth and later collection
    listings answer 503; `appear` adds a collection at a given listing;
    `delete_noop` answers DELETE with 200 but keeps the collection.
    """

    def __init__(self, fail_lists_from=None, appear=None, delete_noop=False):
        self.names = {"flh042_it_preexisting", "unrelated"}
        self.lists, self.deleted = 0, []
        self.fail_lists_from, self.appear, self.delete_noop = fail_lists_from, appear or {}, delete_noop
        facade = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def reply(self, body):
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/collections":
                    facade.lists += 1
                    if facade.lists in facade.appear:
                        facade.names.add(facade.appear[facade.lists])
                    if facade.fail_lists_from and facade.lists >= facade.fail_lists_from:
                        self.send_error(503)
                        return
                    self.reply({"result": {"collections": [{"name": n} for n in sorted(facade.names)]}})
                elif self.path == "/":
                    self.reply({"version": "facade-not-qdrant"})
                else:
                    self.reply({})

            def do_DELETE(self):
                name = self.path.rsplit("/", 1)[1]
                facade.deleted.append(name)
                if not facade.delete_noop:
                    facade.names.discard(name)
                self.reply({"result": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


EXPECTED = qr.read_expected(qr.EXPECTED_FILE.read_text())


def suite_events(outcome):
    """go test -json events for the real expected list: pass, fail or timeout."""
    events = [ev("run", n) for n in EXPECTED]
    if outcome == "fail":
        events += [ev("fail", EXPECTED[0])] + [ev("pass", n) for n in EXPECTED[1:]] + [ev("fail")]
        return events, 1, False
    if outcome == "timeout":
        return events + [ev("output", output="panic: test timed out after 1s\n")], None, True
    return events + [ev("pass", n) for n in EXPECTED] + [ev("pass")], 0, False


class EndpointCleanup(unittest.TestCase):
    """FLH-050: an endpoint-mode cleanup failure must never report PASS."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="flh050-helper-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.saved_run_suite = qr.run_suite
        self.addCleanup(setattr, qr, "run_suite", self.saved_run_suite)
        saved = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        self.addCleanup(lambda: [signal.signal(s, h) for s, h in saved.items()])
        self.sleep = qr.time.sleep
        self.addCleanup(setattr, qr.time, "sleep", self.sleep)
        qr.time.sleep = lambda _s: None  # the sweep's pause between rounds
        self.suite_calls = 0

    def run_helper(self, facade, outcome="pass"):
        def fake_suite(url, artifacts, timeout_s):
            self.suite_calls += 1
            (artifacts / "go-test.jsonl").write_text("synthetic\n")
            return suite_events(outcome)

        qr.run_suite = fake_suite
        artifacts = self.tmp / "artifacts"
        code = qr.main(["--endpoint", facade.url, "--artifacts", str(artifacts), "--ready-timeout", "5"])
        return code, json.loads((artifacts / "summary.json").read_text())

    def test_flh049_final_listing_503_after_passing_suite_fails(self):
        # FLH-049's case: listings 1 (before) and 2 (after) succeed, the
        # sweep's listing 3 answers 503. Previously exit 0 / PASS.
        with Facade(fail_lists_from=3) as f:
            code, summary = self.run_helper(f)
        self.assertEqual(code, qr.EXIT_ENV)
        self.assertEqual(summary["exit"], qr.EXIT_ENV)
        self.assertTrue(summary["verdict"]["ok"])  # the tests themselves passed
        self.assertEqual(summary["verdict"]["passed"], sorted(EXPECTED))
        self.assertFalse(summary["leftover_cleanup"]["verified"])
        self.assertIn("503", summary["leftover_cleanup"]["error"])
        self.assertIn("endpoint leftover cleanup failed", summary["cleanup_error"])
        self.assertTrue((self.tmp / "artifacts" / "go-test.jsonl").exists())

    def test_clean_endpoint_passes_with_verified_cleanup(self):
        with Facade() as f:
            code, summary = self.run_helper(f)
        self.assertEqual(code, qr.EXIT_OK)
        self.assertEqual(summary["leftover_cleanup"], {"found": [], "not_deleted": [], "verified": True})
        self.assertNotIn("cleanup_error", summary)
        self.assertEqual(f.deleted, [])

    def test_cleanup_failure_keeps_regression_status_and_reasons(self):
        with Facade(fail_lists_from=3) as f:
            code, summary = self.run_helper(f, "fail")
        self.assertEqual(code, qr.EXIT_REGRESSION)
        self.assertTrue(any(r.startswith("failed:") for r in summary["verdict"]["reasons"]))
        self.assertIn("cleanup_error", summary)

    def test_cleanup_failure_keeps_timeout_status(self):
        with Facade(fail_lists_from=3) as f:
            code, summary = self.run_helper(f, "timeout")
        self.assertEqual(code, qr.EXIT_TIMEOUT)
        self.assertTrue(summary["timed_out"])
        self.assertIn("cleanup_error", summary)

    def test_deletion_that_does_not_remove_is_caught_by_verification(self):
        # A collection created late (after the post-suite listing) whose
        # DELETE answers 200 but leaves it in place.
        with Facade(appear={3: "flh042_it_late"}, delete_noop=True) as f:
            code, summary = self.run_helper(f)
        self.assertEqual(code, qr.EXIT_ENV)
        self.assertEqual(summary["leftover_cleanup"]["not_deleted"], ["flh042_it_late"])
        self.assertFalse(summary["leftover_cleanup"]["verified"])
        self.assertIn("flh042_it_late", summary["cleanup_error"])

    def test_leftover_is_deleted_and_preexisting_collections_kept(self):
        with Facade(appear={2: "flh042_it_left"}) as f:
            code, summary = self.run_helper(f)
        self.assertEqual(code, qr.EXIT_REGRESSION)  # a leftover is still a regression
        self.assertTrue(summary["leftover_cleanup"]["verified"])
        self.assertEqual(f.deleted, ["flh042_it_left"])
        self.assertEqual(f.names, {"flh042_it_preexisting", "unrelated"})

    def test_listing_failure_before_the_suite_is_an_environment_error(self):
        with Facade(fail_lists_from=1) as f:
            code, summary = self.run_helper(f)
        self.assertEqual(code, qr.EXIT_ENV)
        self.assertIn("could not list collections before the run", summary["error"])
        self.assertEqual(self.suite_calls, 0)


@unittest.skipUnless(shutil.which("go"), "needs the go toolchain")
class FLH049Reproduction(unittest.TestCase):
    """The exact FLH-049 probe shape, as a subprocess: the unchanged helper
    file, real `go test` over eight trivial tests named like the expected
    list in a temporary module, and a facade whose third listing answers 503.
    FLH-049 observed exit 0 / PASS; the fixed helper must exit 3 / FAIL."""

    def test_cleanup_listing_503_exits_nonzero(self):
        with tempfile.TemporaryDirectory(prefix="flh050-repro-") as temp, Facade(fail_lists_from=3) as f:
            tmp = Path(temp)
            package = tmp / "internal" / "vectorindex"
            package.mkdir(parents=True)
            (tmp / "go.mod").write_text("module flh050probe\n\ngo 1.21\n")
            (package / "probe_test.go").write_text(
                'package vectorindex\nimport "testing"\n' + "\n".join(f"func {n}(t *testing.T) {{}}" for n in EXPECTED) + "\n")
            launcher = tmp / "launch.py"
            launcher.write_text(
                "import importlib.util, pathlib, sys\n"
                f"s = importlib.util.spec_from_file_location('helper', {str(HERE / 'qdrant_regression.py')!r})\n"
                "h = importlib.util.module_from_spec(s)\ns.loader.exec_module(h)\n"
                f"h.ROOT = pathlib.Path({temp!r})\nh.TEST_DIR = h.ROOT / 'internal/vectorindex'\n"
                "sys.exit(h.main(sys.argv[1:]))\n")
            artifacts = tmp / "artifacts"
            env = dict(os.environ, GOTOOLCHAIN="local", GOFLAGS="-mod=mod", GOPROXY="off", GOSUMDB="off")
            p = subprocess.run([sys.executable, "-B", str(launcher), "--endpoint", f.url, "--artifacts", str(artifacts),
                                "--ready-timeout", "5", "--test-timeout", "120"],
                               env=env, capture_output=True, text=True, timeout=300)
            summary = json.loads((artifacts / "summary.json").read_text())
            self.assertEqual(p.returncode, qr.EXIT_ENV, p.stdout + p.stderr)
            self.assertEqual(summary["go_exit"], 0)
            self.assertEqual(summary["verdict"]["passed"], sorted(EXPECTED))
            self.assertIn("503", summary["leftover_cleanup"]["error"])
            self.assertIn("FAIL (exit 3)", p.stdout)
            self.assertNotIn("[flh046] PASS", p.stdout)
            self.assertTrue((artifacts / "go-test.jsonl").stat().st_size > 0)


if __name__ == "__main__":
    unittest.main()
