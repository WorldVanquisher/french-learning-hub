"""FLH-059 bounded E5 numerical-reproducibility diagnostic.

Encodes the same rendered model inputs (inputs.json: production-rendered
Concept documents and Unit queries from the frozen FLH-045 fixture, with no
labels or expected targets) under a fixed matrix of batch shapes, for each
dtype x batching policy, directly through the flh_e5 encoder code on the local
GPU. It never contacts a service or endpoint, and it changes no tolerance.

  plan          print the matrix and its bounds (no torch, no model)
  run           encode the matrix on CUDA, then analyze (writes outside the repo)
  analyze       offline arithmetic over a finished run directory
  inputs        check (default) or rewrite inputs.json from the Go renderers

Standard library only, apart from the flh_e5 encoder that `run` imports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
from array import array
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
E5_DIR = ROOT / "tools" / "embedding" / "e5"
INPUTS = HERE / "inputs.json"
FROZEN_FIXTURE_SHA256 = "92726376c7892ef5e7eb539648828eab3ccf9d026912a4a5509dc461c3b7043a"

DTYPES = ("float16", "float32")
POLICIES = ("dynamic_v1", "singleton_v1", "fixed_v1")
MICROBATCH = 8           # the deployed service's microbatch (FLH-054, FLH-058)
QUERY_SAMPLE = 8         # queries chosen by token count only, never by label
DIMENSIONS = 768
MAX_POSITIONS_PER_CONFIG = 600
# FLH-056's declared coordinate tolerance, reported unchanged; never loosened.
TOL_ABS, TOL_REL = 1e-5, 1e-4
TOP_K = 5
RANKING_CONDITIONS = ("ordered", "reversed", "rotated", "flh058_shape")
REFERENCE = ("float32", "singleton_v1")


class DiagnosticError(Exception):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_inputs(path: Path = INPUTS) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "flh059_model_inputs_v1":
        raise DiagnosticError("inputs.json: unexpected schema")
    if len(data["documents"]) != 24 or len(data["queries"]) != 56:
        raise DiagnosticError("inputs.json: expected 24 documents and 56 queries")
    texts = [x["text"] for x in data["documents"] + data["queries"]]
    if len(set(texts)) != len(texts):
        raise DiagnosticError("inputs.json: texts must be unique")
    for item in data["documents"] + data["queries"]:
        if set(item) != {"id", "text"}:
            raise DiagnosticError("inputs.json: items carry only id and text (no labels)")
    return data


# ---------------------------------------------------------------- the matrix

def select_queries(queries: list[dict], token_counts: dict[str, int], n: int = QUERY_SAMPLE) -> list[dict]:
    """n queries evenly spaced by token count (ties by input order), always
    including the shortest and longest. Uses no label or target."""
    ordered = sorted(range(len(queries)), key=lambda i: (token_counts[queries[i]["text"]], i))
    if n >= len(ordered):
        picks = ordered
    else:
        picks = sorted({ordered[round(k * (len(ordered) - 1) / (n - 1))] for k in range(n)})
        k = 0
        while len(picks) < n:  # rounding collisions: fill with the next unused in order
            if ordered[k] not in picks:
                picks.append(ordered[k])
            k += 1
    return [queries[i] for i in sorted(picks)]


def build_matrix(inputs: dict, token_counts: dict[str, int]) -> list[dict]:
    """Requests per condition. Each request is a list of item ids; the service
    rule splits it into consecutive microbatches of MICROBATCH."""
    docs = [d["id"] for d in inputs["documents"]]
    qs = [q["id"] for q in select_queries(inputs["queries"], token_counts)]
    text = {x["id"]: x["text"] for x in inputs["documents"] + inputs["queries"]}
    pool = docs + qs
    shortest = min(pool, key=lambda i: (token_counts[text[i]], pool.index(i)))
    longest = max(pool, key=lambda i: (token_counts[text[i]], -pool.index(i)))
    reqs: list[dict] = []

    def add(condition, items):
        reqs.append({"condition": condition, "items": list(items)})

    for i in pool:
        add("singleton_a", [i])
    for i in pool:
        add("singleton_b", [i])
    add("ordered", docs)
    add("reversed", docs[::-1])
    add("rotated", docs[3:] + docs[:3])
    for d in docs:
        add("short_companion", [d, shortest] if d != shortest else [d, longest])
    for d in docs:
        add("long_companion", [d, longest] if d != longest else [d, shortest])
    for k in range(0, len(docs), 3):
        add("partial3", docs[k:k + 3])
    for q in qs:
        add("flh058_shape", [q] + docs)
    return reqs


def microbatches(items: list[str], size: int = MICROBATCH) -> list[list[str]]:
    return [items[k:k + size] for k in range(0, len(items), size)]


def plan_summary(reqs: list[dict]) -> dict:
    by: dict[str, dict] = {}
    for r in reqs:
        c = by.setdefault(r["condition"], {"requests": 0, "positions": 0, "microbatches": 0})
        c["requests"] += 1
        c["positions"] += len(r["items"])
        c["microbatches"] += len(microbatches(r["items"]))
    positions = sum(c["positions"] for c in by.values())
    return {"conditions": by, "positions_per_config": positions,
            "configs": [f"{d}/{p}" for d in DTYPES for p in POLICIES],
            "positions_total": positions * len(DTYPES) * len(POLICIES)}


# ---------------------------------------------------------------- execution

def shape_of(policy: str, mb_tokens: list[int], row: int) -> tuple[int, int]:
    """(rows, width) of the forward pass that computed this row."""
    if policy == "dynamic_v1":
        return len(mb_tokens), max(mb_tokens)
    if policy == "singleton_v1":
        return 1, mb_tokens[row]
    return MICROBATCH, 512


def encode_config(backend, policy: str, reqs: list[dict], text: dict[str, str], tokens: dict[str, int]):
    """Run every request; returns (records, flat float list, seconds)."""
    sys.path.insert(0, str(E5_DIR))
    from flh_e5 import batching  # noqa: E402

    records, flat, seconds = [], [], 0.0
    for r_index, req in enumerate(reqs):
        position = 0
        for m_index, mb in enumerate(microbatches(req["items"])):
            texts = [text[i] for i in mb]
            started = time.perf_counter()
            vectors = batching.apply_policy(policy, texts, rows=MICROBATCH,
                                            encode_dynamic=backend.encode_dynamic, encode_fixed=backend.encode_fixed)
            seconds += time.perf_counter() - started
            if len(vectors) != len(mb):
                raise DiagnosticError("encoder returned a wrong number of vectors")
            mb_tokens = [tokens[t] for t in texts]
            for row, (item, vec) in enumerate(zip(mb, vectors)):
                if len(vec) != DIMENSIONS or not all(math.isfinite(x) for x in vec):
                    raise DiagnosticError("encoder returned a malformed vector")
                rows, width = shape_of(policy, mb_tokens, row)
                records.append({"condition": req["condition"], "request": r_index, "position": position,
                                "microbatch": m_index, "microbatch_size": len(mb), "row": row,
                                "forward_rows": rows, "forward_width": width, "item": item,
                                "offset": len(flat) // DIMENSIONS})
                flat.extend(vec)
                position += 1
    return records, flat, seconds


def write_f32(path: Path, flat: list[float]) -> str:
    arr = array("f", flat)
    if sys.byteorder != "little":
        arr.byteswap()
    data = arr.tobytes()
    path.write_bytes(data)
    return sha256(data)


def read_f32(path: Path) -> array:
    arr = array("f")
    arr.frombytes(path.read_bytes())
    if sys.byteorder != "little":
        arr.byteswap()
    return arr


def guard_out(out: Path) -> Path:
    out = out.expanduser().resolve()
    try:
        out.relative_to(ROOT.resolve())
        raise DiagnosticError(f"--out must be outside the repository ({ROOT})")
    except ValueError:
        pass
    if out.exists() and any(out.iterdir()):
        raise DiagnosticError("--out exists and is not empty; results are never overwritten")
    out.mkdir(parents=True, exist_ok=True)
    return out


def save(path: Path, obj) -> None:
    if path.exists():
        raise DiagnosticError(f"refusing to overwrite {path.name}")
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")


class CudaBackend:
    """Adapter over the real flh_e5 encoder for one dtype. encode_dynamic is
    the unchanged legacy E5CudaEncoder.encode; encode_fixed is fixed_v1's."""

    def __init__(self, model_dir: Path, dtype: str):
        sys.path.insert(0, str(E5_DIR))
        from flh_e5 import batching
        from flh_e5.encoder import E5CudaEncoder

        self.enc = batching.make_policy_encoder(model_dir, dtype, "singleton_v1", MICROBATCH)
        self.encode_dynamic = lambda texts: E5CudaEncoder.encode(self.enc, texts)
        self.encode_fixed = self.enc.encode_fixed
        self.count_tokens = self.enc.count_tokens
        self.files = self.enc.files

    def evidence(self) -> dict:
        return {"runtime": self.enc.runtime_versions(), "numerics": self.enc.numerics, "gpu": self.enc.gpu_evidence()}

    def close(self) -> None:
        self.enc.close()


def run(out: Path, model_dir: Path | None, dtypes, policies, backend_factory=None) -> int:
    inputs = load_inputs()
    out = guard_out(out)
    sys.path.insert(0, str(E5_DIR))
    from flh_e5 import batching, manifest

    text = {x["id"]: x["text"] for x in inputs["documents"] + inputs["queries"]}
    factory = backend_factory or (lambda dtype: CudaBackend(model_dir, dtype))
    env = {"schema": "flh059_run_v1", "argv": sys.argv[1:], "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "python": platform.python_version(), "platform": platform.platform(terse=True),
           "inputs_sha256": sha256(INPUTS.read_bytes()), "script_sha256": sha256(Path(__file__).read_bytes()),
           "flh_e5_code_sha256_v1": manifest.code_sha256(E5_DIR / "flh_e5"),
           "flh_e5_code_sha256_v2": batching.code_sha256_v2(E5_DIR / "flh_e5"),
           "microbatch": MICROBATCH, "dtypes": list(dtypes), "policies": list(policies), "backend": {}}
    matrix = None
    for dtype in dtypes:
        backend = factory(dtype)
        try:
            tokens = dict(zip(text.values(), backend.count_tokens(list(text.values()))))
            if max(tokens.values()) > 512:
                raise DiagnosticError("an input exceeds 512 tokens")
            reqs = build_matrix(inputs, tokens)
            summary = plan_summary(reqs)
            if summary["positions_per_config"] > MAX_POSITIONS_PER_CONFIG:
                raise DiagnosticError("matrix exceeds its position bound")
            if matrix is None:
                matrix = {"requests": reqs, "summary": summary,
                          "token_counts": {i: tokens[t] for i, t in text.items()}}
                save(out / "matrix.json", matrix)
            elif reqs != matrix["requests"]:
                raise DiagnosticError("token counts differ between dtypes; matrix not comparable")
            for policy in policies:  # one untimed warmup pass per config
                batching.apply_policy(policy, [text[reqs[0]["items"][0]]], rows=MICROBATCH,
                                      encode_dynamic=backend.encode_dynamic, encode_fixed=backend.encode_fixed)
                records, flat, seconds = encode_config(backend, policy, reqs, text, tokens)
                name = f"{dtype}-{policy}"
                digest = write_f32(out / f"vectors-{name}.f32", flat)
                save(out / f"records-{name}.json", {"dtype": dtype, "policy": policy, "encode_seconds": seconds,
                                                    "vectors_sha256": digest, "records": records})
                print(f"{name}: {len(records)} positions, {seconds:.3f}s encode", flush=True)
            env["backend"][dtype] = backend.evidence()
            env["model_files"] = backend.files
        finally:
            backend.close()
    env["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save(out / "environment.json", env)
    return analyze(out)


# ---------------------------------------------------------------- analysis

def within_tolerance(a, b) -> bool:
    return all(abs(x - y) <= TOL_ABS + TOL_REL * max(abs(x), abs(y)) for x, y in zip(a, b))


def compare(a, b) -> dict:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return {"max_abs": max(abs(x - y) for x, y in zip(a, b)), "cos_dist": 1.0 - dot / (na * nb),
            "bitwise": list(a) == list(b), "tolerance_ok": within_tolerance(a, b)}


def cos(a, b) -> float:
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def ranking(qv, doc_vecs: dict[str, list[float]]) -> list[tuple[str, float]]:
    return sorted(((d, cos(qv, v)) for d, v in doc_vecs.items()), key=lambda t: (-t[1], t[0]))


def analyze_config(records: list[dict], vecs: array, matrix: dict) -> dict:
    def vec(r):
        o = r["offset"] * DIMENSIONS
        return vecs[o:o + DIMENSIONS]

    ref = {r["item"]: vec(r) for r in records if r["condition"] == "singleton_a"}
    conds: dict[str, dict] = {}
    worst = None
    norms = []
    shape_groups: dict[tuple, list] = {}
    for r in records:
        v = vec(r)
        norms.append(math.sqrt(sum(x * x for x in v)))
        if r["condition"] == "singleton_a":
            continue
        c = compare(ref[r["item"]], v)
        s = conds.setdefault(r["condition"], {"positions": 0, "bitwise_equal": 0, "tolerance_failures": 0,
                                              "max_abs": 0.0, "max_cos_dist": 0.0})
        s["positions"] += 1
        s["bitwise_equal"] += c["bitwise"]
        s["tolerance_failures"] += not c["tolerance_ok"]
        s["max_abs"] = max(s["max_abs"], c["max_abs"])
        s["max_cos_dist"] = max(s["max_cos_dist"], c["cos_dist"])
        if worst is None or c["max_abs"] > worst["max_abs"]:
            worst = {"item": r["item"], "condition": r["condition"], "request": r["request"], **c}
        shape_groups.setdefault((r["item"], r["forward_rows"], r["forward_width"], r["row"]), []).append(v)
    # Do occurrences computed with an identical forward shape and row agree
    # bitwise, whatever their companions? (An observation, not a cause.)
    multi = [g for g in shape_groups.values() if len(g) > 1]
    same_shape = {"groups_with_repeats": len(multi),
                  "groups_all_bitwise_equal": sum(all(list(x) == list(g[0]) for x in g[1:]) for g in multi)}
    # occurrences whose forward shape equals the singleton reference's shape
    ref_shape = {r["item"]: (r["forward_rows"], r["forward_width"]) for r in records if r["condition"] == "singleton_a"}
    shape_split = {"same_shape_as_reference": {"n": 0, "bitwise": 0}, "different_shape": {"n": 0, "bitwise": 0}}
    for r in records:
        if r["condition"] == "singleton_a":
            continue
        key = "same_shape_as_reference" if (r["forward_rows"], r["forward_width"]) == ref_shape[r["item"]] else "different_shape"
        shape_split[key]["n"] += 1
        shape_split[key]["bitwise"] += list(vec(r)) == list(ref[r["item"]])

    doc_ids = sorted({i for req in matrix["requests"] if req["condition"] == "ordered" for i in req["items"]})
    query_ids = [req["items"][0] for req in matrix["requests"] if req["condition"] == "flh058_shape"]
    rank = {"comparisons": 0, "top5_order_changed": 0, "top5_set_changed": 0, "max_score_change": 0.0,
            "reference_min_adjacent_margin_top6": None, "pairs_within_twice_max_score_change": 0}
    ref_margins = []
    ref_rank = {}
    for q in query_ids:
        rr = ranking(ref[q], {d: ref[d] for d in doc_ids})
        ref_rank[q] = rr
        ref_margins.extend(rr[k][1] - rr[k + 1][1] for k in range(TOP_K))
    by_req: dict[int, dict] = {}
    for r in records:
        if r["condition"] in RANKING_CONDITIONS:
            by_req.setdefault(r["request"], {"condition": r["condition"], "v": {}})["v"][r["item"]] = vec(r)
    for req in by_req.values():
        dv = {d: req["v"][d] for d in doc_ids}
        for q in query_ids:
            if req["condition"] == "flh058_shape" and q not in req["v"]:
                continue
            qv = req["v"][q] if req["condition"] == "flh058_shape" else ref[q]
            got = ranking(qv, dv)
            exp = ref_rank[q]
            rank["comparisons"] += 1
            rank["top5_order_changed"] += [d for d, _ in got[:TOP_K]] != [d for d, _ in exp[:TOP_K]]
            rank["top5_set_changed"] += {d for d, _ in got[:TOP_K]} != {d for d, _ in exp[:TOP_K]}
            es = dict(exp)
            rank["max_score_change"] = max(rank["max_score_change"], max(abs(s - es[d]) for d, s in got))
    if ref_margins:
        rank["reference_min_adjacent_margin_top6"] = min(ref_margins)
        rank["pairs_within_twice_max_score_change"] = sum(m <= 2 * rank["max_score_change"] for m in ref_margins)
    return {"conditions": conds, "worst": worst, "norm_min": min(norms), "norm_max": max(norms),
            "same_shape_rows": same_shape, "shape_vs_reference": shape_split, "ranking": rank,
            "tolerance_failures": sum(c["tolerance_failures"] for c in conds.values()),
            "bitwise_equal": sum(c["bitwise_equal"] for c in conds.values()),
            "compared_positions": sum(c["positions"] for c in conds.values())}


def analyze(out: Path) -> int:
    out = out.resolve()
    matrix = json.loads((out / "matrix.json").read_text(encoding="utf-8"))
    configs, refs = {}, {}
    for rec_path in sorted(out.glob("records-*.json")):
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        name = f"{rec['dtype']}-{rec['policy']}"
        vpath = out / f"vectors-{name}.f32"
        if sha256(vpath.read_bytes()) != rec["vectors_sha256"]:
            raise DiagnosticError(f"{vpath.name}: hash mismatch")
        vecs = read_f32(vpath)
        result = analyze_config(rec["records"], vecs, matrix)
        result["encode_seconds"] = rec["encode_seconds"]
        result["forward_passes"] = len({(r["request"], r["microbatch"]) for r in rec["records"]}) if rec["policy"] != "singleton_v1" else len(rec["records"])
        configs[name] = result
        refs[(rec["dtype"], rec["policy"])] = {r["item"]: vecs[r["offset"] * DIMENSIONS:(r["offset"] + 1) * DIMENSIONS]
                                               for r in rec["records"] if r["condition"] == "singleton_a"}
    cross = {}
    if REFERENCE in refs:
        base = refs[REFERENCE]
        for (dtype, policy), ref in sorted(refs.items()):
            cs = [compare(base[i], ref[i]) for i in base]
            cross[f"{dtype}-{policy}"] = {"max_abs_vs_float32_singleton": max(c["max_abs"] for c in cs),
                                          "max_cos_dist_vs_float32_singleton": max(c["cos_dist"] for c in cs),
                                          "tolerance_failures_vs_float32_singleton": sum(not c["tolerance_ok"] for c in cs)}
    # Pre-registered rule (docs/plans/FLH-059): a configuration passes when no
    # repeated identical text violates the unchanged FLH-056 tolerance in any
    # condition and no top-5 order changes. Bitwise equality is reported only.
    passing = [n for n, c in configs.items() if c["tolerance_failures"] == 0 and c["ranking"]["top5_order_changed"] == 0]
    order = [f"{d}-{p}" for d in DTYPES for p in POLICIES]
    candidate = next((n for n in order if n in passing), None)
    result = {"schema": "flh059_analysis_v1", "tolerance": {"abs": TOL_ABS, "rel": TOL_REL, "source": "FLH-056, unchanged"},
              "reference": "per configuration: the singleton_a vector of the same text", "configs": configs,
              "cross_config": cross, "rule": "tolerance_failures == 0 and top5_order_changed == 0; preference order " + ", ".join(order),
              "passing": passing, "candidate": candidate,
              "note": "diagnostic evidence only; choosing a deployment is a separate decision"}
    save(out / "analysis.json", result)
    print(render_summary(result))
    return 0


def render_summary(result: dict) -> str:
    lines = ["config                  tol_fail  bitwise/compared  max_abs     max_cos_dist  top5_changed  encode_s"]
    for name, c in result["configs"].items():
        md = max(x["max_cos_dist"] for x in c["conditions"].values())
        ma = max(x["max_abs"] for x in c["conditions"].values())
        lines.append(f"{name:<24}{c['tolerance_failures']:>8}  {c['bitwise_equal']:>7}/{c['compared_positions']:<8}  "
                     f"{ma:.3e}   {md:.3e}     {c['ranking']['top5_order_changed']:>5}/{c['ranking']['comparisons']:<5} {c['encode_seconds']:.2f}")
    lines.append(f"passing (pre-registered rule): {result['passing'] or 'none'}; candidate: {result['candidate']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- inputs

def render_inputs() -> dict:
    """Re-render the inputs with the production Go renderers through the
    read-only FLH-051 overlay that FLH-058 used (needs Go; offline)."""
    fixture = ROOT / "scripts/validation/flh045/fixture.json"
    if sha256(fixture.read_bytes()) != FROZEN_FIXTURE_SHA256:
        raise DiagnosticError("frozen fixture hash mismatch")
    with tempfile.TemporaryDirectory(prefix="flh059-") as tmp:
        tmp = Path(tmp)
        overlay = {"Replace": {
            str(ROOT / "internal/application/flh058_production_bridge.go"): str(ROOT / "scripts/validation/flh051/production_bridge.go.txt"),
            str(ROOT / "scripts/validation/flh048/flh058_independent_test.go"): str(ROOT / "scripts/validation/flh051/independent_test.go.txt")}}
        (tmp / "overlay.json").write_text(json.dumps(overlay))
        env = dict(os.environ, FLH051_FIXTURE=str(fixture), FLH051_GO_EVIDENCE=str(tmp / "rendered.json"))
        p = subprocess.run(["go", "test", "-overlay", str(tmp / "overlay.json"), "-count=1",
                            "-run", "^TestFLH051ProductionParityAndEvidence$", "./scripts/validation/flh048"],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            raise DiagnosticError("Go rendering failed:\n" + p.stdout[-2000:] + p.stderr[-2000:])
        cap = json.loads((tmp / "rendered.json").read_text(encoding="utf-8"))
    batches = cap["provider_batches"]
    if not cap["production_parity"] or any(b[1:] != batches[0][1:] for b in batches):
        raise DiagnosticError("unexpected capture shape")
    return {"schema": "flh059_model_inputs_v1",
            "source": {"fixture": "scripts/validation/flh045/fixture.json", "fixture_sha256": FROZEN_FIXTURE_SHA256,
                       "renderer": "production Go renderers via the FLH-051 overlay (TestFLH051ProductionParityAndEvidence)",
                       "contents": "model input strings only; no labels, targets, splits or languages"},
            "documents": [{"id": f"C{d['ConceptID']:03d}", "text": t} for d, t in zip(cap["documents"], batches[0][1:])],
            "queries": [{"id": f"U{q['UnitID']:03d}", "text": b[0]} for q, b in zip(cap["queries"], batches)]}


def inputs_command(write: bool) -> int:
    fresh = json.dumps(render_inputs(), indent=1, ensure_ascii=False) + "\n"
    if write:
        INPUTS.write_text(fresh, encoding="utf-8")
        print(f"wrote {INPUTS.relative_to(ROOT)} sha256 {sha256(fresh.encode())}")
        return 0
    same = INPUTS.read_text(encoding="utf-8").replace("\r\n", "\n") == fresh
    print("inputs.json matches the production renderers" if same else "inputs.json DIFFERS from the production renderers")
    return 0 if same else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="diagnose.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    r = sub.add_parser("run")
    r.add_argument("--model-dir", required=True, type=Path)
    r.add_argument("--out", required=True, type=Path, help="new or empty directory outside the repository")
    r.add_argument("--dtypes", default=",".join(DTYPES))
    r.add_argument("--policies", default=",".join(POLICIES))
    a = sub.add_parser("analyze")
    a.add_argument("--out", required=True, type=Path)
    i = sub.add_parser("inputs")
    i.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.command == "plan":
            inputs = load_inputs()
            approx = {x["text"]: len(x["text"].encode()) // 4 for x in inputs["documents"] + inputs["queries"]}
            reqs = build_matrix(inputs, approx)
            print(json.dumps(plan_summary(reqs), indent=1))
            print("query sample is chosen from real token counts at run time; this plan approximates them")
            return 0
        if args.command == "run":
            dtypes = [d for d in args.dtypes.split(",") if d]
            policies = [p for p in args.policies.split(",") if p]
            if not dtypes or set(dtypes) - set(DTYPES) or not policies or set(policies) - set(POLICIES):
                raise DiagnosticError(f"--dtypes from {DTYPES}, --policies from {POLICIES}")
            return run(args.out, args.model_dir, dtypes, policies)
        if args.command == "analyze":
            return analyze(args.out)
        return inputs_command(args.write)
    except DiagnosticError as e:
        print(f"diagnose: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
