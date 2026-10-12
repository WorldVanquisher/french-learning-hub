# Local multilingual-e5-base embedding service (FLH-054)

A small HTTP service that runs the pinned `intfloat/multilingual-e5-base`
weights on the Windows laptop's CUDA GPU and answers the existing Go
`HTTPProvider` (`POST <base>/embeddings` with `{"model","input"}`). It applies
E5's `query: ` / `passage: ` prefixes from an **explicit role contract**, never
from batch position or guesswork.

What it is **not**: a model evaluation, an accepted model choice, hybrid search,
automatic SAME, a public service or an autostarted daemon. It has no
authentication and must only listen on loopback or a private address.

**Status.** The code and its fake-encoder tests run on any machine.
**Real CUDA, model loading, GPU memory, Windows scripts and NAS access are
NOT RUN**: they need the human's Windows RTX 4070 Laptop after the explicit
preparation below.
FLH-057 replaced `check-env.ps1`'s inline `python -c` with
`windows/check_env.py`; that fix is also **NOT RUN on Windows** (see step 1
below).
FLH-059 added opt-in batching policies and a GPU reproducibility diagnostic.
Neither has run on a GPU; only fake-encoder tests and PowerShell 7 parsing and
argument checks in a Linux container have run.

Contract: [plan](../../../docs/plans/FLH-054-local-e5-service.md).
Evidence: [validation](../../../docs/validation/FLH-054-local-e5-service.md).
Operator view: [SEMANTIC_SEARCH.md](../../../docs/SEMANTIC_SEARCH.md#local-e5-deployment-flh-054).

## Role contract `flh_e5_role_prefix_v1`

Every input must be exactly one of these JSON texts, produced by the Go code:

| Representation / type | Producer | Model text |
| --- | --- | --- |
| `concept_search_query_v2` / `query` (`{"representation","type","text"}`) | semantic search, since FLH-054 | `query: ` + input |
| `concept_embedding_text_v1` / `query` | Unit query (embedding retriever, FLH-048 runner) | `query: ` + input |
| `concept_embedding_text_v1` / `concept` | Concept document (semantic index, retriever) | `passage: ` + input |

**Rules**
- The prefix is the ASCII bytes `query: ` or `passage: `, followed by the
  original input string exactly as received: no re-serialization, trimming or
  second prefix.
- Keys must match the representation exactly. Field types are checked. Duplicate
  keys, `NaN`/`Infinity`, surrounding whitespace, raw text, already-prefixed text
  and any other representation/type pair are rejected (HTTP 422
  `invalid_input`). Error messages never contain input text.
- A user query that *looks like* a Concept document is still a query: search
  wraps it in the `concept_search_query_v2` envelope.
- `tests/golden_inputs.json` holds the exact Go-produced strings. Both this
  package's tests and `internal/application/semantic_search_envelope_test.go`
  check them.

## Pinned model

| | |
| --- | --- |
| Repository | `intfloat/multilingual-e5-base` (MIT licence) |
| Revision (weights and tokenizer) | `d128750597153bb5987e10b1c3493a34e5a4502a` (commit of 2026-04-02) |
| Facts from the model card at that revision | 768 dimensions; `query: `/`passage: ` prefixes for asymmetric retrieval; attention-mask mean pooling; L2 normalization; 512 tokens |

Only these files are used; the service refuses a model directory containing
anything else (for example `pytorch_model.bin`, `.py` or ONNX files):

| File | Bytes | Pinned digest |
| --- | ---: | --- |
| `model.safetensors` | 1,112,201,288 | sha256 `a18a44fa…de09a7` |
| `tokenizer.json` | 17,082,660 | sha256 `62c24cdc…bb75626` |
| `sentencepiece.bpe.model` | 5,069,051 | sha256 `cfc8146a…0db2865` |
| `config.json` | 694 | git blob `2b827c7e…173388c9dc` |
| `tokenizer_config.json` | 418 | git blob `6de1940d…377841b311f` |
| `special_tokens_map.json` | 280 | git blob `d5698132…937b1701812598e` |

The full digests are in `flh_e5/manifest.py`; they were read from the Hugging
Face API on 2026-10-12. The revision is fixed in code, so changing it is a
code change and produces a new deployment identity.

**Loading**
- `XLMRobertaModel.from_pretrained(<dir>, local_files_only=True,
  use_safetensors=True, trust_remote_code=False)` loads the weights, with
  `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` set. Startup never downloads.
- Tokenization uses `tokenizer.json` directly through the `tokenizers` library,
  with no truncation. The service checks that it adds `<s>`/`</s>`.

## Inference

| Setting | Value |
| --- | --- |
| Device | `cuda:0`, required. No CUDA → startup fails; there is no CPU or other-model fallback |
| Dtype | `float16` (default) or `float32`; part of the identity |
| Mode | `model.eval()` and `torch.inference_mode()` |
| Pooling | Attention-mask mean over `last_hidden_state`, in float32 |
| Normalization | L2, float32; the service rejects any vector whose norm differs from 1 by more than 1e-3 |
| Token limit | 512 including the prefix and `<s>`/`</s>`. **Longer inputs are rejected** (HTTP 422 `input_too_long`, counted), **never truncated** (the `truncations` counter stays 0) |
| GPU microbatch | 8 (default; maximum is the request size) |
| Batching policy | `dynamic_v1` (default, FLH-054 behaviour): each microbatch right-padded to its longest input. `singleton_v1` and `fixed_v1` are opt-in, each a new identity. See [Batching and reproducibility](#batching-and-reproducibility-flh-059) |

## Deployment manifest and identity

`GET /manifest`, or before serving:
`python -m flh_e5 manifest --model-dir <dir>` (verifies the files and reads
library and GPU versions; it does not load the model).

**What the manifest contains**
- The vector-defining fields, which are hashed:
  - the model repository, revision and every file's size and SHA-256;
  - the tokenizer revision and its overlength policy;
  - the adapter convention, accepted pairs, prefixes and code SHA-256;
  - dtype, pooling, normalization, dimensions and microbatch;
  - runtime versions: Python, torch, torch CUDA, cuDNN, transformers,
    tokenizers, safetensors, NumPy, GPU name and capability.
- `manifest_sha256`: SHA-256 of the canonical JSON of the vector-defining
  fields.
- `deployment_id`:
  `multilingual-e5-base@<revision>/flh_e5_role_prefix_v1/<dtype>/<manifest_sha256[:16]>`
  (about 110 bytes; the limit is 200).
- The service limits, published but not hashed: they don't change vectors.

The code hash covers `contract.py`, `encoder.py` and `manifest.py` with line
endings normalized, so a CRLF checkout hashes the same.

**Manifest v2 (FLH-059, non-default batching only).** With
`--batching singleton_v1` or `fixed_v1`, the manifest schema is
`flh_e5_deployment_manifest_v2`. It adds two hashed sections to the
vector-defining fields:
- `inference.batching`: policy, service microbatch, padding side, fixed width
  and rows per forward pass;
- `inference.numerics`: the observed attention implementation, TF32 and
  reduced-precision matmul flags, float32 matmul precision, cuDNN flags and SDPA
  backends.

Its code hash also covers `batching.py`, and the identity names the policy:
`multilingual-e5-base@<revision>/flh_e5_role_prefix_v1/<dtype>/<policy>/<sha16>`.
`dynamic_v1` keeps the v1 manifest byte for byte, and `contract.py`,
`encoder.py` and `manifest.py` are unchanged (code hash `96ab7c27…`, pinned by a
test), so the FLH-054 deployment and its identity stay reproducible for
comparison.

**Use `deployment_id` for both `EMBEDDING_MODEL` and `EMBEDDING_MODEL_ID`.**
The service rejects any other `model` value (HTTP 400 `unknown_model`).

If anything vector-defining changes, the identity changes too. That covers a
library upgrade, another dtype or microbatch, an adapter edit or a different
GPU. The Go index then uses a new cache and collection space, and you run
`semantic-index build` for it. Never reuse or relabel vectors from another
identity.

## HTTP API

| Endpoint | Behaviour |
| --- | --- |
| `POST /v1/embeddings` | Body exactly `{"model": <deployment_id>, "input": [1..32 strings]}`. Response `{"object":"list","model":…,"data":[{"object":"embedding","index":i,"embedding":[768 floats]}]}`, with indices `0..n-1` in input order |
| `GET /readyz` | `200` only after the files are verified, the model is on the GPU and the warmup succeeded; otherwise `503` with the state (`starting`, `loading`, `warming`, `failed`, `stopping`) |
| `GET /healthz` | Liveness |
| `GET /manifest` | The public manifest |
| `GET /metrics` | Counters, limits and measured GPU evidence |

**Limits (defaults)**
- Request: 32 inputs, 4,096 UTF-8 bytes per input, 256 KiB body
  (`Content-Length` required).
- Admission: 4 requests admitted at once (running plus waiting), a 30 s wait
  for the GPU, 16 connections, 30 s socket timeout.

**Error types**, as `{"error":{"type","message"}}`, with no input text:
- `invalid_request` 400, `unknown_model` 400, `length_required` 411
- `request_too_large`, `too_many_inputs`, `input_too_large` 413
- `invalid_input`, `input_too_long` 422
- `not_ready`, `overloaded`, `gpu_out_of_memory` 503
- `encoder_error`, `invalid_model_output` 500
- `not_found` 404, `method_not_allowed` 405

**Validation and failure**
- The whole request is validated and token-counted before any GPU work; one bad
  input rejects all of it.
- An out-of-memory error, overload or encoder failure is reported as is. There
  is no retry, no smaller-batch retry and no fallback; the service stays up for
  the next request.

**Counters** (`/metrics`): requests, accepted input positions, inputs by role,
distinct input hashes (SHA-256, capped at 100,000), rejections by type,
microbatch computations, overlength inputs, maximum tokens seen, truncations
(always 0) and encode seconds.

**GPU evidence:** device, GPU name, total memory, allocated, reserved and peak
allocated bytes, whether every parameter is on the device, the parameter dtype
and the training-mode flag.

**Logs:** one line per request, with status, error type, input count and
duration. No input text, response vectors or request headers (including
`Authorization`) are logged.

## Windows: install, prepare, start, smoke, stop (human-run)

All commands run in the existing environment, from the repository root:

```powershell
conda activate flh-embedding
$ModelDir = "$HOME\models\multilingual-e5-base"   # any directory outside the repository; your choice
```

1. **Record the environment first.** This is read-only and checks a real CUDA
   computation.
   ```powershell
   .\tools\embedding\e5\windows\check-env.ps1 | Tee-Object before.txt
   ```
   The Python part lives in `windows\check_env.py` and runs as
   `python -B <path>` (FLH-057). The FLH-054 version passed source through
   `python -c $code`. Windows PowerShell 5.1 strips embedded double quotes from
   native arguments, so it failed with `SyntaxError` at `print(name, NOT ...`.
   `check_env.py` exits 0 when the CUDA computation is correct, 1 when CUDA is
   unavailable or wrong and 2 when torch can't be imported. The script throws
   on any non-zero exit.
2. **Install the pinned libraries without touching torch.** `requirements.txt`
   doesn't list torch, and none of these packages requires it. Check the dry run
   first:
   ```powershell
   python -m pip install --dry-run -r tools\embedding\e5\requirements.txt
   ```
   Make sure the "Would install" list contains no `torch`, `nvidia-*` or CUDA
   package, then:
   ```powershell
   python -m pip install -r tools\embedding\e5\requirements.txt
   .\tools\embedding\e5\windows\check-env.ps1 | Tee-Object after.txt
   ```
   Confirm that `torch 2.13.0+cu126` and the CUDA check are unchanged in
   `after.txt`.
3. **Download and verify the model explicitly.** This needs about 1.13 GB.
   Without `-Download` the script only prints the command:
   ```powershell
   .\tools\embedding\e5\windows\prepare-model.ps1 -ModelDir $ModelDir
   .\tools\embedding\e5\windows\prepare-model.ps1 -ModelDir $ModelDir -Download
   ```
   The download command itself is:
   ```powershell
   hf download intfloat/multilingual-e5-base config.json model.safetensors tokenizer.json tokenizer_config.json special_tokens_map.json sentencepiece.bpe.model --revision d128750597153bb5987e10b1c3493a34e5a4502a --local-dir $ModelDir
   ```
   Verification must print every file; on any mismatch it fails.
4. **Record the identity:**
   ```powershell
   cd tools\embedding\e5
   python -B -m flh_e5 manifest --model-dir $ModelDir > manifest.json
   cd ..\..\..
   ```
5. **Start the service in the foreground,** loopback first:
   ```powershell
   .\tools\embedding\e5\windows\start.ps1 -ModelDir $ModelDir
   ```
   For the NAS, bind the laptop's private IP explicitly. Only loopback and
   RFC 1918 or ULA addresses are accepted; `0.0.0.0` and public addresses are
   refused.
   ```powershell
   .\tools\embedding\e5\windows\start.ps1 -ModelDir $ModelDir -BindHost 192.168.1.20 -Port 8765
   ```
   `-Batching singleton_v1` or `-Batching fixed_v1` serves a non-default
   policy under its own new identity. Record its `manifest` with the same
   `--batching` value.
   Nothing changes the firewall, network profile or router, and nothing
   autostarts. The human confirms that private NAS access is already permitted.
   Loopback success is not NAS reachability.
6. **Smoke test** from a second console:
   ```powershell
   .\tools\embedding\e5\windows\smoke.ps1 -BaseUrl http://127.0.0.1:8765
   ```
   Then run `nvidia-smi` and record the process's GPU memory.
7. **Stop** with Ctrl+C in the service console. It sets readiness to 503, lets a
   running request finish, releases the model and GPU cache, closes the
   listener and logs the final counters. If that console is lost, use
   `windows\stop.ps1` (lists the processes) and then
   `windows\stop.ps1 -Confirmed`. Confirm afterwards with `nvidia-smi` and a
   failed connection.

**Record for the validation report:**
- `before.txt` and `after.txt`;
- `manifest.json` (`deployment_id` and `manifest_sha256`);
- the `nvidia-smi` driver line;
- the startup log line `gpu: {...}` and `/metrics` after the smoke test;
- the exact start command and bind address;
- the stop log line.

## Batching and reproducibility (FLH-059)

**Observed (FLH-058, real GPU, float16, `dynamic_v1`, microbatch 8).** Every
request was a Unit query followed by the same 24 Concept documents in the same
order. The service splits that into microbatches of 8, 8, 8 and 1, so C001–C007
always shared microbatch 1 with a *different* query, while C008–C024 always
had identical companions.
- The 112 repeated vectors that exceeded FLH-056's tolerance were exactly
  C001–C007. The maximum coordinate difference was 3.0e-4.
- Normalization held throughout (norms within 1e-7 of 1). Normalization is not
  reproducibility.

**Code facts (this file set).**
- Inputs are right-padded to the longest input in their microbatch, and the
  attention mask excludes padding.
- The model runs in the selected dtype, while pooling and L2 normalization run
  in float32.
- No TF32, determinism or attention-backend setting is changed.

**Not established.** That the tensor shape (padded width or row count) causes
the drift is a plausible explanation that fits the C001–C007 pattern. So are
float16 accumulation and shape-dependent GPU kernel selection. None has been
measured, and no ranking change from the drift has been shown.

**Policies** (`--batching`, for both `manifest` and `serve`):

| Policy | Forward-pass shape | Identity |
| --- | --- | --- |
| `dynamic_v1` | (microbatch size, longest input in it): depends on companions | Unchanged FLH-054 v1 identity |
| `singleton_v1` | (1, own token count): depends only on the text | New v2 identity |
| `fixed_v1` | (microbatch, 512) always; spare rows are `<s></s>` and discarded | New v2 identity |

None of them promises bitwise determinism; that is measured, not assumed.
**The default stays `dynamic_v1`** until the GPU diagnostic in
[`scripts/validation/flh059`](../../../scripts/validation/flh059/README.md)
supplies evidence. Switching policy gives a new `deployment_id`, so a new
`EMBEDDING_MODEL_ID`, cache and collection space, and a new
`semantic-index build`. Vectors from the old identity are kept for comparison
and never relabelled.

## NAS configuration (Go side)

```sh
EMBEDDING_PROVIDER=http
EMBEDDING_BASE_URL=http://192.168.1.20:8765/v1     # the laptop's private IP; no /embeddings suffix
EMBEDDING_MODEL=<deployment_id from the manifest>
EMBEDDING_MODEL_ID=<the same deployment_id>
EMBEDDING_DIMENSIONS=768
EMBEDDING_TIMEOUT=30                               # seconds; the default 8 may be short for indexing batches
SEMANTIC_BATCH_SIZE=32                             # must not exceed the service's 32 inputs
```

Then run `semantic-index build` for this new identity. Any indexing or
evaluation run with real vectors needs its own explicit authorization.

## Tailscale Serve (operator option)

Instead of binding a private IP, the service can stay on `127.0.0.1` with
Tailscale Serve forwarding tailnet traffic to it. The service's own bind rules
are unchanged: it still refuses the tailnet's CGNAT `100.64.0.0/10` addresses.
Run this on the laptop, in a second console, after the service is ready:

```powershell
.\tools\embedding\e5\windows\start.ps1 -ModelDir $ModelDir            # console 1: loopback only
tailscale serve --http=8765 http://127.0.0.1:8765                       # console 2: foreground, Ctrl+C stops it
tailscale serve status
```

- **NAS URL:** `EMBEDDING_BASE_URL=http://<laptop tailnet IP or MagicDNS name>:8765/v1`.
- **Reach:** Serve shares only within your tailnet, and your tailnet's access
  rules decide which devices reach it. **Never use `tailscale funnel`**, which
  publishes to the internet. The service has no authentication.
- **Persistence:** `--bg` keeps serving after the console closes and resumes
  after a reboot, which is a persistent change on the laptop; this project
  doesn't ask for it. If you used it, remove it with
  `tailscale serve --http=8765 off` (or `tailscale serve reset`, which clears
  *all* Serve configuration), then check `tailscale serve status`.
- **What the service sees:** every connection appears to come from loopback, so
  its connection limit counts the proxy's connections. Check the exact flags
  against `tailscale serve --help` for your installed version.
- **Not set up or run by an agent:** the endpoint FLH-056/058 used
  (`100.118.109.6:8765`) is the human's own forwarding.

## Tests (no GPU, no model)

```sh
python3 -B -m unittest discover -s tools/embedding/e5/tests -t tools/embedding/e5
go test ./internal/application -run 'Envelope|Representations_Unchanged|SemanticSearch'
```

- **What they use:** an injected `FakeEncoder` (hash vectors) over real
  loopback HTTP.
- **What they cover:**
  - the contract and its golden inputs, role from content not position, and the
    raw-JSON query ambiguity;
  - singleton batches, microbatch ordering and contiguous indices;
  - every limit and error type, overlength rejection, OOM and encoder failures
    without retry;
  - readiness during load and warmup, failed startup, counters, no input text in
    logs or metrics, bind-address rules, and graceful shutdown with a request in
    flight;
  - manifest identity and file checks;
  - batching policies (FLH-059): the shapes each policy requests, the v1/v2
    manifest split, distinct identities, and the FLH-054 code hash pinned.
- **Plumbing launcher:** `tests/run_fake_service.py --port N` runs the real
  service with the fake encoder, for checking Go callers.
- **What they don't show:** CUDA, the model or semantic quality.
