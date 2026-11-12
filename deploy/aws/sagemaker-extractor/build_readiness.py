"""Build the offline AWS training-readiness package. No AWS call, no network.

  python3 -B build_readiness.py DATA_DIR OUT_DIR [VALUES.json]

DATA_DIR holds the regenerated files (TRAINING_RUNBOOK.md §2 and the
increment commands): sft-train.jsonl, sft-dev.jsonl, eval-prompts-inputs-only.jsonl,
probe-rb-prompts.jsonl, sub50-prompts.jsonl, sub50-probe-prompts.jsonl.
VALUES.json holds the owner's account-specific values (registry, image digest,
role, bucket); without it the placeholders of values.example.json are used,
which are syntactically valid and point nowhere.

Writes OUT_DIR/input-manifest.json (every file a job reads, with its hash,
size, record count and S3 key), OUT_DIR/prompts/ (the two prediction prompt
files a job reads), and OUT_DIR/rendered/*.json: the smoke, experiment,
base-model prediction and adapter prediction jobs rendered and bound-checked
by render_job.py, never submitted.
"""

import hashlib
import json
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


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def concat(paths, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"".join(Path(p).read_bytes() for p in paths))
    return out


def build(data, out, values=None):
    data, out = Path(data), Path(out)
    values = dict(values or json.loads(EXAMPLE.read_text()))
    values.pop("$comment", None)
    smoke_prompts = concat([data / "sub50-prompts.jsonl", data / "sub50-probe-prompts.jsonl"], out / "prompts" / "smoke" / "eval-prompts.jsonl")
    full_prompts = concat([data / "eval-prompts-inputs-only.jsonl", data / "probe-rb-prompts.jsonl"], out / "prompts" / "full" / "eval-prompts.jsonl")
    train, dev = data / "sft-train.jsonl", data / "sft-dev.jsonl"
    t_sha, d_sha = sha(train), sha(dev)
    files = {"sft-train.jsonl": train, "sft-dev.jsonl": dev, "predict-smoke/eval-prompts.jsonl": smoke_prompts,
             "predict-full/eval-prompts.jsonl": full_prompts}
    m = manifest.build({k: str(v) for k, v in files.items()},
                       [CONFIGS / "sft-qwen3.5-4b-lora.json", CONFIGS / "sft-qwen3.5-4b-lora-smoke.json"])
    keys = {"sft-train.jsonl": f"extractor/datasets/{t_sha}/train/sft-train.jsonl",
            "sft-dev.jsonl": f"extractor/datasets/{t_sha}/dev/sft-dev.jsonl",
            "predict-smoke/eval-prompts.jsonl": f"extractor/prompts/{sha(smoke_prompts)}/eval-prompts.jsonl",
            "predict-full/eval-prompts.jsonl": f"extractor/prompts/{sha(full_prompts)}/eval-prompts.jsonl"}
    for k, v in m["files"].items():
        v["s3_key"] = keys[k]
    m["base_model"] = {"hf_id": "Qwen/Qwen3.5-4B", "revision": "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
                       "s3_prefix": f"extractor/models/{values['BASE_MODEL_KEY']}/", "weights_bytes": 9319737856}
    m["never_uploaded"] = ["eval_candidates.jsonl (references)", "probe references", "boundary cases", "learner data"]
    (out / "input-manifest.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    rendered = {}
    plans = [("sft-smoke", "smoke", "sft-qwen3.5-4b-lora-smoke.json", None),
             ("sft-experiment", "experiment", "sft-qwen3.5-4b-lora.json", None),
             ("predict-base", "predict", None, smoke_prompts),
             ("predict-eval", "predict", None, full_prompts)]
    for tmpl, run, cfg, prompts in plans:
        v = dict(values, TRAIN_SHA256=t_sha, DEV_SHA256=d_sha)
        v["CONFIG_JSON"] = json.dumps({k: x for k, x in json.loads((CONFIGS / (cfg or "sft-qwen3.5-4b-lora.json")).read_text()).items()
                                       if k != "$comment"}, separators=(",", ":"))
        if prompts:
            v["PROMPTS_SHA256"] = sha(prompts)
        path = render_job.render(HERE / "jobs" / f"{tmpl}.json.tmpl", run, out / "rendered", v)
        final = out / "rendered" / f"{tmpl}.json"
        path.replace(final)
        rendered[tmpl] = final.name
    return m, rendered


if __name__ == "__main__":
    vals = json.loads(Path(sys.argv[3]).read_text()) if len(sys.argv) > 3 else None
    m, r = build(sys.argv[1], sys.argv[2], vals)
    print(json.dumps({"manifest_sha256": m["manifest_sha256"], "rendered": r,
                      "files": {k: v["sha256"] for k, v in m["files"].items()}}, indent=1))
