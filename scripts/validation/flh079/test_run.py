"""Unit tests for the FLH-079 harness helpers and the workflow's static policy.

They exercise pure logic (verdicts, asset references, refusals, log bounding)
and the workflow file's text; they start no server and certify nothing about
the demo. Acceptance comes only from running run.py and failure_probe.py.

Run: python3 -B -m unittest discover -s scripts/validation/flh079 -p 'test_*.py'
"""

import importlib.util
import os
import re
import socket
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("flh079_run", HERE / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
WORKFLOW = Path(run.REPO) / ".github" / "workflows" / "public-demo.yml"


def stage(status):
    return {"name": "s", "status": status}


def check(status):
    return {"id": "c", "evidence": "http", "status": status}


class VerdictTests(unittest.TestCase):
    def test_fail_beats_blocked_and_pass(self):
        self.assertEqual(run.overall_status([stage("PASS"), stage("BLOCKED")], [check("FAIL")]), "FAIL")

    def test_blocked_beats_pass(self):
        self.assertEqual(run.overall_status([stage("PASS"), stage("BLOCKED")], [check("PASS")]), "BLOCKED")

    def test_not_run_stage_does_not_fail_but_is_not_a_check(self):
        self.assertEqual(run.overall_status([stage("PASS"), stage("NOT RUN")], [check("PASS")]), "PASS")

    def test_exit_codes(self):
        self.assertEqual([run.exit_code_for(s) for s in ("PASS", "FAIL", "BLOCKED")], [0, 1, 3])


class AssetRefTests(unittest.TestCase):
    def test_vite_index(self):
        html = ('<link rel="icon" href="data:," /><script type="module" crossorigin src="/assets/index-A.js"></script>'
                '<link rel="stylesheet" crossorigin href="/assets/index-B.css"><a href="https://x/assets/no.js">')
        self.assertEqual(run.asset_refs(html), ["/assets/index-A.js", "/assets/index-B.css"])

    def test_no_assets(self):
        self.assertEqual(run.asset_refs("<html></html>"), [])


class RefusalTests(unittest.TestCase):
    def test_relative_work_refused(self):
        self.assertIn("absolute", run.refuse_work("rel/dir"))

    def test_work_inside_repository_refused(self):
        self.assertIn("outside the repository", run.refuse_work(os.path.join(run.REPO, "tmp-flh079")))

    def test_existing_work_refused(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("already exists", run.refuse_work(d))

    def test_new_work_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(run.refuse_work(os.path.join(d, "new")))

    def test_main_refuses_without_creating_anything(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run.main(["--work", d]), 2)
            self.assertEqual(os.listdir(d), [])
            self.assertEqual(run.main(["--work", os.path.join(d, "w"), "--port", "80"]), 2)
            self.assertFalse(os.path.exists(os.path.join(d, "w")))


class FileHelperTests(unittest.TestCase):
    def test_tail_copy_bounds_and_marks_truncation(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "a.log"), os.path.join(d, "b.log")
            Path(src).write_bytes(b"x" * 100 + b"END")
            self.assertTrue(run.tail_copy(src, dst, limit=10))
            data = Path(dst).read_bytes()
            self.assertTrue(data.startswith(b"[truncated: last 10 of 103 bytes]"))
            self.assertTrue(data.endswith(b"xxxxxxxEND"))
            self.assertFalse(run.tail_copy(os.path.join(d, "missing"), dst))

    def test_tree_hashes_detect_change_and_new_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "demo.db").write_bytes(b"one")
            before = run.tree_hashes(d)
            Path(d, "demo.db-wal").write_bytes(b"")
            self.assertNotEqual(run.tree_hashes(d), before)
            os.remove(os.path.join(d, "demo.db-wal"))
            self.assertEqual(run.tree_hashes(d), before)
            Path(d, "demo.db").write_bytes(b"two")
            self.assertNotEqual(run.tree_hashes(d), before)


class PortTests(unittest.TestCase):
    def test_port_in_use_detects_listener(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            self.assertTrue(run.port_in_use(port))
        finally:
            s.close()
        self.assertFalse(run.port_in_use(port))


class ReuseTests(unittest.TestCase):
    def test_reused_repository_tooling_exists(self):
        for p in (run.PROC_GUARD, run.ACCEPT_MJS, run.FIXTURES):
            self.assertTrue(os.path.isfile(p), p)

    def test_web_sources_exist_and_exclude_build_outputs(self):
        for name in run.WEB_SOURCES:
            self.assertTrue(os.path.exists(os.path.join(run.REPO, "web", name)), name)
        self.assertNotIn("node_modules", run.WEB_SOURCES)
        self.assertNotIn("dist", run.WEB_SOURCES)

    def test_playwright_pin_matches_flh076(self):
        sh = Path(run.REPO, "scripts", "demo", "flh076", "browser", "run.sh").read_text()
        self.assertIn(run.PLAYWRIGHT_CORE, sh)


class WorkflowPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text()

    def test_triggers(self):
        for t in ("pull_request:", "push:", "workflow_dispatch:"):
            self.assertRegex(self.text, rf"(?m)^  {t}")
        self.assertNotIn("pull_request_target", self.text)
        self.assertRegex(self.text, r"(?m)^    branches:\n      - main$")

    def test_least_privilege_and_no_secrets(self):
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read$")
        self.assertNotIn("secrets.", self.text)
        self.assertNotIn("write", re.sub(r"(?m)^\s*#.*$", "", self.text).split("jobs:")[0])
        self.assertIn("persist-credentials: false", self.text)

    def test_concurrency_cancels(self):
        self.assertRegex(self.text, r"(?m)^concurrency:\n  group: .+\n  cancel-in-progress: true$")

    def test_timeouts_on_job_and_every_run_step(self):
        self.assertRegex(self.text, r"(?m)^    timeout-minutes: \d+$")
        steps = re.split(r"(?m)^      - name: ", self.text.split("steps:", 1)[1])[1:]
        for s in steps:
            if "\n        run:" in s:
                self.assertIn("timeout-minutes:", s, s.splitlines()[0])

    def test_actions_follow_ci_yml_pins(self):
        ci = Path(run.REPO, ".github", "workflows", "ci.yml").read_text()
        for use in re.findall(r"uses: (\S+)", self.text):
            self.assertIn(f"uses: {use}", ci, use)

    def test_bounded_failure_upload(self):
        upload = self.text.split("Upload diagnostics", 1)[1]
        self.assertIn("if: ${{ failure() || cancelled() }}", upload)
        days = int(re.search(r"retention-days: (\d+)", upload).group(1))
        self.assertLessEqual(days, 7)
        path = re.search(r"path: (.+)", upload).group(1)
        self.assertTrue(path.endswith("flh079-diagnostics"), path)

    def test_path_filters_cover_reused_tooling(self):
        for p in ("scripts/validation/flh079/**", "scripts/demo/flh073/**", "scripts/demo/flh076/browser/**",
                  "scripts/demo/flh034/proc_guard.py", "web/**", "internal/**", "cmd/server/**"):
            self.assertEqual(self.text.count(f'"{p}"'), 2, p)  # pull_request and push

    def test_no_external_services(self):
        lowered = self.text.lower()
        for word in ("docker", "qdrant", "aws", "openai", "services:", "gpu"):
            body = re.sub(r"(?m)^\s*#.*$", "", lowered)
            self.assertNotIn(word, body, word)


if __name__ == "__main__":
    unittest.main()
