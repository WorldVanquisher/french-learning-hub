"""Model runtime operations: interrupted and corrupted downloads, candidate bundles (standard library only)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)

from flh_speaking import fetch  # noqa: E402

GOOD = b"weights-" * 4096
MODE = {"value": "good"}


class Files(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = {"good": GOOD, "corrupt": GOOD[:-1] + b"X", "truncated": GOOD}[MODE["value"]]
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if MODE["value"] == "truncated":
            self.wfile.write(body[: len(body) // 2])  # the connection drops half way
            self.wfile.flush()
            self.connection.shutdown(2)
            return
        self.wfile.write(body)


class Downloads(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Files)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.src = {"repo": "synthetic/weights", "revision": "0" * 40, "url": f"http://127.0.0.1:{self.srv.server_address[1]}/",
                    "files": {"model.bin": (len(GOOD), ("sha256", hashlib.sha256(GOOD).hexdigest()))}}
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def files_left(self):
        return sorted(os.path.relpath(os.path.join(dp, f), self.tmp.name) for dp, _, fs in os.walk(self.tmp.name) for f in fs)

    def test_interrupted_and_corrupted_downloads_leave_nothing(self):
        for mode in ("truncated", "corrupt"):
            MODE["value"] = mode
            with self.assertRaises(Exception):
                fetch.fetch_one(self.tmp.name, self.src, "model.bin", dataset=False, log=lambda *_: None)
            self.assertEqual(self.files_left(), [], mode)
        MODE["value"] = "good"
        p = fetch.fetch_one(self.tmp.name, self.src, "model.bin", dataset=False, log=lambda *_: None)
        self.assertIsNone(fetch.verify(p, *self.src["files"]["model.bin"]))
        with open(p, "r+b") as fh:  # damage after the download: check reports it, a refetch repairs it
            fh.seek(10)
            fh.write(b"Z")
        self.assertIn("sha256", fetch.verify(p, *self.src["files"]["model.bin"]) or "")
        fetch.fetch_one(self.tmp.name, self.src, "model.bin", dataset=False, log=lambda *_: None)
        self.assertIsNone(fetch.verify(p, *self.src["files"]["model.bin"]))


class Bundle(unittest.TestCase):
    def test_export_excludes_trainer_state_and_verifies(self):
        with tempfile.TemporaryDirectory() as t:
            ck = os.path.join(t, "step-000024")
            os.makedirs(ck)
            for n, b in (("model.safetensors", b"w" * 100), ("config.json", b"{}"), ("tokenizer.json", b"{}"), ("trainer_state.pt", b"secret-ish"),
                         ("run_manifest.json", json.dumps({"step": 24, "config_sha256": "c" * 64, "data_manifest_sha256": "d" * 64}).encode())):
                with open(os.path.join(ck, n), "wb") as fh:
                    fh.write(b)
            out = os.path.join(t, "bundle")
            run = lambda *a: subprocess.run([sys.executable, "-I", "-B", os.path.join(PKG, "scripts", "export_candidate.py"), *a],
                                            capture_output=True, text=True)
            r = run("--checkpoint", ck, "--out", out, "--name", "synthetic-ft")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("trainer_state.pt", os.listdir(out))
            with open(os.path.join(out, "candidate_manifest.json"), encoding="utf-8") as fh:
                man = json.load(fh)
            self.assertEqual((man["status"], man["promotion"]["performed"], man["training"]["step"]), ("candidate", False, 24))
            with open(os.path.join(out, "MODEL_CARD.md"), encoding="utf-8") as fh:
                self.assertIn("not promoted", fh.read())
            self.assertEqual(run("--verify", out).returncode, 0)
            with open(os.path.join(out, "model.safetensors"), "ab") as fh:
                fh.write(b"x")
            bad = run("--verify", out)
            self.assertEqual(bad.returncode, 1)
            self.assertIn("model.safetensors", bad.stdout)


class Identity(unittest.TestCase):
    def test_model_and_prompt_changes_are_told_apart(self):
        sys.path.insert(0, os.path.join(PKG, "scripts"))
        import identity_diff as idd
        base = {"deployment_id": "whisper-base@e37978b90ca9/x/cpu-fp32/aaaa", "defining": {"model": {"kind": "pretrained", "files": {"model.safetensors": "a"}},
                                                                                           "decoding": {"policy": "p1"}, "audio": "c", "code_sha256": "k", "runtime": {"torch": "1"}, "device": "cpu"}}
        cand = json.loads(json.dumps(base))
        cand["deployment_id"] = "whisper-base-ft@step24-bbbb/x/cpu-fp32/bbbb"
        cand["defining"]["model"] = {"kind": "fine_tuned", "files": {"model.safetensors": "b"}}
        with tempfile.TemporaryDirectory() as t:
            pa, pb = os.path.join(t, "pa"), os.path.join(t, "pb")
            for d, txt in ((pa, "v1"), (pb, "v2")):
                os.makedirs(d)
                with open(os.path.join(d, "feedback.txt"), "w", encoding="utf-8") as fh:
                    fh.write(txt)
            self.assertEqual(idd.diff(base, cand)["kind"], "model change")
            r = idd.diff(base, base, pa, pb)
            self.assertEqual((r["kind"], r["transcription_identity_changed"]), ("prompt change", False))
            self.assertEqual(idd.diff(base, cand, pa, pb)["kind"], "mixed change")
            self.assertEqual(idd.diff(base, base, pa, pa)["kind"], "no change")


if __name__ == "__main__":
    unittest.main()
