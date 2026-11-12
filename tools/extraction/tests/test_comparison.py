"""Standard-library tests for the extractor-comparison lane: the shortcut
reproduction, row accounting, the paired cue challenge slice and its checks,
and the v3 review expansion.

  cd tools/extraction && python3 -B -m unittest discover -s tests -t tests
"""

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "authoring"))

from flh_extraction import challenge, comparison, controls, matrix, paired, review_packet  # noqa: E402
from test_quality import GEN, NEG, py_validate, rec  # noqa: E402
import generate_challenge  # noqa: E402

RB = 'Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase.'


def frozen_like():
    """Zero-unit references carry category `other` (the training cue)."""
    return [rec("e1", "Je fume jamais.", [NEG]), rec("e2", "le question", [GEN], cat="morphology"),
            rec("e3", "Merci, à demain !", [], cat="other", expl="Thanks; nothing to extract.")]


def rb_like():
    rs = copy.deepcopy(frozen_like())
    for r in rs:
        r["id"] += "#rb"
        r["input"].update(effective_category="grammar", effective_explanation=RB, resolution="unreviewed")
    return rs


class ShortcutRepro(unittest.TestCase):
    def test_category_only_equals_the_oracle_on_the_frozen_cue_and_fails_under_production_cues(self):
        with tempfile.TemporaryDirectory() as d:
            paths = {}
            for name, rs in (("frozen", frozen_like()), ("rb", rb_like())):
                p = Path(d) / f"{name}.jsonl"
                p.write_text("".join(json.dumps(r) + "\n" for r in rs), encoding="utf-8")
                paths[name] = (str(p), rs)
            rep = comparison.shortcut_repro(paths, py_validate, Path(d) / "runs")
        runs = rep["runs"]
        self.assertEqual(runs["frozen/category_only"]["outputs"]["sha256"], runs["frozen/oracle"]["outputs"]["sha256"])
        self.assertEqual(runs["frozen/category_only"]["confusion"]["abstention"],
                         {"true_abstain": 1, "false_extraction": 0, "over_abstention": 0, "true_extraction": 2,
                          "invalid_or_missing": 0})
        self.assertEqual(runs["rb/category_only"]["confusion"]["abstention"]["false_extraction"], 1)
        self.assertEqual(runs["rb/category_only"]["abstention_rate"], 0.0)
        self.assertEqual(runs["rb/constant_empty"]["confusion"]["abstention"]["over_abstention"], 2)
        self.assertEqual(rep["inputs"]["frozen"]["records"], 3)
        self.assertEqual(len(rep["scoring_version"]["sha256"]), 64)


def pred(rid, text, stopped="eos"):
    return {"id": rid, "output_text": text, "stopped": stopped}


class Accounting(unittest.TestCase):
    def fixture(self):
        refs = [rec(f"r{k}", "Je fume jamais.", [NEG]) for k in range(1, 10)]
        good = json.dumps({"units": [NEG]}, ensure_ascii=False)
        preds = [pred("r1", good),
                 pred("r2", '{"units": []}'),
                 pred("r3", good[: len(good) // 2], stopped="max_new_tokens"),
                 pred("r4", "Voici les unités : " + good),
                 pred("r5", good + "\nJ'espère que cela aide."),
                 pred("r6", json.dumps({"units": [{**NEG, "evidence": "Je fume jamais."}]}, ensure_ascii=False)),
                 pred("r7", json.dumps({"units": [{**NEG, "confidence": 1.5}]}, ensure_ascii=False)),
                 # r8: no prediction at all
                 pred("r9", good), pred("r9", '{"units": []}'),
                 pred("zz", good)]
        return refs, preds

    def test_every_reference_row_gets_exactly_one_status(self):
        refs, preds = self.fixture()
        acc = comparison.account_with_validator([r["id"] for r in refs], {r["id"]: r["input"] for r in refs}, preds, py_validate)
        st = {r["id"]: r["status"] for r in acc["rows"]}
        self.assertEqual(st, {"r1": "valid_units", "r2": "valid_empty", "r3": "unparseable:truncated_at_max_new_tokens",
                              "r4": "unparseable:leading_text", "r5": "unparseable:trailing_text",
                              "r6": "valid_extra_keys", "r7": "invalid_output", "r8": "missing_prediction",
                              "r9": "duplicate_prediction"})
        self.assertEqual(acc["references"], 9)
        self.assertEqual(sum(acc["status_counts"].values()), 9)
        self.assertEqual(acc["scorable"], 2)
        self.assertEqual((acc["unknown_ids"], acc["unknown_id_rows"]), (["zz"], 1))
        self.assertEqual(acc["rows"][5]["detail"], ["unit[0]_extra_key:evidence"])

    def test_non_scorable_rows_are_invalid_results_not_abstentions(self):
        refs, preds = self.fixture()
        acc = comparison.account_with_validator([r["id"] for r in refs], {r["id"]: r["input"] for r in refs}, preds, py_validate)
        res = comparison.scored_results(acc)
        self.assertEqual(len(res), 9)
        self.assertEqual([r["valid"] for r in res], [True, True] + [False] * 7)
        conf = comparison.confusion(refs, res)
        self.assertEqual(conf["ref_by_pred"]["ref_units"], {"empty": 1, "units": 1, "invalid": 7, "missing": 0})

    def test_strict_schema_findings(self):
        self.assertEqual(comparison.strict_schema_findings('{"units": []}'), [])
        self.assertEqual(comparison.strict_schema_findings('{"units": [], "notes": "x"}'), ["top_level_extra_key:notes"])
        u = {k: v for k, v in NEG.items() if k != "example"}
        self.assertEqual(comparison.strict_schema_findings(json.dumps({"units": [u]})), ["unit[0]_missing_key:example"])


class ParsingFixture(unittest.TestCase):
    def test_fixture_faults_are_each_counted_once(self):
        refs = [rec(f"r{k:03d}", "Je fume jamais.", [NEG] if k % 4 else []) for k in range(140)]
        rows, expect = comparison.parsing_fixture(refs)
        acc = comparison.account_with_validator([r["id"] for r in refs], {r["id"]: r["input"] for r in refs}, rows, py_validate)
        self.assertEqual(acc["status_counts"], expect)
        self.assertEqual(sum(acc["status_counts"].values()), len(refs))
        self.assertEqual(acc["unknown_id_rows"], 1)
        for status, _ in comparison.FIXTURE_FAULTS:
            self.assertIn(status, acc["status_counts"])

    def test_provider_results_are_accounted_without_raw_text(self):
        refs = [rec(f"r{k}", "Je fume jamais.", [NEG]) for k in range(5)]
        res = [{"id": "r0", "valid": True, "units": [NEG]}, {"id": "r1", "valid": True, "units": []},
               {"id": "r2", "valid": False, "error_class": "provider_timeout", "units": []},
               {"id": "r3", "valid": False, "error_class": "invalid_output", "units": []}]
        acc = matrix.account_results([r["id"] for r in refs], res)
        self.assertEqual(acc["status_counts"], {"invalid_output": 1, "missing_prediction": 1, "provider_error:provider_timeout": 1,
                                                "valid_empty": 1, "valid_units": 1})

    def test_compare_refuses_another_slice_or_scoring_version(self):
        with tempfile.TemporaryDirectory() as d:
            sl = Path(d) / "comparison-slice.jsonl"
            sl.write_text(json.dumps(rec("r1", "Je fume jamais.", [NEG])) + "\n", encoding="utf-8")
            m = {"matrix_sha256": "x", "slice": {"files": {"comparison-slice.jsonl": {"sha256": "0" * 64}}},
                 "scoring_version": {"sha256": "1" * 64}, "systems": [{"system": "qwen3.5-4b-untuned"}, {"system": "current_extractor"}]}
            rep = matrix.compare(m, sl, {"qwen3.5-4b-untuned": [pred("r1", '{"units": []}')]}, py_validate)
        self.assertEqual(len(rep["refused"]), 2)
        self.assertEqual(rep["systems"]["qwen3.5-4b-untuned"]["status"], "REFUSED")
        self.assertEqual(rep["systems"]["current_extractor"]["status"], "NOT_PERFORMED")
        self.assertEqual(rep["real_runs_measured"], 0)


class Challenge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recs = generate_challenge.build()
        cls.train = [rec("t1", "Je mange une pomme.", [GEN], points=["tr.x"]),
                     rec("t2", "Merci pour hier !", [], cat="other", split="dev")]
        cls.evals = [rec("ext-evl-0001", "Tu viens ce soir ?", [], cat="other", split="eval", points=[])]

    def test_generator_is_deterministic_and_groups_share_splits(self):
        again = generate_challenge.build()
        self.assertEqual(json.dumps(self.recs, sort_keys=True), json.dumps(again, sort_keys=True))
        self.assertEqual(len(self.recs), 3 * len(generate_challenge.bank_challenge_v1.GROUPS))
        for rs in challenge.groups_of(self.recs).values():
            self.assertEqual(len({r["meta"]["split_group"] for r in rs}), 1)
            self.assertTrue(all(r["meta"]["review_status"] == "unreviewed" for r in rs))

    def test_the_slice_passes_and_sft_refuses_it(self):
        rep = challenge.check(self.recs, self.train, self.evals)
        self.assertTrue(rep["pass"], json.dumps(rep["groups"]))
        self.assertEqual(rep["splits"]["refused_by_sft"], f"{len(self.recs)}/{len(self.recs)}")
        self.assertTrue(rep["splits"]["both_intents_in_both_splits"])

    def test_broken_groups_and_leaks_fail(self):
        cases = {}
        rs = copy.deepcopy(self.recs)
        rs[1]["meta"]["split_group"] = "challenge_dev" if rs[0]["meta"]["split_group"] == "challenge_test" else "challenge_test"
        cases["split_not_per_group"] = rs
        rs = copy.deepcopy(self.recs)
        rs[1]["expected"]["units"] = []
        cases["reference_differs"] = rs
        rs = copy.deepcopy(self.recs)
        rs[1]["input"].update({k: rs[0]["input"][k] for k in challenge.CUE_FIELDS})
        cases["identical_variants"] = rs
        rs = copy.deepcopy(self.recs)
        rs[2]["meta"]["challenge"]["variant"] = "aligned"
        cases["variants"] = rs
        for problem, rs in cases.items():
            rep = challenge.check(rs, self.train, self.evals)
            self.assertFalse(rep["pass"], problem)
            self.assertTrue(rep["groups"]["problems"].get(problem), problem)
        leak = rec("t9", self.recs[0]["input"]["original_input"], [GEN], points=[self.recs[0]["meta"]["points"][0]])
        rep = challenge.check(self.recs, self.train + [leak], self.evals)
        self.assertFalse(rep["pass"])
        self.assertTrue(rep["against"]["train_dev"]["exact_duplicates"])
        self.assertEqual(rep["objectives"]["points_in_training"], self.recs[0]["meta"]["points"])


class PairedConsistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chl = generate_challenge.build()
        cls.reps = paired.demo(cls.chl, py_validate)

    def test_the_three_reference_systems(self):
        n = len(challenge.groups_of(self.chl))
        o, c, e = (self.reps[k] for k in ("oracle", "category_only", "constant_empty"))
        self.assertEqual((o["headline"]["paired_consistency"], o["headline"]["paired_accuracy"]), (1.0, 1.0))
        self.assertEqual(c["all"]["decision_consistent"]["count"], 0)
        self.assertEqual(c["all"]["cue_flip"]["count"], n)
        self.assertEqual(c["all"]["objective_consistent"]["count"], 0)
        self.assertGreater(c["headline"]["heuristic_unit_f1"], 0.5)  # aggregate F1 alone looks tolerable
        self.assertEqual(e["headline"]["paired_consistency"], 1.0)  # consistent, and wrong on every extract group
        self.assertEqual(e["all"]["paired_correct"]["count"], e["by_intent"]["abstain"]["groups"])
        self.assertEqual(c["per_variant"]["aligned"]["decision_accuracy"], 1.0)
        self.assertEqual(c["per_variant"]["conflicting"]["decision_accuracy"], 0.0)

    def test_invalid_or_missing_output_is_never_consistent(self):
        rows = controls.outputs(self.chl, "oracle")
        res = py_validate(rows)
        res[0] = {"id": res[0]["id"], "valid": False, "error_class": "unparseable_output", "units": []}
        del res[1]
        rep = paired.report(self.chl, res)
        g = rep["groups"][0]
        self.assertFalse(g["decision_consistent"])
        self.assertTrue(g["invalid_or_missing"])
        self.assertEqual((g["decisions"]["aligned"], g["decisions"]["conflicting"]), ("invalid", "missing"))
        self.assertEqual(rep["all"]["decision_consistent"]["count"], len(rep["groups"]) - 1)


class ModelAssets(unittest.TestCase):
    def test_missing_mismatched_and_pinned_files(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import check_model_assets as cma
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.json").write_text("{}")
            (Path(d) / "tokenizer.json").write_text("not the pinned tokenizer")
            sums = {"config.json": cma.sha(Path(d) / "config.json"), "tokenizer.json": "0" * 64,
                    "tokenizer_config.json": "1" * 64, "chat_template.jinja": "2" * 64}
            rep = cma.check(sums, [d])
        st = {r["file"]: r["status"] for r in rep["token_lengths"]}
        self.assertEqual(st["config.json"], "PRESENT_OK")
        self.assertEqual(st["tokenizer.json"], "HASH_MISMATCH")
        self.assertEqual(st["chat_template.jinja"], "MISSING")
        self.assertFalse(rep["token_lengths_ready"])
        self.assertIn("tokenizer.json", rep["owner_command"])
        self.assertIn("--revision " + cma.REVISION, rep["owner_command"])


class Packaging(unittest.TestCase):
    def test_pins_mismatches_and_local_variants(self):
        from unittest import mock
        from flh_extraction import packaging
        with tempfile.TemporaryDirectory() as d:
            req = Path(d) / "r.txt"
            req.write_text("# c\ntorch==2.15.0\ntransformers==5.21.1  # qwen3_5\nsafetensors\nabsentpkg==1.0\n")
            fake = {"torch": "2.15.0+cpu", "transformers": "4.57.6", "safetensors": "0.8.0"}
            with mock.patch.object(packaging, "installed", lambda n: fake.get(n)):
                rep = packaging.check(req, probe_transformers=False)
        st = {k: v["status"] for k, v in rep["packages"].items()}
        self.assertEqual(st, {"torch": "OK", "transformers": "MISMATCH", "safetensors": "UNPINNED", "absentpkg": "MISSING"})
        self.assertEqual(rep["packages"]["torch"]["local_variant"], "cpu")
        self.assertFalse(rep["stack_matches_requirements"])
        self.assertIn("transformers 4.57.6 != 5.21.1", rep["verdict"])


def measured(abst_f=1.0, abst_rb=1.0, over=0.0, pc=1.0, ab=1.0, scorable=472):
    return {"status": "MEASURED", "rows": {"references": 472, "scorable": scorable, "status_counts": {}, "unknown_ids": [],
                                          "unknown_id_rows": 0},
            "metrics": {"frozen": {"headline": {"abstention_rate": abst_f}, "over_abstention_rate": over},
                        "rb": {"headline": {"abstention_rate": abst_rb}, "over_abstention_rate": over},
                        "challenge_test": {"headline": {"paired_consistency": pc},
                                           "by_intent": {"abstain": {"paired_correct": ab}, "extract": {"paired_correct": 1.0}}}}}


class DecisionReport(unittest.TestCase):
    HUMAN = {"current_extractor": {"unit_f1": 0.70, "judged_examples": 120}, "qwen3.5-4b-untuned": {"unit_f1": 0.40, "judged_examples": 120},
             "qwen3.5-4b-tuned": {"unit_f1": 0.82, "judged_examples": 120}}
    REVIEW = [{"id": f"i{k}", "verdict": "accept"} for k in range(44)]
    LOSSES = [{"dev_loss": 1.2}, {"dev_loss": 1.0}, {"dev_loss": 0.9}]
    INPUT = {"files": {"sft-train.jsonl": {"sha256": "t"}, "sft-dev.jsonl": {"sha256": "d"}}}
    RUN = {"train_sha256": "t", "dev_sha256": "d", "suitable_for_production": False, "smoke": False}

    def run_cli(self, comparison, human=None, review=None, extra=()):
        from flh_extraction import __main__ as cli
        with tempfile.TemporaryDirectory() as d:
            files = {"comparison": comparison, "human": human, "input-manifest": self.INPUT, "run-manifest": self.RUN}
            args = []
            for k, v in files.items():
                if v is not None:
                    (Path(d) / f"{k}.json").write_text(json.dumps(v))
                    args += [f"--{k}", str(Path(d) / f"{k}.json")]
            (Path(d) / "losses.jsonl").write_text("".join(json.dumps(x) + "\n" for x in self.LOSSES))
            args += ["--losses", str(Path(d) / "losses.jsonl")]
            if review is not None:
                (Path(d) / "review.jsonl").write_text("".join(json.dumps(x) + "\n" for x in review))
                args += ["--review", str(Path(d) / "review.jsonl")]
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(["decision-report", *args, *extra, "--out", str(Path(d) / "decision")])
            rep = json.loads((Path(d) / "decision.json").read_text())
        return code, rep

    def comp(self, **systems):
        base = {"current_extractor": measured(), "qwen3.5-4b-untuned": measured(), "qwen3.5-4b-tuned": measured()}
        base.update(systems)
        return {"refused": [], "systems": {k: v for k, v in base.items() if v is not None}}

    def test_pass_proposes_the_clear_leader(self):
        code, rep = self.run_cli(self.comp(), self.HUMAN, self.REVIEW)
        self.assertEqual((code, rep["verdict"], rep["winner"]), (0, "WINNER_FOR_OWNER_DECISION", "qwen3.5-4b-tuned"))

    def test_weak_abstention_is_never_the_winner(self):
        code, rep = self.run_cli(self.comp(**{"qwen3.5-4b-tuned": measured(abst_rb=0.0)}), self.HUMAN, self.REVIEW)
        self.assertEqual(rep["winner"], "current_extractor")
        self.assertFalse(rep["systems"]["qwen3.5-4b-tuned"]["eligible"])
        self.assertTrue(any("abstention on rb probe" in r for r in rep["reasons"]))
        weak = measured(abst_f=0.5, ab=0.0, pc=0.2)
        code, rep = self.run_cli(self.comp(**{s: weak for s in ("current_extractor", "qwen3.5-4b-untuned", "qwen3.5-4b-tuned")}),
                                 self.HUMAN, self.REVIEW)
        self.assertEqual((code, rep["verdict"], rep["winner"]), (1, "NO_WINNER", None))

    def test_constant_empty_fails_on_over_abstention_and_a_close_lead_is_no_winner(self):
        code, rep = self.run_cli(self.comp(**{"qwen3.5-4b-tuned": measured(over=1.0)}), self.HUMAN, self.REVIEW)
        self.assertEqual(rep["winner"], "current_extractor")
        close = dict(self.HUMAN, **{"current_extractor": {"unit_f1": 0.80, "judged_examples": 120}})
        code, rep = self.run_cli(self.comp(), close, self.REVIEW)
        self.assertEqual((code, rep["verdict"]), (1, "NO_WINNER"))

    def test_missing_runs_and_missing_human_judgments_are_pending(self):
        code, rep = self.run_cli(self.comp(**{"qwen3.5-4b-tuned": None}), self.HUMAN, self.REVIEW)
        self.assertEqual((code, rep["verdict"], rep["winner"]), (3, "PENDING", None))
        self.assertIn("qwen3.5-4b-tuned", rep["reasons"][0])
        code, rep = self.run_cli(self.comp(), None, self.REVIEW)
        self.assertEqual((code, rep["verdict"]), (3, "PENDING"))
        code, rep = self.run_cli(self.comp(), self.HUMAN, self.REVIEW[:30] + [{"id": "u", "verdict": None}] * 14)
        self.assertEqual((code, rep["verdict"]), (3, "PENDING"))
        code, rep = self.run_cli({"refused": ["slice hash differs from the matrix"], "systems": {}})
        self.assertEqual((code, rep["verdict"]), (1, "REFUSED"))


class ReviewV3(unittest.TestCase):
    def test_one_example_per_label_and_family_samples(self):
        self.assertEqual(set(review_packet.LABELS), {"OK", "OVER_SPLIT", "UNDER_SPLIT", "FALSE_PREMISE", "BILINGUAL_DRIFT",
                                                     "UNSUPPORTED", "CUE_DEPENDENT"})
        chl = generate_challenge.build()
        base = [rec("b1", "« Elle est une acteuse » → « C'est une actrice »", [GEN], points=["p1"]),
                rec("b2", "« les jours » et « le question » ?", [NEG, GEN], cat="mixed", points=["p2", "p3"]),
                rec("b3", "Je fume jamais.", [NEG], case="misconception", points=["p4"]),
                rec("b4", "Merci !", [GEN], expl="Nouns ending in « -tion » are feminine.", points=["p5"])]
        items = review_packet.build_v3(base, [], chl, exclude={"b3"})
        fams = {i["family"] for i in items}
        self.assertIn("CUE_DEPENDENT", fams)
        self.assertNotIn("b3", {i["id"] for i in items})
        self.assertTrue(all(i["verdict"] is None and i["label"] is None for i in items))
        self.assertIn("one illustrative example each", review_packet.markdown_v3(items))


if __name__ == "__main__":
    unittest.main()
