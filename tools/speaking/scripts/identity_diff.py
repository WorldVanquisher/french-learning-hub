"""What changed between two runtime identities: model weights, decoding policy, audio convention,
code, runtime libraries, or FLH's feedback prompts (standard library only).

  python3 -I -B scripts/identity_diff.py --a MANIFEST_A.json --b MANIFEST_B.json [--prompts-a DIR --prompts-b DIR] [--json OUT]

The manifests are ``flh_speaking_deployment_manifest_v1`` (``python -m flh_speaking manifest``,
or a service's ``GET /manifest``). The prompt directories are FLH's Speaking prompt files
(``internal/speaking/prompts``): they drive feedback, never transcription, so a prompt change
leaves the transcription deployment ID unchanged and a weights change leaves the prompts'
identity unchanged. Exit 0 always; the report says which parts differ.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

PARTS = {"model_weights": ("model", "files"), "model_kind": ("model", "kind"), "decoding_policy": ("decoding",), "audio_convention": ("audio",),
         "code": ("code_sha256",), "runtime": ("runtime",), "device": ("device",)}


def _get(d, path):
    for k in path:
        d = (d or {}).get(k)
    return d


def prompts_identity(d: str | None) -> str | None:
    if not d:
        return None
    h = hashlib.sha256()
    for root, _, files in sorted(os.walk(d)):
        for f in sorted(files):
            p = os.path.join(root, f)
            with open(p, "rb") as fh:
                h.update(os.path.relpath(p, d).encode() + b"\0" + fh.read() + b"\0")
    return h.hexdigest()


def diff(a: dict, b: dict, pa: str | None = None, pb: str | None = None) -> dict:
    da, db = a.get("defining", {}), b.get("defining", {})
    changed = [k for k, path in PARTS.items() if _get(da, path) != _get(db, path)]
    ia, ib = prompts_identity(pa), prompts_identity(pb)
    if ia is not None and ib is not None and ia != ib:
        changed.append("feedback_prompts")
    kind = ("no change" if not changed else
            "model change" if set(changed) & {"model_weights", "model_kind"} and "feedback_prompts" not in changed else
            "prompt change" if changed == ["feedback_prompts"] else "mixed change")
    return {"schema": "flh_runtime_identity_diff_v1", "a": a.get("deployment_id"), "b": b.get("deployment_id"),
            "transcription_identity_changed": a.get("deployment_id") != b.get("deployment_id"), "changed": changed, "kind": kind,
            "prompts": {"a": ia, "b": ib},
            "rule": "a transcription deployment ID covers weights, decoding, audio, code and runtime; feedback prompts are versioned "
                    "separately (FLH's feedback provenance), so the two never hide each other"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--prompts-a")
    ap.add_argument("--prompts-b")
    ap.add_argument("--json")
    x = ap.parse_args(argv)

    def load(p):
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    rep = diff(load(x.a), load(x.b), x.prompts_a, x.prompts_b)
    if x.json:
        with open(x.json, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(rep, indent=1, sort_keys=True) + "\n")
    print(f"{rep['kind']}: changed {', '.join(rep['changed']) or 'nothing'}; transcription identity changed {rep['transcription_identity_changed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
