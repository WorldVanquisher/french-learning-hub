"""Standard-library tests for the failure-mode audit, the training increment,
the quality report, the production-input probe, the controlled failures and
the review packet.

  cd tools/extraction && python3 -B -m unittest discover -s tests -t tests
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "authoring"))

from flh_extraction import audit, controls, increment, probe, quality, records, review_packet, sft  # noqa: E402
from flh_extraction.textnorm import norm  # noqa: E402

RB = 'Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).'


def unit(canonical, statement, zh=None, kind="grammar", example=None):
    return {"kind": kind, "canonical": canonical, "statement": statement, "statement_zh": zh or "中文 " + statement,
            "example": example, "confidence": 0.9}


def rec(rid, text, units, cat="grammar", split="train", points=None, case="single", expl="", res="accepted", ctx=""):
    return {"schema": "flh_extraction_candidate_v1", "id": rid,
            "input": {"entry_id": 0, "original_input": text, "original_context": ctx, "effective_category": cat,
                      "effective_explanation": expl, "resolution": res},
            "expected": {"units": units},
            "meta": {"family_id": rid, "split_group": split, "points": points or [], "origin": "synthetic",
                     "review_status": "unreviewed", "label_status": "machine_authored_unreviewed", "case_type": case,
                     "style": case, "rationale": "r"}}


NEG = unit("ne… jamais", "« Ne… jamais » means « never »: « je ne fume jamais ».", "« ne… jamais » 表示“从不”：« je ne fume jamais »。",
           example="Il ne mange jamais de viande.")
GEN = unit("noms en -tion féminins", "Nouns ending in « -tion » are feminine: « la question ».", "以 « -tion » 结尾的名词是阴性：« la question »。",
           kind="morphology")


def py_validate(rows):
    """Stand-in for `extraction-render validate` in tests: json.loads of the
    whole text and the contract's field checks (the real tool is Go)."""
    out = []
    for r in rows:
        res = {"id": r["id"], "valid": False, "units": []}
        try:
            payload = json.loads(r["output_text"])
        except json.JSONDecodeError:
            res["error_class"] = "unparseable_output"
            out.append(res)
            continue
        units = payload.get("units") if isinstance(payload, dict) else None
        keys = [(u.get("kind"), norm(u.get("canonical", "")), u.get("statement"), u.get("example")) for u in units or []]
        ok = isinstance(units, list) and all(
            u.get("kind") in records.KINDS and (u.get("statement_zh") or "").strip() and u.get("canonical", "").strip()
            and 0 <= u.get("confidence", -1) <= 1 for u in units) and len(set(keys)) == len(keys)
        if ok:
            res.update(valid=True, units=units)
        else:
            res["error_class"] = "invalid_output"
        out.append(res)
    return out


class Audit(unittest.TestCase):
    def test_moves_are_one_edit_and_two_corrections_are_two(self):
        self.assertEqual(audit.edit_regions("Je jamais fume.", "Je ne fume jamais."), 1)
        self.assertEqual(audit.edit_regions("Je n'ai vu rien.", "Je n'ai rien vu."), 1)
        self.assertEqual(audit.edit_regions("Elle est une acteuse célèbre.", "C'est une actrice célèbre."), 2)

    def test_bilingual_findings(self):
        self.assertEqual(audit.bilingual_findings(NEG), [])
        drift = dict(NEG, statement_zh="这个用法需要注意。")
        self.assertIn("french_forms_missing_in_zh", " ".join(audit.bilingual_findings(drift)))
        placeholder = unit("pronoms COI", "Verbs with « à + person » take « lui ».", "带 « à + 人 » 的动词用 « lui »。")
        self.assertEqual(audit.bilingual_findings(placeholder), [])
        gloss = unit("en avoir marre", "« J'en ai marre » means « I'm fed up ».", "« j'en ai marre » 意为“我受够了”。")
        self.assertEqual(audit.bilingual_findings(gloss), [])

    def test_category_shortcut_and_coverage_are_reported(self):
        train = [rec("t1", "Merci !", [], cat="other", case="zero_unit"),
                 rec("t2", "« Je jamais fume » ?", [NEG], case="single"),
                 rec("t3", "Pour moi « jamais » remplace « ne ».", [NEG], case="false_premise")]
        rep = audit.audit(train, [rec("e1", "Merci beaucoup", [], cat="other", split="eval")])
        z = rep["no_learning_objective"]["category_vs_label"]
        self.assertEqual(z["train"], {"other/zero": 1, "other/units": 0, "not_other/zero": 0, "not_other/units": 2})
        self.assertEqual(rep["false_premises"]["train_records_teaching_a_misconception"], 1)
        rows = {r["mode"]: r for r in rep["summary"]}
        self.assertEqual(rows["no_learning_objective"]["severity"], "high")
        self.assertEqual(rows["over_splitting"]["coverage"], 0)
        self.assertIn("HEURISTIC", audit.markdown(rep))

    def test_anchor_is_lenient_but_flags_unrelated_units(self):
        r = rec("a", "Quand est-ce qu'on met « du » ou « de la » ?", [])
        u = unit("articles partitifs (du, de la, de l')", "French uses « du, de la » for an amount.")
        self.assertTrue(audit.is_anchored(norm(audit.learner_text(r)), audit.anchor_terms(u)))
        self.assertFalse(audit.is_anchored(norm(audit.learner_text(r)), audit.anchor_terms(GEN)))


class Increment(unittest.TestCase):
    def test_generator_is_deterministic_and_honest(self):
        import generate_increment
        a, b = generate_increment.build(), generate_increment.build()
        self.assertEqual(a, b)
        self.assertGreaterEqual(len(a), 150)
        for r in a:
            self.assertEqual(records.structural_errors(r), [], r["id"])
            self.assertEqual(r["meta"]["label_status"], "machine_authored_unreviewed")
            self.assertTrue(r["id"].startswith("ext-trn-i2-"))
            for p in r["meta"]["points"]:
                self.assertEqual(generate_increment.split_group(p), r["meta"]["split_group"])
        modes = {r["meta"]["style"] for r in a}
        self.assertTrue({"misconception", "wrong_explanation", "zero_production_cues", "counter_shortcut",
                         "fragmentation", "two_errors"} <= modes)
        zero = [r for r in a if not r["expected"]["units"]]
        self.assertTrue(zero and all(r["input"]["effective_category"] != "other" for r in zero))
        rb = [r for r in a if r["meta"]["explanation_source"] == generate_increment.ANALYZER]
        self.assertTrue(rb and all(r["input"]["effective_explanation"].startswith("Local classification selected") for r in rb))

    def test_check_refuses_new_points_eval_points_and_split_crossing(self):
        base = [rec("ext-trn-1", "un texte de base assez long pour les shingles", [NEG], points=["p1"])]
        evals = [rec("ext-evl-1", "un texte d'évaluation tout à fait différent", [GEN], split="eval", points=["e1"])]
        good = [rec("ext-trn-i2-1", "Pour moi « jamais » remplace « ne » dans une phrase.", [NEG], points=["p1"])]
        self.assertTrue(increment.check(base, good, evals)["pass"])
        for bad in ([rec("ext-trn-i2-2", "texte neuf", [NEG], points=["p9"])],
                    [rec("ext-trn-i2-3", "texte neuf", [GEN], points=["e1"])],
                    [rec("ext-trn-i2-4", "texte neuf", [NEG], points=["p1"], split="dev")]):
            self.assertFalse(increment.check(base, bad, evals)["pass"])
        v = [{"id": "ext-trn-i2-1", "valid": False, "units": []}]
        self.assertFalse(increment.check(base, good, evals, validated=v)["pass"])


class Quality(unittest.TestCase):
    def test_parse_diagnostics(self):
        d = quality.parse_diagnostic
        self.assertEqual(d('{"units":[]}'), "parses")
        self.assertEqual(d("```json\n{}\n```"), "code_fence")
        self.assertEqual(d("<think>\n\n</think>\n\n{}"), "think_block")
        self.assertEqual(d('{"units":[{"kind":"gram'), "truncated_json")
        self.assertEqual(d('{"units":[]} merci'), "trailing_text")
        self.assertEqual(d("Voici :"), "leading_text")
        self.assertEqual(d('{"units":[}'), "malformed_json")
        self.assertEqual(d('{"units":[', {"stopped": "max_new_tokens"}), "truncated_at_max_new_tokens")
        self.assertEqual(d(""), "empty")

    def test_exact_sections_and_bases_stay_apart(self):
        refs = [rec("a", "« Je jamais fume » ?", [NEG]), rec("b", "Merci !", [], cat="other"),
                rec("c", "« le solution » ?", [GEN]), rec("d", "Thanks", [], cat="other")]
        res = [{"id": "a", "valid": True, "units": [NEG, GEN]}, {"id": "b", "valid": True, "units": [GEN]},
               {"id": "c", "valid": True, "units": []}, {"id": "d", "valid": False, "error_class": "unparseable_output", "units": []}]
        human = {"a": [{"id": "a", "pred": 0, "ref": 0, "label": "same", "supported": True, "bilingual_ok": True},
                       {"id": "a", "pred": 1, "ref": 0, "label": "none", "supported": False}]}
        rep = quality.report(refs, res, human, [{"id": "d", "output_text": "<think></think>{}"}])
        self.assertEqual(rep["structural"]["valid"], 3)
        self.assertEqual(rep["structural"]["parse_diagnostics_of_invalid"], {"think_block": 1})
        self.assertEqual(rep["unit_count"]["over_count_examples"], 2)
        self.assertEqual(rep["unit_count"]["under_count_examples"], 1)
        self.assertEqual(rep["abstention"]["false_extraction_on_zero_refs"], 1)
        self.assertEqual(rep["abstention"]["zero_refs_invalid_output"], 1)
        self.assertEqual(rep["abstention"]["unit_refs_answered_empty"], 1)
        self.assertEqual(rep["semantic"]["human"]["examples"], 1)
        self.assertEqual(rep["semantic"]["heuristic"]["examples"], 2)
        self.assertEqual(rep["grounding"]["human"]["unsupported"], 1)
        self.assertTrue(all(b in ("exact", "heuristic") for _, b in rep["headline"].values()))
        self.assertIn("never added together", quality.markdown(rep, "t"))
        cmp_ = quality.compare(rep, rep)
        self.assertTrue(all(v["delta"] in (0, 0.0, None) for v in cmp_.values()))


class ProbeAndControls(unittest.TestCase):
    def setUp(self):
        self.refs = [rec("ext-evl-1", "« Je jamais fume » : c'est faux ?", [NEG], split="eval"),
                     rec("ext-evl-2", "Bon, à jeudi !", [], cat="other", split="eval", case="zero"),
                     rec("ext-evl-3", "« La question », « la nation » : pourquoi « la » ?", [GEN, NEG], split="eval", case="multi_2"),
                     rec("ext-evl-4", "Merci pour tout.", [], cat="other", split="eval", case="zero"),
                     rec("ext-evl-5", "« Le solution » ou « la solution » ?", [GEN], split="eval", res="corrected")]
        self.an = [{"id": r["id"], "analyzer": "rule-based:v2:fr_l2_taxonomy_v1", "effective_category": "grammar",
                    "effective_explanation": RB} for r in self.refs]

    def test_probe_variants_keep_references_and_stay_out_of_training(self):
        rb = probe.build(self.refs, self.an, "rb")
        self.assertEqual([r["expected"] for r in rb], [r["expected"] for r in self.refs])
        self.assertEqual(rb[4]["input"]["resolution"], "corrected")
        self.assertTrue(all(r["input"]["resolution"] == "unreviewed" for r in rb[:4]))
        sw = probe.build(self.refs, self.an, "swap")
        s = probe.summary(sw)
        self.assertEqual((s["category_other_on_zero_refs"], s["category_other_on_unit_refs"]), (0, 3))
        rendered = [{"id": r["id"], "developer": "d", "user": "u"} for r in sw]
        rows, refused = sft.build(sw, rendered)
        self.assertEqual((rows, len(refused)), ([], 5))
        with self.assertRaises(ValueError):
            probe.build(self.refs, self.an[:1], "rb")

    def test_control_matrix_catches_targets_and_admits_its_limits(self):
        m = controls.matrix(self.refs, py_validate)
        for c, row in m.items():
            if row["targets"]:
                self.assertTrue(row["caught"], (c, row))
        self.assertEqual(m["false_claim"]["moved"], {})
        self.assertEqual(m["category_shortcut"]["moved"], {})
        self.assertEqual(m["struct_think_block"]["parse_diagnostics"], {"think_block": 5})
        sw = probe.build(self.refs, self.an, "swap")
        pm = controls.matrix(sw, py_validate, {"oracle": [], **controls.PROBE_TARGETS})
        self.assertTrue(pm["category_shortcut"]["caught"])
        self.assertIn("NOT CAUGHT", controls.markdown(m, "t", pm))


class Packet(unittest.TestCase):
    def test_packet_from_the_generated_data(self):
        import generate_eval
        import generate_increment
        import generate_train
        gen = generate_train.build()
        with tempfile.TemporaryDirectory() as d:
            kept, _ = generate_train.finalize(gen, Path(d))
            with contextlib.redirect_stdout(io.StringIO()):
                generate_eval.main(Path(d) / "eval")
            evals = records.load_jsonl(Path(d) / "eval" / "eval_candidates.jsonl")
        an = [{"id": r["id"], "analyzer": "rule-based:v2:fr_l2_taxonomy_v1", "effective_category": "grammar",
               "effective_explanation": RB} for r in evals]
        items = review_packet.build(kept, generate_increment.build(), probe.build(evals, an, "rb"))
        self.assertEqual(len(items), 25)
        self.assertEqual(sorted({i["priority"] for i in items}), [1, 2, 3, 4, 5])
        self.assertTrue(all(i["verdict"] is None and i["label_status"] == "machine_authored_unreviewed" for i in items))
        self.assertEqual(len({i["id"] for i in items}), 25)
        self.assertIn("unreviewed", review_packet.markdown(items))


if __name__ == "__main__":
    unittest.main()
