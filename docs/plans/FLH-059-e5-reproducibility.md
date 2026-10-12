# FLH-059 E5 numerical reproducibility contract

Owner: local Claude Code. Branch label supplied: `feat/flh-059-e5-reproducibility`.
No Git/GitHub command or subagent was used. Inputs: the
[FLH-058 report](../validation/FLH-058-real-e5-exploration.md) and its repeated-vector
finding (read, not edited). Evidence:
[validation](../validation/FLH-059-e5-reproducibility.md).

Not changed: Go retrieval, indexing and search; migrations; the frontend;
hybrid search; tuning; tolerances; FLH-045 frozen inputs; FLH-058 files and
evidence; historical reports; and `contract.py`, `encoder.py`, `manifest.py`
(so the FLH-054 identity stays reproducible).

## Files (exact edit set)

| File | Change |
| --- | --- |
| `tools/embedding/e5/flh_e5/batching.py` (new) | Policies `dynamic_v1`/`singleton_v1`/`fixed_v1`, `apply_policy`, v2 manifest and identity, observed numerics settings, CUDA `PolicyEncoder` with the fixed-shape forward pass |
| `tools/embedding/e5/flh_e5/__main__.py` | `--batching` for `manifest` and `serve`; `dynamic_v1` builds the unchanged v1 manifest |
| `tools/embedding/e5/tests/test_batching.py` (new) | Policy shapes, v1/v2 split, distinct identities, FLH-054 code hash pinned, CLI validation |
| `tools/embedding/e5/windows/start.ps1` | `-Batching` (ValidateSet, default `dynamic_v1`) |
| `tools/embedding/e5/README.md` | Policy row, manifest v2, "Batching and reproducibility", "Tailscale Serve", `$ModelDir` instead of a fixed drive path, tests, status |
| `scripts/validation/flh059/{diagnose.py,inputs.json,run-diagnostic.ps1,test_diagnose.py,README.md}` (new) | Bounded GPU diagnostic, its inputs, the human entry point, offline tests and docs |
| `docs/SEMANTIC_SEARCH.md` | Reproducibility, Tailscale Serve and status bullets |
| This plan and the validation report | New |

## 1. Facts and explanations, kept apart

**Observed (FLH-058, the human's GPU, `float16`, `dynamic_v1`, microbatch 8)**
- 112 repeated Concept vectors exceeded FLH-056's tolerance, with a maximum
  difference of 3.0038e-4, for C001–C007 only.
- Norms stayed within 1e-7 of 1. No ranking difference was established.

**Observed (here, from the Go-rendered capture and service code)**
- All 56 FLH-058 requests were `[Unit query] + the same 24 Concepts in the same
  order`.
- The service splits them into 8+8+8+1, so C001–C007 always shared
  microbatch 1 with a different query, while C008–C024 always had identical
  companions.

**Code facts**
- Right padding to the longest input in each microbatch, with an attention
  mask.
- The model computes in the selected dtype (`float16` by default); pooling and
  L2 normalization run in float32.
- `cuda:0`, `eval()` and `inference_mode()`.
- No TF32, determinism, cuDNN or SDPA setting is changed. The attention
  implementation is the library default.

**Possible explanations (not established)**
- The tensor shape: padded width or row count changes GPU kernel selection or
  reduction order.
- float16 accumulation amplifies that.
- Companion content leaking through padding is unlikely, given the masking, but
  untested.
- The C001–C007 pattern fits shape dependence, but no extra model call was
  made.

## 2–3. Diagnostic matrix and measures

- **Where:** `scripts/validation/flh059/diagnose.py`, which runs in-process on
  the GPU through the real `flh_e5` encoder code. It never contacts the service
  or an endpoint.
- **Inputs:** `inputs.json`, the production-rendered strings for 24 Concepts
  and 56 Unit queries. Ids and text only, with no labels or targets, and
  re-checkable with `diagnose.py inputs`.
- **Configurations:** six, from 2 dtypes × 3 policies.
- **Positions:** 456 per configuration and 2,736 in total, with a hard bound of
  600 per configuration.
- **Conditions:**
  - singleton ×2 (reference and repeat);
  - ordered, reversed and rotated full batches;
  - short and long companions;
  - partial microbatches of 3;
  - FLH-058's 8+8+8+1 shape for 8 queries sampled by token count only.
- **Measures, per configuration and condition, against the same text's
  singleton:**
  - bitwise-equal count, FLH-056 tolerance failures (unchanged), maximum
    coordinate difference, maximum cosine distance and norms;
  - shape attribution: same forward shape and row, then bitwise equal?;
  - ranking sensitivity: top-5 order and set changes, maximum score change,
    smallest top-6 margin, and margins at risk;
  - each configuration against `float32`/`singleton_v1`;
  - encode time and forward passes.

## 4. Strategy choice: pre-registered, evidence-gated

**Candidates**
- `float32` reduces the error per step but doesn't make shapes fixed.
- `singleton_v1` makes a text's shape depend only on itself, at the cost of one
  pass per input.
- `fixed_v1` gives every pass the same shape, at the cost of 8×512 tokens per
  pass.

**Rule (in code, before any GPU result)**
- A configuration passes with zero tolerance failures and zero top-5 order
  changes.
- Candidate: the first passing configuration in the order `float16` dynamic,
  singleton, fixed, then `float32` dynamic, singleton, fixed.
- Bitwise equality is reported, never assumed from a setting.

**The default is not changed by this task.** No GPU evidence exists yet, so
`dynamic_v1` stays the default.

## 5. Identity

- `dynamic_v1` keeps the v1 manifest byte for byte. Its code hash
  (`96ab7c27…`, the value FLH-056 and FLH-058 observed) is pinned by a test.
- `singleton_v1` and `fixed_v1` use manifest v2, which adds two hashed
  sections:
  - `inference.batching`: policy, microbatch, padding side, fixed width and rows
    per pass;
  - `inference.numerics`: the observed attention implementation, TF32 and
    reduced-precision flags, matmul precision, cuDNN and SDPA flags.
- The v2 code hash adds `batching.py`. The identity is
  `…/flh_e5_role_prefix_v1/<dtype>/<policy>/<sha16>`.
- Any change in dtype, policy, microbatch, numerics settings, code or runtime
  gives a new identity, and so a new `EMBEDDING_MODEL_ID`, cache and space.
  Old vectors are kept for comparison and never relabelled.

## 6–8. Operations

- **Human GPU commands:** `scripts/validation/flh059/run-diagnostic.ps1`. Model
  and output directories are parameters, and the output must be outside the
  repository, new or empty, and is never overwritten. No host-specific path is
  tracked, and the README examples use `$HOME`.
- **Tailscale Serve:** documented as an operator option. The service stays on
  `127.0.0.1` behind a foreground `tailscale serve --http=8765
  http://127.0.0.1:8765`, with no funnel. `--bg` is a persistent change and is
  not requested. Private-IP binding is unchanged.
- **FLH-057 quoting:** checked as far as possible without Windows, in a Linux
  PowerShell 7.4 container: parsing, plus `Standard` and `Legacy`
  argument-passing modes. Windows execution is NOT RUN.

## Staged acceptance

| Stage | Owner | State |
| --- | --- | --- |
| 0. Scaffolding: policies, v2 identity, diagnostic, inputs, offline tests, PowerShell parse and argument checks | this task | Done here, with fakes only |
| 1. GPU checkpoint: `run-diagnostic.ps1` on the RTX 4070, results kept outside the repository | human | **NOT RUN** |
| 2. Decision: apply the rule to `analysis.json`; if a non-default policy is chosen, serve it with `-Batching`, record its new manifest and build its own index space | separate task and authorization | Not started |
| 3. If nothing passes: no runtime change; investigate further (for example deterministic settings or another shape scheme) under a new assignment | separate task | Not started |

## Remaining risks

- **CUDA code never run:** `PolicyEncoder.encode_fixed`, `numerics_settings`
  and `CudaBackend` have never run against torch, transformers 5.17 or CUDA.
- **Cost:** `fixed_v1` puts every search query through an 8×512 pass, and
  `singleton_v1` turns FLH-058's 4 passes per request into 25.
- **Limited scope of a pass:** a passing result covers one GPU and runtime only;
  the identity records both.
- **Partial requests under `fixed_v1`:** filler rows or row position could still
  matter. The diagnostic keys the same-shape check by row to show this.
