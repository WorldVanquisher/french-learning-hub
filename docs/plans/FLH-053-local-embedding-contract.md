# FLH-053 — Windows GPU embedding service contract and executable acceptance

2026-10-12. Owner: NAS Codex. Actual `pwd`:
`/home/worldvanquisher/workspace/flh-nas-codex`. Read `AGENTS.md`; no Git/GitHub
commands or subagents. Branch `test/flh-053-local-embedding-contract` is supplied
by the human and not inspected. Owned scope is this plan and
`scripts/validation/flh053/{main.go,fixtures.go,probe_test.go,README.md}` only.
No production/provider/configuration/dependency/shared-doc/fixture change.
FLH-052's runner ownership is separate; its files were inspected, never edited
or awaited. Acceptance preparation is complete; actual service/GPU acceptance
is **NOT RUN**, because no endpoint/runtime/model revision has been supplied.

## Existing request and response contract

Inspected `internal/embedding/http.go`, `concept_embedding_retrieval.go`,
`semantic_index.go`, `semantic_search.go`, relevant configuration and HTTP error
mapping, and FLH-048's HTTPProvider/counter path.

```json
{"model":"caller-selected-model-or-deployment","input":["text at position 0","text at position 1"]}
```

`POST strings.TrimRight(baseURL, "/") + "/embeddings"`; for example a base
ending `/v1/` produces `/v1/embeddings`. Supplying a complete `/embeddings` URL
would append it again. No automatic `/v1` insertion. Content-Type is
application/json. The model field is exactly the configured model string;
production `EMBEDDING_MODEL` is a wire selection, not verified weights identity.
An optional configured key becomes a Bearer header; the FLH-053 probe reads and
sends no key. Empty input makes no HTTP request and returns an empty vector list.

Successful response is HTTP **200**, with:

```json
{"data":[{"index":1,"embedding":[0.0,1.0]},{"index":0,"embedding":[1.0,0.0]}]}
```

Every input needs one explicit integer index 0…N−1 and one numeric vector.
Items may be out of order; Go restores original input order by index. Request
order is preserved in the wire array. HTTPProvider rejects count mismatch,
duplicate/out-of-range indices, empty vectors, dimensions inconsistent within
one response, non-finite/unrepresentable float64 values, malformed JSON,
non-200 statuses and error envelopes. It limits response reads to 16 MiB.
Dimensions are not specified in its request, and it does **not** enforce a
model's configured dimension across calls or normalize vectors.

| Existing layer | Additional behavior / limit |
| --- | --- |
| HTTPProvider | Configurable client timeout; production default 8s. No application retry or fallback. Typical errors wrap provider-unavailable or provider-timeout. Empty/canceled calls are bounded by context. Default Go HTTP client behavior can follow redirects. |
| Unit/Concept embedding retriever | One batch of query followed by all candidate documents, validates equal-dimensional finite vectors, computes cosine, excludes zero norms/nonpositive results. No configured dimension or persistent cache in this path. |
| Production index/search | `ValidateEmbedding` checks configured dimension, finite float32-compatible values and nonzero float64 norm, then converts to float32. It does not L2-normalize. Index uses sequential document-only batches, default 32/max 256; search sends one trimmed raw string, bounded by the 200-byte Library query boundary. |
| FLH-048 embedding path as inspected | Calls the existing retriever/HTTPProvider, counts requests/input positions/unique hashes and stops on first error. Planned frozen package is 56×25=1400 positions; explicit cap required. Optional configured dimension check. No E5 prefix adaptation. FLH-052 changes are not assumed accepted by this task. |

HTTPProvider normally avoids returning keys, request texts or provider bodies,
but its `error.type` string is echoed without sanitization. The owned test
reproduces this with a synthetic marker. Public semantic-search HTTP errors map
to fixed 502/504 categories; callers retaining raw provider error strings must
not assume complete detail sanitization. The probe retains categories/hashes
only. Omitted/null `index` can default to int zero: provider alone is not an
explicit-index-presence validator. The probe's response observer adds that check
without changing provider decoding. No provider patch was made.

## Candidate only: multilingual-e5-base and role adaptation

The model author's card describes 768-dimensional output, query/passage
retrieval prefixes even for non-English text, attention-mask mean pooling,
L2 normalization and a 512-token limit. These make it a candidate worth evaluating,
not an accepted model or a guarantee of fit on the supplied approximately 8 GiB
RTX 4070 Laptop. GPU memory/latency must be observed for the selected dtype and
bounded batch sizes. [Official model card](https://huggingface.co/intfloat/multilingual-e5-base).

| Caller | Exact role signal visible in existing wire text | E5 implication |
| --- | --- | --- |
| Unit-to-Concept experiment / M12 retriever | Each serialized JSON string has `representation: concept_embedding_text_v1`; `type: query` for the Unit, `type: concept` for every Concept. Query includes canonical, statement, example, derived target/intent/scope/features; documents contain identity semantic fields. Sorted feature pairs; no IDs/judgments/labels. | Role can be derived from the recognized structured schema for **this caller**, not first-array-position. Query→`query: `, Concept→`passage: ` under an explicit asymmetric contract. |
| Document indexing | `BuildSemanticIndexDocument` uses the same Concept JSON renderer. Every input is `type: concept`. Batches contain only missing document hashes, in the index's chosen hash order; no query at position zero. | Every element needs passage treatment, including element zero and singleton batches. |
| Free-text semantic search | Provider receives `[]string{q.Text}` as raw trimmed user text. `concept_search_query_v1` exists as an application constant but is **not transmitted** as a wrapper/field. | No reliable wire role. Raw user text may itself be a Concept JSON string. The owned test constructs a real minimal document that passes the actual 200-byte query validator, proving ambiguity within the current boundary. |

The proposed **smallest explicit future contract** keeps HTTPProvider's wire
shape and provider interface unchanged:

1. Give semantic-search queries a versioned string envelope, for example
   `{"representation":"concept_search_query_v2","type":"query","text":"<original trimmed text>"}`.
   The owning production task must implement this at the search embedding call
   and version its query representation. This task does not implement it.
2. Give the Windows adapter an explicit convention ID, e.g.
   `flh_e5_role_prefix_v1`. Accept only recognized representation/type pairs:
   existing Unit query, existing Concept document, and the proposed search query
   envelope. Validate shapes; reject unwrapped/unknown text instead of guessing.
3. Prefix the original serialized envelope bytes once: query type→`query: `,
   Concept type→`passage: `. No array-position rule, label access, fuzzy inference
   or implicit provider-wide default. Keeping whole canonical JSON preserves
   existing evidence; its semantic suitability still needs a later experiment.
4. Freeze pooling/normalization/tokenizer/truncation/dtype and the adapter's code
   identity. Do not switch to natural-text extraction, a symmetric query/query
   convention, double prefixing or another pooling method under the same identity.

This is a proposal for an independently owned adapter/search change, not a
competing implementation. The model card also distinguishes symmetric tasks;
this proposal chooses asymmetric query-to-catalog retrieval explicitly. No E5
prefix is added by the probe. Its plain mode is transport smoke only. Rendered
mode includes the current raw-search gap: a strict future role adapter should
fail there until the caller contract is changed. Preserve that failure.

## Deployment/cache identity

The cache key is document content hash + representation + explicit ModelID +
dimension; collection space is derived from representation/ModelID/dimension.
Neither a mutable model alias, endpoint address nor the separate wire model
field establishes immutable cache identity.

Require a public deployment manifest containing weights repository and immutable
commit, tokenizer revision, adapter/convention version and code hash, pooling,
normalization, dtype, max tokens/truncation behavior, library/runtime versions
and output dimension. Hash its canonical bytes and use a **new explicit
deployment/model identity** for any vector-producing convention/configuration
change. For example `e5-base:<revision>:flh_e5_role_prefix_v1:<manifest-sha>` is
an illustrative format, not a supplied identity (keep actual ModelID ≤200 bytes).
Select that exact deployment in the wire model field and use its immutable
identity for `EMBEDDING_MODEL_ID` if persistent indexing is later authorized.

Prefixing or pooling changes alter vectors even when raw document content hash
and dimension are unchanged. A new ModelID creates a separate cache/index space;
rebuild/index that new space through the existing owned CLI. Never silently reuse
old cached vectors or relabel an existing collection as the new deployment.
No cache/configuration/index operation was performed in this task.

## Executable acceptance and test distinction

Owned probe calls the current Go HTTPProvider with an explicitly supplied
client: no credentials/ambient proxy, no redirects, no reused connections, hard
request/input/byte bounds and bounded per-request/overall context. It observes
bounded response bytes while the provider reads, saves only hashes/statuses,
and stops after the first failure. This observer is not a model adapter.

| Response/scenario | Existing provider | Additional FLH-053 check |
| --- | --- | --- |
| Reversed indexed rows | Restores order | Repeats/permutation agree; fake expected vectors match each actual input |
| Malformed JSON, missing vector, duplicate/out-of-range index | Rejects | Category-only failure, exactly one request, no retry/fallback |
| NaN JSON / numeric overflow, unequal/empty vector | Rejects | Same failure handling; no metrics |
| HTTP 503 / slow response | Unavailable / timeout | Stop; raw body/type contents excluded from evidence |
| Omitted or null index at original position zero | Can accept as zero | Reject missing explicit index |
| Uniform wrong dimensions / zero vector / finite float32 overflow or underflow | Can accept | Fixed dimension, finite components and nonzero float64/converted-float32 vector checks reject |
| Scaled non-unit vectors | Accepts; no normalization | Optional explicit unit-norm requirement rejects |
| Repeat changes beyond tolerance | Accepts each response | Reject within/across-batch inconsistency |
| Provider error envelope with arbitrary error.type | Rejects but echoes type | Probe records safe provider-unavailable category only; blind spot tested |

Repeat tolerance is declared per coordinate: `abs(a-b) <= 1e-5 +
1e-4*max(abs(a),abs(b))` by default; optional unit-norm tolerance is .001.
Do not change tolerances after seeing failures without a new reviewed acceptance
record. A constant-vector service can pass consistency; this probe proves no
semantic discrimination, weight identity, prefixing, CUDA use or quality.

Real endpoint calls require `-allow-real-endpoint`, an explicit private/loopback
IP-literal base URL, model, dimensions and request/input limits. Plain inventory:
2 requests/6 positions. Rendered inventory: 5/11. Hard ceilings: 8 requests,
24 positions, 4096 UTF-8 bytes/input, 30s/request and 120s overall. Smaller caps
than the fixed inventory fail before networking. Default is the local fake.
No authentication support is added; do not supply a protected real endpoint to
this probe without a separately authorized credential-handling design.

## Bounded Windows startup and NAS handoff

No actual service command exists in the supplied baseline; the runtime owner
must supply the executable/command. These are future acceptance criteria:

| Gate | Required observation |
| --- | --- |
| CUDA verification, after installation finishes | Record torch version, torch CUDA version, `torch.cuda.is_available()`, device name/total VRAM and a real CUDA tensor computation followed by synchronize. `nvidia-smi` records driver/GPU state. Availability alone is insufficient. |
| Model loaded on GPU | Exact immutable model/tokenizer revision and manifest; model eval/inference mode, selected dtype and masked mean pooling/normalization policy. Record CUDA placement, measured allocated/reserved/peak VRAM and device activity during the counted probe. No silent CPU fallback. No assumption that 8 GiB guarantees a chosen batch. |
| Explicit startup binding | First local verification may bind 127.0.0.1. NAS access requires the owner's chosen Windows private IP and port; supply the actual startup command with that explicit bind. Do not bind a public address or infer a server launch command. |
| Private connectivity | Human confirms Windows network profile/routing/firewall policy already permits the approved NAS-to-private-IP/port access. Loopback success is not NAS reachability. No firewall rule, router forwarding or public-port change is made here. |
| Readiness after load | Propose root GET `/readyz`: 503 while loading/unavailable; 200 only after CUDA placement, exact weights/adapter load and bounded warmup. A public manifest/hash identifies that ready deployment. HTTPProvider itself probes no readiness route, so the runtime owner must expose and document it. |
| Request contract / limits | POST `<base>/embeddings`, exact model/deployment match or explicit 4xx, contiguous explicit indices, finite nonzero vectors of declared dimension. Proposed initial service ceiling: 32 inputs and 4096 UTF-8 bytes per text, plus a documented token/request-body limit. Measure small batches first; approve larger batches only after VRAM observation. FLH-048 frozen mixed batch is 25; index default is 32. Larger production catalog/max-256 indexing calls require a separate compatible limit decision. |
| Truncation / timeout | E5 candidate limit is 512 tokens including prefix/envelope overhead. Declare rejection versus truncation and count observed truncations; never silently change policy. Bound queue, inference and HTTP timeouts; oversized requests/OOM/timeouts fail explicitly, without retry or alternate model/CPU fallback. |
| Counters / repetition | Record requests, input positions, distinct rendered hashes, actual computations, errors/refusals and truncations before/after; compare with probe counters. Repeated input/permutation tolerance must be declared for the chosen runtime/dtype. No learning content or credentials in logs. |
| Shutdown | Owner stops the owned service; readiness becomes unavailable, port/listener exits and GPU allocation is released. Record PID/start command and cleanup. No background process or permanent autostart is created by this task. |

Example **future human-run** CUDA smoke check (no model download or installation):

```powershell
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available()); assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0), torch.cuda.get_device_properties(0).total_memory); x=torch.ones((2,2),device='cuda'); y=x@x; torch.cuda.synchronize(); assert y.eq(2).all().item(); print(y.device)"
nvidia-smi
```

Actual Windows startup/NAS invocation waits for exactly these human inputs:

1. Successful CUDA computation output, GPU/VRAM/driver and isolated environment
   identity after the ongoing PyTorch installation.
2. Chosen model and **immutable weights/tokenizer revision**, plus approved
   download source/location/size and download/run scope. Candidate name alone
   grants no model-download or service-run authorization.
3. Chosen runtime/service command, dtype, pooling, normalization, role adapter
   contract/code version, truncation and bounded batch/request policy; public
   manifest and immutable deployment/model identity.
4. Exact Windows private IP, bind address, port, base URL (excluding embeddings
   suffix), wire model selector, readiness route and NAS access confirmation.
5. Explicit endpoint-probe scope/input/request budget and numeric tolerances.
   Role-envelope production ownership/approval remains needed for E5 integration.

## Executed evidence and handoff

Linux amd64; cached Go `go1.27.1-X:nodwarf5`. Executed from actual pwd:

```sh
gofmt -w scripts/validation/flh053/main.go scripts/validation/flh053/fixtures.go scripts/validation/flh053/probe_test.go
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off go test ./scripts/validation/flh053 -race -count=1 -v
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off go vet ./scripts/validation/flh053
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off go build -o /tmp/flh053-probe ./scripts/validation/flh053
/tmp/flh053-probe -out /tmp/flh053-plain-final
/tmp/flh053-probe -payload rendered -require-unit-norm -out /tmp/flh053-rendered-final
```

Results: **4 top-level tests + 21 loopback subtests pass, including race checks**;
vet/build exit 0. Plain fake: exit 0, 2 requests/6 positions. Rendered fake: exit
0, 5 requests/11 positions. Explicit-endpoint CLI path was also self-tested
against a counted loopback fake only. Invalid caps/URL/opt-in/timeouts/tolerance
and overwrite/symlink protections pass; no refused configuration contacts a
service. Each failing response stops honestly; no provider was patched to pass.
Outputs retain ordered vectors and hashes under the two isolated directories.

| Final local-fake artifact | SHA-256 |
| --- | --- |
| `/tmp/flh053-plain-final/report.json` | `96714a11fb82abcaf37c99e9bdccf057da87b63ec907e4a6f82a24d27224096b` |
| `/tmp/flh053-rendered-final/report.json` | `bb51a71901c19b4549a6f22516f41cb5b50cade69d170ce8283e92503f4cbd9f` |

Each directory's `sha256.json` independently matches its retained report bytes.
Initial fake outputs also remain under `/tmp/flh053-plain` and
`/tmp/flh053-rendered`; they were not overwritten. Owned-file newline/whitespace
checks passed, `gofmt -l` printed nothing, and `README.zh-CN.md` exists (no shared
README behavior changed). No owned generated output or bytecode is committed.

Read-only identity anchors:

| Input | SHA-256 |
| --- | --- |
| HTTPProvider | `1bea0ee93479e7c1f84f5a799667402f6ab78fb76d092aa3a96c6590ec6710c2` |
| Unit/Concept renderer | `234d8ee5d17c05c0474a6f4102ceed7659cde9ff3cc024aa4a956f1cd17ff30d` |
| Semantic index | `0fd11f40ed8321f0c2de7905e7b957277467ae6f7b88eb1559699522fce139f4` |
| Semantic search | `a353baf0f39b8daece2fb88262aa82f7159bcde06527ff5f05a6f4c48454dc21` |
| Frozen FLH-045 fixture | `92726376c7892ef5e7eb539648828eab3ccf9d026912a4a5509dc461c3b7043a` |

Fake listeners close on exit; no runtime/server installation or live Windows/
GPU/model/semantic acceptance was performed. No frozen proposal becomes human
approval. Delivery includes five owned files; production role adaptation remains
a separately owned decision. Stop editing at delivery.

```sh
git add -- docs/plans/FLH-053-local-embedding-contract.md scripts/validation/flh053/README.md scripts/validation/flh053/main.go scripts/validation/flh053/fixtures.go scripts/validation/flh053/probe_test.go
```

Suggested commit message:

```text
test: prepare bounded local embedding service contract acceptance
```
