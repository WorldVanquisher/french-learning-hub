"""Evaluation-data intake checks and the observation standing (standard library only; synthetic fixtures)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)

from flh_speaking import intake  # noqa: E402

FIX = os.path.join(PKG, "fixtures", "lab", "intake")
REVIEW = os.path.join(PKG, "fixtures", "lab", "candidate_review", "expected")


def rows(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def doc(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class Intake(unittest.TestCase):
    def test_checklist_passes_and_fails_with_reasons(self):
        ok = intake.check_proposal(doc(os.path.join(FIX, "proposal-eligible.json")))
        self.assertEqual(ok["decision"], "eligible for owner approval")
        self.assertEqual(len(ok["rows"]), len(intake.ITEMS))
        bad = intake.check_proposal(doc(os.path.join(FIX, "proposal-not-eligible.json")))
        failed = {r["id"] for r in bad["rows"] if r["status"] == "fail"}
        self.assertEqual(failed, {i[0] for i in intake.ITEMS})
        self.assertIn("speaker_name", next(r["detail"] for r in bad["rows"] if r["id"] == "no_personal_data"))
        self.assertIn("adds no support", next(r["detail"] for r in bad["rows"] if r["id"] == "speaker_ids"))

    def test_speaker_needs_count_corpus_speakers_and_never_train(self):
        rs = [{"split": "train", "corpus": "mls", "speaker": str(i)} for i in range(24)]
        rs += [{"split": "test", "corpus": "mls", "speaker": str(100 + i)} for i in range(8)]
        rs += [{"split": "dev", "corpus": "mls", "speaker": str(200 + i)} for i in range(4)]
        rs += [{"split": "dev", "corpus": "mls", "speaker": "3"}]  # a training speaker in dev: does not count
        rs += [{"split": "ood", "corpus": "fleurs", "speaker": None}] * 5
        n = intake.speaker_needs(rs, 30)
        self.assertEqual(n["splits"]["test"]["needed_for_min_groups"], 22)
        self.assertEqual((n["splits"]["dev"]["speakers"], n["splits"]["dev"]["shared_with_train"], n["splits"]["dev"]["needed_for_min_groups"]), (5, 1, 26))
        self.assertEqual((n["pooled_evaluation_speakers"], n["pooled_needed"]), (12, 18))
        self.assertEqual(n["splits"]["ood"]["clips_without_speaker_id"], 5)

    def test_colliding_speaker_ids_are_kept_apart_and_duplicate_audio_is_caught(self):
        m = intake.merge_check({"src_a": rows("source-a.jsonl"), "src_b": rows("source-b.jsonl")})
        self.assertEqual([c["speaker"] for c in m["collisions"]], ["103"])
        self.assertEqual((m["groups_after_namespacing"], m["groups_if_raw_ids_were_trusted"]), (8, 7))
        self.assertEqual(len(m["duplicate_audio"]), 1)
        self.assertFalse(m["ok"])

    def test_noise_conditions_stay_paired(self):
        q = intake.pair_check(rows("noise-pairs.jsonl"))
        self.assertEqual(q["conditions"], ["clean", "noise_snr10"])
        self.assertEqual(q["paired_clips"], 4)
        self.assertEqual([(u["speaker"], u["clip"], u["missing"]) for u in q["unpaired"]],
                         [("s2", "c2", ["noise_snr10"]), ("s3", "c1", ["clean"])])
        self.assertEqual(q["per_speaker_pairs"], {"s1": 2, "s2": 1, "s3": 1})

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "r.json")
            r = subprocess.run([sys.executable, "-B", "-m", "flh_speaking", "lab", "intake", "--proposal", os.path.join(FIX, "proposal-eligible.json"),
                                "--pairs", os.path.join(FIX, "noise-pairs.jsonl"), "--json", out], cwd=PKG, capture_output=True, text=True,
                               env={**os.environ, "PYTHONPATH": PKG})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("eligible for owner approval", r.stdout)
            self.assertEqual(doc(out)["pairs"]["paired_clips"], 4)
            r = subprocess.run([sys.executable, "-B", "-m", "flh_speaking", "lab", "intake", "--source", "a=" + os.path.join(FIX, "source-a.jsonl"),
                                "--source", "b=" + os.path.join(FIX, "source-b.jsonl")], cwd=PKG, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": PKG})
            self.assertEqual(r.returncode, 1)
            self.assertIn("collision 103", r.stdout)


class Standing(unittest.TestCase):
    def test_eight_speakers_remain_an_observation_in_the_machine_readable_review(self):
        rv = doc(os.path.join(REVIEW, "insufficient.json"))
        self.assertEqual((rv["outcome"], rv["exit_code"], rv["standing"]), ("insufficient_support", 4, "observation"))
        self.assertEqual(rv["thresholds"]["support"]["min_groups"], 30)
        self.assertLess(rv["samples"]["groups"], rv["thresholds"]["support"]["min_groups"])
        self.assertIs(rv["promotion"]["performed"], False)
        self.assertEqual(rv["serving_default"], "unchanged (RUNBOOK.md decides what is served)")


if __name__ == "__main__":
    unittest.main()
