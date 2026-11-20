"""Extraction 2.1 (flh_extraction.practice_flow and the batch / v2 / accept additions): offline, synthetic data."""

from __future__ import annotations

import json
import os
import re
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
from flh_extraction import practice_flow as pf  # noqa: E402
from flh_extraction import practice_workflow as pw  # noqa: E402

FIX = ROOT / "fixtures" / "practice_v1"
BUNDLE = FIX / "workbooks"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def run_cli(*args):
    return subprocess.run([sys.executable, "-B", "-m", "flh_extraction", "practice", *args], cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(ROOT)})


class Tmp(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def session_one(self):
        """The worked example up to the first packet: short path, flagged claim rejected, one correct answer."""
        w = pw.Work(str(self.tmp / "w"))
        w.init(str(FIX / "y_en.r1.json"), with_review=True)
        ids = pf._ids(w.draft())
        w.approve_batch(w.review()["batch_id"])
        w.decide(ids["en-mouvement"], "reject", reason="spotted in the review: that quote is not in my text")
        prac = w.practice(rebuild=True)
        w.answer(pf._pid(prac, "choose", ids["ex-piscine"]), "y")
        return w, ids, w.export("study")


class ShortPath(Tmp):
    def test_the_batch_holds_only_supported_items_and_practice_examples_and_names_the_rest(self):
        for name, flagged in (("y_en.r1.json", "en-mouvement"), ("savoir_connaitre.json", "savoir-personnes")):
            drf = pr.draft(load(name))
            res = pr.resolve(drf, [])
            rv = pr.batch_review(res)
            self.assertTrue(all(m["support"] in pr.BATCH_SUPPORT for m in rv["members"]))
            fid = next(i["item_id"] for i in drf["items"] if i["proposal_ref"] == flagged)
            self.assertEqual([r["item_id"] for r in rv["left_for_you"]], [fid])
            self.assertTrue(rv["left_for_you"][0]["why"].startswith("UNSUPPORTED: « "))
            text = pr.render_review(rv)
            self.assertIn(fid, text.split("Decide yourself, one by one")[1])
            self.assertNotIn(fid, text.split("Decide yourself, one by one")[0])

    def test_the_batch_id_binds_exactly_what_was_shown(self):
        drf = pr.draft(load("y_en.r1.json"))
        res = pr.resolve(drf, [])
        bid = pr.batch_review(res)["batch_id"]
        self.assertRegex(bid, r"^b-[0-9a-f]{12}$")
        with self.assertRaisesRegex(ValueError, "is not the batch shown now"):
            pr.batch_decisions(drf, res, "b-000000000000", 1)
        one = [pr.decision(drf, pr.batch_review(res)["members"][0]["item_id"], "approve", 1)]
        with self.assertRaisesRegex(ValueError, "changed; review again"):  # a decision since the review makes it stale
            pr.batch_decisions(drf, pr.resolve(drf, one), bid, 2)
        members = [m["item_id"] for m in pr.batch_review(res)["members"]]
        with self.assertRaisesRegex(ValueError, "not in batch"):
            pr.batch_decisions(drf, res, bid, 1, except_ids=["k-5ca79503ae78"])  # the flagged claim is never a member
        with self.assertRaisesRegex(ValueError, "every batch member was excepted"):
            pr.batch_decisions(drf, res, bid, 1, except_ids=members)
        ds = pr.batch_decisions(drf, res, bid, 1, except_ids=[members[-1]])
        after = pr.resolve(drf, ds)
        self.assertEqual(after["states"]["approved"], len(members) - 1)
        nxt = pr.batch_review(after)
        self.assertEqual([m["item_id"] for m in nxt["members"]], [members[-1]])  # the excepted item is still the learner's
        self.assertNotEqual(nxt["batch_id"], bid)

    def test_batch_approvals_are_ordinary_learner_decisions(self):
        drf = pr.draft(load("y_en.r1.json"))
        res = pr.resolve(drf, [])
        ds = pr.batch_decisions(drf, res, pr.batch_review(res)["batch_id"], 1, reason="checked each excerpt")
        lines = [json.dumps(d, ensure_ascii=False) for d in ds]
        back = pr.read_decisions(lines)  # the same append-only schema as single decisions
        self.assertEqual(back, ds)
        for d in ds:
            self.assertEqual((d["schema"], d["action"], d["reason"]), (pr.DECISION_SCHEMA, "approve", "checked each excerpt"))
            self.assertEqual(d["batch"]["size"], len(ds))
            self.assertEqual(d["based_on"]["item_hash"], next(i["item_hash"] for i in drf["items"] if i["item_id"] == d["item_id"]))
        r = pr.resolve(drf, ds)
        self.assertTrue(all(i.get("batch_id") == ds[0]["batch"]["batch_id"] for i in r["items"] if i["state"] == "approved"))
        prac = pr.build_practice(r)
        self.assertTrue(all(p["evidence_ids"] for p in prac["items"]))  # every exercise still links to evidence

    def test_revised_and_uncertain_items_are_never_batched_and_say_why(self):
        drf = pr.draft(load("y_en.r1.json"))
        ds = pr.batch_decisions(drf, pr.resolve(drf, []), pr.batch_review(pr.resolve(drf, []))["batch_id"], 1)
        r2 = pr.draft(load("y_en.r2.json"))
        rv = pr.batch_review(pr.resolve(r2, ds), {1: drf, 2: r2})
        self.assertIsNone(rv["batch_id"])
        changed = {r["item_id"]: r for r in rv["left_for_you"] if r["state"] == "needs_review"}
        self.assertEqual(sorted(changed), ["k-0d3281b28da6", "k-40cbe73ae3f5"])
        for r in changed.values():
            self.assertIn("CHANGED IN REVISION 2", r["why"])
            self.assertEqual(r["changes"], ["quote « Je viens de la boulangerie, j'en viens. »: located in revision 1 -> not_found now"])
        with self.assertRaisesRegex(ValueError, "nothing can be approved together"):
            pr.batch_decisions(r2, pr.resolve(r2, ds), "b-000000000000", 99)
        q = pr.draft(load("en_quantite.json"))
        left = pr.batch_review(pr.resolve(q, []))["left_for_you"]
        self.assertTrue(left and all(r["why"].startswith("UNCERTAIN") for r in left))

    def test_measured_steps_before_and_after_with_the_same_outcome(self):
        rep, shown = pf.measure(str(self.tmp / "m"))
        rows = {(r["source_id"], r["revision"]): r for r in rep["rows"]}
        self.assertEqual({k: (r["before"]["steps"], r["after"]["steps"]) for k, r in rows.items()},
                         {("y-en-demo", 1): (9, 3), ("savoir-connaitre-demo", 1): (9, 3), ("y-en-demo", 2): (5, 4)})
        for k in (("y-en-demo", 1), ("savoir-connaitre-demo", 1)):
            r = rows[k]
            for flag in ("same_approved_items", "same_practice_ids", "same_evidence_links", "one_learner_decision_per_approved_item",
                         "left_named_in_review", "left_still_pending"):
                self.assertIs(r[flag], True, (k, flag))
            self.assertEqual((r["approved_items"], r["practice_items"], r["exercises_tied_to_evidence"]), (6, 5, 5))
            self.assertEqual(len(r["left_for_learner"]), 1)
        self.assertIs(rows[("y-en-demo", 2)]["same_practice_ids_as_revision_1"], True)
        self.assertEqual(rows[("y-en-demo", 2)]["changed_items_decided_one_by_one"], 2)
        self.assertEqual(pr.dumps(rep), (FIX / "expected2" / "01-steps.json").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            pf.measure(str(self.tmp / "m"))


class SecondContrast(unittest.TestCase):
    def test_savoir_connaitre_grounds_flags_and_grades(self):
        drf = pr.draft(load("savoir_connaitre.json"))
        self.assertEqual({k: v for k, v in drf["counts"].items() if v}, {"supported": 4, "unsupported": 1, "generated": 2})
        bad = next(i for i in drf["items"] if i["proposal_ref"] == "savoir-personnes")
        self.assertEqual((bad["support"], bad["heuristic_class"]), ("unsupported", "anchored"))  # lexical anchoring misses it
        res = pr.resolve(drf, pr.batch_decisions(drf, pr.resolve(drf, []), pr.batch_review(pr.resolve(drf, []))["batch_id"], 1))
        prac = pr.build_practice(res)
        self.assertEqual(prac["counts"], {"explain": 1, "choose": 2, "produce": 2})
        self.assertEqual(sum(1 for p in prac["items"] if p["new_sentence"]), 4)
        by = {(p["kind"], p["knowledge_ids"][0]): p for p in prac["items"]}
        ids = {i["proposal_ref"]: i["item_id"] for i in drf["items"]}
        self.assertEqual(by[("choose", ids["ex-frere"])]["options"], ["connais", "sais"])
        cases = [(("produce", "ex-frere"), "oui, je le connais", "correct"), (("produce", "ex-nager"), "Oui, je connais nager.", "incorrect"),
                 (("produce", "ex-frere"), "Oui, je le connais bien.", "self_check"), (("choose", "ex-nager"), "sais", "correct"),
                 (("choose", "ex-nager"), "conait", "invalid")]
        for (kind, ref), text, want in cases:
            self.assertEqual(pr.grade(by[(kind, ids[ref])], text)["outcome"], want, text)


class AgentSwitch(Tmp):
    def test_the_fixtures_name_the_packets_this_flow_produces(self):
        w, ids, p1 = self.session_one()
        self.assertEqual(load("switch/codex-return.json")["packet_id"], p1["packet_id"])
        self.assertEqual(p1["schema"], pk.PACKET_SCHEMA_V2)
        self.assertIsNone(p1["last_confusion"])
        self.assertEqual((p1["next_exercise"]["kind"], p1["next_exercise"]["why"]), ("explain", "the first exercise not yet answered correctly"))

    def test_only_an_accepted_candidate_from_this_packet_and_revision_is_accepted(self):
        w, ids, p1 = self.session_one()
        ret = load("switch/codex-return.json")
        for pid, msg in (("c2", "is duplicate"), ("c3", "only corrections"), ("zz", "no proposal")):
            with self.assertRaisesRegex(ValueError, msg):
                w.accept(p1, ret, pid)
        with self.assertRaisesRegex(ValueError, "names packet"):
            w.accept(p1, {**ret, "packet_id": "pk-000000000000"}, "c1")
        n = len(w.decisions())
        d = w.accept(p1, ret, "c1")
        self.assertEqual((d["action"], d["item_id"], d["via"]["agent"], d["via"]["proposal_id"], d["via"]["packet_id"]),
                         ("edit", ids["y-vs-en"], "codex", "c1", p1["packet_id"]))
        self.assertEqual(len(w.decisions()), n + 1)
        with self.assertRaisesRegex(ValueError, "already says this"):
            w.accept(p1, ret, "c1")
        w.revise(str(FIX / "y_en.r2.json"))
        with self.assertRaisesRegex(ValueError, "another revision"):
            w.accept(p1, {**ret, "proposals": [{**ret["proposals"][0], "text": "Another wording."}]}, "c1")

    def test_the_updated_packet_continues_the_session(self):
        w, ids, p1 = self.session_one()
        w.accept(p1, load("switch/codex-return.json"), "c1")
        prac = w.practice(rebuild=True)
        w.answer(pf._pid(prac, "produce", ids["ex-marche"]), "Oui, j'y reviens.")
        p2 = w.export("study", previous=p1)
        self.assertEqual(p2["packet_id"], load("switch/claude-code-return.json")["packet_id"])
        self.assertEqual({k["id"] for k in p2["knowledge"]}, {k["id"] for k in p1["knowledge"]})
        k = next(x for x in p2["knowledge"] if x["id"] == ids["y-vs-en"])
        self.assertEqual(k["accepted_from"], {"agent": "codex", "packet_id": p1["packet_id"], "proposal_id": "c1"})
        self.assertTrue(k["learner_corrected"])
        c = p2["continuity"]
        self.assertEqual((c["previous_packet_id"], c["knowledge_ids_kept"], [x["id"] for x in c["changed"]]), (p1["packet_id"], 6, [ids["y-vs-en"]]))
        last = p2["last_confusion"]
        self.assertEqual((last["forms"], last["kind"], last["resolved_later"]), (["y", "en"], "produce", False))
        nx = p2["next_exercise"]
        self.assertEqual((nx["kind"], nx["knowledge_ids"][0], nx["rule"]), ("produce", ids["ex-piscine"], pk.NEXT_RULE))
        shared = pr.dumps(p2) + pk.markdown(p2)
        self.assertNotIn("Oui, j'y reviens.", shared)  # the attempt text stays local
        keys, _ = pf.answer_keys(w.practice(), shared)
        self.assertTrue(keys)
        self.assertEqual([x for x in keys if x in shared], [])
        md = pk.markdown(p2)
        self.assertLess(md.index("## Where we left off"), md.index("## Approved knowledge"))
        self.assertIn(f"Continues packet `{p1['packet_id']}`", md)

    def test_the_second_agent_cannot_replace_the_accepted_correction(self):
        p2 = load("expected2/07-packet-2-claude-code.json")
        rep = pk.import_preview(p2, load("switch/claude-code-return.json"))
        self.assertEqual({r["proposal_id"]: r["class"] for r in rep["rows"]},
                         {"q1": "conflict", "q2": "accepted_candidate", "q3": "duplicate", "q4": "unknown_reference"})
        self.assertTrue(rep["packet_matches"] and rep["read_only"])

    def test_next_exercise_rule(self):
        ex = [{"id": "p-e", "kind": "explain", "knowledge_ids": ["k-c"]},
              {"id": "p-a1", "kind": "choose", "knowledge_ids": ["k-a", "k-c"]}, {"id": "p-a2", "kind": "produce", "knowledge_ids": ["k-a", "k-c"]},
              {"id": "p-b1", "kind": "choose", "knowledge_ids": ["k-b", "k-c"]}, {"id": "p-b2", "kind": "produce", "knowledge_ids": ["k-b", "k-c"]}]
        miss = {"practice_id": "p-a1", "contrast_id": "k-c", "resolved_later": False}
        self.assertEqual(pk.next_exercise(ex, [], None)["id"], "p-e")
        self.assertEqual(pk.next_exercise(ex, [], miss)["id"], "p-b2")  # other sentence, production first
        self.assertEqual(pk.next_exercise(ex, [{"practice_id": "p-b2", "outcome": "correct"}], miss)["id"], "p-b1")
        done = [{"practice_id": p, "outcome": "correct"} for p in ("p-b1", "p-b2")]
        self.assertEqual(pk.next_exercise(ex, done, miss)["id"], "p-e")  # then recall the rule itself
        self.assertEqual(pk.next_exercise(ex, done, {**miss, "resolved_later": True})["id"], "p-e")
        all_done = [{"practice_id": x["id"], "outcome": "correct"} for x in ex]
        self.assertIsNone(pk.next_exercise(ex, all_done, None))

    def test_version_1_packets_are_unchanged(self):
        w, _, _ = self.session_one()
        v1 = w.export("study", version=1)
        self.assertEqual(v1["schema"], pk.PACKET_SCHEMA)
        self.assertFalse({"last_confusion", "next_exercise", "continuity"} & set(v1))
        self.assertNotIn("## Where we left off", pk.markdown(v1))
        with self.assertRaises(ValueError):
            w.export("study", version=1, previous=v1)
        with self.assertRaisesRegex(ValueError, "another source"):
            w.export("study", previous={**v1, "source": {**v1["source"], "source_id": "other"}})

    def test_cli_short_path_accept_and_continue(self):
        W, S1, S2 = str(self.tmp / "w"), str(self.tmp / "s1"), str(self.tmp / "s2")
        r = run_cli("init", "--source", str(FIX / "y_en.r1.json"), "--work", W)
        self.assertEqual(r.returncode, 0, r.stderr)
        bid = re.search(r"--approve-batch (b-[0-9a-f]{12})", r.stdout).group(1)
        self.assertEqual(run_cli("decide", "--work", W, "--approve-batch", bid, "--item", "k-5ca79503ae78").returncode, 2)
        r = run_cli("decide", "--work", W, "--approve-batch", bid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("still yours to decide one by one: k-5ca79503ae78 (UNSUPPORTED)", r.stdout)
        self.assertEqual(run_cli("decide", "--work", W, "--approve-batch", bid).returncode, 2)  # stale: already used
        steps = [("decide", "--work", W, "--item", "k-5ca79503ae78", "--reject", "--reason", "spotted in the review: that quote is not in my text"),
                 ("build", "--work", W), ("answer", "--work", W, "--item", "p-22a947cd7f5c", "--text", "y"),
                 ("export", "--work", W, "--out", S1)]
        for s in steps:
            r = run_cli(*s)
            self.assertEqual(r.returncode, 0, (s, r.stderr))
        self.assertEqual(json.loads(Path(S1, "packet.json").read_text(encoding="utf-8"))["packet_id"], load("switch/codex-return.json")["packet_id"])
        ret = str(FIX / "switch" / "codex-return.json")
        self.assertEqual(run_cli("accept", "--work", W, "--packet", f"{S1}/packet.json", "--proposals", ret, "--proposal", "c2").returncode, 2)
        r = run_cli("accept", "--work", W, "--packet", f"{S1}/packet.json", "--proposals", ret, "--proposal", "c1")
        self.assertEqual(r.returncode, 0, r.stderr)
        for s in (("build", "--work", W), ("answer", "--work", W, "--item", "p-664f7533a19d", "--text", "Oui, j'y reviens."),
                  ("export", "--work", W, "--previous", f"{S1}/packet.json", "--out", S2)):
            r = run_cli(*s)
            self.assertEqual(r.returncode, 0, (s, r.stderr))
        self.assertEqual(Path(S2, "packet.json").read_text(encoding="utf-8"), (FIX / "expected2" / "07-packet-2-claude-code.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(os.listdir(S2)), ["PROMPT-claude-code.md", "PROMPT-codex.md", "packet.json", "packet.md"])


class WorkbooksBundle(Tmp):
    def verify(self, d):
        return subprocess.run([sys.executable, "-I", "-B", str(Path(d) / "verify.py"), str(d)], capture_output=True, text=True)

    def test_the_shipped_bundle_is_sealed_and_every_case_holds(self):
        r = self.verify(BUNDLE)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("verify: OK", r.stdout)
        man = json.loads((BUNDLE / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(f["source_id"] for f in man["feeds"]), ["savoir-connaitre-demo", "y-en-demo", "y-en-demo", "y-en-demo"])
        self.assertEqual(sorted(man["outcomes_present"]), sorted(man["attempt_outcomes"]))
        self.assertEqual(pk.privacy_findings("".join((BUNDLE / n).read_text(encoding="utf-8") for n in sorted(os.listdir(BUNDLE)))), [])

    def test_verify_catches_a_schedule_a_broken_seal_and_a_leaked_answer(self):
        def copy():
            d = self.tmp / f"b{len(os.listdir(self.tmp))}"
            shutil.copytree(BUNDLE, d)
            return d
        d = copy()
        f = json.loads((d / "feed-y-en-demo-r1.json").read_text(encoding="utf-8"))
        f["items"][0]["due_at"] = "2026-11-20"
        (d / "feed-y-en-demo-r1.json").write_text(pr.dumps(f), encoding="utf-8")
        r = self.verify(d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not match its SHA-256", r.stdout)
        (d / "SHA256SUMS").write_text(pf.seal(str(d)), encoding="utf-8")
        r = self.verify(d)
        self.assertIn("keys that a feed never carries: ['due_at']", r.stdout)
        d = copy()
        with open(d / "study-packet.md", "a", encoding="utf-8") as fh:
            fh.write("\nOui, nous y allons.\n")
        (d / "SHA256SUMS").write_text(pf.seal(str(d)), encoding="utf-8")
        r = self.verify(d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("answer keys present", r.stdout)

    def test_withdrawn_appears_only_against_a_previous_feed(self):
        expected = (FIX / "expected" / "07-workbooks-feed.json").read_text(encoding="utf-8")
        self.assertNotIn("withdrawn", expected)  # the HANDOFF-136 feed shape is unchanged
        f1 = json.loads((BUNDLE / "feed-y-en-demo-r1.json").read_text(encoding="utf-8"))
        prac = {"source": {**f1["source"], "source_id": "other"}, "items": []}
        with self.assertRaisesRegex(ValueError, "same source"):
            pk.workbooks_feed(prac, [], previous=f1)

    def test_the_bundle_regenerates_byte_for_byte_and_the_demo_checks(self):
        rc, text = pf.workbooks_bundle(str(self.tmp / "b"), check=True)
        self.assertEqual(rc, 0, text)
        rc, text = pf.demo2(str(self.tmp / "d"), check=True)
        self.assertEqual(rc, 0, text)
        self.assertIn("9 -> 3 steps", text)
        with self.assertRaises(ValueError):
            pf.demo2(str(self.tmp / "d"))


if __name__ == "__main__":
    unittest.main()
