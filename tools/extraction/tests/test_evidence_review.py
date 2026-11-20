"""Evidence review of extraction outputs (flh_extraction.evidence_review): standard library only."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flh_extraction import evidence_review as er  # noqa: E402
from flh_extraction.records import load_jsonl  # noqa: E402

FIX = ROOT / "fixtures" / "evidence_review_v1"
PINNED = {  # the fixture is reproducible from these files only
    "refs.jsonl": None, "result-a.jsonl": None, "result-b.jsonl": None,
}


def build(limit=50, page=1):
    return er.build(str(FIX / "refs.jsonl"), str(FIX / "result-a.jsonl"), str(FIX / "result-b.jsonl"), limit, page)


class EvidenceReview(unittest.TestCase):
    def test_classes_are_kept_apart(self):
        rep = build()
        self.assertEqual(rep["a"]["counts"]["by_class"], {"anchored": 1, "conflicting_evidence": 2})
        self.assertEqual(rep["b"]["counts"]["by_class"], {"malformed": 1, "missing_evidence": 1, "unsupported": 1})
        self.assertEqual(rep["b"]["record_findings"], [{"id": "er-depuis", "class": "malformed", "reason": "leading_text"}])

    def test_each_unit_sits_beside_a_bounded_excerpt_of_its_source(self):
        rep = build()
        refs = {r["id"]: r for r in load_jsonl(FIX / "refs.jsonl")}
        for u in rep["a"]["units_page"]["items"]:
            self.assertIn("[", u["evidence"])
            self.assertLessEqual(len(u["evidence"]), 2 * er.EXCERPT + 60)  # an excerpt, never the full text
        raw = json.dumps(rep, ensure_ascii=False)
        for r in refs.values():
            self.assertNotIn(r["input"]["original_input"] + " " + r["input"]["original_context"], raw)
        recs = er.review(list(refs.values()), er.load_outputs(FIX / "result-a.jsonl"))["records"]
        self.assertEqual({x["id"]: x["source_sha256"] for x in recs},
                         {i: hashlib.sha256(f"{r['input']['original_input']} {r['input']['original_context']}".encode()).hexdigest() for i, r in refs.items()})

    def test_coverage_per_kind(self):
        cov = build()["a"]["counts"]["coverage_by_kind"]
        self.assertEqual((cov["grammar"]["units"], cov["grammar"]["anchored"], cov["grammar"]["conflicting_evidence"]), (2, 1, 1))
        self.assertEqual((cov["usage"]["units"], cov["usage"]["conflicting_evidence"], cov["usage"]["anchored_share"]), (1, 1, 0.0))

    def test_comparison_is_deterministic_and_counts_only_new_regressions(self):
        a, b = build(), build()
        self.assertEqual(a["comparison"], b["comparison"])
        cmp = a["comparison"]
        self.assertEqual((cmp["regressions"], cmp["improvements"]), (3, 0))
        kinds = sorted((c["id"], c["change"], c["regression"]) for c in cmp["changes_page"]["items"])
        self.assertIn(("er-depuis", "record", True), kinds)
        self.assertIn(("er-missing", "added", True), kinds)
        # the known FLH-154 F1 expected failure is listed apart and never counted as a regression
        self.assertEqual([k["id"] for k in a["known_issues"]], ["FLH-154-F1"])
        self.assertTrue(a["known_issues"][0]["still_marked_expected_failure"])

    def test_pagination_and_limits(self):
        rep = build(limit=2, page=2)
        pg = rep["a"]["units_page"]
        self.assertEqual((pg["total"], pg["pages"], pg["page"], len(pg["items"])), (3, 2, 2, 1))
        with self.assertRaises(ValueError):
            build(limit=0)

    def test_accepted_and_rejected_results_and_pinned_inputs(self):
        rep = build()
        self.assertEqual(rep["a"]["record_findings"], [])                 # A is accepted: every record parses, evidence located
        self.assertTrue(rep["b"]["record_findings"])                      # B is rejected: a malformed record
        self.assertEqual(sorted(rep["inputs"]), sorted(PINNED))
        for name, digest in rep["inputs"].items():
            self.assertEqual(digest, hashlib.sha256((FIX / name).read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
