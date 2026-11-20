"""Speaking Lab (flh_speaking.lab): standard library only, runs offline."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

from flh_speaking import lab, textnorm  # noqa: E402
from flh_speaking import review as rv  # noqa: E402


def case(reference, a, b, sha="0" * 64):
    return {"schema": lab.CASE_SCHEMA, "id": "t", "reference": reference, "audio": {"sha256": sha},
            "results": [{"label": "A", "model_id": "m-a", "config_id": "c", "text": a},
                        {"label": "B", "model_id": "m-b", "config_id": "c", "text": b}]}


class Lab(unittest.TestCase):
    def test_edits_agree_with_the_scoring_alignment_including_ties(self):
        pairs = [("a b c", "a x c"), ("a b c", "a c"), ("a b", "a b c"), ("a a a", "a"), ("le chat noir", "chat le noir"),
                 ("", "un mot"), ("deux mots", ""), ("x y z", "z y x"), ("l' élève a lu", "l' eleve a")]
        for r, h in pairs:
            rw, hw = textnorm.words(r), textnorm.words(h)
            ops = lab.edits(rw, hw)
            got = (sum(e["op"] == "sub" for e in ops), sum(e["op"] == "del" for e in ops), sum(e["op"] == "ins" for e in ops))
            self.assertEqual(got, textnorm.align(rw, hw), (r, h))
            self.assertEqual([e["ref"] for e in ops if e["ref"] is not None], rw)
            self.assertEqual([e["hyp"] for e in ops if e["hyp"] is not None], hw)

    def test_accent_change_and_omitted_word(self):
        res = lab.compare(case("L'élève a lu le texte à voix haute.", "L'eleve a lu le texte à voix haute.", "L'élève a lu le texte à haute."))
        a, b = res["results"]
        self.assertEqual((a["counts"]["sub"], a["accent_only_substitutions"]), (1, 1))
        self.assertEqual((b["counts"]["del"], [e["ref"] for e in b["edits"] if e["op"] == "del"]), (1, ["voix"]))
        self.assertEqual(res["status"], lab.STATUS_OK)
        self.assertIn("Not a pronunciation", res["disclaimer"])

    def test_insufficient_and_low_evidence_states(self):
        res = lab.compare(case("[rires] ...", "bonjour", "salut"))
        self.assertEqual((res["status"], list(res["reasons"]), res["results"], res["paired"]), (lab.STATUS_INSUFFICIENT, ["empty_reference"], [], None))
        res = lab.compare(case("Oui.", "Oui.", ""))
        self.assertEqual(res["status"], lab.STATUS_OK)
        self.assertEqual(sorted(res["reasons"]), ["empty_prediction", "short_reference"])
        self.assertEqual(res["paired"]["evidence"], "low")
        self.assertEqual(res["results"][1]["counts"]["del"], 1)

    def test_text_is_rendered_from_the_json_alone(self):
        res = lab.compare(case("Il fait beau ce matin.", "il fait beau ce matin", "il fait bon matin"))
        self.assertEqual(lab.render_text(json.loads(lab.to_json(res))), lab.render_text(res))

    def test_identity_and_refusals(self):
        demo = json.loads(Path(lab.DEMO_CASE).read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(lab.synthetic_audio()).hexdigest(), demo["audio"]["sha256"])
        with self.assertRaises(ValueError):
            lab.compare(demo, "f" * 64)  # another audio file
        bad = dict(demo, results=demo["results"][:1])
        with self.assertRaises(ValueError):
            lab.compare(bad)
        res = lab.compare(demo)
        self.assertEqual([(r["model_id"], r["config_id"]) for r in res["results"]],
                         [("synthetic-transcript-a", "synthetic-config-1"), ("synthetic-transcript-b", "synthetic-config-1")])

    def test_demo_check_matches_the_shipped_expected_output(self):
        rc, text = lab.demo(check=True)
        self.assertEqual(rc, 0, text)
        cli = subprocess.run([sys.executable, "-B", "-m", "flh_speaking", "lab", "demo", "--check"], cwd=PKG, capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertIn("check: output equals", cli.stdout)



THREE = PKG / "fixtures" / "lab" / "three_rows"


def three_rows():
    return lab.batch(lab.read_refs(str(THREE / "refs.jsonl")), *lab.read_results(str(THREE / "a.jsonl")), *lab.read_results(str(THREE / "b.jsonl")))


class Contract(unittest.TestCase):
    def test_normalization_policy_is_versioned_and_pinned(self):
        # A change in normalize_fr changes this fingerprint: bump NORM_VERSION with it.
        self.assertEqual((textnorm.NORM_VERSION, textnorm.policy_fingerprint()),
                         ("flh_fr_asr_norm_v1", "6912bff3a71ec46e62c831a9ee1340b3521941cfdc0cd8107683843b941bba77"))
        self.assertEqual(lab.compare(json.loads(Path(lab.DEMO_CASE).read_text(encoding="utf-8")))["normalization_fingerprint"], textnorm.policy_fingerprint())

    def test_french_forms(self):
        n = textnorm.normalize_fr
        self.assertEqual(n("L’homme l'a vu"), "l' homme l' a vu")            # elision, apostrophe variants
        self.assertEqual(n("Aujourd'hui"), "aujourd' hui")
        self.assertEqual(n("peut-être a-t-il"), "peut être a t il")           # hyphens separate
        self.assertNotEqual(n("élève"), n("eleve"))                            # accents are kept
        self.assertEqual(n("Ce\u0301cile"), n("Cécile"))                     # decomposed == composed
        self.assertEqual(n("cœur Æ"), "coeur ae")                              # ligatures
        self.assertNotEqual(n("1823"), n("mille huit cent vingt-trois"))      # numbers are not converted
        self.assertEqual(n("[rires] « Oui ! » (bruit)"), "oui")                # tags and punctuation

    def test_cased_uncased_and_punctuation_are_reported_apart(self):
        v = lab.views("Bonjour, Léa !", "bonjour Léa")
        self.assertEqual(v["normalized"]["errors"], 0)                         # the words agree
        self.assertEqual(v["uncased_punct"]["errors"], 2)                      # "," and "!" are missing
        self.assertEqual(v["uncased_punct"]["punctuation_edits"], 2)
        self.assertEqual((v["cased_punct"]["errors"], v["cased_punct"]["case_attributable_errors"]), (3, 1))  # + Bonjour/bonjour

    def test_equal_cost_alignment_is_deterministic(self):
        # "a b" vs "b a": two equal-cost alignments exist (2 substitutions, or del+ins pairs); the
        # documented tie-break (diagonal, then deletion, then insertion) always picks substitutions.
        ops = [e["op"] for e in lab.edits(["a", "b"], ["b", "a"])]
        self.assertEqual(ops, ["sub", "sub"])
        self.assertEqual([lab.edits(["x", "y", "z"], ["z", "y", "x"]) for _ in range(3)].count(lab.edits(["x", "y", "z"], ["z", "y", "x"])), 3)

    def test_three_row_aggregate_equals_the_hand_computation(self):
        res = three_rows()
        a, b = res["models"]["A"], res["models"]["B"]
        # hand-computed: words 3+5+3 = 11; A = ins (r1) + del (r2) + sub (r3) = 3; B = del (r1) + ins (r3) = 2
        self.assertEqual((a["samples"], a["ref_words"], a["sub"], a["del"], a["ins"], a["wer"]), (3, 11, 1, 1, 1, round(3 / 11, 4)))
        self.assertEqual((b["samples"], b["ref_words"], b["sub"], b["del"], b["ins"], b["wer"]), (3, 11, 0, 1, 1, round(2 / 11, 4)))
        # characters 12+26+19 = 57; A: " bien" 5 + "ce " 3 + n->v 1 = 9; B: " dort" 5 + " soir" 5 = 10 (CER ranks the other way)
        self.assertEqual((a["ref_chars"], a["char_errors"], b["char_errors"]), (57, 9, 10))
        # with punctuation as tokens: 4+6+4 = 14 tokens
        self.assertEqual((a["views"]["cased_punct"]["ref_tokens"], a["views"]["cased_punct"]["errors"], b["views"]["cased_punct"]["errors"]), (14, 3, 2))
        p = res["paired"]
        self.assertEqual((p["samples"], p["B_fewer_errors"], p["B_more_errors"], p["same"], p["difference_b_minus_a"]), (3, 1, 0, 2, -1))
        self.assertEqual((res["ranking"]["status"], res["ranking"]["fewer_errors"]), ("ranked", "B"))
        self.assertEqual(res["samples"]["speakers"], "no speaker metadata")

    def test_missing_ids_are_reported_and_block_the_ranking(self):
        refs = {"r1": {"id": "r1", "reference": "le chat dort"}, "r2": {"id": "r2", "reference": "il pleut"}, "r4": {"id": "r4", "reference": "[rires]"}}
        ha, hb = {"label": "A", "model_id": "a", "config_id": "c"}, {"label": "B", "model_id": "b", "config_id": "c"}
        res = lab.batch(refs, ha, {"r1": "le chat dort", "r3": "x", "r4": "oui"}, hb, {"r1": "le chat", "r2": "", "r4": ""})
        self.assertEqual(res["missing"], [{"id": "r2", "reasons": ["missing in A"]}, {"id": "r3", "reasons": ["no reference", "missing in B"]}])
        self.assertEqual((res["samples"]["matched"], res["samples"]["compared"], res["empty_reference_ids"]), (2, 1, ["r4"]))
        self.assertEqual(res["ranking"]["status"], "not_ranked")
        # every aggregate carries its sample count
        self.assertEqual(res["models"]["A"]["samples"], 1)
        self.assertTrue(all(v["samples"] == 1 for v in res["models"]["B"]["views"].values()))

    def test_empty_reference_and_empty_prediction_are_counted_apart(self):
        refs = {"r1": {"id": "r1", "reference": "le chat dort"}, "r2": {"id": "r2", "reference": "..."}}
        ha, hb = {"label": "A", "model_id": "a", "config_id": "c"}, {"label": "B", "model_id": "b", "config_id": "c"}
        res = lab.batch(refs, ha, {"r1": "le chat dort", "r2": "oui"}, hb, {"r1": "", "r2": "non"})
        self.assertEqual((res["samples"]["empty_reference"], res["empty_reference_ids"]), (1, ["r2"]))
        self.assertEqual(res["models"]["B"]["empty_predictions"]["ids"], ["r1"])
        self.assertEqual((res["models"]["B"]["del"], res["models"]["B"]["wer"]), (3, 1.0))
        self.assertEqual(res["models"]["A"]["empty_predictions"]["samples"], 0)

    def test_batch_cli_exit_codes(self):
        run = lambda *a: subprocess.run([sys.executable, "-B", "-m", "flh_speaking", "lab", "batch", *a], cwd=PKG, capture_output=True, text=True)  # noqa: E731
        ok = run("--refs", str(THREE / "refs.jsonl"), "--a", str(THREE / "a.jsonl"), "--b", str(THREE / "b.jsonl"))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("ranking: ranked: fewer errors B", ok.stdout)
        bad = run("--refs", str(THREE / "refs.jsonl"), "--a", str(THREE / "a.jsonl"), "--b", str(THREE / "a.jsonl"))
        self.assertEqual(bad.returncode, 2)  # the same label twice



def sliced():
    """6 source groups x (clean, noisy) = 12 samples. B errs only on noisy variants;
    g1 and g2 are tagged short, g3-g5 long, g6 has no length tag."""
    refs, ra, rb = {}, {}, {}
    for g in range(1, 7):
        for variant in ("clean", "snr5"):
            i = f"g{g}~{variant}"
            tags = {"noise": "none" if variant == "clean" else "white_snr5dB_seed7"}
            if g <= 2:
                tags["phrase_length"] = "short"
            elif g <= 5:
                tags["phrase_length"] = "long"
            refs[i] = {"id": i, "reference": "le petit chat dort ici", "group_id": f"g{g}", "tags": tags}
            ra[i] = "le petit chat dort ici"
            rb[i] = "le petit chat dort ici" if variant == "clean" else "le chat dort"
    return lab.batch(refs, {"label": "A", "model_id": "a", "config_id": "c"}, ra, {"label": "B", "model_id": "b", "config_id": "c"}, rb)


class Slices(unittest.TestCase):
    def test_groups_are_counted_so_variants_cannot_pass_for_independent_samples(self):
        res = sliced()
        self.assertEqual((res["samples"]["compared"], res["samples"]["groups"]), (12, 6))
        self.assertIn("12 samples come from 6 groups", res["samples"]["note"])
        p = res["paired"]
        self.assertEqual((p["groups"], p["B_more_errors_groups"], p["B_fewer_errors_groups"]), (6, 6, 0))
        self.assertNotIn("note", three_rows()["samples"])  # no variants there

    def test_regressions_are_ranked_only_with_enough_groups(self):
        res = sliced()["slices"]
        noisy = res["keys"]["noise"]["white_snr5dB_seed7"]
        self.assertEqual((noisy["samples"], noisy["groups"], noisy["support"], noisy["difference_b_minus_a"]), (6, 6, "ranked", 0.4))
        self.assertEqual([e["slice"] for e in res["regressions"]], ["noise=white_snr5dB_seed7"])
        self.assertEqual(res["keys"]["noise"]["none"]["difference_b_minus_a"], 0.0)
        # few groups: observations, never ranked
        obs = {e["slice"]: e for e in res["observations"]}
        self.assertEqual(sorted(obs), ["phrase_length=(unlabelled)", "phrase_length=long", "phrase_length=short"])
        self.assertEqual((obs["phrase_length=short"]["groups"], obs["phrase_length=short"]["support"]), (2, "observation"))

    def test_overlapping_slices_and_missing_labels(self):
        res = sliced()["slices"]["keys"]
        # every sample is in exactly one cell per key; keys overlap across samples
        self.assertEqual(sum(c["samples"] for c in res["noise"].values()), 12)
        self.assertEqual(sum(c["samples"] for c in res["phrase_length"].values()), 12)
        self.assertEqual((res["phrase_length"]["(unlabelled)"]["samples"], res["phrase_length"]["(unlabelled)"]["groups"]), (2, 1))
        text = lab.render_batch_text(sliced())
        self.assertIn("regression: noise=white_snr5dB_seed7  6 groups / 6 samples", text)
        self.assertIn("observation (fewer than 5 groups, not ranked): phrase_length=short", text)



REVIEW = PKG / "fixtures" / "lab" / "review"


class Review(unittest.TestCase):
    def rec(self, **kw):
        r = {"schema": rv.REVIEW_SCHEMA, "id": "s1", "action": "accept", "reason": "ok", "reviewer": "reviewer-1"}
        r.update(kw)
        return r

    def test_every_diagnostic_says_whether_it_is_measured_a_rule_a_heuristic_or_supplied(self):
        res = lab.compare(case("Il fait beau ce matin.", "il fait beau ce matin", ""))
        kinds = {d["name"]: d["kind"] for d in res["results"][0]["diagnostics"]}
        self.assertEqual(kinds, {"wer": "measured", "accent_only_substitutions": "rule", "low_evidence": "heuristic", "confidence": "not_supplied"})
        conf = lab.compare_one(["un", "deux", "trois"], "un deux trois", {"label": "A", "model_id": "m", "config_id": "c", "text": "un deux", "confidence": 0.7})
        self.assertEqual([d for d in conf["diagnostics"] if d["name"] == "confidence"][0]["kind"], "supplied")

    def test_silence_rule_is_explicit_and_configurable(self):
        tone = lab.synthetic_audio()
        loud = rv.silence(tone)
        self.assertEqual((loud["silent"], loud["kind"], loud["rule"]), (False, "measured", rv.SILENCE_RULE))
        from flh_speaking import variants
        quiet = variants.write_pcm16(16000, [0] * 16000)
        self.assertTrue(rv.silence(quiet)["silent"])
        self.assertTrue(rv.silence(tone, threshold_dbfs=-1.0)["silent"])  # a stricter threshold calls the tone silent

    def test_wrong_language_keeps_the_text_and_abstentions_suggest_a_retry(self):
        r = lab.compare_one(["bonjour", "à", "tous"], "bonjour à tous", {"label": "A", "model_id": "m", "config_id": "c",
                                                                         "text": "hello everyone", "language": {"top": "en", "p_fr": 0.02}})
        self.assertIn("possibly_wrong_language", r["notes"])
        self.assertEqual(r["raw"], "hello everyone")  # context kept, compared as it is
        self.assertEqual(r["counts"]["sub"] + r["counts"]["del"], 3)
        a = lab.compare_one(["bonjour"], "bonjour", {"label": "A", "model_id": "m", "config_id": "c", "text": "", "status": "no_speech"})
        self.assertEqual(a["suggested_retry"]["cause"], "no_speech")
        self.assertEqual(rv.suggest_retry(None)["kind"], "heuristic")

    def test_reviewer_records_are_validated(self):
        self.assertEqual(rv.validate_record(self.rec()), [])
        self.assertTrue(rv.validate_record(self.rec(action="delete")))
        self.assertTrue(rv.validate_record(self.rec(reason=" ")))
        self.assertTrue(rv.validate_record(self.rec(extra=1)))
        self.assertTrue(rv.validate_record(self.rec(action="correct")))  # needs label, correction, source
        self.assertEqual(rv.validate_record(self.rec(action="correct", label="A", correction="x", source="reviewer listened")), [])
        self.assertTrue(rv.validate_record(self.rec(correction="x")))

    def test_invalid_and_correction_records_in_a_batch(self):
        refs = {"s1": {"id": "s1", "reference": "le chat dort"}, "s2": {"id": "s2", "reference": "il pleut fort"}}
        ha, hb = {"label": "A", "model_id": "a", "config_id": "c"}, {"label": "B", "model_id": "b", "config_id": "c"}
        rev = {"s2": [self.rec(id="s2", action="invalid", reason="wrong recording")],
               "s1": [self.rec(id="s1", action="correct", label="B", correction="le chat dort", source="reviewer listened to the take")]}
        res = lab.batch(refs, ha, {"s1": "le chat dort", "s2": "x"}, hb, {"s1": "le chat", "s2": "y"}, review=rev)
        self.assertEqual(res["review"]["excluded"], [{"id": "s2", "action": "invalid", "reason": "wrong recording", "reviewer": "reviewer-1"}])
        self.assertEqual((res["samples"]["compared"], res["samples"]["reviewed_out"]), (1, 1))
        c = res["review"]["corrections"][0]
        self.assertEqual((c["original"], c["correction"]), ("le chat", "le chat dort"))
        self.assertEqual(res["models"]["B"]["del"], 1)  # the original hypothesis is what is scored

    def test_review_walkthrough_pass_retry_and_abstention(self):
        res = lab.batch(lab.read_refs(str(REVIEW / "refs.jsonl")), *lab.read_results(str(REVIEW / "a.jsonl")),
                        *lab.read_results(str(REVIEW / "b.jsonl")), review=rv.read_review(str(REVIEW / "review.jsonl")))
        self.assertEqual([e["id"] for e in res["review"]["accepted"]], ["s1-pass"])
        self.assertEqual([(e["id"], e["action"]) for e in res["review"]["excluded"]], [("s2-retry", "retry")])
        ab = res["abstentions"]
        self.assertEqual((ab["ids"], ab["including"]["B"]["samples"], ab["excluding"]["B"]["samples"]), (["s3-abstention"], 2, 1))
        self.assertEqual((ab["including"]["B"]["wer"], ab["excluding"]["B"]["wer"]), (round(5 / 13, 4), 0.0))
        self.assertEqual(ab["suggestions"][0]["cause"], "no_speech")
        self.assertEqual(lab.render_batch_text(res), (REVIEW / "expected.txt").read_text(encoding="utf-8"))



class Privacy(unittest.TestCase):
    def test_machine_paths_session_links_and_ids_are_found(self):
        text = "\n".join(["ok line", "audio at " + "/" + "home" + "/someone/take.webm", "C:\\Users\\x\\a.wav",
                          "see https://" + "claude.ai" + "/chat/abc", "key " + "-".join(["3f2504e0", "4f89", "41d3", "9a0c", "0305e82c3301"])])
        kinds = [f["kind"] for f in lab.privacy_findings(text)]
        self.assertEqual(kinds, ["home_path", "windows_user_path", "session_link", "uuid"])
        self.assertEqual(lab.privacy_findings((PKG / "fixtures" / "lab" / "synthetic_fr_case.expected.txt").read_text(encoding="utf-8")), [])



class Uncertainty(unittest.TestCase):
    def test_group_bootstrap_matches_a_hand_computed_case(self):
        # groups (errors A, errors B, reference words): both-s1 0, mixed 5/13, both-s3 1.0 (p = 1/4, 1/2, 1/4)
        u = lab.group_bootstrap({"s1": [0, 0, 8], "s3": [0, 5, 5]})
        self.assertEqual((u["wer_difference_b_minus_a"], u["interval_95"], u["groups"]), (0.3846, [0.0, 1.0], 2))
        self.assertFalse(u["excludes_zero"])
        self.assertIn("unstable", u["reliability"])

    def test_it_is_deterministic_and_refuses_too_few_groups(self):
        g = {f"spk{k}": [k % 3, (k + 1) % 4, 10] for k in range(40)}
        self.assertEqual(lab.group_bootstrap(g), lab.group_bootstrap(dict(reversed(list(g.items())))))
        self.assertEqual(lab.group_bootstrap(g)["reliability"], "enough groups for a rough interval")
        one = lab.group_bootstrap({"only": [1, 2, 10]})
        self.assertIsNone(one["interval_95"])
        self.assertIn("fewer than 2 groups", one["reason"])


if __name__ == "__main__":
    unittest.main()
