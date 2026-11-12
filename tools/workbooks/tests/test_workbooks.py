"""Stdlib tests for tools/workbooks (run from tools/workbooks:
python3 -m unittest discover -s tests)."""

import json
import random
import re
import unittest

import copy
import tempfile
from pathlib import Path

import html

from flh_workbooks import adapters, audit, model, quality, render, scan, studypack
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


class StudyPack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(model.RL_PATH.read_text(encoding="utf-8"))
        cls.pack = studypack.load_pack("u05")

    def test_u05_pack_builds_clean_and_only_the_teacher_sheet_has_the_key(self):
        with tempfile.TemporaryDirectory() as d:
            summary = studypack.build(self.doc, "u05", Path(d))
            self.assertEqual(summary["errors"], [])
            self.assertEqual(summary["flags"], [])
            self.assertEqual(summary["scan_findings"]["student-checklist"], 0)
            self.assertEqual(summary["scan_findings"]["reader-sheet"], 0)
            self.assertGreater(summary["scan_findings"]["teacher-debrief"], 0)
            checklist = (Path(d) / "u05-student-checklist.html").read_text(encoding="utf-8")
            for t in find_turns(self.doc, "u05"):
                self.assertNotIn(t, checklist)
            reader = (Path(d) / "u05-reader-sheet.html").read_text(encoding="utf-8")
            self.assertIn("18 h 30", reader)  # the context line is read before the dialogue

    def test_a_fact_only_in_the_reading_text_is_an_error_unless_read_aloud_as_context(self):
        # Since the evidence audit, u05-l04 rests on the dialogue: no flag even without the context line.
        pack = copy.deepcopy(self.pack)
        del pack["context"]
        self.assertEqual(studypack.verify(self.doc, pack)[:2], ([], []))
        # The earlier wording relied on the brochure's class time (p1): an error, with its source.
        doc = copy.deepcopy(self.doc)
        q = next(q for q in studypack.find_unit(doc, "u05")["listening"]["questions"] if q["id"] == "u05-l04")
        q["explanation_en"] = "Work ends before the 18:30 class."
        errors, flags, _ = studypack.verify(doc, pack)
        self.assertEqual({(f["id"], f["fact"], tuple(f["found_in"])) for f in flags}, {("u05-l04", "18 h 30", ("p1",))})
        self.assertTrue(any("18 h 30" in e and "only in the reading text (p1)" in e for e in errors), errors)
        # Read aloud before the dialogue, the context line counts as heard.
        self.assertEqual(studypack.verify(doc, self.pack)[:2], ([], []))

    def test_broken_evidence_reasons_or_plan_are_refused(self):
        pack = copy.deepcopy(self.pack)
        pack["transfer"]["questions"][0]["evidence"][0]["excerpt"] = "le vendredi"
        pack["transfer"]["questions"][1]["options"][0]["why_wrong_en"] = "He pays today (t9)."
        errors, _, _ = studypack.verify(self.doc, pack)
        self.assertTrue(any("occurs 0 times in t2" in e for e in errors), errors)
        self.assertTrue(any("u05-x02 option A" in e for e in errors), errors)
        pack = copy.deepcopy(self.pack)
        pack["context"]["excerpt"] = "de 18 h à 20 h"
        self.assertTrue(any(e.startswith("context:") for e in studypack.verify(self.doc, pack)[0]))
        self.assertEqual(sum(s["minutes"] for s in self.pack["plan"]), 10)


class StudyPacks(unittest.TestCase):
    """Every pack: distinct goals, clean build, key only in the teacher sheet, same bytes twice."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(model.RL_PATH.read_text(encoding="utf-8"))
        cls.units = studypack.pack_units()

    def test_at_least_four_packs_with_distinct_goals_and_focus(self):
        self.assertGreaterEqual(len(self.units), 4)
        packs = [studypack.load_pack(u) for u in self.units]
        self.assertEqual(len({p["goal"]["en"] for p in packs}), len(packs))
        for p in packs:
            ids = {q["id"] for q in studypack.find_unit(self.doc, p["unit"])["listening"]["questions"]}
            self.assertTrue(set(p["focus"]) <= ids, p["unit"])
            self.assertEqual(len(p["transfer"]["questions"]), 3)

    def test_every_pack_separates_the_key_and_builds_the_same_bytes_twice(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first, second = studypack.build_all(self.doc, Path(a)), studypack.build_all(self.doc, Path(b))
            self.assertEqual(sorted(first), self.units)
            for unit_id, summary in first.items():
                self.assertEqual(summary["errors"], [], unit_id)
                self.assertEqual([f for f in summary["flags"] if f["found_in"]], [], unit_id)
                self.assertEqual(summary["scan_findings"]["student-checklist"], 0, unit_id)
                self.assertEqual(summary["scan_findings"]["reader-sheet"], 0, unit_id)
                self.assertGreater(summary["scan_findings"]["teacher-debrief"], 0, unit_id)
                pack = studypack.load_pack(unit_id)
                checklist = (Path(a) / f"{unit_id}-student-checklist.html").read_text(encoding="utf-8")
                teacher = (Path(a) / f"{unit_id}-teacher-debrief.html").read_text(encoding="utf-8")
                # What the student reads (the stylesheet holds sizes such as 14mm).
                visible = html.unescape(scan._visible_text(checklist))
                for q in studypack.find_unit(self.doc, unit_id)["listening"]["questions"] + pack["transfer"]["questions"]:
                    self.assertNotIn(html.escape(q["explanation_en"]), checklist, q["id"])
                    self.assertIn(html.escape(q["explanation_en"]), teacher, q["id"])
                    if q["type"] == "short_answer":
                        # A very short answer that is an ordinary word, letter or digit (« A » for metro
                        # line A, « un » or « 1 » for one password) cannot be told from an option letter,
                        # the plan's minutes or the sheet's own French; two-digit numbers (« 14 ») and
                        # longer answers are checked as whole words.
                        for ref in [r for r in [q["reference_answer"]] + q["accepted_alternatives"]
                                    if len(r) >= 3 or (len(r) == 2 and r.isdigit())]:
                            self.assertIsNone(re.search(r"(?<!\w)" + re.escape(scan.norm(ref)) + r"(?!\w)", scan.norm(visible), re.I),
                                              f"{q['id']} « {ref} »")
                self.assertNotIn(html.escape(pack["transfer"]["productive"]["model"]), checklist)
                self.assertIn(html.escape(pack["goal"]["fr"]), checklist)
            names = sorted(p.name for p in Path(a).iterdir())
            self.assertEqual(names, sorted(p.name for p in Path(b).iterdir()))
            for name in names:
                self.assertEqual((Path(a) / name).read_bytes(), (Path(b) / name).read_bytes(), name)


class StudyPackChecksCanFail(unittest.TestCase):
    """Positive controls: each pack rule and the sheet scanner catch a planted defect."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(model.RL_PATH.read_text(encoding="utf-8"))

    def test_a_transfer_answer_needs_its_own_dialogue(self):
        pack = copy.deepcopy(studypack.load_pack("u01"))
        x01, x02, x03 = pack["transfer"]["questions"]
        next(o for o in x01["options"] if o["correct"])["text"] = "À l'arrêt Bellecour."
        next(o for o in x03["options"] if not o["correct"])["text"] = "À côté de la pharmacie, au fond."
        errors, _, _ = studypack.verify(self.doc, pack)
        text = " | ".join(errors)
        self.assertIn("transfer u01-x01: the answer « À l'arrêt Bellecour. » needs « Bellecour »", text)
        self.assertIn("transfer u01-x02: « à côté de la pharmacie » is shown in u01-x03 option", text)

    def test_the_sheet_scanner_catches_an_injected_key(self):
        pack = studypack.load_pack("u06")
        clean = studypack.student_html(self.doc, pack)
        shorts = [q["reference_answer"] for q in pack["transfer"]["questions"] if q["type"] == "short_answer"]
        self.assertEqual(studypack._scan_sheet(clean, self.doc, "student", shorts), [])
        unit_q = studypack.find_unit(self.doc, "u06")["listening"]["questions"][0]
        planted = {
            "visible reference": clean.replace("</body>", f"<p>{html.escape(shorts[0])}</p></body>"),
            "hidden comment": clean.replace("</body>", "<!-- corrigé : B --></body>"),
            "workbook explanation": clean.replace("</body>", f"<p>{html.escape(unit_q['explanation_en'])}</p></body>"),
            "display none": clean.replace("</body>", '<p style="display:none">x</p></body>'),
        }
        for name, markup in planted.items():
            self.assertNotEqual(studypack._scan_sheet(markup, self.doc, "student", shorts), [], name)


class ListeningAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(model.RL_PATH.read_text(encoding="utf-8"))

    def test_every_listening_question_rests_on_its_script(self):
        rows, errors = audit.listening_audit(self.doc)
        self.assertEqual(len(rows), 120)
        self.assertEqual(errors, [])
        self.assertEqual({r["basis"] for r in rows}, {"script", "script, restated or computed value"})

    def test_reading_reliance_clues_and_uncited_reasons_are_errors(self):
        doc = copy.deepcopy(self.doc)
        u = studypack.find_unit(doc, "u01")["listening"]["questions"]
        wrong = next(o for o in next(q for q in u if q["id"] == "u01-l08")["options"] if not o["correct"])
        wrong["why_wrong_en"] = "The courtyard is only in the advert (p2), not in the call (s9)."
        next(q for q in u if q["id"] == "u01-l01")["stem"] = "Hugo donne le numéro 14 : pourquoi appelle-t-il Lina ?"
        u3 = studypack.find_unit(doc, "u03")["listening"]["questions"]
        wrong3 = next(o for o in next(q for q in u3 if q["id"] == "u03-l01")["options"] if not o["correct"])
        wrong3["why_wrong_en"] = wrong3["why_wrong_zh"] = "No prescription is requested."
        rows, errors = audit.listening_audit(doc)
        text = " | ".join(errors)
        self.assertIn("u01-l08: relies on the reading text cites p2", text)
        self.assertIn("u01-l10: « le numéro 14 » is shown in u01-l01 stem, before reveal", text)
        self.assertIn("u03-l01 option", text)
        self.assertEqual({r["id"]: r["basis"] for r in rows}["u01-l08"], "reading")


class AnswerContext(unittest.TestCase):
    """The answer itself must not need context the script does not give."""

    FIXTURE = Path(__file__).parent / "fixtures" / "answer_context_bad.json"

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(model.RL_PATH.read_text(encoding="utf-8"))

    def test_workbook_answers_are_heard_in_their_scripts(self):
        rows, errors = audit.answer_context(self.doc)
        self.assertEqual(errors, [])
        self.assertGreater(len(rows), 60)
        self.assertEqual({(r["id"], r["anchor"]) for r in rows if r["heard"] == "reviewed"}, set(audit.REVIEWED_ANSWER_CONTEXT))
        self.assertFalse({r["heard"] for r in rows} & {"reading", "nowhere"})

    def test_the_deliberately_bad_fixture_fails(self):
        bad = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        rows, errors = audit.answer_context(bad)
        self.assertEqual(errors, [
            "u90-l01: the answer « Le jeudi. » needs « jeudi », which only the reading text gives",
            "u90-l02: the answer « à 18 h 30 » needs « 18 h 30 », which only the reading text gives",
            "u90-l03: the answer « à Lyon » needs « Lyon » (name), which the script never says",
        ])
        heard = {(r["id"], r["anchor"]): r["heard"] for r in rows}
        self.assertEqual(heard[("u90-l04", "4")], "cited line")  # said in words: « quatre jours »
        self.assertEqual(heard[("u90-l05", "Mei")], "cited line")
        audit_rows, audit_errors = audit.listening_audit(bad)
        self.assertEqual([e for e in audit_errors if "the answer" in e], errors)
        self.assertEqual({r["id"]: r["basis"] for r in audit_rows},
                         {"u90-l01": "reading", "u90-l02": "reading", "u90-l03": "absent context", "u90-l04": "script", "u90-l05": "script"})

    def test_a_reading_only_answer_in_the_workbook_fails_the_audit(self):
        doc = copy.deepcopy(self.doc)
        q = next(q for q in studypack.find_unit(doc, "u05")["listening"]["questions"] if q["id"] == "u05-l04")
        next(o for o in q["options"] if o["correct"])["text"] = "Le cours commence à 18 h 30, après son travail."
        _, errors = audit.listening_audit(doc)
        self.assertTrue(any(e.startswith("u05-l04: the answer") and "18 h 30" in e for e in errors), errors)

    def test_a_stale_reviewed_entry_is_reported(self):
        doc = copy.deepcopy(self.doc)
        q = next(q for q in studypack.find_unit(doc, "u04")["listening"]["questions"] if q["id"] == "u04-l04")
        next(o for o in q["options"] if o["correct"])["text"] = "Il a vécu six mois à Dublin."
        _, errors = audit.answer_context(doc)
        self.assertEqual(errors, ["REVIEWED_ANSWER_CONTEXT u04-l04 « Irlande » is no longer needed; remove it"])

    def test_numbers_said_in_words(self):
        for text, want in [("quatre-vingt-dix euros", 90), ("au troisième étage", 3), ("c'est le 48 213", 48213),
                           ("deux cents, soixante-douze", 200), ("vingt et un", 21), ("plus qu'un seul mot", 1), ("la première fois", 1)]:
            self.assertIn(want, audit.heard_numbers(text), text)
        self.assertNotIn(272, audit.heard_numbers("deux cents, soixante-douze"))


def find_turns(doc, unit_id):
    return [t["text"] for t in studypack.find_unit(doc, unit_id)["listening"]["turns"]]
