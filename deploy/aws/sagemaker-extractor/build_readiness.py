"""Build the offline AWS training-readiness package. No AWS call, no network.

  python3 -B build_readiness.py DATA_DIR OUT_DIR [VALUES.json]

DATA_DIR holds the regenerated files (readiness/README.md): sft-train.jsonl,
sft-dev.jsonl and comparison-prompts.jsonl (the inputs-only prompts of the
pinned comparison slice: frozen evaluation, `rb` probe, challenge_test).
VALUES.json holds the owner's account-specific values (registry, image digest,
role, bucket); without it the placeholders of values.example.json are used,
which are syntactically valid and point nowhere.

Writes OUT_DIR/input-manifest.json (every file a job reads, with its hash,
size, record count and S3 key), OUT_DIR/prompts/ (the two prediction shards:
`a` = frozen evaluation + challenge_test, `b` = the `rb` probe; each fits the
reviewed one-hour prediction bound), OUT_DIR/rendered/*.json (the training
smoke, the experiment, and the untuned and adapter predictions of each shard,
rendered and bound-checked by render_job.py, never submitted) and
OUT_DIR/readiness-checks.json: input digests, held-out reference isolation and
output naming, checked offline.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools" / "extraction"))
import render_job  # noqa: E402
from flh_extraction import manifest  # noqa: E402

CONFIGS = ROOT / "tools" / "extraction" / "configs"
EXAMPLE = HERE / "readiness" / "values.example.json"
NAME = re.compile(r"^flh-extractor-[a-z0-9]+(-[a-z0-9]+)*-\d{8}-\d{6}$")
REFERENCE_KEYS = {"expected", "units", "meta", "rationale", "label_status"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rows(p):
    return [json.loads(line) for line in Path(p).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_rows(path, rs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rs), encoding="utf-8")
    return path


def shards(prompts, out):
    """a = frozen evaluation + challenge_test (whole groups), b = the rb probe."""
    rs = rows(prompts)
    a = [r for r in rs if not r["id"].endswith("#rb")]
    b = [r for r in rs if r["id"].endswith("#rb")]
    return (write_rows(out / "prompts" / "a" / "eval-prompts.jsonl", a),
            write_rows(out / "prompts" / "b" / "eval-prompts.jsonl", b))


def checks(m, jobs, prompts, shard_files):
    """Offline mechanical checks over the rendered jobs (no AWS)."""
    files, out = m["files"], {}
    digest = []
    for name, job in jobs.items():
        hp = job["HyperParameters"]
        uris = {c["ChannelName"]: c["DataSource"]["S3DataSource"]["S3Uri"] for c in job["InputDataConfig"]}
        expect = {"train": ("train_sha256", ["sft-train.jsonl"]), "dev": ("dev_sha256", ["sft-dev.jsonl"]),
                  "prompts": ("prompts_sha256", [k for k in files if k.startswith("predict-")])}
        for ch, (key, cands) in expect.items():
            if ch not in uris:
                continue
            f = next((files[k] for k in cands if files[k]["sha256"] == hp.get(key)), None)
            if f is None:
                digest.append(f"{name}: {key} is not the hash of a manifest file for channel {ch}")
            elif f"/{f['s3_key'].rsplit('/', 1)[0]}/" not in uris[ch].rstrip("/") + "/":
                digest.append(f"{name}: channel {ch} does not point at its file's hashed key")
    ids_all = [r["id"] for r in rows(prompts)]
    ids_sh = [r["id"] for f in shard_files for r in rows(f)]
    if sorted(ids_all) != sorted(ids_sh) or len(set(ids_sh)) != len(ids_sh):
        digest.append("the shards do not partition the comparison prompts")
    out["input_digests"] = {"pass": not digest, "problems": digest, "comparison_prompts_sha256": sha(prompts),
                            "shards": {Path(f).parent.name: {"sha256": sha(f), "records": len(rows(f))} for f in shard_files}}
    iso = []
    for name, job in jobs.items():
        for c in job["InputDataConfig"]:
            u = c["DataSource"]["S3DataSource"]["S3Uri"]
            if c["ChannelName"] in ("eval", "refs", "references") or re.search(r"reference|eval_candidates|comparison-slice", u):
                iso.append(f"{name}: channel {c['ChannelName']} may carry references")
    for f in [prompts] + list(shard_files):
        for r in rows(f):
            if set(r) != {"id", "messages"} or [x["role"] for x in r["messages"]] != ["system", "user"]:
                iso.append(f"{Path(f).name}: {r['id']} is not an inputs-only prompt")
                break
            if REFERENCE_KEYS & set(json.loads(r["messages"][1]["content"]) if r["messages"][1]["content"].startswith("{") else {}):
                iso.append(f"{Path(f).name}: {r['id']} user payload carries reference fields")
                break
    if any("expected" in k or "reference" in k for k in files):
        iso.append("a reference file is in the upload manifest")
    out["reference_isolation"] = {"pass": not iso, "problems": iso,
                                  "uploaded": sorted(files), "never_uploaded": m["never_uploaded"]}
    names = [j["TrainingJobName"] for j in jobs.values()]
    outs = [j["OutputDataConfig"]["S3OutputPath"].rstrip("/") + "/" + j["TrainingJobName"] for j in jobs.values()]
    naming = [f"bad name {n}" for n in names if not NAME.match(n) or len(n) > 63]
    if len(set(names)) != len(names):
        naming.append("two jobs share a name")
    if len(set(outs)) != len(outs):
        naming.append("two jobs share an output prefix")
    out["output_naming"] = {"pass": not naming, "problems": naming, "jobs": dict(sorted((k, j["TrainingJobName"]) for k, j in jobs.items())),
                            "output_prefixes": sorted(outs)}
    out["pass"] = all(v["pass"] for v in out.values() if isinstance(v, dict))
    return out


def build(data, out, values=None):
    data, out = Path(data), Path(out)
    values = dict(values or json.loads(EXAMPLE.read_text()))
    values.pop("$comment", None)
    prompts = data / "comparison-prompts.jsonl"
    sa, sb = shards(prompts, out)
    train, dev = data / "sft-train.jsonl", data / "sft-dev.jsonl"
    t_sha, d_sha = sha(train), sha(dev)
    files = {"sft-train.jsonl": train, "sft-dev.jsonl": dev, "predict-a/eval-prompts.jsonl": sa, "predict-b/eval-prompts.jsonl": sb}
    m = manifest.build({k: str(v) for k, v in files.items()},
                       [CONFIGS / "sft-qwen3.5-4b-lora.json", CONFIGS / "sft-qwen3.5-4b-lora-smoke.json"])
    keys = {"sft-train.jsonl": f"extractor/datasets/{t_sha}/train/sft-train.jsonl",
            "sft-dev.jsonl": f"extractor/datasets/{t_sha}/dev/sft-dev.jsonl",
            "predict-a/eval-prompts.jsonl": f"extractor/prompts/{sha(sa)}/eval-prompts.jsonl",
            "predict-b/eval-prompts.jsonl": f"extractor/prompts/{sha(sb)}/eval-prompts.jsonl"}
    for k, v in m["files"].items():
        v["s3_key"] = keys[k]
    m["comparison_prompts"] = {"sha256": sha(prompts), "records": len(rows(prompts)),
                               "shards": "a = frozen evaluation + challenge_test, b = rb probe (see readiness-checks.json)"}
    m["base_model"] = {"hf_id": "Qwen/Qwen3.5-4B", "revision": "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
                       "s3_prefix": f"extractor/models/{values['BASE_MODEL_KEY']}/", "weights_bytes": 9319737856}
    m["never_uploaded"] = ["eval_candidates.jsonl (references)", "probe references", "challenge references",
                           "comparison-slice.jsonl", "boundary cases", "learner data"]
    (out / "input-manifest.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    plans = [("sft-smoke", "sft-smoke", "smoke", "sft-qwen3.5-4b-lora-smoke.json", None),
             ("sft-experiment", "sft-experiment", "experiment", "sft-qwen3.5-4b-lora.json", None),
             ("predict-base-a", "predict-base", "predict", None, sa), ("predict-base-b", "predict-base", "predict", None, sb),
             ("predict-eval-a", "predict-eval", "predict", None, sa), ("predict-eval-b", "predict-eval", "predict", None, sb)]
    rendered, jobs = {}, {}
    for name, tmpl, run, cfg, pfile in plans:
        v = dict(values, TRAIN_SHA256=t_sha, DEV_SHA256=d_sha)
        v["CONFIG_JSON"] = json.dumps({k: x for k, x in json.loads((CONFIGS / (cfg or "sft-qwen3.5-4b-lora.json")).read_text()).items()
                                       if k != "$comment"}, separators=(",", ":"))
        if pfile:
            v["PROMPTS_SHA256"] = sha(pfile)
        path = render_job.render(HERE / "jobs" / f"{tmpl}.json.tmpl", run, out / "rendered", v, role=name)
        final = out / "rendered" / f"{name}.json"
        path.replace(final)
        rendered[name] = final.name
        jobs[name] = json.loads(final.read_text())
    chk = checks(m, jobs, prompts, (sa, sb))
    (out / "readiness-checks.json").write_text(json.dumps(chk, indent=2, sort_keys=True) + "\n")
    if not chk["pass"]:
        raise SystemExit("readiness checks failed: " + json.dumps({k: v["problems"] for k, v in chk.items() if isinstance(v, dict)}))
    return m, rendered


if __name__ == "__main__":
    vals = json.loads(Path(sys.argv[3]).read_text()) if len(sys.argv) > 3 else None
    m, r = build(sys.argv[1], sys.argv[2], vals)
    print(json.dumps({"manifest_sha256": m["manifest_sha256"], "rendered": r,
                      "files": {k: v["sha256"] for k, v in m["files"].items()}}, indent=1))
