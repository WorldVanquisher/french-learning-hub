"""Tests for the release helper scripts (stdlib only; no network, no Docker).

  python3 -B -m unittest discover -s scripts/release -p 'test_*.py'
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PREFLIGHT = os.path.join(HERE, "disk_preflight.sh")
CHECK = os.path.join(HERE, "publish_metadata_check.py")
# Fake links, assembled at run time so this file itself never contains one.
HOST = "https://claude" + ".ai/"
SESSION = HOST + "code/" + "session_" + "01FAKEFAKEFAKEFAKE"


def tree_digest(root):
    h = hashlib.sha256()
    for dp, dns, fns in sorted(os.walk(root)):
        dns.sort()
        for f in sorted(fns):
            p = os.path.join(dp, f)
            with open(p, "rb") as fh:
                h.update(os.path.relpath(p, root).encode() + b"\0" + fh.read())
    return h.hexdigest()


class DiskPreflight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flh-preflight-test-")
        self.work = os.path.join(self.tmp, "work")
        os.makedirs(os.path.join(self.work, "other-worker"))
        with open(os.path.join(self.work, "other-worker", "scratch.bin"), "wb") as fh:
            fh.write(os.urandom(2048))

    def tearDown(self):
        os.chmod(self.work, 0o700)
        shutil.rmtree(self.tmp)

    def run_preflight(self, *locs, env=None):
        e = dict(os.environ, TMPDIR=self.tmp)
        e.update(env or {})
        return subprocess.run(["bash", PREFLIGHT, "--probe-mb", "1", *locs], capture_output=True, text=True, env=e)

    def test_pass_reports_each_location_and_leaves_no_probe(self):
        before = tree_digest(self.work)
        r = self.run_preflight(f"work={self.work}:1", f"tmp={self.tmp}:1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("work OK", r.stdout)
        self.assertIn("tmp OK", r.stdout)
        self.assertEqual(tree_digest(self.work), before, "another worker's files changed")
        self.assertFalse([f for f in os.listdir(self.work) if f.startswith(".flh-disk-preflight")])

    def test_not_enough_space_is_blocked_with_tmpdir_space_and_dir(self):
        before = tree_digest(self.work)
        r = self.run_preflight(f"work={self.work}:999999999")
        self.assertEqual(r.returncode, 3)
        self.assertIn(f"work BLOCKED: {self.work}", r.stderr)
        self.assertIn("MiB available, 999999999 MiB needed", r.stderr)
        self.assertIn(f"TMPDIR={self.tmp}", r.stderr)
        self.assertIn("nothing was cleaned", r.stderr)
        self.assertEqual(tree_digest(self.work), before)

    def test_unwritable_directory_fails_the_probe(self):
        os.chmod(self.work, 0o500)
        r = self.run_preflight(f"work={self.work}:1")
        self.assertEqual(r.returncode, 3)
        self.assertIn("cannot create a file there", r.stderr)

    def test_noprobe_and_missing_directory_and_unset_tmpdir(self):
        r = self.run_preflight(f"ro={self.work}:1:noprobe", f"gone={self.tmp}/missing:1",
                               env={"TMPDIR": ""})
        self.assertEqual(r.returncode, 3)
        self.assertIn("ro OK", r.stdout)
        self.assertIn("gone BLOCKED", r.stderr)
        self.assertIn("directory does not exist", r.stderr)
        self.assertIn("TMPDIR=<unset, so /tmp>", r.stderr)

    def test_bad_usage(self):
        r = subprocess.run(["bash", PREFLIGHT, "nonsense"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


class MetadataCheck(unittest.TestCase):
    def check(self, text, kind="text"):
        return subprocess.run([sys.executable, "-I", CHECK, "--label", "t", "--kind", kind, "-"],
                              input=text, capture_output=True, text=True)

    def test_clean_message_with_ai_prose_and_human_coauthor_passes(self):
        text = ("feat: add release smoke\n\nThis change was drafted with Claude Code and reviewed by a human.\n"
                "Co-authored with Claude in a pairing session, then edited.\n\n"
                "🤖 Generated with [Claude Code](https://claude.com/claude-code)\n\n"
                "Co-authored-by: Jane Doe <jane@example.com>\n"
                "Co-authored-by: Claudia Smith <claudia@example.org>\n")
        r = self.check(text, "pr-body")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(r.stdout, "")

    def test_claude_coauthor_trailer_fails(self):
        for trailer in ("Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
                        "co-authored-by: Claude <claude@users.noreply.github.com>",
                        "Co-authored-by: Bot <bot@mail.anthropic.com>"):
            r = self.check(f"fix: x\n\n{trailer}\n", "commit")
            self.assertEqual(r.returncode, 1, trailer)
            self.assertIn("ai-coauthor-trailer", r.stdout)

    def test_session_trailer_and_private_links_fail_and_are_redacted(self):
        text = (f"fix: x\n\nClaude-Session: {SESSION}\nSee {SESSION} and {HOST}chat/0f1e2d3c-aaaa-bbbb\n"
                f"Shared: {HOST}share/1234abcd-ef\n")
        r = self.check(text, "pr-body")
        self.assertEqual(r.returncode, 1)
        self.assertIn("session-trailer", r.stdout)
        self.assertEqual(r.stdout.count("private-session-link"), 3)
        self.assertNotIn("01FAKEFAKE", r.stdout)
        self.assertNotIn("0f1e2d3c", r.stdout)
        self.assertIn(HOST + "code/session_[REDACTED]", r.stdout)

    def test_ai_author_identity_only_for_commits(self):
        text = "Author: Claude <noreply@anthropic.com>\nCommitter: Owner <owner@example.com>\n\nfeat: x\n"
        self.assertEqual(self.check(text, "commit").returncode, 1)
        self.assertEqual(self.check(text, "pr-body").returncode, 0)
        ok = "Author: Owner <owner@example.com>\nCommitter: Owner <owner@example.com>\n\nfeat: x\n"
        self.assertEqual(self.check(ok, "commit").returncode, 0)

    def test_redact_filter(self):
        r = subprocess.run([sys.executable, "-I", CHECK, "--redact"], input=f"error near {SESSION}.\n",
                           capture_output=True, text=True)
        self.assertEqual(r.stdout, "error near " + HOST + "code/session_[REDACTED].\n")

    def test_unreadable_file_is_usage_error(self):
        r = subprocess.run([sys.executable, "-I", CHECK, "/nonexistent/file"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
