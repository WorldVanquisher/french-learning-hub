#!/usr/bin/env python3
"""Self-tests for scripts/ci/python_suites.py and the python-tools CI job (standard library only).

  python3 -B -m unittest discover -s scripts/ci -p test_python_suites.py
"""
import contextlib
import importlib.util
import io
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.realpath(os.path.join(HERE, "..", ".."))


def load():
    spec = importlib.util.spec_from_file_location("python_suites", os.path.join(HERE, "python_suites.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PS = load()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def run_main(argv, suites=None, repo=None, env=None):
    out = io.StringIO()
    patches = [mock.patch.object(sys, "argv", ["python_suites.py"] + argv)]
    if suites is not None:
        patches.append(mock.patch.object(PS, "SUITES", suites))
    if repo is not None:
        patches.append(mock.patch.object(PS, "REPO", repo))
    patches.append(mock.patch.dict(os.environ, env or {"GITHUB_ACTIONS": "false"}))
    with contextlib.ExitStack() as st:
        for p in patches:
            st.enter_context(p)
        st.enter_context(contextlib.redirect_stdout(out))
        st.enter_context(contextlib.redirect_stderr(out))
        rc = PS.main()
    return rc, out.getvalue()


class Counts(unittest.TestCase):
    def test_parses_unittest_summaries(self):
        self.assertEqual(PS.counts("...\nRan 20 tests in 1.7s\n\nOK\n")["ran"], 20)
        c = PS.counts("Ran 98 tests in 0.5s\n\nOK (skipped=7, expected failures=1)\n")
        self.assertEqual((c["ran"], c["skipped"], c["expected_failures"], c["unittest"]), (98, 7, 1, "OK"))
        c = PS.counts("Ran 3 tests in 0.0s\n\nFAILED (failures=1, errors=2, skipped=1)\n")
        self.assertEqual((c["failures"], c["errors"], c["skipped"], c["unittest"]), (1, 2, 1, "FAILED"))
        self.assertEqual(PS.counts("Ran 1 test in 0.0s\n\nOK\n")["ran"], 1)

    def test_no_summary_is_not_a_pass(self):
        self.assertIsNone(PS.counts("Traceback (most recent call last):\nImportError: x\n"))


class Runner(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        write(os.path.join(self.td, "good", "tests", "test_ok.py"),
              "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): pass\n"
              "    @unittest.skip('x')\n    def test_b(self): pass\n")
        write(os.path.join(self.td, "bad", "tests", "test_bad.py"),
              "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): self.fail('boom')\n")
        write(os.path.join(self.td, "crash", "tests", "test_crash.py"), "import sys\nsys.exit(3)\n")
        self.suites = {
            "bad-suite": ("bad", ["-B", "-m", "unittest", "discover", "-s", "tests"], ["bad/tests/test_bad.py"]),
            "good-suite": ("good", ["-B", "-m", "unittest", "discover", "-s", "tests"], ["good/tests/test_ok.py"]),
        }

    def tearDown(self):
        import shutil
        shutil.rmtree(self.td)

    def test_failure_propagates_and_every_suite_runs(self):
        rc, out = run_main([], self.suites, self.td)
        self.assertEqual(rc, 1)
        self.assertIn("FAILED: bad-suite", out)
        self.assertRegex(out, r"\| good-suite \| PASS \| 0 \| 2 \| 1 \|")   # counts come from the output
        self.assertRegex(out, r"\| bad-suite \| FAIL \| 1 \| 1 \| 0 \|")

    def test_label_precedes_command(self):
        rc, out = run_main(["--suite", "good-suite"], self.suites, self.td)
        self.assertEqual(rc, 0)
        self.assertLess(out.index("===== good-suite ====="), out.index("command: "))
        rc, out = run_main(["--suite", "good-suite"], self.suites, self.td, env={"GITHUB_ACTIONS": "true"})
        self.assertLess(out.index("::group::good-suite"), out.index("command: "))
        self.assertIn("::endgroup::", out)

    def test_missing_fixture_names_the_path(self):
        suites = {"good-suite": ("good", self.suites["good-suite"][1], ["good/tests/fixtures/missing.json"])}
        rc, out = run_main([], suites, self.td)
        self.assertEqual(rc, 1)
        self.assertIn(os.path.join(self.td, "good/tests/fixtures/missing.json"), out)
        self.assertRegex(out, r"\| good-suite \| MISSING \|")

    def test_missing_interpreter_names_the_path(self):
        rc, out = run_main(["--python", os.path.join(self.td, "no-such-python3")], self.suites, self.td)
        self.assertEqual(rc, 2)
        self.assertIn(os.path.join(self.td, "no-such-python3"), out)

    def test_output_without_summary_fails(self):
        suites = {"crash-suite": ("crash", ["-B", "tests/test_crash.py"], ["crash/tests/test_crash.py"])}
        rc, out = run_main([], suites, self.td)
        self.assertEqual(rc, 1)
        self.assertIn("FAILED: crash-suite", out)


class RunnerEvidence(unittest.TestCase):
    """Items 062-068: optional suites, skips and expected failures apart, timings and resources,
    the negative fixture for required tests that skip, and the hermetic run."""

    FIXTURE = os.path.join(HERE, "fixtures", "skipping-suite")

    def setUp(self):
        self.td = tempfile.mkdtemp()
        write(os.path.join(self.td, "ok", "tests", "test_ok.py"),
              "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): pass\n"
              "    @unittest.expectedFailure\n    def test_b(self): self.fail('known')\n")
        write(os.path.join(self.td, "calls", "tests", "test_calls.py"),
              "import subprocess, unittest\nclass T(unittest.TestCase):\n"
              "    def test_a(self): subprocess.run(['aws', 'sts', 'get-caller-identity'])\n")
        write(os.path.join(self.td, "env", "tests", "test_env.py"),
              "import os, unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n"
              "        self.assertFalse([k for k in os.environ if k.startswith('AWS_') and k not in "
              "('AWS_CONFIG_FILE', 'AWS_SHARED_CREDENTIALS_FILE', 'AWS_EC2_METADATA_DISABLED')])\n"
              "        self.assertEqual(os.listdir(os.environ['HOME']), [])\n"
              "        self.assertEqual(os.environ['AWS_SHARED_CREDENTIALS_FILE'], os.devnull)\n")
        self.suites = {
            "skips": (self.FIXTURE, ["-B", "-m", "unittest", "discover", "-s", "tests"], []),
            "ok": ("ok", ["-B", "-m", "unittest", "discover", "-s", "tests"], []),
            "opt": ("ok", ["-B", "-m", "unittest", "discover", "-s", "tests"], []),
        }

    def tearDown(self):
        import shutil
        shutil.rmtree(self.td)

    def test_a_required_test_that_skips_fails_only_when_required(self):
        rc, out = run_main(["--suite", "skips"], self.suites, self.td)
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"\| skips \| PASS \| 0 \| 2 \| 1 \|")
        self.assertIn("Skipped tests (ran, counted apart): skips 1", out)
        rc, out = run_main(["--suite", "skips", "--fail-on-skip", "skips"], self.suites, self.td)
        self.assertEqual(rc, 1, out)
        self.assertRegex(out, r"\| skips \| FAIL \| 0 \| 2 \| 1 \|")

    def test_skips_expected_failures_and_absent_suites_are_reported_apart(self):
        js = os.path.join(self.td, "r.json")
        with mock.patch.object(PS, "OPTIONAL", {"opt": "ok/not-yet-there.py"}):
            rc, out = run_main(["--json", js], self.suites, self.td)
            self.assertEqual(rc, 0, out)
            self.assertIn("Expected failures (known, not passes): ok 1", out)
            self.assertIn("Suites not run (NOT-PRESENT, not passes): opt", out)
            self.assertIn("(2 suite(s) run, not present: opt", out)
            rc, out = run_main(["--require", "opt"], self.suites, self.td)
            self.assertEqual(rc, 1)
            self.assertIn("FAILED: opt", out)
        import json
        with open(js) as fh:
            res = {r["label"]: r for r in json.load(fh)["suites"]}
        self.assertEqual(res["opt"]["status"], "NOT-PRESENT")
        for k in ("started_at", "seconds", "cpu_seconds", "max_rss_mb", "ran", "skipped", "expected_failures"):
            self.assertIn(k, res["ok"], k)
        self.assertGreater(res["ok"]["max_rss_mb"], 1)

    def test_hermetic_traps_cloud_and_docker_calls_and_scrubs_the_environment(self):
        suites = {"calls": ("calls", ["-B", "-m", "unittest", "discover", "-s", "tests"], []),
                  "env": ("env", ["-B", "-m", "unittest", "discover", "-s", "tests"], [])}
        rc, out = run_main(["--hermetic", "--suite", "env"], suites, self.td,
                           env={"GITHUB_ACTIONS": "false", "AWS_PROFILE": "x", "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE"})
        self.assertEqual(rc, 0, out)
        self.assertIn("trapped calls: 0", out)
        rc, out = run_main(["--hermetic", "--suite", "calls"], suites, self.td)
        self.assertEqual(rc, 1, out)
        self.assertIn("trapped calls: 1 (aws)", out)
        self.assertIn("FAILED: hermetic (1 trapped call(s))", out)


class RealSuites(unittest.TestCase):
    def test_every_suite_path_resolves_from_the_checkout(self):
        for label, (cwd, args, needs) in PS.SUITES.items():
            with self.subTest(suite=label):
                if label in PS.OPTIONAL and not os.path.exists(os.path.join(REPO, PS.OPTIONAL[label])):
                    continue        # an optional suite whose entry has not landed: reported NOT-PRESENT
                self.assertTrue(os.path.isdir(os.path.join(REPO, cwd)), cwd)
                for p in needs:
                    self.assertTrue(os.path.exists(os.path.join(REPO, p)), p)

    def test_optional_suites_are_gated_on_a_path_they_need(self):
        for label, gate in PS.OPTIONAL.items():
            self.assertIn(gate, PS.SUITES[label][2])


class Workflow(unittest.TestCase):
    """Structural checks of ci.yml with the standard library (no YAML parser is a dependency here)."""
    with open(os.path.join(REPO, ".github", "workflows", "ci.yml")) as _fh:
        TEXT = _fh.read()

    def test_no_tabs_and_even_indentation(self):
        for n, line in enumerate(self.TEXT.splitlines(), 1):
            with self.subTest(line=n):
                self.assertNotIn("\t", line)
                indent = len(line) - len(line.lstrip(" "))
                self.assertEqual(indent % 2, 0, line)

    def test_jobs_kept_and_python_tools_added(self):
        jobs = re.findall(r"^  ([a-z][a-z0-9-]*):\s*$", self.TEXT.split("\njobs:\n", 1)[1], re.M)
        self.assertEqual(jobs, ["ci", "qdrant-integration", "web", "python-tools"])

    def test_triggers_have_no_path_filter(self):
        on = self.TEXT.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("pull_request:", on)
        self.assertNotIn("paths", on)  # every PR and every push to main runs every job

    def test_python_tools_runs_this_runner(self):
        job = self.TEXT.split("\n  python-tools:\n", 1)[1]
        self.assertIn("uses: actions/checkout@v6", job)
        self.assertIn('python3 -B scripts/ci/python_suites.py --hermetic --summary "$GITHUB_STEP_SUMMARY" '
                      '--json "$RUNNER_TEMP/python-suites.json"', job)
        self.assertTrue(os.path.isfile(os.path.join(REPO, "scripts", "ci", "python_suites.py")))

    def test_results_upload_keeps_a_failing_status(self):
        """The upload runs after a failure (if: always()) and nothing in the job hides the failure:
        no continue-on-error, no `|| true` after the suites, and the JSON names the file uploaded."""
        job = self.TEXT.split("\n  python-tools:\n", 1)[1]
        steps = job.split("\n      - name: ")[1:]
        suite = next(st for st in steps if "python_suites.py" in st)
        upload = next(st for st in steps if "upload-artifact" in st)
        self.assertLess(steps.index(suite), steps.index(upload))
        self.assertIn("if: always()", upload)
        self.assertIn("path: ${{ runner.temp }}/python-suites.json", upload)
        self.assertNotIn("continue-on-error", job)
        self.assertNotIn("|| true", suite)
        self.assertNotIn("if:", suite)

    def test_installs_use_the_existing_locks(self):
        """Every dependency install in every workflow uses an existing lock or pin."""
        wf = os.path.join(REPO, ".github", "workflows")
        for f in sorted(os.listdir(wf)):
            with open(os.path.join(wf, f)) as fh:
                text = fh.read()
            with self.subTest(workflow=f):
                for line in text.splitlines():
                    code = line.split("#", 1)[0]
                    if re.search(r"\bnpm (install|i)\b", code):
                        self.fail(f"{f}: `npm install` instead of `npm ci` (package-lock.json): {line.strip()}")
                    if re.search(r"\bpip3? install\b", code) and not re.search(r"--require-hashes", text):
                        self.fail(f"{f}: pip install without --require-hashes -r <lock>: {line.strip()}")
                    if re.search(r"\bgo (get|install)\b", code):
                        self.fail(f"{f}: go get/install outside go.sum: {line.strip()}")
                for m in re.finditer(r"uses:\s*([^\s#]+)", text):
                    self.assertRegex(m.group(1), r"@v?[0-9]", f"{f}: action without a version pin: {m.group(1)}")


if __name__ == "__main__":
    unittest.main()
