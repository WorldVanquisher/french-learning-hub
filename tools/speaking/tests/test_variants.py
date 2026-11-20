"""Quality-slice variants (flh_speaking.variants): standard library only."""

from __future__ import annotations

import hashlib
import math
import sys
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

from flh_speaking import lab, variants  # noqa: E402

REF = "L'élève a lu le texte à voix haute, puis il s'est assis."


class Variants(unittest.TestCase):
    def setUp(self):
        self.src = lab.synthetic_audio()
        self.rate, self.samples = variants.read_pcm16(self.src)

    def test_reproducible_ids_tags_and_hashes_and_an_unchanged_source(self):
        m1, f1 = variants.make("s1", self.src, REF)
        m2, _ = variants.make("s1", self.src, REF)
        self.assertEqual(m1, m2)
        self.assertEqual(hashlib.sha256(self.src).hexdigest(), m1["source"]["sha256"])
        self.assertEqual(f1["s1"], self.src)
        made = [i for i in m1["items"] if i["status"] == "made"]
        self.assertEqual(len({i["sha256"] for i in made}), len(made))  # every variant differs
        self.assertTrue(all(i["group_id"] == "s1" for i in m1["items"]))
        self.assertEqual({i["tags"]["phrase_length"] for i in m1["items"]}, {"long"})

    def test_a_gain_that_would_clip_is_refused_not_applied(self):
        m, files = variants.make("s1", self.src, REF, plan=(("volume", 12.0), ("volume", -6.0)))
        refused = [i for i in m["items"] if i["status"] == "refused"]
        self.assertEqual([(i["id"], i["reason"]) for i in refused], [("s1~volume+12dB", "would_clip")])
        self.assertNotIn("s1~volume+12dB", files)
        _, quiet = variants.read_pcm16(files["s1~volume-6dB"])
        self.assertAlmostEqual(variants.rms(quiet) / variants.rms(self.samples), 10 ** (-6 / 20), places=3)

    def test_boundary_silence_noise_and_speed(self):
        out = variants.pad_silence(self.samples, self.rate, 500, 250)
        self.assertEqual(len(out), len(self.samples) + 8000 + 4000)
        self.assertEqual(out[8000:8000 + len(self.samples)], self.samples)
        a, b = variants.white_noise(self.samples, 20.0, 7), variants.white_noise(self.samples, 20.0, 7)
        self.assertEqual(a, b)  # fixed seed
        self.assertNotEqual(a, variants.white_noise(self.samples, 20.0, 8))
        noise = [x - y for x, y in zip(a, self.samples)]
        self.assertAlmostEqual(20 * math.log10(variants.rms(self.samples) / variants.rms(noise)), 20.0, delta=0.2)
        self.assertEqual(len(variants.speed(self.samples, 1.25)), round(len(self.samples) / 1.25))

    def test_counts_and_speakers(self):
        m, _ = variants.make("s1", self.src, REF)
        self.assertEqual(m["counts"], {"samples": 8, "originals": 1, "variants": 7, "refused": 1, "groups": 1, "speakers": "no speaker metadata"})
        m, _ = variants.make("s1", self.src, REF, plan=(("volume", -6.0),), speaker="spk-synthetic")
        self.assertEqual((m["counts"]["speakers"], m["counts"]["groups"]), (1, 1))

    def test_phrase_length_tags(self):
        self.assertEqual([variants.phrase_length(t) for t in ("Oui.", "Il fait beau ce matin.", REF)], ["short", "medium", "long"])
        with self.assertRaises(ValueError):
            variants.read_pcm16(variants.write_pcm16(16000, [0]).replace(b"\x01\x00\x01\x00", b"\x01\x00\x02\x00", 1))  # 2 channels


if __name__ == "__main__":
    unittest.main()
