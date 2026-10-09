# FLH-033 — validation harness reliability and evidence accuracy

Date: 2026-10-09 (America/Toronto). Owner: NAS Codex, sole writer for this task.
AGENTS.md was read; actual pwd was the supplied flh-nas-codex workspace, reported
in chat. Human-supplied branch: fix/flh-033-validation-harness; no Git/GitHub
inspection or operations. FLH-031 F1/F2/F3 were used without repeating that
investigation or editing its helpers/reports. Claude's parallel FLH-032 frontend
recovery is outside this acceptance. No subagents were used.

## Changes and acceptance

| Finding | Expected | Actual |
| --- | --- | --- |
| F1 evidence | Preserve 128 observed results; correct compiler attribution | FLH-029 native loss run corrected to Go 1.27.1-X:nodwarf5; historical wrapper command/filename retained with explicit explanation. Separate pinned Go checks remain distinct |
| F1 selection | Explicit compiler, isolated environment, verifiable build evidence | Default resolves only isolated PATH; optional absolute executable `--go-binary` is native-only. Commands use resolved path; report records compiler path/hash/version and server build metadata/hash |
| F2 naming | Valid project/image independent of arbitrary directory suffix | UUID hexadecimal project/image names; deterministic fixture directory `flh026-_aditmt8` passes naming and owned cleanup assertions; real container workflow passes |
| F3 fidelity | Both duplicate header lines reach upstream | Ordered pair adapter preserves multiplicity; actual loopback upstream captures two keys and two Origins |
| F3 framing | No ambiguous upstream CL/TE | Reject Transfer-Encoding, duplicate Content-Length, and malformed/negative lengths before forwarding; strip framing/hop-by-hop/Connection-nominated headers; upstream generates one Content-Length from bytes |
| F3 persistence | Server rejects duplicates without mutation | Root and `/api`: duplicate Idempotency-Key → 400, duplicate Origin → 403; entire SQLite snapshots and both fake-provider counters unchanged in native and container probes |

`HeaderPairs` retains raw pairs internally, iterates names for HTTPConnection's
preflight, and yields every pair from `items()`. No annotation header becomes a
dictionary. Existing ownership-checking callbacks remain unchanged. Existing loss
modes, explicit retries, response handling and task-owned cleanup remain intact;
no new automatic retry or arbitrary upstream configuration exists.

## Exact owned files

- `scripts/validation/flh026/run.py`
- `scripts/validation/flh026/test_harness.py`
- `scripts/validation/flh026/README.md`
- `scripts/validation/flh028/proxy.py`
- `scripts/validation/flh028/test_proxy.py`
- `scripts/validation/flh028/README.md`
- `docs/validation/FLH-029-annotation-idempotency.md` (evidence correction only)
- `docs/plans/FLH-033-validation-harness.md`
- `docs/validation/FLH-033-validation-harness.md`

No production Go, migration, dependency manifest, frontend, FLH-030/031 report,
or shared project documentation was modified. README.zh-CN.md exists and remains
unchanged alongside README.md; neither English README behavior nor setup changed.

## Executed commands and final results

```sh
python3 -B scripts/validation/flh026/test_harness.py
python3 -B scripts/validation/flh028/test_proxy.py
python3 -B scripts/validation/flh026/run.py --go-binary /usr/bin/go --report /tmp/flh033-native-handoff.json
python3 -B scripts/validation/flh026/run.py --mode container --report /tmp/flh033-container-handoff.json
python3 -B scripts/validation/flh028/reproduce.py --report /tmp/flh033-loss-native-final.json
python3 -B /tmp/flh033-container-loss.py
```

| Final evidence | Result / total |
| --- | --- |
| `/tmp/flh033-harness-tests-handoff.log` | PASS, eight tests |
| `/tmp/flh033-proxy-tests-handoff.log` | PASS, ten tests, including four native application duplicate-header probes |
| `/tmp/flh033-native-handoff.json` | PASS, eight established daily-workflow checks |
| `/tmp/flh033-container-handoff.json` | PASS, eight established daily-workflow checks, including replacement/down-up/build and backup/restore |
| `/tmp/flh033-loss-native-final.json` | PASS, 128 cases: 104 established unkeyed + 24 keyed loss/retry cases |
| `/tmp/flh033-loss-container.json` | PASS, 132 cases: same 128 + four duplicate-header probes |

The temporary container adapter is retained at `/tmp/flh033-container-loss.py`.
It imports the read-only FLH-031 `Verification.forward`/`wire` adapter, invokes
only the inherited established `run()` matrix, and adds the four proxy duplicate
probes. It uses the repaired FLH-026 names without overriding them. It does not
invoke FLH-031 extra checks, helper suites or baseline comparison. Reports include
private tested source SHA-256 inventories and all recorded command outputs.
Container builds necessarily package a frontend snapshot; this is packaging/API
transport evidence, not acceptance of unintegrated FLH-032 frontend behavior.

The initial successful native/container daily-workflow reports remain at
`/tmp/flh033-native.json` and `/tmp/flh033-container.json` (eight checks each).
Final handoff runs verify the preserved single-argument launcher hook used by
read-only FLH-031 adapters, with explicit compiler selection applied afterward.

Native preparation executed compiler module verification, build, compiler version
and server metadata queries under the existing offline isolated environment.
Native compiler resolved from explicit `/usr/bin/go` to `/usr/lib/go/bin/go`:

```text
compiler: go version go1.27.1-X:nodwarf5 linux/amd64
compiler SHA-256: 678de66bea2ad8ae67f23b7faa63e1bab32dd21a406bb0c224de853a64480117
native server metadata: go1.27.1-X:nodwarf5; CGO_ENABLED=0; GOEXPERIMENT=nodwarf5
native server SHA-256: 2981b9b2534d79fa92b1f4cfe1418dccf9cdd9ae79e3defe0c8a115a22fd0647
container compiler: go version go1.26.5 linux/amd64
container server metadata: go1.26.5
container server SHA-256: 3627bd6cd16d585940046bd0e1b1247695ad87e1598569081e9767e8c94d256e
```

Container compiler verification ran the installed release-pinned image with
`docker run --rm --network none --pull never`:
`golang:1.26.5-alpine@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2`.
The adapter copied `/app/server` from its verified owned application container,
then ran the host compiler's `version -m` to inspect embedded build information.
The metadata identifies the binary's compiler, not the inspecting host compiler.
Release packaging uses its pinned Node 24.11.1 build stage; no independent
frontend suite or FLH-032 validation is claimed. No native run is labeled pinned
based on caller PATH, requested filename or wrapper alone.

## Initial failures remain separate

The initial sandbox safety attempt could not create sockets: eight harness tests
had three environment errors; nine then-existing proxy tests had nine environment
errors. Five socket-free harness tests passed. No application result is inferred
from that attempt. Authorized local-socket execution subsequently passed.

`/tmp/flh033-proxy-tests-initial.log` retains the first unsandboxed proxy run:
eight mechanism tests passed, one owned-server test errored. My initial adapter
iterated pairs where this Python HTTPConnection requires names, causing a fixture
request disconnect. `/tmp/flh033-loss-native.json` independently retains FAIL,
zero cases, RemoteDisconnected, cleanup_errors empty and directory removed.
The adapter was corrected; `/tmp/flh033-proxy-tests-final.log` then passed all nine
then-existing tests. An additional actual-upstream wire/framing test brought the
final suite to ten passing tests in `flh033-proxy-tests-complete.log`.
A final targeted rerun after test formatting and unconditional server cleanup
passed eight harness tests and ten proxy tests in the handoff logs listed above.
No production behavior was patched and failed evidence was not overwritten.

## Cleanup and limitations

All four final workflow/matrix JSON reports show `cleanup_errors=[]` and
`temporary_directory_removed=true`. Native server/provider and proxy listeners
and threads were stopped. Container cleanup removed only owned project
containers/network and unique application image tags; shared base images and
Docker build cache remain. The inspected server copy was inside the removed
owned directory. Temporary adapter, logs and JSON evidence remain under `/tmp`.
Safety tests assert cleanup on failure and refusal of an unowned native listener.
Only synthetic fixtures, fresh private SQLite databases and local fake providers
were used; no daily data, secrets, paid calls or permanent dependencies.

This is harness/backend HTTP evidence. No real browser, frontend recovery
acceptance, full Go/frontend suite, production deployment, arbitrary chunked
proxying, power loss, disk exhaustion or sustained load was tested. Native Go
1.26.5 was not selected in this session; Go 1.26.5 evidence is the container build
and inspected binary. The proxy remains a local controlled fixed-length fixture,
not a general-purpose reverse proxy. SIGKILL/daemon failure cannot guarantee
cleanup. Editing stops at handoff for human integration.
