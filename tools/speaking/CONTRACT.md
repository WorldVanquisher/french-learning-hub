# Speaking transcription contract (v1)

| Identifier | Value |
|---|---|
| Service response | `flh_speaking_transcription_v1` (`flh_speaking/service.py`) |
| Decoding policy | `flh_speaking_transcribe_v1` (`flh_speaking/model.py`) |
| Deployment manifest | `flh_speaking_deployment_manifest_v1` (`GET /manifest`, `python -m flh_speaking manifest`) |
| Audio convention | `pcm_f32le/16000Hz/mono/ffmpeg-swr-v1` (`flh_speaking/audio.py`), the same in data preparation, training, evaluation and the service |
| Frontend ↔ backend | **unchanged**: the existing Speaking v1 endpoints (`docs/ARCHITECTURE.md` §4.7) |

## 1. Who talks to whom

```text
browser (records; sends audio only on an explicit "Transcribe" click)
  └─ POST /speaking/takes/{id}/transcriptions   {audio_base64, audio_mime}   (existing FLH API)
       └─ Go SpeakingService → speaking.Transcriber (OpenAI-style client, provider local)
            └─ POST {SPEAKING_TRANSCRIPTION_BASE_URL}/audio/transcriptions   multipart: file, model, response_format=json
                 └─ flh_speaking service (this contract), loopback or private address only
```

The frontend contract does not change. The backend still answers with the
same transcription view (`status`, `failure_code`, `transcriber`, `text`), and
the learner still confirms or corrects the text before any feedback.
`fixtures/frontend/` holds real backend responses captured from the local
end-to-end run, for frontend development.

## 2. Service request

`POST /v1/audio/transcriptions` (also `/audio/transcriptions`), `multipart/form-data`:

| Field | Required | Rule |
|---|---|---|
| `file` | yes | webm, mp4/m4a, mp3 or wav (checked by magic bytes **and** by the decoder), at most 8 MiB and 120 s of audio |
| `model` | yes | must equal the service's `deployment_id` (else 400 `unknown_model`) |
| `response_format` | no | `json` only |
| `language` | no | `fr` only; the service always transcribes French |
| anything else (`prompt`, `temperature`, …) | — | refused (400 `invalid_request`): no prompt can steer the transcript |

An `Authorization` header is accepted and ignored; it is never logged.

## 3. Service response (HTTP 200)

```json
{
  "text": "Bonjour, je voudrais réserver une table pour deux.",
  "flh": {
    "schema": "flh_speaking_transcription_v1",
    "status": "transcribed",
    "warnings": [],
    "language": {"p_fr": 0.98, "top": "fr", "p_top": 0.98},
    "duration_s": 4.2, "sound_s": 3.9, "windows": 1,
    "audio_sha256": "<sha256 of the uploaded bytes>",
    "deployment_id": "whisper-base@e37978b90ca9/flh_speaking_transcribe_v1/cpu-fp32/<16 hex>",
    "timing": {"decode_s": 0.02, "model_s": 0.61}
  }
}
```

FLH's Go client reads `text`, and checks that `flh.deployment_id` equals its
configured `SPEAKING_TRANSCRIPTION_MODEL`. `status`:

| `status` | `text` | Meaning | What FLH stores today |
|---|---|---|---|
| `transcribed` | non-empty | a machine draft the learner must check | a completed transcription |
| `no_speech` | `""` | silence or near-silence (model not run), every window judged silent, or only known phantom phrases | a failed transcription, `failure_code` `invalid_output` ("no usable transcript"); the learner types |
| `not_french` | `""` | language identification: P(fr) < 0.2 and another language > 0.6 | same as `no_speech` |

`warnings` (the text is still returned): `low_confidence`, `repetitive_output`,
`possibly_not_french`, `phantom_phrase_removed`. The Go client ignores them today.

Known limits of v1, measured in the validation memo:
- `not_french` also fires on 4.7% of accented French (short takes), so a learner
  may be asked to type a valid take (owner decision D3: warning-only in v2).
- Strong background noise degrades the draft quickly.
- Homophones (ces/ses, a/à, leur/leurs) are the model's guess.
FLH's `local` provider (§6) records the provenance; `status` and `warnings`
are not stored yet.

## 4. Errors (never HTTP 200)

`{"error": {"type": <code>, "message": <text without audio or transcript content>}}`

| HTTP | `type` | When |
|---|---|---|
| 400 | `invalid_request`, `unknown_model` | bad form, unsupported field, wrong `model` |
| 411 | `length_required` | no `Content-Length` |
| 413 | `request_too_large`, `audio_too_large` | over the byte limits (refused before reading the body) |
| 415 | `unsupported_audio`, `invalid_request` | not multipart; container not accepted or not matching its content |
| 422 | `empty_audio`, `undecodable_audio`, `no_audio_stream`, `audio_too_long` | the audio cannot be used; the duration bound is enforced while decoding |
| 429 | `busy` | one inference runs and the wait queue (default 2) is full |
| 503 | `not_ready` | model still loading or warming, or startup failed |
| 504 | `timeout` | the request passed its deadline: `limits.inference_timeout_s` in `GET /manifest` (default 50 s, `--inference-timeout`), counted from arrival with the queue wait included, so FLH (timeout 60 s) gets this definite answer before it gives up |

FLH maps every non-200 answer to `unavailable` (a definite outcome, not
"unknown"). A dropped connection after sending is FLH's existing "unknown
outcome" case.

## 5. Retries, duplicates, retention

- The service never retries and keeps no state between requests: no cache, no
  de-duplication, no audio or text on disk or in logs. The only thing created in
  the container is an empty torch cache directory, at import. Audio is decoded in
  memory and released after the response. Logs hold method, path, status,
  duration, result code, audio seconds and model seconds only.
- Decoding is deterministic (greedy, CPU, float32), so the same bytes give the
  same text. A client that retries re-runs inference; `audio_sha256` lets it
  match a response to the bytes it sent.
- Duplicate submissions are settled by FLH, not the service: the backend's
  `Idempotency-Key` replays the stored result without a second call (verified
  end-to-end; `docs/validation/SPEAKING-MODEL-V1.md` §9).

## 6. Configuring FLH: `SPEAKING_TRANSCRIPTION_PROVIDER=local`

```sh
SPEAKING_TRANSCRIPTION_PROVIDER=local
SPEAKING_TRANSCRIPTION_MODEL=<deployment_id from GET /manifest>
SPEAKING_TRANSCRIPTION_BASE_URL=http://127.0.0.1:8765/v1   # as FLH's process reaches the service
SPEAKING_TRANSCRIPTION_TIMEOUT=60                           # seconds (default 60)
```

- FLH sends no API key, and the provider runs beside `SPEAKING_PROVIDER=openai`:
  feedback keeps `OPENAI_*`, transcription uses only these four settings.
- Timeouts nest: the service's `inference_timeout_s` (50 s, counted from
  arrival) < `SPEAKING_TRANSCRIPTION_TIMEOUT` (60 s) < `HTTP_WRITE_TIMEOUT`
  (the daily template's 75 s). FLH then always gets a definite answer, and the
  browser always gets FLH's. The request deadline is the longer of
  `OPENAI_TIMEOUT` and `SPEAKING_TRANSCRIPTION_TIMEOUT`, plus 30 s.
- Stored provenance: `local:<deployment_id>:speaking_transcription_v1`, also
  shown in `GET /speaking/prompts` (`providers.transcription.name`) and logged
  at startup with the timeout and the request deadline. Every answer must name
  the same `flh.deployment_id`: a service restarted with other weights cannot
  store text under the old name.
- In Docker Compose, `127.0.0.1` is the FLH container itself. Compose does not
  forward the two new variables yet; the proposed change is
  `docs/validation/SPEAKING-LOCAL-PROVIDER/release-lane-handoff.patch`.

How each service answer is stored (`docs/validation/SPEAKING-LOCAL-PROVIDER.md`
has the real-inference evidence):

| Service answer | FLH `failure_code` | Outcome and next click |
|---|---|---|
| connection refused (not started) | `provider_unavailable` | failed; the next click is sent |
| 503 `not_ready`, 429 `busy`, 400 `unknown_model`, 504 `timeout`, other 5xx | `provider_unavailable` | failed; the next click is sent |
| connection closed without an answer (for example a restart) | `provider_unavailable` | failed: the service bills and keeps nothing |
| 413, 415 or 422 (audio refused: too long, undecodable, empty) | `invalid_output` | failed; sending the same audio again cannot help |
| 200 with `no_speech` or `not_french` (empty `text`) | `invalid_output` | failed; the learner types the transcript |
| an answer naming another `deployment_id` | `provider_unavailable` | failed; nothing is stored as text |
| no answer within `SPEAKING_TRANSCRIPTION_TIMEOUT` | `provider_timeout` | unknown: the next click needs `confirm_unknown_retry` |

`SPEAKING_TRANSCRIPTION_PROVIDER=openai` with `OPENAI_BASE_URL` pointed at the
service also works, but it stores `openai:` provenance and shares `OPENAI_*`
with feedback. Use `local`.

## 7. Readiness and identity

| Endpoint | Meaning |
|---|---|
| `GET /healthz` | 200 while the process runs (liveness only) |
| `GET /readyz` | 503 `starting`/`loading`/`warming`/`failed`; 200 `ready` only after a warm-up inference through the real encoder and decoder succeeded |
| `GET /manifest` | deployment manifest: model files and their SHA-256, pinned revision or fine-tuning inputs, decoding thresholds, audio convention, code SHA-256, runtime versions, limits |
| `GET /metrics` | request counters (no content) |

Anything that can change a transcript changes `deployment_id`: other weights,
thresholds, decoding code, audio code or library versions.
