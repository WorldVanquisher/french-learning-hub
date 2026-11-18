"""Standard-library tests (no torch, NumPy or PyAV): normalization, WER,
the MLS selection rule and pinned-file verification.

  cd tools/speaking && python3 -B -m unittest discover -s tests -t tests
"""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flh_speaking import fetch, mls, pins, textnorm  # noqa: E402


class Normalization(unittest.TestCase):
    def test_case_punctuation_quotes_and_ligatures(self):
        self.assertEqual(textnorm.normalize_fr("L’Homme, qu'il a vu — est-ce « Noël » ?"), "l' homme qu' il a vu est ce noël")
        self.assertEqual(textnorm.normalize_fr("'bonjour' dit-il"), "bonjour dit il")
        self.assertEqual(textnorm.normalize_fr("Cœur ÉTÉ"), "coeur été")
        self.assertEqual(textnorm.normalize_fr("[Musique] (rires) oui"), "oui")

    def test_accents_elision_and_numbers_are_kept(self):
        self.assertNotEqual(textnorm.words("été"), textnorm.words("ete"))
        self.assertEqual(textnorm.words("l'été"), ["l'", "été"])
        self.assertEqual(textnorm.words("en 1823"), ["en", "1823"])  # digits are not spelled out

    def test_alignment_counts(self):
        self.assertEqual(textnorm.align(list("abc"), list("abc")), (0, 0, 0))
        self.assertEqual(textnorm.align(list("abc"), list("axc")), (1, 0, 0))
        self.assertEqual(textnorm.align(list("abc"), list("ac")), (0, 1, 0))
        self.assertEqual(textnorm.align(list("abc"), list("abxc")), (0, 0, 1))
        self.assertEqual(sum(textnorm.align([], list("ab"))), 2)

    def test_score_and_corpus_rate(self):
        s = textnorm.score("le chat est sur la table", "Le chien est la table.")
        self.assertEqual((s["ref_words"], s["sub"], s["del"], s["ins"]), (6, 1, 1, 0))
        r = textnorm.rate([s, textnorm.score("oui", "oui")])
        self.assertAlmostEqual(r["wer"], 2 / 7, places=5)
        self.assertEqual(textnorm.score("bonjour", "")["del"], 1)  # an abstention scores as deletions


META = """ SPEAKER | GENDER | PARTITION | MINUTES | BOOK ID | TITLE | CHAPTER
1 | F | test | 1 | 10 | t | c
2 | M | test | 1 | 11 | t | c
3 | F | dev | 1 | 12 | t | c
4 | M | dev | 1 | 13 | t | c
5 | F | train | 1 | 10 | t | c
6 | F | train | 1 | 20 | t | c
7 | M | train | 1 | 21 | t | c
"""


def _tr(spk, book, n):
    return {f"{spk}_{book}_{i:06d}": f"phrase {spk} {i}" for i in range(n)}


class Selection(unittest.TestCase):
    def setUp(self):
        self.meta = mls.parse_metainfo(META)
        self.tr = {"test": {**_tr(1, 10, 40), **_tr(2, 11, 40)}, "dev": {**_tr(3, 12, 30), **_tr(4, 13, 30)},
                   "train": {**_tr(5, 10, 70), **_tr(6, 20, 70), **_tr(7, 21, 70)}}

    def test_training_books_never_occur_in_dev_or_test(self):
        old = mls.PLAN
        mls.PLAN = (("test", "test", 1, 30, 30), ("dev", "dev", 1, 25, 25), ("train", "train", 1, 60, 60))
        try:
            sel = mls.select(self.meta, self.tr)
        finally:
            mls.PLAN = old
        self.assertEqual([a["archive"] for a in sel["train"]], ["6_20", "7_21"])  # speaker 5 reads test book 10
        self.assertEqual(len(sel["test"][0]["utterances"]), 30)
        self.assertEqual(sel["test"][0]["utterances"], sorted(sel["test"][0]["utterances"]))

    def test_missing_gender_and_duplicate_lines_are_refused(self):
        with self.assertRaises(ValueError):
            mls.archives({}, {"9_9_000000": "x"})
        with self.assertRaises(ValueError):
            mls.parse_transcripts("1_1_0\ta\n1_1_0\tb\n")

    def test_shipped_plan_is_the_documented_one(self):
        self.assertEqual(mls.SELECTION_RULE, "flh_mls_fr_subset_v1")
        self.assertEqual(mls.PLAN, (("test", "test", 4, 30, 30), ("dev", "dev", 2, 25, 25), ("train", "train", 12, 60, 60)))


class Pins(unittest.TestCase):
    def test_every_pin_has_size_and_a_known_digest_kind(self):
        for src in [*pins.MODELS.values(), pins.MLS, pins.FLEURS]:
            self.assertRegex(src["revision"], r"^[0-9a-f]{40}$")
            for path, (size, (kind, digest)) in src["files"].items():
                self.assertGreater(size, 0, path)
                self.assertIn(kind, ("sha256", "gitblob"))
                self.assertEqual(len(digest), 64 if kind == "sha256" else 40)
        self.assertEqual(sum(1 for p in pins.MLS["files"] if p.endswith(".tar.gz")), 36)

    def test_verify_checks_size_sha256_and_git_blob(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f")
            Path(p).write_bytes(b"hello\n")
            sha = hashlib.sha256(b"hello\n").hexdigest()
            blob = hashlib.sha1(b"blob 6\0hello\n").hexdigest()
            self.assertIsNone(fetch.verify(p, 6, ("sha256", sha)))
            self.assertIsNone(fetch.verify(p, 6, ("gitblob", blob)))
            self.assertIn("size", fetch.verify(p, 7, ("sha256", sha)))
            self.assertIn("sha256", fetch.verify(p, 6, ("sha256", "0" * 64)))
            self.assertEqual(fetch.verify(os.path.join(d, "missing"), 1, ("sha256", sha)), "missing")


if __name__ == "__main__":
    unittest.main()


from flh_speaking import compare, evaluate  # noqa: E402


def _doc(errors_by_cluster, words=10, status="transcribed", style=(1.0, 1.0), rtf=0.1):
    items = []
    for c, errs in errors_by_cluster.items():
        for k, e in enumerate(errs):
            ref = " ".join(f"w{j}" for j in range(words))
            hyp = " ".join(("x" if j < e else f"w{j}") for j in range(words))
            items.append({"id": f"{c}-{k}", "cluster": c, "gender": "F", "seconds": 5.0, "quality": {"snr_db": 30},
                          "ref": ref, "raw": {"text": hyp}, "served": {"status": status, "text": hyp, "warnings": []},
                          "score": {"raw": textnorm.score(ref, hyp), "served": textnorm.score(ref, hyp)}})
    return {"items": items, "summary": {"split": "test", "style": {"outputs": len(items), "with_punctuation": style[0], "with_uppercase": style[1]},
                                        "timing": {"real_time_factor": rtf}}}


def _probes(statuses):
    return {"probes": [{"name": n, "expect": "abstain", "status": s} for n, s in statuses.items()]}


class Acceptance(unittest.TestCase):
    def test_paired_delta_sign_test_and_bootstrap_are_deterministic(self):
        a = _doc({f"s{i}": [3, 3] for i in range(8)})
        b = _doc({f"s{i}": [1, 2] for i in range(8)})
        p = compare.paired(a, b)
        self.assertEqual((p["wer_a"], p["wer_b"], p["delta"]), (0.3, 0.15, -0.15))
        self.assertEqual((p["clusters_better"], p["clusters_worse"], p["cluster_sign_test_p"]), (8, 0, 0.00781))
        self.assertEqual(p["delta_ci95"], compare.paired(a, b)["delta_ci95"])
        self.assertLess(p["delta_ci95"][1], 0)
        with self.assertRaises(ValueError):
            compare.paired(a, _doc({"s0": [1]}))

    def test_rule_promotes_only_when_every_criterion_holds(self):
        base = {"test": _doc({f"s{i}": [3, 3] for i in range(8)}), "ood": _doc({f"g{i}": [3] for i in range(8)}),
                "probes": _probes({"silence": "no_speech", "noise": "no_speech"})}
        good = {"test": _doc({f"s{i}": [1, 2] for i in range(8)}), "ood": _doc({f"g{i}": [3] for i in range(8)}),
                "probes": _probes({"silence": "no_speech", "noise": "no_speech"})}
        ids = [i["id"] for i in base["test"]["items"]]
        r = compare.acceptance(base, good, ids)
        self.assertEqual((r["verdict"], r["failed"], r["production_go"]), ("PROMOTE_CANDIDATE", [], False))
        bad = dict(good, probes=_probes({"silence": "no_speech", "noise": "transcribed"}),
                   ood=_doc({f"g{i}": [5] for i in range(8)}, style=(0.2, 1.0)))
        r = compare.acceptance(base, bad, ids)
        self.assertEqual(r["verdict"], "KEEP_BASELINE")
        self.assertEqual(r["failed"], ["A2_no_ood_loss", "A4_abstention", "A5_readable_output"])
        self.assertEqual(r["criteria"]["A4_abstention"]["abstentions_lost"], ["noise"])

    def test_one_speaker_regression_blocks(self):
        base = {"test": _doc({f"s{i}": [3, 3] for i in range(8)}), "ood": _doc({"g": [3]}), "probes": _probes({})}
        cand = {"test": _doc({**{f"s{i}": [1, 1] for i in range(7)}, "s7": [4, 4]}), "ood": _doc({"g": [3]}), "probes": _probes({})}
        r = compare.acceptance(base, cand, [i["id"] for i in base["test"]["items"]])
        self.assertIn("A3_no_speaker_loss", r["failed"])
        self.assertEqual(r["criteria"]["A3_no_speaker_loss"]["worst_speaker"], "s7")

    def test_cluster_bootstrap_needs_two_clusters(self):
        self.assertIsNone(evaluate.bootstrap_ci({"only": (1, 10)}))
        ci = evaluate.bootstrap_ci({"a": (1, 10), "b": (3, 10)})
        self.assertTrue(0.1 <= ci[0] <= ci[1] <= 0.3)
