"""Model candidates for the Speaking Lab (standard library only).

A candidate manifest (``flh_speaking_lab_candidate_v1``) names everything that
identifies a run, without loading any model:
- the pinned model files (``pins.py``: size and digest per file, repository, revision);
- the CPU lock (``requirements-cpu.lock`` SHA-256);
- the device and precision.

Its ``candidate_id`` is a hash of exactly that, so any change to a pin, the
lock or the runtime gives another ID. A result file records the ID in its
header, and ``lab batch --manifest-a/--manifest-b`` invalidates a result whose
ID no longer matches.

Nothing here changes the serving default. ``RUNBOOK.md`` decides what is
served: pretrained whisper-small through ``SPEAKING_TRANSCRIPTION_PROVIDER=local``.
"""

from __future__ import annotations

import hashlib
import json
import os

from . import fetch, pins, textnorm

SCHEMA = "flh_speaking_lab_candidate_v1"
PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK = os.path.join(PKG, "requirements-cpu.lock")
DRY_RUN_ID = "dry-run-echo-v1"


def manifest(name: str, device: str = "cpu", dtype: str = "float32", role: str = "candidate") -> dict:
    if name not in pins.MODELS:
        raise ValueError(f"unknown model {name!r} (pinned: {sorted(pins.MODELS)})")
    src = pins.MODELS[name]
    defining = {
        "model": {"name": name, "repo": src["repo"], "revision": src["revision"],
                  "files": {f: [size, kind, dg] for f, (size, (kind, dg)) in sorted(src["files"].items())}},
        "lock": {"file": "requirements-cpu.lock", "sha256": fetch.file_digest(LOCK, "sha256")},
        "runtime": {"device": device, "dtype": dtype},
        "normalization": {"id": textnorm.NORM_VERSION, "fingerprint": textnorm.policy_fingerprint()},
    }
    cid = hashlib.sha256(json.dumps(defining, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"schema": SCHEMA, "role": role, "candidate_id": f"{name}@{src['revision'][:12]}/{device}-{dtype}/{cid[:16]}", "defining": defining}


def check_files(man: dict, model_dir: str) -> list[str]:
    """Absent or mismatched local files, checked before any loading (empty: usable)."""
    if not os.path.isdir(model_dir):
        return [f"model directory {model_dir!r} does not exist"]
    return [f"{f}: {bad}" for f, (size, kind, dg) in man["defining"]["model"]["files"].items()
            if (bad := fetch.verify(os.path.join(model_dir, f), size, (kind, dg)))]


def dry_run(refs: dict, label: str = "D") -> list[dict]:
    """A candidate that needs no weights: it echoes each reference, dropping the
    last word of every third sample, so the pipeline sees both hits and errors.
    Deterministic; for wiring checks only, never a model result."""
    rows = [{"header": {"label": label, "model_id": DRY_RUN_ID, "config_id": "dry-run", "candidate_id": DRY_RUN_ID,
                        "device": "none", "dtype": "none", "provenance": "dry run: no model, no weights"}}]
    for k, i in enumerate(sorted(refs)):
        words = refs[i]["reference"].split()
        rows.append({"id": i, "text": " ".join(words[:-1]) if k % 3 == 2 and len(words) > 1 else refs[i]["reference"], "status": "transcribed"})
    return rows


def from_eval(doc: dict, label: str, which: str = "served", group: str = "item") -> tuple[list[dict], list[dict]]:
    """Convert a stored v1/v2 evaluation (``evaluate`` output, compact or full)
    into lab references and one result file. The model identity is the
    evaluation's own (model directory = pinned revision, decoding policy).
    ``group="speaker"`` makes each speaker one independent group (clips of one
    speaker are correlated); ``"item"`` keeps one group per clip. The corpus's
    self-reported ``gender`` becomes a slice tag when present."""
    if group not in ("item", "speaker"):
        raise ValueError("group is 'item' or 'speaker'")
    head = {"label": label, "model_id": f"{doc.get('model_dir_name', 'unknown')}/{doc.get('decoding', 'unknown')}",
            "config_id": f"{doc.get('decoding', 'unknown')}/{doc.get('normalization', 'unknown')}",
            "provenance": f"stored evaluation '{doc['summary'].get('label', '')}', split {doc['summary'].get('split', '')}",
            "device": "cpu", "dtype": "float32"}
    timing = doc["summary"].get("timing") or {}
    if timing:
        head["resources"] = {k: timing[k] for k in ("real_time_factor", "peak_rss_mb", "threads", "batch") if k in timing}
    refs = [{"id": i["id"], "reference": i["ref"], "speaker": i.get("cluster"),
             "group_id": (i.get("cluster") or i["id"]) if group == "speaker" else i["id"],
             **({"tags": {"gender": i["gender"]}} if i.get("gender") else {})} for i in doc["items"]]
    rows = [{"header": head}] + [{"id": i["id"], "text": i[which]["text"], "status": i[which].get("status", "transcribed")} for i in doc["items"]]
    return refs, rows


def write_jsonl(rows: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))
