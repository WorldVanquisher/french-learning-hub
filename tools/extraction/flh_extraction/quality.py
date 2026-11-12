"""Extraction quality report with one section per failure family, each
labelled with its basis, so a heuristic number is never read as a human one.

  python3 -m flh_extraction quality --refs R.jsonl --results V.jsonl [--outputs O.jsonl]
         [--judgments J.jsonl] --title T --out PREFIX

  basis "exact"      counted from the production validator's verdict and unit
                     counts; no interpretation
  basis "heuristic"  automatic lexical matching or string checks
                     (evaluate.judge_example, audit.anchor_terms,
                     audit.bilingual_findings): PROVISIONAL
  basis "human"      human judgments (evaluate.py format) for that example

Sections: structural validity (+ raw-output parse diagnostics with --outputs),
unit-count errors, split/merge errors, abstention errors, grounding, bilingual
fidelity, and a semantic summary. Heuristic and human counts are reported
side by side, never summed. FALSE_CLAIM is not measured automatically.
"""

from __future__ import annotations

import json
import re
from collections import Counter

from . import audit, evaluate
from .textnorm import norm

THINK = re.compile(r"<think>|</think>")
FENCE = re.compile(r"^\s*```")


def parse_diagnostic(text, row=None):
    """Why a raw output text would not parse as the contract's JSON (the
    production parser is a plain json.Unmarshal of the whole text)."""
    row = row or {}
    t = text or ""
    try:
        json.loads(t)
        return "parses"
    except json.JSONDecodeError as e:
        err = e
    if row.get("stopped") == "max_new_tokens":
        return "truncated_at_max_new_tokens"
    if not t.strip():
        return "empty"
    if THINK.search(t):
        return "think_block"
    if FENCE.match(t):
        return "code_fence"
    s = t.strip()
    if not s.startswith("{"):
        return "leading_text"
    if err.msg.startswith("Extra data"):
        return "trailing_text"
    return "truncated_json" if _unclosed(s) else "malformed_json"


def _unclosed(s):
    """True when the text ends inside a string or with open brackets: a
    generation that stopped before the JSON was complete."""
    stack, in_str, esc = [], False, False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or stack.pop() != ch:
                return False
    return in_str or bool(stack)


def _bucket(n):
    return str(n) if n < 3 else "3+"


def report(refs, results, judgments=None, outputs=None):
    judgments = judgments or {}
    res = {r["id"]: r for r in results}
    outs = {o["id"]: o for o in (outputs or [])}
    n = len(refs)
    rep = {"schema": "flh_extraction_quality_report_v1", "examples": n}

    # Structural validity (exact).
    invalid = Counter()
    diag = Counter()
    valid = 0
    for r in refs:
        v = res.get(r["id"])
        if v is not None and v.get("valid"):
            valid += 1
        else:
            invalid[(v or {}).get("error_class") or "missing_result"] += 1
            if r["id"] in outs:
                diag[parse_diagnostic(outs[r["id"]].get("output_text"), outs[r["id"]])] += 1
    rep["structural"] = {"basis": "exact", "valid": valid, "of": n, "rate": _rate(valid, n),
                         "invalid_by_class": dict(sorted(invalid.items())),
                         "parse_diagnostics_of_invalid": dict(sorted(diag.items())) if outputs is not None else "not run (pass --outputs)"}

    # Unit counts (exact, over valid outputs).
    conf = Counter()
    over = under = exact = 0
    abs_err = 0
    for r in refs:
        v = res.get(r["id"])
        if not (v and v.get("valid")):
            continue
        rc, pc = len(r["expected"]["units"]), len(v["units"])
        conf[(_bucket(rc), _bucket(pc))] += 1
        exact += rc == pc
        over += pc > rc
        under += pc < rc
        abs_err += abs(pc - rc)
    rep["unit_count"] = {"basis": "exact", "valid_examples": valid, "exact_count": exact, "exact_rate": _rate(exact, valid),
                         "over_count_examples": over, "under_count_examples": under,
                         "mean_abs_error": round(abs_err / valid, 3) if valid else None,
                         "confusion_ref_by_pred": {f"ref {a} → pred {b}": c for (a, b), c in sorted(conf.items())}}

    # Abstention (exact).
    zero = [r for r in refs if not r["expected"]["units"]]
    unitrefs = [r for r in refs if r["expected"]["units"]]
    zero_ok = [r for r in zero if res.get(r["id"], {}).get("valid") and not res[r["id"]]["units"]]
    false_extract = [r for r in zero if res.get(r["id"], {}).get("valid") and res[r["id"]]["units"]]
    over_abstain = [r for r in unitrefs if res.get(r["id"], {}).get("valid") and not res[r["id"]]["units"]]
    by_case = Counter()
    for r in false_extract:
        by_case[r["meta"].get("case_type", "?")] += 1
    rep["abstention"] = {"basis": "exact", "zero_unit_refs": len(zero), "correct_empty": len(zero_ok),
                         "rate": _rate(len(zero_ok), len(zero)),
                         "false_extraction_on_zero_refs": len(false_extract),
                         "false_extraction_by_case": dict(sorted(by_case.items())),
                         "zero_refs_invalid_output": len(zero) - len(zero_ok) - len(false_extract),
                         "unit_refs": len(unitrefs), "unit_refs_answered_empty": len(over_abstain),
                         "over_abstention_rate": _rate(len(over_abstain), len(unitrefs))}

    # Split / merge / duplicate and the semantic summary (heuristic or human, never summed).
    sem = {"heuristic": Counter(), "human": Counter()}
    counts = {"heuristic": Counter(), "human": Counter()}
    for r in refs:
        v = res.get(r["id"])
        pred = v["units"] if v and v.get("valid") else []
        if not (v and v.get("valid")):
            continue
        human = judgments.get(r["id"])
        basis = "human" if human else "heuristic"
        errs, m, _ = evaluate.judge_example(r["expected"]["units"], pred, human)
        sem[basis].update(errs)
        counts[basis].update({"examples": 1, "ref_units": len(r["expected"]["units"]), "pred_units": len(pred), "matched": m})
    rep["split_merge"] = {b: {"basis": b, "examples": counts[b]["examples"],
                              "over_split": sem[b]["OVER_SPLIT"], "merged": sem[b]["MERGED"], "duplicate": sem[b]["DUPLICATE"]}
                          for b in ("heuristic", "human")}
    rep["semantic"] = {}
    for b in ("heuristic", "human"):
        c = counts[b]
        p = c["matched"] / c["pred_units"] if c["pred_units"] else None
        rc = c["matched"] / c["ref_units"] if c["ref_units"] else None
        rep["semantic"][b] = {"basis": b, "examples": c["examples"], "unit_precision": _r(p), "unit_recall": _r(rc),
                              "unit_f1": _r(2 * p * rc / (p + rc)) if p and rc else None,
                              "errors": dict(sorted((k, v) for k, v in sem[b].items()))}

    # Grounding (heuristic; human "supported" judgments separately).
    g = Counter()
    gh = Counter()
    for r in refs:
        v = res.get(r["id"])
        if not (v and v.get("valid")):
            continue
        lt, vt = norm(audit.learner_text(r)), norm(audit.visible_text(r))
        for u in v["units"]:
            g["pred_units"] += 1
            t = audit.anchor_terms(u)
            if audit.is_anchored(lt, t):
                g["anchored_in_learner_text"] += 1
            elif audit.is_anchored(vt, t):
                g["anchored_only_in_explanation"] += 1
            else:
                g["not_anchored"] += 1
            if u.get("example"):
                g["with_example"] += 1
                g["example_from_interaction"] += norm(u["example"]) in vt
        for j in judgments.get(r["id"], []):
            if "supported" in j:
                gh["judged"] += 1
                gh["unsupported"] += j["supported"] is False
    rep["grounding"] = {"heuristic": {"basis": "heuristic", **{k: g[k] for k in ("pred_units", "anchored_in_learner_text",
                                                                               "anchored_only_in_explanation", "not_anchored",
                                                                               "with_example", "example_from_interaction")},
                                      "unsupported_matcher": sem["heuristic"]["UNSUPPORTED"],
                                      "abstention_fail_matcher": sem["heuristic"]["ABSTENTION_FAIL"]},
                        "human": {"basis": "human", "judged": gh["judged"], "unsupported": gh["unsupported"]},
                        "false_claim": "not measured automatically: needs human claim judgments"}

    # Bilingual fidelity (heuristic; human bilingual_ok separately).
    bf = Counter()
    units = 0
    for r in refs:
        v = res.get(r["id"])
        if not (v and v.get("valid")):
            continue
        for u in v["units"]:
            units += 1
            f = audit.bilingual_findings(u)
            bf["units_flagged"] += bool(f)
            for x in f:
                bf["length_ratio" if x.startswith("length_ratio") else x.split(":")[0]] += 1
    bh = Counter()
    for js in judgments.values():
        for j in js:
            if "bilingual_ok" in j:
                bh["judged"] += 1
                bh["mismatch"] += j["bilingual_ok"] is False
    rep["bilingual"] = {"heuristic": {"basis": "heuristic", "pred_units": units, **dict(sorted(bf.items()))},
                        "human": {"basis": "human", "judged": bh["judged"], "mismatch": bh["mismatch"]}}
    rep["provisional"] = counts["heuristic"]["examples"] > 0
    rep["headline"] = headline(rep)
    return rep


def headline(rep):
    """The numbers a reader compares first, each with its basis."""
    s, uc, ab, sm, gr, bi = (rep[k] for k in ("structural", "unit_count", "abstention", "split_merge", "grounding", "bilingual"))
    h = sm["heuristic"]
    return {
        "structural_validity": (s["rate"], "exact"),
        "exact_unit_count_rate": (uc["exact_rate"], "exact"),
        "abstention_rate": (ab["rate"], "exact"),
        "false_extraction_on_zero_refs": (ab["false_extraction_on_zero_refs"], "exact"),
        "unit_refs_answered_empty": (ab["unit_refs_answered_empty"], "exact"),
        "over_split+merged+duplicate": (h["over_split"] + h["merged"] + h["duplicate"], "heuristic"),
        "not_anchored_units": (gr["heuristic"]["not_anchored"], "heuristic"),
        "unsupported_units": (gr["heuristic"]["unsupported_matcher"], "heuristic"),
        "bilingual_flagged_units": (bi["heuristic"].get("units_flagged", 0), "heuristic"),
        "unit_f1": (rep["semantic"]["heuristic"]["unit_f1"], "heuristic"),
    }


def compare(a, b):
    """Metric deltas between two quality reports (e.g. frozen eval vs its
    production-input probe). Only metrics with the same basis are compared."""
    out = {}
    for k, (va, basis) in a["headline"].items():
        vb, bb = b["headline"][k]
        out[k] = {"a": va, "b": vb, "basis": basis,
                  "delta": round(vb - va, 3) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and basis == bb else None}
    return out


def markdown(rep, title):
    f = lambda x: "—" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))  # noqa: E731
    L = [f"# {title}", "",
         "Each section names its basis: **exact** (production validator and counts), **heuristic** "
         "(automatic matcher and string checks, PROVISIONAL) or **human** (judgments). Heuristic and human "
         "numbers are never added together. FALSE_CLAIM is not measured automatically.", "",
         "| Headline | Value | Basis |", "|---|---|---|"]
    for k, (v, b) in rep["headline"].items():
        L.append(f"| {k} | {f(v)} | {b} |")
    s = rep["structural"]
    L += ["", "## Structural validity (exact)", "",
          f"{s['valid']}/{s['of']} valid ({f(s['rate'])}); invalid by class `{json.dumps(s['invalid_by_class'])}`; "
          f"parse diagnostics `{json.dumps(s['parse_diagnostics_of_invalid'], ensure_ascii=False)}`."]
    u = rep["unit_count"]
    L += ["", "## Unit-count errors (exact, valid outputs)", "",
          f"Exact count {u['exact_count']}/{u['valid_examples']} ({f(u['exact_rate'])}); over-count {u['over_count_examples']}, "
          f"under-count {u['under_count_examples']}; mean absolute error {f(u['mean_abs_error'])}.", "",
          "| Reference → prediction | Examples |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in u["confusion_ref_by_pred"].items()]
    a = rep["abstention"]
    L += ["", "## Abstention errors (exact)", "",
          f"Zero-unit references answered empty: {a['correct_empty']}/{a['zero_unit_refs']} ({f(a['rate'])}); "
          f"false extraction {a['false_extraction_on_zero_refs']} `{json.dumps(a['false_extraction_by_case'])}`; "
          f"unit references answered empty {a['unit_refs_answered_empty']}/{a['unit_refs']}."]
    L += ["", "## Split / merge / duplicate", "", "| Basis | Examples | OVER_SPLIT | MERGED | DUPLICATE |", "|---|---|---|---|---|"]
    for b in ("heuristic", "human"):
        x = rep["split_merge"][b]
        L.append(f"| {b} | {x['examples']} | {x['over_split']} | {x['merged']} | {x['duplicate']} |")
    g = rep["grounding"]
    gh = g["heuristic"]
    L += ["", "## Grounding", "",
          f"- heuristic: {gh['pred_units']} predicted units; anchored in the learner's text {gh['anchored_in_learner_text']}, "
          f"only in the explanation {gh['anchored_only_in_explanation']}, not anchored {gh['not_anchored']}; "
          f"matcher UNSUPPORTED {gh['unsupported_matcher']}; examples taken from the interaction "
          f"{gh['example_from_interaction']}/{gh['with_example']}.",
          f"- human: {g['human']['judged']} judged, {g['human']['unsupported']} unsupported.",
          f"- FALSE_CLAIM: {g['false_claim']}."]
    bi = rep["bilingual"]
    L += ["", "## Bilingual fidelity", "",
          f"- heuristic: `{json.dumps(bi['heuristic'], ensure_ascii=False)}`",
          f"- human: {bi['human']['judged']} judged, {bi['human']['mismatch']} mismatches."]
    L += ["", "## Semantic summary", "", "| Basis | Examples | Precision | Recall | F1 | Errors |", "|---|---|---|---|---|---|"]
    for b in ("heuristic", "human"):
        x = rep["semantic"][b]
        L.append(f"| {b} | {x['examples']} | {f(x['unit_precision'])} | {f(x['unit_recall'])} | {f(x['unit_f1'])} | "
                 f"{json.dumps(x['errors'])} |")
    return "\n".join(L) + "\n"


def _rate(a, b):
    return round(a / b, 3) if b else None


def _r(x):
    return None if x is None else round(x, 3)
