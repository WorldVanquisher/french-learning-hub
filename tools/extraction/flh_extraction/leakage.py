"""Answer leakage before retrieval (R4 experiment ``r4-retrieval-leakage``; offline, deterministic).

  python3 -B -m flh_extraction.leakage [--json OUT]

It runs the pre-registered experiment (``experiments/r4-retrieval-leakage.prereg.json``).

**Steps.** It refuses to run if a pinned source changed. Then, for each practice item built
under the registered approval rule, it asks whether an answer string occurs in what the
learner sees before answering. It checks two views:
- the item's prompt and options alone (M1);
- the R4 loop's ``read`` view, which adds the reviewed units and the evidence (M2).

**Decision.** The registered rule picks branch A or B. Nothing is tuned after the run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile

from . import loop as lp
from . import practice as pr
from . import practice22 as p22

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREREG = os.path.join(HERE, "experiments", "r4-retrieval-leakage.prereg.json")


def answers(p: dict) -> list[str]:
    h = p["hidden"]
    if p["kind"] == "choose":
        cloze = p["prompt"].split(" — ", 1)[1] if " — " in p["prompt"] else p["prompt"]
        return [cloze.replace("__", h["answer"])]
    if p["kind"] == "produce":
        return [h["answer"]] + list(h.get("accepted") or [])
    return list(h.get("reference") or [])


def leaks(view: str, strings: list[str]) -> list[str]:
    v = f" {pr.fr_norm(view)} "
    return [s for s in strings if pr.fr_norm(s) and f" {pr.fr_norm(s)} " in v]


def run(prereg: dict) -> dict:
    rows = []
    for s in prereg["corpus"]["sources"]:
        path = os.path.join(HERE, s["file"])
        with open(path, "rb") as fh:
            if hashlib.sha256(fh.read()).hexdigest() != s["sha256"]:
                raise SystemExit(f"{s['file']} changed since registration: this would be another experiment")
        with tempfile.TemporaryDirectory() as t:
            w = p22.Work2(os.path.join(t, "w"))
            w.init(path, with_review=False)
            pl = w.plan()
            if pl["batch_id"]:
                w.approve_batch(pl["batch_id"])
            res, prac, srcs = w.resolved(), w.practice(rebuild=True), w.sources()
        for p in prac["items"]:
            prompt_view = " ".join([p["prompt"]] + list(p.get("options") or []))
            loop = lp.read(lp.start(res, prac, p["practice_id"]), res, srcs)
            ev = loop["events"][0]
            read_view = " ".join([prompt_view] + [u["text"] for u in ev["units"]] + [e["quote"] for e in ev["evidence"]])
            a = answers(p)
            rows.append({"source": s["file"].rsplit("/", 1)[-1], "practice_id": p["practice_id"], "kind": p["kind"],
                         "answers": len(a), "leak_prompt": leaks(prompt_view, a), "leak_read": leaks(read_view, a)})
    n = len(rows)
    m1 = sum(1 for r in rows if r["leak_prompt"]) / n
    m2 = sum(1 for r in rows if r["leak_read"]) / n
    kinds = sorted({r["kind"] for r in rows})
    by = {k: {"items": sum(1 for r in rows if r["kind"] == k), "M1": sum(1 for r in rows if r["kind"] == k and r["leak_prompt"]),
              "M2": sum(1 for r in rows if r["kind"] == k and r["leak_read"])} for k in kinds}
    branch = "branch_A" if m2 >= 0.10 else "branch_B"
    return {"schema": "flh_experiment_result_v1", "id": prereg["id"], "items": n, "expected_items": prereg["corpus"]["expected_items"],
            "M1": round(m1, 4), "M2": round(m2, 4), "by_kind": by, "decision": branch, "decision_text": prereg["decision_rule"][branch],
            "m1_defects": [r["practice_id"] for r in rows if r["leak_prompt"]], "rows": rows, "limits": prereg["limits"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="flh_extraction.leakage")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    with open(PREREG, encoding="utf-8") as fh:
        pre = json.load(fh)
    rep = run(pre)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(pr.dumps(rep))
    print(f"{rep['id']}: {rep['items']} items (registered {rep['expected_items']}); M1 {rep['M1']}, M2 {rep['M2']}; by kind {rep['by_kind']}")
    print(f"decision: {rep['decision']}: {rep['decision_text']}")
    if rep["m1_defects"]:
        print("M1 defects:", ", ".join(rep["m1_defects"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
