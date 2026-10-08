# FLH-028 annotation response-loss reproduction

From the repository root:

```sh
python3 -B scripts/validation/flh028/test_proxy.py
python3 -B scripts/validation/flh028/reproduce.py
```

Optional durable evidence, using a **new** file outside the repository:

```sh
python3 -B scripts/validation/flh028/reproduce.py --report /tmp/flh028-my-run.json
```

Exit zero means every assertion and cleanup passed. Prerequisite/build/assertion/
cleanup failure exits nonzero. Existing reports are never overwritten. No Python
package installation is needed. Native prerequisites are Linux `/proc`, Python
3.10+ with SQLite, a Go compiler compatible with `go.mod`, and installed project
modules in the normal Go module cache. Local socket/process permissions are
required. No browser, Docker, frontend install or personal service is needed.

The harness reuses the **read-only** FLH-026 native launcher and local deterministic
provider from the adjacent `flh026/` directory. It independently implements the
proxy, fixtures, loss scenarios, authoritative reads and assertions. FLH-026's
workflow assertions are not used. The launcher creates a private source snapshot,
temporary HOME/cache/database, its own service port/process and a counted fake
provider. Its inherited temporary names use `flh026-*`; these resources belong
only to this invocation. Builds are offline (`GOPROXY=off`, `GOENV=off`, local Go,
verified installed modules, no VCS inspection). The server has a minimal synthetic
index so both root and `/api` routes run through real production transport.

Each fixture imports synthetic source plus a valid analysis through `/captures`,
then explicitly extracts one unit using the local provider. Annotation requests
and reconciliation GETs go through a new loopback proxy. It preserves actual
Host/Origin for same-origin browser-shaped requests; forwarded headers do not
grant trust. The upstream callback verifies the listener belongs to the owned
server PID before connecting. The CLI has no target URL, database, port, provider
or project option, and never discovers existing instances. No actual `.env`,
provider secret, daily data, paid API, production source change or Git operation
is involved.

## Fault controls and expected results

`LossProxy.arm(mode, method, path)` selects exactly one request. GETs continue
normally in another handler. Its controller is in process, not an exposed admin
endpoint. All original writes are forwarded at most once, with no retry.

| Mode | Proxy behavior | Client sees | Reconciliation read | Final state |
| --- | --- | --- | --- | --- |
| `never` | Close before forwarding | No HTTP response | Unchanged | Unchanged |
| `commit-drop` | Obtain successful upstream response, then close downstream without headers/body | No HTTP response | Desired state | Committed |
| `delay-drop` | Close downstream, gate original write until reconciliation GETs finish, then forward once | No HTTP response | Old state | Desired state after release |

These are actual socket disconnects, not synthetic application error responses.
Gate events and monotonic timestamps establish request order; sleeps do not
decide write/read ordering. The proxy's captured upstream response is a **test
oracle** that a real client with a lost response does not possess.

The matrix covers SAME, reassignment, membership rejection, INVALID, restore,
new concept with seed SAME, preferred unit, DISTINCT, and BROADER/NARROWER/RELATED,
through root and `/api` routes. Every write fixture initially differs from the
desired state. Authoritative GET payloads, all-table SQLite snapshots and provider
counters verify expected outcomes. Each successful lost response is followed by
a separate identical request that is **never forwarded**: the desired state still
matches, but this second request demonstrably did not commit. State confirmation
therefore does not establish request attribution.

Additional DISTINCT and relation cases perform two explicit submissions after
a first committed response was dropped. They require **three separate persisted
event IDs**, unchanged earlier event payloads and, for relations, the exact
supersession back-pointer chain. Inspector and Dataset must expose the newest
single event for the pair/type; history must retain all three. A further case
starts with an existing pair, delays an identical write, confirms the pair via
GET before forwarding, then verifies a second event is appended afterward.
Matching state does not settle a pending duplicate operation.

JSON reports retain source/harness hashes, exact before/reconciliation/final API
payloads, proxy upstream status/body, socket errors, event IDs and ordering,
SQLite persistence outcomes, provider counters, command output and cleanup.
Successful runs currently execute 104 cases. A failed run records the error and
completed cases rather than inventing acceptance evidence.

## Authority and limits

- CURRENT SAME: `GET /knowledge-units/{id}/concept-membership`; its projection
  is authoritative, not old accepted SAME events in concept history.
- INVALID/restore: `GET /knowledge-units/{id}/invalid` supplies effective boolean
  and full judgment history. A restored candidate need not have membership.
- DISTINCT: `GET /knowledge-units/{id}/concept-distinctions` supplies full history;
  `GET /knowledge-units/{id}/effective-annotation` supplies current effective pairs.
- Relations: `GET /concepts/{id}` has append-only links, filtered by unit/type;
  effective annotation identifies the current relation. A historical accepted
  link can already have been superseded. There is no dedicated unit relation
  history GET in current wiring.
- New concept: the catalog can match its full identity; concept detail and seed
  unit membership confirm durable identity and current seed authority.
- Preferred unit: `GET /concepts/{id}` exposes `preferred_unit_id`.
- Inspector/Dataset expose effective authority, not a receipt for a client request.
  Dataset is current-extraction-only; it is not the place to determine whether
  an out-of-current extraction's historical write committed.

An unchanged GET cannot prove a delayed request failed or was canceled. Matching
GET state cannot prove this particular request succeeded: the state may predate
it, belong to another writer, or change again later. Event IDs/new history can
show persistence, but without a client operation ID they do not give general
causal attribution. The single-writer proxy oracle supplies causality only for
this controlled investigation. No server API behavior was modified.

Cleanup releases/drains pending proxy jobs, closes its listener/thread and stops
the owned server/provider, then removes temporary data. SIGINT/SIGTERM and failed
assertions unwind through cleanup. SIGKILL/power loss cannot guarantee cleanup;
resource cleanup errors fail the run. Reports contain only synthetic content and
the public fixture key. They are the only retained output, outside the repository.

This is backend HTTP/database evidence, **not browser or frontend DOM acceptance**.
FLH-027 is not awaited or modified. When its integrated code is supplied, rerun
this harness against that tree and combine the evidence with the frontend owner's
real UI tests. Its reusable proxy can supply controlled transport faults for
that work; it does not itself assert buttons, notices, reconciliation behavior,
request cancellation or retry choices in the UI. Container replacement, full Go
unit/vet suites, arbitrary simultaneous writers, disk failures and proxying real
TLS are outside this investigation.

The backend gap and minimal proposed receipt/idempotency contract are reported
in `docs/validation/FLH-028-review-response-loss.md`; no proposal is implemented.
