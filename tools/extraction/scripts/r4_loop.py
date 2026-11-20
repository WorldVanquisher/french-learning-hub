"""Executable learning-loop example (R4; offline, synthetic): read, recall, reveal, retry, revisit.

  python3 -I -B scripts/r4_loop.py --write     # (re)write fixtures/r4_v1/loop/
  python3 -I -B scripts/r4_loop.py --check     # regenerate and compare byte for byte

One learner works on the y/en source (the same steps as the R4 corpus):
- revision 1 is reviewed;
- a choose item is read, recalled (wrong), revealed and retried (right);
- revision 2 makes its units need review, and a revisit says so, still showing the evidence
  from revision 1;
- revision 3 is confirmed, and a second revisit finds the units current again and the
  evidence moved.

Two more loops show the retention choice:
- ``discard`` from the start;
- ``keep``, then ``discard``, which removes the answers kept so far.

Each loop is checked with ``loop.validate``, and the evidence shown at the reveal and the
revisits is checked against the learner's own text (``verified``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from flh_extraction import loop as lp  # noqa: E402
from flh_extraction import practice as pr  # noqa: E402
from flh_extraction import practice22 as p22  # noqa: E402
from flh_extraction import r4corpus as rc  # noqa: E402

OUT = os.path.join(HERE, "fixtures", "r4_v1", "loop")
PRIVATE_ANSWER = "Oui, j'y retourne demain matin."


def states() -> dict:
    """Review, practice and sources at each step of the corpus lifecycle."""
    out = {}
    with tempfile.TemporaryDirectory() as t:
        y = p22.Work2(os.path.join(t, "y"))
        y.init(os.path.join(rc.PRACTICE, "y_en.r1.json"), with_review=False)
        ids = {i["proposal_ref"]: i["item_id"] for i in y.resolved()["items"]}
        y.decide(ids["en-mouvement"], "reject", reason="my friend corrected exactly this: « j'en vais » is wrong")
        y.approve_batch(y.plan()["batch_id"])
        snap = lambda: {"res": y.resolved(), "prac": y.practice(rebuild=True), "sources": y.sources()}  # noqa: E731
        out["r1"] = snap()
        y.revise(os.path.join(rc.PRACTICE, "y_en.r2.json"), with_review=False)
        out["r2"] = snap()
        y.revise(os.path.join(rc.PRACTICE, "y_en.r3.json"), with_review=False)
        ids = {i["proposal_ref"]: i["item_id"] for i in y.resolved()["items"]}
        for ref in ("en-de", "y-vs-en", "en-vais", "ex-marche"):
            y.decide(ids[ref], "approve", reason="re-read in revision 3")
        out["r3"] = snap()
    return out


def build() -> dict:
    s = states()
    r1, r2, r3 = s["r1"], s["r2"], s["r3"]
    choose = next(p["practice_id"] for p in r1["prac"]["items"] if p["kind"] == "choose")
    produce = next(p["practice_id"] for p in r1["prac"]["items"] if p["kind"] == "produce")
    a = lp.start(r1["res"], r1["prac"], choose, session="learner-a")
    steps = [lp.next_step(a)]
    a = lp.recall(a, r1["prac"], "y")
    steps.append(lp.next_step(a))
    a = lp.reveal(a, r1["prac"], r1["sources"])
    steps.append(lp.next_step(a))
    a = lp.read(a, r1["res"], r1["sources"])
    steps.append(lp.next_step(a))
    a = lp.retry(a, r1["prac"], "en")
    a = lp.revisit(a, r2["res"], r2["prac"], r2["sources"])
    a = lp.revisit(a, r3["res"], r3["prac"], r3["sources"])
    explain = next(p["practice_id"] for p in r1["prac"]["items"] if p["kind"] == "explain")
    d = lp.start(r1["res"], r1["prac"], explain, session="learner-d")
    d = lp.recall(lp.read(d, r1["res"], r1["sources"]), r1["prac"], "y after à, en after de")
    b = lp.start(r1["res"], r1["prac"], produce, retention="discard", session="learner-b")
    b = lp.read(b, r1["res"], r1["sources"])
    b = lp.recall(b, r1["prac"], PRIVATE_ANSWER)
    b = lp.reveal(b, r1["prac"], r1["sources"])
    c = lp.start(r1["res"], r1["prac"], produce, session="learner-c")
    c = lp.recall(c, r1["prac"], PRIVATE_ANSWER)
    c = lp.reveal(c, r1["prac"], r1["sources"])
    c_kept = "answer kept: " + str(PRIVATE_ANSWER in json.dumps(c, ensure_ascii=False))
    c = lp.set_retention(c, "discard")
    refusals = {}
    for name, fn in (("retry_before_reveal", lambda: lp.retry(lp.start(r1["res"], r1["prac"], choose), r1["prac"], "en")),
                     ("recall_after_reveal", lambda: lp.recall(lp.reveal(lp.start(r1["res"], r1["prac"], choose), r1["prac"], r1["sources"]), r1["prac"], "y")),
                     ("start_on_withdrawn_item", lambda: lp.start(r2["res"], r2["prac"], choose))):
        try:
            fn()
            refusals[name] = "NOT REFUSED"
        except lp.LoopError as e:
            refusals[name] = str(e)
    ev = [e for e in a["events"] if e["event"] in ("read", "reveal")] + [e for e in a["events"] if e["event"] == "revisit"]
    checks = {
        "valid": {n: lp.validate(x) for n, x in (("keep", a), ("discard", b), ("opt_out_later", c))},
        "evidence_verified_at_read_reveal_revisit": all(x["verified"] for e in ev for x in e.get("evidence", []) + e.get("original_evidence", [])),
        "revisit_r2": {"units": [u["status"] for u in a["events"][4]["units"]], "practice": a["events"][4]["practice"]},
        "revisit_r3": {"units": [u["status"] for u in a["events"][5]["units"]], "evidence": [x["status"] for x in a["events"][5]["evidence_status"]],
                       "can_practise": a["events"][5]["can_practise"]},
        "discard_keeps_no_answer": PRIVATE_ANSWER not in json.dumps(b, ensure_ascii=False),
        "opt_out_later": {"before": c_kept, "after_contains_answer": PRIVATE_ANSWER in json.dumps(c, ensure_ascii=False),
                          "removed": c["events"][-1]["answers_removed"]},
        "refusals": refusals, "offered_order": steps,
        "retrieval": {"attempt_first": [e.get("retrieval") for e in a["events"] if e["event"] in ("recall", "retry")],
                      "read_first": [e.get("retrieval") for e in d["events"] if e["event"] == "recall"]}}
    checks["ok"] = (all(not v for v in checks["valid"].values()) and checks["evidence_verified_at_read_reveal_revisit"]
                    and checks["revisit_r2"]["practice"]["status"] == "withdrawn" and checks["revisit_r3"]["can_practise"]
                    and checks["discard_keeps_no_answer"] and not checks["opt_out_later"]["after_contains_answer"]
                    and "NOT REFUSED" not in refusals.values() and steps == ["recall", "reveal", "read", "retry"]
                    and checks["retrieval"] == {"attempt_first": ["unaided", "after_reveal"], "read_first": ["after_reading"]})
    checks["valid"]["read_first"] = lp.validate(d)
    return {"keep": a, "discard": b, "opt_out_later": c, "read_first": d, "checks": checks}


README = """# Learning loop example (`flh_learning_loop_v1`, R4; synthetic)

| File | What it shows |
|---|---|
| `loop-keep.json` | attempt first: recall (wrong, `unaided`) → reveal → read → retry (right, `after_reveal`) → revisit after revision 2 (units changed, item withdrawn `knowledge_changed`, original evidence still verified) → revisit after revision 3 confirmed (units current, evidence moved, can practise) |
| `loop-discard.json` | the learner chose `discard` before answering: outcomes only, `answer: null`, `answer_withheld: learner_opt_out` |
| `loop-opt-out-later.json` | `keep`, then `discard`: the kept answer is removed and a `retention` event records it |
| `loop-read-first.json` | an explain item read before recall: the recall is labelled `after_reading` (experiment r4-retrieval-leakage, branch A) |
| `transcript.txt` | the four loops as text |
| `checks.json` | `loop.validate` on each, the evidence checks and the refused orders |

Contract and limits: `tools/extraction/LOOP.md`. Regenerate with `scripts/r4_loop.py --write`.
"""


def files() -> dict:
    b = build()
    return {"loop-keep.json": pr.dumps(b["keep"]), "loop-discard.json": pr.dumps(b["discard"]), "loop-opt-out-later.json": pr.dumps(b["opt_out_later"]),
            "loop-read-first.json": pr.dumps(b["read_first"]),
            "transcript.txt": "".join(lp.render(b[k]) + "\n" for k in ("keep", "discard", "opt_out_later", "read_first")),
            "checks.json": pr.dumps(b["checks"]), "README.md": README}


def write(out: str) -> dict:
    fs = files()
    os.makedirs(out, exist_ok=True)
    for n, t in fs.items():
        with open(os.path.join(out, n), "w", encoding="utf-8") as fh:
            fh.write(t)
    with open(os.path.join(out, "SHA256SUMS"), "w", encoding="utf-8") as fh:
        fh.write("".join(f"{hashlib.sha256(fs[n].encode()).hexdigest()}  {n}\n" for n in sorted(fs)))
    return json.loads(fs["checks.json"])


def _bytes(p: str) -> bytes:
    with open(p, "rb") as fh:
        return fh.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.write:
        shutil.rmtree(OUT, ignore_errors=True)
        ch = write(OUT)
    else:
        with tempfile.TemporaryDirectory() as t:
            ch = write(t)
            bad = [n for n in sorted(set(os.listdir(t)) | set(os.listdir(OUT)))
                   if not (os.path.exists(os.path.join(t, n)) and os.path.exists(os.path.join(OUT, n)))
                   or _bytes(os.path.join(t, n)) != _bytes(os.path.join(OUT, n))]
        print("check: loop/ equals a fresh run" if not bad else "CHECK FAILED: " + ", ".join(bad))
        if bad:
            return 1
    with open(os.path.join(OUT, "transcript.txt"), encoding="utf-8") as fh:
        print(fh.read(), end="")
    print("loop:", "PASS" if ch["ok"] else "FAIL")
    return 0 if ch["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
