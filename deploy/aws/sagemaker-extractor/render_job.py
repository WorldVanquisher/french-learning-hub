"""Render a job template locally and refuse anything outside the reviewed
bounds. No AWS call. Prints the path of the rendered job file.

  python3 render_job.py TEMPLATE RUN OUT_DIR VALUES.json
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")
BOUNDS = {"smoke": 1800, "experiment": 10800, "predict": 3600}
CHANNELS = {"train": {"train", "dev", "model"}, "predict": {"prompts", "model", "adapter"}}


def fill(obj, values):
    if isinstance(obj, dict):
        return {k: fill(v, values) for k, v in obj.items()}
    if isinstance(obj, list):
        return [fill(v, values) for v in obj]
    if isinstance(obj, str):
        missing = [m for m in PLACEHOLDER.findall(obj) if values.get(m) in (None, "")]
        if missing:
            raise SystemExit(f"render: missing value for {missing}")
        return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), obj)
    return obj


def render(template, run, out_dir, values, role=None):
    """role names the job (default: the run type); two jobs rendered in the
    same second need different roles to get different names."""
    if run not in BOUNDS:
        raise SystemExit(f"render: run must be one of {sorted(BOUNDS)}")
    role = role or run
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", role):
        raise SystemExit("render: role must be lower-case words joined by '-'")
    values = dict(values)
    values["JOB_NAME"] = f"flh-extractor-{role}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    if len(values["JOB_NAME"]) > 63:
        raise SystemExit("render: job name longer than 63 characters")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", values.get("IMAGE_DIGEST", "")):
        raise SystemExit("render: IMAGE_DIGEST must be sha256:<64 hex> (images are referenced by digest only)")
    values["IMAGE_URI_BY_DIGEST"] = f"{values['REGISTRY']}/flh-extractor-sft@{values['IMAGE_DIGEST']}"
    job = fill(json.loads(Path(template).read_text()), values)
    rc, sc = job["ResourceConfig"], job["StoppingCondition"]
    mode = job["AlgorithmSpecification"]["ContainerArguments"][0]
    names = {c["ChannelName"] for c in job["InputDataConfig"]}
    problems = []
    if rc["InstanceCount"] != 1 or rc["InstanceType"] != "ml.g5.xlarge":
        problems.append("instance must be 1 x ml.g5.xlarge")
    if sc["MaxRuntimeInSeconds"] > BOUNDS[run]:
        problems.append(f"MaxRuntimeInSeconds above {BOUNDS[run]}")
    if not job["EnableNetworkIsolation"]:
        problems.append("network isolation must be on")
    if not names <= CHANNELS[mode] or "eval" in names:
        problems.append(f"channels {sorted(names)} not allowed for {mode}")
    if mode == "train" and json.loads(job["HyperParameters"]["config_json"]).get("smoke") is True and run != "smoke":
        problems.append("a smoke config must not be used for the experiment")
    if problems:
        raise SystemExit("render: job outside the reviewed bounds: " + "; ".join(problems))
    out = Path(out_dir) / f"{job['TrainingJobName']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(job, indent=2) + "\n")
    return out


if __name__ == "__main__":
    t, run, out_dir, values = sys.argv[1:5]
    print(render(t, run, out_dir, json.loads(Path(values).read_text())))
