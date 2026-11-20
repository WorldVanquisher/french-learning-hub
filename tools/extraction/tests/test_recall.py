"""Extraction 2.2 recall measurement (recall.py, practice2 trial): optional research; offline, synthetic data."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flh_extraction import recall as rc  # noqa: E402

FIX = ROOT / "fixtures" / "practice_v1"


def load(*parts):
    return json.loads(FIX.joinpath(*parts).read_text(encoding="utf-8"))


def cli(*args):
    return subprocess.run([sys.executable, "-B", "-m", "flh_extraction", "practice2", *args], cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(ROOT)})


class Recall(unittest.TestCase):
    probe = load("probe", "y_en_probe_v1.json")

    def test_dry_run_totals_equal_the_hand_computed_ones(self):
        s, diffs = rc.dry_run(self.probe, load("probe", "responses-dry-run.json")["responses"], load("probe", "expected-totals.json"))
        self.assertEqual(diffs, [])
        g = s["groups"]["all"]
        self.assertEqual((g["planned"], g["missing"], g["rates"]["correct_of_completed"], g["rates"]["correct_of_planned"]), (12, 1, "4/7", "4/12"))
        self.assertEqual(set(rc.DEFINITIONS), {"unassisted_recall", "assisted_recall", "transfer"})
        self.assertTrue(s["cannot_support"])

    def test_probe_is_novel_and_absent_from_study_packets(self):
        self.assertTrue(rc.novelty(self.probe, rc.default_corpus())["all_novel"])
        self.assertEqual(rc.answers_in_packets(self.probe, rc.default_study_packets()), [])
        for lvl in ("L1", "L2", "L3"):
            self.assertGreaterEqual(sum(1 for i in self.probe["items"] if i.get("difficulty") == lvl and i["type"] == "transfer"), 3)

    def test_order_is_deterministic_and_refuses_repeats(self):
        a, b = rc.order(self.probe), rc.order(json.loads(json.dumps(self.probe)))
        self.assertEqual(a, b)
        self.assertNotEqual(a, [i["id"] for i in self.probe["items"]])
        dup = json.loads(json.dumps(self.probe))
        dup["items"][4]["example_key"] = dup["items"][3]["example_key"]
        with self.assertRaises(ValueError):
            rc.order(dup)

    def test_statuses_are_kept_apart_and_checked(self):
        it = next(i for i in self.probe["items"] if i["id"] == "t4")
        self.assertEqual(rc.score(it, {"status": "unsupported", "text": "Oui, j'habite là-bas."})["status"], "unsupported")
        self.assertEqual(rc.score(it, None)["status"], "missing")
        with self.assertRaises(ValueError):
            rc.score(it, {"status": "completed", "text": "Oui, j'habite là-bas."})
        with self.assertRaises(ValueError):
            rc.score(it, {"status": "skipped", "text": "Oui, j'y habite."})
        t8 = next(i for i in self.probe["items"] if i["id"] == "t8")
        self.assertIn("ne pas en revenir", t8["ambiguous"])
        t9 = next(i for i in self.probe["items"] if i["id"] == "t9")
        self.assertEqual(rc.score(t9, {"status": "completed", "text": "Oui, j'y irai."})["outcome"], "self_check")
        self.assertEqual(rc.score(t9, {"status": "completed", "text": "Oui, j'irai."})["outcome"], "correct")

    def test_trial_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.tmp = Path(tmp)
            r = cli("trial", "--out", str(self.tmp / "trial"), "--check")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(sorted(os.listdir(self.tmp / "trial")),
                             ["dry-run-summary.md", "probe-checks.json", "probe-key.md", "probe-sheet.md", "responses-template.json"])
            sheet = (self.tmp / "trial" / "probe-sheet.md").read_text(encoding="utf-8")
        for it in load("probe", "y_en_probe_v1.json")["items"]:
            for a in rc.keys(it):
                self.assertNotIn(a, sheet)


if __name__ == "__main__":
    unittest.main()
