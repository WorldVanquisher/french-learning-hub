"""The local mock model smoke (REL-130) must pass, offline and in a fresh directory."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SMOKE = os.path.join(HERE, "..", "rehearsal", "mock_model_smoke.py")
CONFIG = os.path.join(HERE, "..", "runtime", "model-runtime.example.json")


class MockModelSmoke(unittest.TestCase):
    def test_every_exit_criterion_passes(self):
        with tempfile.TemporaryDirectory() as d:
            work = os.path.join(d, "run")
            r = subprocess.run([sys.executable, "-I", "-B", "-W", "error::ResourceWarning", SMOKE, work, "--config", CONFIG],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            with open(os.path.join(work, "results.json"), encoding="utf-8") as fh:
                res = json.load(fh)
            self.assertEqual([x["step"] for x in res["rows"]], [f"S{i}" for i in range(1, 10)])
            self.assertTrue(all(x["status"] == "PASS" for x in res["rows"]))
            self.assertEqual(sorted(os.listdir(work)), ["mock.log", "results.json", "results.tsv"])

    def test_existing_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, "-I", "-B", SMOKE, d], capture_output=True, text=True, timeout=60)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("refused", r.stdout + r.stderr)

    def test_example_config_states_limits_probes_and_fallback(self):
        with open(CONFIG, encoding="utf-8") as fh:
            cfg = json.load(fh)
        for k in ("memory_mib", "cpus", "pids", "disk_gib", "max_request_bytes", "request_timeout_s", "max_in_flight", "startup_deadline_s"):
            self.assertIn(k, cfg["limits"])
        self.assertIn("warm-up", cfg["probes"]["readyz"])
        self.assertIn("no retry", cfg["fallback"])


if __name__ == "__main__":
    unittest.main()
