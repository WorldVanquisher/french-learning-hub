"""A synthetic client for ``flh_speaking_transcription_v1`` responses (standard library only).

It checks a 200 response the way FLH's Go client relies on it. Required, as
the Go client reads them (``internal/speaking/transcribe.go``):
- ``text``, a string;
- ``flh.deployment_id``, which must equal the configured deployment.

Optional, because an older service or a smaller build may omit them:
``flh.schema``, ``status``, ``warnings``, ``language``, ``duration_s``,
``sound_s``, ``windows``, ``audio_sha256`` and ``timing``. When present, each
must have its documented type. Error answers must be
``{"error": {"type": str, "message": str}}``.
"""

from __future__ import annotations

SCHEMA = "flh_speaking_transcription_v1"
STATUSES = {"transcribed", "no_speech", "not_french"}
OPTIONAL = {"schema": str, "status": str, "warnings": list, "language": dict, "duration_s": (int, float), "sound_s": (int, float),
            "windows": int, "audio_sha256": str, "timing": dict}


def check_response(doc, deployment_id: str | None = None) -> dict:
    """{"ok": bool, "problems": [...], "omitted_optional": [...]} for one 200 body."""
    problems, omitted = [], []
    if not isinstance(doc, dict):
        return {"ok": False, "problems": ["the body is not a JSON object"], "omitted_optional": []}
    if not isinstance(doc.get("text"), str):
        problems.append("text must be a string")
    flh = doc.get("flh")
    if not isinstance(flh, dict):
        problems.append("flh block missing: the Go client refuses an answer that names no deployment")
        flh = {}
    dep = flh.get("deployment_id")
    if not isinstance(dep, str) or not dep:
        problems.append("flh.deployment_id must be a non-empty string")
    elif deployment_id is not None and dep != deployment_id:
        problems.append("flh.deployment_id differs from the configured deployment (the Go client refuses it)")
    for k, t in OPTIONAL.items():
        if k not in flh:
            omitted.append(k)
        elif not isinstance(flh[k], t):
            problems.append(f"flh.{k} has the wrong type")
    if "schema" in flh and flh["schema"] != SCHEMA:
        problems.append(f"flh.schema is not {SCHEMA}")
    if "status" in flh and flh["status"] not in STATUSES:
        problems.append(f"flh.status {flh['status']!r} is not one of {sorted(STATUSES)}")
    if flh.get("status") in ("no_speech", "not_french") and doc.get("text"):
        problems.append("an abstention must carry empty text")
    return {"ok": not problems, "problems": problems, "omitted_optional": omitted}


def check_error(doc) -> list[str]:
    e = doc.get("error") if isinstance(doc, dict) else None
    if not isinstance(e, dict) or not isinstance(e.get("type"), str) or not isinstance(e.get("message"), str):
        return ["an error body must be {\"error\": {\"type\": str, \"message\": str}}"]
    return []
