"""Fixture-oracle tests only: these are not mocked Library UI tests."""
import copy
import unittest

from expectations import read_view, verify_view


def fixture():
    expected = {
        "concepts": {1: {"supporting_unit_ids": [10, 20], "preferred_unit_id": 10},
                     2: {"supporting_unit_ids": [], "preferred_unit_id": None}},
        "entries": {100: {"original_input": "source a", "original_context": "context a"},
                    200: {"original_input": "source b", "original_context": "context b"}},
        "selections": {
            100: {"entry_id": 100, "current_extraction_id": 11, "selection_mode": "automatic"},
            200: {"entry_id": 200, "current_extraction_id": 21, "selection_mode": "automatic"}},
        "extractions": {
            11: {"entry_id": 100, "source_analysis_id": 101, "source_feedback_id": None,
                 "units": {10: {"id": 10, "statement": "a"}}},
            21: {"entry_id": 200, "source_analysis_id": 201, "source_feedback_id": None,
                 "units": {20: {"id": 20, "statement": "b"}}}},
        "memberships": {10: 1, 20: 1}, "invalid": {10: False, 20: False},
        "history": {30: {"id": 30, "unit_id": 10, "concept_id": 1,
                         "relation": "same", "status": "accepted"}},
    }
    concepts = [
        {"id": 2, "lifecycle_state": "normal", "support_state": "orphaned",
         "state": "orphaned", "preferred_unit_id": None},
        {"id": 1, "lifecycle_state": "normal", "support_state": "supported",
         "state": "active", "preferred_unit_id": 10},
    ]
    view = {
        "catalog": concepts,
        "concepts": {c["id"]: {"concept": c, "links": []} for c in concepts},
        "entries": {eid: {"id": eid, **record} for eid, record in expected["entries"].items()},
        "selections": copy.deepcopy(expected["selections"]),
        "extractions": {
            xid: {"id": xid, **{k: v for k, v in source.items() if k != "units"},
                  "units": [{**u, "admission": {"effective_state": "active"}}
                            for u in source["units"].values()]}
            for xid, source in expected["extractions"].items()},
        "memberships": {uid: {"unit_id": uid, "current_membership": {"concept_id": cid}}
                        for uid, cid in expected["memberships"].items()},
        "invalid": {uid: {"unit_id": uid, "invalid": state} for uid, state in expected["invalid"].items()},
    }
    view["concepts"][1]["links"] = [copy.deepcopy(expected["history"][30])]
    return view, expected


class ExpectationsTests(unittest.TestCase):
    def test_two_sources_preferred_and_unsupported(self):
        verify_view(*fixture())

    def test_catalog_order(self):
        view, expected = fixture()
        view["catalog"].reverse()
        with self.assertRaisesRegex(AssertionError, "order/dedup"):
            verify_view(view, expected)

    def test_catalog_duplicates(self):
        view, expected = fixture()
        view["catalog"].append(view["catalog"][-1])
        with self.assertRaisesRegex(AssertionError, "order/dedup"):
            verify_view(view, expected)

    def test_catalog_detail_disagreement(self):
        view, expected = fixture()
        view["catalog"] = copy.deepcopy(view["catalog"])
        view["catalog"][0]["preferred_unit_id"] = 20
        with self.assertRaisesRegex(AssertionError, "catalog/detail"):
            verify_view(view, expected)

    def test_wrong_support_state(self):
        view, expected = fixture()
        view["concepts"][1]["concept"]["support_state"] = "orphaned"
        with self.assertRaisesRegex(AssertionError, "support state"):
            verify_view(view, expected)

    def test_stale_accepted_history_cannot_supply_support(self):
        view, expected = fixture()
        view["memberships"][10]["current_membership"] = None
        expected["memberships"][10] = None
        view["concepts"][1]["concept"]["preferred_unit_id"] = None
        expected["concepts"][1]["preferred_unit_id"] = None
        # Keeping the old accepted history row cannot make unit 10 supporting.
        with self.assertRaisesRegex(AssertionError, "supporting fixture units"):
            verify_view(view, expected)
        expected["concepts"][1]["supporting_unit_ids"] = [20]
        verify_view(view, expected)

    def test_historical_preferred_can_remain_without_support(self):
        view, expected = fixture()
        selection = {"entry_id": 100, "current_extraction_id": 99, "selection_mode": "pinned"}
        view["selections"][100] = selection
        expected["selections"][100] = copy.deepcopy(selection)
        expected["concepts"][1]["supporting_unit_ids"] = [20]
        verify_view(view, expected)  # Still preferred SAME, although not a current source.

    def test_invalid_cannot_have_membership(self):
        view, expected = fixture()
        view["invalid"][10]["invalid"] = True
        expected["invalid"][10] = True
        with self.assertRaisesRegex(AssertionError, "INVALID plus SAME"):
            verify_view(view, expected)

    def test_provenance_mismatch(self):
        view, expected = fixture()
        view["extractions"][11]["source_analysis_id"] = 999
        with self.assertRaisesRegex(AssertionError, "source_analysis_id"):
            verify_view(view, expected)

    def test_immutable_unit_mismatch(self):
        view, expected = fixture()
        view["extractions"][11]["units"][0]["statement"] = "rewritten"
        with self.assertRaisesRegex(AssertionError, "immutable statement"):
            verify_view(view, expected)

    def test_original_source_preserved(self):
        view, expected = fixture()
        view["entries"][100]["original_input"] = "rewritten"
        with self.assertRaisesRegex(AssertionError, "original_input"):
            verify_view(view, expected)

    def test_history_preserved(self):
        view, expected = fixture()
        view["concepts"][1]["links"][0]["status"] = "superseded"
        with self.assertRaisesRegex(AssertionError, "immutable history"):
            verify_view(view, expected)

    def test_reader_only_requests_existing_get_paths(self):
        view, expected = fixture()
        responses = {"/concepts": {"concepts": view["catalog"]}}
        for cid, payload in view["concepts"].items():
            responses[f"/concepts/{cid}"] = payload
        for eid, payload in view["entries"].items():
            responses[f"/entries/{eid}"] = payload
            responses[f"/entries/{eid}/current-extraction"] = view["selections"][eid]
        for xid, payload in view["extractions"].items():
            responses[f"/extractions/{xid}"] = payload
        for uid, payload in view["memberships"].items():
            responses[f"/knowledge-units/{uid}/concept-membership"] = payload
            responses[f"/knowledge-units/{uid}/invalid"] = view["invalid"][uid]
        calls = []

        def get(path):
            calls.append(path)
            return responses[path]

        self.assertEqual(read_view(get, expected), view)
        self.assertEqual(set(calls), set(responses))
        self.assertEqual(len(calls), len(responses))


if __name__ == "__main__":
    unittest.main()
