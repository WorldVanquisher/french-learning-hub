"""Tests for pin_audit.py (R2-076) on a synthetic tree."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pin_audit.py")


class PinAudit(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.t)
        self.w(".github/workflows/ci.yml", "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v6\n"
               "      - uses: actions/setup-go@0123456789abcdef0123456789abcdef01234567\n")
        self.w("Dockerfile", "FROM golang:1.26@sha256:" + "a" * 64 + " AS build\nFROM build AS test\nFROM scratch\n")
        self.w("go.mod", "module x\n\ngo 1.26.5\n")
        self.w("go.sum", "x v1 h1:abc=\n")
        self.w("web/package-lock.json", json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/a": {
            "resolved": "https://registry.npmjs.org/a.tgz", "integrity": "sha512-x"}}}))
        self.w("tools/speaking/requirements-cpu.lock", "numpy==2.5.4 \\\n    --hash=sha256:" + "b" * 64 + "\n")

    def w(self, rel, text):
        p = os.path.join(self.t, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)

    def run_it(self):
        r = subprocess.run([sys.executable, "-B", TOOL, self.t, "--json"], capture_output=True, text=True)
        return r.returncode, json.loads(r.stdout)

    def test_pinned_tree_passes_with_a_tag_warning(self):
        rc, out = self.run_it()
        self.assertEqual(rc, 0, out["fail"])
        self.assertEqual(sorted(w["pin"] for w in out["workflows"]), ["sha", "tag"])
        self.assertEqual(len(out["warn"]), 1)

    def test_unpinned_from_missing_integrity_and_unhashed_lock_fail(self):
        self.w("Dockerfile", "FROM alpine:3.22\n")
        self.w("web/package-lock.json", json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/a": {"resolved": "u"}}}))
        self.w("tools/speaking/requirements-cpu.lock", "numpy==2.5.4\n")
        rc, out = self.run_it()
        self.assertEqual(rc, 1)
        text = " ".join(out["fail"])
        self.assertIn("FROM alpine:3.22 is not pinned by digest", text)
        self.assertIn("without integrity", text)
        self.assertIn("without --hash", text)


if __name__ == "__main__":
    unittest.main()
