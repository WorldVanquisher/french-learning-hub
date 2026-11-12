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
    def package_data(self, d, prompt_rows=None):
        rec = {"id": "r", "split": "train", "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                                                         {"role": "assistant", "content": '{"units":[]}'}]}
        data = Path(d) / "data"
        data.mkdir()
        for name in ("sft-train.jsonl", "sft-dev.jsonl"):
            (data / name).write_text(json.dumps(rec) + "\n")
        prompt_rows = prompt_rows or [{"id": i, "messages": rec["messages"][:2]}
                                      for i in ("ext-evl-0001", "ext-evl-0002", "ext-evl-0001#rb", "ext-evl-0002#rb", "ext-chl-0001")]
        (data / "comparison-prompts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in prompt_rows))
        return data

    def test_package_renders_every_job_from_the_data_hashes(self):
        import build_readiness
        with tempfile.TemporaryDirectory() as d:
            m, rendered = build_readiness.build(self.package_data(d), Path(d) / "out")
            self.assertEqual(set(rendered), {"sft-smoke", "sft-experiment", "predict-base-a", "predict-base-b",
                                             "predict-eval-a", "predict-eval-b"})
            self.assertEqual(m["files"]["predict-a/eval-prompts.jsonl"]["records"], 3)
            self.assertEqual(m["files"]["predict-b/eval-prompts.jsonl"]["records"], 2)
            t = m["files"]["sft-train.jsonl"]["sha256"]
            self.assertTrue(m["files"]["sft-dev.jsonl"]["s3_key"].startswith(f"extractor/datasets/{t}/dev/"))
            out = Path(d) / "out"
            smoke = json.loads((out / "rendered" / "sft-smoke.json").read_text())
            exp = json.loads((out / "rendered" / "sft-experiment.json").read_text())
            self.assertTrue(json.loads(smoke["HyperParameters"]["config_json"])["smoke"])
            self.assertFalse(json.loads(exp["HyperParameters"]["config_json"])["smoke"])
            self.assertEqual(exp["HyperParameters"]["train_sha256"], t)
            pa = json.loads((out / "rendered" / "predict-eval-a.json").read_text())
            self.assertEqual(pa["HyperParameters"]["prompts_sha256"], build_readiness.sha(out / "prompts" / "a" / "eval-prompts.jsonl"))
            self.assertEqual(pa["HyperParameters"]["dtype"], "bfloat16")
            chk = json.loads((out / "readiness-checks.json").read_text())
            self.assertTrue(chk["pass"])
            names = list(chk["output_naming"]["jobs"].values())
            self.assertEqual(len(set(names)), 6)
            self.assertIn("predict-base-a", chk["output_naming"]["jobs"]["predict-base-a"])

    def test_package_refuses_prompts_that_carry_references(self):
        import build_readiness
        bad = [{"id": "ext-evl-0001", "messages": [{"role": "system", "content": "s"},
                                                   {"role": "user", "content": json.dumps({"original_input": "x", "expected": []})}]}]
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit) as e:
                build_readiness.build(self.package_data(d, bad), Path(d) / "out")
            self.assertIn("reference fields", str(e.exception))

if __name__ == "__main__":
    unittest.main()
