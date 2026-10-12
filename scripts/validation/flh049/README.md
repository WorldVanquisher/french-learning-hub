# FLH-049 independent probes

Run from the repository root. Standard-library Python only; Go and its existing
module cache are needed for helper probes. No download, production write, model,
daily database or permanent dependency is involved.

```sh
python3 -B scripts/validation/flh049/probe.py fixture --output /tmp/flh049-fixture-new
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off python3 -B scripts/validation/flh049/probe.py helper --output /tmp/flh049-helper-new
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off python3 -B scripts/validation/flh049/probe.py real --output /tmp/flh049-real-new
```

Each output directory must be new. If the default Go cache is read-only, first
create `/tmp/flh049-go-cache` and copy the existing cache there; do not download
modules. Helper probes need permission to bind loopback sockets and connect to
the intentionally unavailable `127.0.0.1:9` endpoint.

Fixture probes create mutated copies in automatically removed temporary
directories. Three deliberately invalid semantic scenarios currently pass the
validator; a legitimate cross-family contrast is structurally rejected.

Helper probes invoke the unchanged helper in subprocesses. A temporary `go`
wrapper delegates to the actual installed Go executable, removing the Qdrant URL
for skips, changing only the selection regex for zero matches, or selecting a
closed endpoint for failures. JSON and readable Go output remain in the supplied
output directory. The skip/zero/fail cases do not inject leftover collections,
so collection failure cannot mask their enforcement.

The loopback readiness/collection facade is **not Qdrant**. Cleanup and timeout
probes use controlled facade collection state. The cleanup-error and timeout
cases redirect only the imported helper's root/test directory to a temporary
stdlib-only Go module with the eight existing expected names. These tests are
synthetic orchestration evidence, never integration-success evidence. The
cleanup-error case intentionally asserts the observed defect: cleanup HTTP 503
with helper exit zero. A future fix should make this assertion fail, requiring
the audit expectation to be reviewed.

Temporary wrappers/modules are automatically removed; the facade is shut down
and its thread joined. Output logs are retained for review. The helper's real
Qdrant container mode is a separate check and is not simulated by `helper` mode.

`real` requires access to Docker and the exact compose-pinned image already in
its cache. It runs the unchanged helper against disposable real Qdrant containers
for baseline, timeout, failed-test, skip and zero-match cases. A temporary Docker
wrapper replaces only `docker pull <pin>` with `docker image inspect <pin>`;
every other Docker command is delegated unchanged. This avoids registry access
and records all invocations. It does not test registry pulling.

Timeout/failure cases copy `internal/`, `migrations/`, `go.mod` and `go.sum` into
an automatically removed temporary directory. Only the first integration test
in that copy gets a three-second delay or deliberate `t.Fatal` after rig setup.
The imported helper's root/test-directory constants point to the copy; its
expected list, compose pin and verdict logic remain unchanged. Skip/zero cases
use the Go wrapper described above while a real Qdrant container is running.
Baseline acceptance separately asserts actual JSON `run` and `pass` events for
all eight expected names, version 1.19.1, exact image pin and container removal.
