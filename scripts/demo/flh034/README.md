# FLH-034 Knowledge Library demo fixture

See [docs/DEMO.md](../../../docs/DEMO.md) for setup, the two-minute walkthrough,
restart and cleanup.

| File | Purpose |
| --- | --- |
| `demo.sh` | `setup` / `start` / `stop` / `cleanup` of an isolated demo directory (refuses unsafe targets, occupied ports and unverified processes; a failure stops what it started and exits non-zero) |
| `proc_guard.py` | Port, listener and process-identity checks (PID + start time + command line) used by `demo.sh`; Linux `/proc` or macOS `ps`/`lsof` |
| `stub_extractor.py` | Local extraction-provider stand-in with fixed synthetic French-learning units |
| `seed.py` | Seeds records, analyses, feedback, extractions and Concepts through the public API only; refuses non-loopback or non-empty backends |
| `walkthrough.mjs` | Optional automated walkthrough in headless Chrome (needs temporary `playwright-core`); `--multi-relation` adds W11 |

The server runs with the demo directory as its working directory, so the
repository `.env` is never read. Provider settings are set explicitly:

- `LISTEN_HOST=127.0.0.1`, so the server binds loopback only;
- `AI_PROVIDER=rule-based`;
- `EXTRACTOR_PROVIDER=openai`, pointed at the local stub with a placeholder key;
- `EMBEDDING_PROVIDER=disabled`.
