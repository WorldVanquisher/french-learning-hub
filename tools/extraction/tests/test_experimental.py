"""Standard-library tests for FLH-154 part 3: the DRAFT experimental report (it
can never issue a production GO) and the review sheet (intent, evidence and
wording apart; disputes and missing verdicts are never accepted silently).
Part 4 (report v1): a preference also needs per-unit reviewer evidence; the
helper `reviewed` supplies a complete, passing queue and evidence so each test
still isolates the criterion it is about (test_reviewer_evidence.py covers it).

  cd tools/extraction && python3 -B -m unittest discover -s tests -t tests
"""

import copy
import csv
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flh_extraction import decision, experimental_report as xr, review_sample, review_sheet  # noqa: E402
from flh_extraction import reviewer_evidence as rev  # noqa: E402
from test_comparison import measured  # noqa: E402

PACKET = [json.loads(x) for x in (ROOT / "review" / "review-sample-v1.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def human(f1, false=0, unsupported=0, bilingual=0, **over):
    h = {"unit_f1": f1, "judged_examples": 120, "judged_objectives": 45,
         "false_claims": {"judged_units": 150, "false": false},
         "unsupported_units": {"judged_units": 150, "unsupported": unsupported},
         "bilingual_mismatch": {"judged_units": 150, "mismatched": bilingual}}
    h.update(over)
    return h


GOOD = {"a": human(0.80), "b": human(0.60), "c": human(0.50)}
REVIEW = [{"id": f"r{k}", "verdict": "accept"} for k in range(30)]


def comp(**systems):
    base = {"a": measured(), "b": measured(), "c": measured()}
    base.update(systems)
    return {"refused": [], "systems": base}


def reviewed(c):
    """A queue with one in-scope unit per measured system and a complete `yes` review of each."""
    q = {"schema": rev.QUEUE_SCHEMA, "matrix_sha256": c.get("matrix_sha256"), "scope": {"source": "test", "records": 1, "ids": ["x"]},
         "systems": {s: {"rows": {k: v["rows"][k] for k in ("references", "scorable", "status_counts")}, "units_in_scope": 1,
                         "items": [{"id": "x", "unit": 0, "unit_sha256": "h-" + s}], "abstentions_in_scope": [], "not_scorable_in_scope": {}}
                     for s, v in c["systems"].items() if v.get("status") == "MEASURED"}}
    ev = [{"system": s, "id": "x", "unit": 0, "unit_sha256": "h-" + s, "source_raised": "yes", "claim_true": "yes", "zh_same": "yes",
           "reviewer": "test"} for s in q["systems"]]
    return q, ev


def xrep(c, h, r):
    return xr.report(c, h, r, *reviewed(c))


class ExperimentalReport(unittest.TestCase):
    def test_a_clear_leader_is_only_an_experimental_preference(self):
        rep = xrep(comp(), GOOD, REVIEW)
        self.assertEqual((rep["verdict"], rep["preference"], rep["production_go"]), ("EXPERIMENTAL_PREFERENCE", "a", False))
        self.assertIn("not a production GO", rep["reasons"][-1])
        self.assertEqual(xr.report(comp(), GOOD, REVIEW)["verdict"], "PENDING")   # v1: no reviewer evidence, no preference

    def test_it_can_never_issue_production_go(self):
        scenarios = [(comp(), GOOD, REVIEW), (comp(), None, None), (comp(a=measured(abst_rb=0.0)), GOOD, REVIEW),
                     ({"refused": ["slice hash differs"], "systems": {}}, GOOD, REVIEW),
                     (comp(), dict(GOOD, production_go=True), REVIEW)]
        for c, h, r in scenarios:
            rep = xr.report(c, h, r)
            self.assertIs(rep["production_go"], False)
            self.assertIn(rep["verdict"], xr.VERDICTS)
            self.assertNotIn("WINNER", json.dumps(rep))
            self.assertNotIn("GO_", rep["verdict"])

    def test_every_missing_piece_of_human_evidence_is_pending(self):
        for field in xr.FIELDS:
            h = copy.deepcopy(GOOD)
            del h["a"][field]
            rep = xrep(comp(), h, REVIEW)
            self.assertEqual(rep["verdict"], "PENDING", field)
            self.assertIsNone(rep["systems"]["a"]["eligible"], field)
        h = copy.deepcopy(GOOD)
        h["a"]["false_claims"] = {"judged_units": 40, "false": 0}       # too few judged units: still PENDING, never a pass
        self.assertEqual(xrep(comp(), h, REVIEW)["verdict"], "PENDING")
        self.assertEqual(xrep(comp(), {"a": GOOD["a"], "b": GOOD["b"]}, REVIEW)["verdict"], "PENDING")

    def test_false_claims_exclude_the_best_f1(self):
        h = dict(GOOD, a=human(0.95, false=10))                         # 10 / 150 = 0.067 > 0.02
        rep = xrep(comp(), h, REVIEW)
        self.assertFalse(rep["systems"]["a"]["eligible"])
        self.assertEqual(rep["systems"]["a"]["excluded_by_human_evidence"], ["human false-claim rate <= 0.02"])
        self.assertEqual(rep["preference"], "b")

    def test_failed_human_review_blocks_any_recommendation(self):
        bad = [{"id": f"r{k}", "verdict": "reject" if k < 6 else "accept"} for k in range(30)]   # 20 % rejected
        rep = xr.report(comp(), GOOD, bad)
        self.assertEqual((rep["verdict"], rep["preference"]), ("BLOCKED", None))
        self.assertTrue(rep["reasons"][0].startswith("reference review failed"))

    def test_unavailable_human_review_never_invents_a_verdict(self):
        rep = xr.report(comp(c=measured(over=1.0)), {"unavailable": {"reason": "no reviewer this month"}}, REVIEW)
        self.assertEqual((rep["verdict"], rep["preference"]), ("PENDING", None))
        self.assertTrue(any("no verdict is invented" in r for r in rep["reasons"]))
        self.assertEqual(rep["systems"]["a"]["human"][0]["evidence"]["unavailable"], "no reviewer this month")
        self.assertEqual(rep["systems"]["c"]["excluded_by_exact_gates"], ["over-abstention on frozen <= 0.1", "over-abstention on rb probe <= 0.1"])
        per = xr.report(comp(), dict(GOOD, b={"unavailable": {"reason": "reviewer left"}}), REVIEW)
        self.assertEqual(per["verdict"], "PENDING")

    def test_incomplete_runs_and_unfinished_review_are_pending(self):
        inc = measured()
        inc["rows"]["status_counts"] = {"missing_prediction": 200}
        self.assertEqual(xrep(comp(a=inc), GOOD, REVIEW)["verdict"], "PENDING")
        self.assertEqual(xrep(comp(), GOOD, REVIEW + [{"id": "x", "verdict": None}])["verdict"], "PENDING")
        self.assertEqual(xrep(comp(), GOOD, None)["verdict"], "PENDING")

    def test_exact_gates_are_the_pre_registered_ones(self):
        for sysrep in (measured(), measured(abst_rb=0.85), measured(pc=0.875), measured(over=0.2), measured(scorable=400)):
            rep = xr.report(comp(a=sysrep), GOOD, REVIEW)
            self.assertEqual(rep["systems"]["a"]["exact"], decision.gates(sysrep))

    def test_an_exact_005_lead_counts_at_three_decimals(self):
        rep = xrep(comp(), {"a": human(0.60), "b": human(0.55), "c": human(0.30)}, REVIEW)
        self.assertEqual(rep["preference"], "a")                         # decision.py would say NO_WINNER (F6)


def fill(sheet_text, answer):
    """answer(row) -> dict of column updates."""
    rows = list(csv.DictReader(io.StringIO(sheet_text)))
    for r in rows:
        r.update(answer(r))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=review_sheet.HEADER, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def all_yes(position=True, verdict="accept"):
    def f(r):
        first = r["unit"] in ("0", "1")
        out = {}
        if r["unit"] != "0":
            out.update({c: "yes" for c in review_sheet.UNIT if c != "C_wording_fix"})
        if first:
            out.update(A_intent_decision_ok="yes", A_intent_objectives_ok="yes", D_verdict=verdict, D_reviewer="owner", D_date="2026-11-20")
            if r["dispute"] and position:
                out["D_dispute_position"] = "the learner's text decides; the reference holds"
        return out
    return f


class ReviewSheet(unittest.TestCase):
    def setUp(self):
        self.text = review_sheet.export(PACKET)
        self.before = json.dumps(PACKET, sort_keys=True)

    def tearDown(self):
        self.assertEqual(json.dumps(PACKET, sort_keys=True), self.before)   # the packet is never changed

    def test_the_sample_is_fixed_and_disputes_are_labelled(self):
        self.assertEqual(len(PACKET), 35)
        rows = list(csv.DictReader(io.StringIO(self.text)))
        self.assertEqual(len(rows), 37)
        disputed = {r["item_id"] for r in rows if r["dispute"].startswith(review_sheet.OPEN)}
        self.assertEqual(disputed, {i["id"] for i in PACKET if i["dispute"]["status"] == "disputed"})
        self.assertEqual(len(disputed), 8)
        filled, rep = review_sheet.load(PACKET, self.text)
        self.assertEqual((rep["counted"], len(rep["labels"]["NO VERDICT"])), (0, 35))

    def test_a_complete_sheet_counts_everything(self):
        filled, rep = review_sheet.load(PACKET, fill(self.text, all_yes()))
        self.assertEqual(rep["counted"], 35)
        self.assertTrue(all(decision.reviewed(i) for i in filled))
        self.assertEqual(xr.review_state(filled)["status"], "PASS")
        ag = review_sample.agreement(filled)
        self.assertEqual(ag["labels"]["COUNTED"], sorted(i["id"] for i in PACKET))
        self.assertEqual(ag["evidence_agreement_with_reference"]["claim_true"]["rate"], 1.0)
        self.assertEqual(ag["intent_agreement_with_reference"]["rate"], 1.0)

    def test_disputes_without_a_position_and_quarantine_stay_open(self):
        for variant in (all_yes(position=False), all_yes(verdict="quarantine")):
            filled, rep = review_sheet.load(PACKET, fill(self.text, variant))
            open_ = rep["labels"][review_sheet.OPEN]
            self.assertEqual(len(open_), 8)
            self.assertFalse(any(decision.reviewed(i) for i in filled if i["id"] in open_))
            self.assertEqual(xr.review_state(filled)["status"], "PENDING")
            self.assertEqual(sorted(review_sample.agreement(filled)["disputed_unresolved"]), open_)

    def test_no_verdict_rows_are_never_counted(self):
        def some(r):
            return all_yes()(r) if r["item"] != "1" else {}
        filled, rep = review_sheet.load(PACKET, fill(self.text, some))
        self.assertEqual(rep["labels"]["NO VERDICT"], [PACKET[0]["id"]])
        self.assertFalse(decision.reviewed(filled[0]))
        self.assertEqual(xr.review_state(filled)["status"], "PENDING")

    def test_refusals(self):
        def tamper(r):
            return {"canonical": "changed"} if r["item"] == "3" else {}
        def guessed(r):
            out = all_yes()(r)
            if r["item"] == "2":
                out["B_evidence_claim_true"] = ""                       # a verdict with an unanswered question
            return out
        def bad_value(r):
            return dict(all_yes()(r), A_intent_decision_ok="maybe") if r["unit"] in ("0", "1") else all_yes()(r)
        def second_row(r):
            out = all_yes()(r)
            if r["unit"] == "2":
                out["D_verdict"] = "reject"
            return out
        for f, msg in ((tamper, "fixed column canonical was changed"), (guessed, "unanswered questions"),
                       (bad_value, "is not yes, no or blank"), (second_row, "first row only")):
            with self.assertRaises(ValueError) as e:
                review_sheet.load(PACKET, fill(self.text, f))
            self.assertIn(msg, str(e.exception))
        with self.assertRaises(ValueError):
            review_sheet.load(PACKET, self.text.replace("D_date", "date", 1))


if __name__ == "__main__":
    unittest.main()
