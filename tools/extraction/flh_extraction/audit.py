"""Training-data audit by failure mode (standard library only).

  python3 -m flh_extraction audit --train T.jsonl [--eval E.jsonl] [--boundary B.jsonl] --out PREFIX

Every count here is a HEURISTIC finding about machine-authored, unreviewed
labels: it says where a human should look, not that a label is wrong. The
audit reads the model-visible input and the expected units only (plus the
`case_type`/`style` metadata to group findings) and changes nothing.

Failure modes (ANNOTATION_POLICY.md §3–§4):

  over_splitting      units in one record that look like one objective; and how
                      many records teach "several examples of one rule = one unit"
  under_splitting     a correction pair with several separate edits but fewer units
  duplicate_units     duplicate units in one record; verbatim unit repetition
                      across records; identical inputs with different labels
  false_premises      how many records teach a misconception or a wrong
                      explanation, and statements that echo the learner's premise
  no_learning_objective  zero-unit records, their subtypes, and the cues that
                      separate them from unit records (shortcut risk)
  bilingual_drift     statement_zh missing Chinese, French forms or numbers of
                      the English statement
  unsupported_claims  units with no anchor in the learner's own text, examples
                      invented outside the interaction, and quoted forms that
                      appear nowhere in the visible input

`input_distribution` compares the visible input fields with what the
production pipeline sends (the default rule-based analyzer, internal/analyzer:
category `other` only for input without letters; explanations of the form
`Local classification selected "<category>" because rule …`; analyses are
`unreviewed` until a human accepts them).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from .evaluate import CJK, QUOTED, similarity
from .textnorm import norm

ARROW = re.compile(r"«\s*([^»]+?)\s*»\s*(?:→|->|en|to)\s*«\s*([^»]+?)\s*»")
HESITATE = re.compile(r"entre\s*«\s*([^»]+?)\s*»\s*et\s*«\s*([^»]+?)\s*»")
NUM = re.compile(r"\d+")
RULE_BASED = "Local classification selected"
PLACEHOLDER = re.compile(r"\+\s*[A-Za-z]+|\((?:[^()]*\+[^()]*)\)")
FRENCH_LETTER = re.compile(r"[àâäçéèêëîïôöùûüÿœæ]")
EN_WORDS = set("the is do does how what why which when where i my can should it to of in a an".split())
ANCHOR_STOP = set("avec pour dans sans être avoir faire mais plus that this with from have when what".split())
FR_WORDS = set("le la les est je tu on dit ce ça que qui pourquoi comment des une un du mon ma et".split())
MAX_EXAMPLES = 6


def anchor_terms(u):
    """A lenient lexical tie between a unit and a text: the stems (first five
    letters) of words of four letters or more in the canonical label and the
    statement's quoted forms, plus every whole segment of the canonical label
    and of those forms (split on commas, slashes and parentheses), so short
    French words count (« qui / que », « du, de la »)."""
    stems, phrases = set(), set()
    sources = [u["canonical"]] + QUOTED.findall(u["statement"]) + QUOTED.findall(u["canonical"])
    for src in sources:
        for w in norm(src).replace("'", " ").split():
            if len(w) >= 4 and w not in ANCHOR_STOP:
                stems.add(w[:5])
        for part in re.split(r"[/,();:—«»+]", src):
            if 2 <= len(norm(part)) <= 40:
                phrases.add(norm(part))
    return stems, phrases


def is_anchored(text_norm, terms):
    stems, phrases = terms
    words = text_norm.replace("'", " ").split()
    padded = " " + " ".join(words) + " "
    return (any(w.startswith(s) for s in stems for w in words)
            or any(" " + p.replace("'", " ") + " " in padded for p in phrases))


def learner_language(r):
    w = set(norm(learner_text(r)).split())
    if CJK.search(learner_text(r)) and not (w & FR_WORDS):
        return "zh"
    return "en" if len(w & EN_WORDS) > len(w & FR_WORDS) else "fr"


def case_of(r):
    m = r.get("meta", {})
    return m.get("case_type") or m.get("category") or "?"


def learner_text(r):
    i = r["input"]
    return f"{i['original_input']} {i['original_context']}"


def visible_text(r):
    i = r["input"]
    return f"{i['original_input']} {i['original_context']} {i['effective_explanation']}"


def excerpt(r, n=160):
    t = r["input"]["original_input"].replace("\n", " ")
    return t if len(t) <= n else t[:n - 1] + "…"


def example_row(r, why, units=None):
    us = r["expected"]["units"] if units is None else units
    return {"id": r["id"], "case": case_of(r), "input": excerpt(r),
            "units": [f"{u['kind']}: {u['canonical']}" for u in us] or ["(zero units)"], "why": why}


def quoted_forms(text):
    return [norm(f) for f in QUOTED.findall(text or "") if norm(f)]


def edit_details(a, b):
    """The separate edits between two short sentences (word level,
    longest-common-subsequence alignment). A word deleted in one region and
    inserted in another is one move, not two edits (« je jamais fume » →
    « je ne fume jamais » is one negation-placement edit). Each edit is a pair
    (removed words, inserted words)."""
    x, y = norm(a).split(), norm(b).split()
    n, m = len(x), len(y)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if x[i] == y[j] else max(dp[i + 1][j], dp[i][j + 1])
    i = j = 0
    regions, cur = [], None
    while i < n or j < m:
        if i < n and j < m and x[i] == y[j]:
            i, j, cur = i + 1, j + 1, None
            continue
        if cur is None:
            cur = (set(), set())
            regions.append(cur)
        if j >= m or (i < n and dp[i + 1][j] >= dp[i][j + 1]):
            cur[0].add(x[i])
            i += 1
        else:
            cur[1].add(y[j])
            j += 1
    # Union regions linked by a moved word.
    parent = list(range(len(regions)))

    def find(k):
        while parent[k] != k:
            k = parent[k]
        return k
    for p in range(len(regions)):
        for q in range(len(regions)):
            if p != q and (regions[p][0] & regions[q][1]):
                parent[find(p)] = find(q)
    merged = {}
    for k, (rem, add) in enumerate(regions):
        m = merged.setdefault(find(k), (set(), set()))
        m[0].update(rem)
        m[1].update(add)
    return list(merged.values())


def edit_regions(a, b):
    """Number of separate edits between two short sentences (see edit_details)."""
    return len(edit_details(a, b))


def correction_pairs(r):
    text = learner_text(r)
    return ARROW.findall(text) + HESITATE.findall(text)


def bilingual_findings(u):
    """Provisional EN/ZH drift checks for one unit (stricter than the
    evaluator's: every quoted French form, IPA and number)."""
    out = []
    zh = u["statement_zh"]
    if not CJK.search(zh):
        out.append("no_chinese_text")
    zh_n = norm(zh)
    # A quoted English gloss (« never ») is translated, not copied, and so is
    # a placeholder (« à + person » → « à + 人 »): only the French part of a
    # form that also occurs in the canonical or example, or carries a French
    # diacritic, must reappear.
    anchor = norm(u["canonical"] + " " + (u["example"] or ""))
    french = []
    for raw in QUOTED.findall(u["statement"]):
        f = norm(PLACEHOLDER.sub(" ", raw))
        if f and (f in anchor or FRENCH_LETTER.search(f)) and f not in zh_n:
            french.append(f)
    if french:
        out.append("french_forms_missing_in_zh: " + ", ".join(french[:3]))
    en_ipa, zh_ipa = re.findall(r"\[[^\]]+\]", u["statement"]), re.findall(r"\[[^\]]+\]", zh)
    if set(en_ipa) - set(zh_ipa):
        out.append("ipa_missing_in_zh")
    if set(NUM.findall(u["statement"])) - set(NUM.findall(zh)):
        out.append("numbers_differ")
    ratio = len(zh) / max(1, len(u["statement"]))
    if ratio < 0.25 or ratio > 1.6:
        out.append(f"length_ratio_{ratio:.2f}")
    return out


def audit(train, evals=(), boundary=()):
    rep = {"schema": "flh_extraction_training_audit_v1", "basis": "HEURISTIC (machine-authored, unreviewed labels)",
           "records": {"train": len(train), "eval": len(evals), "boundary": len(boundary)}}
    units_all = [(r, k, u) for r in train for k, u in enumerate(r["expected"]["units"])]
    rep["units"] = len(units_all)
    by_case = Counter(case_of(r) for r in train)

    # 1. Over-splitting.
    ex, pairs = [], 0
    for r in train:
        us = r["expected"]["units"]
        for a in range(len(us)):
            for b in range(a + 1, len(us)):
                shared = set(quoted_forms(us[a]["canonical"])) & set(quoted_forms(us[b]["canonical"]))
                s = similarity(us[a], us[b])
                if shared or s >= 0.34:
                    pairs += 1
                    if len(ex) < MAX_EXAMPLES:
                        ex.append(example_row(r, f"units {a}/{b} share {sorted(shared) or 'wording'} (sim {s:.2f})"))
    frag_teaching = sum(by_case[c] for c in ("fragmentation", "excessive_fragmentation", "one_rule_many_examples"))
    rep["over_splitting"] = {
        "unit_pairs_that_look_like_one_objective": pairs, "examples": ex,
        "records_teaching_one_rule_many_examples": frag_teaching,
        "note": "No training record shows several examples or forms of one rule collapsing into one unit."
                if not frag_teaching else "Some records teach one unit for several examples of one rule."}

    # 2. Under-splitting.
    ex, n_pairs, multi_edit = [], 0, 0
    for r in train:
        cps = correction_pairs(r)
        n_pairs += len(cps)
        flagged = [(a, b, edit_regions(a, b)) for a, b in cps if edit_regions(a, b) >= 2]
        if flagged and len(r["expected"]["units"]) < len(cps) + sum(e - 1 for _, _, e in flagged):
            multi_edit += 1
            if len(ex) < MAX_EXAMPLES:
                a, b, e = flagged[0]
                ex.append(example_row(r, f"« {a} » → « {b} » has {e} separate edits; {len(r['expected']['units'])} unit(s)"))
    rep["under_splitting"] = {"correction_pairs_seen": n_pairs, "records_with_multi_edit_pair_and_fewer_units": multi_edit,
                              "examples": ex,
                              "note": "Several edits can still be one objective (an agreement chain); each flag needs a human."}

    # 3. Duplicate units.
    ex, within = [], 0
    for r in train:
        us = r["expected"]["units"]
        keys = [(u["kind"], norm(u["canonical"])) for u in us]
        if len(set(keys)) < len(keys):
            within += 1
            if len(ex) < MAX_EXAMPLES:
                ex.append(example_row(r, "two units with the same kind and canonical"))
    sig = Counter((u["canonical"], u["statement"], u["statement_zh"], u["example"]) for _, _, u in units_all)
    reps = sorted(sig.values(), reverse=True)
    top = [{"canonical": k[0], "occurrences": v} for k, v in sig.most_common(5)]
    inputs = defaultdict(set)
    for r in train:
        inputs[tuple(sorted(r["input"].items()))].add(r["id"])
    labels = {r["id"]: tuple(sorted(norm(u["canonical"]) for u in r["expected"]["units"])) for r in train}
    conflicts = [sorted(ids) for ids in inputs.values() if len({labels[i] for i in ids}) > 1]
    rep["duplicate_units"] = {
        "records_with_duplicate_units": within, "examples": ex,
        "distinct_unit_texts": len(sig), "unit_occurrences": len(units_all),
        "verbatim_repetition": {"max": reps[0] if reps else 0, "median": reps[len(reps) // 2] if reps else 0,
                                "texts_seen_5_or_more_times": sum(1 for v in reps if v >= 5), "top": top},
        "identical_inputs_with_different_labels": conflicts[:MAX_EXAMPLES],
        "note": "Every occurrence of a learning point carries the same statement, example and Chinese text: "
                "the target is a lookup of the point, so a model can learn to recite bank wording."}

    # 4. False premises.
    fp_cases = ("false_premise", "misconception", "wrong_explanation")
    teaching = [r for r in train if case_of(r) in fp_cases or r.get("meta", {}).get("style") == "misconception"]
    wrong_expl = [r for r in train if case_of(r) == "wrong_explanation"]
    ex, echo = [], 0
    for r in teaching:
        premise = r["input"]["original_input"]
        for u in r["expected"]["units"]:
            s = similarity({"canonical": "", "statement": premise}, {"canonical": "", "statement": u["statement"]})
            if s >= 0.5:
                echo += 1
                if len(ex) < MAX_EXAMPLES:
                    ex.append(example_row(r, f"statement shares {s:.2f} of its wording with the premise"))
    eval_fp = sum(1 for r in evals if case_of(r) in fp_cases)
    bnd_fp = sum(1 for r in boundary if case_of(r) in ("false_premise",))
    rep["false_premises"] = {
        "train_records_teaching_a_misconception": len(teaching) - len(wrong_expl),
        "train_records_with_a_wrong_explanation": len(wrong_expl),
        "train_records_with_unreviewed_resolution": sum(1 for r in train if r["input"]["resolution"] == "unreviewed"),
        "eval_records_testing_it": eval_fp, "boundary_records": bnd_fp,
        "statements_echoing_the_premise": echo, "examples": ex or [example_row(r, "the only misconception record") for r in teaching[:MAX_EXAMPLES]],
        "note": "The evaluation set tests false premises and wrong explanations; training barely shows either."}

    # 5. No learning objective (abstention) and its cues.
    zero = [r for r in train if not r["expected"]["units"]]
    sub = Counter((r.get("meta", {}).get("style") or case_of(r)) for r in zero)

    def cue_table(rs):
        t = Counter()
        for r in rs:
            t[("other" if r["input"]["effective_category"] == "other" else "not_other",
               "zero" if not r["expected"]["units"] else "units")] += 1
        return {f"{a}/{b}": t[(a, b)] for a in ("other", "not_other") for b in ("zero", "units")}

    expl_by_zero = Counter(r["input"]["effective_explanation"] for r in zero)
    rep["no_learning_objective"] = {
        "zero_unit_records": len(zero), "share": round(len(zero) / len(train), 3) if train else None,
        "by_subtype": dict(sorted(sub.items())),
        "largest_single_template": {"explanation": expl_by_zero.most_common(1)[0][0] if zero else None,
                                    "records": expl_by_zero.most_common(1)[0][1] if zero else 0},
        "category_vs_label": {"train": cue_table(train), "eval": cue_table(evals), "boundary": cue_table(boundary)},
        "examples": [example_row(r, f"category {r['input']['effective_category']!r}; explanation "
                                    f"{r['input']['effective_explanation']!r}") for r in zero[:: max(1, len(zero) // MAX_EXAMPLES)][:MAX_EXAMPLES]],
        "note": "effective_category 'other' separates zero-unit from unit records perfectly in training and in the "
                "frozen evaluation set, and zero-unit explanations describe the abstention itself. A model can "
                "abstain by reading the category; the frozen evaluation cannot detect it."}

    # 6. Bilingual drift.
    ex, kinds = [], Counter()
    flagged_units = 0
    for r, k, u in units_all:
        f = bilingual_findings(u)
        if f:
            flagged_units += 1
            for x in f:
                kinds["length_ratio" if x.startswith("length_ratio") else x.split(":")[0]] += 1
            if len(ex) < MAX_EXAMPLES:
                ex.append({**example_row(r, "; ".join(f), [u]), "statement": u["statement"], "statement_zh": u["statement_zh"]})
    distinct_flagged = len({(u["canonical"], u["statement"]) for r, k, u in units_all if bilingual_findings(u)})
    rep["bilingual_drift"] = {"units_flagged": flagged_units, "distinct_unit_texts_flagged": distinct_flagged,
                              "by_finding": dict(sorted(kinds.items())), "examples": ex,
                              "note": "Automatic checks only (forms, IPA, numbers, length); meaning agreement needs a bilingual reviewer."}

    # 7. Claims the interaction does not support.
    ex_anchor, ex_expl, expl_only, invented_example, absent_forms = [], [], 0, 0, 0
    no_anchor = Counter()
    for r, k, u in units_all:
        lt, vt = norm(learner_text(r)), norm(visible_text(r))
        terms = anchor_terms(u)
        if not is_anchored(lt, terms):
            if is_anchored(vt, terms):
                expl_only += 1
                if len(ex_expl) < MAX_EXAMPLES:
                    ex_expl.append(example_row(r, f"« {u['canonical']} » is anchored only in the explanation", [u]))
            else:
                lang = learner_language(r)
                no_anchor[lang] += 1
                if lang == "fr" and len(ex_anchor) < MAX_EXAMPLES:
                    ex_anchor.append(example_row(r, f"no French term of « {u['canonical']} » appears in the visible input", [u]))
        if u["example"] and norm(u["example"]) not in vt:
            invented_example += 1
        absent_forms += sum(1 for f in quoted_forms(u["statement"]) if f not in vt)
    rep["unsupported_claims"] = {
        "units_not_anchored_in_visible_input": sum(no_anchor.values()),
        "not_anchored_by_learner_language": dict(sorted(no_anchor.items())), "examples": ex_anchor,
        "units_anchored_only_in_the_explanation": expl_only, "explanation_only_examples": ex_expl,
        "units_with_example_not_from_the_interaction": invented_example,
        "quoted_forms_absent_from_visible_input": absent_forms,
        "note": "Policy §2 allows a general statement and §8 prefers an example from the interaction. A unit "
                "anchored only in the explanation is supported only if the explanation is right; an English or "
                "Chinese question has no French term to anchor on, so only French-language flags are listed."}

    # Input distribution vs production.
    def dist(rs):
        n = len(rs) or 1
        return {"records": len(rs),
                "resolution": dict(sorted(Counter(r["input"]["resolution"] for r in rs).items())),
                "category_other_share": round(sum(r["input"]["effective_category"] == "other" for r in rs) / n, 3),
                "rule_based_style_explanations": sum(r["input"]["effective_explanation"].startswith(RULE_BASED) for r in rs),
                "empty_explanations": sum(not r["input"]["effective_explanation"].strip() for r in rs)}

    rep["input_distribution"] = {"train": dist(train), "eval": dist(evals), "boundary": dist(boundary),
                                 "production_default": {
                                     "analyzer": "rule-based:v2 (internal/analyzer)",
                                     "category_other": "only when the input and context contain no letter",
                                     "explanation": 'Local classification selected "<category>" because rule "<rule>" …',
                                     "resolution": "unreviewed until a human accepts or corrects the analysis"}}
    rep["summary"] = summary_rows(rep)
    return rep


def summary_rows(rep):
    """One row per failure mode. Severity is a triage rule for the review
    queue, computed from coverage: a mode the training data barely teaches is
    high, one it teaches but only with unreviewed labels is medium."""
    o, u, d, f, z, b, s = (rep[k] for k in ("over_splitting", "under_splitting", "duplicate_units", "false_premises",
                                            "no_learning_objective", "bilingual_drift", "unsupported_claims"))
    fp_cov = f["train_records_teaching_a_misconception"] + f["train_records_with_a_wrong_explanation"]
    cue = z["category_vs_label"]["train"]
    shortcut = cue["not_other/zero"] == 0 or cue["other/units"] == 0
    return [
        {"mode": "over_splitting", "count": o["unit_pairs_that_look_like_one_objective"],
         "coverage": o["records_teaching_one_rule_many_examples"],
         "severity": "high" if o["records_teaching_one_rule_many_examples"] < 10 else "medium"},
        {"mode": "under_splitting", "count": u["records_with_multi_edit_pair_and_fewer_units"], "coverage": None,
         "severity": "medium" if u["records_with_multi_edit_pair_and_fewer_units"] else "low"},
        {"mode": "duplicate_units", "count": d["records_with_duplicate_units"],
         "coverage": d["verbatim_repetition"]["texts_seen_5_or_more_times"],
         "severity": "high" if d["records_with_duplicate_units"] else "medium"},
        {"mode": "false_premises", "count": f["statements_echoing_the_premise"], "coverage": fp_cov,
         "severity": "high" if fp_cov < 20 or f["statements_echoing_the_premise"] else "medium"},
        {"mode": "no_learning_objective", "count": z["zero_unit_records"], "coverage": z["by_subtype"],
         "severity": "high" if shortcut else "medium"},
        {"mode": "bilingual_drift", "count": b["units_flagged"], "coverage": b["distinct_unit_texts_flagged"],
         "severity": "medium" if b["units_flagged"] else "low"},
        {"mode": "unsupported_claims", "count": s["not_anchored_by_learner_language"].get("fr", 0),
         "coverage": s["units_anchored_only_in_the_explanation"], "severity": "medium"},
    ]


def markdown(rep, title="Training-data audit"):
    L = [f"# {title}", "", f"**{rep['basis']}.** Counts locate review work; they do not prove a label wrong.", "",
         f"Records: train {rep['records']['train']}, eval {rep['records']['eval']}, boundary {rep['records']['boundary']}; "
         f"training units {rep['units']}.", "",
         "| Failure mode | Flagged | Coverage / context | Severity |", "|---|---|---|---|"]
    for row in rep["summary"]:
        cov = row["coverage"]
        cov = ", ".join(f"{k} {v}" for k, v in cov.items()) if isinstance(cov, dict) else ("—" if cov is None else cov)
        L.append(f"| {row['mode']} | {row['count']} | {cov} | {row['severity']} |")
    sections = [("over_splitting", "Over-splitting"), ("under_splitting", "Under-splitting"),
                ("duplicate_units", "Duplicate units"), ("false_premises", "False premises"),
                ("no_learning_objective", "No learning objective (abstention)"), ("bilingual_drift", "Bilingual drift"),
                ("unsupported_claims", "Claims the interaction does not support")]
    for key, name in sections:
        sec = rep[key]
        L += ["", f"## {name}", ""]
        for k, v in sec.items():
            if k in ("examples", "explanation_only_examples", "note"):
                continue
            L.append(f"- **{k}**: `{v}`" if not isinstance(v, (dict, list)) else f"- **{k}**: `{_short(v)}`")
        if sec.get("note"):
            L += ["", f"> {sec['note']}"]
        for label, rows in (("Examples", sec.get("examples") or []), ("Explanation-only examples", sec.get("explanation_only_examples") or [])):
            if rows:
                L += ["", f"{label}:", "", "| id | case | input | units | why |", "|---|---|---|---|---|"]
                for e in rows:
                    L.append(f"| {e['id']} | {e['case']} | {_cell(e['input'])} | {_cell('; '.join(e['units']))} | {_cell(e['why'])} |")
    L += ["", "## Input distribution vs production", "", "| Field | train | eval | boundary |", "|---|---|---|---|"]
    d = rep["input_distribution"]
    for k in ("resolution", "category_other_share", "rule_based_style_explanations", "empty_explanations"):
        L.append(f"| {k} | {_cell(_short(d['train'][k]))} | {_cell(_short(d['eval'][k]))} | {_cell(_short(d['boundary'][k]))} |")
    p = d["production_default"]
    L += ["", f"Production default: analyzer {p['analyzer']}; category `other` {p['category_other']}; explanation "
               f"`{p['explanation']}`; resolution {p['resolution']}.", ""]
    return "\n".join(L)


def _short(v):
    import json
    s = json.dumps(v, ensure_ascii=False, sort_keys=True)
    return s if len(s) <= 300 else s[:299] + "…"


def _cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")
