# Read-only public demo (FLH-073)

The public demo runs the Knowledge Library over a **synthetic** artifact.
Visitors can browse Concepts, open a Concept's filed units, follow each unit
back to its original (synthetic) question, and compare keyword, semantic and
hybrid results for a fixed set of labelled example queries.

- **Read-only:** it records nothing.
- **No AI:** it calls no AI service and computes no embeddings.
- **Data:** it never opens the personal database.
- **Language:** English by default, with an optional 简体中文 interface
  (FLH-083). Only interface text changes; artifact data, preset texts and
  provenance stay as built, and the choice is kept in the visitor's browser
  only.

Contract: [plan](plans/FLH-073-public-readonly-demo.md). Evidence:
[validation](validation/FLH-073-public-readonly-demo.md). Tooling:
[scripts/demo/flh073/](../scripts/demo/flh073/README.md).

**Integrity fixes (FLH-075):** [plan](plans/FLH-075-public-demo-integrity.md),
[validation](validation/FLH-075-public-demo-integrity.md). They fix the two
defects that the independent FLH-074 acceptance found: static files could
escape the web root through a symlink, and the domain fingerprint did not cover
admission authority. Artifacts built before FLH-075 must be rebuilt
([below](#rebuilding-an-older-artifact)).

**Release preparation (FLH-076):**
[plan](plans/FLH-076-public-demo-release-preparation.md),
[validation](validation/FLH-076-public-demo-release-preparation.md). It adds:
- the real-vector pipeline ([below](#real-model-vectors-flh-076));
- real-browser acceptance;
- the portable release package and deployment templates
  ([below](#release-package-and-deployment-handoff-flh-076));
- fingerprint v3.

> **Release status: CANDIDATE prepared, not deployed (FLH-078).** A
> real-model artifact exists (artifact `d025f217f4d76396`, the pinned E5
> deployment `…/float16/singleton_v1/5a3e23f28a05baff`), packaged as
> `flh-public-demo-flh078-rc1`, accepted on Linux and in a real browser.
> Details, hashes and limits:
> [FLH-078 report](validation/FLH-078-demo-release-candidate.md). Nothing has
> been published, installed or changed in DNS; public deployment needs a
> separate decision.
>
> Artifacts built from **mechanical test vectors** (feature hashing of words,
> not a language model) still package only as `…-BLOCKED`: their semantic and
> hybrid rankings show the ranking mechanics only and say nothing about
> relevance.

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
  - the database's domain fingerprint, contract `flh076_domain_fingerprint_v3`
    ([below](#domain-fingerprint-v3));
  - for model vectors, `provenance.json`, which must bind every vector
    ([below](#real-model-vectors-flh-076)).

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

## Static files and symlinks

The demo web build (`-web-dir`) is served through an `os.Root` opened on that
directory. Each file open is confined to the directory tree by the operating
system's directory handle, so a link swapped in after startup is confined
too; there is no separate path check that could race.

| Case | Result |
| --- | --- |
| Regular files inside the web directory | Served (`/`, `/assets/…`) |
| Relative symlink (file or directory, any depth) whose target stays inside the web directory | Followed |
| Absolute symlink, even to a path inside the web directory | Refused, `404` |
| Symlink resolving outside the web directory (directly, through `..`, or through a linked directory) | Refused, `404` |
| Directories | Never listed, `404` |
| `index.html` resolving outside the web directory | Startup error |
| The `-web-dir` path itself being a symlink | Allowed; resolved once at startup |

**Release rule:** ship the demo web build as plain files. Before deploying,
`find <web-dir> -type l` should print nothing. The policy above is a
safeguard, not a reason to keep links.

**Not covered:** `os.Root` does not stop hard links, bind mounts or other
filesystem-level aliases created by someone with write access to the
directory. Keep the release directory read-only.

## Domain fingerprint (v3)

The manifest's `domain_fingerprint` (`version: flh076_domain_fingerprint_v3`)
is a SHA-256 over the content columns of every table the public library reads:
- entries and analyses;
- feedback;
- extractions and the current-extraction selection;
- units;
- admission recommendations and overrides;
- Concepts, links, memberships, distinctions, unit judgments;
- captures.

It also records row counts, and requires the annotation-operation and semantic
index tables to be empty. A test fails if a table in the schema is neither
covered nor explicitly exempted.

**Timestamps:**
- *Absolute* timestamps are excluded, so the same fixture always produces the
  same fingerprint and artifact version.
- Where reads pick the latest record by `created_at` (admission, feedback,
  links, distinctions, judgments), each record's **position in the order the
  reads use** is included, so reordering them invalidates the artifact:
  - within a table, by `(created_at, id)`;
  - SAME links and DISTINCT decisions in one merged order, because effective
    annotation compares them, with ties placing the distinction first (a
    SAME at an equal time wins).
- **v3 vs v2 (FLH-075):** v2 gave equal timestamps equal ranks. Whether two
  rows were written within the same clock tick could therefore change the
  fingerprint between identical builds. FLH-076 found this when two builds of
  the same fixtures differed. 15 consecutive v3 builds were identical.
- The exact bytes, including displayed dates, are still bound by
  `files["demo.db"]`.

**Changing any covered authority invalidates the artifact,** even when someone
also refreshes `files["demo.db"]`. For example, suppressing an admission
recommendation, pinning an extraction or retiring a Concept. This detects
inconsistent edits. It is not a signature: someone who can rewrite the
database *and* recompute the manifest can still forge an artifact. Keep
release directories read-only and record the manifest SHA-256 you deploy.

## Rebuilding an older artifact

Artifacts from FLH-073 (fingerprint without a `version`) and FLH-075 (`v2`) are
refused by the server and `prepare validate` with `domain fingerprint contract
… is not flh076_domain_fingerprint_v3 … Rebuild the artifact`. Nothing is
converted in place; build a new directory:

```sh
go build -o /tmp/flh-prepare ./scripts/demo/flh073/prepare
/tmp/flh-prepare build -out /new/artifact/dir -fixtures scripts/demo/flh073/fixtures/catalog.json
/tmp/flh-prepare validate -artifact /new/artifact/dir            # 0
/tmp/flh-prepare validate -artifact /new/artifact/dir -release   # 3 (BLOCKED) for mechanical vectors
```

Then point the release at the new directory, as for any rollout. Keep the old
directory unchanged if you want it for comparison. The rebuilt artifact has a
new manifest SHA-256 and artifact version. For model vectors, rerun
`prepare import` from the completed work directory into a new directory: it
sends nothing.

## Real-model vectors (FLH-076)

`prepare` embeds the exact production texts through the existing E5 HTTP
service and imports them into a model artifact.

| Position (20 for the catalog) | Text sent | Representation | E5 role |
| --- | --- | --- | --- |
| `concept:<id>` (12) | `BuildSemanticIndexDocument(c).Text` | `concept_embedding_text_v1`, `type: concept` | `passage` |
| `preset:<id>` (8) | `ConceptSearchQueryEmbeddingText(text)` | `concept_search_query_v2`, `type: query` | `query` |

**`prepare plan`** prints the plan hash and counts: 20 positions, so 3 POSTs at
batch 8.

**`prepare embed -work DIR -base-url URL -deployment ID -dimensions N
-allow-live`:**
- **Budget:** a persistent budget per work directory: at most 64 positions,
  16 POSTs and 2 readiness probes, charged *before* sending. If the remaining
  budget is short, the run is refused (exit 3) with nothing sent.
- **Readiness:** `GET /readyz` must be 200, and `GET /manifest` must report
  exactly `-deployment`.
- **Each POST** is reserved, then sent with the production HTTP client. Each
  vector must have N dimensions, be finite and have a unit norm (±1e-3). Its
  receipt (text hash, deployment, dimensions, vector hash, POST number) is
  saved atomically with the POST's outcome.
- **Failures:** the run stops at the first failure. Nothing is retried, and
  the POST stays charged.
- **Resume:** rerunning the same command sends **only** positions without a
  valid receipt.
- **`prepare status -work DIR`** shows progress offline.

**`prepare import -work DIR -out NEW_DIR`:**
- **Checks:** the plan must equal the fixtures', and every position needs
  exactly one valid receipt from a completed POST.
- **Output:** it builds the artifact in a temporary sibling directory, adding
  `provenance.json`; validates it with the server's loader; and only then
  renames it to `NEW_DIR`, which must not exist. Old artifacts are never
  touched.

**The loader requires `provenance.json` for `source: "model"`.** Every vector
must be bound to its exact text hash (document content hash, or envelope
hash), representation, role, vector hash, a completed POST, and a successful
probe of the same deployment. A mechanical artifact relabelled as `model` is
refused, with or without copied provenance.

**Trust boundary:**
- this records what the preparation received; it is not a cryptographic proof
  of the producing model;
- a service lying about its manifest, or someone rewriting every local file,
  could produce consistent files;
- the release packager therefore also requires the model id to be a pinned E5
  deployment equal to `--expected-deployment`.

**Continuation (completed in FLH-078).** This command produced the current
artifact: 20 positions in 3 POSTs. Its work directory has now used both of its
readiness probes, so running `embed` again there is refused. A new artifact,
for example for another deployment id, needs a new work directory and its own
budget decision. Run it from the repository root:

```sh
go build -o /tmp/flh-prepare ./scripts/demo/flh073/prepare && DEP='multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff' && /tmp/flh-prepare embed -work "$HOME/flh076/e5-work" -base-url http://100.118.109.6:8765/v1 -deployment "$DEP" -dimensions 768 -allow-live && /tmp/flh-prepare import -work "$HOME/flh076/e5-work" -out "$HOME/flh076/artifact-e5" && bash scripts/demo/flh076/package.sh --artifact "$HOME/flh076/artifact-e5" --revision "<YOUR-REVISION-LABEL>" --label rc2 --out "$HOME/flh076/packages" --expected-deployment "$DEP"
```

If the service reports another deployment id (for example after a library
upgrade), `embed` refuses. Adopting a new identity is a separate decision.

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

**AWS (FLH-084):** a prepared, not yet applied, single-EC2 deployment of a
release package is in [AWS_DEMO.md](AWS_DEMO.md): no inbound access, private
preview over Session Manager, verified install and rollback with `flh-release`.
The general notes below still apply to any host.

**Server and storage**
- **Account:** a dedicated, unprivileged system user, with its own directory,
  for example `/srv/flh-demo/{bin,releases,current}`.
- **Releases:** each release directory holds the server binary's version, the
  artifact directory and the demo web build. `current` is a symlink to the
  active release.
- **Permissions:** make the artifact and web build read-only for that user
  (`chmod -R a-w releases/<id>`). Check that the web build has no symlinks
  (`find releases/<id>/web -type l` prints nothing). The server needs no write
  access anywhere; it writes only logs to stderr.
- **Process:** run it under the init system (template:
  `scripts/demo/flh076/deploy/flh-public-demo.service.example`) with an
  explicit environment and `WorkingDirectory` set to the release directory, so
  no `.env` is picked up:

  ```text
  LISTEN_HOST=127.0.0.1  PORT=18970
  AI_PROVIDER=rule-based  EXTRACTOR_PROVIDER=disabled  EMBEDDING_PROVIDER=disabled  SEMANTIC_SEARCH=disabled
  HTTP_ALLOWED_HOSTS=<public demo hostname>
  ExecStart=/srv/flh-demo/current/bin/linux-amd64/flh-server -public-demo-artifact /srv/flh-demo/current/artifact -web-dir /srv/flh-demo/current/web
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

**Producing a releasable artifact:** see
[Real-model vectors](#real-model-vectors-flh-076). The demo needs no Qdrant,
because it reads vectors from the artifact.

## Release package and deployment handoff (FLH-076)

**Build** (no Git is run; `--revision` is the label you supply):

```sh
bash scripts/demo/flh076/package.sh --artifact ARTIFACT_DIR --revision LABEL --label NAME --out /abs/out \
  [--expected-deployment DEPLOYMENT_ID]
```

**Output:** `flh-public-demo-NAME[-BLOCKED]/`, plus a `.tar.gz` and its
`.sha256`.

**Packaging host:** Linux or macOS, with Go, Python 3, the `web/node_modules`
install, and `sha256sum` or `shasum`. `sha256sum` is used when present
(usual on Linux), else `shasum -a 256` (macOS). With neither, the packager
stops with exit 2 before building anything. Both produce the same
`SHA256SUMS` format.

| Path | Contents |
| --- | --- |
| `bin/linux-amd64/`, `bin/linux-arm64/` | Static `flh-server` and `flh-prepare` |
| `artifact/` | The artifact |
| `web/` | The demo build |
| `deploy/` | `flh-public-demo.service.example`, `nginx-flh-public-demo.conf.example`, `ctl.sh` |
| `RELEASE.json` | Label, source revision, Go version, artifact identity, model provenance summary, runtime requirements, release status |
| `SHA256SUMS`, `validate-release.sh`, `README.md` | Validation and instructions |

**The packager refuses:**
- symlinks, unexpected files, `.env`, keys, logs or extra databases;
- an artifact that does not validate;
- a model artifact whose id is not a pinned E5 deployment equal to
  `--expected-deployment`.

**Status:** mechanical artifacts produce `…-BLOCKED`, whose
`validate-release.sh` exits 3. Only a model artifact can be `CANDIDATE`.

**Runtime:** Linux, the package and a loopback port. No encoder, GPU,
Windows, Qdrant, cloud credentials, API key or egress.

**Commands** (in the package):
- `./validate-release.sh`: 0 for a candidate, 3 for BLOCKED, 1 if invalid;
- `deploy/ctl.sh start|status|stop RUNTIME_DIR` (`PORT`, `ALLOWED_HOST`);
- **rollback:** switch the `current` symlink (outside the release) back and
  restart.

**Restart, rollback and recovery, as rehearsed in FLH-078**
- **Layout:** releases in `releases/<package>/`, made read-only after
  validation; `current` is a symlink beside them; one runtime directory that
  stays writable.
- **Switch:** replace `current` atomically: `ln -sfn releases/<new>
  current.new && mv -T current.new current`.
- **Restart:** `current/deploy/ctl.sh stop RUN`, then `current/deploy/ctl.sh
  start RUN`, with the same `PORT` and runtime directory. `stop` finds the
  previous server through the recorded pid, even after the switch.
- **Check the identity** after every start: `artifact.version`,
  `manifest_sha256` and `real_model` from `/knowledge-library/demo`.
- **Invalid release:**
  - `validate-release.sh` exits 1, so don't switch.
  - If one is selected anyway, the server refuses to start (for example, a
    `fixtures.json` hash differing from the manifest), and nothing serves.
  - **Recovery:** switch `current` back to the last good release and run
    `start`.
- **Runtime directory must be writable.** `ctl.sh start` checks this before it
  launches anything. If the pid path is not a regular file, or the runtime
  directory is unwritable (quota, permissions), start exits 1 with "start
  refused … nothing launched". If recording the pid fails after the launch
  (disk full), start stops the process it launched and exits 1 with "could not
  record pid". The same happens when start is interrupted by SIGHUP, SIGINT or
  SIGTERM before it reports `started`. Free the space or fix the directory,
  then start again (FLH-080 D3).
- **Exception: SIGKILL.** If `ctl.sh` itself is killed with SIGKILL in the
  instant between the launch and the pid rename, the server can still be left
  untracked. Find it by its full `-public-demo-artifact <release>/artifact`
  command line and stop that one process.

**Local smoke of a package:** `bash scripts/demo/flh076/smoke_package.sh PKG
/abs/new/run/dir`. Off Linux, it uses host builds of the same source.

**Real-browser acceptance:** `bash scripts/demo/flh076/browser/run.sh
/abs/new/dir [ARTIFACT_DIR]`. It drives the installed Chrome headless
through `playwright-core` installed in that directory, with no browser
download.

**Final operator inputs:**
- **Source revision label:** the source revision you are releasing.
- **Real-model artifact:** produced by the continuation command above.
- **Deployment id:** the expected E5 deployment id (the pinned FLH-060 id
  unless you adopt a new one).
- **Host:** the public host name (`HTTP_ALLOWED_HOSTS`, nginx
  `server_name`).
- **Certificate:** the TLS certificate paths.
- **Port and paths:** a free loopback port (default 18970), the target
  architecture (amd64 or arm64), and the release root (default
  `/srv/flh-demo`).

**Remaining deployment steps** (human-owned; none performed). Steps 1 and 2
were done in FLH-078 for `flh-public-demo-flh078-rc1`:
1. Run the continuation command, and get `validate-release.sh` exit 0.
2. Run the browser acceptance against the CANDIDATE artifact
   (`--expect-vectors model` is selected automatically).
3. Create the service user and the release root.
4. Unpack, validate, and make the release read-only.
5. Adapt and install the systemd unit and nginx block yourself, and reload.
6. Check `/readyz` and `/knowledge-library/demo` through the proxy.
7. Decide on publication and DNS. These are not authorized by FLH-076.

## Limits

- **Synthetic data:** 8 questions, 11 units and 12 Concepts.
- **Presets:** 8 example queries.
- **Keyword search:** prefix matching with AND semantics. Many natural-language
  example queries therefore match nothing by keyword, which the hybrid
  evidence shows.
- **Proven:** route filtering, read-only behaviour and ranking mechanics, by
  local tests and a loopback smoke only. **Not claimed:** relevance, security
  audit or public hosting.
