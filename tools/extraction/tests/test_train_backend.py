"""Backend tests for flh_extraction.train on a tiny local fixture model.
Skipped when torch or transformers are not installed.

  TINY_SFT=path/to/sft-sample.jsonl python3 -m unittest discover -s tests -t tests
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import torch
    import transformers  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False


@unittest.skipUnless(HAVE and os.environ.get("TINY_SFT"), "needs torch, transformers and TINY_SFT")
class TrainBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from build_tiny_model import build
        from transformers import AutoModelForCausalLM, AutoTokenizer
        cls.tmp = tempfile.TemporaryDirectory()
        cls.sft = os.environ["TINY_SFT"]
        cls.model_dir = build(cls.sft, Path(cls.tmp.name) / "tiny")
        cls.tok = AutoTokenizer.from_pretrained(cls.model_dir, local_files_only=True)
        cls.model = AutoModelForCausalLM.from_pretrained(cls.model_dir, local_files_only=True)
        cls.recs = [json.loads(line) for line in Path(cls.sft).read_text(encoding="utf-8").splitlines()]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_only_the_answer_is_labelled(self):
        from flh_extraction.train import IGNORE, encode, render_chat
        r = self.recs[0]
        e = encode(self.tok, r, 4096)
        prompt_ids = self.tok(render_chat(self.tok, r["messages"][:2], add_generation_prompt=True), add_special_tokens=False)["input_ids"]
        self.assertTrue(all(l == IGNORE for l in e["labels"][:len(prompt_ids)]))
        answer = [t for t, l in zip(e["input_ids"], e["labels"]) if l != IGNORE]
        self.assertEqual(answer, e["input_ids"][len(prompt_ids):])
        decoded = self.tok.decode(answer)
        self.assertIn(r["messages"][2]["content"], decoded)
        self.assertNotIn(r["messages"][1]["content"][:40], decoded)

    def test_loss_counts_answer_tokens_only(self):
        from flh_extraction.train import IGNORE, collate, encode
        e = encode(self.tok, self.recs[1], 4096)
        ids, labels, mask = collate([e], self.tok.pad_token_id)
        with torch.no_grad():
            loss = self.model(input_ids=ids, attention_mask=mask, labels=labels).loss
            logits = self.model(input_ids=ids, attention_mask=mask).logits
        shift_logits, shift_labels = logits[0, :-1], labels[0, 1:]
        keep = shift_labels != IGNORE
        manual = torch.nn.functional.cross_entropy(shift_logits[keep], shift_labels[keep])
        self.assertAlmostEqual(float(loss), float(manual), places=4)
        # Changing prompt tokens' labels to garbage would change the loss; the mask must hide them.
        self.assertGreater(int(keep.sum()), 0)
        self.assertLess(int(keep.sum()), ids.shape[1] - 1)

    def test_training_runs_saves_and_reloads(self):
        from flh_extraction.train import load_config, run
        from transformers import AutoModelForCausalLM
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "cfg.json"
            cfg_path.write_text(json.dumps({"model_name_or_path": str(self.model_dir), "max_length": 4096, "learning_rate": 0.01,
                                            "max_steps": 12, "batch_size": 2, "grad_accum": 1, "eval_every": 6, "smoke": True}))
            train = Path(d) / "train.jsonl"
            train.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.recs[:4]))
            m = run(load_config(cfg_path), train, None, Path(d) / "run")
            losses = [json.loads(l)["train_loss"] for l in (Path(d) / "run" / "losses.jsonl").read_text().splitlines()]
            self.assertLess(losses[-1], losses[0])
            self.assertFalse(m["suitable_for_production"])
            self.assertTrue(m["smoke"])
            reloaded = AutoModelForCausalLM.from_pretrained(Path(d) / "run" / "model", local_files_only=True)
            ids = torch.tensor([[1, 2, 3, 4]])
            from transformers import AutoModelForCausalLM as A
            again = A.from_pretrained(Path(d) / "run" / "model", local_files_only=True)
            with torch.no_grad():
                self.assertTrue(torch.allclose(reloaded(input_ids=ids).logits, again(input_ids=ids).logits))
            for name, sha in m["files"].items():
                import hashlib
                self.assertEqual(hashlib.sha256((Path(d) / "run" / name).read_bytes()).hexdigest(), sha)

    def test_evaluation_records_are_refused(self):
        from flh_extraction.train import load_config, run
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "cfg.json"
            cfg_path.write_text(json.dumps({"model_name_or_path": str(self.model_dir), "max_steps": 1}))
            bad = Path(d) / "bad.jsonl"
            bad.write_text(json.dumps(dict(self.recs[0], split="eval"), ensure_ascii=False) + "\n")
            with self.assertRaises(ValueError):
                run(load_config(cfg_path), bad, None, Path(d) / "run")

    def test_lora_path(self):
        try:
            import peft  # noqa: F401
        except ImportError:
            self.skipTest("peft not installed")
        from flh_extraction.train import load_config, run
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "cfg.json"
            cfg_path.write_text(json.dumps({"model_name_or_path": str(self.model_dir), "max_length": 4096, "max_steps": 2,
                                            "batch_size": 1, "grad_accum": 1,
                                            "lora": {"r": 4, "lora_alpha": 8, "lora_dropout": 0.0, "target_modules": ["q_proj", "v_proj"]}}))
            train = Path(d) / "train.jsonl"
            train.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.recs[:2]))
            m = run(load_config(cfg_path), train, None, Path(d) / "run")
            self.assertEqual(m["steps"], 2)
            self.assertTrue((Path(d) / "run" / "model" / "adapter_config.json").exists())


if __name__ == "__main__":
    unittest.main()
