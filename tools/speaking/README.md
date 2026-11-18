# Speaking model: local French transcription (research, training, service)

Turns a learner's recorded French answer into a **draft transcript** that the
learner checks and corrects before FLH gives feedback. Runs on CPU, offline,
on the same machine as FLH; audio never leaves it.

What it is **not**: a pronunciation or fluency scorer, a grader, a public
service or an autostarted daemon. The transcript is a draft: Whisper tends to
smooth over learner mistakes, so the learner's confirmation stays required.

Evidence and decisions: [`docs/validation/SPEAKING-MODEL-V1.md`](../../docs/validation/SPEAKING-MODEL-V1.md).
Contract (service API, statuses, errors, retention): [`CONTRACT.md`](CONTRACT.md).

## Layout

| Path | What |
|---|---|
| `flh_speaking/pins.py` | pinned model revisions and dataset files (size + SHA-256 or git blob) |
| `flh_speaking/fetch.py` | downloads and verifies pinned files (public, ungated, no credentials) |
| `flh_speaking/mls.py`, `prepare.py` | speaker- and book-disjoint MLS French subset + FLEURS fr_fr dev; decoded once to 16 kHz mono PCM16; sealed manifest with leakage checks |
| `flh_speaking/audio.py` | the one audio convention (PyAV/FFmpeg, in memory) and signal statistics |
| `flh_speaking/model.py` | Whisper decoding policy `flh_speaking_transcribe_v1` with abstention rules |
| `flh_speaking/textnorm.py`, `evaluate.py`, `compare.py`, `probes.py` | WER/CER, cluster bootstrap, breakdowns, paired comparison, acceptance rule, robustness probes |
| `flh_speaking/train.py`, `sagemaker_entry.py` | resumable fine-tuning; SageMaker wrapper |
| `flh_speaking/service.py`, `deployment.py` | local HTTP service and its deployment identity |
| `configs/` | training configs (`smoke-tiny`, `pilot-base-encoder`, `ablation-base-full`) |
| `aws/` | SageMaker pilot template, IAM policy, bounded renderer, cost and launch commands (not launched) |
| `fixtures/frontend/` | real backend responses from the local end-to-end run |
| `tests/` | standard-library tests (host) and image tests (audio, rules, service, training) |

## Build and run (offline)

```sh
cd tools/speaking
docker build --build-arg TORCH_INDEX=cpu -t flh-speaking:cpu .     # needs network once (pip)
W=$HOME/flh-speaking-work                                          # outside the repository
python3 -m flh_speaking fetch --dest $W/sources --what whisper-base mls fleurs   # network once; verified
# Every later step runs with no network, 2 GB, 4 CPUs:
RUN="docker run --rm --oom-score-adj 1000 --network none --memory 1536m --memory-swap 1536m --cpus 4 --user $(id -u):$(id -g) -e HOME=/tmp -v $W/sources:/sources:ro"
$RUN -v $W/data:/data flh-speaking:cpu prepare --sources /sources --out /data
$RUN -v $W/data:/data:ro -v $W/out:/out flh-speaking:cpu evaluate \
    --model /sources/openai/whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb --data /data --split test --out /out/base-test.json
```

Training (resumable: rerun the same command after an interruption):

```sh
$RUN -v $W/data:/data:ro -v $PWD/configs:/configs:ro -v $W/train:/out flh-speaking:cpu train \
    --config /configs/pilot-base-encoder.json --data /data \
    --base /sources/openai/whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb --out /out
```

Service (loopback only; publish the port on 127.0.0.1):

```sh
docker run --rm --oom-score-adj 1000 -p 127.0.0.1:8765:8765 --memory 1536m --cpus 4 -v $W/sources:/sources:ro \
    flh-speaking:cpu serve --model /sources/openai/whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb --host 0.0.0.0 --port 8765
```

`--host` accepts loopback and private addresses. The unspecified address
(`0.0.0.0`, all interfaces) is accepted only inside a container, where the
host's `-p 127.0.0.1:8765:8765` mapping is what keeps the service off the LAN;
outside a container it is refused. `GET /manifest` gives
the `deployment_id` to set as `SPEAKING_TRANSCRIPTION_MODEL`; `CONTRACT.md` §6
has the FLH settings.

## Tests

```sh
cd tools/speaking && python3 -B -m unittest discover -s tests -t tests          # host: text, selection, pins
docker run --rm --network none -e FLH_SPEAKING_TOKENIZER_DIR=/tok \
    -v $W/sources/openai/whisper-tiny/169d4a4341b33bc18d8881c4b69c2e104e1cc0af:/tok:ro \
    -v $PWD:/src:ro -w /src --entrypoint python3 flh-speaking:cpu -B -m unittest discover -s tests -t tests
```

## Retention

- The service keeps nothing: audio is decoded in memory, released after the
  response, and never written, cached or logged; transcripts are not logged.
- FLH stores audio **metadata** only (type, size, SHA-256, duration) and the
  transcripts the learner confirms (Speaking v1, migration 018).
- Training data here is public (MLS, FLEURS; CC-BY-4.0) and lives outside the
  repository. Learner recordings are never used for training: FLH does not
  store them, and collecting them would need an explicit owner decision with
  consent and a retention limit (see the validation memo).
