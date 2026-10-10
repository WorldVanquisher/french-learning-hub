# FLH-035 Phase A — existing-contract acceptance preparation

This directory does not implement the Knowledge Library, guess its endpoints,
or seed the FLH-034 demo. Phase B requires the human-supplied integrated checkout.
The [acceptance matrix](../../../docs/validation/FLH-035-knowledge-library-acceptance.md)
records the pending integration and demo requirements.

Run from the repository root:

```sh
python3 -B scripts/validation/flh035/test_expectations.py
python3 -B scripts/validation/flh035/verify_existing.py --report /tmp/flh035-my-existing-contract-run.json
```

The report must be a new file outside the repository in an existing directory;
existing evidence is never overwritten. Exit zero means all reached assertions
and cleanup passed. Failure records reached cases and the actual error; it is
not passing acceptance. No Python packages or project dependencies are installed.

The thirteen oracle tests use in-memory HTTP-shaped dictionaries. They test the
acceptance assertions, not a mocked Library UI. The integration probe runs real
HTTP against an owned native Go process, with a fresh isolated SQLite database,
synthetic static index, and the counted local FLH-026 fake Responses provider.
Only explicit fixture extractions call that fake. Captures include prepared
analyses; annotation, selection, browsing and restart must make no provider call.

The launcher and provider in `../flh026/` are reused without modification.
Prerequisites: Linux `/proc`, Python 3.10+ with SQLite, a Go compiler compatible
with the repository's module declaration on the launcher's isolated PATH, and
already-installed verified modules in the normal Go module cache. Socket/process
permissions are necessary. Compiler path/version/hash and built-binary metadata
are retained. Caller PATH wrappers do not select the compiler. Builds are offline,
using temporary HOME/cache, GOENV off, GOTOOLCHAIN local and no VCS inspection.

The probe has no target URL, database, port, provider or demo-fixture options.
Every request uses the launcher's child-listener ownership guard. Its only
retained output is the chosen evidence JSON (plus logs redirected by the caller).
It creates two entries, three Concepts and three Units through existing APIs,
then applies narrowly scoped test transitions. This is a disposable contract
probe, not a public demo seed, reset command or second implementation of FLH-034.
Every fresh invocation starts from an empty private database.

Fourteen checkpoint groups exercise actual root and production `/api` reads,
state filters, deterministic catalog ID ordering, preferred IDs, immutable
extraction/Unit/source evidence, current SAME versus accepted history, and
expected supporting fixture Unit sets. Complete SQLite table snapshots and
provider counters must stay unchanged across each GET sequence. Process
replacement must preserve all tables and HTTP models. The `expectations.py`
reader accepts an ownership-checked GET callback and ID expectations captured
from API responses; it cannot discover or select an arbitrary service.

`verify_view` is a bounded independent test oracle: it checks fixture support
against current selection, current membership and effective admission. It does
not implement browser business rules or infer membership from historical links.
Preferred Units need current SAME membership, not current-extraction support.
The fixtures cover both null and accepted-feedback extraction provenance.

Cleanup stops the owned server/provider and removes its private source, data,
cache and static fixture. SIGINT/SIGTERM and ordinary assertion/build failures
unwind through cleanup; SIGKILL/power loss cannot guarantee cleanup. Cleanup
failure marks the run failed and may retain its private directory for diagnosis.
No secret files, daily databases, paid providers, frontend output, Docker images
or permanent dependencies are used by this Phase A probe.

The probe is **HTTP + SQLite evidence for existing contracts**. It does not test
Library search/rendering, entry-navigation return context, compiled frontend
assets, container deployment, a real browser, or the author's two-minute demo.
Do not turn its result into FLH-034 acceptance. In Phase B, map the implemented
demo's receipt/manifest IDs into expectations, inspect its documented startup and
cleanup instructions, and verify the integrated contract before adding checks.


## Phase B — integrated author demo

Phase B preserves the Phase A scripts above. It runs the merged author's
`scripts/demo/flh034/demo.sh`, `seed.py` and `stub_extractor.py` unchanged, with
an isolated demo directory and generated production assets. It does not use the
Phase A fixture as a demo substitute.

```sh
python3 -B scripts/validation/flh035/test_integrated_checks.py
python3 -B scripts/validation/flh035/verify_integrated.py --report /tmp/flh035-integrated-my-run.json
```

Prerequisites additionally include npm, curl and public npm artifacts cached in
`/tmp/flh029-npm-cache/_cacache` from earlier authorized verification. The cache
is copied into the owned run directory before offline `npm ci`; absence fails
rather than downloading or inheriting credentials. npm uses separate empty user
and global config files. Frontend source/lockfiles/config are copied privately;
production build, the author's four Library jsdom tests, and one independent
mocked duplicate-relation UI probe run there. No repository `node_modules`, dist,
TypeScript output, dependency manifest, demo file or production file is changed.

The runner reserves unique loopback ports and supplies only the documented
`DEMO_PORT`/`STUB_PORT` overrides to the unchanged demo. Every API request requires
the server listener's socket inode to belong to the attributed child PID. The
unchanged demo itself binds its app listener to a wildcard address, recorded as
a finding; requests still target only the owned loopback service. Native builds
use the isolated offline environment and `-buildvcs=false`; no Git command runs.

The author's stub does not expose counters. A temporary `sitecustomize.py` startup
hook observes completed POSTs at its stdlib HTTP handler boundary. It records
only `POST`, changes no request/response, and applies only to `stub_extractor.py`.
The hook text is retained in JSON evidence. Stub POST count must remain unchanged
around browsing and restart; fixture setup legitimately makes five local calls.
No analyzer/external provider counter is invented: analysis is local rule-based,
embedding disabled, and the Library depends on read interfaces only.

Search checks use the implemented AND-prefix contract, not Phase A discovery
semantics. The pristine author's demo runs first, including HTTP content checks,
production asset-byte verification, root/`/api` parity, before/after whole-table
snapshots, and documented stop/start. Only afterward do supported public APIs
introduce tier/ID ties, preferred historical membership, INVALID, multiple source
entries, later feedback/analysis, and multiple relation types. Those are edge
probes, not a replacement or edited demo fixture.

Owned safety probes test normal refusals, a misattributed PID with a disposable
sleep sentinel, and an occupied port with an owned HTTP fixture that rejects seed
writes. They never contact an existing/personal service or kill an unrelated user
process. The runner attributes PID command lines before calling author cleanup,
then requires all reserved ports closed. All data/builds/dependencies/hooks are
removed; only the chosen JSON and redirected logs remain outside the repository.
Cleanup cannot be guaranteed after SIGKILL or power loss. A command timeout or
failed prerequisite remains a failure, not acceptance.

Exit zero requires no runner error, cleanup error **or recorded defect**. Completed
checks with findings use JSON state `CHECKS_COMPLETE` and exit one; this is not a
passing release acceptance. Failed intermediate attempts are retained separately
with new report names. Actual browser interaction and the timed human two-minute
presentation remain NOT RUN when no browser is available. HTTP traversal time,
frontend setup time and Go/demo build-start-seed time are recorded separately.
The independent React probe is explicitly mocked API + real React/jsdom evidence;
it is not a browser. The full findings and limits are in the acceptance report.
