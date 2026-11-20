"""Robustness-set helpers: clip cutting, mixing and the warning-only language policy."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import av  # noqa: F401
    import numpy as np
    HAVE = True
except ImportError:  # host without the image's libraries
    HAVE = False

if HAVE:
    from flh_speaking import audio, model, robustness

SR = 16000


def win(**kw):
    out = {"text": "Bonjour à tous.", "no_speech_prob": 0.01, "avg_logprob": -0.3, "p_fr": 0.95, "top_language": "fr",
           "p_top_language": 0.95, "compression_ratio": 1.2, "hit_token_limit": False}
    out.update(kw)
    return out


@unittest.skipUnless(HAVE, "needs numpy and av")
class Robustness(unittest.TestCase):
    def test_cut_ends_in_the_pause_nearest_the_target(self):
        t = np.arange(int(1.9 * SR)) / SR
        speech = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        x = np.concatenate([speech, np.zeros(int(0.2 * SR), np.float32), speech])  # pause at 1.9-2.1 s
        y = robustness.cut(x, 2.0)
        self.assertGreaterEqual(len(y), int(1.9 * SR))
        self.assertLessEqual(len(y), int(2.1 * SR))
        self.assertEqual(len(robustness.cut(x[: SR // 2], 2.0)), SR // 2)  # shorter than asked: unchanged
        lead = np.concatenate([np.zeros(SR, np.float32), x])  # one second of silence first
        y = robustness.cut(lead, 2.0)
        self.assertGreaterEqual(len(y), int(1.9 * SR))
        self.assertLessEqual(len(y), int(2.2 * SR))
        self.assertGreater(float(np.abs(y[int(0.2 * SR):]).max()), 0.1)  # starts at the speech, not the silence

    def test_mix_reaches_the_requested_snr_and_level(self):
        rng = np.random.default_rng(0)
        s = (0.1 * rng.standard_normal(SR * 2)).astype(np.float32)
        n = rng.standard_normal(SR).astype(np.float32)
        y = robustness.mix(s, n, 10.0)
        self.assertAlmostEqual(robustness.rms_db(s) - robustness.rms_db(y - s), 10.0, delta=0.05)
        self.assertAlmostEqual(robustness.rms_db(robustness.scale_to(s, -45.0)), -45.0, delta=0.01)

    def test_warning_only_transcribes_what_the_current_rule_refuses(self):
        q = {"sound_seconds": 2.0, "seconds": 2.0}
        english = win(text="Hello everyone.", p_fr=0.05, top_language="en", p_top_language=0.9)
        self.assertEqual(model.decide([dict(english)], q).status, "not_french")
        r = robustness.decide_warning_only([dict(english)], q)
        self.assertEqual((r.status, r.text), ("transcribed", "Hello everyone."))
        self.assertIn("possibly_not_french", r.warnings)
        self.assertEqual(model.NOT_FRENCH_FR_MAX, 0.2)  # restored
        self.assertEqual(robustness.decide_warning_only([], {"sound_seconds": 0.0, "seconds": 1.0}).status, "no_speech")
        self.assertEqual(robustness.decide_warning_only([dict(win())], q).warnings, [])



@unittest.skipUnless(HAVE, "needs numpy and av")
class Punctuated(unittest.TestCase):
    def test_selection_excludes_held_out_sentences_and_texts(self):
        import hashlib
        import io
        import json
        import os
        import tarfile
        import tempfile
        from unittest import mock

        from flh_speaking import fetch, pins, prepare

        tone = lambda s: audio.to_wav_pcm16((0.2 * np.sin(2 * np.pi * 200 * np.arange(int(s * SR)) / SR)).astype(np.float32))  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp:
            src, base, out = (os.path.join(tmp, d) for d in ("src", "base", "out"))
            root = os.path.join(src, pins.FLEURS_FR_TRAIN["repo"], pins.FLEURS_FR_TRAIN["revision"], "data", "fr_fr")
            os.makedirs(os.path.join(root, "audio"))
            rows = [("100", "1.wav", "Bonjour, Paris !", 1.0), ("101", "2.wav", "Une phrase déjà tenue.", 1.0),
                    ("102", "3.wav", "Beaucoup trop longue.", 25.0), ("103", "4.wav", "Il pleut ; on reste.", 1.0),
                    ("104", "5.wav", "Et demain ?", 1.0), ("103", "6.wav", "Il pleut ; on reste.", 1.0), ("104", "7.wav", "Et demain ?", 1.0)]
            with open(os.path.join(root, "train.tsv"), "w", encoding="utf-8") as fh:
                for sid, f, text, s in rows:
                    fh.write(f"{sid}\t{f}\t{text}\t{text.lower()}\tx\t{int(s * SR)}\tFEMALE\n")
            with tarfile.open(os.path.join(root, "audio", "train.tar.gz"), "w:gz") as tf:
                for _, f, _, s in rows:
                    b = tone(min(s, 2.0))
                    ti = tarfile.TarInfo(f"train/{f}")
                    ti.size = len(b)
                    tf.addfile(ti, io.BytesIO(b))
            files = {p: (os.path.getsize(os.path.join(root, p.split("fr_fr/", 1)[1])), ("sha256", fetch.file_digest(os.path.join(root, p.split("fr_fr/", 1)[1]), "sha256")))
                     for p in pins.FLEURS_FR_TRAIN["files"]}
            os.makedirs(base)
            held = [{"id": "d1", "split": "dev", "corpus": "mls_fr", "group": "book:1", "text": "une phrase déjà tenue", "file": "audio/dev/d1.wav"},
                    {"id": "o1", "split": "ood", "corpus": "fleurs_fr_fr", "group": "sentence:100", "text": "Bonjour, Paris !", "file": "audio/ood/o1.wav"}]
            with open(os.path.join(base, "manifest.jsonl"), "w", encoding="utf-8") as fh:
                fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in held))
            with mock.patch.dict(pins.FLEURS_FR_TRAIN, {"files": files}):
                man = prepare.prepare_punctuated(src, base, out, n=2, n_dev=1, log=lambda *_: None)
                with self.assertRaises(ValueError):  # the train sentence has only two readers
                    prepare.prepare_punctuated(src, base, os.path.join(tmp, "out2"), n=3, n_dev=1, log=lambda *_: None)
            self.assertEqual(man["excluded"], {"dev_sentence": 1, "held_out_text": 1, "too_long": 1})
            self.assertEqual((man["splits"]["train"]["sentences"], man["splits"]["train"]["with_second_reader"]), (1, 1))
            with open(os.path.join(out, "manifest.jsonl"), encoding="utf-8") as fh:
                got = [json.loads(line) for line in fh]
            # two eligible sentences: one for dev, the other's two readers for train; raw text kept
            self.assertEqual({r["text"] for r in got}, {"Il pleut ; on reste.", "Et demain ?"})
            self.assertEqual(sorted(r["split"] for r in got), ["dev", "train", "train"])
            self.assertEqual(len({r["text"] for r in got if r["split"] == "train"}), 1)
            self.assertEqual(man["splits"]["train"]["with_punctuation"], 1.0)
            self.assertEqual(man["splits"]["dev"]["sentences_shared_with_train"], 0)
            for r in got:
                with open(os.path.join(out, r["file"]), "rb") as fh:
                    self.assertEqual(hashlib.sha256(fh.read()[44:]).hexdigest(), r["pcm_sha256"])


if __name__ == "__main__":
    unittest.main()
