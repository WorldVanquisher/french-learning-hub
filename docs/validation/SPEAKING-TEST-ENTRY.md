# Speaking tests: dependency-enabled entry point

Scope: `tools/speaking` tests and docs only. CI YAML belongs to the release
lane; this note gives them the command and its resource needs.
Entry point: `tools/speaking/scripts/run_tests.py`. Usage:
`tools/speaking/README.md` § Tests.

## Skips before (item 1, 2)

Host: Python 3.14 with no NumPy, PyAV or torch. Command:
`cd tools/speaking && python3 -B -m unittest discover -s tests -t tests -v`.
Result: 43 tests, OK, 28 skipped, exit 0.

| Class | Tests | Skip reason as printed | Needs |
|---|---|---|---|
| `test_audio_service.Audio` | 5 | needs numpy and av (run in the image) | NumPy, PyAV |
| `test_audio_service.Rules` | 6 | needs numpy | NumPy, PyAV (the label understated it; now "needs numpy and av") |
| `test_audio_service.Service` | 8 | needs numpy and av | NumPy, PyAV |
| `test_robustness.Robustness` | 3 | needs numpy and av | NumPy, PyAV |
| `test_robustness.Punctuated` | 1 | needs numpy and av | NumPy, PyAV |
| `test_train.Training` | 5 | needs torch, transformers and FLH_SPEAKING_TOKENIZER_DIR | torch, transformers, and a fixture: the pinned whisper-tiny `config.json` and tokenizer files |

- 23 skips are missing dependencies only (NumPy and PyAV).
- 5 are missing dependencies plus a data fixture.
- None is a platform skip or an intentional permanent skip.
- The fixture holds no weights: the tests build a tiny random Whisper from its
  config, so `fetch --no-weights` (4.3 MB) is enough.

## After (items 4, 11–13)

| Run | Tests | Skipped | Exit |
|---|---|---|---|
| Host, offline: `python3 -B scripts/run_tests.py` (or plain `unittest discover`) | 47 | 28: 23 "needs numpy and av", 5 "needs torch, transformers and FLH_SPEAKING_TOKENIZER_DIR" | 0 |
| Host, `--require-deps` | — (not run) | — | 2: "MISSING: module numpy; module av; module torch; module transformers; FLH_SPEAKING_TOKENIZER_DIR …" |
| Image, `--require-deps`, no fixture | — (not run) | — | 2 |
| Image (fresh no-cache build from `requirements-cpu.lock`), `--require-deps`, weights-free fixture, `--network none` | 47 | 0 | 0 |

The 4 tests added in `tests/test_run_tests.py` are standard-library only and
run in both modes:
- a skip fails `--require-deps` but not offline;
- the preflight names missing modules and the fixture;
- a missing dependency exits 2 before any test runs;
- the fixture fetch skips the weights.

Every class that skips offline ran in full mode. These are the NumPy and PyAV
paths of `audio.py`, `model.decide`, `service.py`, `robustness.py` and
`prepare.prepare_punctuated`, and the torch paths of `train.py`: loss check,
checkpoint, resume after interruption, refusal on mismatch, and
`verify_checkpoint`. Line coverage was not measured: `coverage` is not in the
lock.

## Environment checks (items 3, 5–10, 14)

- **Working directory:** commands run from `tools/speaking` (the image mounts
  it at `/src` with `-w /src`). `run_tests.py` resolves `tests/` from its own
  path, so it also works from the repository root.
- **One lock:** `requirements-cpu.lock` serves the image build and the venv
  alike; no second lock was created. The fresh image's `pip freeze` equals the
  lock's package set (numpy 2.5.4, av 19.0.2, torch 2.15.0+cpu, transformers 5.21.1).
- **No downloads during tests:** the full run used `--network none`, with
  `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` set in the image. The only network
  call in the tests goes to a local test server on 127.0.0.1.
- **No GPU or credentials:** the container got only `HOME`, `PYTHONPATH` and
  `FLH_SPEAKING_TOKENIZER_DIR`. torch is the CPU build.
  `test_aws_render` renders a template with placeholder values and makes no AWS call.
- **Timing, measured separately:**
  - fixture fetch 2.4 s;
  - image build (`--no-cache`, 39 downloads) 165 s;
  - tests 11.9 s, 15.1 s wall; peak RSS 528 MiB; 2 CPUs and 1 GB allowed;
  - offline mode about 0.3 s.

## Without Docker (item 19)

The fallback is a Python 3.12 virtual environment installed from the same lock:

```sh
python3.12 -m venv .venv && .venv/bin/pip install --require-hashes --no-deps \
    --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple -r requirements-cpu.lock
```

It was run in a bare `python:3.12-slim` container (the pinned base image,
without the project image), standing in for a CI runner:
- install 124 s; `pip check`: no broken requirements;
- `--require-deps`: 47 tests, 0 skipped, exit 0, 11.6 s, peak 527 MiB.

It was not run natively on this host, which has only Python 3.14. The lock's
cp312 torch and NumPy wheels need CPython 3.12.

## Extraction suite (item 18)

`cd tools/extraction && python3 -B -m unittest discover -s tests -t tests`:
98 tests, OK, exit 0, 0.7 s. It was not changed here.
- **7 skips:** "needs torch, transformers and TINY_SFT". These are optional
  tests that need a tiny model fixture.
- **1 expected failure:** `test_reporting.CrossReportDenominators.test_quality_and_evaluate_count_invalid_rows_alike`,
  the documented FLH-154 F1 discrepancy (item 29).

## For the release lane (item 16): proposed CI steps, not applied

These steps touch no CI YAML here. Run them from `tools/speaking`:

1. Offline mode, on the runner's own Python (≥ 3.12, no packages):
   `python3 -B scripts/run_tests.py`. Expect 47 run, 28 skipped, exit 0, about 1 s.
2. Full mode. Two steps:
   - Fixture (cacheable; key: the whisper-tiny revision `169d4a43…`):
     `python3 -B -m flh_speaking fetch --dest "$FIX" --what whisper-tiny --no-weights`.
     It downloads 4.3 MB, hash-verified against `pins.py`.
   - Then either
     - (a) the image: `docker build --build-arg TORCH_INDEX=cpu -t flh-speaking:cpu .`,
       then the `docker run … --network none … scripts/run_tests.py --require-deps`
       command in `tools/speaking/README.md` § Tests;
     - or (b) the Python 3.12 venv from `requirements-cpu.lock` (§ Without Docker).

   Expect 47 run, 0 skipped, exit 0.
3. Resources:
   - 2 CPUs and 1 GB of memory (peak 530 MiB);
   - about 1.5 GB of disk for the image, or about 1 GB for the venv;
   - network only for the fixture and the install (about 250 MB of wheels);
   - no GPU, secrets, model weights or datasets;
   - runtime about 3 min cold (install 124–165 s, tests 15 s), seconds when the image or venv is cached.
4. Not for CI: the real-inference smoke (`tools/speaking/scripts/verify_local_provider.py`).
   It needs the pinned weights, the frozen MLS data and about 2 GB; run it
   before deploying the service.

## Release contract (increment 2: tested invocation and fixture identity)

Exact invocation, tested from a fresh read-only copy of `tools/speaking`
(51 run, 0 skipped, exit 0, about 11.4 s of tests). It works from the package
directory and, as `python3 -B tools/speaking/scripts/run_tests.py …`, from the
repository root:

```sh
docker run --rm --network none --cpus 2 --memory 1g --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e FLH_SPEAKING_TOKENIZER_DIR=/tok -v "$FIXTURE":/tok:ro -v "$PWD":/repo:ro -w /repo/tools/speaking \
  --entrypoint python3 flh-speaking:cpu -B scripts/run_tests.py --require-deps --json /dev/stdout > speaking-tests.json
```

| Requirement | Value |
|---|---|
| Image | `tools/speaking/Dockerfile` with `--build-arg TORCH_INDEX=cpu`: base `python:3.12-slim@sha256:6c4dd321…`, packages from `requirements-cpu.lock` (`--require-hashes`) |
| Python | 3.12.13 (the image, and the bare `python:3.12-slim` used for the venv check) |
| CPU / memory | 2 CPUs, 1 GB (peak 530 MiB); no GPU |
| Network | none while testing; only to build or install (about 250 MB) and to fetch the fixture |
| Fixture | the 10 pinned non-weight files of `openai/whisper-tiny@169d4a4341b33bc18d8881c4b69c2e104e1cc0af`, 4,372,752 bytes; contract `sha256:55f3d55eaaa4291c715c37cb8f18e2dd8ecb379bad2041593d6ca6bb9826ecc2` (sorted `name size kind digest` lines of `pins.py`; also printed as `fixture.contract_sha256` in the JSON). A good cache key. |
| Fixture fetch | `python3 -B -m flh_speaking fetch --dest DIR --what whisper-tiny --no-weights`; `FIXTURE=DIR/openai/whisper-tiny/169d4a4341b33bc18d8881c4b69c2e104e1cc0af` |
| Exit status | 0 pass; 1 a failure, an error or any skip; 2 a missing module or a fixture file that is missing or does not match its pin (checked before discovery; the JSON is still written) |
| Evidence | `--json FILE`; the suite's exit status is unchanged by it, so CI uploads the file `if: always()` and keeps the step's status |

## Increment 3 (Speaking Lab batch): strict CPU checks, items 061-070

- **Offline entry point kept (061):** `python3 -B scripts/run_tests.py`, or plain
  `unittest discover`.
- **Strict mode (062):** still fails on a missing module or fixture (exit 2) and
  on any skip (exit 1). It now also fails when the summary's counts do not add
  up (`counts_consistent`).
- **Network guard (065):** `--expect-offline` exits 2 before any test if
  1.1.1.1:443, 8.8.8.8:53 or pypi.org:443 is reachable. On this host, with
  network, it exits 2; in the image with `--network none` it records
  `reachable: []` and the run passes.
- **Corrupt fixture (067):** already covered by
  `test_fixture_with_a_missing_or_wrong_file_is_refused`, which runs in both modes.
- **Counts (068):** the JSON's per-class counts must equal `ran`, and
  `skipped_tests` must list every skip; both are checked inside the run.

**An environment problem is not a failed test (069).**

| Situation | Exit | JSON | Meaning |
|---|---|---|---|
| no Python 3.12 with the lock installed (NumPy, PyAV, torch or transformers missing) | 2 | `missing: ["module numpy", …]` | environment: install from `requirements-cpu.lock` (image or venv), then rerun |
| fixture missing or not matching its pins | 2 | `missing: ["fixture … tokenizer.json: …"]` | environment: `fetch --what whisper-tiny --no-weights` |
| network reachable with `--expect-offline` | 2 | `network.reachable: [...]` | environment: run with `--network none` |
| a test failed or errored | 1 | `failures` / `errors` > 0 | a real test result: investigate |
| a test skipped in strict mode | 1 | `skipped` > 0, `skipped_tests` | the environment is incomplete in a way the preflight did not catch: fix, do not ignore |

**For release (070): the exact command, cache identity and expected report.**

```sh
docker run --rm --network none --cpus 2 --memory 1g --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e FLH_SPEAKING_TOKENIZER_DIR=/tok -v "$FIXTURE":/tok:ro -v "$PWD":/repo:ro -w /repo/tools/speaking \
  --entrypoint python3 flh-speaking:cpu -B scripts/run_tests.py --require-deps --expect-offline --json /dev/stdout > speaking-tests.json
```

Cache identity:
- **image:** `sha256(tools/speaking/Dockerfile)` + `sha256(tools/speaking/requirements-cpu.lock)`;
- **fixture:** `fixture.contract_sha256` `55f3d55e…26ecc2` (whisper-tiny@169d4a43…, 10 files, 4,372,752 bytes).

Expected report:
- `mode: require-deps`, `skipped: 0`, `failures: 0`, `errors: 0`, `counts_consistent: true`;
- `network.reachable: []`;
- `versions` numpy 2.5.4, av 19.0.2, torch 2.15.0+cpu, transformers 5.21.1;
- `ran` equals the number of tests in the tree (87 at item 070; later Speaking Lab items add tests, see `SPEAKING-LAB-V1.md`).

Timings measured this increment, separately (066):

| Step | Time |
|---|---|
| dependency setup: `docker build --no-cache`, CPU | 185 s |
| fixture setup: fetch into an empty directory | 5.0 s (10 files, no weights) |
| test execution: strict, `--network none`, 2 CPUs and 1 GB | 16.1 s of tests, 19.0 s wall |
