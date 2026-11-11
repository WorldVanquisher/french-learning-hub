import json
import tempfile
import unittest
from pathlib import Path

import render_job

HERE = Path(__file__).resolve().parent
CFG = json.dumps({"model_name_or_path": "/opt/ml/input/data/model", "smoke": False})
VALUES = {"REGISTRY": "123456789012.dkr.ecr.us-east-1.amazonaws.com", "IMAGE_DIGEST": "sha256:" + "a" * 64,
          "EXEC_ROLE_ARN": "arn:aws:iam::123456789012:role/flh-extractor-exec", "BUCKET": "example-bucket",
          "BASE_MODEL_KEY": "qwen3.5-4b-851bf6e8", "TRAIN_SHA256": "b" * 64, "DEV_SHA256": "c" * 64, "CONFIG_JSON": CFG,
          "PROMPTS_SHA256": "d" * 64, "ADAPTER_KEY": "run-1"}


class Render(unittest.TestCase):
    def test_bounded_jobs_render(self):
        with tempfile.TemporaryDirectory() as d:
            for tmpl, run in (("sft-smoke", "smoke"), ("sft-experiment", "experiment"), ("predict-eval", "predict")):
                job = json.loads(render_job.render(HERE / "jobs" / f"{tmpl}.json.tmpl", run, d, VALUES).read_text())
                self.assertTrue(job["TrainingJobName"].startswith(f"flh-extractor-{run}-"))
                self.assertTrue(job["EnableNetworkIsolation"])
                self.assertNotIn("eval", {c["ChannelName"] for c in job["InputDataConfig"]})
                self.assertIn("@sha256:", job["AlgorithmSpecification"]["TrainingImage"])

    def test_out_of_bounds_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                render_job.render(HERE / "jobs/sft-smoke.json.tmpl", "smoke", d, dict(VALUES, IMAGE_DIGEST="latest"))
            with self.assertRaises(SystemExit):
                render_job.render(HERE / "jobs/sft-experiment.json.tmpl", "smoke", d, VALUES)  # 10800 s > smoke bound
            with self.assertRaises(SystemExit):
                render_job.render(HERE / "jobs/sft-experiment.json.tmpl", "experiment", d,
                                  dict(VALUES, CONFIG_JSON=json.dumps({"smoke": True})))
            bad = Path(d) / "bad.json.tmpl"
            j = json.loads((HERE / "jobs/sft-smoke.json.tmpl").read_text())
            j["InputDataConfig"].append(dict(j["InputDataConfig"][0], ChannelName="eval"))
            bad.write_text(json.dumps(j))
            with self.assertRaises(SystemExit):
                render_job.render(bad, "smoke", d, VALUES)


if __name__ == "__main__":
    unittest.main()
