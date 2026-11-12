"""Controlled failures: synthetic model outputs that each break one thing, to
show which metric catches it (and which failure no automatic metric catches).

  python3 -m flh_extraction control-matrix --refs R.jsonl --render extraction-render --out DIR
         [--probe P.jsonl]

For every control the matrix records how each headline metric of
quality.report moved against the oracle (the references themselves, which are
machine-authored and unreviewed: the oracle shows the harness, not a model).
A control is CAUGHT when every target metric moves the wrong way; collateral
movements are listed. `false_claim` is expected NOT CAUGHT: a wrong statement
that keeps its canonical label and French forms needs a human claim judgment.
`category_shortcut` imitates a model that learned the training cue (category
`other` = zero units): on the frozen evaluation it is indistinguishable from
the oracle; the `swap` probe exposes it.
"""

import json
import subprocess
from pathlib import Path

from . import quality

FAKE = {"kind": "vocabulary", "canonical": "salutations", "statement": "Greetings are polite.",
        "statement_zh": "问候语很礼貌。", "example": None, "confidence": 0.9}

LOWER_IS_WORSE = {"structural_validity", "exact_unit_count_rate", "abstention_rate", "unit_f1"}

TARGETS = {
    "oracle": [],
    "struct_code_fence": ["structural_validity"],
    "struct_think_block": ["structural_validity"],
    "struct_truncated": ["structural_validity"],
    "count_drop": ["exact_unit_count_rate"],
    "over_split": ["exact_unit_count_rate", "over_split+merged+duplicate"],
    "merge": ["exact_unit_count_rate", "over_split+merged+duplicate"],
    "duplicate": ["exact_unit_count_rate", "over_split+merged+duplicate"],
    "over_abstain": ["unit_refs_answered_empty"],
    "hallucinate_on_zero": ["false_extraction_on_zero_refs", "abstention_rate"],
    "unsupported_swap": ["unsupported_units", "not_anchored_units"],
    "bilingual_drift": ["bilingual_flagged_units"],
    "false_claim": [],
    "category_shortcut": [],
}
PROBE_TARGETS = {"category_shortcut": ["false_extraction_on_zero_refs", "unit_refs_answered_empty"]}


def _js(units):
    return json.dumps({"units": units}, ensure_ascii=False)


def _halves(text):
    if ": " in text:
        a, b = text.split(": ", 1)
        return a + ".", b
    w = text.split()
    return " ".join(w[:len(w) // 2]), " ".join(w[len(w) // 2:])


def outputs(refs, control):
    """{"id", "input", "output_text"} rows for one control."""
    rows = []
    n = len(refs)
    for k, r in enumerate(refs):
        units = [dict(u) for u in r["expected"]["units"]]
        text = None
        if control == "struct_code_fence":
            text = "```json\n" + _js(units) + "\n```"
        elif control == "struct_think_block":
            text = "<think>\n\n</think>\n\n" + _js(units)
        elif control == "struct_truncated":
            full = _js(units)
            text = full[:max(1, len(full) // 2)]
        elif control == "count_drop" and len(units) >= 2:
            units = units[:-1]
        elif control == "over_split" and units:
            u = units[0]
            a, b = _halves(u["statement"])
            units = [{**u, "canonical": u["canonical"] + " (1)", "statement": a},
                     {**u, "canonical": u["canonical"] + " (2)", "statement": b}] + units[1:]
        elif control == "merge" and len(units) >= 2:
            u, v = units[0], units[1]
            units = [{**u, "canonical": f"{u['canonical']} / {v['canonical']}", "statement": f"{u['statement']} {v['statement']}",
                      "statement_zh": u["statement_zh"] + v["statement_zh"]}] + units[2:]
        elif control == "duplicate" and units:
            units = units + [{**units[0], "statement": "In other words: " + units[0]["statement"]}]
        elif control == "over_abstain":
            units = []
        elif control == "hallucinate_on_zero" and not units:
            units = [dict(FAKE)]
        elif control == "unsupported_swap" and len(units) == 1:
            for step in range(1, n):
                other = refs[(k + 37 * step) % n]["expected"]["units"]
                if other and other[0]["canonical"] != units[0]["canonical"]:
                    units = [dict(other[0])]
                    break
        elif control == "bilingual_drift":
            units = [{**u, "statement_zh": "这个用法需要注意。"} for u in units]
        elif control == "false_claim":
            units = [{**u, "statement": "It is a common mistake to think that " + u["statement"][0].lower() + u["statement"][1:]}
                     for u in units]
        elif control == "category_shortcut":
            if r["input"]["effective_category"] == "other":
                units = []
            elif not units:
                units = [dict(FAKE)]
        if text is None:
            text = _js(units)
        rows.append({"id": r["id"], "input": r["input"], "output_text": text})
    return rows


def moved(oracle_h, h):
    out = {}
    for k, (v0, _) in oracle_h.items():
        v1 = h[k][0]
        if v0 is None or v1 is None or v0 == v1:
            out[k] = 0
        else:
            worse = v1 < v0 if k in LOWER_IS_WORSE else v1 > v0
            out[k] = round(v1 - v0, 3) if worse else 0
    return out


def matrix(refs, validate, targets=None):
    """validate(rows) -> production verdicts. Returns {control: row}."""
    targets = targets or TARGETS
    reports = {}
    for c in targets:
        rows = outputs(refs, c)
        reports[c] = quality.report(refs, validate(rows), outputs=rows)
    base = reports["oracle"]["headline"]
    out = {}
    for c, rep in reports.items():
        mv = moved(base, rep["headline"])
        tg = targets[c]
        caught = all(mv[t] for t in tg) if tg else None
        out[c] = {"targets": tg, "caught": caught, "moved": {k: v for k, v in mv.items() if v},
                  "collateral": sorted(k for k, v in mv.items() if v and k not in tg),
                  "parse_diagnostics": rep["structural"]["parse_diagnostics_of_invalid"]}
    return out


def render_validator(binary, workdir):
    """A validate() that runs `extraction-render validate` (the production parser and validator)."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    def validate(rows):
        i, o = workdir / "outputs.jsonl", workdir / "validated.jsonl"
        i.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        subprocess.run([str(binary), "validate", "-in", str(i), "-out", str(o)], check=True)
        return [json.loads(line) for line in o.read_text(encoding="utf-8").splitlines() if line.strip()]
    return validate


def markdown(m, title, probe_m=None):
    L = [f"# {title}", "",
         "Each control breaks one thing in the reference outputs; a metric \"moves\" when it gets worse than the "
         "oracle. CAUGHT = every target moved. References are machine-authored and unreviewed.", "",
         "| Control | Targets | Result | Moved (Δ vs oracle) | Collateral |", "|---|---|---|---|---|"]
    for c, row in m.items():
        res = {True: "CAUGHT", False: "MISSED", None: "—"}[row["caught"]]
        if c == "false_claim":
            res = "NOT CAUGHT (needs human claim judgment)" if not row["moved"] else "moved: " + res
        if c == "category_shortcut":
            res = "hidden on the frozen eval" if not row["moved"] else "visible"
        mv = ", ".join(f"{k} {v:+g}" for k, v in row["moved"].items()) or "nothing"
        L.append(f"| {c} | {', '.join(row['targets']) or '—'} | {res} | {mv} | {', '.join(row['collateral']) or '—'} |")
    if probe_m:
        L += ["", "## On the `swap` probe (production-style cues)", "", "| Control | Targets | Result | Moved |", "|---|---|---|---|"]
        for c, row in probe_m.items():
            if c == "oracle":
                continue
            res = {True: "CAUGHT", False: "MISSED", None: "—"}[row["caught"]]
            mv = ", ".join(f"{k} {v:+g}" for k, v in row["moved"].items()) or "nothing"
            L.append(f"| {c} | {', '.join(row['targets']) or '—'} | {res} | {mv} |")
    return "\n".join(L) + "\n"
