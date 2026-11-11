"""Build the 80 boundary cases: JSONL (one record per case) and Markdown.

  python3 -I -B build_boundary.py OUT_DIR
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import AUTHORING, CONFIDENCE_POLICY  # noqa: E402
import boundary_a  # noqa: E402
import boundary_b  # noqa: E402

SCHEMA = "flh_extraction_boundary_case_v1"


def records():
    out = []
    for cid, cat, title, inp, decision, units, rationale, targets in boundary_a.CASES + boundary_b.CASES:
        if decision != "extract" and units:
            raise SystemExit(f"{cid}: {decision} with units")
        if decision == "extract" and not units:
            raise SystemExit(f"{cid}: extract without units")
        out.append({"schema": SCHEMA, "id": cid, "input": inp, "expected": {"units": units},
                    "meta": {"category": cat, "title": title, "decision": decision, "rationale": rationale,
                             "targets_errors": targets, "model_visible": decision != "not_eligible",
                             "origin": "synthetic", "review_status": "unreviewed",
                             "label_status": "machine_authored_unreviewed", "authoring": AUTHORING,
                             "confidence_policy": CONFIDENCE_POLICY}})
    ids = [r["id"] for r in out]
    if len(set(ids)) != len(ids) or ids != sorted(ids):
        raise SystemExit("ids must be unique and ordered")
    return out


def markdown(recs):
    lines = ["# Boundary cases v1 (80, synthetic, unreviewed)", "",
             "Expected decisions follow `ANNOTATION_POLICY.md`. Every case is machine-authored and unreviewed; none is gold.", ""]
    for r in recs:
        m, i = r["meta"], r["input"]
        lines += [f"## {r['id']} — {m['title']} (`{m['category']}`)", "",
                  f"- **Input:** {i['original_input']}"]
        if i["original_context"]:
            lines.append(f"- **Context:** {i['original_context']}")
        lines += [f"- **Effective analysis:** `{i['effective_category']}`, {i['resolution']}: {i['effective_explanation']}",
                  f"- **Decision:** `{m['decision']}`" + (f" — {len(r['expected']['units'])} unit(s)" if r["expected"]["units"] else "")]
        for u in r["expected"]["units"]:
            lines.append(f"  - `{u['kind']}` **{u['canonical']}** — {u['statement']} / {u['statement_zh']}"
                         + (f" — e.g. « {u['example']} »" if u["example"] else "") + f" (confidence {u['confidence']})")
        lines += [f"- **Why:** {m['rationale']}", f"- **Targets:** {', '.join(m['targets_errors']) or '—'}", ""]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    recs = records()
    with open(out / "boundary_cases_v1.jsonl", "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    (out / "BOUNDARY_CASES.md").write_text(markdown(recs), encoding="utf-8")
    cats = {}
    for r in recs:
        cats[r["meta"]["category"]] = cats.get(r["meta"]["category"], 0) + 1
    print(json.dumps({"cases": len(recs), "by_category": cats,
                      "units": sum(len(r["expected"]["units"]) for r in recs),
                      "zero_unit_cases": sum(1 for r in recs if r["meta"]["decision"] == "zero_units"),
                      "not_eligible": sum(1 for r in recs if r["meta"]["decision"] == "not_eligible")}, ensure_ascii=False))
