"""Controlled audio variants for quality slices (standard library only).

  python3 -B -m flh_speaking lab variants --case CASE.json [--audio FILE] --out DIR

From one source recording (mono PCM16 WAV) it makes labelled variants, each
with its own SHA-256, the source's ID as ``group_id`` and reproducible tags:

* volume: a gain in dB. A gain that would clip is refused and recorded, never
  applied with clipping.
* silence: zeros added at the start and the end (boundary silence).
* noise: white noise from ``random.Random(seed)`` at a target SNR (RMS over the
  whole clip). It is refused if the mix would clip.
* speed: a linear-interpolation resample, which changes duration and pitch
  together. It is a crude speed probe, not a time-stretch.

The source bytes are never modified: their hash is checked before and after.
Tags (``TAG_RULES``) come from the parameters and the reference text only, so
the same plan on the same source gives the same IDs, tags and hashes.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import random
import struct
import wave

from . import textnorm

SCHEMA = "flh_speaking_lab_variants_v1"
TAG_RULES = {
    "phrase_length": "reference words after flh_fr_asr_norm_v1: short <= 3, medium 4-10, long > 10",
    "volume": "gain in dB as applied (0dB for the source)",
    "silence": "none, or lead<ms>ms_trail<ms>ms of added boundary silence",
    "noise": "none, or white_snr<dB>dB_seed<seed>",
    "speed": "x1.00, or the resample factor x<f>",
}
DEFAULT_PLAN = (("volume", -12.0), ("volume", 6.0), ("volume", 12.0), ("silence", (500, 500)),
                ("noise", (20.0, 7)), ("noise", (5.0, 7)), ("speed", 1.25), ("speed", 0.8))
PEAK = 32767


class Refused(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


def read_pcm16(data: bytes) -> tuple[int, list[int]]:
    with wave.open(io.BytesIO(data), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("variants need mono 16-bit PCM WAV")
        rate, frames = w.getframerate(), w.readframes(w.getnframes())
    return rate, list(struct.unpack(f"<{len(frames) // 2}h", frames))


def write_pcm16(rate: int, samples: list[int]) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


def rms(x: list[float]) -> float:
    return math.sqrt(sum(v * v for v in x) / len(x)) if x else 0.0


def gain(samples: list[int], db: float) -> list[int]:
    g = 10 ** (db / 20)
    peak = max((abs(v) for v in samples), default=0) * g
    if peak > PEAK:
        raise Refused("would_clip", f"peak {peak:.0f} > {PEAK} at {db:+g} dB")
    return [int(round(v * g)) for v in samples]


def pad_silence(samples: list[int], rate: int, lead_ms: int, trail_ms: int) -> list[int]:
    return [0] * (rate * lead_ms // 1000) + samples + [0] * (rate * trail_ms // 1000)


def white_noise(samples: list[int], snr_db: float, seed: int) -> list[int]:
    rnd = random.Random(seed)
    noise = [rnd.gauss(0.0, 1.0) for _ in samples]
    scale = rms(samples) / (10 ** (snr_db / 20)) / (rms(noise) or 1.0)
    mixed = [v + n * scale for v, n in zip(samples, noise)]
    peak = max((abs(v) for v in mixed), default=0)
    if peak > PEAK:
        raise Refused("would_clip", f"peak {peak:.0f} > {PEAK} at SNR {snr_db:g} dB")
    return [int(round(v)) for v in mixed]


def speed(samples: list[int], factor: float) -> list[int]:
    n = max(1, int(round(len(samples) / factor)))
    out = []
    for k in range(n):
        pos = k * factor
        i = int(pos)
        if i + 1 >= len(samples):
            out.append(samples[-1])
            continue
        f = pos - i
        out.append(int(round(samples[i] * (1 - f) + samples[i + 1] * f)))
    return out


def phrase_length(reference: str) -> str:
    n = len(textnorm.words(reference))
    return "short" if n <= 3 else "medium" if n <= 10 else "long"


def ident(source_id: str, kind: str, p) -> tuple[str, str, str]:
    """Variant ID and its tag, from the parameters alone (made or refused alike)."""
    if kind == "volume":
        return f"{source_id}~volume{p:+g}dB", "volume", f"{p:+g}dB"
    if kind == "silence":
        return f"{source_id}~silence{p[0]}-{p[1]}ms", "silence", f"lead{p[0]}ms_trail{p[1]}ms"
    if kind == "noise":
        return f"{source_id}~noise-snr{p[0]:g}dB-seed{p[1]}", "noise", f"white_snr{p[0]:g}dB_seed{p[1]}"
    if kind == "speed":
        return f"{source_id}~speed-x{p:.2f}", "speed", f"x{p:.2f}"
    raise ValueError(f"unknown variant kind {kind!r}")


def make(source_id: str, data: bytes, reference: str, plan=DEFAULT_PLAN, speaker: str | None = None) -> tuple[dict, dict]:
    """The manifest and {item id: wav bytes}. The source is item 0 (group_id = its own id)."""
    src_sha = hashlib.sha256(data).hexdigest()
    rate, samples = read_pcm16(data)
    base_tags = {"phrase_length": phrase_length(reference), "volume": "0dB", "silence": "none", "noise": "none", "speed": "x1.00"}
    items = [{"id": source_id, "group_id": source_id, "kind": "source", "params": None, "status": "made", "tags": dict(base_tags),
              "sha256": src_sha, "bytes": len(data), "seconds": round(len(samples) / rate, 3), "speaker": speaker}]
    files = {source_id: data}
    for kind, p in plan:
        vid, key, val = ident(source_id, kind, p)
        tags = dict(base_tags, **{key: val})
        try:
            out = {"volume": lambda: gain(samples, p), "silence": lambda: pad_silence(samples, rate, *p),
                   "noise": lambda: white_noise(samples, *p), "speed": lambda: speed(samples, p)}[kind]()
            wav = write_pcm16(rate, out)
            items.append({"id": vid, "group_id": source_id, "kind": kind, "params": p, "status": "made", "tags": tags,
                          "sha256": hashlib.sha256(wav).hexdigest(), "bytes": len(wav), "seconds": round(len(out) / rate, 3), "speaker": speaker})
            files[vid] = wav
        except Refused as r:
            items.append({"id": vid, "group_id": source_id, "kind": kind, "params": p, "status": "refused",
                          "reason": r.reason, "detail": r.detail, "tags": tags, "speaker": speaker})
    if hashlib.sha256(data).hexdigest() != src_sha:  # defensive: the source must never change
        raise RuntimeError("the source bytes changed")
    made = [i for i in items if i["status"] == "made"]
    speakers = sorted({i["speaker"] for i in made if i["speaker"]})
    manifest = {
        "schema": SCHEMA, "tag_rules": TAG_RULES, "source": {"id": source_id, "sha256": src_sha, "unchanged": True},
        "counts": {"samples": len(made), "originals": 1, "variants": len(made) - 1, "refused": len(items) - len(made),
                   "groups": len({i["group_id"] for i in made}),
                   "speakers": len(speakers) if speakers else "no speaker metadata"},
        "items": items,
        "note": "Variants share the source's group_id: count groups, not samples, when estimating independent evidence.",
    }
    return manifest, files


def write(manifest: dict, files: dict, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for vid, data in files.items():
        with open(os.path.join(out_dir, vid.replace("/", "_") + ".wav"), "wb") as fh:
            fh.write(data)
    with open(os.path.join(out_dir, "variants.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
