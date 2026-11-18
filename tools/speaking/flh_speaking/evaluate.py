"""Transcribe a split of the frozen dataset and score it (``flh_speaking_eval_v1``).

Scores use ``flh_fr_asr_norm_v1`` on both sides. Two hypotheses are scored per
utterance: ``raw`` (model text) and ``served`` (after the abstention rules in
``model.decide``; an abstention scores as all deletions). Uncertainty is a
cluster bootstrap over speakers (MLS) or sentence groups (FLEURS), because
utterances of one speaker are not independent.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import resource
import time

from . import textnorm  # audio and model (NumPy, torch) are imported where needed

SCHEMA = "flh_speaking_eval_v1"
BOOTSTRAP = 2000
SEED = 20261117
DURATION_BUCKETS = ((0, 8, "<8s"), (8, 14, "8-14s"), (14, 1e9, ">=14s"))
SNR_BUCKETS = ((-1e9, 25, "snr<25dB"), (25, 35, "snr25-35dB"), (35, 1e9, "snr>=35dB"))


def load_rows(data: str, split: str, ids=None) -> list[dict]:
    with open(os.path.join(data, "manifest.jsonl"), encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    rows = [r for r in rows if r["split"] == split]
    if ids is not None:
        want = set(ids)
        rows = [r for r in rows if r["id"] in want]
        if len(rows) != len(want):
            raise ValueError("some requested ids are not in the split")
    return rows


def read_audio(data: str, row: dict):
    from . import audio
    with open(os.path.join(data, row["file"]), "rb") as fh:
        b = fh.read()
    if hashlib.sha256(b[44:]).hexdigest() != row["pcm_sha256"]:
        raise ValueError(f"prepared audio changed: {row['id']}")
    return audio.read_wav_pcm16(b)


def cluster_of(row: dict) -> str:
    return row["speaker"] or row["group"]


def bucket(value: float, buckets) -> str:
    for lo, hi, name in buckets:
        if lo <= value < hi:
            return name
    return "other"


def bootstrap_ci(per_cluster: dict[str, tuple[int, int]], seed: int = SEED, n: int = BOOTSTRAP) -> list[float] | None:
    """95% percentile interval of pooled error rate, resampling clusters."""
    keys = sorted(per_cluster)
    if len(keys) < 2:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        e = w = 0
        for _ in keys:
            ce, cw = per_cluster[keys[rng.randrange(len(keys))]]
            e += ce
            w += cw
        vals.append(e / w if w else 0.0)
    vals.sort()
    return [round(vals[int(0.025 * n)], 5), round(vals[int(0.975 * n) - 1], 5)]


def summarize(items: list[dict], which: str) -> dict:
    sc = [i["score"][which] for i in items]
    out = textnorm.rate(sc)
    clusters: dict[str, list[int]] = {}
    for i, s in zip(items, sc):
        c = clusters.setdefault(i["cluster"], [0, 0])
        c[0] += s["sub"] + s["del"] + s["ins"]
        c[1] += s["ref_words"]
    out["wer_ci95_cluster_bootstrap"] = bootstrap_ci({k: tuple(v) for k, v in clusters.items()})
    out["clusters"] = len(clusters)
    return out


def breakdown(items: list[dict], which: str) -> dict:
    def by(fn):
        groups: dict[str, list] = {}
        for i in items:
            groups.setdefault(fn(i), []).append(i["score"][which])
        return {k: {kk: v for kk, v in textnorm.rate(g).items() if kk in ("utterances", "ref_words", "wer", "cer")} for k, g in sorted(groups.items())}

    no_digit = [i["score"][which] for i in items if not (i["score"][which]["hyp_has_digit"] or i["score"][which]["ref_has_digit"])]
    return {
        "by_cluster": by(lambda i: i["cluster"]),
        "by_gender": by(lambda i: i["gender"]),
        "by_duration": by(lambda i: bucket(i["seconds"], DURATION_BUCKETS)),
        "by_snr": by(lambda i: bucket(i["quality"]["snr_db"], SNR_BUCKETS)),
        "without_digits": {k: v for k, v in textnorm.rate(no_digit).items() if k in ("utterances", "ref_words", "wer", "cer")},
        "hyp_with_digits": sum(1 for i in items if i["score"][which]["hyp_has_digit"]),
    }


def style(items: list[dict]) -> dict:
    """Share of non-empty raw outputs with an uppercase letter / with punctuation."""
    texts = [i["raw"]["text"] for i in items if i["raw"]["text"]]
    if not texts:
        return {"outputs": 0}
    return {
        "outputs": len(texts),
        "with_uppercase": round(sum(any(c.isupper() for c in t) for t in texts) / len(texts), 4),
        "with_punctuation": round(sum(any(c in ".,;:!?" for c in t) for t in texts) / len(texts), 4),
    }


def evaluate(model_dir: str, data: str, split: str, out: str, *, ids=None, batch: int = 8, threads: int = 4, label: str = "") -> dict:
    from . import audio, model
    rows = load_rows(data, split, ids)
    t0 = time.monotonic()
    tr = model.Transcriber(model_dir, threads=threads)
    load_s = time.monotonic() - t0
    items, batch_secs, audio_secs = [], [], []
    for k in range(0, len(rows), batch):
        chunk = rows[k:k + batch]
        wavs = [read_audio(data, r) for r in chunk]
        if any(len(w) > model.WINDOW_SECONDS * audio.SAMPLE_RATE for w in wavs):
            raise ValueError("evaluation clips must be at most 30 s")
        t1 = time.monotonic()
        outs = tr.raw(wavs)
        batch_secs.append(time.monotonic() - t1)
        audio_secs.append(sum(len(w) for w in wavs) / audio.SAMPLE_RATE)
        for r, w, o in zip(chunk, wavs, outs):
            q = audio.quality(w)
            res = model.decide([dict(o)], q)
            items.append({
                "id": r["id"], "cluster": cluster_of(r), "gender": r["gender"], "seconds": r["seconds"],
                "quality": q, "ref": r["text"], "raw": o,
                "served": {"status": res.status, "text": res.text, "warnings": res.warnings},
                "score": {"raw": textnorm.score(r["text"], o["text"]), "served": textnorm.score(r["text"], res.text)},
            })
    peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    timing = {
        "model_load_s": round(load_s, 2), "batch": batch, "threads": threads,
        "audio_s": round(sum(audio_secs), 1), "compute_s": round(sum(batch_secs), 1),
        "real_time_factor": round(sum(batch_secs) / max(sum(audio_secs), 1e-9), 4),
        "peak_rss_mb": round(peak_kb / 1024, 1),
    }
    doc = build(items, label, split, timing, os.path.basename(os.path.normpath(model_dir)))
    write(doc, out)
    return doc


def write(doc: dict, out: str) -> None:
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, out)


def build(items: list[dict], label: str, split: str, timing: dict, model_name: str) -> dict:
    from . import model
    summary = {
        "label": label, "split": split, "utterances": len(items),
        "raw": summarize(items, "raw"), "served": summarize(items, "served"),
        "served_status": {s: sum(1 for i in items if i["served"]["status"] == s) for s in ("transcribed", "no_speech", "not_french")},
        "served_warnings": {w: sum(1 for i in items if w in i["served"]["warnings"]) for w in sorted({w for i in items for w in i["served"]["warnings"]})},
        "style": style(items),
        "timing": timing,
    }
    return {
        "schema": SCHEMA, "model_dir_name": model_name,
        "decoding": model.DECODING, "normalization": textnorm.NORM_VERSION,
        "runtime": {"python": platform.python_version(), "machine": platform.machine()},
        "summary": summary, "breakdown": {"raw": breakdown(items, "raw"), "served": breakdown(items, "served")},
        "items": items,
    }


def rescore(path: str, data: str, out: str | None = None) -> dict:
    """Re-apply the current abstention rules and scoring to stored raw model outputs
    (no inference). Used when a rule changes after an evaluation ran."""
    from . import audio, model
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    rows = {r["id"]: r for r in load_rows(data, doc["summary"]["split"])}
    for i in doc["items"]:
        q = audio.quality(read_audio(data, rows[i["id"]]))
        res = model.decide([dict(i["raw"])], q)
        i["quality"] = q
        i["served"] = {"status": res.status, "text": res.text, "warnings": res.warnings}
        i["score"] = {"raw": textnorm.score(i["ref"], i["raw"]["text"]), "served": textnorm.score(i["ref"], res.text)}
    new = build(doc["items"], doc["summary"]["label"], doc["summary"]["split"], doc["summary"]["timing"], doc["model_dir_name"])
    new["rescored"] = True
    write(new, out or path)
    return new
