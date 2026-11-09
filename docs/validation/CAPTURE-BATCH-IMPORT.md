# Capture batch import — validation

Owner: NAS Claude Code, sole implementation owner. Date: 2026-11-08 (UTC).
Built and tested in a disposable allowlisted copy of the working tree outside
the checkout (the checkout was not modified); intended branch
`feat/capture-batch-import`.

**Status: implemented and tested.**
- Unit, CLI and in-process integration tests pass.
- A real-binary acceptance against `cmd/server` passed 46/46 on loopback, with
  a disposable SQLite database.

**What was not used:**
- No provider: the analyzer is rule-based, and every other provider was
  disabled.
- No new route, schema, migration or frontend change.
- The daily service was not touched.

## 1. What changed

| Area | Change |
|---|---|
| `cmd/capture/main.go` | **New flags:** `-batch FILE...` and `-batch -preview FILE...`, with batch exit statuses `0`/`1`/`3`, and `2` for usage.<br>**Single-file and stdin behaviour, output and exit `0`/`1` unchanged**, with one exception: stray positional arguments without `-batch` used to be ignored silently (the CLI then read stdin). They are now refused with exit `2` |
| `internal/captureclient/batch.go` (new) | **`PlanBatch`:** 1–100 files, byte-wise path order, refuses a file listed twice by path or identity.<br>**`PreviewBatch`:** local checks only, no HTTP.<br>**`Client.RunBatch`:** one unchanged `Client.Import` per file, outcome classification, stop rules.<br>**Labels:** the content-free `capture_id` label |
| Tests (new) | `internal/captureclient/batch_test.go`, `internal/captureclient/batch_integration_test.go`, `cmd/capture/main_test.go` |
| Acceptance (new) | `scripts/validation/capture_batch/run.sh`, `lossy_proxy.py` |
| Docs | `docs/ARCHITECTURE.md` (§4.2 *Batch mode*, §A.9 *Batch import and preview*), `README.md`, `README.zh-CN.md`, `AGENTS.md` (capture CLI bullet; `CLAUDE.md` is a symlink to it), this report |

### Outcomes

| Server answer / event | Outcome | Decided by |
|---|---|---|
| `201` | `created` | server |
| `200` | `replayed` | server |
| `409` | `conflict`: the stored capture is unchanged | server |
| `400`, `422` | `invalid` | server |
| Missing, unreadable, non-regular, blank or >1 MiB file | `invalid`, not sent | local |
| Any other status, lost or unreadable response, timeout, interruption while waiting | `unconfirmed`: may or may not be stored | none |
| Connection could not be opened | `not_attempted` (nothing delivered) | none |
| After an interruption, or after 3 files in a row without a server response | `not_attempted` | none |

**Exit status:**
- `0`: every file is created or replayed (preview: every file ready).
- `1`: some file is conflict or invalid.
- `3`: some file is unconfirmed or not attempted. Rerun the same files.
- `2`: the batch was refused before any file was read or sent.

**Recovery is a rerun, never an automatic retry.** The server's
fingerprinted receipt per `capture_id` decides committed versus new.

**Reports contain identifiers only:** paths, a `capture_id` label (shown only
when it is a portable identifier), HTTP status, and entry and analysis IDs.
They never contain learner text or request bodies. A server message that
repeats request content is withheld.

## 2. Commands and results

All commands ran in the scratch copy, with
`GOFLAGS=-mod=readonly GOPROXY=off GOTOOLCHAIN=local`. Go is 1.27.3 (local
toolchain).

| Command | Result |
|---|---|
| `go test -count=1 ./cmd/capture ./internal/captureclient ./internal/domain` (baseline copy, before changes) | ok (`cmd/capture` had no test files) |
| `go test -count=1 -v ./internal/captureclient -run 'Batch\|Preview\|BoundAndLabel'` | 8 tests PASS: plan and refusals, preview sends 0 requests, every outcome classified with bytes sent unchanged, one bad file does not hide others, interruption, connection failure, refusal sends nothing, label and bounds |
| Mutation check: `maxConsecutiveNoResponse` 3 → 4 | The classification test **failed** as expected. Restored |
| `go test -count=1 -v ./internal/captureclient -run MixedBatch` | PASS. The test uses the real handler, real temporary SQLite and a proxy that drops one response after commit. The first run of this test failed because of a test bug: the proxy's drop counter also counted the rerun. The counter was fixed (CompareAndSwap) |
| `go test -count=1 -v ./cmd/capture` | 5 tests PASS: single-file and stdin output byte-identical, usage errors exit 2 with 0 requests, batch exit statuses, report order, preview sends nothing. One expectation was corrected: the report follows path order, not argument order (the intended behaviour) |
| `go test -race -count=3 ./cmd/capture ./internal/captureclient` | ok |
| `unshare -rn … gofmt -l …; go vet ./...; go test -count=1 ./...` | gofmt clean, vet ok, every package ok |
| `unshare -rn bash -c 'ip link set lo up; bash scripts/validation/capture_batch/run.sh <scratch>/accept4'` | **46 PASS, 0 FAIL, exit 0** (details below). Earlier runs: accept1 (34/0), accept2 (35/0) and accept3 (41/0) were the same script while it grew |

**Real-binary acceptance (`run.sh`):**
- **Setup:**
  - built `cmd/server` and `cmd/capture`;
  - server on `127.0.0.1:18997`, from an empty working directory (no `.env`), with `env -i`, a disposable `hub.db`, the rule-based analyzer and every provider disabled;
  - `lossy_proxy.py` on `:18998`, logging method, path and `capture_id` only.
- **Single file:** the existing `-file` import printed `capture stored (new)`.
- **Preview:** exit 1. Proxy log empty (**0 requests**), summary `total=8 ready=7 invalid=1`, nothing written.
- **Mixed batch through the proxy:** exit 3.
  - Outcomes: `01-new` created, `02-replay` replayed, `03-conflict` conflict, `04-lost` unconfirmed, `05-invalid-schema` invalid (422), `06-missing` invalid (local, not sent), `07-new` created, `08-not-json` invalid (400).
  - Summary: `created=2 replayed=1 conflict=1 invalid=3 unconfirmed=1`.
  - The proxy dropped exactly the `batch-lost` response after an upstream `201`.
  - 7 POSTs were sent (none for the missing file).
  - `GET /captures/batch-lost` returned 200 (committed). The conflicting capture still points at entry 1.
  - The database holds 4 entries.
- **Rerun of the same files:** exit 1. `04-lost` is **replayed**; summary `created=0 replayed=4 conflict=1 invalid=3 unconfirmed=0`; **still 4 entries (no duplicate)**.
- **Unreachable server:** exit 3, `not_attempted=5`. The first three could not connect; the batch then stopped after 3 files without a response. Entries unchanged.
- **Real SIGINT:** sent after 1 s to a batch whose listener accepts but never answers. Exit 3: the in-flight file is unconfirmed, the other 2 not attempted, and the report prints `interrupted:`. Entries unchanged.
- **The documented example `-batch captures/*.json`:** 16 created, then 16 replayed on rerun; 20 entries in total.
- **Reports:** none contains the learner-text marker, `«`, `original_input`, or text from the synthetic captures.

## 3. Limits and owner checks

- **Not run:** `make verify` was not run, because the scratch copy has no
  `web/node_modules` and no frontend file changed. The Go half (format, vet,
  every Go test, builds) ran as above. Run `make verify` on the branch.
- **Batch size:** a batch holds at most 100 files. Larger sets are split by
  the user into several runs.
- **Edited files between preview and send:** the CLI does not detect a file
  edited between `-preview` and the real run. The server's fingerprint turns
  such an edit into `conflict` for an already stored `capture_id`.
- **The real-binary acceptance needs** Python 3, `curl`, and `unshare` (for
  network isolation; optional).
