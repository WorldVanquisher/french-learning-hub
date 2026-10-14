# FLH-073 validation: deployable read-only public demo

Date: 2026-10-14. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64). Contract:
[plan](../plans/FLH-073-public-readonly-demo.md); operator guide:
[PUBLIC_DEMO.md](../PUBLIC_DEMO.md).

**Not used:** Git/GitHub, subagents, Docker, Windows, a GPU, AWS, a model, a
provider, the internet (beyond loopback), DNS or the personal website
repository.

**Data:** synthetic fixtures only. No daily database was opened.

## Release-artifact status: **BLOCKED**

The only artifact that can be built uses **mechanical test vectors**
(`flh073_mechanical_hash_v1`: signed feature hashing of words, 64 dimensions).
`prepare validate -release` exits **3** with `RELEASE BLOCKED`, as intended.

**Evidence of what mechanical rankings are:** in the smoke's sample hybrid
search for the preset "how to tell a friend I miss them":
- keyword found 0 matches (AND prefix semantics);
- the mechanical semantic ranking put "the pronouns y and en" first (similarity
  0.471) and "imparfait for background and past habits" second.

These rankings show the mechanics and **no relevance**. A real-model artifact
needs a separately authorized run. No live model call was authorized or made.

## Implementation summary

- **`internal/publicdemo/`:**
  - artifact schema and strict loader (`LoadArtifact`, `OpenArtifact`);
  - read-only immutable database open with a migration-ledger check;
  - timestamp-free domain fingerprint;
  - `ArtifactIndex`, a read-only in-process `VectorIndex` with exact cosine;
  - `ArtifactPublication`;
  - `PresetQueryVectors`, a preset-only `EmbeddingProvider` with counters and
    no network code;
  - `Build`, which seeds through the real services, then computes mechanical
    vectors and writes the manifest.
- **`internal/transport/http/public_demo.go`:**
  - `NewPublicDemoBoundary`, the allowlist;
  - the `GET /knowledge-library/demo` info route;
  - the preset-only `/demo/semantic-search` and `/demo/hybrid-search`, which
    substitute the preset text and run the **unchanged** handlers.
- **`cmd/server`:**
  - `-public-demo-artifact` and `-public-demo-allow-mechanical`, with an early
    branch, so normal mode is unchanged;
  - `checkPublicDemoConfig` and `buildPublicDemo`. The order is browser
    boundary → demo allowlist → workbench → handler;
  - the serve/shutdown code was extracted unchanged for both modes.
- **Web:**
  - a `VITE_FLH_PUBLIC_DEMO=1` build renders `PublicDemoApp`: an English
    intro, a mechanical-vector banner, the page title and language, and the
    Knowledge Library only;
  - `KnowledgeLibrary` gains an optional `demo` prop: a preset selector with
    the exact text, and a restriction note;
  - the normal build is unchanged, and its bundle contains no demo copy
    (checked).
- **Tooling:** `scripts/demo/flh073/` (fixtures, `prepare`, `smoke.sh`), plus
  `docs/PUBLIC_DEMO.md` and an `AGENTS.md` entry.

## Automated results

| Command | Result |
| --- | --- |
| `go test ./internal/publicdemo/ -count=1 -v` | 6 tests PASS, including 17 tampering subtests |
| `go test ./internal/transport/http/ -run PublicDemo -count=1` | ok (2 tests) |
| `go test ./cmd/server/ -count=1 -v` | 3 tests PASS (full stack over real loopback HTTP) |
| `TMPDIR=/private/tmp/flh073-gotmp make verify` | **exit 0**: gofmt; `go test ./...` all 15 packages ok; `go vet`; server and capture builds; frontend typecheck, **18 files / 219 tests passed**, production build |
| `TMPDIR=… go test ./... -count=1` | all packages ok |
| `bash scripts/demo/flh073/smoke.sh /tmp/flh073-smoke-final` | **exit 0, 93 PASS lines, `SMOKE PASSED`**, no server left running |
| `VITE_FLH_PUBLIC_DEMO=1 npx vite build --outDir /tmp/…` | built; the documented manual steps served `/` and an `/assets/*.js` file with `200` |

**`TMPDIR`:** this is the macOS workaround recorded in FLH-071. Under the
default macOS temp directory, the pre-existing `scripts/validation/flh053`
probe refuses its symlinked output path. It is unrelated to this work.

**Bugs found and fixed during validation:**
1. The first smoke run counted 8 vector lookups instead of 4, because the
   script's `expect()` sent each GET twice.
2. That run also left its demo server running. `$!` was a wrapper subshell's
   PID, so the script's command-line ownership check correctly refused to
   signal it.

   I stopped the process after verifying its command line, then made the server
   the direct child, added a "server stopped" check, and made a foreign-PID
   refusal fail the smoke.
3. The demo page inherited the workbench title "Concept Review" and
   `lang="fr"`. The demo now sets its own title and `lang="en"`.

## What the tests cover

**Allowed routes, root and `/api`** (`cmd/server` full stack and smoke):
- **`/knowledge-library/demo`:** schema
  `knowledge_library_public_demo_v1`, `read_only`, `data: synthetic`,
  `vector_source: mechanical-test`, `real_model: false`, `release_status:
  blocked_mechanical_vectors`, the notice and 8 presets.
- **Library routes:** keyword search, Concept detail, unit source (provenance
  with extractor `fixture:flh073:knowledge_extraction_v1` and the original
  synthetic question).
- **Preset searches:**
  - semantic for `miss-someone`: schema v2, `query` equal to the exact preset
    text, `last_run_operation: artifact`;
  - hybrid for `subjunctive` with `state` and `depth`: policy
    `concept_hybrid_rrf_v1`.
- **Health, static and HEAD:** `/healthz`, `/readyz`, `/`, `/assets/app.js`,
  HEAD.
- **Identical bodies:** 7 routes return byte-identical bodies at the root and
  under `/api`.

**Denied routes, before any handler runs:**
- **Proof that nothing runs:** in the transport test, a recording inner
  handler saw none of the denied requests:
  - 34 GET paths × {root, `/api`} → `404`;
  - 6 methods × 8 paths → `405` with `Allow: GET, HEAD`.
- **What is denied:**
  - free-text `/knowledge-library/semantic-search` and `/hybrid-search`;
  - entry/analysis/extraction/capture/inventory/concept/reviewable-unit/
    resolution routes;
  - annotation dataset and quality, retrieval evaluation and comparison,
    annotation operations;
  - unknown paths, `/api`, `/api/`, `/api/assets/…`, a bare `/assets/`;
  - non-canonical paths (trailing slash, `..`, `//`), an encoded `%2F` and
    upper-case variants.
- **Without `-web-dir`,** `/` and `/assets` are denied too.

**Nothing changes on denied requests:**
- **What was compared** before and after (`cmd/server`):
  - the `demo.db` SHA-256;
  - the domain fingerprint;
  - the preset-vector counters (0 lookups, 0 refused).
- **What was sent:** 4 write methods × 8 paths × {root, `/api`}, then 15
  denied provider-triggering or full-surface GETs × {root, `/api`},
  including `/retrieval-evaluation/v1?retriever=embedding_retriever_v1`
  (normally an embedding-provider path).
- **Bad preset requests** (`q` without a preset, `q` alongside a preset, an
  empty or unknown preset, a duplicate preset, an unknown parameter,
  `limit=0`) → `400`/`404` on both routes. No vector lookup happened.
- **Host boundary:** a foreign `Host` → `403` (the boundary is preserved).
- **One valid hybrid preset search** gives exactly 1 lookup, 0 refused, and
  an unchanged database.
- **The smoke repeats this** against the real binary:
  - counters stay `0 0` across all denied requests;
  - four preset searches give `4 0`;
  - the hybrid result is identical at the root and under `/api`;
  - the `demo.db` hash is unchanged, with no `-wal` file;
  - the artifact still validates afterwards.

**Startup refusals:**
- **Provider configuration:** `AI_PROVIDER=openai`, `EXTRACTOR_PROVIDER=openai`,
  `EMBEDDING_PROVIDER=http`, `SEMANTIC_SEARCH=qdrant` and an unknown analyzer
  are all refused with "public demo refuses live providers". The smoke checks
  the same against the real binary: exit 1.
- **Artifact:** a mechanical artifact without `-public-demo-allow-mechanical`
  is refused, and a missing artifact directory is refused.

**Artifact integrity** (17 tampering cases, each giving `ErrArtifact`; the
unaltered copy still opens):
- **Missing files:** the manifest, the database, the vectors file.
- **Altered bytes:** database bytes changed; a vector value changed (manifest
  stale).
- **Consistent re-hash still caught by the deeper checks:**
  - a preset text changed while its envelope was kept;
  - a preset envelope hash changed;
  - a preset vector with the wrong dimension;
  - a zero document vector;
  - a document content hash changed;
  - a Concept without a vector;
  - a duplicate preset.
- **Manifest identity changed:** the model id differs from `vectors.json`;
  mechanical vectors relabelled as a real model; the query representation
  changed; the fingerprint changed; an unknown manifest field.
- **Other database checks:**
  - a database whose migration ledger differs is refused;
  - a missing database is not created;
  - the opened database refuses writes ("attempt to write a readonly
    database").
- **Build refusals:** a non-empty output directory, non-synthetic fixtures,
  and output inside the repository (CLI exit 2).
- **Reproducibility:** two builds give identical `vectors.json` and
  `fixtures.json` hashes, artifact version (`54386d802b65d2b3`) and domain
  fingerprint. The `demo.db` bytes differ (timestamps), as documented.

**Provider and index:**
- **Provider:** only the exact preset envelope returns a vector. The bare
  preset text, any other envelope and the empty string are refused with
  `ErrEmbeddingProviderUnavailable` and counted.
- **Index:** every write method returns `ErrReadOnlyIndex`; only the artifact
  collection exists; queries are ordered by similarity.

**Frontend:**
- **Demo shell (`PublicDemoApp.test.tsx`):** it shows the intro (synthetic,
  read-only, free-text semantic disabled), the mechanical-vector banner, and
  the title and language. It has no workbench tabs and no
  import/analysis/extraction controls, and sends GET only.
- **Searches:** keyword is free text. Semantic and hybrid replace the text box
  with "Example query" options showing `label: “exact text”`, plus the
  restriction note. The requests are exactly
  `/api/knowledge-library/demo/semantic-search?preset=miss-someone` and
  `/api/knowledge-library/demo/hybrid-search?preset=no-longer&state=active`.
  No free-text semantic or hybrid request is sent, and only allowlisted paths
  are called.
- **Normal mode:** the existing 217 workbench tests pass unchanged. The demo
  routes return `404` in normal mode at the root and under `/api`, and the
  free-text hybrid route still works there.

## NOT RUN

- **Real browser:** no browser automation was available in this session. The
  page was served and fetched with `curl` only.
- **Real-model vectors and release artifact:** BLOCKED, as above.
- **Remote deployment:** no NAS run, no public host, no reverse proxy, no DNS
  change and no publication. No Qdrant either: the demo does not use it, and
  Docker is unavailable on this Mac.
- **Security audit:** none. The allowlist and read-only behaviour are proven
  only by the tests above.

## Remaining deployment steps (human-owned)

1. Produce a real-model `vectors.json` for the same fixtures in a separately
   authorized run, rebuild the manifest, and confirm `prepare validate
   -release` exits 0.
2. Check the demo in a real browser locally (steps in PUBLIC_DEMO.md).
3. Provision the host per PUBLIC_DEMO.md: dedicated user, read-only release
   directory, loopback listener, explicit environment, `HTTP_ALLOWED_HOSTS`,
   and a TLS reverse proxy passing GET/HEAD only with rate limits.
4. Decide on publication and DNS. Neither is authorized by this task.
