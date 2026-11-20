"""Extraction 2.2 (review2, practice22, exercises, portable, recall, feed2, feed_compat, storage_rt, practice_flow22): offline, synthetic data."""

from __future__ import annotations

import hashlib
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

from flh_extraction import exercises as ex  # noqa: E402
from flh_extraction import feed2  # noqa: E402
from flh_extraction import feed_compat as fc  # noqa: E402
from flh_extraction import packet as pk  # noqa: E402
from flh_extraction import portable as pt  # noqa: E402
from flh_extraction import practice as pr  # noqa: E402
from flh_extraction import practice22 as p22  # noqa: E402
from flh_extraction import practice_flow22 as f22  # noqa: E402
from flh_extraction import review2 as rv  # noqa: E402
from flh_extraction import storage_rt as st  # noqa: E402

FIX = ROOT / "fixtures" / "practice_v1"


def load(*parts):
    return json.loads(FIX.joinpath(*parts).read_text(encoding="utf-8"))


def cli(*args):
    return subprocess.run([sys.executable, "-B", "-m", "flh_extraction", "practice2", *args], cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(ROOT)})


class Tmp(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def work(self, name="w", src="a_en_lieux.json"):
        w = p22.Work2(str(self.tmp / name))
        w.init(str(FIX / src))
        return w, {i["proposal_ref"]: i["item_id"] for i in w.draft()["items"]}

    def a_en_decided(self, name="a"):
        w, ids = self.work(name)
        for ref, action, text, attest in f22.SCRIPTS["a-en-lieux-demo"]["before_batch"]:
            w.decide(ids[ref], action, text, attest=attest)
        w.approve_batch(w.plan()["batch_id"])
        w.practice(rebuild=True)
        return w, ids


class Grounding(Tmp):
    def test_public_excerpts_are_quoted_exactly_with_their_revision(self):
        src = load("a_en_lieux.json")
        prov = src["provenance"]
        self.assertEqual(prov["author"].split(" (")[0], "Jules Verne")
        self.assertTrue(all(p["revid"] > 0 and len(p["text_sha256"]) == 64 for p in prov["transcription"]["pages"]))
        text = pr.source_text(src)
        for e in prov["excerpts"]:
            self.assertEqual(text.count(pr.fold(e["text"])), 1, e["text"])
        self.assertTrue(prov["usage_boundaries"] and "synthetic_parts" in prov)
        self.assertNotIn("provenance", json.dumps(pr.revision_sha256(src)))

    def test_word_cues_flag_quotes_that_do_not_carry_the_claim(self):
        w, ids = self.work()
        res = w.resolved()
        by = {i["proposal_ref"]: i for i in res["items"]}
        self.assertEqual([c["cue"] for c in by["en-tous-pays"]["cues"]], ["generalises"])
        self.assertEqual([c["cue"] for c in by["en-gerondif"]["cues"]], ["en_plus_ant"])
        self.assertEqual(by["en-tous-pays"]["support"], "supported")  # the quote is located: text matching is not refuted
        self.assertFalse(by["a-ville"]["cues"] or by["en-pays"]["cues"])
        plan = w.plan()
        left = {r["item_id"]: r["why"] for r in plan["left_for_you"]}
        self.assertIn("a word check, not a proof", left[ids["en-tous-pays"]])
        self.assertNotIn(ids["en-tous-pays"], [m["item_id"] for m in plan["members"]])

    def test_a_non_entailing_claim_without_a_cue_word_is_not_caught(self):
        it = {"origin": "source", "type": "claim", "groundings": [{"quote": "à Paris", "status": "located"}],
              "content": {"statement": "« à » is used before a country name: « à Paris »."}}
        self.assertEqual(rv.cues(it), [], "documented limit: the cues compare words; they prove nothing either way")

    def test_quote_and_paraphrase_are_labelled_apart(self):
        w, ids = self.work()
        text = w.show()
        block = text.split(f"[{ids['aux-pluriel']}]", 1)[1].split("\n\n", 1)[0]
        self.assertIn("QUOTE       ev-", block)
        self.assertIn("PARAPHRASE  restates ev-", block)
        res = w.resolved()
        it = next(i for i in res["items"] if i["item_id"] == ids["aux-pluriel"])
        self.assertEqual(it["paraphrases"][0]["of_status"], "located")
        self.assertEqual(it["evidence_ids"], [it["paraphrases"][0]["of_evidence_id"]], "a paraphrase adds no evidence")

    def test_conflicting_drafts_are_accepted_edited_and_rejected_one_by_one(self):
        w, ids = self.work()
        conf = w.resolved()["conflicts"]
        self.assertEqual({(c["error_id"], c["other_id"]) for c in conf}, {(ids["en-japon"], ids["en-tous-pays"])})
        self.assertFalse({ids["en-japon"], ids["en-tous-pays"]} & {m["item_id"] for m in w.plan()["members"]})
        w2, ids2 = self.a_en_decided()
        st_ = {i["proposal_ref"]: i["state"] for i in w2.resolved()["items"]}
        self.assertEqual((st_["en-japon"], st_["en-tous-pays"], st_["en-gerondif"], st_["aux-pluriel"]), ("approved", "rejected", "corrected", "approved"))

    def test_the_y_en_conflict_blocks_the_batch_until_one_side_is_rejected(self):
        w, ids = self.work(src="y_en.r1.json")
        self.assertNotIn(ids["en-vais"], [m["item_id"] for m in w.plan()["members"]])
        w.decide(ids["en-mouvement"], "reject", reason="my friend corrected it")
        self.assertIn(ids["en-vais"], [m["item_id"] for m in w.plan()["members"]])


class Approval(Tmp):
    def test_acceptance_matrix(self):
        m = p22.acceptance_matrix(str(self.tmp / "m"))
        self.assertTrue(m["all_ok"], [r for r in m["rows"] if not r["ok"]])
        self.assertGreaterEqual(len(m["rows"]), 24)

    def test_plan_lists_the_selection_and_its_effects(self):
        w, ids = self.work()
        pl = w.plan()
        self.assertEqual(pl["selected"], [m["item_id"] for m in pl["members"]])
        self.assertEqual(pl["effects"]["knowledge_approved"], 5)
        self.assertEqual((pl["effects"]["practice_before"], pl["effects"]["practice_after"]), (0, 5))
        text = rv.render_plan(pl)
        self.assertIn("Effect: 5 items become approved knowledge", text)
        self.assertEqual(text.count("  [x] "), 5)
        sub = w.plan(select=[ids["a-ville"], ids["a-vs-en"]])
        self.assertEqual(sub["batch_id"], pl["batch_id"], "the ID binds the batch shown; the selection is recorded per decision")
        self.assertEqual(sub["effects"]["knowledge_approved"], 2)
        with self.assertRaises(ValueError):
            w.plan(select=[ids["en-tous-pays"]])
        ds = w.approve_batch(pl["batch_id"], select=[ids["a-ville"], ids["a-vs-en"]])
        self.assertEqual([d["batch"]["selected"] for d in ds][0], [ids["a-ville"], ids["a-vs-en"]])
        self.assertEqual(len(ds[0]["batch"]["members"]), 5)

    def test_revised_or_uncertain_evidence_is_never_batched(self):
        w, ids = self.work(src="y_en.r1.json")
        w.decide(ids["en-mouvement"], "reject")
        w.approve_batch(w.plan()["batch_id"])
        w.revise(str(FIX / "y_en.r2.json"))
        w.revise(str(FIX / "y_en.r3.json"))
        pl = w.plan()
        self.assertIsNone(pl["batch_id"])
        kinds = {r["item_id"]: r["why"].split(":")[0] for r in pl["left_for_you"]}
        self.assertEqual(kinds, {ids["en-de"]: "RESTORED", ids["y-vs-en"]: "RESTORED", ids["en-vais"]: "CHANGED", ids["ex-marche"]: "CHANGED"})
        en = load("en_quantite.json")
        w2 = p22.Work2(str(self.tmp / "q"))
        w2.init(str(FIX / "en_quantite.json"))
        unc = [i["item_id"] for i in w2.resolved()["items"] if i["support"] in ("uncertain", "unsupported", "no_evidence")]
        self.assertTrue(unc and not set(unc) & {m["item_id"] for m in w2.plan()["members"]})
        self.assertTrue(en)

    def test_revision_3_keeps_unchanged_decisions_shows_moves_and_refuses_material_reuse(self):
        w, ids = self.work(src="y_en.r1.json")
        w.decide(ids["en-mouvement"], "reject", reason="my friend corrected it")
        w.approve_batch(w.plan()["batch_id"])
        w.revise(str(FIX / "y_en.r2.json"))
        w.revise(str(FIX / "y_en.r3.json"))
        res = w.resolved()
        by = {i["proposal_ref"]: i for i in res["items"]}
        self.assertEqual(by["ex-piscine"]["state"], "approved")
        self.assertEqual(by["ex-piscine"]["carried_from_revision"], 1)
        self.assertEqual(by["y-a"]["state"], "approved")
        self.assertIn("spacing", by["y-a"]["normalized_only"])
        self.assertEqual((by["en-de"]["state"], by["en-de"]["review_kind"]), ("needs_review", "restored"))
        self.assertEqual((by["ex-marche"]["state"], by["ex-marche"]["review_kind"]), ("needs_review", "changed"))
        self.assertIn("accepted: removed « Non, je n'en reviens pas. »", by["ex-marche"]["changes"])
        self.assertEqual(by["en-mouvement"]["rejected_on"]["revision"], 1)
        self.assertIn("corrected it", by["en-mouvement"]["rejected_on"]["reason"])
        self.assertEqual(len(res["moves"]), 3)
        self.assertTrue(all(m["old_evidence_id"] != m["new_evidence_id"] for m in res["moves"].values()))
        self.assertIn("MOVED since revision 2", w.show())
        # the 2.1 resolution would have reactivated the restored items silently
        old = pr.resolve(w.draft(), w.decisions())
        self.assertEqual({i["proposal_ref"]: i["state"] for i in old["items"]}["en-de"], "approved")

    def test_reject_reason_stays_with_the_revision_that_caused_it(self):
        w, ids = self.work(src="y_en.r1.json")
        w.decide(ids["ex-marche"], "reject", reason="I want my own example first")
        w.revise(str(FIX / "y_en.r3.json"))
        it = next(i for i in w.resolved()["items"] if i["item_id"] == ids["ex-marche"])
        self.assertEqual(it["state"], "needs_review")
        self.assertEqual((it["earlier_decision"]["action"], it["earlier_decision"]["revision"]), ("reject", 1))
        self.assertIn("your reason then (revision 1): I want my own example first", w.show())

    def test_paraphrase_needs_attestation_and_records_it(self):
        w, ids = self.work()
        with self.assertRaises(ValueError):
            w.decide(ids["aux-pluriel"], "approve")
        with self.assertRaises(ValueError):
            w.decide(ids["a-ville"], "approve", attest=True)
        d = w.decide(ids["aux-pluriel"], "approve", attest=True)
        self.assertEqual(d["attest"]["by"], "learner")
        it = next(i for i in w.resolved()["items"] if i["item_id"] == ids["aux-pluriel"])
        self.assertTrue(it["attested"])

    def test_interrupted_batch_is_refused_until_repaired_then_completes_once(self):
        w, ids = self.work()
        pl = w.plan()
        res = w.resolved()
        byid = {i["item_id"]: i for i in res["items"]}
        recs = [w._stamp(pr.decision(w.draft(), i, "approve", k + 1, batch=rv.batch_meta(pl)), byid[i]) for k, i in enumerate(pl["selected"][:2])]
        Path(w.p("decisions.jsonl")).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in recs) + '{"schema": "flh', encoding="utf-8")
        with self.assertRaises(p22.TornWrite):
            w.decisions()
        self.assertEqual(cli("decide", "--work", w.path, "--approve-batch", pl["batch_id"]).returncode, 2)
        out = cli("repair", "--work", w.path)
        self.assertIn("set aside", out.stdout)
        self.assertTrue(Path(w.p("decisions.torn-1.txt")).exists())
        r = cli("decide", "--work", w.path, "--approve-batch", pl["batch_id"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("recorded 3 decisions", r.stdout)
        self.assertEqual(sorted(d["item_id"] for d in w.decisions()), sorted(pl["selected"]))
        again = cli("decide", "--work", w.path, "--approve-batch", pl["batch_id"])
        self.assertIn("nothing new", again.stdout)

    def test_complete_record_without_line_end_is_repaired_in_place(self):
        w, ids = self.work()
        d = w.decide(ids["a-ville"], "approve")
        Path(w.p("decisions.jsonl")).write_text(json.dumps(d, sort_keys=True), encoding="utf-8")
        self.assertIn("added it", w.repair())
        self.assertEqual(len(w.decisions()), 1)


class Exercises(Tmp):
    def setUp(self):
        super().setUp()
        self.w, self.ids = self.a_en_decided()
        self.p1 = self.w.export3()
        self.ret = load("switch2", "codex-a-en.json")
        self.assertEqual(self.ret["packet_id"], self.p1["packet_id"], "the fixture names packet 1 of the demo")

    def test_preview_shows_variants_rubric_and_ambiguity(self):
        rep = ex.preview(self.p1, self.ret, self.w.resolved(), [])
        rows = {r["proposal_id"]: r for r in rep["rows"]}
        self.assertEqual({k: r["class"] for k, r in rows.items()}, {"e1": "candidate", "e2": "candidate", "e3": "candidate"})
        self.assertEqual(rows["e2"]["accepted"][0], "Je vais en Italie.")
        self.assertTrue(rows["e2"]["rubric"])
        self.assertTrue(any(a.startswith("declared by the agent") for a in rows["e2"]["ambiguity"]))
        self.assertIn("provenance, not evidence", ex.render_preview(rep))
        self.assertEqual({k: v for k, v in ex.KINDS.items()}, {"explanation": "explain", "discrimination": "choose", "production": "produce"})

    def test_rule_and_revision_are_required(self):
        bad = json.loads(json.dumps(self.ret))
        bad["proposals"][0]["rule_id"] = self.ids["ex-lyon"]
        bad["proposals"][1]["source"] = {**bad["proposals"][1]["source"], "revision": 7}
        del bad["proposals"][2]["rule_id"]
        rows = {r["proposal_id"]: r["class"] for r in ex.preview(self.p1, bad)["rows"]}
        self.assertEqual(rows, {"e1": "invalid", "e2": "wrong_revision", "e3": "invalid"})

    def test_edit_approve_is_idempotent_and_never_evidence(self):
        d, new = self.w.exercise(self.p1, self.ret, "e1", "approve", edits={"prompt": "Mon oncle travaille __ Marseille depuis deux ans."})
        self.assertTrue(new)
        self.assertEqual(d["edited"], ["prompt"])
        d2, new2 = self.w.exercise(self.p1, self.ret, "e1", "approve", edits={"prompt": "Mon oncle travaille __ Marseille depuis deux ans."})
        self.assertFalse(new2)
        self.assertEqual(len(self.w.exercise_decisions()), 1)
        with self.assertRaises(ValueError):
            self.w.exercise(self.p1, self.ret, "e1", "reject")
        prac = self.w.practice(rebuild=True)
        p = next(x for x in prac["items"] if x["practice_id"] == d["practice_id"])
        self.assertEqual((p["origin"], p["support"], p["provenance"]["accepted_by"]), ("agent_proposal", "agent_proposed", "learner"))
        ev_ids = {e["evidence_id"] for e in self.w.resolved()["evidence"]}
        self.assertTrue(set(p["evidence_ids"]) <= ev_ids)
        self.assertNotIn(self.ret["proposals"][0]["rationale"], json.dumps(self.w.resolved()["evidence"], ensure_ascii=False))
        self.assertEqual(p["prompt"], "Mon oncle travaille __ Marseille depuis deux ans.")
        rows = {r["proposal_id"]: r["class"] for r in ex.preview(self.p1, self.ret, self.w.resolved(), self.w.exercise_decisions())["rows"]}
        self.assertEqual(rows["e1"], "decided")

    def test_edited_variants_are_checked_again(self):
        with self.assertRaises(ValueError):
            self.w.exercise(self.p1, self.ret, "e1", "approve", edits={"answer": "au"})
        bad = json.loads(json.dumps(self.ret))
        bad["proposals"][1]["accepted"] = ["Je vais en Italie.", "en Japon"]
        rows = {r["proposal_id"]: r["class"] for r in ex.preview(self.p1, bad, self.w.resolved(), [])["rows"]}
        self.assertEqual(rows["e2"], "conflict")

    def test_withdrawn_rule_is_actionable_and_suspends_the_exercise(self):
        d, _ = self.w.exercise(self.p1, self.ret, "e1", "approve")
        self.w.revise(str(FIX / "a_en_lieux.r2.json"))
        rows = {r["proposal_id"]: r for r in ex.preview(self.p1, self.ret, self.w.resolved(), self.w.exercise_decisions())["rows"]}
        self.assertEqual(rows["e3"]["class"], "withdrawn")
        self.assertIn("practice2 review", rows["e3"]["why"])
        prac = self.w.practice(rebuild=True)
        self.assertNotIn(d["practice_id"], [p["practice_id"] for p in prac["items"]])
        self.assertEqual(prac["from_agents"]["suspended"][0]["practice_id"], d["practice_id"])

    def test_same_exercise_from_another_agent_is_a_duplicate(self):
        self.w.exercise(self.p1, self.ret, "e1", "approve")
        other = {**self.ret, "agent": "claude-code", "proposals": [{**self.ret["proposals"][0], "proposal_id": "z1", "rule_id": self.ids["a-vs-en"]}]}
        rows = ex.preview(self.p1, other, self.w.resolved(), self.w.exercise_decisions())["rows"]
        self.assertEqual(rows[0]["class"], "duplicate")


class Portable(Tmp):
    def setUp(self):
        super().setUp()
        self.w, self.ids = self.a_en_decided()
        prac = self.w.practice()
        self.w.answer(next(p["practice_id"] for p in prac["items"] if p["kind"] == "produce"), "Je vais à Espagne.")

    def test_one_packet_for_every_agent(self):
        p = self.w.export3()
        for a in pt.ADAPTERS:
            pt.write_packet3(p, str(self.tmp / a), a)
        b = {a: (self.tmp / a / "packet.json").read_bytes() + (self.tmp / a / "packet.md").read_bytes() for a in pt.ADAPTERS}
        self.assertEqual(len(set(b.values())), 1)
        self.assertEqual(pt.normalized(pr.dumps(p)) + pt.normalized(pt.markdown3(p)), [])
        self.assertEqual(sorted(os.listdir(self.tmp / "any-agent")), ["PROMPT-any-agent.md", "packet.json", "packet.md"])
        generic = (ROOT / "practice_prompts" / "PROMPT-any-agent.md").read_text(encoding="utf-8")
        self.assertIn("If you cannot read files, ask me to paste packet.md", generic)

    def test_study_v3_has_no_answers_and_no_attempt_text(self):
        p = self.w.export3()
        body = pr.dumps(p) + pt.markdown3(p)
        self.assertNotIn("Je vais à Espagne", body)
        prac = self.w.practice()
        for x in prac["items"]:
            if x["kind"] == "produce":
                for a in x["hidden"]["accepted"]:
                    self.assertNotIn(a, body)
        self.assertNotIn("rubric", json.dumps(p["next_exercises"]))
        self.assertTrue(p["next_exercise"] and "answer" not in p["next_exercise"])

    def test_minimal_packet_and_omissions(self):
        full, mini = self.w.export3(keep=False), self.w.export3(variant="minimal", omit=("learner_goal",), keep=False)
        self.assertLess(len(pt.markdown3(mini)), len(pt.markdown3(full)) / 3)
        self.assertIsNone(mini["learner_goal"])
        self.assertIn("## Where we left off", pt.markdown3(mini))
        self.assertNotIn(load("a_en_lieux.json")["learner_goal"], pt.markdown3(mini))
        e = self.w.export3(omit=("evidence_text",), keep=False)
        self.assertTrue(all(set(x) == {"evidence_id", "source_revision", "status"} for x in e["evidence"]))
        self.assertIn("text omitted by you", pt.preview3(e))
        with self.assertRaises(ValueError):
            self.w.export3(omit=("knowledge",), keep=False)

    def test_proposed_and_accepted_facts_stay_apart(self):
        w, _ = self.a_en_decided("fresh")
        p1 = w.export3()
        ret = load("switch2", "codex-a-en.json")
        w.exercise(p1, ret, "e1", "approve")
        awaiting = pt.awaiting_from(None, ex.preview(p1, ret, w.resolved(), w.exercise_decisions()))
        p = w.export3(awaiting=awaiting, keep=False)
        md = pt.markdown3(p)
        approved_part = md.split("## Approved knowledge", 1)[1].split("## Evidence excerpts", 1)[0]
        self.assertNotIn("Où vas-tu cet hiver", approved_part)
        proposed_part = md.split("NOT accepted by the learner", 1)[1].split("##", 1)[0]
        self.assertIn("Où vas-tu cet hiver", proposed_part)
        self.assertNotIn("e2", [k["id"] for k in p["knowledge"]])
        x = next(x for x in p["next_exercises"] if x["origin"] == "agent_proposal")
        self.assertEqual(x["accepted_from"]["agent"], "codex")

    def test_older_versions_unknown_fields_and_bad_versions(self):
        v1 = json.loads((FIX / "expected" / "packet-study__packet.json").read_text(encoding="utf-8"))
        v2 = json.loads((FIX / "expected2" / "06-packet-1-codex.json").read_text(encoding="utf-8"))
        r1 = pt.import_any(v1, load("agent_return.json"))
        self.assertEqual(r1["corrections"]["counts"], pk.import_preview(v1, load("agent_return.json"))["counts"])
        r2 = pt.import_any(v2, load("switch", "codex-return.json"))
        self.assertEqual(r2["corrections"]["counts"], pk.import_preview(v2, load("switch", "codex-return.json"))["counts"])
        ret = load("switch2", "claude-code-a-en.json")
        self.assertIn("unknown top-level field 'session_summary' ignored", ex.check_return(ret)["warnings"])
        with self.assertRaises(ValueError) as cm:
            ex.check_return({**ret, "schema": "flh_agent_proposals_v9"})
        self.assertIn("flh_agent_proposals_v1, flh_agent_proposals_v2", str(cm.exception))
        with self.assertRaises(ValueError):
            pt.import_any({"schema": "flh_practice_packet_v9"}, ret)

    def test_previous_latest_survives_losing_the_first_session(self):
        p1 = self.w.export3()
        d = self.tmp / "session-1"
        pt.write_packet3(p1, str(d), "codex")
        shutil.rmtree(d)
        p2 = self.w.export3(previous="latest")
        self.assertEqual(p2["continuity"]["previous_packet_id"], p1["packet_id"])
        self.assertTrue((Path(self.w.path) / "packets" / f"{p1['packet_id']}.json").exists())
        self.assertNotIn("conversation", json.dumps(p2["continuity"]))


class Feeds(Tmp):
    def test_v1_bundle_unchanged_and_still_verifies(self):
        d = FIX / "workbooks"
        for line in (d / "SHA256SUMS").read_text().splitlines():
            h, n = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((d / n).read_bytes()).hexdigest(), h, n)
        self.assertEqual(subprocess.run([sys.executable, "-I", "-B", str(d / "verify.py"), str(d)], capture_output=True).returncode, 0)

    def test_bundle2_is_sealed_and_its_checker_is_the_module(self):
        d = FIX / "workbooks2"
        for line in (d / "SHA256SUMS").read_text().splitlines():
            h, n = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((d / n).read_bytes()).hexdigest(), h, n)
        self.assertEqual((d / "check_feed_compat.py").read_bytes(), (ROOT / "flh_extraction" / "feed_compat.py").read_bytes())
        feeds = sorted(str(p) for p in d.glob("feed-*.json"))
        ok = subprocess.run([sys.executable, "-I", "-B", str(d / "check_feed_compat.py"), *feeds, "--replay", str(d / "replay-cases.json")],
                            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        old = subprocess.run([sys.executable, "-I", "-B", str(d / "check_feed_compat.py"), str(FIX / "workbooks" / "feed-y-en-demo-r2.json"),
                              "--strict-consumer"], capture_output=True, text=True)
        self.assertEqual(old.returncode, 1)
        self.assertIn("all-withdrawn feed is refused", old.stdout)

    def test_storage_rows_check_runs_without_the_extraction_package(self):
        d = FIX / "workbooks2"
        self.assertEqual((d / "check_storage_rows.py").read_bytes(), (ROOT / "flh_extraction" / "storage_check.py").read_bytes())
        self.assertEqual((d / "storage-proposed-0NN.sql").read_bytes(), (FIX / "storage" / "workbooks-proposed-0NN.sql").read_bytes())
        r = subprocess.run([sys.executable, "-I", "-B", str(d / "check_storage_rows.py"), str(d)], capture_output=True, text=True, cwd=str(self.tmp))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("as_proposed: stored", r.stdout)
        self.assertIn("refused 2", r.stdout)

    def test_feed_sequence_withdraws_and_restores_without_silent_reactivation(self):
        b = {n: load("workbooks2", n) for n in os.listdir(FIX / "workbooks2") if n.startswith("feed-")}
        f2, f3, f4, f5 = (b[n] for n in sorted(b)[1:])
        agent = f2["added"]
        self.assertEqual(len(agent), 1)
        self.assertEqual([x["practice_id"] for x in f3["withdrawn"]], agent)
        self.assertEqual(f3["withdrawn"][0]["reason_code"], "rule_not_approved")
        self.assertEqual(f4["withdrawn"][0]["reason_code"], "awaiting_confirmation")
        self.assertNotIn(agent[0], [p["practice_id"] for p in f4["items"]])
        self.assertEqual(f5["restored"], agent)
        for f in (f2, f3, f4, f5):
            self.assertEqual(fc.contract_issues(f), [])
            self.assertEqual(fc.consumer_issues(f), [])
            self.assertTrue(all(p["source_revision"]["revision_sha256"] == f["source"]["revision_sha256"] for p in f["items"]))
            self.assertFalse(fc._keys(f["items"]) & fc.NEVER)

    def test_replay_and_repeat_restore_change_nothing(self):
        cases = load("workbooks2", "replay-cases.json")["cases"]
        self.assertEqual(cases["replay-every-feed"]["expect"]["items"], cases["in-order"]["expect"]["items"])
        self.assertEqual(cases["repeat-restore"]["expect"]["actions"][-2:], ["replay", "replay"])
        self.assertEqual(cases["late-old-feed"]["expect"]["actions"][-1], "stale")
        self.assertEqual(cases["missed-awaiting-feed"]["expect"]["items"], cases["in-order"]["expect"]["items"])
        self.assertEqual(fc.run_replay({"cases": cases}, lambda n: load("workbooks2", n)), [])

    def test_feed_id_detects_tampering(self):
        f = load("workbooks2", "feed-2-r1-newly-approved.json")
        f["items"][0]["prompt"] += " (changed)"
        self.assertIn("feed_id does not match the feed's content", fc.contract_issues(f))
        f = load("workbooks2", "feed-1-r1.json")
        f["items"][0]["due_at"] = "2026-11-20"
        self.assertTrue(any("never carries" in x for x in fc.contract_issues(f)))


class Storage(Tmp):
    def test_round_trip_through_the_proposed_tables(self):
        w, ids = self.a_en_decided()
        p1 = w.export3()
        w.exercise(p1, load("switch2", "codex-a-en.json"), "e1", "approve")
        w.answer(w.exercise_decisions()[0]["practice_id"], "à")
        a = st.round_trip(w, amended=False)
        self.assertEqual(len(a["refused_by_constraints"]), 1)
        self.assertIn("subject_kind", a["refused_by_constraints"][0])
        self.assertTrue(a["learner_visible_differences"], "as proposed, the attestation and batch provenance are lost")
        b = st.round_trip(w, amended=True)
        self.assertEqual((b["refused_by_constraints"], b["learner_visible_differences"], b["exercise_decisions_stored"]), ([], [], 1))
        self.assertTrue(a["resend_refused_by_operation_key"] and b["resend_refused_by_operation_key"])
        c = st.round_trip(w, amended=True, keep_answer_text=False)
        self.assertEqual(c["answer_texts_stored"], 0)
        exp = st.export_attempts(w.attempts())
        self.assertTrue(all("text" not in r and r["text_omitted"] for r in exp))

    def test_history_keeps_withdrawn_outcomes(self):
        feeds = [load("workbooks2", n) for n in sorted(os.listdir(FIX / "workbooks2")) if n.startswith("feed-")]
        h = {x["practice_id"]: x for x in st.history(None, feeds[:3])}
        wd = feeds[2]["withdrawn"][0]["practice_id"]
        self.assertEqual(h[wd]["status"], "withdrawn")
        self.assertTrue(h[wd]["outcomes"])
        self.assertEqual(h[wd]["retracted"]["reason_code"], "rule_not_approved")


class Demo3(Tmp):
    def test_demo3_check(self):
        r = cli("demo3", "--out", str(self.tmp / "demo"), "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("check: every output equals the shipped expected file", r.stdout)

    def test_older_demos_unchanged(self):
        for cmd, out in (("demo", "d1"), ("demo2", "d2")):
            r = subprocess.run([sys.executable, "-B", "-m", "flh_extraction", "practice", cmd, "--out", str(self.tmp / out), "--check"], cwd=ROOT,
                               capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT)})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_feed_cli_with_previous(self):
        w, ids = self.a_en_decided()
        f1 = self.tmp / "f1.json"
        self.assertEqual(cli("feed", "--work", w.path, "--out", str(f1), "--seq", "1").returncode, 0)
        w.revise(str(FIX / "a_en_lieux.r2.json"))
        f2 = self.tmp / "f2.json"
        r = cli("feed", "--work", w.path, "--out", str(f2), "--seq", "2", "--previous", str(f1))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(fc.contract_issues(json.loads(f2.read_text(encoding="utf-8"))), [])
        self.assertTrue(feed2.RECALL)


if __name__ == "__main__":
    unittest.main()
