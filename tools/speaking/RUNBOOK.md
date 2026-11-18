# Local Speaking transcription: build, deploy, check, roll back

For the operator. The service is optional: with
`SPEAKING_TRANSCRIPTION_PROVIDER=disabled`, the default, learners type their
transcripts. Contract: [`CONTRACT.md`](CONTRACT.md). Evidence:
`docs/validation/SPEAKING-LOCAL-PROVIDER.md`. Nothing here touches AWS, and
nothing autostarts.

## 1. What a deployment is

A deployment is identified by its `deployment_id`, for example
`whisper-base@e37978b90ca9/flh_speaking_transcribe_v1/cpu-fp32/ac92e8688ef9e17b`.
The final hash covers:
- the model files (SHA-256, checked against `flh_speaking/pins.py`);
- the decoding policy and its thresholds;
- the audio convention;
- the code of `audio.py`, `model.py`, `service.py` and `deployment.py`;
- the versions of Python, torch, transformers, numpy and PyAV.

Anything that can change a transcript changes it. Limits such as timeouts and
queue size are published in `GET /manifest` but not hashed.

| Input | Pinned by |
|---|---|
| Base image | `python:3.12-slim@sha256:6c4dd321…` (Dockerfile) |
| Python packages | `requirements-cpu.lock` / `requirements-gpu.lock`: every package, version and SHA-256 (`pip --require-hashes`); `requirements.txt` lists the direct ones |
| Model weights | `pins.py` (repository revision, size, SHA-256 of every file); `fetch` and `check` verify them |
| Code | the files of this directory (hashed into `deployment_id`) |

Identities of this tree (CPU image built from `requirements-cpu.lock`):

| Model | `deployment_id` |
|---|---|
| whisper-base | `whisper-base@e37978b90ca9/flh_speaking_transcribe_v1/cpu-fp32/ac92e8688ef9e17b` |
| whisper-small | `whisper-small@973afd24965f/flh_speaking_transcribe_v1/cpu-fp32/d20b5c67adbff447` |

## 2. Build and verify (network once)

```sh
cd tools/speaking
W=$HOME/flh-speaking-work                                   # outside the repository
TAG=flh-speaking:cpu-$(date -u +%Y%m%d)
docker build --build-arg TORCH_INDEX=cpu -t $TAG .
python3 -B -m flh_speaking fetch --dest $W/sources --what whisper-base whisper-small    # or: check
MODEL=/sources/openai/whisper-small/973afd24965f72e36ca33b3055d56a652f456b4d          # or whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb
docker run --rm --network none --memory 1g -v $W/sources:/sources:ro $TAG manifest --model $MODEL \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['deployment_id'])"
```

The printed `deployment_id` must equal §1's table for this tree. A different one
means the code, a library or the weights differ. Find out which before serving
it.

## 3. Supported configuration

| Setting | whisper-small (recommended) | whisper-base (low memory) |
|---|---|---|
| Container memory (`--memory` = `--memory-swap`) | 2g (measured peak about 1.4 GiB) | 1g (measured peak about 0.9 GiB) |
| CPUs / threads | `--cpus 4`, `serve --threads 4` (default) | same |
| Latency, CPU (10 s / 120 s take) | 2.5 s / 17.3 s | 0.8 s / 5.6 s |
| Bind | `-p 127.0.0.1:8765:8765` with `--host 0.0.0.0` inside the container, or a private address; never public | same |
| Service deadline | `--inference-timeout 50` (default; counted from arrival, queue included) | same |
| Queue | `--max-waiting 2` (default); a further request gets 429 `busy` | same |
| FLH | `SPEAKING_TRANSCRIPTION_PROVIDER=local`, `SPEAKING_TRANSCRIPTION_MODEL=<deployment_id>`, `SPEAKING_TRANSCRIPTION_BASE_URL=http://127.0.0.1:8765/v1`, `SPEAKING_TRANSCRIPTION_TIMEOUT=60`, `HTTP_WRITE_TIMEOUT=75` | same |

Timeouts nest: service 50 s < FLH 60 s < HTTP write 75 s, so every layer gets a
definite answer from the one below it.

Not supported yet:
- FLH in Docker Compose: `127.0.0.1` is the FLH container itself, and Compose
  does not forward the two new variables. See
  `docs/validation/SPEAKING-LOCAL-PROVIDER/release-lane-handoff.patch`.
- GPUs, more than one service instance, and any public exposure.

## 4. Deploy

```sh
docker run -d --name flh-speaking --oom-score-adj 1000 --restart no \
  -p 127.0.0.1:8765:8765 --memory 2g --memory-swap 2g --cpus 4 --user 10001 \
  -v $W/sources:/sources:ro $TAG serve --model $MODEL --host 0.0.0.0 --port 8765
until curl -fsS http://127.0.0.1:8765/readyz; do sleep 1; done          # loading → warming → ready (about 5-10 s)
curl -fsS http://127.0.0.1:8765/manifest | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['deployment_id'], d['limits'])"
```

Set the FLH settings from §3 with that exact `deployment_id`, then restart FLH:
the settings are read at startup. Its log must show
`speaking transcription: local deployment <id>, timeout 1m0s, request deadline 1m30s`.

## 5. Check

- `GET /speaking/prompts` → `providers.transcription.name` is
  `local:<deployment_id>:speaking_transcription_v1`.
- Record a short take and send it once; the transcription's `transcriber`
  carries the same name. Silence returns "no usable transcript" (`invalid_output`).
- A repeatable end-to-end check, against a disposable FLH and database:
  `tools/speaking/scripts/verify_local_provider.py` (its docstring has the
  commands). It never touches the daily instance.
- `GET /metrics` on the service shows these counters, and never any content:
  - `requests`, `transcribed`, `abstained`;
  - `refused`, `busy`, `timeouts`, `errors`.

## 6. Upgrade (new weights, code or libraries)

1. Build and start the new deployment on another port, for example 8766; check §2 and §4.
2. Point FLH at it: set the new `SPEAKING_TRANSCRIPTION_MODEL` and
   `SPEAKING_TRANSCRIPTION_BASE_URL`, then restart FLH.
3. Stop the old container.

Transcriptions already stored keep the provenance they were made with. Until FLH
is reconfigured, it refuses answers from the new deployment (they name another
`deployment_id`), so a half-done switch cannot mislabel a transcript.

## 7. Roll back

| To | Do | Data |
|---|---|---|
| The previous deployment | Start the previous image tag and model as in §4 (keep the tag; `docker image ls flh-speaking`). Set `SPEAKING_TRANSCRIPTION_MODEL` and `_BASE_URL` back to their recorded values. Restart FLH. | nothing to migrate |
| No local transcription | `SPEAKING_TRANSCRIPTION_PROVIDER=disabled` (learners type) or `openai`. Restart FLH. Then `docker rm -f flh-speaking`. | stored transcriptions and their provenance stay |

After either, repeat the §5 check: the provider name must match what was intended.

## 8. Failures and what they look like

The table of FLH failure states is in `CONTRACT.md` §6. In short:
- **Not running or still loading:** "the provider was unavailable"; the next click is sent.
- **Refused audio, silence, or not French:** "the answer was not usable"; the learner types.
- **FLH timeout:** outcome unknown; the next click asks for confirmation.

If memory runs out, the kernel kills the container first (`--oom-score-adj 1000`).
FLH then reports "unavailable" until the container is started again; it is not
restarted automatically.

## 9. Stop and clean up

```sh
docker rm -f flh-speaking                  # the service keeps nothing: no audio, no transcript, no cache
docker image ls flh-speaking               # keep the current and previous tags; remove older ones
```
