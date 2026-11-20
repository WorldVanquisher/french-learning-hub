"""The bounded lab experiment's prepare and report steps (standard library only; no model, no Docker)."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "scripts"))

import lab_experiment as ex  # noqa: E402
from flh_speaking import lab, pins  # noqa: E402

REF = "le chat dort sur le canapé"


def source_data(root: Path) -> None:
    """Six synthetic clips from three speakers, in the prepared-data layout."""
    (root / "audio" / "test").mkdir(parents=True)
    wav = lab.synthetic_audio()
    rows = []
    for spk in ("s2", "s1", "s3"):
        for k in (1, 0):
            i = f"{spk}_{k}"
            (root / "audio" / "test" / f"{i}.wav").write_bytes(wav)
            rows.append({"id": i, "speaker": spk, "gender": "F", "group": "book:1", "text": REF, "seconds": 0.6, "corpus": "synthetic",
                         "split": "test", "file": f"audio/test/{i}.wav", "pcm_sha256": hashlib.sha256(wav[44:]).hexdigest()})
    rows.append({**rows[0], "id": "other", "split": "train"})
    (root / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def fake_eval(work: Path, model: str, cond: str, hyp: dict, ids) -> None:
    items = [{"id": i, "cluster": i.split("_")[0], "ref": REF, "served": {"text": hyp.get(i, REF), "status": "transcribed"}} for i in ids]
    doc = {"model_dir_name": pins.MODELS[model]["revision"], "decoding": "d", "normalization": "n",
           "summary": {"label": f"{model} {cond}", "split": cond,
                       "timing": {"real_time_factor": 0.1, "peak_rss_mb": 900.0, "compute_s": 1.0, "audio_s": 10.0, "model_load_s": 1.0}},
           "items": items}
    (work / "evals").mkdir(exist_ok=True)
    (work / "evals" / f"{model}-{cond}.json").write_text(json.dumps(doc), encoding="utf-8")


def quiet(fn, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(argparse.Namespace(**kw))


class Experiment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        source_data(self.root / "src")
        self.work = self.root / "work"
        quiet(ex.prepare, data=str(self.root / "src"), work=str(self.work), per_speaker=1)
        self.prep = json.loads((self.work / "prepare.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_prepare_selects_deterministically_and_hashes_the_noise_copies(self):
        self.assertEqual(self.prep["ids"], ["s1_0", "s2_0", "s3_0"])  # first clip per speaker, id order, test split only
        rows = [json.loads(x) for x in (self.work / "data" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted({r["split"] for r in rows}), ["clean", "noise20"])
        for r in rows:
            b = (self.work / "data" / r["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(b[44:]).hexdigest(), r["pcm_sha256"])
        clean = {r["id"]: r["pcm_sha256"] for r in rows if r["split"] == "clean"}
        noisy = {r["id"]: r["pcm_sha256"] for r in rows if r["split"] == "noise20"}
        self.assertTrue(all(clean[i] != noisy[i] for i in clean))
        self.assertNotIn(str(self.root), (self.work / "prepare.json").read_text(encoding="utf-8"))

    def write_run(self):
        (self.work / "run.json").write_text(json.dumps({"image_id": "sha256:test", "image_lock_sha256": "l", "code_sha256": {}, "limits": ex.LIMITS,
                                                        "runs": [{"model": m, "condition": c, "exit": 0, "wall_s": 1.0}
                                                                 for m in ex.MODELS for c in ex.CONDITIONS]}), encoding="utf-8")

    def test_report_gives_identity_intervals_and_sizes_and_never_ranks_few_speakers(self):
        ids = self.prep["ids"]
        for m in ex.MODELS:
            for c in ex.CONDITIONS:
                fake_eval(self.work, m, c, {"s1_0": "le chat dort"} if m == "whisper-base" else {}, ids)
        self.write_run()
        quiet(ex.report, work=str(self.work))
        doc = json.loads((self.work / "experiment-result.json").read_text(encoding="utf-8"))
        cmp = doc["comparisons"]["base-vs-small-clean"]
        self.assertEqual((cmp["samples"], cmp["groups"], cmp["invalidated"]), (3, 3, []))
        self.assertEqual(cmp["wer_difference_b_minus_a"], -0.1667)  # small fixes 3 of 18 words
        self.assertIn("fewer than 30 groups", cmp["ranking_note"])
        self.assertEqual(cmp["standing"], "observation")
        self.assertEqual(doc["status"], "experimented")
        self.assertTrue(doc["experiment_id"].startswith("lab-exp-"))
        for name, o in doc["sizes"]["outputs"].items():
            self.assertEqual(o["sha256"], hashlib.sha256((self.work / name).read_bytes()).hexdigest())
        again = self.work / "again.json"
        os.replace(self.work / "experiment-result.json", again)
        quiet(ex.report, work=str(self.work))
        self.assertEqual(json.loads(again.read_text())["experiment_id"], json.loads((self.work / "experiment-result.json").read_text())["experiment_id"])

    def test_a_differing_sample_set_is_refused(self):
        ids = self.prep["ids"]
        for m in ex.MODELS:
            for c in ex.CONDITIONS:
                fake_eval(self.work, m, c, {}, ids if m == "whisper-base" else ids[:-1])
        self.write_run()
        with self.assertRaises(SystemExit) as e:
            quiet(ex.report, work=str(self.work))
        self.assertIn("do not share one reference set", str(e.exception))


    def test_rerun_picks_the_smallest_speaker_and_compares_every_text(self):
        spk, ids = ex.smallest_speaker(str(self.work))
        self.assertEqual((spk, ids), ("s1", ["s1_0"]))  # equal audio: lowest id wins
        first = {"items": [{"id": "s1_0", "served": {"text": "le chat", "status": "transcribed"}},
                           {"id": "s2_0", "served": {"text": "x", "status": "transcribed"}}]}
        same = {"items": [{"id": "s1_0", "served": {"text": "le chat", "status": "transcribed"}}]}
        other = {"items": [{"id": "s1_0", "served": {"text": "le chat.", "status": "transcribed"}}]}
        self.assertEqual(ex.compare_rerun(first, same)["identical"], 1)
        self.assertEqual(ex.compare_rerun(first, other)["identical"], 0)

    def test_reproduce_refuses_packaged_code_that_differs_from_the_tree(self):
        pkg = self.root / "pkg"
        (pkg / "__pycache__").mkdir(parents=True)
        (pkg / "a.py").write_text("x = 1\n", encoding="utf-8")
        (pkg / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"cache")  # bytecode never counts
        tree = ex.code_hashes(str(pkg))
        self.assertEqual(list(tree), ["a.py"])
        self.assertEqual(ex.code_differences(dict(tree), tree), [])
        image = {"a.py": "0" * 64, "old.py": "1" * 64}
        self.assertEqual(ex.code_differences(image, tree), [
            {"path": "a.py", "image": "0" * 12, "tree": tree["a.py"][:12]},
            {"path": "old.py", "image": "1" * 12, "tree": "absent"}])
        self.assertIn("/opt/program/flh_speaking", ex.PACKAGED_HASHES)  # the image side reads its own copy, not a mount

    def test_reproduce_compares_the_same_ids_without_measured_resources(self):
        ids = self.prep["ids"]
        for m in ex.MODELS:
            fake_eval(self.work, m, "clean", {"s1_0": "le chat dort"} if m == "whisper-base" else {}, ids)
        docs = {m: json.loads((self.work / "evals" / f"{m}-clean.json").read_text(encoding="utf-8")) for m in ex.MODELS}
        small = {m: ex.restrict(d, ["s1_0"]) for m, d in docs.items()}
        self.assertEqual([i["id"] for i in small["whisper-base"]["items"]], ["s1_0"])
        a = ex.pair_from_docs(small["whisper-base"], small["whisper-small"], *ex.MODELS, "base", "small")
        slower = {m: {**d, "summary": {**d["summary"], "timing": {**d["summary"]["timing"], "real_time_factor": 0.9}}} for m, d in small.items()}
        b = ex.pair_from_docs(slower["whisper-base"], slower["whisper-small"], *ex.MODELS, "base", "small")
        self.assertNotEqual(a, b)  # the measured speed differs ...
        self.assertEqual(ex.without_resources(a), ex.without_resources(b))  # ... the comparison does not
        self.assertEqual((a["paired"]["samples"], a["paired"]["groups"], a["ranking"]["standing"]), (1, 1, "observation"))
        changed = {**small["whisper-small"], "items": [{**small["whisper-small"]["items"][0], "served": {"text": "le chien", "status": "transcribed"}}]}
        c = ex.pair_from_docs(small["whisper-base"], changed, *ex.MODELS, "base", "small")
        self.assertNotEqual(ex.without_resources(a), ex.without_resources(c))


if __name__ == "__main__":
    unittest.main()
