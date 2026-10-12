# FLH-056 — Integrated E5 service and live endpoint acceptance

Owner: NAS Codex. Date: 2026-10-12. Actual `pwd`:
`/home/worldvanquisher/workspace/flh-nas-codex` (Linux).
Supplied branch: `test/flh-056-live-e5-acceptance`; supplied integrated baseline:
`26a3221` / FLH-054. These are human-supplied identifiers, not Git observations.
AGENTS.md and the implemented FLH-054 plan, validation, service, encoder,
manifest, golden fixtures, Go renderers and HTTPProvider were read.
No Git/GitHub commands, downloads, installation, credentials, personal/daily
records, evaluation runs, index builds or service/proxy configuration changes.

**ACCEPTED for bounded synthetic E5 service/endpoint contract verification.**
One independently reproduced integration reporting defect remains below;
complete production search metadata parity is **NOT ACCEPTED**. This does not
establish semantic quality, production retrieval policy, browser acceptance or
independent Windows/GPU runtime acceptance.

## Adjudication

| Requirement | Expected / actual | Decision |
| --- | --- | --- |
| Deployment | Exact supplied identity; canonical manifest digest and LF-normalized local vector-code hash match | Pass |
| Renderers/roles | Unit query + Concepts, document-only permutations, search-v2 English/French; role from representation/type, prefix once | Pass in independent fake tests; live role-counter deltas agree |
| Positive responses | Five 200 responses; ordered contiguous indices, matching response model; eleven finite/nonzero normalized 768-D vectors | Pass |
| Repeats/permutations | Fixed coordinate tolerance `1e-5 + 1e-4*max(abs(a),abs(b))`; norm tolerance .001 | Pass; maximum repeat difference **0**, observed norms **1.0000000052515226–1.0000000338764774** |
| Unknown model | One request → 400 `unknown_model`, no encoder work | Pass; Go probe exit 1, expected refusal |
| Raw text | One request → 422 `invalid_input`, no encoder work | Pass; Go probe exit 1, expected refusal |
| Accounting | Seven requests, five OK, two refusals; eleven accepted positions (query 4 / passage 7), five computations, zero truncations/overlength | All fresh counter deltas match |
| Endpoint confinement | Explicit CGNAT opt-in; IP literals only; no public addresses, credentials, ambient proxies or redirects | Local boundary tests pass; actual supplied endpoint used |
| HTTP query representation | Actual v2 input/report should be advertised as v2 | **Medium defect: HTTP reports v1** on root and `/api`; reproduction below |

## Concrete defect

`internal/transport/http/semantic_search.go:118` hardcodes
`application.ConceptSearchQueryRepresentationV1`, while
`internal/application/semantic_search.go` renders v2 and returns
`report.QueryRepresentation = concept_search_query_v2`. Every successful
semantic-search HTTP response can therefore misdescribe the text embedded.
Impact: false representation provenance for consumers/audits; no evidence of
wrong role prefixes or vectors in the live requests tested here.

An owned, read-only Go overlay injects
`scripts/validation/flh053/http_metadata_probe_test.go.txt` as
`internal/transport/http/flh056_metadata_acceptance_test.go`. The fake application
report explicitly supplies v2; the **actual transport handler** returns v1 on
both root and workbench-prefixed routes. Expected acceptance exit 0; actual
exit **1**, twice reporting `expected concept_search_query_v2, actual
concept_search_query_v1`. The test is an unmet expectation, not a passing
snapshot of the defect. This dependency was already disclosed by FLH-054 and
is independently confirmed here, without patching it.

Suggested owner revision: serialize `report.QueryRepresentation`, update the
transport assertion and maintained contract documentation, then rerun this
probe. No production file was changed.

## Executable probe changes and independent offline evidence

Changed only the owned FLH-053 directory and this report:

- `fixtures.go`: search-v2 English/French envelopes replace historical raw-search
  positives; `raw-negative` retains the unsupported input as a deliberate refusal.
  Actual production index and embedding-retriever renderers still produce the
  Unit/Concept inputs; their document strings agree byte-for-byte.
- `probe_test.go`: explicit CGNAT range boundaries and three shared golden search
  cases compare the mirrored envelope with the actual production renderer,
  including escaped characters and Concept-looking user text. Existing provider
  blind-spot/failure/cap/timeout/output tests remain.
- `main.go`: explicit `-allow-tailscale-cgnat`; safe response evidence includes
  indices, response-model equality and only allowlisted rejection types.
  Provider errors are categorized; arbitrary `error.type`/bodies are not echoed.
- `accept_e5.py`: default is the **actual service with its injected fake encoder**,
  not a replacement server. It checks six accepted/22 rejected golden inputs,
  original-string prefixing, all eleven provider-returned vectors against
  prefix-derived fake vectors, ordering and repeats, role counters, raw/unknown
  refusals, and six encoder failures (OOM/error/NaN/unnormalized/short/count).
  Each failure makes exactly one attempt; no retry/fallback. Fake thread and
  encoder are closed. The live mode retains expected/actual evidence and reserves
  its entire planned budget before POSTs; an existing reservation blocks reruns.
- `README.md`: changed expectations, offline execution, CGNAT opt-in, live guard
  and defect reproduction. Historical FLH-053 plan and FLH-051 report preserved.

HTTPProvider itself appends `/embeddings`, sends `model` plus ordered `input`
strings, rejects non-200/malformed JSON/count/index/equal-dimension/nonfinite
failures and restores response order by index. It does **not** enforce configured
768 dimensions, zero norm, normalization, explicit missing/null index presence,
repeat consistency or response-model identity. Additional probe/driver checks
cover those distinctions; provider acceptance alone is insufficient. Existing
provider `error.type` echo remains a documented blind spot, masked in this probe.
The probe disables proxies/redirects through its own supplied HTTP client;
this is not a claim that production HTTPProvider universally disables them.

The supplied service's **31 fake tests** passed independently on Linux, including
readiness after warmup, 512/513 token boundary, bounded queue/timeouts, malformed
vectors, failures without retry, connection limits, safe metrics, manifest
identity and owned fake shutdown. The independent driver also passed, separately
from those supplied tests. No Python model dependencies were needed or loaded.
Production Go golden/index/search tests passed. Six top-level Go probe tests
(including 21 failure-mode subtests) passed with `-race`; scoped vet and formatting
checks passed. README.zh-CN.md exists; root README behavior was not changed.

## Actual endpoint evidence and budget

Base: `http://100.118.109.6:8765/v1`. Exact deployment:

```text
multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/dd0889c6f1869f7f
```

The earlier three successful readiness/manifest/metrics GETs remain in
`/tmp/flh056-discovery/`. The manifest was reused, not fetched again. Resumed
verification read fresh readiness and metrics before/after POSTs; their state
and deployment match the retained manifest. Its canonical digest is
`dd0889c6f1869f7fe3bcaf85e40713b99cd21812342155be9eac55222313bb56`;
local `contract.py`, `encoder.py`, `manifest.py` code hash is
`96ab7c27ec6e18ec98cbafd3c8f3aac39c72f317110b98887d24d95d5e466bc0`.
Pinned file sizes/digests agree with the implemented pins. This checks public
manifest/source consistency; the agent did not read Windows model files.

| Service counter | Before | After | Delta |
| --- | ---: | ---: | ---: |
| requests_total | 1 | 8 | 7 |
| requests_ok | 1 | 6 | 5 |
| accepted input_positions | 2 | 13 | 11 |
| query / passage | 1 / 1 | 5 / 8 | 4 / 7 |
| computations | 1 | 6 | 5 |
| invalid_input / unknown_model refusals | 0 / 0 | 1 / 1 | 1 / 1 |
| distinct input hashes | 2 | 7 | 5 |
| truncations / overlength | 0 / 0 | 0 / 0 | 0 / 0 |

Live request inventory: Unit/Concept mixed (3), document-only reordered/repeated
(3), English search-v2 (1), French search-v2 (1), repeated mixed (3), unknown-model
refusal (1), raw-text refusal (1). **7/8 requests and 13/24 submitted positions**
used; **11 accepted positions**, two rejected requests counted separately.
No automatic retries, tolerance changes or further live embedding calls.
The remaining 1 request/11 positions were not consumed. The one-shot guard at
`/tmp/flh056-live-post-reservation.json` was independently checked to refuse
before network access; do not delete it to rerun this task.

Human observations remain attributed: Windows RTX 4070 load on cuda:0/float16,
local smoke and Tailscale forwarding. The endpoint's metrics independently
returned `parameters_on_device: true`, `parameter_dtype: float16`, training false,
GPU name RTX 4070 Laptop and 8,585,216,000 bytes total memory. These are remote
service-reported measurements, not independent hardware attestation or execution
of Windows startup/shutdown scripts. Neither the human's service nor proxy was
stopped; only task-created fake listeners were shut down.

## Commands, retained outcomes and hashes

All Go commands used cached dependencies:
`GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off`.
All Python runs used `python3 -B`. No package installation/download occurred.

| Exact command (from repository root) | Result |
| --- | --- |
| `pwd` | Path recorded above |
| `go build -o /tmp/flh053-probe-flh056 ./scripts/validation/flh053` | Exit 0 |
| `go test ./scripts/validation/flh053 -race -count=1 -v` | Exit 0; retained `/tmp/flh056-go-tests.txt` |
| `go vet ./scripts/validation/flh053` | Exit 0 |
| `gofmt -l scripts/validation/flh053/*.go` | No output |
| `python3 -B -m unittest discover -s tools/embedding/e5/tests -t tools/embedding/e5 -v` | Exit 0, 31 tests; `/tmp/flh056-service-tests.txt` |
| `go test ./internal/application -run 'TestConceptSearchQueryEnvelope_MatchesGoldenWireBytes\|TestConceptEmbeddingRepresentations_UnchangedAgainstGolden\|TestSemanticSearch_SendsVersionedQueryEnvelope' -count=1 -v` | Exit 0, three tests; `/tmp/flh056-golden-go-tests.txt` |
| `python3 -B scripts/validation/flh053/accept_e5.py --binary /tmp/flh053-probe-flh056 --out /tmp/flh053-flh056-offline` | Exit 0; independent checks passed |
| `python3 -B scripts/validation/flh053/accept_e5.py --binary /tmp/flh053-probe-flh056 --out /tmp/flh053-flh056-offline-final` | Exit 0 after final driver guard/output changes; `/tmp/flh056-offline-driver.txt` |
| `python3 -B scripts/validation/flh053/accept_e5.py --binary /tmp/flh053-probe-flh056 --out /tmp/flh053-flh056-live --allow-live --base http://100.118.109.6:8765/v1 --manifest-snapshot /tmp/flh056-discovery/manifest.json` | Exit 0; independently reconstructed expected/actual outcomes pass; **historical command, do not repeat** |
| `go test -overlay /tmp/flh056-http-overlay.json ./internal/transport/http -run TestFLH056HTTPMetadataMatchesEmbeddedRepresentation -count=1 -v` | **Exit 1 expected defect evidence**, actual v1 on both routes; `/tmp/flh056-http-metadata.txt` |

Recreate the overlay without touching production, using a new isolated JSON file:

```sh
python3 -B - <<'PY'
import json
from pathlib import Path
root = Path.cwd()
Path('/tmp/flh056-http-overlay.json').write_text(json.dumps({'Replace': {
    str(root/'internal/transport/http/flh056_metadata_acceptance_test.go'):
    str(root/'scripts/validation/flh053/http_metadata_probe_test.go.txt')
}}))
PY
```

Full evidence is consolidated in `/tmp/flh056-evidence/`: 49 artifacts plus its
hash manifest, including earlier GETs, both offline runs, raw ordered live vectors,
negative reports, fresh metrics, exact subprocess commands/exits and source
hashes. These are synthetic task-local outputs, not repository fixtures.
Every listed artifact hash was independently verified. Key SHA-256 values:

| Artifact, relative to evidence directory | SHA-256 |
| --- | --- |
| `flh053-flh056-live/independent.json` | `396a4fa088a5f006787caa71a91a5a4ecdb9182b0b450f6bcc315fa3ccd7678a` |
| `flh053-flh056-live/positive/report.json` | `d03faec3e3f7a497535c791e915688d7a83bd822efaa661b7cdf19d2ad5f8ba7` |
| `flh053-flh056-live/manifest.json` | `b8b8e21231da90cf3068c3fc8993c8c06bdc270dac2fd45680305bb61da1de05` |
| `artifact-sha256.json` | `13de8d33ed2bec3598afa4b6853a1b62981abcc3879066433a76bcbda66a2732` |

The frozen FLH-045 fixture still hashes to
`92726376c7892ef5e7eb539648828eab3ccf9d026912a4a5509dc461c3b7043a`.
Source hashes record the inspected integrated baseline, not a fabricated
before/after preservation snapshot. Historical reports and frozen inputs were
not edited. No changes outside owned files were made.

Remaining requirements: fix and accept the HTTP representation provenance defect;
retain separate human Windows startup/shutdown and GPU evidence; obtain separate
authorization, human label adjudication and a bounded experiment plan before any
quality evaluation. These eleven accepted synthetic inputs do not justify a
semantic-quality claim, cache reuse under another deployment identity, or running
the 1,400-position evaluation. Ownership is handed back; editing stops at delivery.
