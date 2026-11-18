"""SageMaker training entry point (container argument ``train``).

Channels (File mode, read-only):
  /opt/ml/input/data/data    the prepared dataset (dataset_manifest.json, manifest.jsonl, audio/)
  /opt/ml/input/data/model   the pinned base model files
Hyperparameters (/opt/ml/input/config/hyperparameters.json):
  config_json     the training config (flh_speaking_train_config_v1), as a JSON string
  data_sha256     expected manifest_jsonl_sha256 of the dataset (refuses another)
  base_model      pinned model name (whisper-tiny / whisper-base / whisper-small)
Outputs:
  /opt/ml/checkpoints        checkpoints + LATEST (SageMaker syncs it to S3, so a
                             Spot interruption or a retry resumes from the last one)
  /opt/ml/model              the final checkpoint's model files and run_manifest.json
  /opt/ml/output/failure     a one-line reason when the job fails

No network is needed (the job runs with network isolation); nothing is downloaded.
"""

from __future__ import annotations

import json
import os
import shutil
import sys

from . import fetch, pins, train

ML = os.environ.get("SM_ROOT", "/opt/ml")


def _fail(msg: str) -> int:
    os.makedirs(os.path.join(ML, "output"), exist_ok=True)
    with open(os.path.join(ML, "output", "failure"), "w", encoding="utf-8") as fh:
        fh.write(msg[:1000] + "\n")
    print(msg, file=sys.stderr, flush=True)
    return 1


def main() -> int:
    try:
        with open(os.path.join(ML, "input", "config", "hyperparameters.json"), encoding="utf-8") as fh:
            hp = json.load(fh)
        cfg = json.loads(hp["config_json"])
        base_name = hp["base_model"]
        data = os.path.join(ML, "input", "data", "data")
        base = os.path.join(ML, "input", "data", "model")
        with open(os.path.join(data, "dataset_manifest.json"), encoding="utf-8") as fh:
            if json.load(fh)["manifest_jsonl_sha256"] != hp["data_sha256"]:
                return _fail("dataset manifest does not match data_sha256")
        src = pins.MODELS[base_name]
        bad = [f for f, (size, dg) in src["files"].items() if fetch.verify(os.path.join(base, f), size, dg)]
        if bad:
            return _fail(f"base model files differ from the {base_name} pin: {bad}")
        if cfg.get("base_model") != base_name:
            return _fail("config base_model differs from the base_model hyperparameter")
        work = os.path.join(ML, "checkpoints")
        os.makedirs(work, exist_ok=True)
        cfg_path = os.path.join(work, "train_config.json")
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=1, sort_keys=True)
        res = train.train(cfg_path, data, base, work)
        if res["status"] != "completed":
            return _fail(f"training stopped at step {res['step']} ({res['status']}); rerun to resume")
        model_out = os.path.join(ML, "model")
        os.makedirs(model_out, exist_ok=True)
        for f in os.listdir(res["checkpoint"]):
            if f != "trainer_state.pt":
                shutil.copyfile(os.path.join(res["checkpoint"], f), os.path.join(model_out, f))
        print(json.dumps(res), flush=True)
        return 0
    except Exception as exc:  # message without data content
        return _fail(f"training failed: {type(exc).__name__}: {str(exc)[:300]}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "train":
        sys.exit(_fail("usage: sagemaker_entry train"))
    sys.exit(main())
