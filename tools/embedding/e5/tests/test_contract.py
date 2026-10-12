"""Contract flh_e5_role_prefix_v1: known representation/type pairs only,
prefix applied once to the original bytes. The golden inputs are the exact
strings the Go producers emit (checked on the Go side by
internal/application/semantic_search_envelope_test.go)."""

import json
import unittest
from pathlib import Path

from flh_e5 import contract

GOLDEN = json.loads((Path(__file__).resolve().parent / "golden_inputs.json").read_text(encoding="utf-8"))


class Accepted(unittest.TestCase):
    def test_golden_inputs_get_their_declared_role_and_prefix_once(self):
        self.assertEqual(GOLDEN["convention"], contract.CONVENTION)
        for case in GOLDEN["accepted"]:
            with self.subTest(case["name"]):
                a = contract.adapt(case["input"])
                self.assertEqual(a.role, case["role"])
                self.assertEqual(a.model_text, case["model_text"])
                prefix = {"query": b"query: ", "passage": b"passage: "}[case["role"]]
                self.assertEqual(a.model_text.encode("utf-8"), prefix + case["input"].encode("utf-8"))
                # Exactly one prefix: what follows it is the untouched input,
                # which itself starts with "{" (never with a prefix).
                self.assertEqual(a.model_text[len(prefix):], case["input"])
                self.assertTrue(case["input"].startswith("{"))

    def test_role_comes_from_content_not_position(self):
        by_name = {c["name"]: c for c in GOLDEN["accepted"]}
        concept, query = by_name["concept_document"]["input"], by_name["search_query"]["input"]
        for batch in ([concept], [query], [concept, query], [query, concept, concept]):
            roles = [contract.adapt(t).role for t in batch]
            self.assertEqual(roles, ["passage" if t == concept else "query" for t in batch])

    def test_raw_json_query_ambiguity_is_resolved_by_the_envelope(self):
        # The same Concept-document JSON is a passage when sent bare (indexing)
        # and a query when the search wraps it; the service never guesses.
        by_name = {c["name"]: c for c in GOLDEN["accepted"]}
        bare = by_name["unwrapped_concept_json_is_a_document"]
        wrapped = by_name["search_query_that_looks_like_a_concept_document"]
        self.assertEqual(json.loads(wrapped["input"])["text"], bare["input"])
        self.assertEqual(contract.adapt(bare["input"]).role, "passage")
        self.assertEqual(contract.adapt(wrapped["input"]).role, "query")
        self.assertTrue(contract.adapt(wrapped["input"]).model_text.startswith('query: {"representation":"concept_search_query_v2"'))


class Rejected(unittest.TestCase):
    def test_golden_rejections(self):
        for case in GOLDEN["rejected"]:
            with self.subTest(case["name"]):
                with self.assertRaises(contract.InputRejected) as cm:
                    contract.adapt(case["input"])
                self.assertNotIn("subjonctif", str(cm.exception))

    def test_model_text_is_never_accepted_again(self):
        for case in GOLDEN["accepted"]:
            with self.assertRaises(contract.InputRejected):
                contract.adapt(case["model_text"])

    def test_non_strings_and_deep_nesting(self):
        for value in (None, 5, b"{}", ["x"]):
            with self.assertRaises(contract.InputRejected):
                contract.adapt(value)
        with self.assertRaises(contract.InputRejected):
            contract.adapt("{" + '"a":[' * 5000 + "]" * 5000 + "}")

    def test_messages_never_contain_input_text(self):
        marker = "SECRET-LEARNER-TEXT"
        for text in (marker, '{"representation":"x","type":"query","text":"%s"}' % marker,
                     '{"representation":"concept_search_query_v2","type":"query","text":"%s","x":1}' % marker):
            with self.assertRaises(contract.InputRejected) as cm:
                contract.adapt(text)
            self.assertNotIn(marker, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
