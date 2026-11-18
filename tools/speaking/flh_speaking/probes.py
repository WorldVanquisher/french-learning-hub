"""Robustness probes (``flh_speaking_probes_v1``): what the served path does with
short, silent, noisy, clipped, long, re-encoded, invalid and non-French audio.

Each probe states what it expects:
  abstain     no transcript (status no_speech / not_french)
  transcribe  a transcript; scored against the reference when one exists
  refuse      a structured input error before the model runs (AudioError code)
  record      no expectation (a fragment of a word may or may not be transcribed)

Synthetic signals use a fixed seed; speech probes reuse frozen test utterances.
Lossy re-encodings (webm/opus, mp4/aac, mp3) go through the same in-memory
decoder as the service, so they also check that preprocessing and inference use
one audio convention.
"""

from __future__ import annotations

import io
import json
import os
import time

import numpy as np

from . import audio, evaluate, model, textnorm

SCHEMA = "flh_speaking_probes_v1"
SR = audio.SAMPLE_RATE
SEED = 7
SERVICE_MAX_SECONDS = 120.0
SPEECH_IDS = 3  # first test utterances (sorted ids) reused by speech probes
NON_FRENCH_ENV = "FLH_SPEAKING_NON_FRENCH"  # optional dir of {name}.wav + {name}.txt (other-language speech)


def _noise(seconds, dbfs, rng):
    x = rng.standard_normal(int(seconds * SR)).astype(np.float32)
    return x / np.sqrt(np.mean(x ** 2)) * (10 ** (dbfs / 20))


def _add_noise(speech, snr_db, rng):
    p = float(np.mean(speech.astype(np.float64) ** 2))
    n = rng.standard_normal(len(speech)).astype(np.float32)
    n *= np.sqrt(p / (10 ** (snr_db / 10)) / float(np.mean(n.astype(np.float64) ** 2)))
    return np.clip(speech + n, -1, 1).astype(np.float32)


def encode(samples: np.ndarray, fmt: str, codec: str, rate: int = SR, layout: str = "mono") -> bytes:
    """Encode float32 16 kHz mono with FFmpeg (PyAV) into a container, in memory."""
    import av

    buf = io.BytesIO()
    with av.open(buf, mode="w", format=fmt) as c:
        st = c.add_stream(codec, rate=rate, layout=layout)
        rs = av.AudioResampler(format=st.codec_context.format.name if st.codec_context.format else "fltp", layout=layout, rate=rate)
        fr = av.AudioFrame.from_ndarray(samples.reshape(1, -1).astype(np.float32), format="flt", layout="mono")
        fr.sample_rate = SR
        frames = rs.resample(fr) + rs.resample(None)
        for f in frames:
            for p in st.encode(f):
                c.mux(p)
        for p in st.encode(None):
            c.mux(p)
    return buf.getvalue()


def run(model_dir: str, out: str, *, data: str | None = None, threads: int = 4) -> dict:
    rng = np.random.default_rng(SEED)
    tr = model.Transcriber(model_dir, threads=threads)
    probes = []

    def served(name, samples, expect, ref=None, note=""):
        t0 = time.monotonic()
        r = tr.transcribe(samples)
        p = {"name": name, "expect": expect, "status": r.status, "text": r.text, "warnings": r.warnings,
             "seconds": round(len(samples) / SR, 2), "sound_seconds": r.quality.get("sound_seconds"),
             "windows": len(r.windows), "latency_s": round(time.monotonic() - t0, 3), "note": note,
             "window_detail": [{k: w.get(k) for k in ("no_speech_prob", "avg_logprob", "p_fr", "top_language", "compression_ratio", "kept", "text")} for w in r.windows]}
        if ref is not None:
            p["ref"] = ref
            p["wer"] = textnorm.rate([textnorm.score(ref, r.text)])["wer"]
        p["ok"] = None if expect == "record" else (r.status != "transcribed") if expect == "abstain" else (r.status == "transcribed")
        probes.append(p)

    def refused(name, data_bytes, allowed=audio.SERVICE_FAMILIES, max_seconds=SERVICE_MAX_SECONDS):
        try:
            d = audio.decode(data_bytes, max_seconds=max_seconds, allowed=allowed)
            probes.append({"name": name, "expect": "refuse", "status": "decoded", "seconds": round(d.seconds, 2), "ok": False})
        except audio.AudioError as e:
            probes.append({"name": name, "expect": "refuse", "status": "refused", "code": e.code, "message": str(e), "ok": True})

    # -- abstention probes --------------------------------------------------
    served("silence_1s", np.zeros(SR, np.float32), "abstain")
    served("silence_10s", np.zeros(10 * SR, np.float32), "abstain")
    served("hiss_-50dBFS_5s", _noise(5, -50, rng), "abstain")
    served("noise_-20dBFS_5s", _noise(5, -20, rng), "abstain")
    served("noise_-10dBFS_10s", _noise(10, -10, rng), "abstain")
    t = np.arange(3 * SR) / SR
    served("tone_440Hz_3s", (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), "abstain")
    served("hum_50Hz_5s", (0.2 * np.sin(2 * np.pi * 50 * np.arange(5 * SR) / SR)).astype(np.float32), "abstain")
    clicks = np.zeros(5 * SR, np.float32)
    clicks[:: SR // 2] = 0.9
    served("clicks_5s", clicks, "abstain")

    # -- refusals -----------------------------------------------------------
    refused("empty", b"")
    refused("random_bytes", rng.integers(0, 256, 4096, dtype=np.uint8).tobytes())
    wav = audio.to_wav_pcm16(_noise(1, -30, rng))
    refused("truncated_wav_header", wav[:30])
    refused("flac_not_accepted_by_service", b"fLaC" + b"\0" * 64)
    refused("too_long_125s", audio.to_wav_pcm16(np.zeros(125 * SR, np.float32)))

    # -- speech probes ------------------------------------------------------
    if data:
        rows = evaluate.load_rows(data, "test")[:SPEECH_IDS]
        speech = [(r, evaluate.read_audio(data, r)) for r in rows]
        r0, s0 = speech[0]
        served("speech_clean", s0, "transcribe", r0["text"])
        served("speech_first_0.5s", s0[: SR // 2], "record", None, "partial word")
        served("speech_first_1.5s", s0[: int(1.5 * SR)], "record", None, "a few words")
        for snr in (20, 10, 5, 0):
            served(f"speech_snr_{snr}dB", _add_noise(s0, snr, rng), "transcribe", r0["text"])
        served("speech_clipped_x8", np.clip(s0 * 8, -1, 1).astype(np.float32), "transcribe", r0["text"])
        served("speech_quiet_-30dB", (s0 * 10 ** (-30 / 20)).astype(np.float32), "transcribe", r0["text"])
        pad = np.zeros(20 * SR, np.float32)
        served("speech_padded_20s_silence_each_side", np.concatenate([pad, s0, pad]), "transcribe", r0["text"],
               "long-form windows; silent windows must add no text")
        long = np.concatenate([s for _, s in speech] * 2)
        refs = " ".join(r["text"] for r, _ in speech) * 1
        served("long_form_concat", long[: int(SERVICE_MAX_SECONDS * SR)], "transcribe", " ".join([refs, refs]),
               "the same three utterances twice (cut at 120 s)")
        for name, fmt, codec in (("webm_opus", "webm", "libopus"), ("mp4_aac", "mp4", "aac"), ("mp3", "mp3", "libmp3lame"), ("wav_44k_stereo", "wav", "pcm_s16le")):
            try:
                if name == "wav_44k_stereo":
                    up = np.interp(np.arange(0, len(s0), SR / 44100.0), np.arange(len(s0)), s0).astype(np.float32)
                    st = np.stack([up, up])
                    buf = io.BytesIO()
                    import wave
                    with wave.open(buf, "wb") as w:
                        w.setnchannels(2)
                        w.setsampwidth(2)
                        w.setframerate(44100)
                        w.writeframes((np.clip(st.T, -1, 1) * 32767).astype("<i2").tobytes())
                    blob = buf.getvalue()
                else:
                    blob = encode(s0, fmt, codec, rate=48000 if codec == "libopus" else (44100 if codec == "libmp3lame" else SR))
                d = audio.decode(blob, max_seconds=SERVICE_MAX_SECONDS, allowed=audio.SERVICE_FAMILIES)
                n = min(len(d.samples), len(s0))
                corr = float(np.corrcoef(d.samples[:n], s0[:n])[0, 1]) if n > SR else None
                served(f"reencoded_{name}", d.samples, "transcribe", r0["text"],
                       f"{len(blob)} bytes; decoded {d.family}/{d.source_codec} {d.source_rate} Hz x{d.source_channels}; corr={corr and round(corr, 4)}")
            except audio.AudioError as e:
                probes.append({"name": f"reencoded_{name}", "expect": "transcribe", "status": "refused", "code": e.code, "ok": False})
            except Exception as e:  # encoder missing from the FFmpeg build
                probes.append({"name": f"reencoded_{name}", "expect": "transcribe", "status": "encoder_unavailable", "error": type(e).__name__, "ok": None})
    nf = os.environ.get(NON_FRENCH_ENV)
    if nf and os.path.isdir(nf):
        for fn in sorted(os.listdir(nf)):
            if fn.endswith(".wav"):
                with open(os.path.join(nf, fn), "rb") as fh:
                    d = audio.decode(fh.read(), max_seconds=35, allowed=audio.DATA_FAMILIES)
                served(f"non_french_{fn[:-4]}", d.samples, "abstain", None, "other-language speech")
    summary = {
        "probes": len(probes),
        "as_expected": sum(1 for p in probes if p.get("ok") is True),
        "not_as_expected": sorted(p["name"] for p in probes if p.get("ok") is False),
        "recorded_only": sorted(p["name"] for p in probes if p.get("ok") is None and p.get("expect") == "record"),
        "not_run": sorted(p["name"] for p in probes if p.get("ok") is None and p.get("expect") != "record"),
    }
    doc = {"schema": SCHEMA, "decoding": model.DECODING, "summary": summary, "probes": probes}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    return doc
