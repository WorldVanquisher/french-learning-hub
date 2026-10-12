# FLH-054 Explicit-role local E5 embedding deployment

Owner: local Claude Code. Branch label supplied: `feat/flh-054-local-e5-service`.
No Git/GitHub command or subagent was used. Builds on the
[FLH-053 contract](FLH-053-local-embedding-contract.md) (read, not edited).
Evidence: [validation](../validation/FLH-054-local-e5-service.md).

Authorized: a bounded local embedding service and the small search-envelope
change. Not authorized and not done: automatic SAME, hybrid search, training,
public exposure, paid calls, model download by the agent, real-model
evaluation.

## Files (exact edit set)

| File | Change |
| --- | --- |
| `internal/application/semantic_search.go` | `ConceptSearchQueryRepresentationV2`, `ConceptSearchQueryEmbeddingText`, envelope used by `embedQuery`, `SemanticSearchReport.QueryRepresentation` |
| `internal/application/semantic_search_envelope_test.go` (new) | Golden wire bytes, unchanged Unit/Concept representations, search sends one envelope, singleton index batches |
| `tools/embedding/e5/` (new) | `flh_e5/{__init__,__main__,contract,manifest,encoder,service}.py`, `requirements.txt`, `windows/{check-env,prepare-model,start,smoke,stop}.ps1`, `tests/{__init__,fakes,test_contract,test_manifest,test_service,run_fake_service}.py`, `tests/golden_inputs.json`, `README.md` |
| `docs/SEMANTIC_SEARCH.md` | What a search sends; Local E5 deployment section |
| `AGENTS.md` (`CLAUDE.md` is a symlink to it) | Minimal FLH-054 contract description |
| This plan and the validation report | New |

Not edited: FLH-045/048/051/053 files, historical reports, the HTTP provider,
configuration, migrations, frontend, dependencies, CI.

## Bounded dependencies (reported, not edited)

1. **HTTP response field.** `internal/transport/http/semantic_search.go:118`
   still sets `query_representation` to `application.ConceptSearchQueryRepresentationV1`,
   although search now embeds `concept_search_query_v2`. Fix: use
   `report.QueryRepresentation` (added for this purpose), and update
   `docs/ARCHITECTURE.md:1975` and, optionally, the web test fixture
   (`web/src/pages/KnowledgeLibrary.test.tsx:186`). The frontend type is a
   plain `string`.
2. **Demo fake.** `scripts/demo/flh040/fake_embeddings.py` ignores the JSON keys
   `representation` and `type` but not `concept_search_query_v2`, `query` or
   `text`, so demo query vectors now carry three constant extra tokens. Fix: add
   them to `IGNORE`. The demo was not run.
3. **FLH-053 probe on macOS** (observed, unrelated to this change).
   `TestCapsTimeoutAndOptIn` fails when `TMPDIR` has a symlinked ancestor
   (`/var` → `/private/var`); it passes with a symlink-free `TMPDIR`.

## Contracts

**Search query envelope (Go)**
- `{"representation":"concept_search_query_v2","type":"query","text":<trimmed q>}`
  rendered by `encoding/json` with fixed field order. The text is exactly the
  query as received (already trimmed by the library parser). An empty text is
  an error.
- One provider call per search, as before. Query vectors are not persisted, so
  no cache or space change follows. Unit query and Concept document
  representations (`concept_embedding_text_v1`) are byte-identical to before
  (golden test).

**Role adapter `flh_e5_role_prefix_v1` (service)**
- Accepted pairs, exact key sets and field types:
  `concept_search_query_v2/query`, `concept_embedding_text_v1/query` →
  `query: `; `concept_embedding_text_v1/concept` → `passage: `.
- Model text = ASCII prefix + the original input string. No position rule, no
  raw-text guessing, no trimming. Raw, prefixed, duplicate-key, NaN-constant,
  whitespace-wrapped or unknown inputs are rejected with HTTP 422.

**Wire (unchanged HTTPProvider)**
- `POST <base>/embeddings` with exactly `{"model","input"}`. `model` must equal
  the deployment id.
- Response: `data[i] = {index: i, embedding: 768 finite floats with L2 norm 1}`,
  in input order.

**Inference**
- Pinned `intfloat/multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a`.
- Six pinned files: the safetensors weights and the tokenizer files, verified
  by size and digest. Any other entry in the model directory is refused.
- `XLMRobertaModel` loaded with `local_files_only`, `use_safetensors`,
  `trust_remote_code=False` and the offline environment variables set.
- CUDA only; `float16` by default; `eval()` with `inference_mode()`.
- Masked mean pooling and L2 normalization in float32.
- 512 tokens including the prefix and special tokens. Longer inputs are
  rejected, never truncated.

**Identity**
- The manifest's vector-defining section (files, tokenizer policy, adapter and
  code hash, inference settings, runtime and GPU versions) is hashed.
- `deployment_id = multilingual-e5-base@<revision>/flh_e5_role_prefix_v1/<dtype>/<sha16>`
  (108 bytes).
- It is used for both `EMBEDDING_MODEL` and `EMBEDDING_MODEL_ID`; any change
  gives a new space and a new `build`.

**Operation**
- Binding: `127.0.0.1` by default, or an explicit RFC 1918 or ULA IP literal.
  Wildcard, public, link-local and CGNAT addresses are refused.
- Readiness: `/readyz` returns 200 only after file verification, GPU load and
  warmup.
- Limits: 32 inputs, 4,096 bytes per input, 256 KiB body, microbatch 8, an
  admission queue of 4, a 30 s GPU wait and 16 connections.
- Failures: OOM and overload are 503, encoder failure is 500, with no retry or
  fallback.
- Counters and GPU evidence are at `/metrics`; logs contain no text.
- Shutdown: Ctrl+C or a signal drains the running request, releases the model
  and closes the listener.
