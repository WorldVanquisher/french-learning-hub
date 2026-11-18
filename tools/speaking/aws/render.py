"""Render a Speaking training job locally and refuse anything outside the
reviewed bounds. No AWS call. Prints the rendered file's path.

  python3 render.py VALUES.json CONFIG.json OUT_DIR

VALUES may name the run (``RUN``, default ``pilot``; for example ``punct`` for
the punctuated-target experiment): it names the job and its ``Run`` tag.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")
MAX_RUNTIME, MAX_WAIT = 3600, 7200
INSTANCES = {"ml.g5.xlarge"}
CHANNELS = {"data", "model"}
REQUIRED_TAGS = {"Project", "Component", "Run", "DatasetSha256", "ImageDigest", "Owner", "DeleteAfter"}


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


def render(values: dict, config: dict, out_dir: str, now=None) -> Path:
    v = dict(values)
    if config.get("schema") != "flh_speaking_train_config_v1" or config.get("base_model") != v.get("BASE_MODEL"):
        raise SystemExit("render: config schema or base_model does not match")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", v.get("IMAGE_DIGEST", "")):
        raise SystemExit("render: IMAGE_DIGEST must be sha256:<64 hex> (images are referenced by digest only)")
    if not re.fullmatch(r"[0-9a-f]{64}", v.get("DATA_SHA256", "")) or not re.fullmatch(r"[0-9a-f]{40}", v.get("BASE_REVISION", "")):
        raise SystemExit("render: DATA_SHA256 and BASE_REVISION must be full hashes")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v.get("DELETE_AFTER", "")):
        raise SystemExit("render: DELETE_AFTER must be YYYY-MM-DD")
    v.setdefault("RUN", "pilot")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,15}", v["RUN"]):
        raise SystemExit("render: RUN must be 1-16 characters: a-z, 0-9 and -")
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    v["JOB_NAME"] = f"flh-speaking-{v['RUN']}-{stamp}"
    v["IMAGE_URI_BY_DIGEST"] = f"{v['REGISTRY']}/flh-speaking@{v['IMAGE_DIGEST']}"
    v["CONFIG_JSON"] = json.dumps(config, sort_keys=True, separators=(",", ":"))
    job = fill(json.loads((HERE / "train-pilot.json.tmpl").read_text()), v)
    rc, sc = job["ResourceConfig"], job["StoppingCondition"]
    problems = []
    if rc["InstanceCount"] != 1 or rc["InstanceType"] not in INSTANCES:
        problems.append("instance must be 1 x ml.g5.xlarge")
    if sc["MaxRuntimeInSeconds"] > MAX_RUNTIME or sc.get("MaxWaitTimeInSeconds", 0) > MAX_WAIT:
        problems.append("runtime above the reviewed bound")
    if not job["EnableNetworkIsolation"]:
        problems.append("network isolation must be on")
    if {c["ChannelName"] for c in job["InputDataConfig"]} != CHANNELS:
        problems.append("channels must be exactly data and model")
    if {t["Key"] for t in job["Tags"]} != REQUIRED_TAGS:
        problems.append("tags incomplete")
    if len(job["HyperParameters"]["config_json"]) > 2500:
        problems.append("config_json too long for a hyperparameter")
    if len(job["TrainingJobName"]) > 63:
        problems.append("job name longer than 63 characters")
    if problems:
        raise SystemExit("render: job outside the reviewed bounds: " + "; ".join(problems))
    out = Path(out_dir) / f"{job['TrainingJobName']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(job, indent=2) + "\n")
    return out


if __name__ == "__main__":
    values, config, out_dir = sys.argv[1:4]
    print(render(json.loads(Path(values).read_text()), json.loads(Path(config).read_text()), out_dir))
