# FLH-031 annotation idempotency author verification

These files review the supplied FLH-029 implementation. They modify no production
source, migrations, shared documentation or FLH-026/028 harness file. Since the
verifier also authored FLH-029, results are **author verification**, not independent
review. No Git/GitHub commands are used.

From the repository root, use new report files outside the repository:

```sh
python3 -B scripts/validation/flh031/verify.py --report /tmp/flh031-native-new.json
python3 -B scripts/validation/flh031/verify.py --mode container --report /tmp/flh031-container-new.json
python3 -B scripts/validation/flh031/checks.py --report /tmp/flh031-checks-new.json
python3 -B scripts/validation/flh031/workflow.py --report /tmp/flh031-workflow-native-new.json
python3 -B scripts/validation/flh031/workflow.py --mode container --report /tmp/flh031-workflow-container-new.json
python3 -B scripts/validation/flh026/test_harness.py
python3 -B scripts/validation/flh028/test_proxy.py
```

No target URL/database/provider/project options are exposed. Reports must not
exist already. Native mode needs Linux `/proc`, Python 3.10+, a compatible local
Go toolchain and cached project modules. Native mode uses the actual local Go;
setting caller `PATH` does not override FLH-026's intentionally clean environment.
The report records `go version` and executable build metadata. Container mode
uses the established digest-pinned Dockerfile, Docker/Compose and the already
installed `python:3.12-slim` fixture image. It may download public locked build
dependencies as the existing release workflow does. No registry credentials,
real `.env`, personal service, learning data or paid provider is accessed.

`checks.py` explicitly invokes the cached digest-pinned Go 1.26.5 image without
network access for formatting, module verification, focused/full tests, vet and
both builds. It copies the existing frontend and installed dependencies into a
private directory for typecheck/tests/build. It installs no permanent dependency
and writes no shared `dist`, TypeScript build metadata or dependency cache. Node
26 needs `--no-experimental-webstorage` here so jsdom supplies browser storage.
If frontend dependencies or the pinned Go image are missing, that limitation is
reported rather than installing them implicitly.

`verify.py` reuses the 128-case FLH-028 matrix unchanged. New checks cover:

- 16 simultaneous equivalent first-arrivals: one event/receipt, identical 201
  results and exactly one initial-commit response; restart/lookup/replay preserve it.
- 16 competing first-arrivals under one key: one semantic payload wins, eight
  identical successes and eight 409 conflicts, one event and one receipt.
- Root/workbench aliases, uppercase UUID keys, decimal path leading zeros and
  JSON whitespace/order equivalence; different action/unit/concept/relation conflicts.
- Invalid/empty/multiple keys, malformed/null/wrong-type/unknown/trailing JSON,
  invalid relation and missing targets, with full-table/provider-counter invariance.
- Receipt INSERT abort after event INSERT: 500, no receipt or additional event,
  unchanged authority; explicit same-key retry commits after removing the fixture
  trigger and supersedes the original event, never a rolled-back event.
- Original historical receipt/result after newer unkeyed annotation, SAME,
  preferred-unit selection and reassignment. Existing SAME contradiction rules
  suppress older pair evidence; replay does not resurrect it or alter membership,
  support or preferred-unit authority.
- Native-only real 008→009 upgrade: build a private binary with migration 009
  temporarily excluded, create annotations through HTTP, then restart the final
  binary. Only the new empty receipt table and migration ledger row appear;
  existing table contents, catalog, effective projections and Dataset stay identical.

Totals are 169 native cases and 168 container cases. Each includes 128 inherited
cases plus 40 new operation/alias probes; native adds the migration probe.
Simultaneous first-arrivals go directly to the owned Go listener, because the
Python proxy's small listen queue is not the application concurrency boundary.
Duplicate header lines also go directly: the shared proxy converts headers to a
dictionary and loses multiplicity. Response-loss cases still use the real proxy.
Neither path automatically retries writes.

The adapter gives each Compose project a Docker-safe hexadecimal suffix while
retaining the inherited harness ownership prefix. `workflow.py` applies the same
safe name and otherwise runs FLH-026's existing assertions unchanged. Native
listeners must belong to the owned child PID; container startup verifies project
labels, data mount and published loopback port. Database-trigger fault injection
is confined to the run's private database. Every mutation/projection observation
uses synthetic fixtures and the counted controllable local provider.

Reports retain baseline/source/harness SHA-256 inventories, API/SQLite observations,
actual commands, failure details and cleanup. Cleanup drains delayed proxy jobs,
stops the owned service/provider, removes only the project's temporary image/tag,
containers/network and private files. Shared base images/build caches remain.
SIGKILL, power loss and daemon failure cannot guarantee cleanup.

See `docs/validation/FLH-031-idempotency-contract-verification.md` for the exact
reviewed baseline, actual results, reporting defects and remaining limits. These
checks do not replace real-browser acceptance or independent review.
