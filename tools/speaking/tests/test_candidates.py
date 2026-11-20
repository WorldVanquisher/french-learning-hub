"""Candidate manifests, file checks, dry run, invalidation (standard library only)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

from flh_speaking import candidates as cd, fetch, lab  # noqa: E402

V1 = PKG.parents[1] / "docs" / "validation" / "SPEAKING-MODEL-V1" / "evals"
THREE = PKG / "fixtures" / "lab" / "three_rows"


class Candidates(unittest.TestCase):
    def test_manifest_identity_follows_pins_lock_and_runtime(self):
        a = cd.manifest("whisper-base")
        self.assertEqual(a, cd.manifest("whisper-base"))
        self.assertEqual(a["defining"]["lock"]["sha256"], fetch.file_digest(cd.LOCK, "sha256"))
        self.assertNotEqual(a["candidate_id"], cd.manifest("whisper-base", dtype="int8")["candidate_id"])
        self.assertNotEqual(a["candidate_id"], cd.manifest("whisper-small")["candidate_id"])
        with tempfile.TemporaryDirectory() as d:
            lock = os.path.join(d, "requirements-cpu.lock")
            Path(lock).write_text(Path(cd.LOCK).read_text() + "# changed\n")
            with mock.patch.object(cd, "LOCK", lock):
                self.assertNotEqual(a["candidate_id"], cd.manifest("whisper-base")["candidate_id"])

    def test_absent_or_mismatched_files_are_found_before_loading(self):
        man = {"defining": {"model": {"files": {"config.json": [2, "sha256", "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"],
                                                 "model.safetensors": [3, "sha256", "0" * 64]}}}}
        with tempfile.TemporaryDirectory() as d:
            Path(d, "config.json").write_text("{}")  # sha256("{}") matches
            Path(d, "model.safetensors").write_text("abc")
            bad = cd.check_files(man, d)
            self.assertEqual(len(bad), 1)
            self.assertTrue(bad[0].startswith("model.safetensors: sha256"))
            os.remove(os.path.join(d, "config.json"))
            self.assertIn("config.json: missing", cd.check_files(man, d))
        self.assertTrue(cd.check_files(man, "/nonexistent-flh-dir")[0].startswith("model directory"))

    def test_dry_run_needs_no_weights_and_goes_through_the_batch(self):
        refs = lab.read_refs(str(THREE / "refs.jsonl"))
        rows = cd.dry_run(refs)
        self.assertEqual(rows, cd.dry_run(refs))
        self.assertEqual(rows[0]["header"]["model_id"], cd.DRY_RUN_ID)
        head, res = rows[0]["header"], {r["id"]: r for r in rows[1:]}
        out = lab.batch(refs, head, res, *lab.read_results(str(THREE / "b.jsonl")))
        self.assertEqual(out["models"]["D"]["errors"], 1)  # every third sample drops its last word
        self.assertEqual(out["models"]["D"]["runtime"], {"device": "none", "dtype": "none"})

    def test_a_result_is_invalidated_when_its_manifest_changes(self):
        refs = lab.read_refs(str(THREE / "refs.jsonl"))
        ha, ra = lab.read_results(str(THREE / "a.jsonl"))
        hb, rb = lab.read_results(str(THREE / "b.jsonl"))
        man = cd.manifest("whisper-base")
        ha = dict(ha, candidate_id=man["candidate_id"])
        ok = lab.batch(refs, ha, ra, hb, rb, manifests={"A": man})
        self.assertEqual((ok["ranking"]["status"], ok["validity"]["invalidated"]), ("ranked", []))
        changed = cd.manifest("whisper-base", dtype="float16")
        bad = lab.batch(refs, ha, ra, hb, rb, manifests={"A": changed})
        self.assertEqual(bad["ranking"]["status"], "not_ranked")
        self.assertIn("invalidated", bad["ranking"]["reason"])
        seeds = lab.batch(refs, dict(ha, seed=1), ra, dict(hb, seed=2), rb)
        self.assertIn("different seeds", seeds["ranking"]["reason"])

    def test_identical_sample_order_whatever_the_input_order(self):
        refs = lab.read_refs(str(THREE / "refs.jsonl"))
        ha, ra = lab.read_results(str(THREE / "a.jsonl"))
        hb, rb = lab.read_results(str(THREE / "b.jsonl"))
        x = lab.batch(refs, ha, ra, hb, rb)
        y = lab.batch(dict(reversed(list(refs.items()))), ha, dict(reversed(list(ra.items()))), hb, rb)
        self.assertEqual(x["sample_order_sha256"], y["sample_order_sha256"])
        self.assertEqual(x["models"], y["models"])

    def test_stored_v1_outputs_reproduce_the_v1_comparison(self):
        base, small = (json.loads((V1 / f"{m}-test.json").read_text(encoding="utf-8")) for m in ("base", "small"))
        rb_refs, rows_b = cd.from_eval(base, "base")
        rs_refs, rows_s = cd.from_eval(small, "small")
        self.assertEqual(rb_refs, rs_refs)  # both saw the identical test set
        refs = {r["id"]: r for r in rb_refs}
        out = lab.batch(refs, rows_b[0]["header"], {r["id"]: r for r in rows_b[1:]}, rows_s[0]["header"], {r["id"]: r for r in rows_s[1:]})
        self.assertEqual((out["models"]["base"]["wer"], out["models"]["small"]["wer"]),
                         (round(base["summary"]["served"]["wer"], 4), round(small["summary"]["served"]["wer"], 4)))
        self.assertEqual((out["paired"]["small_fewer_errors"], out["paired"]["small_more_errors"]), (212, 9))
        self.assertEqual(out["samples"]["speakers"], 8)
        self.assertEqual(out["ranking"]["fewer_errors"], "small")


    def test_speaker_grouping_makes_speakers_the_independent_unit(self):
        doc = {"model_dir_name": "m", "decoding": "d", "normalization": "n", "summary": {"label": "x", "split": "test"},
               "items": [{"id": f"c{k}", "cluster": f"spk{k % 2}", "ref": "un deux trois", "served": {"text": "un deux trois"}} for k in range(4)]}
        refs, _ = cd.from_eval(doc, "A", group="speaker")
        self.assertEqual(sorted({r["group_id"] for r in refs}), ["spk0", "spk1"])
        refs, _ = cd.from_eval(doc, "A")
        self.assertEqual(len({r["group_id"] for r in refs}), 4)
        with self.assertRaises(ValueError):
            cd.from_eval(doc, "A", group="book")


if __name__ == "__main__":
    unittest.main()
