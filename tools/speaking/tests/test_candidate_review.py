"""Offline candidate review (flh_speaking.candidate_review): standard library only, no inference."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

from flh_speaking import candidate_review as cr  # noqa: E402
from flh_speaking import lab, textnorm  # noqa: E402

FIX = PKG / "fixtures" / "lab" / "candidate_review"
FIXTURE_SHA256 = {
    "baseline.json": "ea80f8a47ac5a9dbb835709ed32863b05279164b0c610caf1d4fb6ee9156049b",
    "candidate.json": "e1a79bc2cb711455cf245ffde9adc9220b405f2a50bb0ce89442c7c0f05d17fe",
    "baseline-8.json": "b2f776236acd9df7fc3bf491ed7dff9ef414c00132b086a1719470b8e869d7ba",
    "candidate-8.json": "336dbf6bf4a9eab2ff1fd7c73d678b9c3b6181b5716a734fe50413fec5ecd284",
    "candidate-mismatched.json": "11bb0399a9f28d2b8658081b6a505489c09c0329329e4c422cf32cd68b13c1c6",
}


def ev(texts: list[tuple[str, str, str]], timing: dict | None = None, name: str = "m", split: str = "t") -> dict:
    """A minimal saved evaluation: (speaker, reference, served text) per item, one item per row."""
    items = [{"id": f"{spk}-{k}", "cluster": spk, "gender": "F", "ref": ref, "served": {"status": "transcribed", "text": hyp}}
             for k, (spk, ref, hyp) in enumerate(texts)]
    summary = {"label": name, "split": split, "served": textnorm.rate([textnorm.score(i["ref"], i["served"]["text"]) for i in items])}
    if timing is not None:
        summary["timing"] = timing
    return {"schema": cr.EVAL_SCHEMA, "model_dir_name": name, "decoding": "d", "normalization": textnorm.NORM_VERSION,
            "summary": summary, "items": items}


def pair(n_groups=30, words=5, base_errors=None, cand_errors=None, timing=None):
    """n_groups speakers, one item each of ``words`` words; errors are dropped trailing words."""
    ref = "un deux trois quatre cinq six sept huit neuf dix".split()[:words]
    be = base_errors or [1] * n_groups
    ce = cand_errors or [0] * n_groups
    b = ev([(f"s{k:02d}", " ".join(ref), " ".join(ref[:words - be[k]])) for k in range(n_groups)], {"real_time_factor": 0.1, "peak_rss_mb": 700.0}, "base")
    c = ev([(f"s{k:02d}", " ".join(ref), " ".join(ref[:words - ce[k]])) for k in range(n_groups)],
           timing if timing is not None else {"real_time_factor": 0.3, "peak_rss_mb": 1500.0}, "cand")
    return b, c


def run(b, c, th=None, **kw):
    inputs = {"baseline": {"file": "b.json", "bytes": 0, "sha256": "0" * 64}, "candidate": {"file": "c.json", "bytes": 0, "sha256": "1" * 64}}
    return cr.review(b, c, inputs, cr.load_thresholds(th) if th else None, **kw)


def status(rv, cid):
    return next(c for c in rv["checks"] if c["id"] == cid)["status"]


class Outcomes(unittest.TestCase):
    def test_fixtures_are_the_pinned_synthetic_files(self):
        for f, h in FIXTURE_SHA256.items():
            self.assertEqual(hashlib.sha256((FIX / f).read_bytes()).hexdigest(), h, f)

    def test_ready_insufficient_and_mismatched_each_name_a_concrete_reason(self):
        ready = cr.from_files(str(FIX / "baseline.json"), str(FIX / "candidate.json"))
        self.assertEqual((ready["outcome"], ready["exit_code"]), ("ready_for_owner_review", 0))
        self.assertEqual([r["code"] for r in ready["reasons"]], ["all_checks_pass"])
        self.assertIn("32 paired samples over 32 groups", ready["reasons"][0]["detail"])
        few = cr.from_files(str(FIX / "baseline-8.json"), str(FIX / "candidate-8.json"))
        self.assertEqual((few["outcome"], few["exit_code"]), ("insufficient_support", 4))
        self.assertEqual([r["code"] for r in few["reasons"]], ["support.min_paired_samples", "support.min_groups", "other_checks_decide_nothing"])
        self.assertEqual(few["reasons"][1]["detail"], "8 groups (speakers) compared; at least 30 are required")
        bad = cr.from_files(str(FIX / "baseline.json"), str(FIX / "candidate-mismatched.json"))
        self.assertEqual((bad["outcome"], bad["exit_code"]), ("mismatched_inputs", 5))
        self.assertEqual([r["code"] for r in bad["reasons"]], ["same_ids", "same_references"])
        self.assertIn("syn-s07-u1 (missing in candidate)", bad["reasons"][0]["detail"])
        self.assertIn("syn-s12-u1", bad["reasons"][1]["detail"])
        self.assertTrue(all(c["status"] == "not_evaluated" for c in bad["checks"][2:]))

    def test_counts_identities_hashes_and_unmeasured_values_are_reported(self):
        few = cr.from_files(str(FIX / "baseline-8.json"), str(FIX / "candidate-8.json"))
        s = few["samples"]
        self.assertEqual((s["baseline"], s["candidate"], s["paired"], s["missing"], s["speakers"]["paired"], s["groups"]), (8, 8, 8, [], 8, 8))
        self.assertEqual(few["inputs"]["baseline"]["sha256"], FIXTURE_SHA256["baseline-8.json"])
        self.assertEqual(few["inputs"]["candidate"]["file"], "candidate-8.json")  # basename only, never a machine path
        self.assertEqual((few["models"]["baseline"]["model_dir_name"], few["models"]["candidate"]["model_dir_name"]),
                         ("synthetic-baseline-v1", "synthetic-candidate-v1"))
        self.assertIsNone(few["models"]["candidate"]["candidate_id"])
        self.assertIn("not pinned", few["models"]["candidate"]["candidate_id_basis"])
        m = few["measures"]["baseline"]
        self.assertEqual((m["peak_rss_mb"]["status"], m["peak_rss_mb"]["value"]), ("not_measured", None))
        self.assertEqual(m["peak_rss_mb"]["reason"], "the evaluation recorded no timing")
        self.assertEqual(few["measures"]["candidate"]["peak_rss_mb"], {"value": 1500.0, "status": "measured", "basis": cr.TIMING[1][1]})
        self.assertIn("not measured", cr.render_text(few))

    def test_unmeasured_candidate_resources_block_readiness(self):
        b, c = pair(timing={})
        rv = run(b, c)
        self.assertEqual(rv["outcome"], "thresholds_not_met")
        self.assertEqual([r["code"] for r in rv["reasons"]], ["resources.max_real_time_factor", "resources.max_peak_rss_mb"])
        self.assertTrue(rv["reasons"][0]["detail"].startswith("not measured: "))

    def test_other_mismatches(self):
        b, c = pair()
        c2 = copy.deepcopy(c)
        c2["summary"]["split"] = "other"
        self.assertIn("same_split", [r["code"] for r in run(b, c2)["reasons"]])
        c3 = copy.deepcopy(c)
        c3["summary"]["served"]["sub"] += 1  # an edited summary
        self.assertIn("candidate_stored_summary", [r["code"] for r in run(b, c3)["reasons"]])
        self.assertIn("distinct_models", [r["code"] for r in run(b, copy.deepcopy(b))["reasons"]])
        with self.assertRaises(ValueError):
            run(b, {"schema": "something_else"})


class Thresholds(unittest.TestCase):
    """Every limit is inclusive: a value exactly at its limit passes, one step beyond fails."""

    def test_hand_computed_defaults_at_the_limit(self):
        # 30 speakers x 5 words = 150 words; the candidate saves 3 errors: WER difference exactly -3/150 = -0.02
        b, c = pair(30, 5, base_errors=[1, 1, 1] + [0] * 27, cand_errors=[0] * 30, timing={"real_time_factor": 0.5, "peak_rss_mb": 2048.0})
        rv = run(b, c)
        self.assertEqual(rv["measures"]["difference"]["wer"], -0.02)
        self.assertEqual((rv["samples"]["paired"], rv["samples"]["groups"]), (30, 30))
        for cid in ("support.min_paired_samples", "support.min_groups", "quality.max_wer_difference",
                    "resources.max_real_time_factor", "resources.max_peak_rss_mb"):
            self.assertEqual(status(rv, cid), "pass", cid)
        # 29 speakers: one below both support minimums
        b29, c29 = pair(29)
        self.assertEqual(run(b29, c29)["outcome"], "insufficient_support")
        # two saved errors on 150 words: -0.0133 > -0.02
        b2, c2 = pair(30, 5, base_errors=[1, 1] + [0] * 28, cand_errors=[0] * 30)
        self.assertEqual(status(run(b2, c2), "quality.max_wer_difference"), "fail")
        _, cr_over = pair(30, timing={"real_time_factor": 0.5001, "peak_rss_mb": 2048.1})
        over = run(b, cr_over)
        self.assertEqual((status(over, "resources.max_real_time_factor"), status(over, "resources.max_peak_rss_mb")), ("fail", "fail"))

    def test_every_limit_equal_to_the_measured_value_passes_and_one_step_beyond_fails(self):
        b, c = (json.loads((FIX / f).read_text(encoding="utf-8")) for f in ("baseline.json", "candidate.json"))
        base = run(b, c)
        steps = {"support": 1, "quality": 0.0001, "resources": 0.0001}
        for chk in base["checks"]:
            section, key = chk["id"].split(".")
            at = {"schema": cr.THRESHOLDS_SCHEMA, section: {key: chk["value"]}}
            self.assertEqual(status(run(b, c, at), chk["id"]), "pass", chk["id"])
            step = steps[section] if key.startswith("min") else -steps[section]
            beyond = {"schema": cr.THRESHOLDS_SCHEMA, section: {key: round(chk["value"] + step, 4)}}
            rv = run(b, c, beyond)
            self.assertEqual(status(rv, chk["id"]), "fail", chk["id"])
            self.assertEqual(rv["outcome"], "insufficient_support" if section == "support" else "thresholds_not_met", chk["id"])
            self.assertIn(chk["id"], [r["code"] for r in rv["reasons"]])

    def test_threshold_files_are_validated(self):
        for bad in ({"schema": "x"}, {"schema": cr.THRESHOLDS_SCHEMA, "quality": {"max_wer": 0}},
                    {"schema": cr.THRESHOLDS_SCHEMA, "support": {"min_groups": 2.5}}, {"schema": cr.THRESHOLDS_SCHEMA, "speed": {}},
                    {"schema": cr.THRESHOLDS_SCHEMA, "quality": {"max_wer_difference": True}}):
            with self.assertRaises(ValueError):
                cr.load_thresholds(bad)
        self.assertEqual(cr.load_thresholds({"schema": cr.THRESHOLDS_SCHEMA, "support": {"min_groups": 8}})["support"],
                         {"min_paired_samples": 30, "min_groups": 8})


class Boundaries(unittest.TestCase):
    def test_promotion_is_never_performed(self):
        for a, b in (("baseline.json", "candidate.json"), ("baseline-8.json", "candidate-8.json"), ("baseline.json", "candidate-mismatched.json")):
            rv = cr.from_files(str(FIX / a), str(FIX / b))
            self.assertEqual((rv["promotion"]["performed"], rv["promotion"]["decided_by"]), (False, "owner"))
            self.assertIn("promotion: not performed", cr.render_text(rv))
        src = (PKG / "flh_speaking" / "candidate_review.py").read_text(encoding="utf-8")
        for word in ("import service", "import deployment", "RUNBOOK.md\", \"w", "environ"):
            self.assertNotIn(word, src)

    def test_cli_writes_only_the_requested_files_and_exits_by_outcome(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run([sys.executable, "-B", "-m", "flh_speaking", "lab", "candidate-review", "--baseline", str(FIX / "baseline-8.json"),
                                "--candidate", str(FIX / "candidate-8.json"), "--json", f"{d}/r.json", "--text", f"{d}/r.txt"],
                               cwd=PKG, capture_output=True, text=True)
            self.assertEqual(p.returncode, 4, p.stderr)
            self.assertEqual(sorted(x.name for x in Path(d).iterdir()), ["r.json", "r.txt"])
            rv = json.loads(Path(d, "r.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(d, "r.txt").read_text(encoding="utf-8"), cr.render_text(rv))  # text from the JSON alone
            self.assertEqual(lab.privacy_findings(Path(d, "r.json").read_text(encoding="utf-8")), [])
            promote = subprocess.run([sys.executable, "-B", "-m", "flh_speaking", "lab", "candidate-review", "--baseline", "x", "--candidate", "y", "--promote"],
                                     cwd=PKG, capture_output=True, text=True)
            self.assertEqual(promote.returncode, 2)  # no such option

    def test_demo_needs_a_clean_directory_and_matches_the_expected_files(self):
        with tempfile.TemporaryDirectory() as d:
            rc, text = cr.demo(f"{d}/out", check=True)
            self.assertEqual(rc, 0, text)
            self.assertEqual(len(list(Path(d, "out").iterdir())), 7)  # 3 scenarios x JSON + text, and one walkthrough
            with self.assertRaises(ValueError):
                cr.demo(f"{d}/out")


class Walkthrough(unittest.TestCase):
    """Item 109: why a review's speakers are, or are not, enough; computed from the saved review only."""

    def test_eight_speakers_are_explained_step_by_step(self):
        rv = cr.from_files(str(FIX / "baseline-8.json"), str(FIX / "candidate-8.json"))
        text = cr.walkthrough(rv)
        self.assertEqual(text, (FIX / "expected" / "insufficient.walkthrough.txt").read_text(encoding="utf-8"))
        self.assertIn("speakers: 8 < 30 -> fail; 22 more distinct speakers are needed", text)
        self.assertIn("fewer errors for 7 of 8 speakers, more for 0, the same for 1", text)
        self.assertIn("would be 'ready_for_owner_review'. That is not a forecast", text)
        self.assertIn("promotion performed: false", text)
        self.assertEqual(lab.privacy_findings(text), [])

    def test_clips_never_stand_in_for_speakers_and_the_data_manifest_counts_speakers(self):
        b, c = pair(n_groups=4, base_errors=[2, 1, 1, 0], cand_errors=[0, 0, 1, 0])
        for d in (b, c):  # ten clips per speaker: 40 clips, 4 speakers
            d["items"] = [{**i, "id": f"{i['id']}-{k}"} for i in d["items"] for k in range(10)]
            d["summary"]["served"] = textnorm.rate([textnorm.score(i["ref"], i["served"]["text"]) for i in d["items"]])
        rv = run(b, c)
        self.assertEqual(rv["outcome"], "insufficient_support")
        text = cr.walkthrough(rv, [{"split": "t", "speaker": f"s{k}", "corpus": "synthetic"} for k in range(4)]
                              + [{"split": "train", "speaker": f"x{k}"} for k in range(40)])
        self.assertIn("clips: 40 >= 30 -> pass; speakers: 4 < 30 -> fail", text)
        self.assertIn("40 clips are still 4 speakers' worth of evidence", text)
        self.assertRegex(text, r"width \d\.\d{4}, (wider than|narrower than|the same as) the speaker interval's")
        self.assertIn("split 't' has 4 speakers in total, so no selection from it can reach 30", text)
        self.assertNotIn("every split has fewer than", text)  # train has 40
        self.assertIn("corpora named in the manifest: synthetic", text)

    def test_one_speaker_has_no_interval_and_other_documents_are_refused(self):
        b, c = pair(n_groups=1)
        text = cr.walkthrough(run(b, c))
        self.assertIn("no interval: fewer than 2 groups with reference words", text)
        with self.assertRaises(ValueError):
            cr.walkthrough({"schema": "flh_speaking_lab_batch_v1"})

    def test_cli_reads_a_saved_review(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable, "-B", "-m", "flh_speaking", "lab", "candidate-review", "--baseline", str(FIX / "baseline-8.json"),
                            "--candidate", str(FIX / "candidate-8.json"), "--json", f"{d}/r.json", "--text", f"{d}/r.txt"], cwd=PKG, check=False)
            p = subprocess.run([sys.executable, "-B", "-m", "flh_speaking", "lab", "candidate-review-walkthrough", "--review", f"{d}/r.json"],
                               cwd=PKG, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stdout, (FIX / "expected" / "insufficient.walkthrough.txt").read_text(encoding="utf-8"))
            bad = subprocess.run([sys.executable, "-B", "-m", "flh_speaking", "lab", "candidate-review-walkthrough", "--review", f"{d}/r.txt"],
                                 cwd=PKG, capture_output=True, text=True)
            self.assertEqual(bad.returncode, 2)


class Compatibility(unittest.TestCase):
    """Item 103: low support is visible in JSON and text; existing fields and exit codes are unchanged."""

    def test_observation_standing_is_added_without_changing_the_ranking_fields(self):
        three = PKG / "fixtures" / "lab" / "three_rows"
        res = lab.batch(lab.read_refs(str(three / "refs.jsonl")), *lab.read_results(str(three / "a.jsonl")), *lab.read_results(str(three / "b.jsonl")))
        rk = res["ranking"]
        self.assertEqual((rk["status"], rk["fewer_errors"], rk["note"]), ("ranked", "B", "observation only: fewer than 30 groups"))
        self.assertEqual((rk["standing"], rk["min_groups"]), ("observation", 30))
        text = lab.render_batch_text(res)
        self.assertIn("ranking: ranked: fewer errors B (observation only: fewer than 30 groups)", text)  # the old line, unchanged
        self.assertIn("standing: OBSERVATION ONLY: 3 groups, fewer than 30", text)

    def test_ranked_and_not_ranked_standings(self):
        refs = {f"r{k}": {"id": f"r{k}", "reference": "le chat dort", "speaker": f"s{k}", "group_id": f"s{k}"} for k in range(30)}
        h = lambda x: {"label": x, "model_id": x, "config_id": "c"}  # noqa: E731
        ok = lab.batch(refs, h("A"), {i: "le chat" for i in refs}, h("B"), {i: "le chat dort" for i in refs})
        self.assertEqual((ok["ranking"]["status"], ok["ranking"]["standing"]), ("ranked", "ranked"))
        self.assertIn("standing: ranked on 30 groups", lab.render_batch_text(ok))
        gone = lab.batch(refs, h("A"), {i: "x" for i in list(refs)[1:]}, h("B"), {i: "x" for i in refs})
        self.assertEqual((gone["ranking"]["status"], gone["ranking"]["standing"]), ("not_ranked", "not_ranked"))
        self.assertIn("standing: NOT RANKED: the sample sets differ", lab.render_batch_text(gone))


if __name__ == "__main__":
    unittest.main()
