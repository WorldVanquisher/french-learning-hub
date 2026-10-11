"""Offline adversarial fixture checks; no provider, application, or database."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import validate as validator

HERE = Path(__file__).resolve().parent


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = validator.load(HERE / "fixture.json")

    def test_shipped_fixture_inventory_and_frozen_groups(self):
        report = validator.validate(self.fixture)
        self.assertEqual(report["counts"], {"groups": 14, "concepts": 24, "queries": 56, "judgments": 56})
        self.assertEqual(report["buckets"], {"single_target": 48, "ambiguous": 4, "no_match": 4})
        self.assertEqual([g["id"] for g in self.fixture["groups"] if g["split"] == "held_out"], ["F09", "F10", "F11", "F12", "F13", "F14"])
        self.assertEqual(report["splits"]["held_out"]["single_target"], 16)

    def invalid(self, change):
        data = deepcopy(self.fixture)
        change(data)
        with self.assertRaises(validator.ValidationError):
            validator.validate(data)

    def test_duplicate_concept_id(self):
        self.invalid(lambda d: d["concepts"][1].update(id="C001"))

    def test_duplicate_identity(self):
        self.invalid(lambda d: d["concepts"][1].update(identity=deepcopy(d["concepts"][0]["identity"])))

    def test_duplicate_query_wording(self):
        self.invalid(lambda d: d["queries"][1].update(free_text="  " + d["queries"][0]["free_text"].upper() + "  "))

    def test_duplicate_unit_evidence(self):
        self.invalid(lambda d: d["queries"][1].update(unit_evidence=deepcopy(d["queries"][0]["unit_evidence"])))

    def test_unknown_relevance_reference(self):
        self.invalid(lambda d: d["judgments"][0].update(proposed_relevant_concept_ids=["C999"]))

    def test_unknown_negative_reference(self):
        self.invalid(lambda d: d["judgments"][0]["hard_negatives"][0].update(concept_id="C999"))

    def test_missing_judgment(self):
        self.invalid(lambda d: d["judgments"].pop())

    def test_duplicate_judgment_query(self):
        self.invalid(lambda d: d["judgments"][1].update(query_id="Q001"))

    def test_unknown_group(self):
        self.invalid(lambda d: d["queries"][0].update(group_id="F99"))

    def test_query_split_crosses_family(self):
        self.invalid(lambda d: d["queries"][0].update(split="held_out"))

    def test_cross_family_positive(self):
        self.invalid(lambda d: d["judgments"][0].update(proposed_relevant_concept_ids=["C017"]))

    def test_cross_family_negative(self):
        self.invalid(lambda d: d["judgments"][0]["hard_negatives"][0].update(concept_id="C017"))

    def test_no_match_cannot_be_positive(self):
        self.invalid(lambda d: d["judgments"][52].update(proposed_relevant_concept_ids=["C001"]))

    def test_ambiguous_cannot_be_scored_as_single_positive(self):
        self.invalid(lambda d: d["judgments"][48].update(proposed_relevant_concept_ids=["C001"], possible_concept_ids=[]))

    def test_positive_cannot_have_multiple_targets(self):
        self.invalid(lambda d: d["judgments"][0].update(proposed_relevant_concept_ids=["C001", "C002"]))

    def test_contradictory_negative(self):
        self.invalid(lambda d: d["judgments"][0]["hard_negatives"][0].update(concept_id="C001"))

    def test_cannot_declare_human_ground_truth(self):
        self.invalid(lambda d: d.update(label_status="human_ground_truth"))

    def test_cannot_self_approve_a_judgment(self):
        self.invalid(lambda d: d["judgments"][0].update(review_status="approved"))

    def test_leakage_fields_in_unit_input(self):
        for key in sorted(validator.PROHIBITED):
            with self.subTest(key=key):
                self.invalid(lambda d, key=key: d["queries"][0]["unit_evidence"].update({key: "hidden truth"}))

    def test_leakage_fields_in_identity_features(self):
        for key in ("target_concept_id", "signature", "relevance", "group_id", "rank"):
            with self.subTest(key=key):
                self.invalid(lambda d, key=key: d["concepts"][0]["identity"]["identity_features"].update({key: "hidden truth"}))

    def test_ids_in_text(self):
        self.invalid(lambda d: d["queries"][0].update(free_text="Please return C001"))

    def test_serialized_labels_in_text(self):
        self.invalid(lambda d: d["queries"][0]["unit_evidence"].update(statement='{"target_concept_id": "answer"}'))

    def test_full_identity_copy(self):
        self.invalid(lambda d: d["queries"][0].update(free_text=" ".join([d["concepts"][0]["identity"]["target"], d["concepts"][0]["identity"]["scope"], *d["concepts"][0]["identity"]["identity_features"].values()])))

    def test_missing_bilingual_case(self):
        self.invalid(lambda d: d["queries"][1].update(language="fr"))

    def test_too_small_corpus(self):
        self.invalid(lambda d: d.update(concepts=d["concepts"][:19]))

    def test_unknown_input_field(self):
        self.invalid(lambda d: d["queries"][0]["unit_evidence"].update(extra_prompt="secret label"))

    def test_non_string_example(self):
        self.invalid(lambda d: d["queries"][0]["unit_evidence"].update(example=42))

    def test_hashes_are_repeatable_and_track_edits(self):
        original = validator.validate(self.fixture)["canonical_sha256"]
        self.assertEqual(original, validator.validate(deepcopy(self.fixture))["canonical_sha256"])
        data = deepcopy(self.fixture)
        data["queries"][0]["unit_evidence"]["statement"] += " Merci."
        changed = validator.validate(data)["canonical_sha256"]
        self.assertNotEqual(original["queries"], changed["queries"])
        self.assertEqual(original["judgments"], changed["judgments"])

    def test_cli_success_without_outputs_or_network(self):
        result = subprocess.run([sys.executable, "-B", str(HERE / "validate.py")], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["counts"]["queries"], 56)

    def test_cli_failure_nonzero_and_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory(prefix="flh045-selftest-") as tmp:
            path = Path(tmp) / "invalid.json"
            for content in ('{"schema_version":"a","schema_version":"b"}', '{"x":NaN}', '{bad json', '{}'):
                with self.subTest(content=content):
                    path.write_text(content, encoding="utf-8")
                    result = subprocess.run([sys.executable, "-B", str(HERE / "validate.py"), str(path)], capture_output=True, text=True, check=False)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("INVALID:", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_cli_missing_file(self):
        with tempfile.TemporaryDirectory(prefix="flh045-selftest-") as tmp:
            result = subprocess.run([sys.executable, "-B", str(HERE / "validate.py"), str(Path(tmp) / "absent.json")], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("INVALID:", result.stderr)


if __name__ == "__main__":
    unittest.main()
