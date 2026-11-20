"""R4 extraction: corpus, grounding quality, lifecycle, learning loop, agent exchange, feed interop (offline, synthetic)."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from flh_extraction import exchange as xc  # noqa: E402
from flh_extraction import feed_compat as fc  # noqa: E402
from flh_extraction import feed_interop as fi  # noqa: E402
from flh_extraction import grounding_quality as gq  # noqa: E402
from flh_extraction import loop as lp  # noqa: E402
from flh_extraction import practice as pr  # noqa: E402

R4 = ROOT / "fixtures" / "r4_v1"


def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*a)


class Fixtures(unittest.TestCase):
    """Every R4 fixture directory equals a fresh run (fixed file names and bytes; R4-EXT-069)."""

    def test_corpus_and_current_results(self):
        import r4_corpus
        self.assertEqual(quiet(r4_corpus.main, ["--check"]), 0)

    def test_baseline_is_frozen_and_differs_only_where_r4_changed_it(self):
        import r4_corpus
        base = json.loads((R4 / "baseline" / "summary.json").read_text(encoding="utf-8"))
        cur = json.loads((R4 / "current" / "summary.json").read_text(encoding="utf-8"))
        changed = {c["name"] for c in r4_corpus.compare(base, cur)}
        self.assertEqual(changed, {"service", "10-feed-r3-awaiting", "12-feed-r3-restored"})
        self.assertEqual(next(s for s in base["scenarios"] if s["name"] == "10-feed-r3-awaiting")["status"], 422)
        with self.assertRaises(SystemExit):
            quiet(r4_corpus.main, ["--freeze-baseline"])

    def test_lifecycle_loop_and_exchange_fixtures(self):
        import r4_exchange
        import r4_lifecycle
        import r4_loop
        for mod in (r4_lifecycle, r4_loop, r4_exchange):
            self.assertEqual(quiet(mod.main, ["--check"]), 0, mod.__name__)


class Grounding(unittest.TestCase):
    def setUp(self):
        self.rep = gq.evaluate()

    def test_annotations_frozen_before_the_candidate(self):
        self.assertEqual(pr.sha((R4 / "quality" / "annotations.json").read_text(encoding="utf-8")),
                         "448426d841ddd4f9bbe00483a260b2dc1fe1926b917855fb4270c5c73145ed05")

    def test_baseline_errors_are_reproducible(self):
        s = self.rep["summary"]
        self.assertEqual((s["exact_v1"]["correct"], s["exact_v1"]["errors"]),
                         (11, {"false_support_contradiction": 3, "false_support_unrelated": 2, "missed_variant": 2}))
        self.assertEqual(s["folded_v1"]["errors"].get("variant_accepted_silently"), 2)

    def test_candidate_only_adds_review_and_fixes_negation_and_variants(self):
        rows = {r["ref"]: r for r in self.rep["items"]}
        for r in rows.values():
            b, c = r["exact_v1"]["outcome"], r["exact_v1+checks_v2"]["outcome"]
            self.assertTrue(b == c or c == "review", r["ref"])
        for ref in ("n2", "n5", "a2", "a3"):
            self.assertEqual(rows[ref]["exact_v1+checks_v2"]["category"], "correct", ref)
        self.assertEqual(self.rep["summary"]["exact_v1+checks_v2"]["correct"], 15)
        self.assertEqual(sorted(k for k, r in rows.items() if r["exact_v1+checks_v2"]["category"] != "correct"), ["n6", "p3", "p5"])

    def test_negation_cue_respects_clause_and_claim_polarity(self):
        self.assertIsNotNone(gq.negated_quote("« en Japon » is correct French.", "On ne dit pas en Japon"))
        self.assertIsNone(gq.negated_quote("« en Japon » is wrong: it is not said.", "On ne dit pas en Japon"))
        self.assertIsNone(gq.negated_quote("« Je reste en France » is correct French.", "il n'a rien corrigé : « Je reste en France » était juste"))

    def test_report_file_is_current(self):
        self.assertEqual(json.loads((R4 / "quality" / "report.json").read_text(encoding="utf-8"))["summary"], self.rep["summary"])


class Loop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import r4_loop
        cls.s = r4_loop.states()
        cls.pid = next(p["practice_id"] for p in cls.s["r1"]["prac"]["items"] if p["kind"] == "choose")

    def test_order_rules_and_validation(self):
        r1 = self.s["r1"]
        a = lp.start(r1["res"], r1["prac"], self.pid)
        with self.assertRaises(lp.LoopError):
            lp.retry(a, r1["prac"], "en")
        a = lp.reveal(a, r1["prac"], r1["sources"])
        with self.assertRaises(lp.LoopError):
            lp.recall(a, r1["prac"], "en")
        self.assertEqual(lp.validate(a), [])
        bad = copy.deepcopy(a)
        bad["events"].insert(0, {"seq": 0, "event": "retry"})
        self.assertTrue(lp.validate(bad))

    def test_discard_never_keeps_answer_text(self):
        r1 = self.s["r1"]
        a = lp.start(r1["res"], r1["prac"], self.pid, retention="discard")
        a = lp.recall(a, r1["prac"], "y")
        self.assertIsNone(a["events"][0]["answer"])
        k = lp.recall(lp.start(r1["res"], r1["prac"], self.pid), r1["prac"], "y")
        k = lp.set_retention(k, "discard")
        self.assertEqual((k["events"][0]["answer"], k["events"][-1]["answers_removed"], lp.validate(k)), (None, 1, []))

    def test_revisit_returns_to_the_original_evidence(self):
        r1, r2 = self.s["r1"], self.s["r2"]
        a = lp.reveal(lp.start(r1["res"], r1["prac"], self.pid), r1["prac"], r1["sources"])
        v = lp.revisit(a, r2["res"], r2["prac"], r2["sources"])["events"][-1]
        self.assertEqual(v["practice"]["status"], "withdrawn")
        self.assertTrue(all(e["verified"] for e in v["original_evidence"]))
        for e in v["original_evidence"]:
            text = pr.fold(r1["sources"][e["source_revision"]]["capture"][e["field"]])
            self.assertEqual(text[e["start"]:e["end"]], e["quote"])

    def test_unapproved_units_have_no_pointer(self):
        r2 = self.s["r2"]
        with self.assertRaises(lp.LoopError):
            lp.start(r2["res"], r2["prac"], self.pid)


class Experiment(unittest.TestCase):
    def test_preregistered_result_and_branch(self):
        from flh_extraction import leakage
        pre = json.loads((ROOT / "experiments" / "r4-retrieval-leakage.prereg.json").read_text(encoding="utf-8"))
        self.assertEqual(pr.sha((ROOT / "experiments" / "r4-retrieval-leakage.prereg.json").read_text(encoding="utf-8")),
                         "90955c7322767ff1dbcbbc82b41dc839ec70c258af133184bfd94017625f7995")
        rep = leakage.run(pre)
        self.assertEqual((rep["items"], rep["M1"], rep["M2"], rep["decision"]), (20, 0.0, 0.2, "branch_A"))
        self.assertEqual(rep, json.loads((ROOT / "experiments" / "r4-retrieval-leakage.result.json").read_text(encoding="utf-8")))

    def test_branch_a_labels_a_recall_after_reading(self):
        import r4_loop
        r1 = r4_loop.states()["r1"]
        pid = next(p["practice_id"] for p in r1["prac"]["items"] if p["kind"] == "explain")
        a = lp.start(r1["res"], r1["prac"], pid)
        self.assertEqual(lp.next_step(a), "recall")
        self.assertEqual(lp.recall(a, r1["prac"], "x")["events"][-1]["retrieval"], "unaided")
        b = lp.recall(lp.read(a, r1["res"], r1["sources"]), r1["prac"], "x")
        self.assertEqual(b["events"][-1]["retrieval"], "after_reading")
        b["events"][-1]["retrieval"] = "unaided"
        self.assertTrue(lp.validate(b))


class Exchange(unittest.TestCase):
    def setUp(self):
        self.ctx = json.loads((R4 / "exchange" / "context.json").read_text(encoding="utf-8"))
        self.ret = json.loads((R4 / "exchange" / "return-codex.json").read_text(encoding="utf-8"))

    def test_markdown_body_is_agent_neutral(self):
        a, b = xc.markdown(self.ctx, "claude-code"), xc.markdown(self.ctx, "codex")
        self.assertEqual(a.split("\n", 1)[1], b.split("\n", 1)[1])
        self.assertNotEqual(a.split("\n", 1)[0], b.split("\n", 1)[0])

    def test_preview_applies_nothing_and_classifies(self):
        pv = xc.import_preview(self.ctx, self.ret)
        self.assertFalse(pv["applied"])
        self.assertEqual([r["class"] for r in pv["rows"]], ["candidate", "duplicate", "uncited"])

    def test_versions_and_tampering_are_refused_with_recovery(self):
        for doc, code in (({**self.ret, "schema": "flh_agent_corrections_v2"}, "unsupported_return"),
                          ({**self.ret, "context_id": "cx-000000000000"}, "other_context")):
            with self.assertRaises(xc.ExchangeError) as cm:
                xc.import_preview(self.ctx, doc)
            self.assertEqual(cm.exception.code, code)
            self.assertIn("import-preview", cm.exception.recovery)
        with self.assertRaises(xc.ExchangeError) as cm:
            xc.import_preview({**self.ctx, "units": []}, self.ret)
        self.assertEqual(cm.exception.code, "altered_context")
        self.assertIn("export", cm.exception.recovery)

    def test_cli_refusal_exit_code(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            rc = xc.main(["import-preview", "--context", str(R4 / "exchange" / "context.json"), "--return", str(R4 / "exchange" / "README.md")])
        self.assertEqual(rc, 2)
        self.assertIn("recovery:", err.getvalue())

    def test_packet_carries_no_answer_and_no_private_data(self):
        text = json.dumps(self.ctx, ensure_ascii=False)
        for k in ('"hidden"', '"accepted"', '"rubric', '"answer":'):
            self.assertNotIn(k, text)
        from flh_extraction import packet as pk
        self.assertEqual(pk.privacy_findings(text), [])


class Interop(unittest.TestCase):
    def test_merged_mirror_accepts_every_sample_and_the_old_one_is_kept(self):
        rep = fi.report()
        self.assertTrue(rep["ok"], rep["summary"])
        self.assertEqual(rep["summary"]["merged_mirror_refuses"], [])
        self.assertTrue(rep["summary"]["increment_4_mirror_refuses"])  # historical, unchanged on purpose
        self.assertEqual(rep["unknown_reason_code"]["kept"], "future_code_v9")

    def test_reason_code_examples_cover_all_five_codes(self):
        codes = set()
        for n in ("08-feed-withdrawn-reason-codes.response.json", "09-feed-awaiting-confirmation.response.json"):
            f = json.loads((ROOT / "fixtures" / "service_v1" / n).read_text(encoding="utf-8"))["body"]["feed"]
            self.assertEqual(fc.contract_issues(f), [])
            codes |= {w["reason_code"] for w in f["withdrawn"]}
        w2 = json.loads((ROOT / "fixtures" / "practice_v1" / "workbooks2" / "feed-3-r2-withdrawn.json").read_text(encoding="utf-8"))
        codes |= {w["reason_code"] for w in w2["withdrawn"]}
        self.assertEqual(codes, set(fc.REASONS))


if __name__ == "__main__":
    unittest.main()
