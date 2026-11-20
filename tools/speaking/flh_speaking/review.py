"""Speaking Lab review: silence rule, reviewer records, retry suggestions (standard library only).

* ``silence`` is an explicit, configurable local rule. It counts 30 ms frames
  above a dBFS threshold; the defaults equal the service's sound gate
  (``audio.SOUND_DBFS`` -70 dBFS, ``model.MIN_SOUND_SECONDS`` 0.3 s). The
  result is a measurement under a stated rule, not a model judgement.
* Reviewer records (``flh_speaking_lab_review_v1``, JSONL) are validated
  strictly. ``invalid`` and ``retry`` remove a sample from the aggregates,
  listed with their reason. ``correct`` adds a corrected text with its source
  next to the original hypothesis, which is never changed. ``accept`` records a
  pass.
* ``suggest_retry`` turns an abstention into an action for the learner when
  the cause is known.
"""

from __future__ import annotations

import io
import json
import math
import struct
import wave

REVIEW_SCHEMA = "flh_speaking_lab_review_v1"
ACTIONS = {"accept": "the result was checked and passes",
           "invalid": "the sample cannot be used (for example a wrong recording); it leaves the aggregates",
           "retry": "the take should be recorded again; it leaves the aggregates until then",
           "correct": "a corrected transcript for one result, kept beside the original"}
REQUIRED = {"schema", "id", "action", "reason", "reviewer"}
OPTIONAL = {"label", "correction", "source"}
SILENCE_RULE = {"threshold_dbfs": -70.0, "min_sound_seconds": 0.3, "frame_ms": 30}


def silence(data: bytes, threshold_dbfs: float = SILENCE_RULE["threshold_dbfs"],
            min_sound_seconds: float = SILENCE_RULE["min_sound_seconds"], frame_ms: int = SILENCE_RULE["frame_ms"]) -> dict:
    """Measured: seconds of sound under the stated rule. ``silent`` is the rule's verdict."""
    with wave.open(io.BytesIO(data), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("the silence rule reads 16-bit PCM WAV")
        rate, ch, frames = w.getframerate(), w.getnchannels(), w.readframes(w.getnframes())
    x = struct.unpack(f"<{len(frames) // 2}h", frames)
    if ch > 1:
        x = [sum(x[i:i + ch]) / ch for i in range(0, len(x), ch)]
    step = max(1, rate * frame_ms // 1000)
    loud = 0
    for k in range(0, len(x) - step + 1, step):
        fr = x[k:k + step]
        r = math.sqrt(sum(v * v for v in fr) / len(fr)) / 32768.0
        if 20 * math.log10(max(r, 1e-6)) > threshold_dbfs:
            loud += 1
    sound = round(loud * step / rate, 3)
    return {"kind": "measured", "seconds": round(len(x) / rate, 3), "sound_seconds": sound, "silent": sound < min_sound_seconds,
            "rule": {"threshold_dbfs": threshold_dbfs, "min_sound_seconds": min_sound_seconds, "frame_ms": frame_ms}}


def validate_record(rec: dict) -> list[str]:
    """Problems with one reviewer record; empty when it is accepted."""
    if not isinstance(rec, dict):
        return ["a record must be a JSON object"]
    bad = []
    if rec.get("schema") != REVIEW_SCHEMA:
        bad.append(f"schema must be {REVIEW_SCHEMA}")
    missing, unknown = REQUIRED - set(rec), set(rec) - REQUIRED - OPTIONAL
    if missing:
        bad.append(f"missing {sorted(missing)}")
    if unknown:
        bad.append(f"unknown fields {sorted(unknown)}")
    if rec.get("action") not in ACTIONS:
        bad.append(f"action must be one of {sorted(ACTIONS)}")
    for k in ("id", "reason", "reviewer"):
        if k in rec and (not isinstance(rec[k], str) or not rec[k].strip()):
            bad.append(f"{k} must be a non-empty string")
    if rec.get("action") == "correct":
        for k in ("label", "correction", "source"):
            if not isinstance(rec.get(k), str) or not rec[k].strip():
                bad.append(f"a correction needs a non-empty {k!r}")
    elif "correction" in rec:
        bad.append("only action 'correct' carries a correction")
    return bad


def read_review(path: str) -> dict:
    """{id: [records]}; any invalid record refuses the whole file (ValueError naming its line)."""
    out: dict = {}
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            bad = validate_record(rec)
            if bad:
                raise ValueError(f"review line {n}: {'; '.join(bad)}")
            out.setdefault(rec["id"], []).append(rec)
    for i, recs in out.items():
        if len({r["action"] for r in recs if r["action"] in ("invalid", "retry", "accept")}) > 1:
            raise ValueError(f"review: {i!r} has conflicting accept/invalid/retry records")
    return out


SUGGESTIONS = {
    "no_speech": "Record again closer to the microphone, in a quieter place: almost no speech was heard.",
    "silence": "Record again and check the microphone: the take is silent under the stated rule.",
    "not_french": "Answer in French: the transcriber detected another language. Or type the answer.",
}


def suggest_retry(status: str | None) -> dict:
    """An actionable suggestion for an abstention, or a generic one when the cause is unknown."""
    if status in SUGGESTIONS:
        return {"cause": status, "kind": "supplied", "suggestion": SUGGESTIONS[status]}
    return {"cause": "unknown", "kind": "heuristic", "suggestion": "Record again, or type what you said."}
