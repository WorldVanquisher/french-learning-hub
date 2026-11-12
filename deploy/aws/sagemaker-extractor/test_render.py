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
            for tmpl, run in (("sft-smoke", "smoke"), ("sft-experiment", "experiment"), ("predict-eval", "predict"),
                              ("predict-base", "predict")):
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

    def test_base_model_prediction_has_no_adapter(self):
        with tempfile.TemporaryDirectory() as d:
            job = json.loads(render_job.render(HERE / "jobs" / "predict-base.json.tmpl", "predict", d, VALUES).read_text())
            self.assertEqual({c["ChannelName"] for c in job["InputDataConfig"]}, {"prompts", "model"})
            self.assertEqual(job["AlgorithmSpecification"]["ContainerArguments"], ["predict"])


class Readiness(unittest.TestCase):
    def test_package_renders_every_job_from_the_data_hashes(self):
        import build_readiness
        rec = {"id": "r", "split": "train", "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                                                         {"role": "assistant", "content": '{"units":[]}'}]}
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "data"
            data.mkdir()
            for name in ("sft-train.jsonl", "sft-dev.jsonl"):
                (data / name).write_text(json.dumps(rec) + "\n")
            for name in ("eval-prompts-inputs-only.jsonl", "probe-rb-prompts.jsonl", "sub50-prompts.jsonl", "sub50-probe-prompts.jsonl"):
                (data / name).write_text(json.dumps({"id": name, "messages": rec["messages"][:2]}) + "\n")
            m, rendered = build_readiness.build(data, Path(d) / "out")
            self.assertEqual(set(rendered), {"sft-smoke", "sft-experiment", "predict-base", "predict-eval"})
            self.assertEqual(m["files"]["predict-full/eval-prompts.jsonl"]["records"], 2)
            t = m["files"]["sft-train.jsonl"]["sha256"]
            self.assertTrue(m["files"]["sft-dev.jsonl"]["s3_key"].startswith(f"extractor/datasets/{t}/dev/"))
            smoke = json.loads((Path(d) / "out" / "rendered" / "sft-smoke.json").read_text())
            exp = json.loads((Path(d) / "out" / "rendered" / "sft-experiment.json").read_text())
            self.assertTrue(json.loads(smoke["HyperParameters"]["config_json"])["smoke"])
            self.assertFalse(json.loads(exp["HyperParameters"]["config_json"])["smoke"])
            self.assertEqual(exp["HyperParameters"]["train_sha256"], t)
            pred = json.loads((Path(d) / "out" / "rendered" / "predict-eval.json").read_text())
            full = Path(d) / "out" / "prompts" / "full" / "eval-prompts.jsonl"
            self.assertEqual(pred["HyperParameters"]["prompts_sha256"], build_readiness.sha(full))


if __name__ == "__main__":
    unittest.main()
