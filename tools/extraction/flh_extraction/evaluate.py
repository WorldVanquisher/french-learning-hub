"""Evaluation of extraction outputs against reference candidates.

Inputs: reference records (candidates JSONL) and production verdicts
(`extraction-render validate` results: id, valid, error_class, units).
Structural validity is the production validator's verdict. Semantic errors
(ANNOTATION_POLICY.md §4) need a one-to-one match between predicted and
reference units *by meaning*. Without human judgments this module uses an
automatic lexical matcher and labels every semantic number PROVISIONAL.
Human judgments ({"id", "pred", "ref", "label": same|part|covers|none,
"supported": bool, "bilingual_ok": bool}) override the matcher per example.
Exact output match is never the measure: different valid wordings match.
"""

import itertools
import re
from collections import Counter, defaultdict

from .textnorm import norm

QUOTED = re.compile(r"«\s*([^»]+?)\s*»")
CJK = re.compile(r"[一-鿿]")
STOP = set("the a an of to in is and or with for be not on at by it as are this that its one de la le les des du un une et à en".split())


def toks(u):
    text = f"{u['canonical']} {u['statement']}"
    return {t for t in norm(text).split() if t not in STOP and len(t) > 1}


def forms(u):
    return {norm(f) for f in QUOTED.findall(u["canonical"] + " " + u["statement"]) if norm(f)}


def similarity(p, r):
    """Lexical proxy for "same objective": token overlap of canonical and
    statement, boosted when quoted French forms coincide."""
    a, b = toks(p), toks(r)
    j = len(a & b) / len(a | b) if a | b else 0.0
    fa, fb = forms(p), forms(r)
    f = len(fa & fb) / len(fa | fb) if fa | fb else 0.0
    return max(j, 0.5 * j + 0.5 * f)


MATCH, PART = 0.34, 0.18


def best_assignment(sim):
    """Maximum-weight one-to-one assignment over pairs >= MATCH (tiny sizes:
    exhaustive search)."""
    n_p, n_r = len(sim), len(sim[0]) if sim else 0
    best, best_pairs = -1.0, []
    if n_p == 0 or n_r == 0:
        return []
    k = min(n_p, n_r)
    for preds in itertools.permutations(range(n_p), k):
        for refs in itertools.permutations(range(n_r), k):
            pairs = [(p, r) for p, r in zip(preds, refs) if sim[p][r] >= MATCH]
            score = sum(sim[p][r] for p, r in pairs)
            if score > best:
                best, best_pairs = score, pairs
        if n_r > 6:
            break
    return best_pairs


def bilingual_issues(u):
    """Automatic, provisional English–Chinese checks: Chinese present, and every
    French form quoted in the English statement also quoted in the Chinese."""
    issues = []
    if not CJK.search(u["statement_zh"]):
        issues.append("no_chinese_text")
    # Only French forms must reappear: quoted forms that also occur in the
    # unit's canonical label or example (English glosses may be quoted too).
    anchor = norm(u["canonical"] + " " + (u["example"] or ""))
    en = {norm(f) for f in QUOTED.findall(u["statement"]) if norm(f) and norm(f) in anchor}
    zh_text = norm(u["statement_zh"])
    if any(f not in zh_text for f in en):
        issues.append("french_forms_missing_in_zh")
    if re.findall(r"\d+", u["statement"]) and set(re.findall(r"\d+", u["statement"])) - set(re.findall(r"\d+", u["statement_zh"])):
        issues.append("numbers_differ")
    return issues


def judge_example(ref_units, pred_units, human=None):
    """Errors for one example. Returns (errors Counter, matched, details)."""
    errs = Counter()
    if human:
        same = [(h["pred"], h["ref"]) for h in human if h["label"] == "same"]
        matched = set()
        used_p, used_r = set(), set()
        for p, r in same:
            if p not in used_p and r not in used_r:
                used_p.add(p), used_r.add(r), matched.add((p, r))
            else:
                errs["DUPLICATE" if r in used_r else "OVER_SPLIT"] += 1
        for r in range(len(ref_units)):
            if r not in used_r:
                parts = [h for h in human if h["ref"] == r and h["label"] == "part"]
                covers = [h for h in human if h["ref"] == r and h["label"] == "covers"]
                errs["OVER_SPLIT" if len(parts) >= 2 else "MERGED" if covers else "MISSED"] += 1
        for p in range(len(pred_units)):
            if p not in used_p and not any(h["pred"] == p and h["label"] in ("part", "covers") for h in human):
                if any(h["pred"] == p and h.get("supported") is False for h in human):
                    errs["UNSUPPORTED"] += 1
                else:
                    errs["EXTRA_SUPPORTED"] += 1
        for h in human:
            if h.get("bilingual_ok") is False:
                errs["BILINGUAL_MISMATCH"] += 1
        return errs, len(matched), {"basis": "human"}
    if not ref_units:
        if pred_units:
            errs["ABSTENTION_FAIL"] += 1
            errs["UNSUPPORTED"] += len(pred_units)
        return errs, 0, {"basis": "automatic"}
    sim = [[similarity(p, r) for r in ref_units] for p in pred_units]
    pairs = best_assignment(sim)
    mp, mr = {p for p, _ in pairs}, {r for _, r in pairs}
    for p, r in pairs:
        if pred_units[p]["kind"] != ref_units[r]["kind"]:
            errs["KIND_MISMATCH"] += 1
    for r in range(len(ref_units)):
        if r in mr:
            continue
        partial = [p for p in range(len(pred_units)) if p not in mp and sim[p][r] >= PART]
        # An unmatched reference that an already-matched prediction also
        # covers was merged into it; otherwise it was split or missed.
        covered = [p for p in mp if sim[p][r] >= PART]
        errs["OVER_SPLIT" if len(partial) >= 2 else "MERGED" if covered and not partial else "MISSED"] += 1
    seen = []
    for p in range(len(pred_units)):
        if p in mp:
            seen.append(p)
            continue
        if any(similarity(pred_units[p], pred_units[q]) >= 0.8 or
               norm(pred_units[p]["canonical"]) == norm(pred_units[q]["canonical"]) for q in seen):
            errs["DUPLICATE"] += 1
        elif sum(1 for r in range(len(ref_units)) if sim[p][r] >= PART) >= 2:
            errs["MERGED"] += 1
        elif any(sim[p][r] >= PART for r in range(len(ref_units))):
            errs["OVER_SPLIT"] += 1
        else:
            errs["UNSUPPORTED"] += 1
        seen.append(p)
    for u in pred_units:
        if bilingual_issues(u):
            errs["BILINGUAL_MISMATCH"] += 1
    return errs, len(pairs), {"basis": "automatic"}


def evaluate(refs, results, judgments=None):
    """refs: candidate records; results: production verdicts keyed by id."""
    judgments = judgments or {}
    res = {r["id"]: r for r in results}
    tot = Counter()
    by_case = defaultdict(Counter)
    n_ref = n_pred = n_match = 0
    zero_refs = zero_ok = nonzero_refs = abstained_wrongly = 0
    perfect = valid = 0
    rows = []
    for rec in refs:
        out = res.get(rec["id"])
        ref_units = rec["expected"]["units"]
        case = rec["meta"].get("case_type", rec["meta"].get("category", "?"))
        if out is None or not out["valid"]:
            pred_units = []
            tot["STRUCT_INVALID"] += 1
            by_case[case]["STRUCT_INVALID"] += 1
        else:
            valid += 1
            pred_units = out["units"]
        errs, m, d = judge_example(ref_units, pred_units, judgments.get(rec["id"]))
        if out is None or not out["valid"]:
            errs["MISSED"] = len(ref_units)
        n_ref += len(ref_units)
        n_pred += len(pred_units)
        n_match += m
        if not ref_units:
            zero_refs += 1
            zero_ok += int(not pred_units and out is not None and out["valid"])
        else:
            nonzero_refs += 1
            abstained_wrongly += int(not pred_units)
        ok = out is not None and out["valid"] and not errs and len(pred_units) == len(ref_units)
        perfect += int(ok)
        tot.update(errs)
        by_case[case].update(errs)
        by_case[case]["_examples"] += 1
        by_case[case]["_perfect"] += int(ok)
        rows.append({"id": rec["id"], "case": case, "errors": dict(errs), "matched": m, "basis": d["basis"]})
    prec = n_match / n_pred if n_pred else None
    rec_ = n_match / n_ref if n_ref else None
    f1 = 2 * prec * rec_ / (prec + rec_) if prec and rec_ else None
    automatic = sum(1 for r in rows if r["basis"] == "automatic")
    return {
        "examples": len(refs),
        "structural_validity": valid / len(refs) if refs else None,
        "semantic_basis": {"automatic_provisional": automatic, "human_judged": len(rows) - automatic},
        "provisional": automatic > 0,
        "unit_precision": prec, "unit_recall": rec_, "unit_f1": f1,
        "example_perfect_rate": perfect / len(refs) if refs else None,
        "abstention": {"zero_unit_refs": zero_refs, "correct_empty": zero_ok,
                       "rate": zero_ok / zero_refs if zero_refs else None,
                       "nonzero_refs_answered_empty": abstained_wrongly},
        "errors": dict(sorted(tot.items())),
        "by_case": {k: dict(sorted(v.items())) for k, v in sorted(by_case.items())},
        "rows": rows,
    }


def markdown(report, title):
    p = report
    flag = "**PROVISIONAL**: automatic lexical matching, not human-reviewed semantics." if p["provisional"] else "Human-judged semantics."
    fmt = lambda x: "—" if x is None else f"{x:.3f}"  # noqa: E731
    lines = [f"# {title}", "", flag, "",
             "| Metric | Value |", "|---|---|",
             f"| Examples | {p['examples']} |",
             f"| Structural validity (production validator) | {fmt(p['structural_validity'])} |",
             f"| Unit precision / recall / F1 | {fmt(p['unit_precision'])} / {fmt(p['unit_recall'])} / {fmt(p['unit_f1'])} |",
             f"| Example perfect rate | {fmt(p['example_perfect_rate'])} |",
             f"| Abstention on zero-unit references | {p['abstention']['correct_empty']}/{p['abstention']['zero_unit_refs']} |",
             f"| Non-zero references answered with no unit | {p['abstention']['nonzero_refs_answered_empty']} |",
             "", "| Error | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in p["errors"].items()] or ["| — | 0 |"]
    lines += ["", "| Case | Examples | Perfect | Errors |", "|---|---|---|---|"]
    for case, c in p["by_case"].items():
        errs = ", ".join(f"{k} {v}" for k, v in c.items() if not k.startswith("_")) or "—"
        lines.append(f"| {case} | {c.get('_examples', 0)} | {c.get('_perfect', 0)} | {errs} |")
    return "\n".join(lines) + "\n"
