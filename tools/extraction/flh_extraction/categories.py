"""Report four failure categories separately from an evaluation run.

Input: the references, the production validator's verdicts and the report of
`python3 -m flh_extraction evaluate`. Nothing is recomputed differently from
the harness; the categories only regroup its counts so that one number never
hides another:

  schema_validity   production validator verdicts (exact)
  unsupported       UNSUPPORTED units: a predicted objective the input did not raise
                    (automatic matcher: PROVISIONAL). FALSE_CLAIM is not measured
                    without human claim judgments and is reported as such.
  abstention        zero-unit references answered with no unit (exact), and
                    unit references answered with none (over-abstention)
  splitting         OVER_SPLIT, MERGED and DUPLICATE (automatic matcher: PROVISIONAL)
"""

import json


def summarize(refs, results, report):
    res = {r["id"]: r for r in results}
    n = len(refs)
    valid = sum(1 for r in refs if res.get(r["id"], {}).get("valid"))
    errors = report.get("errors", {})
    ab = report.get("abstention", {})
    unit_refs = sum(1 for r in refs if r["expected"]["units"])
    multi_refs = sum(1 for r in refs if len(r["expected"]["units"]) >= 2)
    return {
        "examples": n,
        "provisional": report.get("provisional", True),
        "schema_validity": {"valid": valid, "of": n, "rate": round(valid / n, 3) if n else None,
                            "invalid_by_class": _count(r.get("error_class") for r in results if not r.get("valid"))},
        "unsupported": {"units": errors.get("UNSUPPORTED", 0),
                        "examples_with_unsupported": sum(1 for row in report.get("rows", []) if row["errors"].get("UNSUPPORTED")),
                        "false_claim": "not measured: needs human claim judgments"},
        "abstention": {"zero_unit_refs": ab.get("zero_unit_refs"), "correct_empty": ab.get("correct_empty"),
                       "rate": ab.get("rate"), "abstention_fail": errors.get("ABSTENTION_FAIL", 0),
                       "unit_refs": unit_refs, "unit_refs_answered_empty": ab.get("nonzero_refs_answered_empty")},
        "splitting": {"over_split": errors.get("OVER_SPLIT", 0), "merged": errors.get("MERGED", 0),
                      "duplicate": errors.get("DUPLICATE", 0), "multi_unit_refs": multi_refs},
        "other_errors": {k: v for k, v in sorted(errors.items())
                         if k not in ("UNSUPPORTED", "ABSTENTION_FAIL", "OVER_SPLIT", "MERGED", "DUPLICATE")},
    }


def _count(values):
    out = {}
    for v in values:
        out[v or "unknown"] = out.get(v or "unknown", 0) + 1
    return out


def markdown(s, title):
    f = lambda x: "—" if x is None else x  # noqa: E731
    sv, un, ab, sp = s["schema_validity"], s["unsupported"], s["abstention"], s["splitting"]
    return "\n".join([
        f"# {title}", "",
        "Automatic matching is PROVISIONAL; FALSE_CLAIM needs human claim judgments." if s["provisional"] else "Human-judged.", "",
        "| Category | Result |", "|---|---|",
        f"| Schema validity (production validator) | {sv['valid']}/{sv['of']} ({f(sv['rate'])}); invalid: {json.dumps(sv['invalid_by_class'])} |",
        f"| Unsupported claims | {un['units']} units in {un['examples_with_unsupported']} examples; FALSE_CLAIM {un['false_claim']} |",
        f"| Abstention | {f(ab['correct_empty'])}/{f(ab['zero_unit_refs'])} zero-unit refs correct (ABSTENTION_FAIL {ab['abstention_fail']}); "
        f"{f(ab['unit_refs_answered_empty'])}/{ab['unit_refs']} unit refs answered empty |",
        f"| Splitting | OVER_SPLIT {sp['over_split']}, MERGED {sp['merged']}, DUPLICATE {sp['duplicate']} ({sp['multi_unit_refs']} multi-unit refs) |",
        f"| Other errors | {json.dumps(s['other_errors'])} |", ""])
