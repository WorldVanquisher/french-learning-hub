#!/usr/bin/env python3
"""Check that the workbench grades like the extraction lane, using its SEALED code.

    python3 -I -B scripts/validation/extraction_practice/grade_parity.py --handoff H

H is the extraction lane's sealed handoff (handoff-2.1). Its seal is verified, and a scratch
overlay of the sealed code (sealed_extraction.py) must reproduce that lane's sealed outputs
byte for byte before its practice.grade() is used. The live extraction worktree is never read.

Each case in grading_cases.json names a grading fixture (a tutor packet with rubrics) and a
feed from web/src/prototype/extractionPracticeFixture.ts. It is graded by the sealed grade()
over the feed's item and the packet's rubric; every outcome must equal the expected one,
which web/src/prototype/practiceFeed.test.ts also checks against the TypeScript mirror.
Exit 0 when all match, 1 on a mismatch, 3 when the seal or the reproduction fails.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sealed_extraction as se  # noqa: E402

REPO = se.REPO


def documents() -> dict:
    text = (REPO / "web/src/prototype/extractionPracticeFixture.ts").read_text(encoding="utf-8")
    marker = "export const FIXTURE_DOCUMENTS: readonly FixtureDocument[] = "
    docs = json.loads(text[text.index(marker) + len(marker):].rstrip().rstrip(";"))
    return {d["name"]: json.loads(d["text"]) for d in docs if d["name"].endswith(".json")}


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "--handoff":
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    h = Path(os.path.realpath(sys.argv[2]))
    try:
        digest = se.verify_handoff(h)
        with tempfile.TemporaryDirectory(prefix="flh-parity-") as t:
            tools = se.overlay(h, Path(t) / "overlay")
            for line in se.reproduce(tools, Path(t) / "check", h):
                print(line)
            sys.dont_write_bytecode = True
            sys.path.insert(0, str(tools))
            from flh_extraction import practice  # the sealed grading, from the scratch overlay
            docs = documents()
            cases = json.loads((HERE / "grading_cases.json").read_text(encoding="utf-8"))["cases"]
            bad = 0
            for c in cases:
                it = next(i for i in docs[c["feed"]]["items"] if i["practice_id"] == c["practice_id"])
                r = next(x["rubric"] for x in docs[c["grading"]]["next_exercises"] if x["id"] == c["practice_id"])
                p = {"kind": it["kind"], "options": it.get("options"),
                     "hidden": {"answer": r.get("answer"), "accepted": r.get("accepted", []), "known_errors": r.get("known_errors", [])}}
                got = practice.grade(p, c["text"])["outcome"]
                ok = got == c["outcome"]
                bad += not ok
                print("PASS" if ok else "FAIL", c["grading"], c["practice_id"], repr(c["text"]), "->", got, "" if ok else f"(expected {c['outcome']})")
    except se.SealError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 3
    print(f"{len(cases) - bad}/{len(cases)} match the sealed grade() (handoff SHA256SUMS {digest[:12]}…)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
