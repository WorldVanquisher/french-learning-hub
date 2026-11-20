"""Extraction 2.0 practice prototype (flh_extraction.practice, packet, practice_workflow): offline, synthetic data."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flh_extraction import packet as pk  # noqa: E402
from flh_extraction import practice as pr  # noqa: E402
from flh_extraction import practice_workflow as pw  # noqa: E402

FIX = ROOT / "fixtures" / "practice_v1"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def refs(drf):
    return {i["proposal_ref"]: i for i in drf["items"]}


def decided(src_name="y_en.r1.json", script=None):
    drf = pr.draft(load(src_name))
    by = refs(drf)
    ds = [pr.decision(drf, by[r]["item_id"], a, k + 1, t, why) for k, (r, a, t, why) in enumerate(script or pw.DEMO_SCRIPT)]
    return drf, ds, pr.resolve(drf, ds)


def run_cli(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-B", "-m", "flh_extraction", "practice", *args], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(ROOT)})


class Representation(unittest.TestCase):
    def test_four_types_stable_ids_and_revision_references(self):
        drf = pr.draft(load("y_en.r1.json"))
        self.assertEqual(sorted({i["type"] for i in drf["items"]}), sorted(pr.TYPES))
        self.assertTrue(all(i["item_id"].startswith("k-") and len(i["item_id"]) == 14 for i in drf["items"]))
        self.assertTrue(all(e["evidence_id"].startswith("ev-") and e["source_revision"] == 1 for e in drf["evidence"]))
        self.assertEqual(drf["source"]["revision"], 1)
        self.assertEqual(len(drf["source"]["revision_sha256"]), 64)
        r2 = pr.draft(load("y_en.r2.json"))
        self.assertEqual([i["item_id"] for i in drf["items"]], [i["item_id"] for i in r2["items"]])  # IDs never hash the revision
        self.assertNotEqual(drf["draft_id"], r2["draft_id"])

    def test_source_learner_and_generated_are_kept_apart_and_uncertain_stays_visible(self):
        _, _, res = decided()
        st = {i["proposal_ref"]: (i["origin_effective"], i["support"], i["state"]) for i in res["items"]}
        self.assertEqual(st["en-de"], ("source", "supported", "approved"))
        self.assertEqual(st["y-a"], ("learner", "supported", "corrected"))
        self.assertEqual(st["ex-piscine"], ("generated", "generated", "approved"))
        self.assertEqual(st["en-mouvement"], ("source", "unsupported", "rejected"))
        y = next(i for i in res["items"] if i["proposal_ref"] == "y-a")
        self.assertNotEqual(y["effective"]["statement"], y["proposed_text"])  # the proposal is kept beside the correction
        q = pr.draft(load("en_quantite.json"))
        b = refs(q)
        self.assertEqual((b["en-pronom"]["support"], b["en-pronom"]["groundings"][0]["status"]), ("uncertain", "ambiguous"))
        self.assertEqual((b["les-defini"]["support"], b["les-defini"]["groundings"][0]["status"]), ("uncertain", "explanation_only"))
        text = pr.render_preview(pr.resolve(q, []))
        self.assertIn("UNCERTAIN: still a draft, decide explicitly", text)

    def test_invalid_sources_are_refused(self):
        src = load("y_en.r1.json")
        for mutate in (lambda s: s.update(schema="x"), lambda s: s.update(source_id="Bad Id"), lambda s: s.update(revision=0),
                       lambda s: s["proposal"]["items"].append({"type": "claim", "ref": "y-a", "statement": "dup"}),
                       lambda s: s["proposal"]["items"][0].update(applies=["nope"]), lambda s: s["proposal"]["items"][0].update(type="rule")):
            s = copy.deepcopy(src)
            mutate(s)
            with self.assertRaises(ValueError):
                pr.draft(s)


class DraftAndDecisions(unittest.TestCase):
    def test_preview_places_each_statement_beside_its_evidence(self):
        drf = pr.draft(load("y_en.r1.json"))
        text = pr.render_preview(pr.resolve(drf, []))
        block = text.split("[" + refs(drf)["en-de"]["item_id"] + "]")[1].split("\n\n")[0]
        self.assertIn("statement « en » replaces a place introduced by « de »", block)
        self.assertIn("[Je viens de la boulangerie, j'en viens.]", block)
        self.assertIn("UNSUPPORTED: still a draft", text)

    def test_exact_replay_is_byte_identical(self):
        a = pr.dumps(pr.draft(load("y_en.r1.json")))
        b = pr.dumps(pr.draft(json.loads((FIX / "y_en.r1.json").read_text(encoding="utf-8"))))
        self.assertEqual(a, b)

    def test_a_revised_source_carries_unchanged_decisions_and_reopens_changed_ones(self):
        _, ds, _ = decided()
        res2 = pr.resolve(pr.draft(load("y_en.r2.json")), ds)
        st = {i["proposal_ref"]: (i["state"], i.get("carried_from_revision")) for i in res2["items"]}
        self.assertEqual(st["y-a"], ("corrected", 1))  # the learner's correction survives: its evidence is unchanged
        self.assertEqual(st["en-mouvement"], ("rejected", 1))
        self.assertEqual(st["en-de"][0], "needs_review")  # its quote is gone from revision 2
        self.assertEqual(st["y-vs-en"][0], "needs_review")
        y = next(i for i in res2["items"] if i["proposal_ref"] == "y-a")
        self.assertTrue(y["effective"]["statement"].startswith("« y » replaces where you go"))
        prac2 = pr.build_practice(res2)
        self.assertEqual(prac2["items"], [])  # the contrast needs review, so no practice is built from it

    def test_decisions_are_validated(self):
        drf = pr.draft(load("y_en.r1.json"))
        for bad in (("k-nope", "approve", None), (drf["items"][0]["item_id"], "accept", None), (drf["items"][0]["item_id"], "edit", " ")):
            with self.assertRaises(ValueError):
                pr.decision(drf, bad[0], bad[1], 1, bad[2])
        with self.assertRaises(ValueError):
            pr.read_decisions([json.dumps({"schema": pr.DECISION_SCHEMA, "seq": 1, "item_id": "k", "action": "approve"})] * 2)


class Practice(unittest.TestCase):
    def setUp(self):
        _, _, self.res = decided()
        self.prac = pr.build_practice(self.res)
        self.by = {(p["kind"], p["knowledge_ids"][0]): p for p in self.prac["items"]}
        self.ids = {i["proposal_ref"]: i["item_id"] for i in self.res["items"]}

    def test_three_types_from_approved_knowledge_only(self):
        self.assertEqual(self.prac["counts"], {"explain": 1, "choose": 2, "produce": 2})
        used = {k for p in self.prac["items"] for k in p["knowledge_ids"]}
        self.assertNotIn(self.ids["en-mouvement"], used)  # rejected
        self.assertTrue(all(p["evidence_ids"] for p in self.prac["items"]))
        self.assertTrue(all(p["new_sentence"] for p in self.prac["items"] if p["kind"] != "explain"))
        src = pr.source_text(load("y_en.r1.json"))
        for p in self.prac["items"]:
            if p["kind"] == "produce":
                self.assertNotIn(p["hidden"]["answer"], src)  # practice in a sentence absent from the source
        pending = pr.build_practice(pr.resolve(pr.draft(load("y_en.r1.json")), []))
        self.assertEqual(pending["items"], [])

    def test_answers_stay_hidden_until_an_attempt_or_reveal(self):
        text = pr.render_practice(self.prac)
        for p in self.prac["items"]:
            self.assertNotIn("hidden", pr.public(p))
            for v in p["hidden"].get("accepted", []) + [p["hidden"].get("answer") or "", p["hidden"]["explanation"]]:
                if v and v not in ("y", "en"):
                    self.assertNotIn(v, text)
        p = self.by[("produce", self.ids["ex-piscine"])]
        rec, fb = pr.attempt(self.prac, p["practice_id"], 1, "Oui, on y va !")
        out = pr.render_feedback(fb)
        self.assertIn("why       « aller à la piscine »", out)
        self.assertIn("source    ev-", out)
        rec, fb = pr.attempt(self.prac, p["practice_id"], 2, reveal=True)
        self.assertEqual((rec["action"], rec["outcome"]), ("reveal", "revealed"))
        with self.assertRaises(ValueError):
            pr.attempt(self.prac, p["practice_id"], 3, "  ")

    def test_valid_variants_self_check_and_known_errors(self):
        p = self.by[("produce", self.ids["ex-piscine"])]
        for text in ("Oui, on y va !", "oui on y va", "Non, nous n’y allons pas."):
            self.assertEqual(pr.grade(p, text)["outcome"], "correct", text)
        self.assertEqual(pr.grade(p, "Oui, nous en allons.")["outcome"], "incorrect")
        self.assertEqual(pr.grade(p, "Oui, on va y aller ce soir.")["outcome"], "self_check")  # valid French, not listed
        c = self.by[("choose", self.ids["ex-piscine"])]
        self.assertEqual([pr.grade(c, x)["outcome"] for x in ("y", "EN", "le")], ["correct", "incorrect", "invalid"])
        e = self.by[("explain", self.ids["y-vs-en"])]
        self.assertEqual(pr.grade(e, "anything")["outcome"], "self_check")

    def test_ambiguous_evidence_and_alternate_answers(self):
        script = [(r, "approve", None, "") for r in ("en-quantite", "en-vs-les", "les-deux", "ex-freres", "ex-cles")]
        _, _, res = decided("en_quantite.json", script)
        prac = pr.build_practice(res)
        ids = {i["proposal_ref"]: i["item_id"] for i in res["items"]}
        by = {(p["kind"], p["knowledge_ids"][0]): p for p in prac["items"]}
        f = by[("produce", ids["ex-freres"])]
        self.assertEqual([pr.grade(f, x)["outcome"] for x in ("J'en ai trois.", "Oui, j'en ai trois", "Oui, j'en ai deux.", "Oui, je les ai trois.")],
                         ["correct", "correct", "self_check", "incorrect"])
        ch = by[("choose", ids["ex-freres"])]
        self.assertEqual(ch["options"], ["j'en", "je les"])
        self.assertEqual(pr.grade(ch, "j’en")["outcome"], "correct")
        self.assertEqual(pr.grade(by[("produce", ids["ex-cles"])], "Oui, j'en ai.")["outcome"], "incorrect")


class Packets(unittest.TestCase):
    def setUp(self):
        _, _, self.res = decided()
        self.prac = pr.build_practice(self.res)
        miss = next(p for p in self.prac["items"] if p["kind"] == "produce")
        self.attempts = [{"seq": 1, "practice_id": miss["practice_id"], "action": "attempt", "text": "SECRET-ATTEMPT-TEXT", "outcome": "incorrect"}]

    def keys(self):
        """Answer keys: accepted answers, answers and per-example wrong answers. A known confusion
        (common error) is shared on purpose: it is part of the packet (item 126)."""
        shared = {i["effective"][f] for i in self.res["items"] if i["type"] == "common_error" for f in ("wrong", "right")}
        out = set()
        for p in self.prac["items"]:
            h = p["hidden"]
            out |= set(h.get("accepted", [])) | set(h.get("known_errors", [])) | ({h["answer"]} if len(h.get("answer", "")) > 3 else set())
        return out - shared

    def test_markdown_and_json_come_from_the_same_data(self):
        p = pk.export(self.res, self.prac, self.attempts)
        self.assertEqual(pk.markdown(json.loads(pr.dumps(p))), pk.markdown(p))
        for k in p["knowledge"]:
            self.assertIn(k["id"], pk.markdown(p))
        for e in p["evidence"]:
            self.assertIn(e["evidence_id"], pk.markdown(p))

    def test_study_omits_keys_and_tutor_needs_an_explicit_choice(self):
        study = pk.export(self.res, self.prac, self.attempts, "study")
        tutor = pk.export(self.res, self.prac, self.attempts, "tutor")
        full = pk.export(self.res, self.prac, self.attempts, "tutor", include_rubrics=True)
        for doc in (study, tutor):
            blob = pr.dumps(doc) + pk.markdown(doc)
            self.assertEqual([k for k in self.keys() if k in blob], [], doc["mode"])
            self.assertFalse(any("rubric" in x for x in doc["next_exercises"]))
        self.assertIn("withheld", tutor["rubrics_note"])
        self.assertTrue(all("rubric" in x for x in full["next_exercises"]))
        full_blob = pr.dumps(full) + pk.markdown(full)
        self.assertEqual([k for k in self.keys() if k not in full_blob], [])  # every key, by the learner's explicit choice
        with self.assertRaises(ValueError):
            pk.export(self.res, self.prac, self.attempts, "study", include_rubrics=True)

    def test_defaults_exclude_unrelated_records_and_private_data(self):
        p = pk.export(self.res, self.prac, self.attempts)
        blob = pr.dumps(p) + pk.markdown(p)
        rejected = next(i for i in self.res["items"] if i["state"] == "rejected")
        self.assertNotIn(rejected["item_id"], blob)
        self.assertNotIn(rejected["content"]["statement"], blob)
        self.assertNotIn("SECRET-ATTEMPT-TEXT", blob)
        src = load("y_en.r1.json")["capture"]
        self.assertNotIn(src["original_context"], blob)  # excerpts only
        self.assertEqual(p["known_confusions"][0]["missed_in_practice"], 1)
        bad = copy.deepcopy(self.res)
        bad["learner_goal"] = "see /" + "home" + "/someone/notes.txt"
        with self.assertRaises(PermissionError):
            pk.export(bad, self.prac)
        bad["learner_goal"] = "token " + "sk" + "-" + "a" * 20
        with self.assertRaises(PermissionError):
            pk.export(bad, self.prac)

    def test_preview_lists_what_will_be_shared(self):
        p = pk.export(self.res, self.prac, self.attempts)
        text = pk.preview(p)
        self.assertIn("nothing has been written yet", text)
        self.assertIn("answer keys        not included", text)
        self.assertIn(p["packet_id"], text)


class AgentReturn(unittest.TestCase):
    def setUp(self):
        _, _, res = decided()
        prac = pr.build_practice(res)
        self.packet = json.loads((FIX / "expected" / "packet-study__packet.json").read_text(encoding="utf-8"))
        self.ret = load("agent_return.json")

    def test_every_class_is_reported_and_nothing_is_applied(self):
        before = (FIX / "expected" / "packet-study__packet.json").read_bytes()
        rep = pk.import_preview(self.packet, self.ret)
        self.assertTrue(rep["packet_matches"])
        self.assertEqual(rep["counts"], {"accepted_candidate": 3, "duplicate": 1, "conflict": 2, "unknown_reference": 1, "invalid": 1})
        cls = {r["proposal_id"]: r["class"] for r in rep["rows"]}
        self.assertEqual(cls, {"p1": "accepted_candidate", "p2": "conflict", "p3": "accepted_candidate", "p4": "duplicate",
                               "p5": "unknown_reference", "p6": "conflict", "p7": "accepted_candidate", "p8": "invalid"})
        p7 = next(r for r in rep["rows"] if r["proposal_id"] == "p7")
        self.assertIn("cites no evidence", p7["flags"][0])
        self.assertEqual((FIX / "expected" / "packet-study__packet.json").read_bytes(), before)
        other = dict(self.ret, packet_id="pk-other")
        self.assertFalse(pk.import_preview(self.packet, other)["packet_matches"])
        with self.assertRaises(ValueError):
            pk.import_preview(self.packet, {"schema": "x"})

    def test_prompts_ask_for_evidence_ids_one_question_and_unsupported_labels(self):
        for name, mention in (("PROMPT-codex.md", "packet.md"), ("PROMPT-claude-code.md", "@packet.md")):
            t = (ROOT / "practice_prompts" / name).read_text(encoding="utf-8")
            for phrase in (mention, "evidence ID (ev-…)", "one question at a time", "not in the packet", pk.PROPOSALS_SCHEMA, "proposals.json"):
                self.assertIn(phrase, t, (name, phrase))

    def test_handoff_from_an_empty_directory_with_only_the_packet_and_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            for f in ("packet.json", "packet.md"):
                shutil.copyfile(FIX / "expected" / f"packet-study__{f}", Path(d) / f)
            shutil.copyfile(ROOT / "practice_prompts" / "PROMPT-codex.md", Path(d) / "PROMPT-codex.md")
            shutil.copyfile(FIX / "agent_return.json", Path(d) / "proposals.json")  # stands in for the agent's reply
            self.assertEqual(sorted(os.listdir(d)), ["PROMPT-codex.md", "packet.json", "packet.md", "proposals.json"])
            out = run_cli("import-preview", "--packet", "packet.json", "--proposals", "proposals.json", cwd=d)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("counts: accepted_candidate 3, duplicate 1, conflict 2, unknown_reference 1, invalid 1", out.stdout)
            md = (Path(d) / "packet.md").read_text(encoding="utf-8")
            pkt = json.loads((Path(d) / "packet.json").read_text(encoding="utf-8"))
            for x in pkt["next_exercises"]:
                self.assertIn(x["id"], md)
            self.assertEqual(pk.privacy_findings(md + json.dumps(pkt)), [])


class Workflow(unittest.TestCase):
    def test_demo_reproduces_the_shipped_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            rc, text = pw.demo(f"{d}/out", check=True)
            self.assertEqual(rc, 0, text)
            self.assertIn("rejected k-", text)
            self.assertIn("new-sentence items 4", text)
            with self.assertRaises(ValueError):
                pw.demo(f"{d}/out")

    def test_cli_round_trip_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            w = f"{d}/w"
            self.assertEqual(run_cli("init", "--source", str(FIX / "y_en.r1.json"), "--work", w).returncode, 0)
            item = pr.draft(load("y_en.r1.json"))["items"][1]["item_id"]
            self.assertEqual(run_cli("decide", "--work", w, "--item", item, "--approve").returncode, 0)
            self.assertEqual(run_cli("decide", "--work", w, "--item", "k-nope", "--approve").returncode, 2)
            self.assertIn("approved 1", run_cli("preview", "--work", w).stdout)
            self.assertEqual(run_cli("export", "--work", w, "--mode", "study", "--include-rubrics", "--preview").returncode, 2)
            self.assertEqual(run_cli("init", "--source", str(FIX / "y_en.r1.json"), "--work", w).returncode, 2)  # not empty

    def test_comparison_counts(self):
        rep = pw.compare()
        y = rep["rows"][0]
        self.assertEqual((y["new_flow"]["supported"], y["new_flow"]["unsupported"], y["new_flow"]["exercises_tied_to_evidence"]), (2, 1, 5))
        self.assertEqual(y["existing_extraction"]["evidence_review_classes"], {"anchored": 3})  # lexical anchoring misses the unsupported claim
        r2 = rep["rows"][1]  # the revised source: a quote vanished, lexical anchoring still says anchored
        self.assertEqual((r2["new_flow"]["supported"], r2["new_flow"]["unsupported"], r2["new_flow"]["exercises"]), (1, 2, 0))
        self.assertEqual(r2["existing_extraction"]["evidence_review_classes"], {"anchored": 3})
        q = rep["rows"][2]
        self.assertEqual((q["new_flow"]["supported"], q["new_flow"]["uncertain"]), (1, 2))

    def test_workbooks_feed_has_no_keys_and_no_schedule(self):
        feed = json.loads((FIX / "expected" / "07-workbooks-feed.json").read_text(encoding="utf-8"))
        self.assertEqual(feed["schema"], pk.FEED_SCHEMA)
        for i in feed["items"]:
            self.assertEqual(set(i) & {"hidden", "accepted", "answer", "due", "due_on", "interval", "schedule"}, set())
            self.assertIn("outcomes", i)
            self.assertTrue(all(set(o) == {"seq", "action", "outcome"} for o in i["outcomes"]))  # no attempt text


if __name__ == "__main__":
    unittest.main()
