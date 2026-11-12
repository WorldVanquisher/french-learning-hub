"""Row accounting, abstention confusion counts and the pinned scoring version
shared by the shortcut reproduction, the paired-consistency metric and the
three-system comparison.

  python3 -m flh_extraction shortcut-repro --eval E --probe-rb P --probe-swap S --render BIN --out DIR
  python3 -m flh_extraction account --slice R.jsonl --predictions P.jsonl --render BIN --out PREFIX

Every reference row gets exactly one status; nothing is dropped:

  valid_units / valid_empty     the production validator accepted the output
  valid_extra_keys              accepted by the production parser, which ignores
                                unknown JSON keys, but outside the strict
                                knowledge_extraction_v2 schema (additionalProperties
                                false): a provider with strict structured output
                                cannot return it; a local model can
  invalid_output                parsed, rejected by production validation
  unparseable:<diagnostic>      quality.parse_diagnostic (truncated_at_max_new_tokens,
                                leading_text, trailing_text, code_fence, ...)
  missing_prediction            no prediction row for this reference
  duplicate_prediction          two or more prediction rows (ambiguous: not scored)

Predictions whose id is not in the slice are counted separately (unknown_ids).
Only valid_units and valid_empty are scorable; every other status is a
structural failure under the strict count.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from . import controls, quality

SCORING_NAME = "flh_extraction_scoring_v1"
SCORING_SOURCES = ("audit.py", "challenge.py", "comparison.py", "controls.py", "evaluate.py", "matrix.py", "paired.py",
                   "quality.py", "textnorm.py")
UNIT_KEYS = ("kind", "canonical", "statement", "statement_zh", "example", "confidence")
SYSTEMS = {"oracle": "oracle", "category_only": "category_shortcut", "constant_empty": "over_abstain"}
SCORABLE = ("valid_units", "valid_empty")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scoring_version():
    """The scoring code's identity: SHA-256 over the scoring modules' bytes."""
    here = Path(__file__).resolve().parent
    files = {n: sha256_file(here / n) for n in SCORING_SOURCES if (here / n).is_file()}
    blob = "".join(f"{n}\t{h}\n" for n, h in sorted(files.items()))
    return {"name": SCORING_NAME, "sha256": hashlib.sha256(blob.encode()).hexdigest(), "files": files}


def file_entry(path):
    p = Path(path)
    lines = sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
    return {"path": p.name, "sha256": sha256_file(p), "bytes": p.stat().st_size, "records": lines}


def strict_schema_findings(text):
    """Keys the strict knowledge_extraction_v2 schema forbids or requires,
    for an output text that already parses as JSON (empty list = conforms)."""
    try:
        doc = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return ["not_json"]
    if not isinstance(doc, dict):
        return ["top_level_not_object"]
    out = [f"top_level_extra_key:{k}" for k in sorted(set(doc) - {"units"})]
    units = doc.get("units")
    if not isinstance(units, list):
        return out + ["units_not_list"]
    for i, u in enumerate(units):
        if not isinstance(u, dict):
            out.append(f"unit[{i}]_not_object")
            continue
        out += [f"unit[{i}]_extra_key:{k}" for k in sorted(set(u) - set(UNIT_KEYS))]
        out += [f"unit[{i}]_missing_key:{k}" for k in UNIT_KEYS if k not in u]
    return out


def account(ref_ids, predictions, validated):
    """One status per reference id (see the module docstring).

    predictions: rows with id and output_text (and optionally stopped).
    validated:   production validator results for the predictions that were
                 sent to it (one per id that has exactly one prediction).
    Returns {"rows": [...], "status_counts": {...}, "unknown_ids": [...]}.
    """
    preds = defaultdict(list)
    for p in predictions:
        preds[p["id"]].append(p)
    vals = {v["id"]: v for v in validated}
    ids = set(ref_ids)
    rows = []
    for rid in ref_ids:
        ps = preds.get(rid, [])
        row = {"id": rid, "status": None, "detail": None, "result": None}
        if not ps:
            row["status"] = "missing_prediction"
        elif len(ps) > 1:
            row["status"], row["detail"] = "duplicate_prediction", len(ps)
        else:
            p, v = ps[0], vals.get(rid)
            if v is None:
                row["status"] = "missing_prediction"
                row["detail"] = "prediction not validated"
            elif v.get("valid"):
                extra = [f for f in strict_schema_findings(p.get("output_text")) if "extra_key" in f or "missing_key" in f]
                if extra:
                    row["status"], row["detail"] = "valid_extra_keys", extra
                else:
                    row["status"] = "valid_units" if v["units"] else "valid_empty"
                row["result"] = v
            elif v.get("error_class") == "invalid_output":
                row["status"], row["detail"] = "invalid_output", v.get("error")
            else:
                row["status"] = "unparseable:" + quality.parse_diagnostic(p.get("output_text"), p)
                row["detail"] = v.get("error")
        rows.append(row)
    counts = Counter(r["status"] for r in rows)
    unknown = sorted({p["id"] for p in predictions} - ids)
    assert sum(counts.values()) == len(ref_ids)
    return {"rows": rows, "status_counts": dict(sorted(counts.items())), "references": len(ref_ids),
            "scorable": sum(counts[s] for s in SCORABLE), "unknown_ids": unknown,
            "unknown_id_rows": sum(len(preds[i]) for i in unknown)}


def scored_results(acc):
    """Validator-shaped results for quality.report: a non-scorable row is an
    invalid result (never a missing one, never an abstention)."""
    out = []
    for r in acc["rows"]:
        if r["status"] in SCORABLE:
            out.append(r["result"])
        else:
            out.append({"id": r["id"], "valid": False, "error_class": r["status"], "units": []})
    return out


def decision(v):
    if v is None:
        return "missing"
    if not v.get("valid"):
        return "invalid"
    return "units" if v["units"] else "empty"


def confusion(refs, results):
    """Abstention confusion counts (positive class = the reference has zero
    units). Invalid and missing outputs are their own columns, never folded
    into a decision."""
    res = {r["id"]: r for r in results}
    cols = ("empty", "units", "invalid", "missing")
    table = {k: dict.fromkeys(cols, 0) for k in ("ref_zero", "ref_units")}
    by_cue = {c: {k: dict.fromkeys(cols, 0) for k in ("ref_zero", "ref_units")}
              for c in ("category_other", "category_not_other")}
    for r in refs:
        k = "ref_units" if r["expected"]["units"] else "ref_zero"
        d = decision(res.get(r["id"]))
        table[k][d] += 1
        cue = "category_other" if r["input"]["effective_category"] == "other" else "category_not_other"
        by_cue[cue][k][d] += 1
    z, u = table["ref_zero"], table["ref_units"]
    return {"basis": "exact", "ref_by_pred": table, "by_category_cue": by_cue,
            "abstention": {"true_abstain": z["empty"], "false_extraction": z["units"],
                           "over_abstention": u["empty"], "true_extraction": u["units"],
                           "invalid_or_missing": z["invalid"] + z["missing"] + u["invalid"] + u["missing"]}}


def shortcut_repro(slices, validate, workdir):
    """slices: {name: (path, refs)}. Runs the three synthetic systems through
    the production validator and records manifests and confusion counts."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out = {"schema": "flh_extraction_shortcut_repro_v1", "scoring_version": scoring_version(),
           "systems": {k: f"controls.outputs(refs, {v!r})" for k, v in SYSTEMS.items()},
           "inputs": {}, "runs": {}}
    for name, (path, refs) in slices.items():
        out["inputs"][name] = file_entry(path)
        for sysname, control in SYSTEMS.items():
            rows = controls.outputs(refs, control)
            res = validate(rows)
            o, v = workdir / f"{name}.{sysname}.outputs.jsonl", workdir / f"{name}.{sysname}.validated.jsonl"
            o.write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in rows), encoding="utf-8")
            v.write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in res), encoding="utf-8")
            rep = quality.report(refs, res, outputs=rows)
            out["runs"][f"{name}/{sysname}"] = {
                "outputs": file_entry(o), "validated": file_entry(v), "confusion": confusion(refs, res),
                "abstention_rate": rep["headline"]["abstention_rate"][0],
                "over_abstention_rate": rep["abstention"]["over_abstention_rate"],
                "heuristic_unit_f1": rep["headline"]["unit_f1"][0],
                "structural_validity": rep["headline"]["structural_validity"][0]}
    return out


def shortcut_markdown(rep):
    L = ["# Category-only abstention shortcut: reproduction", "",
         f"Scoring version `{rep['scoring_version']['sha256'][:16]}…` ({rep['scoring_version']['name']}). "
         "Systems are synthetic: `oracle` returns the references, `category_only` abstains iff the effective "
         "category is `other` and otherwise returns the references (an invented unit on a zero-unit reference), "
         "`constant_empty` always returns `{\"units\": []}`. Every output went through the production validator.", "",
         "## Inputs", "", "| Slice | File | Records | SHA-256 |", "|---|---|---|---|"]
    for n, f in rep["inputs"].items():
        L.append(f"| {n} | `{f['path']}` | {f['records']} | `{f['sha256']}` |")
    L += ["", "## Confusion counts (exact)", "",
          "Positive class = the reference has zero units. TA true abstain, FE false extraction (units on a zero "
          "reference), OA over-abstention (empty on a unit reference), TE true extraction; invalid/missing never "
          "fold into a decision.", "",
          "| Slice / system | TA | FE | OA | TE | invalid+missing | abstention | over-abstention | heuristic F1 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for k, r in rep["runs"].items():
        a = r["confusion"]["abstention"]
        L.append(f"| {k} | {a['true_abstain']} | {a['false_extraction']} | {a['over_abstention']} | {a['true_extraction']} "
                 f"| {a['invalid_or_missing']} | {r['abstention_rate']} | {r['over_abstention_rate']} | {r['heuristic_unit_f1']} |")
    L += ["", "## By category cue (category_only)", "", "| Slice | cue | ref zero → empty / units | ref units → empty / units |",
          "|---|---|---|---|"]
    for k, r in rep["runs"].items():
        if not k.endswith("/category_only"):
            continue
        for cue, t in r["confusion"]["by_category_cue"].items():
            L.append(f"| {k.split('/')[0]} | {cue} | {t['ref_zero']['empty']} / {t['ref_zero']['units']} "
                     f"| {t['ref_units']['empty']} / {t['ref_units']['units']} |")
    L += ["", "## Output manifests", "", "| Run | outputs SHA-256 | validated SHA-256 |", "|---|---|---|"]
    for k, r in rep["runs"].items():
        L.append(f"| {k} | `{r['outputs']['sha256'][:16]}…` | `{r['validated']['sha256'][:16]}…` |")
    return "\n".join(L) + "\n"


def account_with_validator(ref_ids, inputs, predictions, validate):
    """Send each reference's single prediction (with its input) to the
    production validator, then account for every reference row."""
    n = Counter(p["id"] for p in predictions)
    send = [{"id": p["id"], "input": inputs[p["id"]], "output_text": p.get("output_text") or ""}
            for p in predictions if p["id"] in inputs and n[p["id"]] == 1]
    return account(ref_ids, predictions, validate(send) if send else [])


# Fixture faults: (status the accounting must report, how the row is built).
FIXTURE_FAULTS = (
    ("unparseable:truncated_at_max_new_tokens", "truncated"),
    ("unparseable:leading_text", "leading_prose"),
    ("unparseable:trailing_text", "trailing_prose"),
    ("unparseable:code_fence", "code_fence"),
    ("unparseable:think_block", "think_block"),
    ("valid_extra_keys", "evidence_key"),
    ("invalid_output", "confidence_out_of_range"),
    ("invalid_output", "blank_statement_zh"),
    ("missing_prediction", "dropped_row"),
    ("duplicate_prediction", "duplicated_row"),
)


def parsing_fixture(refs, every=7):
    """Deterministic raw predictions for a slice: the references as JSON, with
    one fault from FIXTURE_FAULTS on every `every`-th row in turn, plus one row
    for an id outside the slice. Returns (rows, expected status counts)."""
    rows, expect, k = [], Counter(), 0
    for i, r in enumerate(refs):
        units = [dict(u) for u in r["expected"]["units"]]
        good = json.dumps({"units": units}, ensure_ascii=False)
        fault = None
        if i % every == every - 1:
            fault = FIXTURE_FAULTS[k % len(FIXTURE_FAULTS)]
            k += 1
            if fault[1] in ("evidence_key", "confidence_out_of_range", "blank_statement_zh") and not units:
                fault = ("unparseable:leading_text", "leading_prose")
        row = {"id": r["id"], "output_text": good, "stopped": "eos"}
        if fault is None:
            expect["valid_units" if units else "valid_empty"] += 1
            rows.append(row)
            continue
        expect[fault[0]] += 1
        kind = fault[1]
        if kind == "truncated":
            row.update(output_text=good[: max(1, len(good) // 2)], stopped="max_new_tokens")
        elif kind == "leading_prose":
            row["output_text"] = "Here are the units: " + good
        elif kind == "trailing_prose":
            row["output_text"] = good + "\nI hope this helps."
        elif kind == "code_fence":
            row["output_text"] = "```json\n" + good + "\n```"
        elif kind == "think_block":
            row["output_text"] = "<think>\nThe learner asks about one rule.\n</think>\n\n" + good
        elif kind == "evidence_key":
            row["output_text"] = json.dumps({"units": [{**units[0], "evidence": r["input"]["original_input"][:40]}] + units[1:]},
                                            ensure_ascii=False)
        elif kind == "confidence_out_of_range":
            row["output_text"] = json.dumps({"units": [{**units[0], "confidence": 1.5}] + units[1:]}, ensure_ascii=False)
        elif kind == "blank_statement_zh":
            row["output_text"] = json.dumps({"units": [{**units[0], "statement_zh": " "}] + units[1:]}, ensure_ascii=False)
        elif kind == "dropped_row":
            continue
        elif kind == "duplicated_row":
            rows.append(dict(row))
        rows.append(row)
    rows.append({"id": "not-in-slice-0001", "output_text": '{"units": []}', "stopped": "eos"})
    return rows, dict(sorted(expect.items()))
