# Frontend fixtures: real FLH Speaking responses with the local transcription service

Captured from the end-to-end run (`tools/speaking/scripts/e2e_flh.py`, provider
`local`, i.e. with the proposed Go patch applied; with today's code the only
difference is the `transcriber` prefix `openai:`). The FLH server ran with a
fresh database, the whisper-base service on loopback, and a webm/Opus take made
from a frozen MLS test utterance (CC-BY-4.0). No learner data.

| File | Request | HTTP |
|---|---|---|
| `transcription-created.json` | `POST /speaking/takes/{id}/transcriptions` (new `Idempotency-Key`) | 201 |
| `transcription-replayed.json` | the same request and key again (no second model call; header `Idempotency-Replayed: true`) | 200 |
| `transcription-request.json` | `GET /speaking/transcription-requests/{key}` | 200 |
| `transcript-confirmed.json` | `POST /speaking/takes/{id}/transcripts` with the machine text | 201 |
| `transcription-no-speech.json` | a 3 s silent take: the service abstains, FLH stores `failure_code: invalid_output` | 502 |
| `transcription-service-down.json` | the service stopped: `failure_code: provider_unavailable` | 502 |

The response shapes are the existing Speaking v1 API (`docs/ARCHITECTURE.md`
§4.7); nothing in the frontend contract changes. Timestamps and ids come from
that run.
