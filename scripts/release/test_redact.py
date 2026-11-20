#!/usr/bin/env python3
"""Tests for scripts/release/redact.py (item 077) and the redacted handoff inventory (item 078)."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "redact.py")


def red(text, *args):
    r = subprocess.run([sys.executable, "-I", "-B", TOOL, *args], input=text, capture_output=True, text=True)
    return r.stdout, r.stderr


class Redact(unittest.TestCase):
    def test_each_rule(self):
        cases = [
            ("arn:aws:iam::111122223333:role/flh-stg-host", "arn:aws:iam::<ACCOUNT>:role/flh-stg-host"),
            ("account 111122223333", "account <ACCOUNT>"),
            ("i-0123456789abcdef0 vol-0123456789abcdef0", "<INSTANCE> <VOLUME>"),
            ("s3://flh-stg-20261118000000000000000000/releases/x.tar", "s3://<BUCKET>/releases/x.tar"),
            ("bucket flh-stg-20261118000000000000000000", "bucket <BUCKET>"),
            ("10.85.0.12 and 127.0.0.1:8080", "<IP> and 127.0.0.1:8080"),
            ("ip-10-85-0-12.ec2.internal", "<HOST>"),
            ("owner@example.com", "<EMAIL>"),
            ("https://b.s3.amazonaws.com/k?X-Amz-Signature=abc", "<PRIVATE-URL>"),
            ("database: /home/someone/data/app/app.db", "database: <path>/app.db"),
            ("worktree ~/workspace/overnight/x/release", "worktree <path>/release"),
            ("....../home/someone/x/tool.py:72: Warning", "......~/x/tool.py:72: Warning"),   # glued to progress dots
            ("see ./scripts/release/x.py", "see ./scripts/release/x.py"),
        ]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(red(raw)[0], want)

    def test_kept_and_named(self):
        out, err = red("project flh-stg-20261119183937-first; see deploy/aws/private-staging/RUNBOOK.md; "
                       "root /srv/flh-staging/current", "--name", "ROOT=/srv/flh-staging")
        self.assertEqual(out, "project flh-stg-20261119183937-first; see deploy/aws/private-staging/RUNBOOK.md; "
                              "root <ROOT>/current")
        self.assertIn("read the result before sharing it", err)
        self.assertEqual(red("/opt/keep/me /var/x/y", "--keep-path", "/opt/keep")[0], "/opt/keep/me <path>/y")


class RedactedInventory(unittest.TestCase):
    def test_inventory_redact_hides_local_paths(self):
        import json
        import tempfile
        import shutil
        td = tempfile.mkdtemp()
        try:
            run_dir = os.path.join(td, "run")
            os.makedirs(run_dir)
            with open(os.path.join(td, "p.txt"), "w") as fh:
                fh.write("A x\n")
            r = subprocess.run([sys.executable, "-I", "-B", os.path.join(HERE, "lane_handoffs.py"), "import", "--lane", "a",
                                "--state", "FINISHED", "--paths", os.path.join(td, "p.txt"), "--id", "a@t",
                                "--worktree", "/home/someone/private/worktree", "--test", "run /home/someone/x => OK",
                                "--out", os.path.join(run_dir, "a.handoff.json")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            for extra in ([], ["--json"]):
                r = subprocess.run([sys.executable, "-I", "-B", os.path.join(HERE, "lane_handoffs.py"), "inventory", run_dir,
                                    "--redact", *extra], capture_output=True, text=True)
                self.assertNotIn("/home/someone", r.stdout)
                self.assertIn("<path>/worktree", r.stdout)
            json.loads(r.stdout)        # still valid JSON
        finally:
            shutil.rmtree(td)


if __name__ == "__main__":
    unittest.main()
