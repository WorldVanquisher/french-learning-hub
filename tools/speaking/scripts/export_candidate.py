"""Export a trained checkpoint as a candidate bundle (standard library only; no model is loaded).

  python3 -I -B scripts/export_candidate.py --checkpoint CKPT_DIR --out NEW_DIR --name NAME
      [--deployment-manifest MANIFEST.json] [--evaluation EVAL_SUMMARY.json] [--status candidate]

The bundle holds exactly the inference files (no optimizer or trainer state), a
``candidate_manifest.json`` (``flh_speaking_candidate_bundle_v1``: every file's size and SHA-256,
the base model, step, seed, config and data-manifest hashes from the checkpoint's own
``run_manifest.json``, the deployment identity when given) and ``MODEL_CARD.md`` rendered from
that manifest. ``SHA256SUMS`` seals the bundle. A bundle is never a promotion: its status is
``candidate`` unless the owner decides otherwise.

  python3 -I -B scripts/export_candidate.py --verify NEW_DIR      # sizes and hashes; exit 1 on any difference
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys

SCHEMA = "flh_speaking_candidate_bundle_v1"
INFERENCE = ("config.json", "generation_config.json", "model.safetensors", "preprocessor_config.json", "normalizer.json", "tokenizer.json",
             "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json", "vocab.json", "merges.txt", "run_manifest.json", "train_config.json")
NEVER = ("trainer_state.pt", "optimizer.pt", "scheduler.pt", "rng_state.pth")


def sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def export(ckpt: str, out: str, name: str, deployment: dict | None, evaluation: dict | None, status: str) -> dict:
    if os.path.exists(out) and os.listdir(out):
        raise SystemExit("--out must be a new or empty directory")
    missing = [f for f in ("model.safetensors", "config.json", "run_manifest.json") if not os.path.exists(os.path.join(ckpt, f))]
    if missing:
        raise SystemExit(f"not a flh_speaking checkpoint: missing {', '.join(missing)}")
    os.makedirs(out, exist_ok=True)
    files = {}
    for f in INFERENCE:
        p = os.path.join(ckpt, f)
        if os.path.exists(p):
            shutil.copyfile(p, os.path.join(out, f))
            files[f] = {"bytes": os.path.getsize(p), "sha256": sha(p)}
    with open(os.path.join(ckpt, "run_manifest.json"), encoding="utf-8") as fh:
        run = json.load(fh)
    man = {"schema": SCHEMA, "name": name, "status": status,
           "promotion": {"performed": False, "decided_by": "owner", "note": "a bundle is evidence for review; serving changes only by the owner's decision"},
           "files": files, "excluded": [f for f in NEVER if os.path.exists(os.path.join(ckpt, f))],
           "training": {k: run.get(k) for k in ("step", "config_sha256", "data_manifest_sha256", "seed", "base") if k in run},
           "deployment": deployment or None, "evaluation": evaluation or None}
    with open(os.path.join(out, "candidate_manifest.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(man, indent=1, sort_keys=True) + "\n")
    with open(os.path.join(out, "MODEL_CARD.md"), "w", encoding="utf-8") as fh:
        fh.write(card(man))
    seal(out)
    return man


def card(m: dict) -> str:
    t, d, e = m["training"], m.get("deployment") or {}, m.get("evaluation") or {}
    L = [f"# Model card: {m['name']} ({m['status'].upper()}, not promoted)", "",
         "**What it is.** A French speech-recognition candidate fine-tuned from a pinned Whisper checkpoint by "
         "`flh_speaking train`. It transcribes French audio for FLH's local Speaking provider; it gives no feedback, score or "
         "pronunciation judgement.", "",
         f"- Training step: {t.get('step')}; seed: {t.get('seed', 'see the config')}",
         f"- Training config SHA-256: `{t.get('config_sha256')}`",
         f"- Training data manifest SHA-256: `{t.get('data_manifest_sha256')}`",
         f"- Weights: `model.safetensors` SHA-256 `{m['files']['model.safetensors']['sha256']}` ({m['files']['model.safetensors']['bytes']} bytes)",
         f"- Deployment identity: `{d.get('deployment_id', 'not computed')}`", "",
         "## Evaluation", ""]
    if e:
        L += [f"- {k}: {v}" for k, v in sorted(e.get("summary", {}).items())]
        L += ["", e.get("note", "")]
    else:
        L.append("- not attached")
    L += ["", "## Limits", "",
          "- Trained and evaluated on public read-speech datasets only (CC BY 4.0); no learner audio was used or kept.",
          "- Fewer than 30 independent test speakers: every comparison is an observation (Speaking Lab 2).",
          "- Serving it needs the owner's decision; the bundle never changes `SPEAKING_TRANSCRIPTION_MODEL` by itself.", ""]
    return "\n".join(L)


def seal(d: str) -> None:
    rows = [f"{sha(os.path.join(d, n))}  {n}\n" for n in sorted(os.listdir(d)) if n != "SHA256SUMS"]
    with open(os.path.join(d, "SHA256SUMS"), "w", encoding="utf-8") as fh:
        fh.write("".join(rows))


def verify(d: str) -> list[str]:
    problems = []
    with open(os.path.join(d, "SHA256SUMS"), encoding="utf-8") as fh:
        listed = dict(reversed(line.rstrip("\n").split("  ", 1)) for line in fh if line.strip())
    present = {n for n in os.listdir(d) if n != "SHA256SUMS"}
    problems += [f"{n}: not sealed" for n in sorted(present - set(listed))]
    for n, h in sorted(listed.items()):
        p = os.path.join(d, n)
        if not os.path.exists(p):
            problems.append(f"{n}: missing")
        elif sha(p) != h:
            problems.append(f"{n}: SHA-256 differs from the seal")
    with open(os.path.join(d, "candidate_manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    for n, f in man["files"].items():
        p = os.path.join(d, n)
        if os.path.exists(p) and (os.path.getsize(p) != f["bytes"] or sha(p) != f["sha256"]):
            problems.append(f"{n}: differs from candidate_manifest.json")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint")
    ap.add_argument("--out")
    ap.add_argument("--name")
    ap.add_argument("--deployment-manifest")
    ap.add_argument("--evaluation")
    ap.add_argument("--status", default="candidate", choices=("candidate", "rejected", "owner_review"))
    ap.add_argument("--verify")
    a = ap.parse_args(argv)
    if a.verify:
        bad = verify(a.verify)
        print("\n".join(bad) if bad else "bundle verified: every file matches its seal and the manifest")
        return 1 if bad else 0
    if not (a.checkpoint and a.out and a.name):
        ap.error("--checkpoint, --out and --name are required (or --verify DIR)")

    def load(p):
        if not p:
            return None
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    man = export(a.checkpoint, a.out, a.name, load(a.deployment_manifest), load(a.evaluation), a.status)
    print(f"exported {a.name}: {len(man['files'])} files, excluded {man['excluded']}; weights {man['files']['model.safetensors']['sha256'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
