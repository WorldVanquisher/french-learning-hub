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
