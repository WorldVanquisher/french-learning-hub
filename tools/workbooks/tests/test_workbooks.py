"""Stdlib tests for tools/workbooks (run from tools/workbooks:
python3 -m unittest discover -s tests)."""

import json
import random
import re
import unittest

from flh_workbooks import adapters, model, quality, render, scan
from flh_workbooks.__main__ import gates, outputs


class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc, cls.files = outputs()

    def test_committed_files_equal_a_fresh_build(self):
        for path, text in self.files.items():
            self.assertEqual(path.read_text(encoding="utf-8"), text, f"{path.name} is stale: run build")

    def test_gates_pass(self):
        errs, _, stats = gates()
        self.assertEqual(errs, [])
        self.assertEqual(stats["questions"], 240)

    def test_labels(self):
        st = self.doc["status"]
        self.assertTrue(st["synthetic"])
        self.assertFalse(st["human_reviewed"])
        self.assertEqual(st["review_state"], "unreviewed")
        self.assertFalse(self.doc["provenance"]["generated_by_provider"])
        for u in self.doc["units"]:
            self.assertIsNone(u["listening"]["audio"])
            self.assertEqual(u["listening"]["format"], "script")
            self.assertNotIn("start", json.dumps(u["listening"]["turns"]))

    def test_one_correct_option_and_answer_key_agree(self):
        for q in model.all_questions(self.doc):
            if q["type"] == "single_choice":
                correct = [o["key"] for o in q["options"] if o["correct"]]
                self.assertEqual(correct, [q["answer"]], q["id"])

    def test_positions_balanced_without_long_runs(self):
        st = model.position_stats(model.all_questions(self.doc))
        self.assertLessEqual(st["max_run"], model.MAX_RUN)
        self.assertLessEqual(max(st["counts"].values()) - min(st["counts"].values()), 2)

    def test_run_repair(self):
        qs = [{"id": f"q{i}", "distractors": [{}, {}]} for i in range(60)]
        pos = model.assign_positions(qs, random.Random(1))
        seq = [pos[q["id"]] for q in qs]
        runs = max(len(m.group(0)) for m in re.finditer(r"(.)\1*", "".join(map(str, seq))))
        self.assertLessEqual(runs, model.MAX_RUN)
        self.assertEqual(sorted(set(seq)), [0, 1, 2])


class Student(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(model.RL_PATH.read_text(encoding="utf-8"))

    def test_student_html_has_no_key(self):
        self.assertEqual(scan.scan_html(render.rl_html(self.doc, False), self.doc), [])

    def test_scanner_detects_teacher_edition(self):
        found = scan.scan_html(render.rl_html(self.doc, True), self.doc, "teacher")
        self.assertTrue(any("explanation_en" in f for f in found))
        self.assertTrue(any("teacher class" in f for f in found))

    def test_scanner_detects_hidden_markup(self):
        html = render.rl_html(self.doc, False).replace("<body>", '<body><div data-answer="B"></div><!-- key -->', 1)
        found = scan.scan_html(html, self.doc)
        self.assertIn("student.html: data attribute", found)
        self.assertIn("student.html: HTML comment", found)

    def test_student_markdown_has_no_key(self):
        md = render.rl_markdown(self.doc, False)
        self.assertNotIn("✓", md)
        self.assertEqual(scan.scan_text(md, self.doc, "md"), [])


class Adapters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(model.RL_PATH.read_text(encoding="utf-8"))

    def test_pack_items_follow_the_authored_rules(self):
        pack = adapters.reading_pack(self.doc)
        self.assertEqual(pack["schema_version"], "flh_reading_pack_v1")
        for p in pack["passages"]:
            kinds = [q["kind"] for q in p["questions"]]
            self.assertTrue(2 <= len(kinds) <= 5, p["id"])
            self.assertEqual(kinds.count("main_idea"), 1)
            self.assertGreaterEqual(kinds.count("detail"), 1)
            self.assertLessEqual(kinds.count("inference"), 1)
            texts = {s["id"]: s["text"] for s in p["segments"]}
            for q in p["questions"]:
                self.assertTrue(1 <= len(q["wrong_answers"]) <= 4)
                for e in q["evidence"]:
                    self.assertEqual(texts[e["segment"]].count(e["excerpt"]), 1)

    def test_listening_script_pack_keeps_every_question_and_invents_nothing(self):
        pack = adapters.listening_script_pack(self.doc)
        self.assertEqual(pack["schema_version"], "flh_listening_script_pack_v1")
        self.assertEqual(len(pack["scripts"]), 12)
        raw = json.dumps(pack, ensure_ascii=False)
        for banned in ("http", "youtu", '"audio"', '"video_id"', '"source_url"', '"start_seconds"'):
            self.assertNotIn(banned, raw)
        for s, u in zip(pack["scripts"], self.doc["units"]):
            turns = u["listening"]["turns"]
            self.assertEqual([(x["id"], x["text"]) for x in s["lines"]], [(t["id"], t["text"]) for t in turns])
            self.assertEqual([q["id"] for q in s["questions"]], [q["id"] for q in u["listening"]["questions"]])
            for q, src in zip(s["questions"], u["listening"]["questions"]):
                if src["type"] == "single_choice":
                    self.assertEqual(q["choices"], [o["text"] for o in src["options"]])
                    self.assertEqual(q["expected_answer"], next(o["text"] for o in src["options"] if o["correct"]))
                    self.assertEqual(len(q["wrong_answers"]), len(src["options"]) - 1)
                else:
                    self.assertNotIn("choices", q)
                for e in q["evidence"]:
                    self.assertIn(e["segment"], q["segments"])
                    self.assertEqual(s["lines"][e["segment"] - 1]["text"].count(e["excerpt"]), 1)
            for a in s["annotations"]:
                self.assertEqual(s["lines"][a["segment"] - 1]["text"].count(a["excerpt"]), 1)

    def test_lesson_text_splits_into_workbook_paragraphs(self):
        for b, u in zip(adapters.learner_lessons(self.doc)["bodies"], self.doc["units"]):
            parts = [p.strip() for p in b["body"]["text"].split("\n\n")]
            self.assertEqual(parts, [s["text"] for s in u["reading"]["segments"]])

    def test_capture_needs_the_learners_words_and_has_no_analysis(self):
        with self.assertRaises(ValueError):
            adapters.capture(self.doc, "u05-r05", "  ")
        c = adapters.capture(self.doc, "u05-r05", "Pourquoi « sur présentation d'un justificatif » ?")
        self.assertEqual(c["source"], "manual")
        self.assertNotIn("analysis", c)
        self.assertRegex(c["capture_id"], r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
        self.assertLessEqual(len(c["capture_id"]), 200)
        self.assertIn("not a human judgment", c["original_context"])


class Quality(unittest.TestCase):
    def test_excerpt_must_occur_once(self):
        errs = []
        q = {"id": "u01-r01", "type": "short_answer", "kind": "detail", "stem": "s", "accepted": ["a"],
             "evidence": [{"ref": "p1", "excerpt": "le"}], "explanation_en": "e", "explanation_zh": "中"}
        quality.check_question(q, {"p1": "le chat et le chien"}, errs)
        self.assertTrue(any("occurs 2 times" in e for e in errs))


class Productive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(model.PW_PATH.read_text(encoding="utf-8"))

    def test_labels_and_counts(self):
        self.assertTrue(self.doc["status"]["synthetic"])
        self.assertFalse(self.doc["status"]["human_reviewed"])
        self.assertIn("not the only", self.doc["status"]["samples"])
        self.assertEqual(len(self.doc["units"]), 12)
        self.assertEqual(sum(len(u["practice"]) for u in self.doc["units"]), 72)

    def test_rubric_has_no_score(self):
        text = json.dumps(self.doc["rubric"], ensure_ascii=False).lower().replace("gives no score", "")
        self.assertNotIn("score", text)
        self.assertIsNone(re.search(r"\b\d+\s*/\s*\d+\b|\b[abc][12]\b", text))
        self.assertEqual([l["id"] for l in self.doc["rubric"]["levels"]], ["not_yet", "developing", "secure"])

    def test_retry_corrections_apply_exactly(self):
        for u in self.doc["units"]:
            r = u["retry"]
            self.assertEqual(quality.apply_corrections(r["draft"], r["corrections"]), r["corrected"])
            for c in r["corrections"]:
                self.assertEqual(r["draft"].count(c["quote"]), 1, u["id"])

    def test_student_edition_has_no_key_and_scanner_sees_teacher(self):
        self.assertEqual(scan.scan_html(render.pw_html(self.doc, False), self.doc), [])
        self.assertEqual(scan.scan_text(render.pw_markdown(self.doc, False), self.doc, "md"), [])
        found = scan.scan_html(render.pw_html(self.doc, True), self.doc, "teacher")
        self.assertTrue(any("writing_sample" in f for f in found))
        self.assertTrue(any("retry_corrected_window" in f for f in found))

    def test_adapters(self):
        bodies = adapters.writing_task_bodies(self.doc)["bodies"]
        self.assertEqual(len(bodies), 12)
        for b in bodies:
            self.assertEqual(set(b["body"]), {"title", "prompt", "requirements", "word_min", "word_max"})
        wp = adapters.writing_prompt_set(self.doc)
        sp = adapters.speaking_prompt_set(self.doc)
        for p in wp["prompts"]:
            self.assertRegex(p["id"], r"^wr-[a-z0-9]+(-[a-z0-9]+)*$")
        for p in sp["prompts"]:
            self.assertRegex(p["id"], r"^sp-[a-z0-9]+(-[a-z0-9]+)*$")
            self.assertLessEqual(p["seconds_max"], 120)

    def test_phone_numbers_are_fictional(self):
        errs = []
        u = json.loads(json.dumps(self.doc["units"][0]))
        u["retry"]["draft"] += " Appelez le 06 12 34 56 78."
        errs, _, _ = quality.check_pw([u], expected_units=1)
        self.assertTrue(any("reserved for fiction" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
