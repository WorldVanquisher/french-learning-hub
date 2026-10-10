"""Acceptance-oracle tests, not UI/browser tests."""
import copy
import unittest

from integrated_checks import check_detail, check_search


class IntegratedChecksTests(unittest.TestCase):
    def search(self):
        return {"schema_version": "knowledge_library_search_v1", "limit": 1,
                "total_matches": 2, "truncated": True, "tokens": ["subj"],
                "results": [{"concept": {"id": 3}, "match_tier": "identity",
                             "matched_fields": ["target"], "supporting_unit_count": 1,
                             "current_member_count": 2}]}

    def test_search_order_tier_tokens_and_total(self):
        check_search(self.search(), [3], ["subj"], ["identity"], limit=1, total=2)

    def test_search_rejects_wrong_order_or_tokens(self):
        for ids, tokens in [([4], ["subj"]), ([3], ["wrong"])]:
            with self.subTest(ids=ids, tokens=tokens), self.assertRaises(AssertionError):
                check_search(self.search(), ids, tokens, limit=1, total=2)

    def test_search_rejects_inaccurate_truncation(self):
        data = self.search()
        data["truncated"] = False
        with self.assertRaisesRegex(AssertionError, "truncation"):
            check_search(data, [3], limit=1, total=2)

    def detail(self):
        return {"schema_version": "knowledge_library_concept_v1",
                "concept": {"preferred_unit_id": 1},
                "preferred_unit": {"unit_id": 1}, "supporting_units": [],
                "non_supporting_members": [{"unit_id": 1, "in_current_extraction": False,
                                            "admission": "active"}],
                "current_relations": [], "historical_units": []}

    def test_historical_current_same_can_remain_preferred(self):
        check_detail(self.detail(), [], members=[1], preferred=1)

    def test_historical_member_cannot_be_support(self):
        data = self.detail()
        data["supporting_units"] = data.pop("non_supporting_members")
        data["non_supporting_members"] = []
        with self.assertRaisesRegex(AssertionError, "support qualification"):
            check_detail(data, [1], preferred=1)

    def test_duplicate_sections_are_rejected(self):
        data = self.detail()
        data["historical_units"] = [{"unit": copy.deepcopy(data["non_supporting_members"][0])}]
        with self.assertRaisesRegex(AssertionError, "exactly one"):
            check_detail(data, [], members=[1], historical=[1], preferred=1)


if __name__ == "__main__":
    unittest.main()
