"""Standard-library tests for FLH-154 part 4: the one-record fixture and the
per-unit reviewer evidence the experimental report now requires.

  cd tools/extraction && python3 -B -m unittest discover -s tests -t tests
"""

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flh_extraction import comparison, decision, experimental_report as xr  # noqa: E402
from flh_extraction import fixture_one_record as fx1, reviewer_evidence as rev  # noqa: E402

FX = fx1.load()
EXPECTED = json.loads((fx1.FIXTURE_DIR / "expected.json").read_text(encoding="utf-8"))
DOC = fx1.run(FX)
PARTS = fx1.build(FX)
REFS = fx1.slice_refs(PARTS)
RAW, RES = fx1.outputs(FX, REFS)
COMP, ACCOUNTS = fx1.comparison_report(REFS, RES)
QUEUE = rev.queue(REFS, ACCOUNTS, [r["id"] for r in REFS], fx1.LIBRARY_MATRIX, "library", fx1.SCOPE)
EV = fx1.evidence_sets(FX, QUEUE)
HUMAN = FX["assumed_human_evidence"]["experimental"]
AUTOMATIC = [c for c in EXPECTED["expect"]["cases"]["correct"] if not c.startswith("experimental")]


def xrep(rows, q=QUEUE, review=fx1.REVIEW_OK, human=HUMAN):
    return xr.report(COMP, human, review, q, rows)


class Fixture(unittest.TestCase):
    def test_actual_matches_the_hand_written_expectations(self):
        self.assertEqual(fx1.diff(EXPECTED["expect"], fx1.project(DOC)), [])

    def test_one_record_ten_rows_and_the_frozen_artifacts_untouched(self):
        self.assertEqual({p: len(v) for p, v in PARTS.items()}, {"frozen": 2, "rb": 2, "challenge": 6})
        self.assertEqual({r["meta"]["fixture_source"] for r in REFS}, {"record", "follow_up"})
        self.assertTrue(all(r["id"].startswith("p4-") for r in REFS))
        self.assertTrue(all(r["meta"]["origin"] == "synthetic" and r["meta"]["review_status"] == "unreviewed" for r in REFS))
        self.assertEqual(fx1.run(FX), DOC)                                          # deterministic

    def test_bad_cases_that_every_automatic_report_accepts_are_caught_by_reviewer_evidence_only(self):
        quiet = [k for k, v in DOC["cases"].items() if v["bad"] and all(v[c]["result"] == "accept" for c in AUTOMATIC)]
        self.assertEqual(sorted(quiet), ["bilingual_drift", "unsupported_claim"])
        for k in quiet:
            v = DOC["cases"][k]
            self.assertEqual(v["experimental report without reviewer evidence (its system, E1)"]["result"], "eligible")
            self.assertEqual(v["experimental report with reviewer evidence (its system, E5)"]["result"], "excluded")
        ws = DOC["cases"]["wrong_source"]
        self.assertEqual(ws["quality heuristic (matcher, grounding, bilingual)"]["anchored_in_learner_text"], 5)   # context quotes it
        self.assertEqual(ws["quality exact (abstention, unit count)"]["result"], "reject")

    def test_every_in_scope_unit_is_listed_whatever_the_automatic_checks_say(self):
        for s, v in QUEUE["systems"].items():
            units = sum(len(x["units"]) for x in RES[s])
            self.assertEqual(v["units_in_scope"], units, s)
        self.assertEqual(sum(i["automatic"]["accepted_by_every_automatic_check"] for i in QUEUE["systems"]["wrong_source"]["items"]), 5)

    def test_cli_check_and_the_release_decision_report_unchanged(self):
        from flh_extraction import __main__ as cli
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["one-record-fixture", "--out", d, "--check"]), 0)
            self.assertTrue((Path(d) / "inputs" / "predictions-correct.jsonl").is_file())
        self.assertTrue(json.loads(out.getvalue())["matches_expected"])
        # The pre-registered decision report keeps its behaviour: it proposes the false-claim system (G6).
        self.assertEqual(DOC["decision_scenarios"]["A"]["winner_system"], "unsupported_claim")
        self.assertEqual(decision.VERSION, "flh_extractor_decision_v1 (pre-registered 2026-11-12)")


class Contract(unittest.TestCase):
    def test_missing_reviews_stay_pending(self):
        for rows in (None, [], EV["blank"], EV["partial"]):
            rep = xrep(rows)
            self.assertEqual(rep["verdict"], "PENDING")
            self.assertIsNone(rep["systems"]["unsupported_claim"]["eligible"])
        self.assertEqual(xr.report(COMP, HUMAN, fx1.REVIEW_OK)["systems"]["correct"]["reviewer"]["evidence"], "no reviewer queue")
        no_reviewer = [dict(r, reviewer="") for r in EV["full"]]
        self.assertEqual(xrep(no_reviewer)["systems"]["correct"]["reviewer"]["status"], "PENDING")

    def test_explicit_failures_exclude_and_never_become_the_preference(self):
        rep = xrep(EV["full"])
        self.assertEqual((rep["verdict"], rep["preference"]), ("EXPERIMENTAL_PREFERENCE", "correct"))
        for s, q in (("unsupported_claim", "claim_true"), ("bilingual_drift", "zh_same"), ("wrong_source", "source_raised")):
            self.assertFalse(rep["systems"][s]["eligible"])
            self.assertTrue(all(x.endswith(q) for x in rep["systems"][s]["excluded_by_reviewer_evidence"]), s)
        self.assertEqual(xrep(EV["fails_correct"])["verdict"], "NO_PREFERENCE")
        one_no = xrep(EV["explicit_no_incomplete"])
        self.assertFalse(one_no["systems"]["bilingual_drift"]["eligible"])          # a `no` wins over blanks
        self.assertEqual(one_no["verdict"], "PENDING")

    def test_the_best_f1_with_clean_sample_rates_is_still_excluded_by_one_reviewed_failure(self):
        self.assertEqual(max((h["unit_f1"], s) for s, h in HUMAN.items() if "unit_f1" in h)[1], "unsupported_claim")
        rep = xrep(EV["full"])
        self.assertEqual(rep["systems"]["unsupported_claim"]["excluded_by_human_evidence"], [])
        self.assertNotEqual(rep["preference"], "unsupported_claim")

    def test_stale_duplicate_and_mismatched_evidence_never_counts(self):
        for rows, field in ((EV["stale"], "stale_hash"), (EV["duplicate"], "duplicate")):
            rep = xrep(rows)
            self.assertEqual(rep["verdict"], "PENDING")
            self.assertEqual(len(rep["systems"]["correct"]["reviewer"]["evidence"][field]), 1)
        stale_no = copy.deepcopy(EV["full"])
        i = next(k for k, r in enumerate(stale_no) if r["system"] == "correct")
        stale_no[i].update(unit_sha256="0" * 64, claim_true="no")                  # a `no` about another output does not apply
        self.assertIsNone(xrep(stale_no)["systems"]["correct"]["eligible"])
        other = dict(QUEUE, matrix_sha256="another")
        self.assertIn("queue_mismatch", xrep(EV["full"], other)["systems"]["correct"]["reviewer"]["evidence"])
        moved = copy.deepcopy(QUEUE)
        moved["systems"]["correct"]["rows"]["scorable"] = 9
        self.assertEqual(xrep(EV["full"], moved)["systems"]["correct"]["reviewer"]["status"], "PENDING")
        absent = copy.deepcopy(QUEUE)
        del absent["systems"]["correct"]
        self.assertEqual(xrep(EV["full"], absent)["systems"]["correct"]["reviewer"]["evidence"]["queue_mismatch"],
                         ["system not in the reviewer queue"])

    def test_invalid_answers_and_scopes_are_refused(self):
        for bad in ("maybe", True, 1, "Yes "):
            with self.assertRaises(ValueError):
                rev.load_evidence([dict(EV["full"][0], claim_true=bad)])
        with self.assertRaises(ValueError):
            rev.load_evidence([{k: v for k, v in EV["full"][0].items() if k != "unit_sha256"}])
        with self.assertRaises(ValueError):
            rev.queue(REFS, ACCOUNTS, [], "m", "s", "empty")
        with self.assertRaises(ValueError):
            rev.queue(REFS, ACCOUNTS, ["not-in-slice"], "m", "s", "bad")
        from flh_extraction import __main__ as cli
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()) as out:
            p = Path(d)
            (p / "c.json").write_text(json.dumps(COMP))
            (p / "q.json").write_text(json.dumps(QUEUE))
            (p / "e.jsonl").write_text("".join(json.dumps(r) + "\n" for r in EV["invalid"]))
            self.assertEqual(cli.main(["experimental-report", "--comparison", str(p / "c.json"), "--reviewer-queue", str(p / "q.json"),
                                       "--reviewer-evidence", str(p / "e.jsonl"), "--out", str(p / "x")]), 1)
            self.assertFalse((p / "x.json").exists())
        self.assertIn("refused", out.getvalue())

    def test_failed_reference_review_still_blocks_and_production_go_is_never_true(self):
        self.assertEqual(xrep(EV["full"], review=fx1.REVIEW_FAILED)["verdict"], "BLOCKED")
        for k, v in DOC["experimental_scenarios"].items():
            if "verdict" in v:
                self.assertIs(v["production_go"], False, k)

    def test_reviewer_evidence_is_not_a_scoring_source(self):
        self.assertNotIn("reviewer_evidence.py", comparison.SCORING_SOURCES)
        self.assertNotIn("fixture_one_record.py", comparison.SCORING_SOURCES)
        self.assertNotIn("experimental_report.py", comparison.SCORING_SOURCES)


if __name__ == "__main__":
    unittest.main()
