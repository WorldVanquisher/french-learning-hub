# Read-only public demo (FLH-073)

The public demo runs the Knowledge Library over a **synthetic** artifact.
Visitors can browse Concepts, open a Concept's filed units, follow each unit
back to its original (synthetic) question, and compare keyword, semantic and
hybrid results for a fixed set of labelled example queries.

- **Read-only:** it records nothing.
- **No AI:** it calls no AI service and computes no embeddings.
- **Data:** it never opens the personal database.

Contract: [plan](plans/FLH-073-public-readonly-demo.md). Evidence:
[validation](validation/FLH-073-public-readonly-demo.md). Tooling:
[scripts/demo/flh073/](../scripts/demo/flh073/README.md).

> **Release status: BLOCKED.** The only artifact that can be built today uses
> **mechanical test vectors** (feature hashing of words, not a language
> model). Its semantic and hybrid rankings show the ranking mechanics only and
> say nothing about relevance; for example, one example query ranks an
> unrelated Concept first. A public release needs a real-model artifact, which
> requires a separately authorized run. Nothing has been published, and no DNS
> change has been made.

## What the server does in demo mode

`cmd/server -public-demo-artifact DIR` (plus `-web-dir` for the demo web
build):

- **Database:** it opens only `DIR/demo.db`, read-only and immutable. `DB_PATH`
  is never opened. Nothing is migrated, and the migration ledger must match
  the server exactly.
- **Artifact checks:** it validates the artifact before serving:
  - the file hashes, the vector identity (source, model, dimensions,
    representations) and each preset's exact query envelope;
  - that every Concept has exactly its recorded document vector;
  - the database fingerprint.

  Any mismatch stops startup.
- **Providers:** startup is refused unless `AI_PROVIDER=rule-based`,
  `EXTRACTOR_PROVIDER=disabled`, `EMBEDDING_PROVIDER=disabled` and
  `SEMANTIC_SEARCH=disabled`. No provider client is constructed.
- **Mechanical vectors:** an artifact with mechanical vectors also needs
  `-public-demo-allow-mechanical`, intended for local smoke tests only.
- **Allowlist:** only these routes are served, at the root and under `/api`:
  - `GET`/`HEAD` on `/healthz`, `/readyz`, `/knowledge-library/concepts`,
    `/knowledge-library/concepts/{id}`, `/knowledge-library/units/{id}/source`,
    `/knowledge-library/demo`, `/knowledge-library/demo/semantic-search` and
    `/knowledge-library/demo/hybrid-search`;
  - plus `/` and `/assets/…` with `-web-dir`.
- **Refusals:** every other method gets `405`; every other path gets `404`,
  including free-text semantic/hybrid search, all writes and the
  annotation/evaluation routes. The existing Host/Origin boundary stays in
  front.
- **Queries:**
  - keyword search accepts free text within its existing bounds;
  - semantic and hybrid accept only `preset=<id>`, and any `q` or other
    parameter gets `400`;
  - semantic and hybrid use the unchanged services and the
    `concept_hybrid_rrf_v1` policy, over an in-process read-only index of the
    artifact's vectors. **No Qdrant is used.**

## Local smoke (this Mac or any Linux host; no Docker)

```sh
bash scripts/demo/flh073/smoke.sh /tmp/flh073-smoke-$(date +%s)
```

It builds the binaries, a mechanical artifact and the demo web build in that
new directory. It then starts the demo on `127.0.0.1:18973` with an empty
environment and checks:
- allowed and denied requests at the root and under `/api`;
- the provider-config refusal and the release `BLOCKED` exit;
- unchanged database bytes and counters;
- that the server stops.

It prints `SMOKE PASSED` and exits 0 only if every check passed.

**To look at it in a browser** (by hand):

```sh
W=/tmp/flh073-manual; go build -o $W/bin/server ./cmd/server
go run ./scripts/demo/flh073/prepare build -out $W/artifact
(cd web && VITE_FLH_PUBLIC_DEMO=1 npx vite build --outDir $W/web --emptyOutDir)
(cd $W && env -i PATH=/usr/bin:/bin LISTEN_HOST=127.0.0.1 PORT=18974 \
  $W/bin/server -public-demo-artifact $W/artifact -public-demo-allow-mechanical -web-dir $W/web)
# open http://127.0.0.1:18974/ ; stop with Ctrl-C ; rm -rf $W
```

## Deployment preparation (not performed)

**Server and storage**
- **Account:** a dedicated, unprivileged system user, with its own directory,
  for example `/srv/flh-demo/{bin,releases,current}`.
- **Releases:** each release directory holds the server binary's version, the
  artifact directory and the demo web build. `current` is a symlink to the
  active release.
- **Permissions:** make the artifact read-only for that user
  (`chmod -R a-w releases/<id>/artifact`). The server needs no write access
  anywhere; it writes only logs to stderr.
- **Process:** run it under the init system with an explicit environment and
  `WorkingDirectory` set to the release directory, so no `.env` is picked up:

  ```text
  LISTEN_HOST=127.0.0.1  PORT=18970
  AI_PROVIDER=rule-based  EXTRACTOR_PROVIDER=disabled  EMBEDDING_PROVIDER=disabled  SEMANTIC_SEARCH=disabled
  HTTP_ALLOWED_HOSTS=<public demo hostname>
  ExecStart=/srv/flh-demo/current/bin/server -public-demo-artifact /srv/flh-demo/current/artifact -web-dir /srv/flh-demo/current/web
  ```

- **Not on the public host:** no API keys, `.env`, personal database, Qdrant
  or embedding service. The artifact contains only synthetic fixtures,
  vectors and hashes. Check it before copying with `prepare validate
  -artifact DIR -release`, which must exit 0.

**Reverse proxy** (TLS terminates here; the server stays on loopback):
- **Exposure:** forward only `GET` and `HEAD` to `127.0.0.1:18970` and answer
  every other method `405` at the proxy as well. The server refuses them
  anyway.
- **Host:** pass the original `Host` (it must be listed in
  `HTTP_ALLOWED_HOSTS`). Do not rely on forwarded headers: the server grants
  them no trust.
- **Limits:** rate-limit per client and cap request size. The demo has no
  authentication; it is read-only public data by design.
- **Never exposed:** port 18970 itself, Qdrant (not used) or any internal
  service.

**Startup, rollback and shutdown**
- **Startup:** start the service, then check `GET /readyz` and `GET
  /knowledge-library/demo`. Confirm that `artifact.version`,
  `artifact.manifest_sha256` and `real_model: true` are what you released.
- **Rollback:** point `current` at the previous release directory and restart.
  Artifacts are immutable, so no data migration is involved.
- **Shutdown:** stop the service. SIGTERM triggers a graceful shutdown (5 s).
  Nothing needs cleaning up because nothing is written.

**Producing a releasable artifact (future, separately authorized)**
1. Run the same fixtures through a real embedding model, for example the
   pinned E5 deployment, used for both the Concept documents
   (`concept_embedding_text_v1`) and the preset envelopes
   (`concept_search_query_v2`).
2. Write `vectors.json` in the documented schema `flh073_demo_vectors_v1`,
   with `source: "model"`, `real_model: true` and that deployment's
   `model_id` and dimensions.
3. Write a manifest with `release_status: "model_vectors"`.
4. Make sure `prepare validate -release` exits 0.

The preparation tool has no live-call code today. A later NAS run would need
Qdrant only if the semantic index were built there with the existing
`semantic-index` CLI. The demo itself needs no Qdrant, because it reads
vectors from the artifact.

## Limits

- **Synthetic data:** 8 questions, 11 units and 12 Concepts.
- **Presets:** 8 example queries.
- **Keyword search:** prefix matching with AND semantics. Many natural-language
  example queries therefore match nothing by keyword, which the hybrid
  evidence shows.
- **Proven:** route filtering, read-only behaviour and ranking mechanics, by
  local tests and a loopback smoke only. **Not claimed:** relevance, security
  audit or public hosting.
