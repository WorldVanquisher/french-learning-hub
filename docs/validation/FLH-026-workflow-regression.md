# FLH-026 — Repeatable daily-workflow regression

Implementation owner: NAS Codex. Actual working directory:
`/home/worldvanquisher/workspace/flh-nas-codex`. Requested branch label:
`test/flh-026-workflow-regression-harness`; no Git/GitHub operations performed.
Verified 2026-10-08. Status: complete, stopped for human review.

Read `AGENTS.md`, current merged `docs/RELEASE.md`, the FLH-019 and FLH-023
contract notes, and relevant HTTP/provider/domain/storage wiring. The supplied
FLH-017 validation report is also present and was consulted. The harness does
not wait for FLH-020 or include FLH-025 frontend behavior as an integrated
baseline. `README.zh-CN.md` exists; shared READMEs remain outside ownership.

## Exact modified paths

All five are new task-owned files:

- `scripts/validation/flh026/run.py`
- `scripts/validation/flh026/fake_provider.py`
- `scripts/validation/flh026/test_harness.py`
- `scripts/validation/flh026/README.md`
- `docs/validation/FLH-026-workflow-regression.md`

No production code, configuration, dependencies, Makefile, CI, AGENTS, shared
README or frontend files changed for this task. Earlier task changes in the
supplied working tree are preserved.

Usage and safety prerequisites are maintained in
[`scripts/validation/flh026/README.md`](../../scripts/validation/flh026/README.md).
The one native command is `python3 -B scripts/validation/flh026/run.py`;
optional container mode adds `--mode container`. Neither accepts a service URL,
existing database, port, provider, project or image target. All data and processes
belong to a new private temporary run. Native listener PID/socket ownership and
container project/mount/port checks refuse ambiguous targets.

## Executed verification

These final commands actually completed with exit 0:

```sh
python3 -B scripts/validation/flh026/test_harness.py
python3 -B scripts/validation/flh026/run.py --report /tmp/flh026-native-final.json
python3 -B scripts/validation/flh026/run.py --mode container --report /tmp/flh026-container-final.json
```

Safety suite: **6 tests passed**, including controlled copy/checksum/non-`ok`
integrity failures, no inherited configuration, refusal to connect to an unowned
HTTP target, and cleanup of an owned process/provider/directory after an injected
assertion failure. A first sandboxed safety run lacked socket permission; it was
rerun with the authorized local-listener access and passed. Constructor cleanup
was strengthened for failed port reservation, and its initial empty temporary
directories were removed.

Both workflow modes: **8 assertion groups passed**, `RESULT=PASS CLEANUP=PASS`.
Native and container source snapshots have identical backend hashes. The final
reports' three Python harness hashes match the final working-tree files.
Evidence includes complete per-file SHA-256 manifests, command output, service
logs, assertion groups and cleanup outcomes. No source revision or branch state
is inferred from Git.

| Workflow assertion | Native | Release container |
| --- | --- | --- |
| Capture create/lookup/replay/conflict, unchanged stored records/counters | PASS | PASS |
| Accepted/corrected/rejected effective interpretation and inventory; extraction eligibility/provenance | PASS | PASS |
| Feedback and newer-analysis changes while extraction provider is gated: 409, no partial persistence | PASS | PASS |
| Human SAME, INVALID/restore, fresh SAME, append-only judgments, support/reviewability, Inspector/Dataset/NDJSON | PASS | PASS |
| Old pin/newer extraction/pin survives replacement/reset/repeated clear/automatic advance; labels unchanged | PASS | PASS |
| Root and `/api` cross-site/null/metadata/unknown-Host rejections; complete table snapshots and provider counters unchanged | PASS | PASS |
| CLI-shaped, same-origin release, trusted development-origin and explicit NAS name/IP compatibility | PASS | PASS |
| Complete table state, selection and dataset survive process/container replacement | PASS | PASS |
| File-only backup, exact integrity result, checksums, preserved old directory, restored snapshot selected after ordinary restart | PASS | PASS |
| Restored directory remains selected after ordinary Compose down/up and up `--build` | N/A: native process restarts | PASS |
| Actual browser-origin attack / real Vite browser exercise / frontend DOM | NOT RUN | NOT RUN |

The rejection matrix sends 50 mutation probes (five routes, five header shapes,
root and prefixed) plus two unknown-Host reads and one same-origin text/plain
body probe. It covers bodyless analysis/extraction/INVALID and pin reset, rather
than relying only on Content-Type rejection. Every table remains identical and
both analyzer/extractor call counts remain unchanged. This establishes zero
persisted writes and zero provider calls; it does not trace internal SQL.

Provider gates observe arrival before changing the source. Each conflict result
is compared with every database table from immediately after the intended source
change; only feedback/analysis and SQLite sequence rows may change before that
snapshot. Successful extractions use distinct deterministic evidence, high valid
confidence, and exact persisted source IDs. There is no external provider call,
retry, fallback or permanent dependency added.

The backup writer is stopped before copying. Only `app.db` and applicable WAL/SHM
files enter the backup; no recursive data-directory copy occurs. Integrity must
be exactly one `ok` row and SHA-256 checksums are computed afterward. Restore
validates its entire manifest and stages into a private sibling, preserving the
old directory before swapping onto the same custom configured path. A new
post-backup entry is absent in restored data and present in the preserved data.
Subsequent ordinary starts retain the restored snapshot. These are Python
standard-library implementations of the documented release steps, not execution
of the Bash documentation blocks.

## Toolchains, source scope and cleanup

Native mode actually executed `go version`, `go mod verify`, a server build, and
`go version -m` with offline module resolution and a clean environment. Installed
native compiler: `go1.27.1-X:nodwarf5 linux/amd64`; module declares Go `1.26.5`.
Container mode successfully built the release Dockerfile with its digest-pinned
Go `1.26.5` stage, Node stage and Alpine runtime; the resulting service passed
the same HTTP/SQLite workflow. The container frontend is packaging input only,
not frontend acceptance evidence. Full Go unit tests/vet and capture-executable
tests were **NOT RUN in this task**; this task's checks are the workflow harness,
its safety tests and builds.

The container fixture used installed `python:3.12-slim`, actual image ID
`sha256:9cbfea842643d1cf45df5d841ac78e8cc1a8bfbcc36934a9d31fdc964fcc5917`.
Docker emitted a missing-buildx warning and successfully used the classic
builder. Compose always used `--env-file /dev/null`; no actual `.env`, user
provider secrets, daily data or personal instance was accessed.

Final native source inventory: 145 files; canonical inventory digest
`e16352269dadabeda4b187a87149e12563c94681d676eb8cfd4edc7d3ddefe9a`.
Final container inventory: 193 files including packaging/frontend input; digest
`7b33929eb3edd0a62b09a820fb6f05f2e302ea4fdb232c23dbe6f1932acb8d6b`.
Digests are SHA-256 of `json.dumps(source_sha256, sort_keys=True).encode()`.
The original release `.dockerignore` further excludes Go tests and testdata from
the image build context. Native uses a generated minimal index for `/api` wiring.

Final isolated identifiers were `/tmp/flh026-pnkq58g1` (native) and
`/tmp/flh026-oag1m496`, project `flh026-oag1m496`, image
`flh026-oag1m496:local` (container). Both temporary directories were removed.
Container down/removal and unique image-tag removal returned zero. The fake
provider is also replaced by full down/up, so its new zero counters are checked
before asserting subsequent startup calls none. Public base images/build cache
are retained. Durable evidence JSON files remain outside the repository.

Initial exploratory runs failed on harness assumptions about table/response
names, a listener-inspection race, and hashing a backup before the WAL integrity
check updated its sidecar. Those harness errors were corrected and both entire
modes rerun successfully. No application defect was confirmed; no production
patch was made to obtain a pass.

## Limits and handoff

Real browsers, Vite proxy execution, DOM behavior and FLH-025 integration are
NOT RUN. Header probes demonstrate actual server behavior and simulated
development compatibility only. Host tests approve exact synthetic NAS hostname
and documentation IP; they do not exercise actual NAS DNS/network routing.
FLH-019 permits only loopback defaults plus explicitly configured exact NAS/IP
hosts, ignores forwarded headers for trust, and separately validates mutation
Origin/Fetch Metadata. It is browser-request protection, not authentication;
DNS for an approved hostname is not pinned, so an attacker-controlled approved
name remains a rebinding gap.

Crash/power-loss recovery, external writers, disk exhaustion, arbitrary filesystem
faults, concurrent-load stress, dataset exporter training policy and preferred-unit/
retirement changes are outside this baseline. Cleanup cannot be guaranteed after
SIGKILL or daemon failure; failed cleanup is reported nonzero with the owned
private run retained. Reviewed source scope is recorded in the evidence manifests,
and the human must rerun after integrating another task's source changes.

README-owner handoff: if adding validation commands to shared documentation,
link the maintained harness usage document in both English and Simplified Chinese.
This task stops editing for human review.
