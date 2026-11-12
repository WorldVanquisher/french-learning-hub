"""SageMaker training entry point (`docker run IMAGE train`), A6 layout.

  /opt/ml/input/config/hyperparameters.json   string values:
      config_json      the training config (JSON object as a string)
      train_sha256     sha256 of train/sft-train.jsonl (required)
      dev_sha256       sha256 of dev/sft-dev.jsonl (optional)
  /opt/ml/input/data/train/sft-train.jsonl    channel "train"
  /opt/ml/input/data/dev/sft-dev.jsonl        channel "dev" (optional)
  /opt/ml/input/data/model/                   channel "model": pinned base weights (network isolation)
  /opt/ml/model/                              artefacts (uploaded as model.tar.gz)
  /opt/ml/output/failure                      a short, secret-free reason on failure

No evaluation channel exists: evaluation inputs are scored in a separate
prediction step, and their references never enter a training job.
FLH_SM_ROOT overrides /opt/ml for local tests.

Before training or prediction the installed stack is compared with
requirements-train.txt (packaging.py) and written to /opt/ml/model/stack-check.json;
a mismatch (a stale image) fails the job unless FLH_ALLOW_STACK_MISMATCH=1,
which only tiny offline fixtures set.
"""

import hashlib
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

from . import train


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stack_gate(root):
    """Record the installed stack beside the outputs; refuse a mismatch unless allowed."""
    from . import packaging
    rep = packaging.check()
    (root / "model").mkdir(parents=True, exist_ok=True)
    (root / "model" / "stack-check.json").write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n")
    if not rep["stack_matches_requirements"]:
        if not packaging.allowed_mismatch():
            raise RuntimeError(f"{rep['verdict']} (set {packaging.ALLOW_ENV}=1 only for a tiny offline fixture)")
        print(json.dumps({"event": "stack_mismatch_allowed", "verdict": rep["verdict"]}))
    return rep


def main(argv):
    if len(argv) < 2 or argv[1] not in ("train", "predict"):
        print("usage: <image> train|predict", file=sys.stderr)
        return 2
    root = Path(os.environ.get("FLH_SM_ROOT", "/opt/ml"))
    failure = root / "output" / "failure"
    if argv[1] == "predict":
        return predict(root, failure)
    try:
        hp_path = root / "input" / "config" / "hyperparameters.json"
        hp = json.loads(hp_path.read_text()) if hp_path.is_file() else {}
        data = root / "input" / "data"
        if (data / "eval").exists():
            raise ValueError("an eval channel is refused: evaluation data never enters a training job")
        tr, dv = data / "train" / "sft-train.jsonl", data / "dev" / "sft-dev.jsonl"
        if not hp.get("train_sha256") or sha(tr) != hp["train_sha256"]:
            raise ValueError("train_sha256 is missing or does not match the train channel")
        if dv.is_file() and hp.get("dev_sha256") and sha(dv) != hp["dev_sha256"]:
            raise ValueError("dev_sha256 does not match the dev channel")
        stack_gate(root)
        cfg_obj = json.loads(hp.get("config_json") or "{}")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg_obj, f)
        cfg = train.load_config(f.name)
        m = train.run(cfg, tr, dv if dv.is_file() else None, root / "model")
        print(json.dumps({"event": "finished", "steps": m["steps"], "train_examples": m["train_examples"],
                          "train_sha256": m["train_sha256"], "suitable_for_production": False}))
        return 0
    except Exception as e:  # noqa: BLE001 - every failure leaves a reason file
        failure.parent.mkdir(parents=True, exist_ok=True)
        failure.write_text(f"{e.__class__.__name__}: {e}"[:1000] + "\n")
        traceback.print_exc()
        return 1


def predict(root, failure):
    """Prediction job: channel "prompts" (inputs-only eval-prompts.jsonl),
    channel "model" (base weights) and optional channel "adapter" (a trained
    LoRA adapter). Writes /opt/ml/model/predictions.jsonl. No references."""
    from . import predict as pred
    try:
        hp_path = root / "input" / "config" / "hyperparameters.json"
        hp = json.loads(hp_path.read_text()) if hp_path.is_file() else {}
        data = root / "input" / "data"
        prompts = data / "prompts" / "eval-prompts.jsonl"
        if not hp.get("prompts_sha256") or sha(prompts) != hp["prompts_sha256"]:
            raise ValueError("prompts_sha256 is missing or does not match the prompts channel")
        stack_gate(root)
        args = ["--model", str(data / "model"), "--prompts", str(prompts), "--out", str(root / "model" / "predictions.jsonl"),
                "--max-new-tokens", hp.get("max_new_tokens", "512"), "--template-kwargs", hp.get("template_kwargs", "{}"),
                "--profile", hp.get("model_profile", "auto"), "--dtype", hp.get("dtype", "default")]
        if (data / "adapter").is_dir():
            args += ["--adapter", str(data / "adapter")]
        (root / "model").mkdir(parents=True, exist_ok=True)
        return pred.main(args)
    except Exception as e:  # noqa: BLE001
        failure.parent.mkdir(parents=True, exist_ok=True)
        failure.write_text(f"{e.__class__.__name__}: {e}"[:1000] + "\n")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
