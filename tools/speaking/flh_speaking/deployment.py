"""Deployment manifest and identity of a local transcription model.

The identity covers everything that can change a transcript: the model files
(SHA-256), whether they are a pinned pretrained revision or a fine-tuned
checkpoint (with its training inputs), the decoding policy and thresholds, the
audio convention, the code of the audio/model/service modules and the runtime
library versions. ``deployment_id`` is what the operator sets as
``SPEAKING_TRANSCRIPTION_MODEL``; the service refuses any other ``model`` value.
Service limits are published but not hashed: they never change a transcript.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform

from . import audio, fetch, model, pins

SCHEMA = "flh_speaking_deployment_manifest_v1"
CODE_FILES = ("audio.py", "model.py", "service.py", "deployment.py")
LIMITS = {
    "max_request_bytes": 8 * 1024 * 1024 + 64 * 1024,
    "max_audio_bytes": 8 * 1024 * 1024,
    "max_audio_seconds": 120.0,
    "accepted_containers": list(audio.SERVICE_FAMILIES),
    "concurrent_inferences": 1,
    "read_timeout_s": 30.0,
    # Counted from the request's arrival, queue wait included, so a client whose
    # own timeout is longer (FLH: SPEAKING_TRANSCRIPTION_TIMEOUT, default 60 s)
    # always receives a definite answer (504) instead of giving up first.
    "inference_timeout_s": 50.0,
}


def _sha(path: str) -> str:
    return fetch.file_digest(path, "sha256")


def code_sha256() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha256()
    for f in CODE_FILES:
        with open(os.path.join(here, f), "rb") as fh:
            h.update(f.encode() + b"\0" + fh.read().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def identify(model_dir: str) -> dict:
    files = {f: _sha(os.path.join(model_dir, f)) for f in sorted(os.listdir(model_dir))
             if f.endswith((".json", ".txt", ".safetensors")) and f != "run_manifest.json" and not f.startswith(".")}
    if "model.safetensors" not in files:
        raise ValueError("model directory has no model.safetensors")
    for name, src in pins.MODELS.items():
        if files["model.safetensors"] == src["files"]["model.safetensors"][1][1]:
            bad = [f for f, (size, dg) in src["files"].items() if fetch.verify(os.path.join(model_dir, f), size, dg)]
            if bad:
                raise ValueError(f"files of pinned {name} differ from the pin: {bad}")
            return {"kind": "pretrained", "name": name, "repo": src["repo"], "revision": src["revision"], "files": files}
    rm = os.path.join(model_dir, "run_manifest.json")
    if os.path.exists(rm):
        with open(rm, encoding="utf-8") as fh:
            run = json.load(fh)
        base = next((n for n, s in pins.MODELS.items() if s["files"]["model.safetensors"][1][1] == run["base"]["files"].get("model.safetensors")), "unknown")
        return {"kind": "fine_tuned", "name": f"{base}-ft", "base": base, "step": run["step"], "config_sha256": run["config_sha256"],
                "data_manifest_sha256": run["data_manifest_sha256"], "files": files}
    raise ValueError("model directory is neither a pinned revision nor a flh_speaking checkpoint")


def manifest(model_dir: str) -> dict:
    import av
    import numpy
    import torch
    import transformers

    ident = identify(model_dir)
    defining = {
        "model": ident,
        "decoding": {
            "policy": model.DECODING, "language": "fr", "task": "transcribe", "timestamps": False, "search": "greedy",
            "window_s": model.WINDOW_SECONDS, "cut_search_s": model.SEARCH_SECONDS, "max_new_tokens": model.MAX_NEW_TOKENS, "loop_cut": [model.LOOP_REPEATS, model.LOOP_MAX_NGRAM],
            "min_sound_s": model.MIN_SOUND_SECONDS, "sound_dbfs": audio.SOUND_DBFS, "no_speech_prob": model.NO_SPEECH_PROB, "logprob_threshold": model.LOGPROB_THRESHOLD,
            "compression_threshold": model.COMPRESSION_THRESHOLD, "not_french": [model.NOT_FRENCH_FR_MAX, model.NOT_FRENCH_OTHER_MIN],
            "phantom_patterns": [p.pattern for p in model.PHANTOM],
        },
        "audio": audio.CONVENTION,
        "device": "cpu", "dtype": "float32",
        "code_sha256": code_sha256(),
        "runtime": {"python": platform.python_version(), "torch": torch.__version__, "transformers": transformers.__version__,
                    "numpy": numpy.__version__, "av": av.__version__},
    }
    sha = hashlib.sha256(json.dumps(defining, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    rev = ident.get("revision", "")[:12] or f"step{ident.get('step')}-{ident['files']['model.safetensors'][:12]}"
    return {
        "schema": SCHEMA, "defining": defining, "manifest_sha256": sha,
        "deployment_id": f"{ident['name']}@{rev}/{model.DECODING}/cpu-fp32/{sha[:16]}",
        "limits": LIMITS,
        "response_schema": "flh_speaking_transcription_v1",
    }
