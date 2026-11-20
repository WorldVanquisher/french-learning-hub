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


class TrainingData(unittest.TestCase):
    rows = [{"id": "t1", "split": "train", "corpus": "mls", "speaker": "1", "text": "Une phrase.", "pcm_sha256": "a" * 64, "gender": "F", "seconds": 3.0},
            {"id": "t2", "split": "train", "corpus": "mls", "speaker": "2", "text": "Deux phrases.", "pcm_sha256": "b" * 64, "gender": "M", "seconds": 4.0},
            {"id": "e1", "split": "test", "corpus": "mls", "speaker": "3", "text": "Une phrase !", "pcm_sha256": "c" * 64, "gender": "F", "seconds": 2.0},
            {"id": "e2", "split": "test", "corpus": "mls", "speaker": "2", "text": "Autre chose.", "pcm_sha256": "b" * 64, "gender": "M", "seconds": 5.0},
            {"id": "o1", "split": "ood", "corpus": "fleurs", "speaker": None, "text": "", "pcm_sha256": "d" * 64, "gender": None, "seconds": 1.0}]

    def test_speaker_group_claims_refuse_unlabeled_rows(self):
        r = intake.require_speakers(self.rows)
        self.assertEqual((r["without_speaker"], r["examples"]), (1, ["o1"]))
        self.assertTrue(r["decision"].startswith("refused"))
        self.assertEqual(intake.require_speakers(self.rows[:4])["decision"], "usable")

    def test_overlap_by_speaker_text_and_audio(self):
        train = [r for r in self.rows if r["split"] == "train"]
        o = intake.overlap_report(train, {"test": [r for r in self.rows if r["split"] == "test"], "ood": [self.rows[-1]]})
        self.assertEqual((o["sets"]["test"]["speakers_shared"], o["sets"]["test"]["texts_shared"], o["sets"]["test"]["audio_shared"]), (1, 1, 1))
        self.assertEqual(o["sets"]["ood"]["rows_without_speaker"], 1)
        self.assertFalse(o["ok"])

    def test_balance_counts_missing_labels(self):
        b = intake.balance(self.rows)
        self.assertEqual((b["test"]["speakers"], b["test"]["gender"]), (2, {"F": 1, "M": 1}))
        self.assertEqual((b["ood"]["missing_text"], b["ood"]["missing_speaker"], b["ood"]["gender"]), (1, 1, {"unknown": 1}))
        self.assertEqual(b["train"]["hours"], round(7 / 3600, 3))


class TrainingIntake(unittest.TestCase):
    """R4: training-data intake on synthetic manifests (no audio exists)."""
    OK = os.path.join(PKG, "fixtures", "intake_r4", "training-intake.ok.json")
    BAD = os.path.join(PKG, "fixtures", "intake_r4", "training-intake.refused.json")

    def test_clean_proposal_is_eligible_and_reports_counts_only(self):
        r = intake.training_intake(doc(self.OK))
        self.assertEqual((r["decision"], r["refusals"]), ("eligible for owner approval", []))
        self.assertEqual({k: (v["clips"], v["distinct_speakers"]) for k, v in r["summary"].items()}, {"test": (12, 6), "train": (12, 0)})
        self.assertEqual(r["summary"]["test"]["varieties"], {"african_accented": 6, "unspecified": 6})
        text = json.dumps(r, ensure_ascii=False)
        self.assertNotIn("phrase d", text)  # no transcript in the report
        self.assertTrue(any("cannot be checked" in n for n in r["notes"]))  # FLEURS rows carry no speaker ID: never assumed disjoint

    def test_every_fault_is_refused_with_a_fix(self):
        r = intake.training_intake(doc(self.BAD))
        joined = "\n".join(r["refusals"])
        for needle in ("CC-BY-NC-4.0", "personal fields", "generator's terms", "voices' speakers consented", "same audio as row",
                       "repeated ID", "missing locale", "'mystery' is not declared", "locale fr_ca", "1 speakers shared with train"):
            self.assertIn(needle, joined)
        self.assertTrue(all(" — " in x for x in r["refusals"]))
        self.assertTrue(r["decision"].startswith("refused"))

    def test_speakers_are_namespaced_per_source(self):
        m = doc(self.OK)
        m["rows"].append({**m["rows"][-1], "id": "x", "source_id": "mls_fr", "split": "train", "speaker": "a1", "pcm_sha256": "e" * 64, "text": "autre"})
        r = intake.training_intake(m)
        self.assertEqual(r["leakage"]["sets"]["test"]["speakers_shared"], 0)  # mls_fr:a1 is not slr57:a1

    def test_cli_exit_codes(self):
        run = lambda f: subprocess.run([sys.executable, "-B", "-m", "flh_speaking", "lab", "training-intake", "--manifest", f], cwd=PKG,  # noqa: E731
                                       capture_output=True, text=True).returncode
        self.assertEqual((run(self.OK), run(self.BAD)), (0, 1))


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
