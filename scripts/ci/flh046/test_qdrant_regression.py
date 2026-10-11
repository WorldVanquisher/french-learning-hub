"""Unit tests for the FLH-046 helper's pure logic (verdict, image pin, test
list). They use synthetic `go test -json` events and certify nothing about
Qdrant; real acceptance comes only from running the helper against Qdrant.

Run: python3 -B -m unittest discover -s scripts/ci/flh046 -p 'test_*.py'
"""

import importlib.util
import unittest
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


if __name__ == "__main__":
    unittest.main()
