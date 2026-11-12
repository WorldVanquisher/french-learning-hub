"""Production-input probes derived from the frozen evaluation set (never training data).

  python3 -m flh_extraction probe --eval E.jsonl --analyses A.jsonl --variant rb|swap --out P.jsonl

`A.jsonl` is `extraction-render analyze` run on the evaluation inputs: the
default production analyzer's category and explanation for each input.

  rb    the extractor's view under the production default: every input keeps
        its learner text and context, its effective category and explanation
        become the rule-based analyzer's, and its resolution becomes
        `unreviewed` (a human-corrected record keeps its correction)
  swap  a stress test of the cue the training data teaches: zero-unit
        references get the analyzer's category and explanation (never
        `other` for text), unit references get category `other` with a
        neutral imported-capture explanation

References are inherited unchanged (ANNOTATION_POLICY rule 6: the explanation
is evidence, not authority; the learner's text is the same). They remain
machine-authored and unreviewed; the probe adds no label. Probe records keep
split `eval`, so `sft` refuses them.
"""

import copy

NEUTRAL = "Imported question; no analysis summary was provided."


def build(evals, analyses, variant):
    if variant not in ("rb", "swap"):
        raise ValueError("variant must be rb or swap")
    a = {x["id"]: x for x in analyses}
    missing = [r["id"] for r in evals if r["id"] not in a]
    if missing:
        raise ValueError(f"no analysis for {missing[:5]}")
    out = []
    for r in evals:
        rec = copy.deepcopy(r)
        i, an = rec["input"], a[r["id"]]
        if variant == "rb" and i["resolution"] != "corrected":
            i.update(effective_category=an["effective_category"], effective_explanation=an["effective_explanation"],
                     resolution="unreviewed")
        elif variant == "swap":
            if r["expected"]["units"]:
                i.update(effective_category="other", effective_explanation=NEUTRAL, resolution="accepted")
            else:
                i.update(effective_category=an["effective_category"], effective_explanation=an["effective_explanation"],
                         resolution="unreviewed")
        rec["id"] = f"{r['id']}#{variant}"
        rec["meta"]["probe"] = {"variant": variant, "derived_from": r["id"], "analyzer": an.get("analyzer"),
                                "references": "inherited from the frozen evaluation record (machine-authored, unreviewed)"}
        out.append(rec)
    return out


def summary(probe):
    from collections import Counter
    return {"records": len(probe),
            "category_other_on_zero_refs": sum(1 for r in probe if not r["expected"]["units"]
                                               and r["input"]["effective_category"] == "other"),
            "category_other_on_unit_refs": sum(1 for r in probe if r["expected"]["units"]
                                               and r["input"]["effective_category"] == "other"),
            "categories": dict(sorted(Counter(r["input"]["effective_category"] for r in probe).items())),
            "resolution": dict(sorted(Counter(r["input"]["resolution"] for r in probe).items()))}
