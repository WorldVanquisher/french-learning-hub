"""R4 Speaking pilot: bounded job render against the pre-registration, and the teardown-order check.

No AWS call, no credentials. The owner runs every AWS command (deploy/aws/model-runtime/SPEAKING-PILOT-R4.md).

  python3 -I -B pilot_r4.py render VALUES.json OUT_DIR [--now 2026-11-20T00:00:00Z]
  python3 -I -B pilot_r4.py teardown-check PLAN.json

``render`` first refuses values that disagree with ``r4-pilot.prereg.json``. Those are the
dataset hash, the base revision, the config file's SHA-256 and the run name. It then renders
through ``render.py``, which keeps its own bounds: 1 x ml.g5.xlarge, at most 3600 s of run time
and 7200 s of Spot wait, network isolation, two pinned channels and the required tags.

The R4 checks on the rendered request:
- no credential-like string in it;
- Spot wait at least the run time;
- checkpoints under the job's own prefix, output under ``speaking/output/``;
- at most one retry;
- ``DeleteAfter`` within 31 days of the render date.

``teardown-check`` checks the order of a teardown plan. Its rules:
- the job reaches a terminal state before anything is copied or deleted;
- evidence is copied before job artifacts or the model are deleted;
- endpoint, then endpoint config, then model;
- the ECR image last;
- every deletion names a ``speaking/`` prefix or a named resource, never retained evidence;
- the plan ends with a verification listing.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import render  # noqa: E402

PREREG = HERE / "r4-pilot.prereg.json"
SECRET = re.compile(r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|aws_secret_access_key|-----BEGIN [A-Z ]*PRIVATE KEY|SessionToken|password", re.I)
ORDER = ("stop_training_job", "wait_job_terminal", "copy_evidence", "delete_endpoint", "delete_endpoint_config", "delete_model",
         "delete_s3_prefix", "delete_ecr_image", "verify_empty")


def _prereg() -> dict:
    return json.loads(PREREG.read_text(encoding="utf-8"))


def render_r4(values: dict, out_dir: str, now: datetime | None = None) -> Path:
    pre = _prereg()
    cfg_path = HERE.parent / pre["candidate"]["config"]
    problems = []
    if hashlib.sha256(cfg_path.read_bytes()).hexdigest() != pre["candidate"]["config_sha256"]:
        problems.append("the config file changed since the pre-registration")
    if values.get("DATA_SHA256") != pre["candidate"]["data_manifest_sha256"]:
        problems.append("DATA_SHA256 is not the pre-registered dataset")
    if values.get("BASE_REVISION") != pre["baseline"]["revision"]:
        problems.append("BASE_REVISION is not the pre-registered base")
    if values.get("RUN") != "r4pilot":
        problems.append("RUN must be r4pilot")
    when = now or datetime.now(timezone.utc)
    try:
        if (date.fromisoformat(str(values.get("DELETE_AFTER"))) - when.date()).days > 31:
            problems.append("DELETE_AFTER more than 31 days after the render")
    except ValueError:
        problems.append("DELETE_AFTER must be YYYY-MM-DD")
    if problems:
        raise SystemExit("pilot_r4: " + "; ".join(problems))
    out = render.render(values, json.loads(cfg_path.read_text(encoding="utf-8")), out_dir, now=when)
    text = out.read_text(encoding="utf-8")
    job = json.loads(text)
    sc = job["StoppingCondition"]
    if SECRET.search(text):
        problems.append("the rendered request contains a credential-like string")
    if sc.get("MaxWaitTimeInSeconds", 0) < sc["MaxRuntimeInSeconds"]:
        problems.append("Spot wait shorter than the run time")
    if job["TrainingJobName"] not in job["CheckpointConfig"]["S3Uri"] or not job["CheckpointConfig"]["S3Uri"].endswith("/"):
        problems.append("checkpoints must sit under the job's own prefix")
    if not re.fullmatch(r"s3://[a-z0-9.-]+/speaking/output/", job["OutputDataConfig"]["S3OutputPath"]):
        problems.append("output must be s3://BUCKET/speaking/output/")
    if job.get("RetryStrategy", {}).get("MaximumAttemptsAfterFailure", job.get("RetryStrategy", {}).get("MaximumRetryAttempts", 0)) > 1:
        problems.append("at most one retry")
    tags = {t["Key"]: t["Value"] for t in job["Tags"]}
    if (date.fromisoformat(tags["DeleteAfter"]) - when.date()).days > 31:
        problems.append("DeleteAfter more than 31 days after the render")
    if problems:
        out.unlink()
        raise SystemExit("pilot_r4: rendered job refused: " + "; ".join(problems))
    return out


def teardown_check(plan: dict) -> list[str]:
    steps = plan.get("steps", [])
    acts = [s.get("action") for s in steps]
    out = [f"step {i + 1}: unknown action {a!r}" for i, a in enumerate(acts) if a not in ORDER]

    def first(a):
        return acts.index(a) if a in acts else None
    deletes = [i for i, a in enumerate(acts) if a and a.startswith("delete_")]
    w, c = first("wait_job_terminal"), first("copy_evidence")
    if w is None:
        out.append("no wait_job_terminal: the job may still write to its prefixes")
    elif any(i < w for i in deletes) or (c is not None and c < w):
        out.append("something is copied or deleted before the job is terminal")
    s = first("stop_training_job")
    if s is not None and w is not None and s > w:
        out.append("stop_training_job must come before wait_job_terminal")
    if c is None:
        out.append("no copy_evidence step: job evidence would be lost")
    else:
        for i in deletes:
            t = str(steps[i].get("target", ""))
            if acts[i] == "delete_model" or "/output/" in t or "/checkpoints/" in t:
                if i < c:
                    out.append(f"step {i + 1}: {acts[i]} {t} before the evidence is copied")
    e, ec, m = first("delete_endpoint"), first("delete_endpoint_config"), first("delete_model")
    if e is not None and ec is not None and not e < ec:
        out.append("delete the endpoint before its config")
    if ec is not None and m is not None and not ec < m:
        out.append("delete the endpoint config before the model")
    img = first("delete_ecr_image")
    if img is not None and any(i > img for i in deletes):
        out.append("the ECR image must be deleted last")
    for i in deletes:
        t = str(steps[i].get("target", ""))
        if acts[i] == "delete_s3_prefix" and not re.fullmatch(r"s3://[A-Za-z0-9.${}_-]+/speaking/[A-Za-z0-9.${}_/-]+/", t):
            out.append(f"step {i + 1}: an S3 deletion must name one speaking/… prefix ending in /, not {t!r}")
        if "evidence" in t.lower():
            out.append(f"step {i + 1}: retained evidence is never deleted")
    if not acts or acts[-1] != "verify_empty":
        out.append("the plan must end with verify_empty")
    return out


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if a[:1] == ["render"] and len(a) >= 3:
        now = None
        if "--now" in a:
            now = datetime.fromisoformat(a[a.index("--now") + 1].replace("Z", "+00:00"))
        print(render_r4(json.loads(Path(a[1]).read_text(encoding="utf-8")), a[2], now))
        return 0
    if a[:1] == ["teardown-check"] and len(a) == 2:
        issues = teardown_check(json.loads(Path(a[1]).read_text(encoding="utf-8")))
        print("teardown plan: " + ("ok" if not issues else "REFUSED\n  " + "\n  ".join(issues)))
        return 0 if not issues else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
