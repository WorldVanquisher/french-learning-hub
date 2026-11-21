"""Model readiness for the cross-subject workflow: artifacts, availability, measurements (local; no network, no model call).

  python3 -I -B scripts/model_readiness.py [--qwen-dir DIR …] [--whisper-dir DIR] [--runs 20] [--json OUT]

* **inventory** (EXT-071): every pinned artifact the repository names, with its expected digest and size:
  - the extraction model profiles (``flh_extraction/models.py``, ``configs/*.sha256``);
  - the Speaking models (``tools/speaking/flh_speaking/pins.py``);
  - the rules-only extraction service (its deployment ID and code hashes).
* **availability** (EXT-073, EXT-074): what is actually on this machine. Each pinned file is searched for in the
  given directories and reported ``PRESENT_OK``, ``HASH_MISMATCH``, ``SIZE_ONLY`` or ``MISSING``. Only file names
  are written, never a directory path.
* **measurements** (EXT-075 to EXT-077): the fixture workflow (draft, review, units export with recall) on the
  music source:
  - **cold:** a new Python process per run, interpreter start and imports included;
  - **warm:** repeated in one process.

  Time is split into preprocessing (reading and checking the source, grounding the quotes) and the rest (review,
  export, recall). The workflow runs no model, so its inference time is reported as 0 with that reason. Peak RSS
  is that of a separate child process (``wait4``).

Timings depend on this machine and its load. The report records CPU, cores and load average.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from flh_extraction import models  # noqa: E402
from flh_extraction import practice as pr  # noqa: E402
from flh_extraction import review2 as rv  # noqa: E402
from flh_extraction import service as svc  # noqa: E402
from flh_extraction import units as un  # noqa: E402

MUSIC = os.path.join(HERE, "fixtures", "xsubject_v1", "sources", "music_thirds.r1.json")


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def speaking_pins() -> dict:
    sys.path.insert(0, os.path.join(ROOT, "tools", "speaking"))
    from flh_speaking import pins
    return pins.MODELS


def inventory() -> dict:
    out = {"extraction_models": {}, "speaking_models": {}, "extraction_service": {}}
    for name, p in models.PROFILES.items():
        if not isinstance(p, dict) or not p.get("hf_id"):
            continue
        sums = os.path.join(HERE, "configs", f"{name}-{p['revision'][:8]}.sha256")
        files = {}
        if os.path.exists(sums):
            with open(sums, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        h, n = line.split(None, 1)
                        files[n.strip()] = {"sha256": h}
        out["extraction_models"][name] = {"repo": p["hf_id"], "status": p.get("status"), "revision": p["revision"], "license": p.get("license"),
                                          "weights_bytes": p.get("weights_bytes"), "pinned_files": files,
                                          "weights": "shards named by model.safetensors.index.json; size only (not pinned by hash)"}
    for name, m in speaking_pins().items():
        out["speaking_models"][name] = {"repo": m["repo"], "revision": m["revision"],
                                        "files": {f: {"bytes": size, "digest": list(dig)} for f, (size, dig) in m["files"].items()},
                                        "total_bytes": sum(size for size, _ in m["files"].values())}
    man = svc.manifest()
    out["extraction_service"] = {"deployment_id": man["deployment_id"], "code_files": len(man["code_sha256"]), "model": man.get("model")}
    return out


def _gitblob(path: str) -> str:
    with open(path, "rb") as fh:
        data = fh.read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def availability(inv: dict, qwen_dirs: list[str], whisper_dir: str | None) -> dict:
    out = {}
    for name, m in inv["extraction_models"].items():
        rows = {}
        for f, d in m["pinned_files"].items():
            found = [os.path.join(x, f) for x in qwen_dirs if os.path.isfile(os.path.join(x, f))]
            rows[f] = "MISSING" if not found else "PRESENT_OK" if any(_sha(p) == d["sha256"] for p in found) else "HASH_MISMATCH"
        weights = "MISSING" if not any(os.path.isfile(os.path.join(x, "model.safetensors-00001-of-00002.safetensors")) for x in qwen_dirs) else "SIZE_ONLY"
        out[name] = {"files": rows, "weights": weights, "usable": weights != "MISSING" and all(v == "PRESENT_OK" for v in rows.values()),
                     "searched_dirs": len(qwen_dirs)}
    for name, m in inv["speaking_models"].items():
        d = os.path.join(whisper_dir, m["repo"], m["revision"]) if whisper_dir else None
        rows = {}
        for f, info in m["files"].items():
            p = os.path.join(d, f) if d else None
            if not p or not os.path.isfile(p):
                rows[f] = "MISSING"
                continue
            kind, want = info["digest"]
            got = _sha(p) if kind == "sha256" else _gitblob(p)
            rows[f] = "PRESENT_OK" if got == want and os.path.getsize(p) == info["bytes"] else "HASH_MISMATCH"
        out[name] = {"files": rows, "usable": all(v == "PRESENT_OK" for v in rows.values())}
    return out


def _stages(src_doc: dict) -> dict:
    t = {}
    t0 = time.perf_counter()
    src, _ = un.read_source(json.loads(json.dumps(src_doc)))
    drf = pr.draft(src)
    t["preprocessing_s"] = time.perf_counter() - t0
    t1 = time.perf_counter()
    res = rv.resolve2({src["revision"]: drf}, [], {src["revision"]: src})
    plan = rv.plan(res)
    decs = []
    for k, iid in enumerate(plan["selected"]):
        d = pr.decision(drf, iid, "approve", k + 1)
        d["based_on"]["draft_id"], d["based_on"]["material_hash"] = drf["draft_id"], next(x["material_hash"] for x in res["items"] if x["item_id"] == iid)
        decs.append(d)
    res = rv.resolve2({src["revision"]: drf}, decs, {src["revision"]: src})
    t["review_s"] = time.perf_counter() - t1
    t2 = time.perf_counter()
    doc = un.export(res, {src["revision"]: src})
    t["export_and_recall_s"] = time.perf_counter() - t2
    t["inference_s"] = 0.0
    t["units"], t["recall"] = doc["counts"]["units"], doc["counts"]["recall"]
    return t


def measure(runs: int) -> dict:
    with open(MUSIC, encoding="utf-8") as fh:
        src = json.load(fh)
    warm = [_stages(src) for _ in range(runs + 1)][1:]
    code = ("import json,sys,time;t0=time.perf_counter();sys.path.insert(0,sys.argv[1]);import scripts.model_readiness as m;"
            "s=json.load(open(sys.argv[2]));r=m._stages(s);r['process_s']=time.perf_counter()-t0;print(json.dumps(r))")
    cold, rss = [], []
    for _ in range(min(runs, 5)):
        t0 = time.perf_counter()
        p = subprocess.Popen([sys.executable, "-B", "-c", code, HERE, MUSIC], cwd=HERE, stdout=subprocess.PIPE, text=True,
                             env={"PATH": os.environ.get("PATH", "")})
        outp = p.stdout.read()
        _, status, ru = os.wait4(p.pid, 0)
        p.stdout.close()
        p.returncode = 0
        r = json.loads(outp)
        r["wall_s"] = time.perf_counter() - t0
        cold.append(r)
        rss.append(ru.ru_maxrss / 1024)

    def med(xs, k):
        v = sorted(x[k] for x in xs)
        return round(v[len(v) // 2] * 1000, 2)
    keys = ("preprocessing_s", "review_s", "export_and_recall_s")
    return {"workflow": "music source: read+check, draft (grounding), review + batch approval, units export with recall",
            "inference": "none: the fixture workflow is rules only (no model); inference_s is 0 by construction",
            "warm": {"runs": runs, "median_ms": {k: med(warm, k) for k in keys}},
            "cold": {"runs": len(cold), "median_ms": {k: med(cold, k) for k in keys} | {"process_start_to_done": med(cold, "process_s"), "wall": med(cold, "wall_s")}},
            "peak_rss_mib": {"max": round(max(rss), 1), "runs": len(rss)}}


def environment() -> dict:
    cpu = "unknown"
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            cpu = next((ln.split(":", 1)[1].strip() for ln in fh if ln.startswith("model name")), cpu)
    except OSError:
        pass
    return {"cpu": cpu, "cores": os.cpu_count(), "python": platform.python_version(), "load_average": [round(x, 2) for x in os.getloadavg()]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qwen-dir", action="append", default=[])
    ap.add_argument("--whisper-dir", help="the directory holding <repo>/<revision>/ (for example the Speaking work sources)")
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    inv = inventory()
    rep = {"schema": "flh_model_readiness_v1", "inventory": inv, "availability": availability(inv, a.qwen_dir, a.whisper_dir),
           "measurements": measure(a.runs), "environment": environment(),
           "cpu_fallback": {"fixture_workflow": "rules only: runs on CPU with the standard library; no model is ever needed",
                            "model_free_extractor": "unit_eval.sentence_baseline (deterministic, language-agnostic), measured in fixtures/xsubject_v1/eval",
                            "rule": "a missing or failed model never falls back silently: the local rules output stays, and the model step reports its failure"}}
    text = json.dumps(rep, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(text)
    av = rep["availability"]
    print("availability: " + ", ".join(f"{k} {'usable' if v['usable'] else 'UNAVAILABLE'}" for k, v in av.items()))
    m = rep["measurements"]
    print(f"warm median ms {m['warm']['median_ms']}; cold median ms {m['cold']['median_ms']}; peak RSS {m['peak_rss_mib']['max']} MiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
