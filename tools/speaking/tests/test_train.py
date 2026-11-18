"""Training mechanics with a tiny random-weight Whisper (real architecture, real
pinned tokenizer, synthetic audio). Needs torch and transformers (the image) and
the pinned whisper-tiny tokenizer files: set FLH_SPEAKING_TOKENIZER_DIR to the
fetched whisper-tiny directory, otherwise the tests are skipped.

  docker run --rm --network none -e FLH_SPEAKING_TOKENIZER_DIR=/tok \
      -v <sources>/openai/whisper-tiny/<rev>:/tok:ro -v $PWD/tools/speaking:/src:ro -w /src \
      --entrypoint python3 flh-speaking:cpu-dev -B -m unittest tests.test_train
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TOK = os.environ.get("FLH_SPEAKING_TOKENIZER_DIR", "")
try:
    import numpy as np
    import torch  # noqa: F401
    import transformers  # noqa: F401
    HAVE = bool(TOK) and os.path.isfile(os.path.join(TOK, "tokenizer.json"))
except ImportError:
    HAVE = False

if HAVE:
    from flh_speaking import audio, train

SR = 16000
TEXTS = ["bonjour à tous", "je voudrais un café", "il fait beau aujourd'hui", "merci beaucoup",
         "nous partons demain", "elle habite à lyon", "le train arrive", "à bientôt"]


def make_base(d: str) -> str:
    from transformers import WhisperConfig, WhisperForConditionalGeneration
    base = os.path.join(d, "base")
    os.makedirs(base)
    cfg = WhisperConfig.from_pretrained(TOK)
    for k, v in dict(d_model=16, encoder_layers=1, decoder_layers=1, encoder_attention_heads=2, decoder_attention_heads=2,
                     encoder_ffn_dim=32, decoder_ffn_dim=32).items():
        setattr(cfg, k, v)
    torch.manual_seed(0)
    WhisperForConditionalGeneration(cfg).save_pretrained(base, safe_serialization=True)
    for f in train.MODEL_FILES_COPIED:
        if f != "config.json" and os.path.exists(os.path.join(TOK, f)):
            shutil.copyfile(os.path.join(TOK, f), os.path.join(base, f))
    return base


def make_data(d: str) -> str:
    data = os.path.join(d, "data")
    os.makedirs(os.path.join(data, "audio", "train"))
    rows = []
    rng = np.random.default_rng(1)
    for i, text in enumerate(TEXTS):
        x = (0.2 * np.sin(2 * np.pi * (200 + 40 * i) * np.arange(SR) / SR) + 0.01 * rng.standard_normal(SR)).astype(np.float32)
        wav = audio.to_wav_pcm16(x)
        rel = f"audio/train/u{i}.wav"
        Path(data, rel).write_bytes(wav)
        rows.append({"id": f"u{i}", "split": "train" if i < 6 else "dev", "speaker": f"s{i % 3}", "group": "g", "gender": "F",
                     "text": text, "file": rel, "pcm_sha256": hashlib.sha256(wav[44:]).hexdigest(), "seconds": 1.0})
    body = "".join(json.dumps(r) + "\n" for r in rows)
    Path(data, "manifest.jsonl").write_text(body)
    Path(data, "dataset_manifest.json").write_text(json.dumps({"manifest_jsonl_sha256": hashlib.sha256(body.encode()).hexdigest(),
                                                               "tiny_fixture": {"train": [r["id"] for r in rows[:6]], "eval": ["u6", "u7"]}}))
    return data


def config(d: str, **kw) -> str:
    c = {"schema": "flh_speaking_train_config_v1", "base_model": "whisper-tiny", "seed": 3, "train_ids": "tiny:train", "dev_ids": "tiny:eval",
         "max_steps": 4, "batch_size": 2, "grad_accum": 2, "lr": 1e-3, "warmup_steps": 1, "weight_decay": 0.0, "max_grad_norm": 1.0,
         "freeze": "none", "gradient_checkpointing": False, "eval_every": 2, "save_every": 2, "keep_checkpoints": 0, "threads": 1}
    c.update(kw)
    p = os.path.join(d, f"config-{len(os.listdir(d))}.json")
    Path(p).write_text(json.dumps(c))
    return p


@unittest.skipUnless(HAVE, "needs torch, transformers and FLH_SPEAKING_TOKENIZER_DIR")
class Training(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.base = make_base(cls.tmp)
        cls.data = make_data(cls.tmp)
        cls.cfg = config(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_train(self, out, cfg=None, stop_after=0):
        return train.train(cfg or self.cfg, self.data, self.base, out, stop_after=stop_after, log=lambda m: None)

    def test_loss_check_checkpoints_and_manifest(self):
        out = os.path.join(self.tmp, "a")
        res = self.run_train(out)
        self.assertEqual((res["status"], res["step"]), ("completed", 4))
        st = torch.load(os.path.join(res["checkpoint"], "trainer_state.pt"), weights_only=False)
        check = st["history"][0]["check"]
        self.assertAlmostEqual(check["library_loss"], check["manual_loss"], places=4)
        self.assertGreater(check["tokens"], 0)
        losses = [h["loss"] for h in st["history"][1:]]
        self.assertEqual(len(losses), 4)
        self.assertTrue(all(np.isfinite(losses)))
        self.assertEqual(sorted(os.listdir(os.path.join(out, "checkpoints"))), ["LATEST", "step-000002", "step-000004"])
        self.assertEqual(train.verify_checkpoint(res["checkpoint"]), [])
        for f in ("tokenizer.json", "vocab.json", "preprocessor_config.json"):  # byte copies of the base
            self.assertEqual(train.sha256_file(os.path.join(res["checkpoint"], f)), train.sha256_file(os.path.join(self.base, f)))
        man = json.loads(Path(res["checkpoint"], "run_manifest.json").read_text())
        self.assertFalse(man["suitable_for_production"])
        self.assertEqual(man["params"]["total"], man["params"]["trainable"])
        Path(res["checkpoint"], "model.safetensors").write_bytes(b"corrupt")
        self.assertEqual(train.verify_checkpoint(res["checkpoint"]), ["model.safetensors: sha256 mismatch"])

    def test_interrupted_and_resumed_run_equals_an_uninterrupted_run(self):
        ref = self.run_train(os.path.join(self.tmp, "ref"))
        out = os.path.join(self.tmp, "resumed")
        first = self.run_train(out, stop_after=1)
        self.assertEqual((first["status"], first["step"]), ("interrupted", 1))
        second = self.run_train(out)
        self.assertEqual((second["status"], second["step"]), ("completed", 4))
        self.assertEqual(second["model_sha256"], ref["model_sha256"])

    def test_resume_refuses_a_changed_config(self):
        out = os.path.join(self.tmp, "changed")
        self.run_train(out, stop_after=1)
        with self.assertRaises(ValueError):
            self.run_train(out, cfg=config(self.tmp, lr=5e-4))

    def test_freezing_counts_trainable_parameters(self):
        res = self.run_train(os.path.join(self.tmp, "frozen"), cfg=config(self.tmp, freeze="decoder", max_steps=1, save_every=1))
        man = json.loads(Path(res["checkpoint"], "run_manifest.json").read_text())
        self.assertLess(man["params"]["trainable"], man["params"]["total"])
        self.assertEqual(res["trainable_params"], man["params"]["trainable"])

    def test_bad_configs_and_test_ids_are_refused(self):
        with self.assertRaises(ValueError):
            train.load_config(config(self.tmp, freeze="everything"))
        with self.assertRaises(ValueError):
            train.load_config(config(self.tmp, unexpected=1))
        with self.assertRaises(ValueError):
            self.run_train(os.path.join(self.tmp, "bad"), cfg=config(self.tmp, train_ids=["u6"]))


if __name__ == "__main__":
    unittest.main()
