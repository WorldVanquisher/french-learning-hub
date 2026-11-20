"""Tests for evidence_share.py (R2-071 to R2-074) on synthetic files."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "evidence_share.py")
HOST = "box." + "tail0000a.ts" + ".net"          # never a real name; assembled so this file holds no literal one


def run(*args):
    return subprocess.run([sys.executable, "-B", TOOL, *args], capture_output=True, text=True)


class EvidenceShare(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.td)
        self.src = os.path.join(self.td, "seal")
        os.makedirs(os.path.join(self.src, "evidence"))
        self.w("evidence/run.log", f"ok from /home/someone/work at http://{HOST}:8765/v1 and 100.101.102.103\n")
        self.w("evidence/clean.txt", "PASS 12/12\n")
        self.w("report.json", json.dumps({"base_url": f"http://{HOST}:8765/v1"}))
        db = sqlite3.connect(os.path.join(self.src, "app.db"))
        db.execute("create table t(x)")
        db.commit()
        db.close()
        lines = []
        for rel in ("evidence/run.log", "evidence/clean.txt", "report.json", "app.db"):
            import hashlib
            with open(os.path.join(self.src, rel), "rb") as fh:
                lines.append(f"{hashlib.sha256(fh.read()).hexdigest()}  {rel}")
        self.w("SHA256SUMS", "\n".join(lines) + "\n")

    def w(self, rel, text):
        p = os.path.join(self.src, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)

    def test_audit_reports_classes_never_values(self):
        tar = os.path.join(self.td, "pkg.tar.gz")
        with tarfile.open(tar, "w:gz") as tf:
            tf.add(os.path.join(self.src, "report.json"), arcname="pkg/RELEASE.json")
        r = run("audit", self.src, tar, "--json")
        self.assertEqual(r.returncode, 1)
        out = json.loads(r.stdout)
        files = {x["file"]: set(x["classes"]) for x in out["rows"]}
        self.assertEqual(files["evidence/run.log"], {"private-address", "home-path"})
        self.assertEqual(files["app.db"], {"database"})
        self.assertIn("pkg.tar.gz:pkg/RELEASE.json", files)
        self.assertNotIn("evidence/clean.txt", files)
        for text in (r.stdout, run("audit", self.src).stdout):
            self.assertNotIn(HOST, text)
            self.assertNotIn("100.101.102.103", text)
            self.assertNotIn("someone", text)

    def test_share_redacts_records_and_is_not_the_seal(self):
        out = os.path.join(self.td, "share")
        r = run("share", self.src, "--out", out, "--include", "evidence/*", "--seal-of", self.src)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(out, "evidence/run.log")) as fh:
            text = fh.read()
        self.assertNotIn(HOST, text)
        self.assertNotIn("100.101.102.103", text)
        self.assertNotIn("/home/someone", text)
        with open(os.path.join(out, "REDACTIONS.json")) as fh:
            man = fh.read()
        self.assertNotIn(HOST, man)
        self.assertIn('"replacements"', man)
        self.assertFalse(os.path.exists(os.path.join(out, "SHA256SUMS")))
        v = run("verify-seal", out)
        self.assertNotEqual(v.returncode, 0)
        self.assertIn("is a redacted copy", v.stderr)
        self.assertEqual(run("verify-seal", self.src).returncode, 0)

    def test_share_refuses_databases_and_unredactable_files(self):
        r = run("share", self.src, "--out", os.path.join(self.td, "s1"), "--include", "app.db")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("never shared", r.stderr)


if __name__ == "__main__":
    unittest.main()
