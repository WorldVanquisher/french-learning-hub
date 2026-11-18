"""Robustness sets for Speaking v2: model outputs only, analysis elsewhere.

Each set is a list of clips built deterministically (seed 20261118) from the
frozen public material. For every clip it records the signal statistics, the
model's raw output for one <= 30 s window (language probabilities read at the
start-of-transcript position, no-speech probability, average log-probability,
text) and the decision of the current policy ``flh_speaking_transcribe_v1``.
Other policies (for example warning-only language identification) are applied
to the same raw outputs afterwards, so they are compared on identical inference.

* ``short``: native French truncated to 1-5 s (MLS test, FLEURS ood), their
  full-length versions, and FLEURS ood clips that are naturally under 5 s.
* ``language``: a sample kept apart from v1: SLR57 dev (Niger, West African
  French; v1 used test/ca16, Central Africa), FLEURS English and Mandarin dev
  utterances after the 10 per language v1 used, and MLS dev full and truncated.
* ``noise``: 40 MLS test utterances under babble and white noise at fixed SNRs,
  scaled to low levels, and the noises alone.

Nothing is written but the output JSON (no audio).
"""

from __future__ import annotations

import json
import os
import random
import re
import tarfile
import time

import numpy as np

from . import audio, evaluate, fetch, model, pins, prepare

SCHEMA = "flh_speaking_robustness_v1"
SEED = 20261118
SR = audio.SAMPLE_RATE
LENGTHS = (1.0, 1.5, 2.0, 3.0, 5.0)
RAW_KEYS = ("text", "p_fr", "top_language", "p_top_language", "no_speech_prob", "avg_logprob", "compression_ratio", "hit_token_limit", "loop_cut")
SNRS = (20, 10, 5, 0)
LEVELS = (-35, -45, -55, -65)


ONSET_DBFS = -45.0


def onset(x: np.ndarray) -> int:
    """Sample index 0.1 s before the first 30 ms frame above -45 dBFS (speech
    start; FLEURS recordings begin with up to a second of silence)."""
    loud = np.flatnonzero(audio.frame_db(x) > ONSET_DBFS)
    return max(0, int(loud[0]) * audio.FRAME - SR // 10) if loud.size else 0


def cut(x: np.ndarray, target: float) -> np.ndarray:
    """``target`` seconds from the speech onset, ended at the quietest 30 ms
    frame within +-0.25 s of the target, so a word is cut as rarely as possible."""
    x = x[onset(x):]
    lo, hi = int((target - 0.25) * SR), min(len(x), int((target + 0.25) * SR))
    if hi - lo <= audio.FRAME:
        return x[: int(target * SR)]
    step = audio.FRAME // 2
    starts = list(range(lo, hi - audio.FRAME, step))
    j = starts[int(np.argmin([float(np.sum(x[s:s + audio.FRAME] ** 2)) for s in starts]))] + audio.FRAME // 2
    return x[:j]


def decide_warning_only(outs: list[dict], q: dict):
    """The candidate policy: language identification never abstains; a clip
    the current rule would refuse as not_french is transcribed with the
    possibly_not_french warning (P(fr) < 0.2 is below that warning's 0.5)."""
    saved = model.NOT_FRENCH_FR_MAX
    model.NOT_FRENCH_FR_MAX = -1.0
    try:
        return model.decide(outs, q)
    finally:
        model.NOT_FRENCH_FR_MAX = saved


def rms_db(x: np.ndarray) -> float:
    return 20 * np.log10(max(float(np.sqrt(np.mean(x.astype(np.float64) ** 2))), 1e-12))


def scale_to(x: np.ndarray, dbfs: float) -> np.ndarray:
    return (x * 10 ** ((dbfs - rms_db(x)) / 20)).astype(np.float32)


def mix(speech: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    n = np.resize(noise, len(speech))
    n = n * 10 ** ((rms_db(speech) - snr_db - rms_db(n)) / 20)
    y = speech + n
    peak = float(np.max(np.abs(y))) or 1.0
    return (y / peak * 0.95 if peak > 0.95 else y).astype(np.float32)


def clip(set_, id_, x, *, group, cluster, condition, ref=None, length=None) -> dict:
    if len(x) > model.WINDOW_SECONDS * SR:
        raise ValueError(f"{id_}: longer than one window")
    return {"set": set_, "id": id_, "group": group, "cluster": cluster, "condition": condition, "length": length, "ref": ref, "x": x}


def infer(tr, clips, batch: int) -> list[dict]:
    """Run clips as they are produced (a generator), ``batch`` windows at a
    time, and drop each clip's audio once it is decided."""
    done, pending = [], []

    def flush():
        for c, r in zip(pending, tr.raw([c["x"] for c in pending])):
            c["raw"] = {k: (round(r[k], 5) if isinstance(r.get(k), float) else r.get(k)) for k in RAW_KEYS}
            finish(c)
        pending.clear()

    def finish(c):
        # Without sound the gate answers before any window is read.
        res = model.decide([dict(c["raw"])] if c["raw"] else [], c["quality"])
        c["served"] = {"status": res.status, "text": res.text, "warnings": res.warnings}
        warn = decide_warning_only([dict(c["raw"])] if c["raw"] else [], c["quality"])
        c["served_warning_only"] = {"status": warn.status, "text": warn.text, "warnings": warn.warnings}
        del c["x"]
        done.append(c)

    for c in clips:
        c["quality"] = audio.quality(c["x"])
        c["raw"] = None
        if c["quality"]["sound_seconds"] < model.MIN_SOUND_SECONDS:
            finish(c)
            continue
        pending.append(c)
        if len(pending) == batch:
            flush()
    if pending:
        flush()
    return done


def _by_speaker(rows: list[dict], per: int) -> list[dict]:
    out, seen = [], {}
    for r in sorted(rows, key=lambda r: r["id"]):
        k = evaluate.cluster_of(r)
        if seen.get(k, 0) < per:
            out.append(r)
            seen[k] = seen.get(k, 0) + 1
    return out


def set_short(data: str):
    rng = random.Random(SEED)
    test = _by_speaker(evaluate.load_rows(data, "test"), 8)
    ood = evaluate.load_rows(data, "ood")
    picked = test + rng.sample(sorted(ood, key=lambda r: r["id"]), 64)
    for r in picked:
        x = evaluate.read_audio(data, r)
        g = "mls_test" if r["split"] == "test" else "fleurs_ood"
        yield clip("short", r["id"], x, group=g, cluster=evaluate.cluster_of(r), condition="full", ref=r["text"], length=round(len(x) / SR, 2))
        for L in LENGTHS:
            y = cut(x, L)
            yield clip("short", f"{r['id']}@{L}", y, group=g, cluster=evaluate.cluster_of(r), condition=f"cut_{L}", length=round(len(y) / SR, 2))
    for r in sorted(ood, key=lambda r: r["id"]):
        if r["seconds"] < 5.0 and r not in picked:
            x = evaluate.read_audio(data, r)
            yield clip("short", r["id"], x, group="fleurs_ood_natural_short", cluster=evaluate.cluster_of(r), condition="full", ref=r["text"], length=round(len(x) / SR, 2))


def _slr57_dev(sources: str, n: int) -> list[tuple[str, str, str, np.ndarray]]:
    path = "African_Accented_French.tar.gz"
    src = prepare._src(sources, pins.SLR57, path)
    bad = fetch.verify(src, *pins.SLR57["files"][path])
    if bad:
        raise ValueError(f"openslr/57/{path}: {bad}")
    texts = {}
    with tarfile.open(src, "r:gz") as tf:
        for m in tf:
            if m.name == "African_Accented_French/transcripts/dev/niger_west_african_fr/transcripts.txt":
                for line in tf.extractfile(m).read().decode("utf-8").splitlines():
                    f, _, text = line.strip().partition(" ")
                    if f and text.strip():
                        texts[f.rsplit("/", 1)[-1][:-4]] = (f.split("/")[1], text.strip())
                break
    by_spk: dict[str, list[str]] = {}
    for uid, (spk, _) in sorted(texts.items()):
        by_spk.setdefault(spk, []).append(uid)
    rng = random.Random(SEED)
    want: list[str] = []
    while len(want) < n and any(by_spk.values()):
        for spk in sorted(by_spk):
            if by_spk[spk] and len(want) < n:
                want.append(by_spk[spk].pop(rng.randrange(len(by_spk[spk]))))
    wanted, got = set(want), {}
    with tarfile.open(src, "r:gz") as tf:
        for m in tf:
            if m.isfile() and m.name.startswith("African_Accented_French/speech/dev/niger_west_african_fr/") and m.name.endswith(".wav"):
                uid = m.name.rsplit("/", 1)[-1][:-4]
                if uid in wanted:
                    got[uid] = audio.decode(tf.extractfile(m).read(), max_seconds=prepare.MAX_SOURCE_SECONDS, allowed=audio.DATA_FAMILIES).samples
    return [(uid, texts[uid][0], texts[uid][1], got[uid]) for uid in want if uid in got]


def _fleurs_other(sources: str, skip: int, take: int) -> list[tuple[str, str, np.ndarray]]:
    out = []
    for lang, base in prepare.NON_FRENCH.items():
        rows = [line.split("\t") for line in prepare._read(sources, pins.FLEURS, f"{base}/dev.tsv").splitlines() if line.strip()]
        stems = sorted({r[1].rsplit(".", 1)[0] for r in rows})[skip:skip + take]
        got = dict(prepare._members(prepare._src(sources, pins.FLEURS, f"{base}/audio/dev.tar.gz"), set(stems), re.compile(r"\d+\.wav")))
        for stem in stems:
            out.append((lang, stem, audio.decode(got[stem], max_seconds=prepare.MAX_SOURCE_SECONDS, allowed=audio.DATA_FAMILIES).samples))
    return out


def set_language(data: str, sources: str):
    for uid, spk, text, x in _slr57_dev(sources, 300):
        if len(x) <= model.WINDOW_SECONDS * SR:
            yield clip("language", f"slr57_dev/{uid}", x, group="accented_fr_niger", cluster=spk, condition="full", ref=text, length=round(len(x) / SR, 2))
    for lang, stem, x in _fleurs_other(sources, skip=10, take=40):
        y = x[: int(model.WINDOW_SECONDS * SR)]
        yield clip("language", f"{lang}_{stem}", y, group=f"other_{lang}", cluster=lang, condition="full", length=round(len(y) / SR, 2))
    for r in evaluate.load_rows(data, "dev"):
        x = evaluate.read_audio(data, r)
        yield clip("language", r["id"], x, group="native_fr_mls_dev", cluster=evaluate.cluster_of(r), condition="full", ref=r["text"], length=round(len(x) / SR, 2))
        for L in (1.5, 2.0):
            y = cut(x, L)
            yield clip("language", f"{r['id']}@{L}", y, group="native_fr_mls_dev", cluster=evaluate.cluster_of(r), condition=f"cut_{L}", length=round(len(y) / SR, 2))


def set_noise(data: str):
    rows = evaluate.load_rows(data, "test")
    targets = _by_speaker(rows, 5)
    rng = np.random.default_rng(SEED)
    for k, r in enumerate(targets):
        x = evaluate.read_audio(data, r)
        spk = evaluate.cluster_of(r)
        others = [o for o in rows if evaluate.cluster_of(o) != spk]
        pick = [others[(k * 7 + j * 31) % len(others)] for j in range(4)]
        babble = np.sum([np.resize(scale_to(evaluate.read_audio(data, o), -30.0), len(x)) for o in pick], axis=0).astype(np.float32)
        white = rng.standard_normal(len(x)).astype(np.float32)
        base = dict(group="mls_test", cluster=spk)
        yield clip("noise", r["id"], x, condition="clean", ref=r["text"], length=round(len(x) / SR, 2), **base)
        for snr in SNRS:
            yield clip("noise", f"{r['id']}+babble{snr}", mix(x, babble, snr), condition=f"babble_{snr}dB", ref=r["text"], **base)
            yield clip("noise", f"{r['id']}+white{snr}", mix(x, white, snr), condition=f"white_{snr}dB", ref=r["text"], **base)
        for lv in LEVELS:
            yield clip("noise", f"{r['id']}@{lv}dBFS", scale_to(x, lv), condition=f"level_{lv}dBFS", ref=r["text"], **base)
        if k % 2 == 0:
            yield clip("noise", f"babble_only_{k}", scale_to(babble, -30.0), condition="babble_only", **base)
            yield clip("noise", f"white_only_{k}", scale_to(white, -30.0), condition="white_only", **base)


def run(set_name: str, model_dir: str, data: str, out: str, *, sources: str | None = None, batch: int = 4, threads: int = 4) -> dict:
    clips = {"short": lambda: set_short(data), "language": lambda: set_language(data, sources), "noise": lambda: set_noise(data)}[set_name]()
    tr = model.Transcriber(model_dir, threads=threads)
    t1 = time.monotonic()
    items = infer(tr, clips, batch)
    doc = {"schema": SCHEMA, "set": set_name, "seed": SEED, "model_dir_name": os.path.basename(os.path.normpath(model_dir)),
           "model_safetensors_sha256": fetch.file_digest(os.path.join(model_dir, "model.safetensors"), "sha256"),
           "decoding": model.DECODING, "timing": {"build_and_inference_s": round(time.monotonic() - t1, 1), "batch": batch, "threads": threads},
           "items": items}
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({k: v for k, v in doc.items() if k != "items"}, ensure_ascii=False, sort_keys=True)[:-1])
        fh.write(', "items": [\n' + ",\n".join(json.dumps(i, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for i in items) + "\n]}\n")
    return {k: v for k, v in doc.items() if k != "items"} | {"clips": len(items)}
