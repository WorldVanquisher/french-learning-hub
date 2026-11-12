"""Three-system comparison: the pinned matrix and the report that scores it.

  python3 -m flh_extraction comparison-slice --eval E --probe-rb P --challenge C --rendered R [R2 …] --out DIR
      writes DIR/comparison-slice.jsonl (references; local only), comparison-inputs.jsonl
      (id + input, for `extraction-render run`) and comparison-prompts.jsonl (inputs-only
      chat prompts for the Qwen prediction jobs)
  python3 -m flh_extraction comparison-matrix --slice-dir DIR --rendered R --repo ROOT --out MATRIX.json
      pins the slice, output schema, decoding settings and scoring version; every run NOT_PERFORMED
  python3 -m flh_extraction compare --matrix MATRIX.json --slice DIR/comparison-slice.jsonl --render BIN
         [--predictions SYSTEM=FILE …] --out PREFIX
      scores every system that has predictions; the others stay NOT_PERFORMED with null metrics

The slice is the frozen evaluation (200), its `rb` production-input probe (200)
and the challenge slice's `challenge_test` split (72, whole groups only). A
prediction file is either raw model output (`id`, `output_text`, optional
`stopped`) or results already produced by the production path (`extraction-render
run`: `id`, `valid`, `units`, `error_class`). `compare` refuses a run whose
slice hash or scoring version differs from the matrix.
"""

import hashlib
import json
from collections import Counter
from pathlib import Path

from . import comparison, paired, quality, sft

MATRIX_SCHEMA = "flh_extractor_comparison_matrix_v1"
PARTS = ("frozen", "rb", "challenge_test")
VALIDATOR_SOURCES = ("cmd/extraction-render/main.go", "internal/extractor/openai.go", "internal/domain/knowledge.go")
QWEN = {"hf_id": "Qwen/Qwen3.5-4B", "revision": "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a", "model_profile": "qwen3.5-4b"}
QWEN_DECODING = {"do_sample": False, "num_beams": 1, "max_new_tokens": 512, "dtype": "bfloat16",
                 "chat_template_kwargs": {"enable_thinking": False}, "add_generation_prompt": True, "batch_size": 1,
                 "stop": "eos (<|im_end|>) or max_new_tokens; row field `stopped`",
                 "prompt": "system = production developer instruction, user = production user payload (extraction-render render)"}


def canon_sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def part_of(rec):
    if rec["meta"].get("challenge"):
        return "challenge_test"
    return "rb" if rec["id"].endswith("#rb") else "frozen"


def build_slice(evals, probe_rb, chl, rendered):
    test = [r for r in chl if r["meta"]["split_group"] == "challenge_test"]
    groups = Counter(r["meta"]["challenge"]["group_id"] for r in test)
    whole = {g for g, n in Counter(r["meta"]["challenge"]["group_id"] for r in chl).items() if groups.get(g) == n}
    if set(groups) != whole:
        raise ValueError("challenge_test does not hold whole groups")
    refs = list(evals) + list(probe_rb) + test
    ids = [r["id"] for r in refs]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate ids in the comparison slice")
    inputs = [{"id": r["id"], "input": r["input"]} for r in refs]
    prompts = sft.eval_prompts(refs, rendered, split_groups=("eval", "challenge_test"))
    if [p["id"] for p in prompts] != ids:
        raise ValueError("prompts do not cover the slice in order")
    return refs, inputs, prompts


def write_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def build_matrix(slice_dir, rendered_row, repo_root):
    sd, root = Path(slice_dir), Path(repo_root)
    refs = [json.loads(line) for line in (sd / "comparison-slice.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    parts = Counter(part_of(r) for r in refs)
    files = {n: comparison.file_entry(sd / n) for n in ("comparison-slice.jsonl", "comparison-inputs.jsonl", "comparison-prompts.jsonl")}
    validator = {p: comparison.sha256_file(root / p) for p in VALIDATOR_SOURCES}
    common = {"input_slice": "comparison-inputs.jsonl (provider) / comparison-prompts.jsonl (local model): the same inputs",
              "scored_by": "compare (account + production validator + quality + paired consistency)"}
    systems = [
        {"system": "current_extractor", "status": "NOT_PERFORMED", "reason": "paid provider call; owner decision",
         "provenance": "openai:<OPENAI_MODEL>:knowledge_extraction_v2 (record the model at run time)",
         "how": "EXTRACTOR_PROVIDER=openai with OPENAI_MODEL set: extraction-render run -in comparison-inputs.jsonl "
                f"-out current-results.jsonl -max-requests {len(refs)} -confirm-paid-calls",
         "decoding": {"api": "OpenAI Responses", "structured_output": "json_schema strict (knowledge_units)", "store": False,
                      "temperature": "not set by the request (provider default)", "retries": 0,
                      "requests": len(refs)}, **common},
        {"system": "qwen3.5-4b-untuned", "status": "NOT_PERFORMED", "reason": "needs the GPU prediction job (readiness step 6)",
         "model": QWEN, "adapter": None, "how": "rendered/predict-base-a.json then predict-base-b.json (owner submits; concatenate a, b)", "decoding": QWEN_DECODING, **common},
        {"system": "qwen3.5-4b-tuned", "status": "NOT_PERFORMED", "reason": "needs the experiment and adapter prediction jobs (steps 7-8)",
         "model": QWEN, "adapter": "sft-experiment output (config sft-qwen3.5-4b-lora.json; train/dev hashes in input-manifest.json)",
         "how": "rendered/predict-eval-a.json then predict-eval-b.json (owner submits; concatenate a, b)", "decoding": QWEN_DECODING, **common},
    ]
    m = {"schema": MATRIX_SCHEMA, "created": "2026-11-12", "slice": {"files": files, "parts": dict(sorted(parts.items())),
                                                                     "records": len(refs)},
         "output_schema": {"name": "knowledge_extraction_v2", "sha256": canon_sha(rendered_row["schema"]),
                           "developer_instruction_sha256": hashlib.sha256(rendered_row["developer"].encode()).hexdigest()},
         "scoring_version": comparison.scoring_version(), "validator_sources": validator, "systems": systems,
         "real_runs_performed": 0}
    m["matrix_sha256"] = canon_sha({k: v for k, v in m.items() if k != "matrix_sha256"})
    return m


def _metrics(refs, results, outputs):
    by = {p: [r for r in refs if part_of(r) == p] for p in PARTS}
    ids = {p: {r["id"] for r in by[p]} for p in PARTS}
    out = {}
    for p in ("frozen", "rb"):
        rs = [x for x in results if x["id"] in ids[p]]
        q = quality.report(by[p], rs, outputs=[o for o in outputs if o["id"] in ids[p]] if outputs else None)
        out[p] = {"headline": {k: v[0] for k, v in q["headline"].items()}, "confusion": comparison.confusion(by[p], rs),
                  "over_abstention_rate": q["abstention"]["over_abstention_rate"]}
    rs = [x for x in results if x["id"] in ids["challenge_test"]]
    pc = paired.report(by["challenge_test"], rs)
    out["challenge_test"] = {"headline": pc["headline"], "by_intent": {k: {m: v[m]["rate"] for m in ("decision_consistent", "paired_correct")}
                                                                         for k, v in pc["by_intent"].items()},
                             "confusion": comparison.confusion(by["challenge_test"], rs)}
    return out


def compare(matrix, slice_path, predictions, validate):
    """predictions: {system: rows}. Returns the comparison report."""
    refs = [json.loads(line) for line in Path(slice_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    rep = {"schema": "flh_extractor_comparison_report_v1", "matrix_sha256": matrix["matrix_sha256"], "systems": {}, "refused": []}
    if comparison.sha256_file(slice_path) != matrix["slice"]["files"]["comparison-slice.jsonl"]["sha256"]:
        rep["refused"].append("slice hash differs from the matrix")
    sv = comparison.scoring_version()["sha256"]
    if sv != matrix["scoring_version"]["sha256"]:
        rep["refused"].append(f"scoring version {sv[:12]} differs from the matrix {matrix['scoring_version']['sha256'][:12]}")
    ids = [r["id"] for r in refs]
    inputs = {r["id"]: r["input"] for r in refs}
    for s in matrix["systems"]:
        name = s["system"]
        rows = predictions.get(name)
        if rows is None or rep["refused"]:
            rep["systems"][name] = {"status": "NOT_PERFORMED" if rows is None else "REFUSED", "rows": None, "metrics": None}
            continue
        raw = [r for r in rows if "output_text" in r]
        done = [r for r in rows if "output_text" not in r]
        if raw and done:
            raise ValueError(f"{name}: a prediction file mixes raw outputs and production results")
        # Results from the production path (extraction-render run) carry no raw text to diagnose.
        acc = comparison.account_with_validator(ids, inputs, raw, validate) if raw else account_results(ids, done)
        res = comparison.scored_results(acc)
        rep["systems"][name] = {"status": "MEASURED", "rows": {k: acc[k] for k in ("references", "scorable", "status_counts",
                                                                                  "unknown_ids", "unknown_id_rows")},
                                "metrics": _metrics(refs, res, raw or None)}
    rep["real_runs_measured"] = sum(1 for v in rep["systems"].values() if v["status"] == "MEASURED")
    return rep


def account_results(ref_ids, results):
    """Accounting for rows that are already production results (provider path)."""
    by = {}
    dup = Counter(r["id"] for r in results)
    for r in results:
        by[r["id"]] = r
    rows = []
    for rid in ref_ids:
        v = by.get(rid)
        if v is None:
            st = "missing_prediction"
        elif dup[rid] > 1:
            st = "duplicate_prediction"
        elif v.get("valid"):
            st = "valid_units" if v["units"] else "valid_empty"
        elif v.get("error_class") == "invalid_output":
            st = "invalid_output"
        else:
            st = "provider_error:" + (v.get("error_class") or "unknown")
        rows.append({"id": rid, "status": st, "detail": None, "result": v if st.startswith("valid_") else None})
    counts = Counter(r["status"] for r in rows)
    unknown = sorted(set(by) - set(ref_ids))
    return {"rows": rows, "status_counts": dict(sorted(counts.items())), "references": len(ref_ids),
            "scorable": sum(counts[s] for s in comparison.SCORABLE), "unknown_ids": unknown,
            "unknown_id_rows": sum(dup[i] for i in unknown)}


def markdown(matrix, rep=None):
    L = ["# Extractor comparison matrix", "",
         f"Matrix `{matrix['matrix_sha256'][:16]}…`; slice {matrix['slice']['records']} records "
         f"({', '.join(f'{k} {v}' for k, v in matrix['slice']['parts'].items())}); output schema "
         f"`{matrix['output_schema']['name']}` `{matrix['output_schema']['sha256'][:16]}…`; scoring "
         f"`{matrix['scoring_version']['sha256'][:16]}…`.", "",
         "| System | Status | Model / provenance | Decoding | How (owner) |", "|---|---|---|---|---|"]
    for s in matrix["systems"]:
        st = rep["systems"][s["system"]]["status"] if rep else s["status"]
        model = s.get("provenance") or f"{s['model']['hf_id']}@{s['model']['revision'][:8]}" + (" + adapter" if s.get("adapter") else "")
        dec = ", ".join(f"{k}={json.dumps(v) if not isinstance(v, str) else v}" for k, v in s["decoding"].items()
                        if k not in ("prompt", "stop"))
        L.append(f"| {s['system']} | **{st}** | {model} | {dec} | {s['how']} |")
    if rep:
        L += ["", "| System | Rows (scorable/ref) | Status counts | Frozen abstention | rb abstention | rb false extraction "
                  "| Paired consistency | Paired accuracy | Frozen F1 (heur.) |", "|---|---|---|---|---|---|---|---|---|"]
        for name, v in rep["systems"].items():
            if v["metrics"] is None:
                L.append(f"| {name} | — | {v['status']} | — | — | — | — | — | — |")
                continue
            m = v["metrics"]
            L.append(f"| {name} | {v['rows']['scorable']}/{v['rows']['references']} | `{json.dumps(v['rows']['status_counts'])}` "
                     f"| {m['frozen']['headline']['abstention_rate']} | {m['rb']['headline']['abstention_rate']} "
                     f"| {m['rb']['confusion']['abstention']['false_extraction']} | {m['challenge_test']['headline']['paired_consistency']} "
                     f"| {m['challenge_test']['headline']['paired_accuracy']} | {m['frozen']['headline']['unit_f1']} |")
    return "\n".join(L) + "\n"
