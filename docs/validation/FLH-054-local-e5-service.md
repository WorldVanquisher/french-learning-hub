# FLH-054 validation: explicit-role local E5 service

Date: 2026-10-12. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` on **macOS arm64** (Go
`go1.26.5`, Python 3.13.5). This is **not** the human's Windows RTX 4070
Laptop. No Git/GitHub command, subagent, model-weight download, paid call,
secret, `.env` read or daily data was used. Contract:
[plan](../plans/FLH-054-local-e5-service.md).

## Model facts (official sources, metadata only)

- `GET https://huggingface.co/api/models/intfloat/multilingual-e5-base?blobs=true`
  reported `sha` `d128750597153bb5987e10b1c3493a34e5a4502a`, lastModified
  2026-04-02, licence MIT, and per-file sizes, git blob ids and LFS SHA-256
  values. These are the pins in `flh_e5/manifest.py`.
- At that revision only the small files were fetched: `config.json`,
  `tokenizer_config.json`, `special_tokens_map.json`, `1_Pooling/config.json`
  and `README.md` (the model card). Their computed git blob SHA-1 values equal
  the API's ids, confirming the verification method.
- **Observed:**
  - `hidden_size` 768, `XLMRobertaModel`, `pad_token_id` 1,
    `model_max_length` 512;
  - pooling config `pooling_mode_mean_tokens: true`;
  - the model card's `average_pool` (masked mean) plus `F.normalize`;
  - "Each input text should start with "query: " or "passage: ", even for
    non-English texts", with asymmetric retrieval using both;
  - "Long texts will be truncated to at most 512 tokens" (this service rejects
    instead).
- **No weights were downloaded.** `model.safetensors`, `tokenizer.json` and
  `sentencepiece.bpe.model` are pinned by the API's SHA-256 values only.
- **PyPI metadata** chose versions released at least two weeks earlier, with
  win_amd64/cp311 or abi3 wheels:
  - `transformers==5.17.0`, which needs `huggingface-hub<2.0` and
    `tokenizers<0.24`;
  - `tokenizers==0.23.2`, `safetensors==0.8.0`, `huggingface_hub==1.33.0`;
  - `numpy==2.4.6`, the newest NumPy line that still supports Python 3.11
    (2.5.x needs 3.12 or later).
  - None of these lists torch as a dependency.

## Mocked evidence (fake encoder, this machine)

`python3 -B -m unittest discover -s tools/embedding/e5/tests -t tools/embedding/e5`:
**31 tests OK**, with subtests. All Python files also parse with
`feature_version=(3, 11)`.

| Area | Shown |
| --- | --- |
| Contract | Six golden accepted inputs (Go-produced) get their declared role and `prefix + original bytes`; 22 golden rejections; model text is never accepted again; role follows content in any batch order; the same Concept JSON is a passage bare and a query inside the search envelope; messages never echo input |
| Requests | Mixed batch: contiguous indices in order, 768-dimensional finite unit vectors equal to the fake of each prefixed text. Singleton batches of each kind. Microbatch 2 over 5 inputs gives calls of 2, 2 and 1 in order |
| Limits and errors | unknown model, extra key, empty, non-list, non-string, 33 inputs, 4,100-byte input, raw text, prefixed text, invalid JSON, duplicate key, `NaN`, non-UTF-8, body over the limit, missing `Content-Length`, 404/405. None reached the encoder |
| Tokens | 513 tokens → 422 `input_too_long`, counted; 512 accepted; `truncations` 0 |
| Failures | OOM → 503, encoder error → 500, NaN, unnormalized, short or missing vectors → 500. Each made exactly one encoder attempt with no retry, and the next request succeeded |
| Admission | Full queue → immediate 503; GPU wait timeout → 503; connection limit → 503 counted |
| Readiness | 503 `starting` → 503 `warming` (and POST `not_ready`) → 200 with `deployment_id`. Failed load or a NaN warmup → `failed`, never ready |
| Observability | Counters for requests, positions, roles, distinct hashes, rejections and computations. A marker in inputs and in an `Authorization` header never appears in logs or `/metrics` |
| Shutdown | `serve()` with a request in flight: the request completes (200), then the encoder closes, state `stopped`, exit 0, and the port refuses connections. Startup failure exits 3 |
| Binding | Loopback, RFC 1918 and ULA accepted; `0.0.0.0`, `::`, public, link-local, CGNAT, multicast, documentation addresses and host names refused; the CLI refuses before loading |
| Manifest | Pins are digests; identity is deterministic, 108 bytes, and changes with dtype, code, microbatch, runtime, files or prefixes but not with service limits; the code hash ignores CRLF; unexpected, missing or wrong-size files are refused |

**Go** (`internal/application`, also with `-race`):
- `TestConceptSearchQueryEnvelope_MatchesGoldenWireBytes`: three search
  cases, including HTML escaping and a query that is a Concept JSON.
- `TestConceptEmbeddingRepresentations_UnchangedAgainstGolden`: index document
  and retriever Unit query, byte-equal to the golden file.
- `TestSemanticSearch_SendsVersionedQueryEnvelope`: five singleton index
  batches, all Concept documents. Search sends exactly one envelope, never a
  document text, and the report carries `concept_search_query_v2`.
- All earlier semantic tests pass unchanged.

**Mutation checks** (each applied in place and restored byte-identical; all 10
caught):
- double prefix; key-set check removed; raw text guessed as a query;
- overlength not rejected; retry after OOM; ready before warmup;
  wildcard bind allowed; blocking admission;
- service limits hashed into the identity;
- Go search sending the raw query.

## Plumbing through the real Go HTTPProvider (fake encoder, loopback)

`python3 -B tools/embedding/e5/tests/run_fake_service.py --port 18765` runs the
real service and HTTP stack with the fake encoder (deployment
`fake-e5-plumbing-only`).

| Command | Result |
| --- | --- |
| `go run ./scripts/validation/flh048 -out <scratch> -embedding http -embedding-base-url http://127.0.0.1:18765/v1 -embedding-model fake-e5-plumbing-only -embedding-max-inputs 1400 -embedding-dimensions 768 -embedding-timeout 30s` | Exit 0; embedding `completed`; runner counters 56 requests, 1,400 positions, 80 unique inputs, dimensions [768]. Service counters match: 56 OK, 1,400 positions, **56 `query` and 1,344 `passage`** (one Unit query plus 24 Concepts per request), 0 rejections, 0 truncations, max 43 tokens. Fake vectors: **plumbing only, not quality data** |
| FLH-053 probe `-payload plain` (unchanged, `TMPDIR` set to scratch) | Exit 1: its first request of unwrapped plain text was rejected (422) |
| FLH-053 probe `-payload rendered` | Exit 1: `unit-to-concept` and `document-only-permuted` **passed** its ordering, unit-norm and repeat checks; `raw-search-en` (unwrapped search text) rejected with 422. This is the failure FLH-053 asked to preserve |
| SIGINT to the service | Process exited; port closed (curl exit 7) |

## Repository checks

| Command | Result |
| --- | --- |
| `gofmt -l .` | no output |
| `go vet ./...` | ok |
| `go test ./... -count=1` | all ok except `scripts/validation/flh053` `TestCapsTimeoutAndOptIn` under macOS's default `TMPDIR` (`/var/folders/…`, `/var` is a symlink): the probe refuses a symlinked output ancestor. With `TMPDIR` set to a symlink-free directory the whole module passes. It's independent of this change and FLH-053's file was not edited |
| `go test ./internal/application -race` | ok |
| `python3 -B -m unittest discover -s scripts/ci/flh046 -p 'test_*.py'` | OK |

No `__pycache__` was left (all runs used `-B`). The fake service and the
FLH-053 probe outputs are in the session scratchpad only.

## NOT RUN (need the Windows RTX 4070 Laptop)

- **Not run on Windows at all:** the PowerShell helpers (`pwsh` isn't
  installed here, so they weren't even parsed), the pip install with its dry run
  and the torch-unchanged check, `hf download` and real file verification, and
  `python -m flh_e5 manifest` and `serve`.
- **Not exercised on this machine:** `E5CudaEncoder` itself. That covers real
  CUDA, `transformers` 5.17 / torch 2.13 compatibility (including the `dtype=`
  keyword), float16 loading, GPU placement and memory, warmup latency, real
  token counts, OOM behaviour, and SIGBREAK/Ctrl+C on Windows.
- **Not run anywhere:** NAS reachability over a private address, the HTTP
  transport response field (dependency 1 in the plan) and the FLH-040 demo
  (dependency 2).
- **No real-model evaluation or quality claim.** Whether whole-JSON
  `query:`/`passage:` texts suit E5 is a later, separately authorized
  experiment.
