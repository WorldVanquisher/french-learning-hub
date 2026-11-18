"""In-memory audio decoding to the model's convention: 16 kHz, mono, float32 in [-1, 1].

One function, ``decode``, is used by data preparation, evaluation, training and
the service, so every path converts audio the same way (PyAV/FFmpeg resampler,
channels down-mixed by FFmpeg's ``mono`` layout). Audio never touches the file
system here: the input is bytes and the output is a NumPy array.

Errors are ``AudioError`` with a stable ``code`` and a message that never
contains audio content.
"""

from __future__ import annotations

import io
import math
import wave
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16_000
CONVENTION = "pcm_f32le/16000Hz/mono/ffmpeg-swr-v1"

# Container names as PyAV reports them, by accepted family.
CONTAINERS = {
    "matroska,webm": "webm",
    "mov,mp4,m4a,3gp,3g2,mj2": "mp4",
    "mp3": "mp3",
    "wav": "wav",
    "flac": "flac",
    "ogg": "ogg",
}
SERVICE_FAMILIES = ("webm", "mp4", "mp3", "wav")  # what FLH's Go backend accepts
DATA_FAMILIES = ("flac", "wav")  # what the pinned datasets contain


class AudioError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Decoded:
    samples: np.ndarray  # float32, mono, SAMPLE_RATE
    family: str
    source_rate: int
    source_channels: int
    source_codec: str

    @property
    def seconds(self) -> float:
        return len(self.samples) / SAMPLE_RATE


def sniff(data: bytes) -> str | None:
    """Container family from magic bytes (None when unknown)."""
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return "mp4"
    if data[:4] == b"fLaC":
        return "flac"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:3] == b"ID3" or (len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "mp3"
    return None


def decode(data: bytes, *, max_seconds: float, allowed: tuple[str, ...]) -> Decoded:
    """Decode bytes to 16 kHz mono float32, refusing more than ``max_seconds``.

    The duration bound is enforced while decoding, so a small compressed file
    that expands to hours of audio is refused after ``max_seconds`` of work.
    """
    import av  # imported lazily so text-only tools do not need PyAV

    if not data:
        raise AudioError("empty_audio", "the audio is empty")
    family = sniff(data)
    if family is None or family not in allowed:
        raise AudioError("unsupported_audio", f"audio container is not one of {', '.join(allowed)}")
    limit = int(math.ceil(max_seconds * SAMPLE_RATE))
    chunks: list[np.ndarray] = []
    total = 0
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            if CONTAINERS.get(container.format.name) != family:
                raise AudioError("unsupported_audio", "audio container does not match its content")
            streams = [s for s in container.streams if s.type == "audio"]
            if not streams:
                raise AudioError("no_audio_stream", "the file has no audio stream")
            stream = streams[0]
            src_rate = int(stream.codec_context.sample_rate or 0)
            src_channels = len(stream.codec_context.layout.channels) if stream.codec_context.layout else 0
            codec = stream.codec_context.name
            resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)

            def take(frames):
                nonlocal total
                for fr in frames:
                    arr = fr.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                    total += arr.size
                    if total > limit:
                        raise AudioError("audio_too_long", f"audio is longer than {max_seconds:g} s")
                    chunks.append(arr)

            for frame in container.decode(stream):
                take(resampler.resample(frame))
            take(resampler.resample(None))
    except AudioError:
        raise
    except Exception as exc:  # PyAV/FFmpeg errors: never echo content
        raise AudioError("undecodable_audio", f"audio could not be decoded ({type(exc).__name__})") from None
    if total == 0:
        raise AudioError("empty_audio", "the audio decodes to no samples")
    samples = np.concatenate(chunks) if len(chunks) > 1 else chunks[0].copy()
    if not np.all(np.isfinite(samples)):
        raise AudioError("undecodable_audio", "decoded audio has non-finite samples")
    np.clip(samples, -1.0, 1.0, out=samples)
    return Decoded(samples, family, src_rate, src_channels, codec)


def to_wav_pcm16(samples: np.ndarray) -> bytes:
    """16 kHz mono PCM16 WAV bytes (deterministic: no metadata chunks)."""
    pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def read_wav_pcm16(data: bytes) -> np.ndarray:
    """Inverse of ``to_wav_pcm16`` for prepared data (refuses anything else)."""
    with wave.open(io.BytesIO(data), "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, SAMPLE_RATE):
            raise AudioError("unsupported_audio", "prepared audio must be 16 kHz mono PCM16")
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return (pcm.astype(np.float32) / 32767.0).clip(-1.0, 1.0)


FRAME = 480  # 30 ms at 16 kHz
SOUND_DBFS = -70.0


def frame_db(samples: np.ndarray) -> np.ndarray:
    n = len(samples) // FRAME
    if n == 0:
        return np.full(1, -120.0)
    fr = samples[: n * FRAME].reshape(n, FRAME).astype(np.float64)
    rms = np.sqrt(np.mean(fr * fr, axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-6))


def quality(samples: np.ndarray) -> dict:
    """Cheap, deterministic signal statistics used for abstention and evaluation buckets.

    sound_seconds: 30 ms frames above -70 dBFS (absolute). This is the only
      quantity the abstention gate uses: it catches digital or near-digital
      silence and nothing else (quiet but valid recordings around -63 dBFS RMS
      exist in FLEURS). Noise is left to the model's no-speech rule.
    voiced_seconds: frames above -45 dBFS and at least 12 dB above the 10th
      percentile frame level. Informational only: on a steady noisy recording
      it undercounts speech (a first draft gated on it and wrongly abstained on
      a whole noisy test speaker).
    snr_db: mean voiced level minus the 10th-percentile level (rough estimate).
    """
    db = frame_db(samples)
    floor = float(np.percentile(db, 10))
    voiced = (db > -45.0) & (db > floor + 12.0)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    rms_db = float(20.0 * np.log10(max(float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))), 1e-6))) if samples.size else -120.0
    return {
        "seconds": round(len(samples) / SAMPLE_RATE, 3),
        "sound_seconds": round(float((db > SOUND_DBFS).sum()) * FRAME / SAMPLE_RATE, 3),
        "voiced_seconds": round(float(voiced.sum()) * FRAME / SAMPLE_RATE, 3),
        "rms_dbfs": round(rms_db, 2),
        "peak": round(peak, 4),
        "clipped_ratio": round(float(np.mean(np.abs(samples) >= 0.999)) if samples.size else 0.0, 5),
        "snr_db": round(float(db[voiced].mean() - floor), 2) if voiced.any() else 0.0,
    }
