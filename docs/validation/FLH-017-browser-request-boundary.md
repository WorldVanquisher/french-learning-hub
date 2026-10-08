# FLH-017 — Local browser request boundary

Read-only investigation of FLH-013 findings X1 (cross-site writes) and X2
(any `Host` accepted). The only file this task writes is this report. No
production code, configuration, dependency, or Git state was changed.

## Summary

| ID | Result |
|----|--------|
| X1 | **Reproduced independently and widened.** All 8 cross-site POST probes over root and `/api` paths returned `2xx` and wrote data: entries, captures, a rule-based analysis, an extraction that called the provider, and a forged human `INVALID` judgment. |
| X1 cause | No `Origin`, `Sec-Fetch-Site`, `Host`, or `Content-Type` check exists in `internal/transport/http` or `cmd/server`. Handlers decode JSON regardless of `Content-Type`, and some state-changing POSTs take no body at all. |
| Content-Type alone | **Insufficient.** Analysis, extraction, `invalid`, and `invalid/restore` are bodyless POSTs. The workbench sends no `Content-Type` for them, and the cross-site bodyless extraction triggered a provider call. |
| Proposed fix | Wrap `Handler.Routes()` in Go's standard-library `http.NewCrossOriginProtection()` (Go ≥ 1.25; module is `go 1.26`). A prototype rejected every cross-site probe with `403`, with zero new rows and zero provider calls. Same-origin, Vite-proxy-shaped, plain-HTTP NAS, curl and real capture CLI requests all still succeeded. |
| X2 | **Confirmed, not fixed by the proposal.** A DNS-rebinding-shaped request is genuinely same-origin, so it still reads and writes through the prototype. It needs a separate owner decision (see §6). |
| Browser | **No real browser was available.** All evidence below is curl with browser-shaped headers. Browser acceptance steps are proposed in §8. |

## Environment and isolation

- Working directory: the provided working tree for branch
  `audit/flh-017-browser-request-boundary`. No Git command was run; the
  branch name comes from the task statement.
- Toolchain: local `go1.27.1`. `go.mod` declares `go 1.26.5`, and the
  Dockerfile builder is `golang:1.26.5-alpine`. The prototype ran on the
  local toolchain, not 1.26.5.
- Scratch root `$T` was a fresh `mktemp -d` under `/tmp`. Binaries were built
  from the working tree into `$T/bin` (`go build ./cmd/server`,
  `./cmd/capture`).
- Server: `$T/bin/server -web-dir $T/web` on `:18290`, cwd `$T/run`. The repo
  `.env` therefore wasn't in the search path, and `env -i` gave the process
  only these variables: `PORT=18290`, `DB_PATH=$T/run/app.db`,
  `AI_PROVIDER=rule-based`, `EXTRACTOR_PROVIDER=openai`,
  `OPENAI_API_KEY=fake-local-key`, `OPENAI_MODEL=fake-model`,
  `OPENAI_BASE_URL=http://127.0.0.1:18291`, `EMBEDDING_PROVIDER=disabled`.
  The startup log confirmed `extractor provider: openai` and the temp DB path.
- `$T/web` was a synthetic `index.html` plus one asset. `web/dist` and
  `web/node_modules` don't exist in the working tree, and creating them would
  mutate shared files.
- Fake provider: a 20-line `python3 -I` `http.server` on `127.0.0.1:18291`.
  It answers `POST /responses` with one valid `vocabulary` unit and appends
  the request path to `$T/provider.log`. A provider call means one line in
  that log. No real or paid provider was contacted.
- Data checks used `sqlite3 -readonly` on the temp DB only. No daily or
  release database was touched.
- Prototype (§4): a scratch Go module in `$T/proto` with stdlib only. It
  listens on `127.0.0.1:18292` and wraps `httputil.ReverseProxy` to `:18290`
  in `http.NewCrossOriginProtection().Handler`. It keeps the incoming `Host`
  (`r.Out.Host = r.In.Host`) so the check sees the same `Host`, `Origin` and
  `Sec-Fetch-Site` an in-process wrapper would.
- All processes were stopped and `$T` was deleted after the run.

## 1. Checkpoint — X1 reproduction (unmodified server, curl)

Unless a row says otherwise, the headers were `Origin: http://evil.test:9999`,
`Sec-Fetch-Site: cross-site`, `Sec-Fetch-Mode: no-cors` and
`Content-Type: text/plain`. This is the shape a browser uses for a
preflight-free `fetch(..., {mode: "no-cors"})` or a `<form enctype="text/plain">`.

| Probe | Request | Status | Effect |
|-------|---------|--------|--------|
| P1 | `POST /entries` (JSON body) | `201` | entry 1 |
| P2 | `POST /api/entries` | `201` | entry 2 |
| P3 | `POST /api/captures` (`learning_capture_v1`) | `201` | capture `flh017-p3`, entry 3 |
| P4 | `POST /captures` | `201` | capture `flh017-p4`, entry 4 |
| P5 | `POST /api/entries/1/analysis`, no body, no `Content-Type` | `201` | analysis 1 (rule-based) |
| P6 | `POST /api/entries/1/extractions`, no body | `201` | extraction 1 with 1 unit; **provider calls 0 → 1** |
| P7 | `POST /knowledge-units/1/invalid`, no body | `200` | judgment with `"decision_source":"human"`, which forges human annotation authority |
| P8 | `POST /entries`, `Content-Type: application/x-www-form-urlencoded`, `Origin: null` | `201` | entry 5 |
| P9 | `GET /api/entries`, `Host: rebind.test:18290` | `200` | full entry list returned (X2) |
| P10 | `OPTIONS` preflight for `PUT /api/knowledge-units/1/concept-membership` | `405` | no `Access-Control-*` headers, so a browser blocks cross-site `PUT` |

No response carried `Access-Control-*` headers, so a cross-site page cannot
read write responses. The header check itself was a cross-site POST and
created entry 6.

Counts after the baseline: entries 6, captures 2, analyses 1, extractions 1,
units 1, `unit_resolution_judgments` 1, provider calls 1.

Conclusions:
- Root and `/api` paths behave identically, because `NewWorkbenchHandler`
  strips `/api` in front of the same mux.
- `Content-Type` is ignored: `text/plain` and form encoding both decode as
  JSON.
- Bodyless POSTs need no simple-request trick at all. Any cross-site
  `fetch(url, {method: "POST", mode: "no-cors"})` or plain HTML form works.
  Extraction spends provider money when it is enabled.
- `PUT` routes are already protected by the browser's preflight. The server
  answers `405` without CORS headers.

## 2. Checkpoint — header, CLI and Vite handling (inspection)

- **Server:** `cmd/server/main.go` sets `srv.Handler = routes`, either
  `Handler.Routes()` or `NewWorkbenchHandler` around it, with no middleware. A
  grep of `internal/transport` and `cmd/server` found no reference to
  `Origin`, `Sec-Fetch-Site` or `r.Host`, and no `Content-Type` check on
  input. JSON handlers use `json.NewDecoder(r.Body)` with
  `DisallowUnknownFields`, whatever the media type.
- **Workbench client** (`web/src/api/client.ts`): requests go to the relative
  base `/api`, so they are always same-origin. `Content-Type:
  application/json` is set only when a body exists. Analysis, extraction,
  `invalid` and `invalid/restore` are sent without a body or a
  `Content-Type`.
- **Capture CLI** (`internal/captureclient/client.go`): `POST {base}/captures`
  with `Content-Type: application/json` on a stdlib `http.Client`. It sends no
  `Origin` and no `Sec-Fetch-*` header.
- **Vite** (`web/vite.config.ts`, lockfile `vite` 5.4.21): proxies `/api` to
  `FRENCH_HUB_URL` (default `http://localhost:8080`) with `changeOrigin: true`,
  which rewrites `Host` to the backend's host, and strips `/api`. Nothing in the
  config removes `Origin` or `Sec-Fetch-*`, so the backend sees the browser's
  `Sec-Fetch-Site: same-origin` together with `Origin: http://localhost:5173`
  and `Host: localhost:8080`. **Not run:** `web/node_modules` is absent, and
  `npm ci` would mutate the shared tree. The header pass-through is an
  inspection conclusion that C3 below simulates.
- **Stdlib `CrossOriginProtection`** (Go source `net/http/csrf.go`, read
  locally):
  - It never blocks `GET`, `HEAD` or `OPTIONS`.
  - It allows `Sec-Fetch-Site` values `same-origin` and `none`, and rejects
    every other value.
  - When `Sec-Fetch-Site` is absent, it allows a request that has no `Origin`,
    or whose `Origin` host equals `r.Host`, and rejects anything else.
  - It rejects with `403` and a `text/plain` body. `SetDenyHandler` can replace
    the response, and `AddTrustedOrigin` adds exemptions.

## 3. Checkpoint — prototype rejection (curl through `:18292`)

R1–R6 used the cross-site headers from §1.

| Probe | Request | Status |
|-------|---------|--------|
| R1 | `POST /entries` `text/plain` | `403` |
| R2 | `POST /api/captures` `text/plain` | `403` |
| R3 | `POST /captures` | `403` |
| R4 | `POST /api/entries/2/analysis` (bodyless) | `403` |
| R5 | `POST /api/entries/1/extractions` (bodyless; entry 1 eligible) | `403` |
| R6 | `POST /knowledge-units/1/invalid/restore` (annotation mutation) | `403` |
| R7 | `Origin: http://127.0.0.1:3000`, `Sec-Fetch-Site: same-site` (other local port) | `403` |
| R8 | no `Sec-Fetch-Site`, `Origin: http://evil.test:9999` (plain-HTTP browser shape) | `403` |
| R9 | no `Sec-Fetch-Site`, `Origin: null` | `403` |

The counts before and after R1–R9 were identical: entries 6, captures 2,
analyses 1, extractions 1, invalid judgments 1, **provider calls 1 (no new
call)**.

## 4. Checkpoint — prototype compatibility (curl and real CLI through `:18292`)

| Probe | Shape | Status |
|-------|-------|--------|
| C1 | Release same-origin: `Origin: http://127.0.0.1:18292`, `Sec-Fetch-Site: same-origin` | `201` |
| C2 | NAS over plain HTTP: `Host: nas.lan:18292`, `Origin: http://nas.lan:18292`, no `Sec-Fetch-Site` | `201` |
| C3 | Vite proxy: `Host: 127.0.0.1:18292`, `Origin: http://localhost:5173`, `Sec-Fetch-Site: same-origin` | `201` |
| C4 | curl/CLI: no `Origin`, no `Sec-Fetch-Site`, `POST /captures` | `201` |
| C5 | same-origin bodyless analysis | `201` |
| C6 | same-origin bodyless extraction | `201`; **provider calls 1 → 2** |
| C7 | cross-site `GET /api/entries` | `200` (reads unchanged; no CORS, so not readable cross-site) |
| CLI | `$T/bin/capture -url http://127.0.0.1:18292 -file cli.json` | exit 0, `capture stored (new)` |
| CLI | same file, `-url http://127.0.0.1:18292/api` | exit 0, `idempotent replay` |

The final counts were entries 11 and captures 4 before the X2 probe.

## 5. Checkpoint — X2 (DNS-rebinding shape)

| Probe | Request | Status |
|-------|---------|--------|
| D1 | `POST /api/entries`, `Host: rebind.test:18292`, `Origin: http://rebind.test:18292`, `Sec-Fetch-Site: same-origin` (prototype) | `201`, entry 12 |
| D2 | `GET /api/entries`, `Host: rebind.test:18292` (prototype) | `200` with data |

After a rebind, the attacker's page really is same-origin with the service,
so no `Origin` or `Sec-Fetch-Site` rule can tell it apart. X2 also allows
**reads**, which X1 does not. No real rebinding (attacker DNS) was run.

## 6. Recommendation

**Smallest X1 correction (transport layer, stdlib, no config).** Wrap the
API mux once in `internal/transport/http/handler.go`:

```go
// Routes ... (end of function)
	// Reject browser cross-site writes (X1): Sec-Fetch-Site, else Origin vs Host.
	// Requests without either header (CLI, curl) are unaffected.
	return http.NewCrossOriginProtection().Handler(mux)
```

`Routes()` serves both API-only mode and the workbench, because
`NewWorkbenchHandler` dispatches `/api/...` and root paths into it. One wrap
therefore covers every write route. `GET /` and `/assets/` stay unwrapped,
which is fine because they only serve `GET`.

As an optional tweak in the same change, `SetDenyHandler` can return the
existing `{"error": "..."}` JSON envelope. Without it the workbench still
shows `request failed with status 403`.

Rejected alternatives:
- Requiring `application/json` leaves bodyless POSTs open, including the
  paid extraction (P6), and would break the workbench's bodyless calls if
  applied to them.
- A hand-written Origin/Host comparison duplicates the stdlib check and
  misses `Sec-Fetch-Site` handling.
- A CORS layer is the wrong tool, since there are no cross-origin
  consumers.

**Compatibility:**
- **Same-origin release** (`127.0.0.1:8080` or `localhost:8080`): browsers
  send `Sec-Fetch-Site: same-origin` to these trustworthy origins, so the
  request is allowed (C1). `127.0.0.1` and `localhost` stay separate origins,
  but each works on its own.
- **Vite development:** the page and its `/api` fetch share the
  `localhost:5173` origin, so the browser sends `same-origin`. The check
  passes even though `changeOrigin` makes `Host` differ from `Origin` (C3).
  Cross-site pages that hit the Vite proxy forward `cross-site` and are
  rejected. One edge: a browser that omits `Sec-Fetch-Site` would hit the
  Origin≠Host fallback and get `403` in dev only. Every current browser sends
  the header to `localhost`.
- **CLI and curl without `Origin`:** these are allowed (C4, plus the real
  CLI on root and `/api`). No CLI change is needed.
- **Intentional NAS access:** browsers don't send `Sec-Fetch-*` to plain-HTTP
  non-local origins. The fallback compares `Origin` to `Host`:
  - Direct `http://nas.lan:8080` access passes (C2), and a cross-site page
    fails (R8).
  - A reverse proxy in front must preserve `Host` (for example nginx
    `proxy_set_header Host $host`), or same-origin writes fail with `403`.
  - Behind HTTPS, browsers send `Sec-Fetch-Site` and `Host` no longer
    matters.
  - Compose currently binds `127.0.0.1` only, so NAS access from other
    devices already requires a proxy or a compose change. That change is
    outside this task.
- **No Host allowlist is assumed.** A localhost-only allowlist would break
  NAS access by hostname or IP and any proxy setup, and the X1 fix doesn't
  need one.

**X2 needs a separate owner decision.** None of these options is in scope
for this task:
- **(a)** A server-side allowed-hosts list. This needs configuration, because
  the valid NAS names are deployment-specific.
- **(b)** A TLS reverse proxy with a fixed `server_name` that rejects unknown
  `Host` values. This is a deployment change with no code.
- **(c)** Accept the risk for loopback-only use, and record it in
  `docs/RELEASE.md`.

Browser Local Network Access restrictions shouldn't be relied on.

## 7. Limitations and NOT RUN

- **Real-browser evidence: none.** No Chromium, Chrome or Firefox was found
  on `PATH`, in `/opt`, in Playwright/Puppeteer caches, or by a depth-4
  filesystem search. Installing a browser would add a dependency. Every
  header combination above was supplied by curl, and the claim that browsers
  send those headers comes from documented browser behavior, not from
  observation.
- The Vite dev server was not run (no `node_modules`). Proxy header
  forwarding is inferred from the config and simulated by C3.
- The fix was prototyped as a `Host`-preserving reverse proxy in front of the
  unmodified server, not as an in-process change. It ran on the local
  go1.27.1 stdlib, not the 1.26.5 builder.
- The annotation coverage was `invalid` and `invalid/restore`. SAME,
  relation, distinction, reject, preferred-unit, concept creation and
  admission-override POSTs go through the same mux and were not probed one by
  one.
- No real DNS-rebinding attack, no TLS or reverse-proxy setup, no Docker
  image, and no `make verify` (documentation-only task).

## 8. Proposed acceptance tests

Go tests in `internal/transport/http` use existing `httptest` patterns, temp
SQLite databases and a counting stub extractor, with no new dependencies:

1. **Cross-site rejection.** For every `POST`/`PUT` route, on both
   `Routes()` and `NewWorkbenchHandler(.../api)`, send
   `Sec-Fetch-Site: cross-site`. Expect `403`, unchanged row counts, and zero
   stub-extractor calls on `POST /entries/{id}/extractions`.
2. Rejection also covers `same-site`, a mismatched `Origin` without
   `Sec-Fetch-Site`, and `Origin: null`.
3. **Allowed shapes:**
   - `same-origin`, and `none`.
   - No `Sec-Fetch-Site` with `Origin == Host` (`http://nas.lan:8080`).
   - The Vite shape: `same-origin`, `Origin: http://localhost:5173`,
     `Host: localhost:8080`.
   - No headers at all.

   Each must give the existing `2xx` result.
4. Cross-site `GET` reads are still `200`, and no `Access-Control-*` header
   appears on any response.
5. The existing `internal/captureclient/integration_test.go` and
   `web` client tests pass unchanged.
6. If `SetDenyHandler` is used, the `403` body is `{"error": ...}` JSON.
7. **Known gap.** A test documents that `Host`/`Origin` = `rebind.test` with
   `same-origin` is still accepted, until an X2 decision is made.

Manual browser acceptance runs against an isolated server with a temp DB and
synthetic pages only, never an external site:

1. Serve `attack.html` with `python3 -m http.server --bind 127.0.0.1 18393`
   and open it as `http://localhost:18393/attack.html`. That makes it a
   different site from `http://127.0.0.1:8080`. The page should contain:
   - `fetch(".../api/captures", {method: "POST", mode: "no-cors", headers: {"Content-Type": "text/plain"}, body: ...})`
   - A bodyless `fetch(".../api/entries/1/extractions", {method: "POST", mode: "no-cors"})`
   - An auto-submitted `<form enctype="text/plain">` whose field name/value
     forms a valid entry JSON body.

   Before the fix, expect new rows (and a fake-provider call). After it,
   expect `403` in the server log and no new rows or provider calls.
2. Use the release workbench at `http://127.0.0.1:8080/` to import a capture,
   run analysis, run extraction (fake provider), and mark/restore a unit
   INVALID. All should succeed.
3. Repeat step 2 through `npm run dev` at `http://localhost:5173/`.
4. If NAS access is intended, repeat step 2 from another device by hostname,
   directly and through any reverse proxy.
