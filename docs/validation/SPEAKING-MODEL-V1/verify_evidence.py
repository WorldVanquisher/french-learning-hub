"""Recompute the Speaking v1 evidence from per-utterance outputs (standard library only).

  python3 -I -B docs/validation/SPEAKING-MODEL-V1/verify_evidence.py            # verify; exit 1 on any mismatch
  python3 -I -B docs/validation/SPEAKING-MODEL-V1/verify_evidence.py --compact FULL.json OUT.json

Every ``evals/*.json`` holds, per utterance, the reference, the raw model text and
the served text (after the abstention rules), but no scores. The script scores each
utterance with ``flh_fr_asr_norm_v1`` and recomputes each stored summary: WER, CER,
abstentions and the cluster bootstrap interval with the same seed. It then
recomputes the acceptance verdict (``acceptance.json``) from the evaluations it
names. Nothing is taken from the stored summaries; they are only compared.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "speaking"))

from flh_speaking import compare, evaluate, textnorm  # noqa: E402

ITEM_KEYS = ("id", "cluster", "gender", "seconds", "ref")
RAW_KEYS = ("text", "no_speech_prob", "avg_logprob", "p_fr", "top_language", "compression_ratio", "loop_cut")


def compact(src: str, dst: str) -> None:
    with open(src, encoding="utf-8") as fh:
        doc = json.load(fh)
    items = []
    for i in doc["items"]:
        items.append({**{k: i[k] for k in ITEM_KEYS}, "quality": {"snr_db": i["quality"]["snr_db"]},
                      "raw": {k: i["raw"].get(k) for k in RAW_KEYS}, "served": i["served"]})
    out = {k: doc[k] for k in ("schema", "model_dir_name", "decoding", "normalization", "summary")}
    out["breakdown"] = doc["breakdown"]
    out["items"] = items
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({k: v for k, v in out.items() if k != "items"}, ensure_ascii=False, sort_keys=True)[:-1])
        fh.write(', "items": [\n' + ",\n".join(json.dumps(i, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for i in items) + "\n]}\n")


def scored(doc: dict) -> dict:
    """Attach freshly computed scores to every item (the files store none)."""
    for i in doc["items"]:
        i["score"] = {"raw": textnorm.score(i["ref"], i["raw"]["text"]), "served": textnorm.score(i["ref"], i["served"]["text"])}
    return doc


def check_eval(path: str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        doc = scored(json.load(fh))
    bad = []
    for i in doc["items"]:
        if i["served"]["status"] != "transcribed" and i["served"]["text"]:
            bad.append(f"{os.path.basename(path)}: {i['id']} abstained with text")
    for which in ("raw", "served"):
        got = evaluate.summarize(doc["items"], which)
        want = doc["summary"][which]
        for k in ("wer", "cer", "ref_words", "wer_ci95_cluster_bootstrap", "clusters"):
            if got[k] != want[k]:
                bad.append(f"{os.path.basename(path)}: {which}.{k} {got[k]} != stored {want[k]}")
    status = {s: sum(1 for i in doc["items"] if i["served"]["status"] == s) for s in ("transcribed", "no_speech", "not_french")}
    if status != doc["summary"]["served_status"]:
        bad.append(f"{os.path.basename(path)}: served_status differs")
    return bad


def check_acceptance(path: str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        acc = json.load(fh)
    files = acc["inputs"]
    load = lambda f: scored(json.load(open(os.path.join(HERE, f), encoding="utf-8"))) if "probes" not in f else json.load(open(os.path.join(HERE, f), encoding="utf-8"))  # noqa: E731
    base = {k: load(files["base"][k]) for k in ("test", "ood", "probes")}
    cand = {k: load(files["candidate"][k]) for k in ("test", "ood", "probes")}
    got = compare.acceptance(base, cand, acc["overlap_free_test_ids"])
    bad = []
    if got["verdict"] != acc["verdict"] or got["failed"] != acc["failed"]:
        bad.append(f"acceptance verdict {got['verdict']} {got['failed']} != stored {acc['verdict']} {acc['failed']}")
    for k, v in got["criteria"].items():
        if v != acc["criteria"][k]:
            bad.append(f"acceptance {k} differs")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compact", nargs=2, metavar=("FULL", "OUT"))
    a = ap.parse_args()
    if a.compact:
        compact(*a.compact)
        return 0
    problems, checked = [], []
    ev = os.path.join(HERE, "evals")
    for f in sorted(os.listdir(ev)):
        if f.endswith(".json") and not f.startswith("probes"):
            problems += check_eval(os.path.join(ev, f))
            checked.append(f"evals/{f}")
    for i in (f for f in sorted(os.listdir(ev)) if f.startswith("probes")):
        with open(os.path.join(ev, i), encoding="utf-8") as fh:
            doc = json.load(fh)
        ok = sum(1 for p in doc["probes"] if p.get("ok") is True)
        if ok != doc["summary"]["as_expected"]:
            problems.append(f"evals/{i}: as_expected differs")
        checked.append(f"evals/{i}")
    if os.path.exists(os.path.join(HERE, "acceptance.json")):
        problems += check_acceptance(os.path.join(HERE, "acceptance.json"))
        checked.append("acceptance.json")
    print(json.dumps({"checked": checked, "problems": problems}, indent=1))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
