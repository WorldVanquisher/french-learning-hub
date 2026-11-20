"""The SageMaker job renderer (no AWS call): run names, bounds, both configs."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("speaking_aws_render", PKG / "aws" / "render.py")
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)

NOW = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)


def values(**kw):
    v = json.loads((PKG / "aws" / "values.example.json").read_text())
    v.update(kw)
    return v


def config(name):
    return json.loads((PKG / "configs" / name).read_text())


class Render(unittest.TestCase):
    def job(self, v, cfg):
        with tempfile.TemporaryDirectory() as tmp:
            return json.loads(render.render(v, cfg, tmp, now=NOW).read_text())

    def test_pilot_and_punctuated_runs_render_within_bounds(self):
        pilot = self.job(values(), config("pilot-base-encoder.json"))
        self.assertEqual(pilot["TrainingJobName"], "flh-speaking-pilot-20261118-120000")
        self.assertIn({"Key": "Run", "Value": "pilot"}, pilot["Tags"])
        punct = self.job(values(RUN="punct", DATA_SHA256="a" * 64), config("punct-base-encoder.json"))
        self.assertEqual(punct["TrainingJobName"], "flh-speaking-punct-20261118-120000")
        self.assertIn({"Key": "Run", "Value": "punct"}, punct["Tags"])
        self.assertEqual(json.loads(punct["HyperParameters"]["config_json"]), config("punct-base-encoder.json"))
        self.assertTrue(punct["InputDataConfig"][0]["DataSource"]["S3DataSource"]["S3Uri"].endswith("/speaking/datasets/" + "a" * 64 + "/"))
        self.assertEqual((punct["ResourceConfig"]["InstanceType"], punct["StoppingCondition"]["MaxRuntimeInSeconds"]), ("ml.g5.xlarge", 3600))
        self.assertTrue(punct["EnableNetworkIsolation"])

    def test_refusals(self):
        for v, cfg in ((values(RUN="Punct!"), config("punct-base-encoder.json")),
                       (values(IMAGE_DIGEST="latest"), config("punct-base-encoder.json")),
                       (values(BASE_MODEL="whisper-small"), config("punct-base-encoder.json"))):
            with self.assertRaises(SystemExit):
                self.job(v, cfg)


if __name__ == "__main__":
    unittest.main()


class PilotR4(unittest.TestCase):
    """R4: the bounded owner-run job against its pre-registration, and the teardown order (no AWS call, no credentials)."""

    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(PKG / "aws"))
        import pilot_r4
        cls.p = pilot_r4
        cls.v = json.loads((PKG / "aws" / "values.r4.example.json").read_text())
        cls.now = datetime(2026, 11, 20, tzinfo=timezone.utc)

    def test_render_is_deterministic_and_equals_the_committed_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.p.render_r4(self.v, tmp, self.now)
            committed = PKG.parents[1] / "deploy" / "aws" / "model-runtime" / "speaking-r4" / out.name
            self.assertEqual(out.read_bytes(), committed.read_bytes())
            job = json.loads(out.read_text())
        self.assertEqual((job["ResourceConfig"]["InstanceCount"], job["ResourceConfig"]["InstanceType"]), (1, "ml.g5.xlarge"))
        self.assertEqual(job["StoppingCondition"], {"MaxRuntimeInSeconds": 3600, "MaxWaitTimeInSeconds": 7200})
        self.assertIn(job["TrainingJobName"], job["CheckpointConfig"]["S3Uri"])
        self.assertIsNone(self.p.SECRET.search(json.dumps(job)))

    def test_values_that_disagree_with_the_preregistration_are_refused(self):
        for kw in ({"DATA_SHA256": "a" * 64}, {"BASE_REVISION": "b" * 40}, {"RUN": "pilot"}, {"DELETE_AFTER": "2027-06-01"}):
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
                self.p.render_r4({**self.v, **kw}, tmp, self.now)

    def test_teardown_plan_order(self):
        plan = json.loads((PKG / "aws" / "r4-teardown-plan.json").read_text())
        self.assertEqual(self.p.teardown_check(plan), [])
        s = plan["steps"]
        bad = {"delete before copy": [s[1], s[6], s[2]] + s[3:6] + s[7:], "no evidence copy": s[:2] + s[3:],
               "image not last": s[:6] + [s[9]] + s[6:9] + [s[10]], "bucket-wide delete": s[:6] + [{"action": "delete_s3_prefix", "target": "s3://b/"}] + s[6:],
               "no final verification": s[:-1], "deletes evidence": s[:6] + [{"action": "delete_s3_prefix", "target": "s3://b/speaking/evidence/"}] + s[6:]}
        for name, steps in bad.items():
            self.assertTrue(self.p.teardown_check({"steps": steps}), name)
