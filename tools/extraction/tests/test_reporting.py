"""Standard-library regressions for the reporting discrepancies found in the
FLH-154 review (items 26-39) and tests of the frozen reviewer sample.

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

from flh_extraction import __main__ as cli  # noqa: E402
from flh_extraction import decision, evaluate, promotion, quality, review_sample  # noqa: E402
from test_comparison import measured  # noqa: E402
from test_quality import GEN, NEG, rec  # noqa: E402
import generate_challenge  # noqa: E402

HUMAN = {"current_extractor": {"unit_f1": 0.70, "judged_examples": 120}, "qwen3.5-4b-untuned": {"unit_f1": 0.40, "judged_examples": 120},
         "qwen3.5-4b-tuned": {"unit_f1": 0.82, "judged_examples": 120}}
REVIEW = [{"id": f"i{k}", "verdict": "accept"} for k in range(44)]
LOSSES = [{"dev_loss": 1.2}, {"dev_loss": 1.0}, {"dev_loss": 0.9}]
INPUT = {"files": {"sft-train.jsonl": {"sha256": "t"}, "sft-dev.jsonl": {"sha256": "d"}}}
RUN = {"train_sha256": "t", "dev_sha256": "d", "suitable_for_production": False, "smoke": False}


def comp(**systems):
    base = {"current_extractor": measured(), "qwen3.5-4b-untuned": measured(), "qwen3.5-4b-tuned": measured()}
    base.update(systems)
    return {"refused": [], "systems": base}


def with_counts(sysrep, **counts):
    s = copy.deepcopy(sysrep)
    s["rows"]["status_counts"] = counts
    return s


class IncompleteRunIsPending(unittest.TestCase):
    """FLH-154 item 28: a forgotten rb shard was read as weak rb abstention and
    another system was proposed as the winner."""

    def test_a_missing_shard_is_pending_and_never_read_as_weak_abstention(self):
        tuned = with_counts(measured(abst_rb=0.0, scorable=272), missing_prediction=200, valid_units=225, valid_empty=47)
        rep = decision.decide(comp(**{"qwen3.5-4b-tuned": tuned}), HUMAN, REVIEW, LOSSES, RUN, INPUT)
        self.assertEqual((rep["verdict"], rep["winner"]), ("PENDING", None))
        t = rep["systems"]["qwen3.5-4b-tuned"]
        self.assertIsNone(t["eligible"])
        self.assertEqual(t["incomplete_run"], {"missing_prediction": 200})
        self.assertFalse(any("abstention on rb probe" in r for r in rep["reasons"]))
        self.assertTrue(rep["reasons"][0].startswith("incomplete run: qwen3.5-4b-tuned has 200 missing_prediction"))
        self.assertIn("INCOMPLETE RUN", decision.markdown(rep))

    def test_duplicated_predictions_are_incomplete_too(self):
        rep = decision.decide(comp(**{"current_extractor": with_counts(measured(), duplicate_prediction=2)}), HUMAN, REVIEW,
                              LOSSES, RUN, INPUT)
        self.assertEqual(rep["verdict"], "PENDING")
        self.assertEqual(rep["systems"]["current_extractor"]["incomplete_run"], {"duplicate_prediction": 2})

    def test_complete_runs_keep_the_pre_registered_rules(self):
        rep = decision.decide(comp(**{"qwen3.5-4b-tuned": with_counts(measured(abst_rb=0.0), valid_units=472)}), HUMAN, REVIEW,
                              LOSSES, RUN, INPUT)
        self.assertEqual((rep["verdict"], rep["winner"]), ("WINNER_FOR_OWNER_DECISION", "current_extractor"))
        self.assertTrue(any("abstention on rb probe" in r for r in rep["reasons"]))


def run_cli(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(args)
    return code, out.getvalue(), err.getvalue()


def jl(path, rows):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return str(path)


class StandaloneReportsRefuseDuplicateIds(unittest.TestCase):
    """FLH-154 item 27: quality, evaluate and paired-consistency kept the last
    of two contradicting result rows; compare counts them as duplicate_prediction."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.refs = [rec("e1", "Je fume jamais.", [NEG], split="eval"), rec("e2", "Merci !", [], cat="other", split="eval")]
        good = [{"id": "e1", "valid": True, "units": [NEG]}, {"id": "e2", "valid": True, "units": []}]
        self.ok = jl(self.d / "ok.jsonl", good)
        self.dup = jl(self.d / "dup.jsonl", good + [{"id": "e1", "valid": True, "units": []}])
        self.extra = jl(self.d / "extra.jsonl", good + [{"id": "x9", "valid": True, "units": []}])
        self.r = jl(self.d / "refs.jsonl", self.refs)

    def tearDown(self):
        self.tmp.cleanup()

    def test_quality_and_evaluate(self):
        for cmd in (["quality"], ["evaluate", "--title", "t"]):
            code, _, _ = run_cli(cmd + ["--refs", self.r, "--results", self.ok, "--out", str(self.d / "o")])
            self.assertEqual(code, 0)
            with self.assertRaises(SystemExit) as e:
                run_cli(cmd + ["--refs", self.r, "--results", self.dup, "--out", str(self.d / "o")])
            self.assertIn("duplicated id", str(e.exception.code))
            code, _, err = run_cli(cmd + ["--refs", self.r, "--results", self.extra, "--out", str(self.d / "o")])
            self.assertEqual(code, 0)
            self.assertIn("1 result id(s) are not in the references", err)

    def test_paired_consistency(self):
        chl = [r for r in generate_challenge.build() if r["meta"]["split_group"] == "challenge_test"]
        c = jl(self.d / "chl.jsonl", chl)
        res = [{"id": r["id"], "valid": True, "units": r["expected"]["units"]} for r in chl]
        code, _, _ = run_cli(["paired-consistency", "--challenge", c, "--results", jl(self.d / "r.jsonl", res), "--out", str(self.d / "p")])
        self.assertEqual(code, 0)
        with self.assertRaises(SystemExit):
            run_cli(["paired-consistency", "--challenge", c, "--results", jl(self.d / "r2.jsonl", res + res[:1]), "--out", str(self.d / "p")])

    def test_quality_compare_warns_on_different_populations(self):
        a = quality.report(self.refs, [{"id": "e1", "valid": True, "units": [NEG]}, {"id": "e2", "valid": True, "units": []}])
        b = quality.report(self.refs[:1], [{"id": "e1", "valid": True, "units": [NEG]}])
        pa, pb = self.d / "a.json", self.d / "b.json"
        pa.write_text(json.dumps(a))
        pb.write_text(json.dumps(b))
        code, _, err = run_cli(["quality-compare", "--a", str(pa), "--b", str(pb), "--out", str(self.d / "qc")])
        self.assertEqual(code, 0)
        self.assertIn("different populations", err)
        self.assertTrue((self.d / "qc.md").read_text().startswith("WARNING"))


class PromotionNeedsTheSameExamples(unittest.TestCase):
    """FLH-154 item 28: promotion-check compared a candidate scored on one set
    of examples with a baseline scored on another."""

    def setUp(self):
        self.refs = [rec(f"e{i}", "Je fume jamais.", [NEG], split="eval") for i in range(4)] + [rec("z", "Merci !", [], cat="other", split="eval")]
        self.res = [{"id": r["id"], "valid": True, "units": r["expected"]["units"]} for r in self.refs]

    def test_different_example_sets_are_pending_never_a_fail(self):
        cand = quality.report(self.refs[:2] + self.refs[4:], self.res)
        base = quality.report(self.refs, [{**x, "units": []} for x in self.res])
        rep = promotion.check(cand, cand, base)
        self.assertEqual(rep["criteria"][0]["status"], "PENDING")
        self.assertNotIn("FAIL", {c["status"] for c in rep["criteria"]})
        self.assertEqual(rep["verdict"], "PENDING")

    def test_same_examples_pass_the_population_criterion(self):
        q = quality.report(self.refs, self.res)
        rep = promotion.check(q, q, q)
        self.assertEqual(rep["criteria"][0]["status"], "PASS")


class CrossReportDenominators(unittest.TestCase):
    @unittest.expectedFailure
    def test_quality_and_evaluate_count_invalid_rows_alike(self):
        """KNOWN DISCREPANCY (FLH-154 F1, item 29), kept as an expected failure:
        quality.report leaves invalid rows out of unit F1 and never counts them as
        empty answers; evaluate.evaluate counts their reference units as missed and
        the rows as `nonzero_refs_answered_empty`. Both modules are pinned scoring
        code: aligning them changes the scoring version and needs the owner's
        decision and a re-pinned matrix. Remove the decorator once they agree."""
        refs = [rec("e1", "Je fume jamais.", [NEG], split="eval"), rec("e2", "le question", [GEN], cat="morphology", split="eval")]
        res = [{"id": "e1", "valid": True, "units": [NEG]}, {"id": "e2", "valid": False, "error_class": "unparseable_output", "units": []}]
        q, e = quality.report(refs, res), evaluate.evaluate(refs, res)
        self.assertEqual(q["semantic"]["heuristic"]["unit_f1"], round(e["unit_f1"], 3))
        self.assertEqual(q["abstention"]["unit_refs_answered_empty"], e["abstention"]["nonzero_refs_answered_empty"])


RB = 'Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase.'


def fake_slice():
    """Frozen references in two objective clusters plus zero and false-premise
    cases, their rb views, and the real challenge_test groups."""
    fz = [rec("ext-evl-0001", "Moi : je fume jamais.", [NEG], split="eval", points=["p.neg"]),
          rec("ext-evl-0002", "le question ?", [GEN], cat="morphology", split="eval", points=["p.gen"]),
          rec("ext-evl-0003", "Deux erreurs : je fume jamais, le question.", [NEG, GEN], split="eval", points=["p.neg", "p.gen"],
              case="multi_2"),
          rec("ext-evl-0004", "Tu as des chaussures marrons ?", [dict(GEN, canonical="adjectifs de couleur invariables (marron, orange)")],
              split="eval", points=["p.col"]),
          rec("ext-evl-0005", "Merci !", [], cat="other", split="eval", case="zero"),
          rec("ext-evl-0006", "Et là ?", [], cat="other", split="eval", case="insufficient"),
          rec("ext-evl-0007", "On dit jamais ne, c'est inutile.", [NEG], split="eval", points=["p.neg"], case="false_premise")]
    rb = []
    for r in fz:
        x = copy.deepcopy(r)
        x["id"] += "#rb"
        x["input"].update(effective_category="grammar", effective_explanation=RB, resolution="unreviewed")
        x["meta"]["probe"] = {"variant": "rb", "derived_from": r["id"]}
        rb.append(x)
    chl = generate_challenge.build()
    return fz + rb + [r for r in chl if r["meta"]["split_group"] == "challenge_test"], chl


class ReviewSample(unittest.TestCase):
    def setUp(self):
        self.slice, self.chl = fake_slice()
        self.rows = review_sample.packet(review_sample.select(self.slice, self.chl))

    def test_selection_is_frozen_and_follows_the_rule(self):
        again = review_sample.packet(review_sample.select(self.slice, self.chl))
        self.assertEqual(json.dumps(self.rows, sort_keys=True), json.dumps(again, sort_keys=True))
        by = {}
        for r in self.rows:
            by.setdefault(r["stratum"], []).append(r["id"])
        self.assertEqual(len(by["objective"]), 2)        # two clusters: {neg, gen} linked by the multi_2 record, {col}
        self.assertEqual(sorted(by["zero"]), ["ext-evl-0005", "ext-evl-0006"])
        self.assertTrue(all(i.startswith("chl-g") for i in by["cue_dispute"]))
        self.assertEqual(len({r["id"] for r in self.rows}), len(self.rows))
        disputed = {r["id"] for r in self.rows if r["dispute"]["status"] == "disputed"}
        self.assertTrue(set(by["cue_dispute"]) <= disputed)
        self.assertIn("ext-evl-0004", disputed)            # holds an over-general unit
        for r in self.rows:
            self.assertIsNone(r["verdict"])
            self.assertEqual(len(r["review"]["wording"]), len(r["reference"]["units"]))

    def test_rubric_examples_never_come_from_the_held_out_sets(self):
        text = json.dumps(review_sample.RUBRIC, ensure_ascii=False)
        self.assertNotRegex(text, r"ext-evl-|ext-chl-|chl-g\d")
        for q in review_sample.RUBRIC["intent"] + review_sample.RUBRIC["wording"]:
            self.assertTrue(q["yes"] and q["no"])

    def fill(self, rows, intent=True, wording=True, resolve=False):
        rows = copy.deepcopy(rows)
        for r in rows:
            r["review"]["intent"].update(decision_ok=intent, objectives_ok=True)
            for w in r["review"]["wording"]:
                w.update(statement_true=wording, statement_zh_same=True, canonical_ok=True, example_ok=True)
            r["verdict"] = "accept" if (resolve or r["dispute"]["status"] != "disputed") else None
            if resolve and r["dispute"]["status"] == "disputed":
                r["review"]["dispute_position"] = "the reference holds: the learner's text decides"
        return rows

    def test_agreement_keeps_intent_and_wording_apart_and_leaves_disputes_open(self):
        rows = self.fill(self.rows, wording=False)
        rep = review_sample.agreement(rows)
        disputed = [r["id"] for r in rows if r["dispute"]["status"] == "disputed"]
        self.assertEqual(sorted(rep["disputed_unresolved"]), sorted(disputed))
        counted = len(rows) - len(disputed)
        self.assertEqual(rep["intent_agreement_with_reference"], {"count": counted, "of": counted, "rate": 1.0})
        self.assertEqual(rep["wording_agreement_with_reference"]["all_fields"]["count"], 0)
        self.assertIn("never_combined", rep)
        quarantined = self.fill(self.rows)
        for r in quarantined:
            if r["dispute"]["status"] == "disputed":
                r["verdict"] = "quarantine"
                r["review"]["dispute_position"] = "reasonable people disagree"
        self.assertEqual(len(review_sample.agreement(quarantined)["disputed_unresolved"]), len(disputed))
        resolved = review_sample.agreement(self.fill(self.rows, resolve=True))
        self.assertEqual(resolved["disputed_unresolved"], [])
        self.assertEqual(resolved["intent_agreement_with_reference"]["of"], len(rows))

    def test_decision_report_never_resolves_a_dispute_by_default(self):
        rows = self.fill(self.rows)
        for r in rows:
            if r["dispute"]["status"] == "disputed":
                r["verdict"] = "accept"                    # a verdict without the position taken
        rep = decision.decide(comp(), HUMAN, REVIEW[:25] + rows, LOSSES, RUN, INPUT)
        self.assertEqual(rep["verdict"], "PENDING")
        self.assertGreater(rep["review"]["evidence"]["disputed_unresolved"], 0)
        rep = decision.decide(comp(), HUMAN, REVIEW[:25] + self.fill(self.rows, resolve=True), LOSSES, RUN, INPUT)
        self.assertEqual((rep["verdict"], rep["review"]["evidence"]["disputed_unresolved"]), ("WINNER_FOR_OWNER_DECISION", 0))

    def test_between_reviewers(self):
        a = self.fill(self.rows, resolve=True)
        b = self.fill(self.rows, resolve=True)
        b[0]["review"]["intent"]["decision_ok"] = False
        rep = review_sample.agreement(a, b)["between_reviewers"]
        self.assertEqual(rep["intent"]["count"], len(a) - 1)
        self.assertEqual(rep["intent"]["cohen_kappa"], 0.0)   # reviewer a says yes everywhere: chance agreement is high
        self.assertEqual(review_sample._kappa([(True, True), (False, False), (True, False), (False, True)]), 0.0)
        self.assertEqual(review_sample._kappa([(True, True), (False, False)]), 1.0)

    def test_export_privacy(self):
        clean = json.dumps(self.rows, ensure_ascii=False) + review_sample.markdown(self.rows, review_sample.selection_doc(self.rows, "0" * 64, "1" * 64))
        self.assertEqual(review_sample.export_findings(clean), [])
        planted = ('{"entry_id": 42} /home/someone/notes http://localhost:8080/private a.person@example.org '
                   'AKIAABCDEFGHIJKLMNOP 123456789012 000000000000')
        self.assertEqual({f["rule"] for f in review_sample.export_findings(planted)},
                         {"entry_id_nonzero", "local_path", "private_link", "email", "secret_like", "aws_account"})


if __name__ == "__main__":
    unittest.main()
