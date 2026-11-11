"""Build the human review queue: a prioritized 30-item packet, then a
topic-stratified sample of the training and evaluation candidates.

  python3 build_review_queue.py BOUNDARY.jsonl TRAIN.jsonl QUARANTINE.jsonl EVAL.jsonl OUT_DIR
"""

import json
import random
import sys
from pathlib import Path

RUBRIC = ("Decision right? · per unit: grounded / true / atomic / granularity / kind / canonical / EN–ZH agree / example "
          "· verdict: accept / edit / reject / quarantine")


def load(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]


def entry(r, source, why):
    i = r["input"]
    return {"id": r["id"], "source": source, "why_review": why, "input": i["original_input"], "context": i["original_context"],
            "explanation": i["effective_explanation"], "resolution": i["resolution"],
            "expected": [f"{u['kind']}: {u['canonical']}" for u in r["expected"]["units"]] or ["(zero units)"],
            "case": r["meta"].get("case_type") or r["meta"].get("category"),
            "quarantine_reason": r["meta"].get("quarantine_reason"), "verdict": None, "reviewer": None, "notes": None}


def main(bpath, tpath, qpath, epath, out):
    R = random.Random(20261110)
    boundary, train, quarantine, evals = load(bpath), load(tpath), load(qpath), load(epath)
    packet = []
    pick_b = {"zero_unit": 2, "insufficient_context": 2, "false_premise": 2, "rejected_or_corrected": 2, "prompt_injection": 2,
              "misleading_example": 1, "excessive_fragmentation": 1, "one_vs_multiple": 1, "general_knowledge_boundary": 1}
    for cat, n in pick_b.items():
        for r in [x for x in boundary if x["meta"]["category"] == cat][:n]:
            packet.append(entry(r, "boundary", f"Policy-defining case ({cat}); its decision shapes every label."))
    for r in [x for x in evals if x["meta"]["case_type"] not in ("single", "multi_2")][:7]:
        packet.append(entry(r, "eval", "Held-out edge case; an error here biases every evaluation."))
    for case in ("multi_3", "minimal_pair_unit", "multi_2"):
        for r in R.sample([x for x in train if x["meta"]["case_type"] == case], 2):
            packet.append(entry(r, "train", f"Training item of type {case}; checks atomicity and the context rule."))
    for r in quarantine[:3]:
        packet.append(entry(r, "quarantine", "Quarantined: a human must decide the label or drop it."))
    packet = packet[:30]
    topics = {}
    for r in train + evals:
        for t in r["meta"].get("topics") or ["(zero)"]:
            topics.setdefault((r["meta"]["split_group"], t), []).append(r)
    strat = []
    seen = {p["id"] for p in packet}
    for (split, t), rs in sorted(topics.items()):
        r = R.choice(rs)
        if r["id"] not in seen:
            seen.add(r["id"])
            strat.append(entry(r, split, f"Topic-stratified sample: {t}"))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "review_queue.jsonl", "w", encoding="utf-8") as f:
        for k, e in enumerate(packet + strat, 1):
            e["priority"] = k
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    lines = ["# Human review queue (extraction)", "", f"Rubric: {RUBRIC}", "",
             "Every item below is synthetic and machine-authored; none is gold until a reviewer accepts it.", "",
             f"## Priority packet ({len(packet)} items)", ""]
    for k, e in enumerate(packet, 1):
        lines += [f"### {k}. `{e['id']}` ({e['source']}, {e['case']})", f"- Why: {e['why_review']}",
                  f"- Input: {e['input']}"] + ([f"- Context: {e['context']}"] if e["context"] else []) + [
                  f"- Explanation ({e['resolution']}): {e['explanation']}", f"- Expected: {'; '.join(e['expected'])}"] + (
                  [f"- Quarantine reason: {e['quarantine_reason']}"] if e["quarantine_reason"] else []) + [
                  "- Verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · Reviewer: ____ · Notes: ____", ""]
    lines += [f"## Topic-stratified sample ({len(strat)} items, one per split and topic)", "",
              "| # | id | split | topic sample | expected |", "|---|---|---|---|---|"]
    for k, e in enumerate(strat, len(packet) + 1):
        lines.append(f"| {k} | `{e['id']}` | {e['source']} | {e['why_review'].split(': ', 1)[1]} | {'; '.join(e['expected'])} |")
    (out / "REVIEW_QUEUE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"priority_packet": len(packet), "stratified": len(strat)}))


if __name__ == "__main__":
    main(*sys.argv[1:6])
