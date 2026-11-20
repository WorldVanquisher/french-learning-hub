#!/usr/bin/env python3
"""Tests for scripts/release/lane_handoffs.py on synthetic lanes (standard library only)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lane_handoffs.py")


def run(*args):
    return subprocess.run([sys.executable, "-B", TOOL, *args], capture_output=True, text=True)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


class LaneHandoffs(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.base = os.path.join(self.td, "base")
        write(os.path.join(self.base, "Dockerfile"), "FROM scratch\n")
        write(os.path.join(self.base, "compose.yaml"), "services: {}\n")
        write(os.path.join(self.base, "docs/shared.md"), "one\ntwo\nthree\nfour\nfive\n")
        write(os.path.join(self.base, "docs/clash.md"), "alpha\n")
        self.run_dir = os.path.join(self.td, "run")

    def tearDown(self):
        shutil.rmtree(self.td)

    def lane(self, name, files, paths_text, *extra, state="FINISHED"):
        content = os.path.join(self.td, f"content-{name}")
        for p, text in files.items():
            write(os.path.join(content, p), text)
        pf = os.path.join(self.td, f"{name}-paths.txt")
        write(pf, paths_text)
        r = run("import", "--lane", name, "--state", state, "--paths", pf, "--content", content,
                "--id", f"{name}@t", "--out", os.path.join(self.run_dir, f"{name}.handoff.json"), *extra)
        return r, content

    def test_import_reads_the_three_path_formats_and_refuses_duplicates(self):
        r, _ = self.lane("a", {"x": "1\n", "y": "2\n", "z": "3\n"}, "A\tx\nM y\nA " + "0" * 64 + " z\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.run_dir, "a.handoff.json")) as fh:
            m = json.load(fh)
        self.assertEqual([(p["status"], p["path"]) for p in m["paths"]], [("A", "x"), ("M", "y"), ("A", "z")])
        self.assertEqual(m["paths"][2]["sha256"], "0" * 64)
        r, _ = self.lane("b", {"x": "1\n"}, "A x\nM x\n")
        self.assertEqual(r.returncode, 2)
        self.assertIn("duplicate paths", r.stderr)

    def test_overlap_tells_clean_identical_and_conflicting_apart(self):
        self.lane("a", {"docs/shared.md": "one CHANGED\ntwo\nthree\nfour\nfive\n", "docs/clash.md": "alpha A\n", "same.md": "s\n"},
                  "M docs/shared.md\nM docs/clash.md\nA same.md\n")
        self.lane("b", {"docs/shared.md": "one\ntwo\nthree\nfour\nfive CHANGED\n", "docs/clash.md": "alpha B\n", "same.md": "s\n"},
                  "M docs/shared.md\nM docs/clash.md\nA same.md\n")
        out = os.path.join(self.td, "ov")
        r = run("overlap", self.run_dir, "--base-dir", self.base, "--base-tree", "f" * 40, "--out", out)
        self.assertEqual(r.returncode, 1, r.stdout)            # a conflict exists
        self.assertIn("docs/shared.md: a + b (M/M): clean merge", r.stdout)
        self.assertIn("docs/clash.md: a + b (M/M): CONFLICT", r.stdout)
        self.assertIn("same.md: a + b (A/A): identical", r.stdout)
        with open(os.path.join(out, "overlap.json")) as fh:
            res = json.load(fh)
        self.assertTrue(all(x["expected_baseline"]["tree_id"] == "f" * 40 for x in res))

    def test_superseded_handoffs_are_marked_and_ignored_for_overlap(self):
        self.lane("old", {"docs/clash.md": "alpha OLD\n"}, "M docs/clash.md\n")
        self.lane("a", {"docs/clash.md": "alpha A\n"}, "M docs/clash.md\n")
        r, _ = self.lane("new", {"x": "1\n"}, "A x\n", "--supersedes", "old@t")
        inv = run("inventory", self.run_dir)
        self.assertIn("old@t  [FINISHED]  SUPERSEDED by new@t", inv.stdout)
        r = run("overlap", self.run_dir, "--base-dir", self.base, "--base-tree", "f" * 40, "--out", os.path.join(self.td, "ov"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("0 path(s) claimed by more than one lane", r.stdout)

    def test_stage_preview_refuses_missing_unexpected_and_doubly_committed_paths(self):
        _, content = self.lane("a", {"x": "1\n", "y": "2\n"}, "A x\nA y\n", "--commit", "one => x", "--commit", "two => y")
        mf = os.path.join(self.run_dir, "a.handoff.json")
        wt = os.path.join(self.td, "wt")
        shutil.copytree(self.base, wt)
        write(os.path.join(wt, "x"), "1\n")
        write(os.path.join(wt, "y"), "2\n")
        r = run("stage-preview", mf, "--worktree", wt, "--baseline-dir", self.base)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("git add -- x", r.stdout)
        self.assertIn("git add -- y", r.stdout)
        os.unlink(os.path.join(wt, "y"))
        write(os.path.join(wt, "docs/clash.md"), "edited outside the handoff\n")
        r = run("stage-preview", mf, "--worktree", wt, "--baseline-dir", self.base)
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing path: y", r.stderr)
        self.assertIn("unexpected changed paths not in the handoff: ['docs/clash.md']", r.stderr)
        with open(mf) as fh:
            m = json.load(fh)
        m["commits"] = [{"subject": "one", "paths": ["x", "y"]}, {"subject": "two", "paths": ["y", "q"]}]
        with open(mf, "w") as fh:
            json.dump(m, fh)
        r = run("stage-preview", mf)
        self.assertEqual(r.returncode, 1)
        self.assertIn("paths in more than one commit: ['y']", r.stderr)
        self.assertIn("unexpected paths in commits (not in the handoff): ['q']", r.stderr)

    def test_deps_order_and_unresolved(self):
        self.lane("a", {"x": "1\n"}, "A x\n", "--depends", "b: needs b's runner [unresolved]")
        self.lane("b", {"y": "1\n"}, "A y\n", "--depends", "c: c's fixture [resolved]")
        self.lane("c", {"z": "1\n"}, "A z\n")
        r = run("deps", self.run_dir)
        self.assertEqual(r.returncode, 1)
        self.assertIn("review order (dependencies first): c -> b -> a", r.stdout)
        self.assertIn("a needs b: needs b's runner: UNRESOLVED", r.stdout)
        self.assertIn("1 unresolved dependency", r.stdout)


if __name__ == "__main__":
    unittest.main()
