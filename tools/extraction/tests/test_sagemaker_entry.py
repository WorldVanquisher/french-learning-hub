"""The SageMaker entry point in its /opt/ml layout (FLH_SM_ROOT), offline.

Refusals need only the standard library. The full train → predict dry run
needs torch, transformers and TINY_SFT (a tiny random fixture model; a
pipeline check, never a model).

  TINY_SFT=path/to/sft-sample.jsonl python3 -B -m unittest discover -s tests -t tests
"""

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flh_extraction import sagemaker_entry  # noqa: E402

try:
    import torch  # noqa: F401
    import transformers  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False

REC = {"id": "r1", "split": "train", "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                                                  {"role": "assistant", "content": '{"units":[]}'}]}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def layout(root, hp, train=None, dev=None, prompts=None, extra_channels=()):
    data = Path(root) / "input" / "data"
    (Path(root) / "input" / "config").mkdir(parents=True)
    for name, rows, fname in (("train", train, "sft-train.jsonl"), ("dev", dev, "sft-dev.jsonl"), ("prompts", prompts, "eval-prompts.jsonl")):
        if rows is not None:
            (data / name).mkdir(parents=True)
            (data / name / fname).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    for c in extra_channels:
        (data / c).mkdir(parents=True)
    (Path(root) / "input" / "config" / "hyperparameters.json").write_text(json.dumps(hp))
    return data


class Refusals(unittest.TestCase):
    def run_entry(self, root, mode):
        with mock.patch.dict(os.environ, {"FLH_SM_ROOT": str(root)}), contextlib.redirect_stderr(io.StringIO()):
            return sagemaker_entry.main(["entry", mode])

    def test_eval_channel_wrong_hashes_and_unknown_mode(self):
        with tempfile.TemporaryDirectory() as d:
            data = layout(d, {"train_sha256": "x"}, train=[REC], extra_channels=["eval"])
            self.assertEqual(self.run_entry(d, "train"), 1)
            self.assertIn("eval channel is refused", (Path(d) / "output" / "failure").read_text())
        with tempfile.TemporaryDirectory() as d:
            layout(d, {"train_sha256": "0" * 64}, train=[REC])
            self.assertEqual(self.run_entry(d, "train"), 1)
            self.assertIn("train_sha256", (Path(d) / "output" / "failure").read_text())
        with tempfile.TemporaryDirectory() as d:
            data = layout(d, {}, train=[REC], dev=[dict(REC, split="dev")])
            hp = {"train_sha256": sha(data / "train" / "sft-train.jsonl"), "dev_sha256": "0" * 64}
            (Path(d) / "input" / "config" / "hyperparameters.json").write_text(json.dumps(hp))
            self.assertEqual(self.run_entry(d, "train"), 1)
            self.assertIn("dev_sha256", (Path(d) / "output" / "failure").read_text())
        with tempfile.TemporaryDirectory() as d:
            layout(d, {"prompts_sha256": "0" * 64}, prompts=[{"id": "p", "messages": REC["messages"][:2]}])
            self.assertEqual(self.run_entry(d, "predict"), 1)
            self.assertIn("prompts_sha256", (Path(d) / "output" / "failure").read_text())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(sagemaker_entry.main(["entry", "evaluate"]), 2)

    def test_a_stale_stack_is_refused_and_recorded(self):
        from flh_extraction import packaging
        with tempfile.TemporaryDirectory() as d:
            req = Path(d) / "requirements-train.txt"
            req.write_text("transformers==0.0.0-never\n")
            data = layout(Path(d) / "sm", {"prompts_sha256": ""}, prompts=[{"id": "p", "messages": REC["messages"][:2]}])
            hp = {"prompts_sha256": sha(data / "prompts" / "eval-prompts.jsonl")}
            (Path(d) / "sm" / "input" / "config" / "hyperparameters.json").write_text(json.dumps(hp))
            with mock.patch.object(packaging, "REQUIREMENTS", req):
                self.assertEqual(self.run_entry(Path(d) / "sm", "predict"), 1)
            self.assertIn("STALE_OR_INCOMPLETE", (Path(d) / "sm" / "output" / "failure").read_text())
            rep = json.loads((Path(d) / "sm" / "model" / "stack-check.json").read_text())
            self.assertFalse(rep["stack_matches_requirements"])
            self.assertEqual(rep["mismatches"], ["transformers"])


@unittest.skipUnless(HAVE and os.environ.get("TINY_SFT"), "needs torch, transformers and TINY_SFT")
class DryRun(unittest.TestCase):
    def test_train_then_predict_in_the_sagemaker_layout(self):
        from build_tiny_model import build
        recs = [json.loads(line) for line in Path(os.environ["TINY_SFT"]).read_text(encoding="utf-8").splitlines() if line.strip()]
        with tempfile.TemporaryDirectory() as d:
            tiny = build(os.environ["TINY_SFT"], Path(d) / "tiny")
            root = Path(d) / "train-job"
            data = layout(root, {}, train=[dict(r, split="train") for r in recs[:6]], dev=[dict(r, split="dev") for r in recs[6:8]])
            cfg = {"model_name_or_path": str(tiny), "max_length": 4096, "max_steps": 2, "batch_size": 1, "grad_accum": 1,
                   "eval_every": 1, "smoke": True, "lora": {"r": 4, "lora_alpha": 8, "lora_dropout": 0.0, "target_modules": ["q_proj", "v_proj"]}}
            hp = {"config_json": json.dumps(cfg), "train_sha256": sha(data / "train" / "sft-train.jsonl"),
                  "dev_sha256": sha(data / "dev" / "sft-dev.jsonl")}
            (root / "input" / "config" / "hyperparameters.json").write_text(json.dumps(hp))
            with mock.patch.dict(os.environ, {"FLH_SM_ROOT": str(root), "FLH_ALLOW_STACK_MISMATCH": "1"}):
                self.assertEqual(sagemaker_entry.main(["entry", "train"]), 0)
            m = json.loads((root / "model" / "run_manifest.json").read_text())
            self.assertEqual((m["train_sha256"], m["steps"], m["suitable_for_production"]), (hp["train_sha256"], 2, False))
            self.assertTrue((root / "model" / "model" / "adapter_config.json").exists())
            proot = Path(d) / "predict-job"
            pdata = layout(proot, {}, prompts=[{"id": r["id"], "messages": r["messages"][:2]} for r in recs[:3]])
            os.symlink(tiny, pdata / "model")
            os.symlink(root / "model" / "model", pdata / "adapter")
            hp = {"prompts_sha256": sha(pdata / "prompts" / "eval-prompts.jsonl"), "max_new_tokens": "4", "template_kwargs": "{}",
                  "model_profile": "auto"}
            (proot / "input" / "config" / "hyperparameters.json").write_text(json.dumps(hp))
            with mock.patch.dict(os.environ, {"FLH_SM_ROOT": str(proot), "FLH_ALLOW_STACK_MISMATCH": "1"}):
                self.assertEqual(sagemaker_entry.main(["entry", "predict"]), 0)
            rows = [json.loads(line) for line in (proot / "model" / "predictions.jsonl").read_text().splitlines()]
            self.assertEqual([r["id"] for r in rows], [r["id"] for r in recs[:3]])
            self.assertTrue(all(r["stopped"] in ("eos", "max_new_tokens") for r in rows))


if __name__ == "__main__":
    unittest.main()
