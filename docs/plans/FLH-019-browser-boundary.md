# FLH-019 — Browser request boundary

Owner: NAS Codex, explicitly assigned implementation ownership by the human.
Working directory: the human-provided `flh-nas-codex` working tree (actual
absolute directory reported in chat).
Status: complete; stopped for human review.
Requested branch label: `fix/flh-019-browser-request-boundary`; no Git/GitHub
commands or branch inspection. Date: 2026-10-08 (America/Toronto).

Read AGENTS.md, FLH-013 X1/X2, HTTP wiring, capture client, Vite proxy, release
documentation. No FLH-017 report was present at initial inspection or after the
first full test run. On continuation, the human reported FLH-017 merged as
PR #42, but `docs/validation/FLH-017-browser-request-boundary.md` was still
absent in the supplied working tree. The supplied findings about bodyless
provider/judgment POSTs, insufficient Content-Type enforcement, the successful
CrossOriginProtection prototype, and its DNS/Vite limitations informed the
additional checks below. No dependency on FLH-020. No subagents spawned.

## Ownership and acceptance

Exact files announced before edits:

- `internal/transport/http/browser_boundary.go`
- `internal/transport/http/browser_boundary_test.go`
- `cmd/server/main.go`
- `internal/config/http_boundary.go`
- `internal/config/http_boundary_test.go`
- `internal/config/config.go`
- `.env.example`
- `compose.yaml`
- `docs/RELEASE.md`
- This task note.

Compatibility criteria: protect root and /api-prefixed routes before services,
providers, or request-body decoding; preserve release same-origin requests,
bodyless POSTs, default Vite proxy and no-Origin CLI requests; permit explicitly
configured NAS DNS/IP access; no implicit trust in forwarded headers; no
annotation/business changes, authentication, CORS wildcard, retries, providers,
dependencies or frontend edits. Tests must prove blocked requests perform no
SQLite writes and no analyzer/extractor calls.

No schema, migration, domain/application contract, dependency, Makefile,
AGENTS.md, shared README or frontend changes. Both configuration settings are
necessary: Host protects arbitrary rebinding names, while trusted origins
support Vite's existing Host rewrite and explicit TLS reverse-proxy deployment.

## Reproduction before implementation

Isolated baseline source and database: `/tmp/flh-019-0mt6qujj/baseline` and
`baseline.db`; HTTP process stopped after probes. Clean constructed environment,
rule-based analyzer, disabled extraction/embedding, dynamic loopback port, no
.env or daily database reads.

`/tmp/flh019-baseline.py` compiled the unchanged server, served a minimal synthetic
workbench, then issued requests recorded in `baseline-results.json`:

| Probe | Confirmed server behavior |
| --- | --- |
| POST /entries, Origin https://attacker.example, text/plain JSON body | 201; synthetic entry persisted |
| POST /api/captures, same cross-origin/plain headers | 201; synthetic capture and entry persisted |
| GET /api/entries, Host attacker.example:<isolated-port> | 200; both synthetic entries returned |

These are HTTP probes, **not** an executed browser attack or DNS rebinding
exploit. No Chromium, Chrome, or Firefox executable was available. Real-browser
checks are NOT RUN.

## Implemented boundary

The server wraps its complete final handler (API-only or workbench) once, before
mux routing and prefix stripping. Unknown/malformed Host is a secret-safe JSON
403 on every method, including reads and workbench delivery. Host matching does
not resolve DNS or accept suffixes, subdomains or forwarding headers.

Unsafe methods require a valid same-origin or explicitly trusted Origin when
Origin is present. Null/empty/multiple/malformed origins fail even with claimed
same-origin Fetch Metadata. Scheme and port participate in the comparison; TLS
is determined directly from the connection. Go's `net/http.CrossOriginProtection`
also rejects cross-site/same-site Fetch Metadata without an explicit trusted
Origin. No bypass route patterns or CORS response permissions are added.
Browser mutation bodies must use application/json, with valid media-type
parameters allowed. Bodyless POSTs are retained. Requests with no browser
Origin/Fetch Metadata retain existing CLI content-type behavior. Safe methods
retain their read-only behavior after Host validation.

Configuration rules are maintained in docs/RELEASE.md and .env.example:

- HTTP_ALLOWED_HOSTS: always includes localhost, 127.0.0.1 and ::1; nonempty
  comma-separated entries add exact ASCII DNS names or IP literals. No port,
  scheme, wildcard, path, trailing dot, underscore, IPv6 zone or empty item.
  Host authorities support bracketed IPv6 and ports 1–65535. No network ranges.
- HTTP_TRUSTED_ORIGINS: empty/unset defaults to http://localhost:5173,
  http://127.0.0.1:5173 and http://[::1]:5173. Nonempty lists replace defaults.
  Exact HTTP(S) origins only, with validated host/port, no credentials, path,
  trailing slash, query, fragment or wildcard. Normalize DNS case, IP literals
  and default ports. Invalid settings stop startup without echoing their values.

Compose forwards these two settings; its loopback publish rule remains intact.
NAS exposure/listening configuration is independent. An approved NAS host can
make direct same-origin requests without a trusted-origin exception. TLS proxies
can use an explicit advertised trusted origin and approved Host; spoofed
Forwarded/X-Forwarded headers alone do not grant access.

This is browser protection, **not authentication**. Non-browser clients can
forge/omit these headers. An approved host and explicitly trusted development
origins remain trusted; network restrictions still matter. The Host allowlist
rejects arbitrary unapproved rebinding names, but performs no DNS pinning or
DNS-control verification. An attacker-controlled explicitly approved hostname
can still rebind and pass Host/same-origin checks. Only approve names you control;
literal IP entries avoid that DNS-name gap.

## Validation evidence

All checks below passed. Evidence is retained at `/tmp/flh-019-0mt6qujj`:
`checks.log`, `baseline-results.json`, `smoke-commands.log`, `smoke-results.json`,
`vite.log`, `api-only.log`, `health.log`, isolated source copies and synthetic databases.
All child processes use a constructed environment, not inherited provider
settings: analyzer rule-based, extraction/embedding disabled, credential/model/
provider URL/timeout variables empty, temporary HOME/DOCKER_CONFIG and existing
Go module cache. Every Compose call uses `--env-file /dev/null`. No production
.env, daily database or paid provider was used.

Executed via the temporary isolated-copy wrapper `/tmp/flh019-checks.py`:

```sh
go test ./internal/config ./internal/transport/http ./internal/captureclient
go test ./...
go vet ./...
go build -o /tmp/flh-019-0mt6qujj/server ./cmd/server
go build -o /tmp/flh-019-0mt6qujj/capture ./cmd/capture
```

The wrapper refreshed only the owned backend/config/Compose files in its source
copy before checking; no shared-tree builds or generated frontend outputs.
`gofmt -w` was limited to the six changed Go files; final `gofmt -l` returned
empty. Configuration tests validate defaults, additive hosts, replacement
origins, invalid settings, secret-safe errors and environment precedence.

Transport tests cover release/CLI/Vite/NAS requests, HTTP/TLS scheme and port
matching, IPv4/IPv6, bodyless and chunked requests, media types, invalid/null/
duplicate origins, Fetch Metadata, forwarded-header spoofing, OPTIONS, Host
suffix attacks, unknown/malformed hosts, and unchanged capture client calls.
The SQLite integration suite exercises all 16 mutation routes with both root
and /api prefixes and nine blocked variants (288 requests), including
bodyless requests with cross Origin, cross-site Fetch Metadata alone, and null
Origin plus misleading same-origin Metadata. `total_changes()`
on the repository's single SQLite connection stays unchanged after each
request; counted fake analyzer and extractor calls stay zero. Allowed analyzer
and extractor calls increment their counters and persist, proving those fakes
and services are actually reachable when permitted. Rejected chunked requests
never read the supplied body.

Packaging/native/proxy smoke executed by `/tmp/flh019-smoke.py`:

```sh
# Isolated source, unique image override, constructed environment:
docker compose --env-file /dev/null -p flh-019-0mt6qujj \
  -f /tmp/flh-019-0mt6qujj/source/compose.yaml \
  -f /tmp/flh-019-0mt6qujj/compose-override.yaml up -d --build
# Same transport used for subsequent up -d --force-recreate and down.
npm ci                       # isolated source/web only
# Actual unchanged Vite configuration, isolated strict port and backend URL:
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port <isolated-port> --strictPort
```

| Check | Observed |
| --- | --- |
| Packaged workbench, health/readiness | Successful delivery; both root/prefixed health routes preserved; Docker healthcheck explicitly reached healthy with NAS hosts and release-only trusted origin |
| Same-origin release mutations | 201 on both /entries and /api/entries |
| Actual compiled capture CLI | Root and /api base URLs succeed; replays also succeed on smoke reruns |
| Bodyless analysis/extraction | 201 local rule analysis; 503 default-disabled extraction |
| Cross-origin plain/JSON writes | 403 on entries, captures, analysis and extraction, root and prefixed |
| Null origins, same-origin plain body | 403 / 415 respectively |
| Rebinding-like Host read and static request | 403 despite matching attacker Origin/Fetch Metadata and spoofed forwarded headers |
| Blocked-request persistence | Complete contents of all SQLite tables identical before/after probe group |
| NAS defaults then explicit configuration | Unlisted NAS host 403; configured DNS/IPv4/IPv6 Host plus same Origin each creates a synthetic entry with 201 |
| Real Vite proxy | Trusted isolated frontend Origin succeeds (201) through existing Host/prefix rewrite; attacker Origin blocked (403) |
| API-only executable | No-web-dir mode allows no-Origin CLI write and blocks cross-origin write and attacker Host read |
| CORS | Go responses contain no CORS permission headers; OPTIONS remains 405. Vite retains its existing development CORS behavior, without wildcard in tested responses |
| Cleanup | Compose container/network removed, Vite and native API-only processes stopped; filtered docker ps -a returned no task containers |

Dedicated image `french-learning-hub:flh-019-0mt6qujj` and isolated evidence are
retained for review; no pre-existing image tag was replaced. Dynamic host/Vite
ports and final healthy observation are recorded in smoke-results.json. A final
SHA-256 comparison confirmed all six changed Go files exactly match the tested
and packaged source; release Bash blocks passed bash -n.

Validation harness corrections: initial sandbox listener restriction required
escalation for the authorized isolated HTTP tests; one synthetic capture ID
contained a slash and was corrected; one assertion wrongly applied the Go
no-CORS contract to Vite's existing development server and was corrected.
The failed attempts cleaned up their task containers/networks before reruns.
No production-code failure was found in those attempts.

NOT RUN: real-browser interaction or DNS rebinding attack; off-host NAS network
access (NAS/IP values were exercised as Host/Origin HTTP probes), real TLS reverse
proxy deployment (TLS/proxy policy is covered by transport tests), external
providers, no-cache/BuildKit build, or authentication. Docker used its available
legacy builder. These limits do not change the confirmed server probe results.

Implementation is complete and editing stops for human review. Existing FLH-013
build-context/permission findings and unrelated release work are outside scope.

## Continuation: exact project Go version and bodyless evidence

Verified the updated working tree using Go **1.26.5**, as declared in go.mod,
not just host Go 1.27.1. `/tmp/flh019-go126.py` made a fresh isolated backend
source copy and invoked the digest-pinned Dockerfile toolchain image:

```text
golang:1.26.5-alpine@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2
```

The container ran with `--rm --network none`, read-only source/module-cache
mounts, writable isolated output, `GOTOOLCHAIN=local`, `GOPROXY=off`,
`GOFLAGS="-mod=readonly -buildvcs=false"`, and `CGO_ENABLED=0`. Provider
credentials/settings were empty; the analyzer was local rule-based, extraction
and embedding disabled. Tests use fake/local providers inside the container.
The shell used `set -eu`; all commands below actually completed with exit 0:

```sh
go version                         # go1.26.5 linux/amd64
test "$(go env GOVERSION)" = go1.26.5
go mod verify                      # all modules verified
go test ./... -count=1
go vet ./...
go build -o /checks/server ./cmd/server
go build -o /checks/capture ./cmd/capture
go version -m /checks/server        # executable records go1.26.5
go version -m /checks/capture       # executable records go1.26.5
```

Fresh evidence: `/tmp/flh-019-go126-hay02zbn/go126.log`, source and output
binaries. The auto-removed test container exposed no host ports or external
network access. All six owned Go files match the verified source byte-for-byte;
formatting and release Bash syntax checks passed. Production implementation
and configuration behavior remain the existing FLH-019 changes; this
continuation adds rejection tests and clarifies documentation only. The earlier
packaging build already used that same Go 1.26.5 base; its HTTP/Vite/CLI/health
smoke evidence remains applicable to the unchanged production code.

`TestBrowserBoundaryBodylessProvidersAndJudgments` additionally creates a real
extracted unit with valid source analysis/admission evidence, then issues
bodyless analysis, extraction, INVALID, restore and RejectSame POSTs through
both route prefixes. Four origin/metadata combinations (40 requests) yield
403, unchanged SQLite total_changes and zero analyzer/extractor calls. An
additional blocked restore preserves an already recorded INVALID judgment.
Allowed bodyless controls record exactly two human judgments and call each fake
provider exactly once; this proves rejected targets were real and reachable.
The larger rejection matrix also adds the three bodyless variants to every
mutation route. No Content-Type header is used for these bodyless probes.

Vite compatibility was exercised through the actual unchanged proxy with HTTP
clients and exact trusted frontend Origin, **not a real browser**. Browser
executables remain unavailable; real-browser and actual DNS-rebinding attacks
are NOT RUN. Explicit NAS names/IPs were verified as server Host/Origin probes,
not off-host network deployment. DNS control of approved names remains the
operator's responsibility. No frontend/shared README edits, Git/GitHub commands,
new branch, subagents, daily database access or paid provider calls.

Editing stops for human review with the existing FLH-019 ownership unchanged.

## README handoff (outside this task's ownership)

README.zh-CN.md exists. Suggested English text for the human README owner:

> The HTTP service validates destination Host names and blocks inappropriate
> cross-origin browser mutations. Loopback access and the default Vite proxy
> work out of the box. For NAS names/IPs, configure HTTP_ALLOWED_HOSTS; for another
> Vite port or an explicitly trusted TLS proxy, configure HTTP_TRUSTED_ORIGINS.
> See docs/RELEASE.md for exact defaults and validation. This is browser-request
> protection, not authentication; keep the service on a trusted network.

Suggested Simplified Chinese companion text:

> HTTP 服务会校验目标 Host，并阻止不适当的跨源浏览器写请求。默认支持本机回环地址
> 和 Vite 开发代理。通过 NAS 主机名或 IP 访问时，请配置 HTTP_ALLOWED_HOSTS；使用其他
> Vite 端口或明确受信任的 TLS 代理时，请配置 HTTP_TRUSTED_ORIGINS。具体默认值和校验
> 规则见 docs/RELEASE.md。这些措施是浏览器请求防护，不是身份认证；服务仍应仅在
> 可信网络中使用。


Human-only staging command (displayed, never executed):

```sh
git add -- internal/transport/http/browser_boundary.go internal/transport/http/browser_boundary_test.go cmd/server/main.go internal/config/http_boundary.go internal/config/http_boundary_test.go internal/config/config.go .env.example compose.yaml docs/RELEASE.md docs/plans/FLH-019-browser-boundary.md
```

Suggested commit message:
`fix: protect HTTP service from cross-site browser requests`
