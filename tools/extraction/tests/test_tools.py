"""Standard-library tests for the extraction dataset tools.

  cd tools/extraction && python3 -B -m unittest discover -s tests -t .
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "authoring"))

from flh_extraction import evaluate, manifest, records, sft, splits  # noqa: E402
from flh_extraction.dedup import exact_groups, near_pairs  # noqa: E402


def unit(canonical, statement, zh=None, kind="grammar", example=None):
    return {"kind": kind, "canonical": canonical, "statement": statement, "statement_zh": zh or "中文陈述 " + canonical,
            "example": example, "confidence": 0.9}


def rec(rid, text, units, split="train", family=None, points=None, ctx=""):
    return {"schema": "flh_extraction_candidate_v1", "id": rid,
            "input": {"entry_id": 0, "original_input": text, "original_context": ctx, "effective_category": "grammar",
                      "effective_explanation": "", "resolution": "accepted"},
            "expected": {"units": units},
            "meta": {"family_id": family or rid, "split_group": split, "points": points or [], "origin": "synthetic",
                     "review_status": "unreviewed", "label_status": "machine_authored_unreviewed", "case_type": "single",
                     "rationale": "r"}}


AUX = unit("aller — passé composé avec être", "« Aller » forms the passé composé with « être ».",
           "« aller » 用 « être » 构成复合过去时。", example="Je suis allé au marché.")
AGR = unit("accord en nombre du nom et de l'adjectif", "In the plural both the noun and its adjective take the plural mark.",
           "复数时名词和形容词都要加复数标记。")


class RecordChecks(unittest.TestCase):
    def test_honest_statuses_and_contract_fields(self):
        r = rec("a", "texte", [AUX])
        self.assertEqual(records.structural_errors(r), [])
        bad = json.loads(json.dumps(r))
        bad["meta"]["label_status"] = "gold"
        self.assertTrue(records.structural_errors(bad))
        bad = json.loads(json.dumps(r))
        bad["expected"]["units"][0]["statement_zh"] = " "
        self.assertTrue(records.structural_errors(bad))
        bad = json.loads(json.dumps(r))
        bad["input"]["topic"] = "leak"
        self.assertTrue(records.structural_errors(bad))

    def test_the_generated_datasets_pass(self):
        for path in ("boundary_a", "boundary_b"):
            mod = __import__(path)
            self.assertEqual(len(mod.CASES), 40)


class Duplicates(unittest.TestCase):
    def test_exact_and_near(self):
        a = rec("a", "Pourquoi on dit « je suis allé » et pas « j'ai allé » au passé ?", [AUX])
        b = rec("b", "Pourquoi on dit « je suis allé » et pas « j'ai allé » au passé ?", [AUX])
        c = rec("c", "Pourquoi on dit « je suis allé » et pas « j'ai allé » au passé ? Merci d'avance.", [AUX])
        d = rec("d", "Quelle heure est-il à Paris ?", [])
        self.assertEqual(exact_groups([a, b, d]), [["a", "b"]])
        self.assertTrue(any({x, y} == {"a", "c"} for x, y, _ in near_pairs([a, c, d], 0.3)))
        self.assertFalse(any("d" in (x, y) for x, y, _ in near_pairs([a, c, d], 0.3)))


class Splits(unittest.TestCase):
    def test_leaks_are_reported(self):
        train = [rec("ext-trn-1", "un texte d'entraînement", [AUX], points=["p1"]),
                 rec("ext-trn-2", "un autre texte", [AUX], split="dev", points=["p1"])]
        evals = [rec("ext-evl-1", "un texte d'évaluation séparé", [AUX], split="eval", points=["p1"], family="ext-trn-1")]
        rep = splits.check(train, evals)
        self.assertFalse(rep["pass"])
        self.assertEqual(rep["points_in_train_and_dev"], ["p1"])
        self.assertEqual(rep["points_in_train_and_eval"], ["p1"])
        self.assertEqual(rep["canonical_overlap_train_eval"], [AUX["canonical"]])
        self.assertEqual(rep["families_in_two_splits"], ["ext-trn-1"])


class Evaluation(unittest.TestCase):
    def judge(self, ref, pred):
        return evaluate.judge_example(ref, pred)[0]

    def test_valid_rewording_matches_without_exact_output(self):
        pred = [unit("aller + être au passé composé", "The verb « aller » takes « être » in the passé composé.",
                     "« aller » 在复合过去时中用 « être »。")]
        self.assertEqual(dict(self.judge([AUX], pred)), {})

    def test_missed_unsupported_duplicate_merged_and_abstention(self):
        other = unit("le subjonctif après « il faut que »", "« Il faut que » takes the subjunctive.", "« il faut que » 后用虚拟式。")
        self.assertEqual(self.judge([AUX, AGR], [AUX])["MISSED"], 1)
        self.assertEqual(self.judge([AUX], [AUX, other])["UNSUPPORTED"], 1)
        dup = dict(AUX, canonical=AUX["canonical"])
        self.assertEqual(self.judge([AUX], [AUX, dup])["DUPLICATE"], 1)
        merged = unit("aller avec être et accord en nombre du nom et de l'adjectif",
                      "« Aller » takes « être », and the noun and its adjective take the plural mark.", "合并的陈述。")
        errs = self.judge([AUX, AGR], [merged])
        # The matched merged unit also covers the second reference: MERGED, not MISSED.
        self.assertEqual((errs["MERGED"], errs["MISSED"]), (1, 0))
        self.assertEqual(self.judge([], [AUX])["ABSTENTION_FAIL"], 1)
        self.assertEqual(dict(self.judge([], [])), {})

    def test_bilingual_checks(self):
        self.assertEqual(evaluate.bilingual_issues(AUX), [])
        self.assertIn("french_forms_missing_in_zh", evaluate.bilingual_issues(dict(AUX, statement_zh="这个用法需要注意。")))
        self.assertIn("no_chinese_text", evaluate.bilingual_issues(dict(AUX, statement_zh="Same in English.")))

    def test_report_marks_automatic_semantics_provisional_and_counts_invalid_outputs(self):
        refs = [rec("a", "x", [AUX]), rec("b", "y", [])]
        results = [{"id": "a", "valid": False, "error_class": "invalid_output", "units": []},
                   {"id": "b", "valid": True, "units": []}]
        rep = evaluate.evaluate(refs, results)
        self.assertTrue(rep["provisional"])
        self.assertEqual(rep["structural_validity"], 0.5)
        self.assertEqual(rep["errors"]["STRUCT_INVALID"], 1)
        self.assertEqual(rep["abstention"]["correct_empty"], 1)

    def test_human_judgments_override_the_matcher(self):
        refs = [rec("a", "x", [AUX])]
        results = [{"id": "a", "valid": True, "units": [unit("autre chose", "Unrelated wording.", "无关。")]}]
        human = {"a": [{"id": "a", "pred": 0, "ref": 0, "label": "same", "supported": True, "bilingual_ok": True}]}
        rep = evaluate.evaluate(refs, results, human)
        self.assertFalse(rep["provisional"])
        self.assertEqual(rep["unit_recall"], 1.0)


class SFT(unittest.TestCase):
    def test_only_train_and_dev_and_exact_prompts(self):
        cands = [rec("t", "x", [AUX]), rec("d", "y", [], split="dev"), rec("e", "z", [AUX], split="eval")]
        q = rec("q", "w", [AUX])
        q["meta"]["quarantine_reason"] = "ambiguous"
        rendered = [{"id": i, "developer": "DEV", "user": f"USER {i}"} for i in ("t", "d", "e", "q")]
        rows, refused = sft.build(cands + [q], rendered)
        self.assertEqual([r["id"] for r in rows], ["t", "d"])
        self.assertEqual(sorted(refused), ["e", "q"])
        self.assertEqual(rows[0]["messages"][0]["content"], "DEV")
        target = json.loads(rows[0]["messages"][2]["content"])
        self.assertEqual(list(target["units"][0]), ["kind", "canonical", "statement", "statement_zh", "example", "confidence"])
        prompts = sft.eval_prompts(cands, rendered)
        self.assertEqual([p["id"] for p in prompts], ["e"])
        self.assertEqual([m["role"] for m in prompts[0]["messages"]], ["system", "user"])


class Manifest(unittest.TestCase):
    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.jsonl"
            p.write_text('{"id": 1}\n{"id": 2}\n')
            a, b = manifest.build({"a": p}), manifest.build({"a": p})
            self.assertEqual(a, b)
            self.assertEqual(a["files"]["a"]["records"], 2)


if __name__ == "__main__":
    unittest.main()
