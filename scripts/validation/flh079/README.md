# FLH-079 public-demo CI acceptance

Report, reproduction and limitations: [docs/validation/FLH-079-public-demo-ci.md](../../../docs/validation/FLH-079-public-demo-ci.md).
Workflow: [.github/workflows/public-demo.yml](../../../.github/workflows/public-demo.yml).

| File | Purpose |
| --- | --- |
| `run.py` | Single entry point: builds from source, synthetic mechanical artifact, HTTP + DOM checks, restart, `summary.json` (PASS/FAIL/BLOCKED/NOT RUN) |
| `failure_probe.py` | Shows an assertion failure exits 1 and SIGTERM exits 143, both with verified cleanup |
| `test_run.py` | Helper unit tests and static workflow-policy checks |

```sh
python3 -B scripts/validation/flh079/run.py --work /abs/new/dir
python3 -B scripts/validation/flh079/failure_probe.py --work /abs/new/dir2
python3 -B -m unittest discover -s scripts/validation/flh079 -p 'test_*.py'
```

Mechanical vectors prove mechanics, not retrieval quality. No model, provider,
Docker, Qdrant or network beyond 127.0.0.1 (and package registries for builds).
