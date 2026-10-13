# FLH-060 validation: isolated persistent semantic-search demo

Date: 2026-10-12. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` on **macOS arm64** (Go 1.26.5,
Python 3.13.5, Docker Desktop).
- **Not used:** Git/GitHub commands, subagents, model downloads, paid
  providers, `.env` or daily data.
- **The human's service and proxy:** never restarted or stopped. Only
  read-only GETs and the budgeted POSTs below reached them.
- **Raw evidence:** in the session scratchpad, outside the repository.

Contract: [plan](../plans/FLH-060-semantic-demo.md).

## Human observations (not executed by this agent)

- The FLH-059 diagnostic on the RTX 4070: float16 `dynamic_v1` had 359
  tolerance failures and 4/32 top-5 order changes. float16 `singleton_v1` was
  424/424 bitwise equal with zero failures, and was the pre-registered
  candidate.
- The singleton service smoke test passed: 768-D unit vectors on `cuda:0`.

## Live run (real mode, the supplied endpoint): executed once

**Endpoint and deployment**
- `http://100.118.109.6:8765/v1`
- `multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff`

| Step | Result |
| --- | --- |
| Initial read-only `GET /readyz` | ready, exact deployment id |
| `demo.py setup <W> --mode real --embedding-base-url … --embedding-model … --embedding-dimensions 768 --port-base 18970` | Exit 0. Three read-only preflights over setup and restart: ready, `identity_ok`, manifest sha256 `5a3e23f2…ae4bc74`, 768 dimensions. **0 POSTs** |
| `demo.py walkthrough <W> --allow-live` | Exit 0, **PASSED 18/18 mechanical checks** |
| Second `walkthrough --allow-live` / without the flag | Exit 2 "already started; not repeated" / exit 2 "pass --allow-live". No request was sent |
| `demo.py stop <W>` | Directory kept |

**Budget and counters**
- Planned 9 POSTs and 22 positions; used **9/64 POSTs and 22/256
  positions**, with no refusals, retries or failed POSTs.
- **Gateway:** 2 index POSTs carrying 15 Concept-document positions, and 7
  search POSTs carrying 7 query positions. The one offline-switch refusal never
  reached the endpoint.
- **The service's own `/metrics` delta:** `requests_total` 9, `requests_ok` 9,
  `input_positions` 22, passage 15, query 7, no rejections, truncations or
  overlength inputs, `max_tokens_seen` 68. It matches the gateway exactly. On a
  shared service the delta could also include other clients; none appeared.

**Mechanics observed**
- `build` embedded 15 documents (0 query positions).
- Each semantic search used exactly 1 query position; keyword searches used
  none.
- After stop/start the publication was still verified healthy.
- `sync`: verified unchanged, 0 calls. `rebuild`: 0 embedded, 15 reused from
  cache, 0 calls.
- Offline switch: semantic search returned HTTP 502 `embedding provider
  unavailable` with no hits, while keyword search (200) and index status
  (healthy) kept working. After switching back, semantic search worked again
  with no rebuild.

**Rankings (exploratory and synthetic; demonstration inputs, not labels).**
For example, "how do I tell a friend I miss them" put *tu me manques* first
(0.8720), and "I want two of them" put *the pronoun en* first (0.8427). Scores
ranged from about 0.81 to 0.87, close together. They are cosine scores, not
probabilities, not relevance judgments and not SAME decisions. The repeated
first query gave the same top-5 order and 4-decimal scores after recovery: an observation for one
query only, not a general determinism claim. **No general semantic-quality
claim.**

**Evidence files** (scratchpad `flh060/real1/`):

| File | SHA-256 |
| --- | --- |
| `evidence/20261012-224200-walkthrough.json` | `ef185cd7…3c9da8f` |
| `gateway/budget.json` | `c09f6781…dc05d` |
| `gateway/state.json` | `df81e578…0b8da` |

Preflight, index-build/sync/rebuild reports and the run marker are also kept.

## Fake mode and safety (run here)

| Check | Result |
| --- | --- |
| First setup attempt | Failed (Qdrant `/readyz` is plain text and the client expected JSON). The failure path removed the container and records; `cleanup` removed the directory. Fixed, then re-run |
| Setup on a fresh directory (`fake3`, with `--web-dist`) | Exit 0; 15 Concepts (7 + 8); embedded nothing |
| `walkthrough` | **PASSED 18/18**; 9 POSTs, 15 document and 7 query positions |
| Workbench `GET /` | 200 |
| stop → start → status | Healthy; 15 cached vectors; counters persisted |
| cleanup | Directory removed; 0 `flh060.work` containers left |
| Earlier directory (`fake1`): stop/start mid-walkthrough | Found a restart failure: the fake service's port was in `TIME_WAIT` because FLH-054 sets `allow_reuse_address = False`. Fixed in `fake_e5.py` for its own listener only. `start` then recovered the stale records, and repeating `start` worked |
| Walkthrough on an already-built directory | Build skipped; **PASSED 16/16** |
| `setup` on an occupied port | Exit 2 "port 18960 (server) is already in use"; directory not created |
| Gateway record forged to point at an unrelated `sleep` | `stop` didn't signal it ("not ours; nothing signalled"), reported the real gateway as an unrecorded demo process and exited non-zero. `status` lists unrecorded processes. Restoring the record let `stop` finish cleanly |
| `python3 -B -m unittest discover -s scripts/demo/flh060 -p 'test_*.py'` | **13 OK** (loopback stubs) |

Fake vectors are hash-based: their rankings carry no meaning.

## Compose semantic profile (fake mode; Docker Desktop on this Mac)

| Command | Result |
| --- | --- |
| `compose-up <W> --container-embedding-url http://host.docker.internal:18961/v1 --build` | Exit 0 in 78 s. Project `flh060-b6cf3cac8ef2`, image `flh060-demo-app:local`, app `127.0.0.1:18966` (healthy), Qdrant `127.0.0.1:18967` |
| `compose-index <W> status` | `UNHEALTHY — collection missing` (copied publication record, fresh Compose Qdrant) |
| `compose-index <W> sync` | Embedded 0, reused 15, published; **0 gateway POSTs** |
| `search … --compose` | 200; 1 query position counted by the gateway |
| `compose-down`, then `compose-up` (no build), then `status` | 0 project containers after down; after up, the same publication, HEALTHY |

The built image `flh060-demo-app:local` was removed afterwards. The BuildKit
cache from this build wasn't pruned, because a global prune would also remove
unrelated cache. The pinned Qdrant image was already present before this task.

## `run-diagnostic.ps1` (PowerShell 7.4.6 in a Linux container; not Windows)

This used the temporary image `mcr.microsoft.com/powershell:7.4-ubuntu-22.04`,
run as uid 1000 with `--network none` and stub `python` and `nvidia-smi`. The
image was removed afterwards.

| Case | Result |
| --- | --- |
| Normal run | Exit 0; 4 files hashed; the list doesn't contain itself |
| `-HashOnly` on the same directory | Exit 0; the earlier list was kept as `artifact-sha256.previous-<time>.txt` and hashed with the rest (5 files) |
| `-HashOnly` without `analysis.json` | Exit 1 with an explanation |
| One unreadable file (`chmod 000`) | **Exit 1**; all files kept; no hash list written |
| No `-ModelDir` without `-HashOnly` | Exit 1 |

The FLH-059 bug was `Get-ChildItem | Get-FileHash | Out-File` enumerating the
list while writing it. That failure was observed on Windows by the human and
can't be reproduced on Linux. **Windows PowerShell execution of the fix is NOT
RUN.** To hash the existing results without re-running GPU inference:
`.\scripts\validation\flh059\run-diagnostic.ps1 -OutDir <results dir> -HashOnly`.

## NOT RUN

- **On the NAS:**
  - native real mode: `README.md` "Real mode", with `WORK` under `$HOME` and
    the pinned Qdrant image pulled explicitly if missing;
  - Compose real mode: `compose-up … --container-embedding-url
    http://100.118.109.6:8765/v1 --build`. Whether a NAS container can reach
    the tailnet address is untested.
- **On Linux:** Docker Qdrant with `--user uid:gid` bind-mount ownership.
- **On Windows:** the fixed `run-diagnostic.ps1`.
- **Not done:** the 1,400-position evaluation, any relevance or quality
  evaluation, automatic SAME.
