# FLH-072 production hybrid acceptance

Mechanics only: actual Go server/web assets/index CLI, the cached pinned Qdrant
image, and FLH-060's hash-vector fake provider. No model/GPU/AWS, relevance labels
or quality claim. Browser interaction is not supplied by this harness.

Requires existing Go modules, `web/node_modules`, Docker access and the Qdrant
image pinned in compose.yaml. It never pulls an image or installs dependencies.
Use new task-local directories and free ports:

```sh
mkdir /tmp/flh072-new
(cd web && ./node_modules/.bin/vite build --outDir /tmp/flh072-new/web-dist)
python3 -B scripts/validation/flh072/accept.py --out /tmp/flh072-new --work /tmp/flh072-new-demo --port-base 19720
```

The helper reuses `scripts/demo/flh060/demo.py` directly. Its only environment
shim preserves `GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off` for child Go
builds; it changes no demo/provider/ranking code. Setup starts the real production
server with `-web-dir`, synthetic SQLite and semantic configuration. Its actual
CLI builds the index, syncs, rebuilds and exercises persisted restart behavior.

The independent oracle requests keyword and semantic at the same depth, then
hybrid at a separate display limit. It reconstructs equal-weight RRF with k=60,
ID tie order, deduplication, ranks/evidence, null components and state filters.
Stable-data comparison groups assert identical full SQLite logical dumps and
publication pointers, two single-query provider calls and no document positions.
Those two calls are the separate semantic and hybrid requests; keyword calls none.

Controlled mutations are only in the isolated synthetic DB/Qdrant: stale title,
retirement, a foreign point ID/payload mismatch and incompatible collection shape.
Production source/normal expectations are unchanged. Foreign points are dropped
by the existing Qdrant adapter, so legitimate duplicate Concept IDs cannot be
manufactured by adding another distinct Qdrant point. The union of both component
lists independently proves hybrid deduplication; existing Go tests cover duplicate
component-ID inputs to fusion.

A task-owned forwarding barrier passes real Qdrant responses unchanged. Immediately
before an old collection's query it runs the actual operator `rebuild`, causing a
real 404 and publication retry. Two replacements must fail explicitly. These
intentional operator index writes are separate from search's read-only behavior.

Exit 0 requires all recorded expectations to pass; inspect raw evidence rather
than exit alone. `finally` stops only identity-verified demo processes and the
work-labelled Qdrant container, and closes the owned proxy. The demo directory,
SQLite, Qdrant storage, counters and raw HTTP/CLI evidence remain outside the repo.
Ports base+0/1/2/3 and base+10 must be free; no unrelated service is signalled.

The actual FLH-072 initial run was preserved after a helper path-joining error
and an incorrect foreign-point duplicate expectation. `--resume` starts the
retained demo and runs **only** the corrected foreign-point and double-publication
checks, then cleans up. It does not repeat the full audit:

```sh
mkdir /tmp/flh072-followup-new
python3 -B scripts/validation/flh072/accept.py --out /tmp/flh072-followup-new --work /tmp/flh072-demo --port-base 19720 --resume
```

The [report](../../../docs/validation/FLH-072-hybrid-search-acceptance.md) records
exact executed commands, expected/actual results, test counts, provider totals,
hashes, browser limitations and cleanup evidence. No production defect was
identified in the adjudicated cases.
