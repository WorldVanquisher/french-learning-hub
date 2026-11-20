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

### Caching, page identity and newer versions (demo-refresh frontend batch)

| What | Behaviour |
| --- | --- |
| `index.html` | `Cache-Control: no-cache` (revalidated on every visit) |
| `/assets/name-XXXXXXXX.ext` (Vite's content-hashed names) | `Cache-Control: public, max-age=31536000, immutable`; a rebuild changes the name |
| Any other `/assets/…` file | `no-cache` |
| A missing asset | `404` with no caching header (never cached) |
| Page identity | `package.sh` builds with `VITE_FLH_BUILD_ID=<package name>` and `VITE_FLH_API_BASE=/api`: `<meta name="flh-build">`, `<html data-flh-build>` and `RELEASE.json` `web` (`build_id`, `api_base`, `entry`, `index_sha256`) name the same package |
| Startup | `index.html` shows a "Loading…" line until the page renders, and after 8 seconds says to check the connection and reload (plain HTML and CSS, no JavaScript) |
| A tab left open across an upgrade | When the tab is shown again (or a lazily loaded part fails to load), the page compares its entry script with the one `GET /` now names. If they differ, it shows "A newer version … Reload". It never reloads by itself |

`VITE_FLH_API_BASE` must be a same-origin path; anything else (a scheme, a
host, `//`) stops the build. The server has no cross-origin access, and the
page never calls another origin.

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
- **Migration 012 columns are not fingerprinted.** The column lists predate
  FLH-095, so `entry_analyses.explanation_en/_zh`,
  `knowledge_units.statement_en/_zh` and the per-language feedback columns are
  outside the domain fingerprint (the coverage test checks tables, not
  columns). They are protected only by the `files["demo.db"]` hash. Demo unit
  and source responses now include `statements` from those columns; fixture
  artifacts store NULL there.

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

### Migration 012 (FLH-095) and existing artifacts

The server compares the artifact's `schema_migrations` ledger with its own
embedded migrations exactly. A binary built with migration
`012_bilingual_explanations` therefore refuses any artifact built before it
(`database migrations … differ from this server's …`), and an older binary
refuses an artifact built with 012. Rebuild the artifact with the same tree as
the binary, as above.

A release package bundles its own binary and artifact, so an already packaged
or deployed release is unaffected. Only a new package needs a matching rebuild.

## Real-model vectors (FLH-076)

`prepare` embeds the exact production texts through the existing E5 HTTP
service and imports them into a model artifact.

| Position (23 for the catalog) | Text sent | Representation | E5 role |
| --- | --- | --- | --- |
| `concept:<id>` (14) | `BuildSemanticIndexDocument(c).Text` | `concept_embedding_text_v1`, `type: concept` | `passage` |
| `preset:<id>` (9) | `ConceptSearchQueryEmbeddingText(text)` | `concept_search_query_v2`, `type: query` | `query` |

**`prepare plan`** prints the plan hash and counts: 23 positions, so 3 POSTs at
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

**Continuation (completed in FLH-078).** This command produced the FLH-078
artifact from the catalog of that time: 20 positions in 3 POSTs. Its work directory has now used both of its
readiness probes, so running `embed` again there is refused. A new artifact,
for example for another deployment id, needs a new work directory and its own
budget decision. Run it from the repository root, with `E5` set to your E5
service's `/v1` base URL (a loopback or private address; it is not recorded
here):

```sh
go build -o /tmp/flh-prepare ./scripts/demo/flh073/prepare && DEP='multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff' && /tmp/flh-prepare embed -work "$HOME/flh076/e5-work" -base-url "$E5" -deployment "$DEP" -dimensions 768 -allow-live && /tmp/flh-prepare import -work "$HOME/flh076/e5-work" -out "$HOME/flh076/artifact-e5" && bash scripts/demo/flh076/package.sh --artifact "$HOME/flh076/artifact-e5" --revision "<YOUR-REVISION-LABEL>" --label rc2 --out "$HOME/flh076/packages" --expected-deployment "$DEP"
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
| `artifact/` | The artifact, with a public `provenance.json` (below) |
| `web/` | The demo build |
| `deploy/` | `flh-public-demo.service.example`, `nginx-flh-public-demo.conf.example`, `ctl.sh` |
| `RELEASE.json` | Label, source revision, Go version, artifact identity, model provenance summary, runtime requirements, release status |
| `SHA256SUMS`, `validate-release.sh`, `README.md` | Validation and instructions |

**Public provenance (`scripts/demo/flh076/public_provenance.py`):**
- The preparation records the embedding service's address in the artifact's `provenance.json`. That
  address is private.
- `package.sh` therefore projects its staged copy of the artifact onto an allowlist. The address and any
  unknown field are dropped, and a post's error text is emptied. It then updates `manifest.json`'s
  provenance entry and validates the copy with the server's loader. The input artifact is never changed.
- **What stays:** the artifact version, vectors, fixtures, database and fingerprint. The manifest
  digest differs from the private artifact's.
- **The check:** before checksums, `public_provenance.py check` allows only public fields in
  `RELEASE.json` and `artifact/provenance.json`. `RELEASE.json`'s model provenance summary no longer
  carries the address. A failure names the file and key path, never the value.
- **The gate (R3):** `check_package.sh` runs the same check in its identity stage, so the gate
  refuses a package that carries a non-public field. That includes every package built before this
  rule: their `RELEASE.json` and `artifact/provenance.json` hold the private host, and they must
  never serve as a public rollout or rollback artifact.

**Metadata versions and compatibility (R3-020):**
- **Schemas:** `RELEASE.json` keeps `flh076_public_demo_release_v1`, and `provenance.json` keeps the
  artifact's `flh076_vector_provenance_v1`. The public files hold a subset of those fields; no field
  was renamed or added, so readers of either schema read both.
- **Allowlist owner:** `public_provenance.py` (`RELEASE`, `PROVENANCE`). A new public field needs an
  allowlist entry, a test and a review: the packager and the gate refuse unknown keys at every
  depth.
- **Unchanged readers:**
  - the server's artifact loader, which revalidates the projected copy;
  - `validate-release.sh`;
  - `flh-release` (artifact version and manifest digest from the package's own files);
  - `check_served.py` (the manifest digest from the package).
- **What does change:** the artifact manifest digest, from `3aa4e7cc…` (private provenance) to
  `4c2488b2…` (public projection). The artifact version (`97dbe0f215af37e7`) and the domain fingerprint
  stay. An `--expect-manifest` pinned to `3aa4e7cc…` belongs to a private-provenance package; use
  `4c2488b2…`.
- **Projection is deterministic:** the same input artifact always gives the same `provenance.json`
  bytes and manifest digest. The R3 package is byte-identical to the packaging lane's reviewed
  projection.

**The packager refuses:**
- symlinks, unexpected files, `.env`, keys, logs or extra databases;
- a non-public field in `RELEASE.json` or `artifact/provenance.json`;
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

## Authored French examples (demo refresh, 2026-11-10)

Three questions are written in French, so a visitor can follow the whole path,
question → units → Concept → evidence, on French input:

| Question | Units | Concept(s) |
|---|---|---|
| « Dans « j'y vais » et « j'en veux », qu'est-ce que « y » et « en » remplacent ? » | `y remplace à + lieu`, `en remplace de + nom` | the pronouns y and en (two units, one question) |
| « Il faut que tu viennes demain » … pourquoi « viennes » ? | `il faut que + subjonctif de venir` | subjunctive after « il faut que » (now supported by two questions) |
| « je suis cuisinant » existe ? | `présent pour une action en cours`, `être en train de + infinitif` | two new Concepts |

A new preset, « doing something right now », exercises the new Concepts.
Changing the catalog changes the domain fingerprint, so every older artifact
(including the FLH-078/FLH-087 real-model artifact) must be rebuilt. A releasable
artifact needs a new real-vector run in a **new** work directory (23 positions,
3 POSTs). `scripts/validation/demo_refresh/accept_paths.mjs` walks these paths in
English and 简体中文 at desktop and phone widths against a running package.

## First visit: guided examples (demo first-visit task)

The starting screen says in one sentence what a visitor can do, then offers the
three authored questions above as **guided examples**, with direct search kept
below them for returning visitors.

- **Example screen:** the learner's question (marked French, unchanged in every
  interface language) → the units extracted from it → the Concepts they are
  filed under, with how much evidence comes from this question and how much
  from others. Each unit links to its source; each Concept opens with its
  evidence. Back actions return to the example, and from there to the starting
  screen with focus on that example's card. The search query and results are
  kept throughout.
- **No new API:** an example is resolved in the browser from the existing reads
  (one keyword search, the matched Concepts, one unit source) using a fixed
  query and a word from one unit's stored wording (`web/src/demo/examples.ts`).
  If a build lacks an example, the page says so and offers that search instead
  of guessing; `GuidedExample.test.tsx` keeps the definitions in step with
  `scripts/demo/flh073/fixtures/catalog.json`.
- **Labels:** *Read-only* and *Synthetic data* stay in the header on every
  screen; a mechanical build adds *Development build* and a plain warning that
  semantic and hybrid results in that build are not meaningful. The
  synthetic/read-only/no-AI notice and the artifact identity line stay visible
  on the starting screen, just below the examples (so the first example fits
  on a phone's first screen); only the longer explanation of Concepts and
  search modes is folded under "How this demo works".
- **Check:** `scripts/validation/demo_first_visit/accept_guided.mjs` (README
  beside it) walks every example in both languages at both widths, plus the
  loading, failed-read and no-match states.

Navigation and evidence (second change of the same task):

- **Back:** each screen is a browser-history entry on the same URL (no route,
  nothing sent), so the browser's or phone's Back retraces Concept → example →
  start instead of leaving the demo. The in-page back actions stay in a bar
  that remains in view while scrolling.
- **Concept and evidence:** a Concept page names itself, folds its identity
  details, says for each supporting unit which record it was taken from, and
  leaves out empty relation and history sections. The source page puts the
  learner's question first, says why the record is shown (the unit taken from
  it and the Concept it is filed under), and keeps the extraction and
  interpretation (the provenance trail) visible after the unit. Long
  identifiers wrap instead of widening the page.
- **Mechanical scores:** in a mechanical build, semantic and hybrid results
  carry their own notice that the order only shows how ranking works and is
  not evidence of relevance; a model build shows none.
- The private workbench's Knowledge Library is unchanged by all of this.

Resilience: a failed read of the demo description is shown with its status and
a *Try again* that recovers in place (before, the page stopped at "The demo is
unavailable" until reloaded). Slow, failed, out-of-order and empty reads are
exercised by `scripts/validation/demo_first_visit/accept_resilience.mjs` and
`web/src/demo/Resilience.test.tsx`.

Direct links and accessibility:

- **Direct links are URL fragments:** `/#example=y-en`, `/#concept=12`,
  `/#concept=12&unit=14`, optionally with `example=<key>` so the back actions
  return to that example. The address bar follows the visitor, so copying it
  shares the current screen, and a reload stays on it. Path links
  (`/example/y-en`, `/concept/12`) cannot work with the current serving: the
  server serves the demo only at `/` (no SPA fallback) and the demo boundary
  answers unknown paths `404`. A fragment is never sent to the server, so it
  needs no route, allowlist or nginx change. Malformed or unknown links open
  the starting screen; a link to a Concept that does not exist shows that
  read's error with the way back. Links carry IDs only, which are stable for a
  given catalog and change when the catalog changes.
- **Keyboard:** the whole guided path (start → example → Concept → evidence
  → back to the Concept → back to the example → start) works with Tab,
  Shift+Tab and Enter in 21 key presses. Each screen focuses its heading, which
  is never hidden under the return bar, and focus returns to the card a visitor
  started from. The return bar is in the same place in loading and error
  states.
- **Motion:** the demo has no animations, transitions or smooth scrolling, so
  `prefers-reduced-motion` needs no special case.
- **Check:** `scripts/validation/demo_first_visit/accept_a11y.mjs`.

## Navigation contract, walkthrough and phone layout (demo-ux lane)

**Navigation** (`web/src/demo/history.ts`; the workbench keeps no history):
- **Screens are entries.** The start (or a search's results), an example, a
  Concept and an evidence screen are each one browser-history entry.
  Opening a screen adds an entry. So does submitting a search that changes
  the results, or clearing one; repeating the same search adds nothing.
- **In-page back is the browser's Back.** An in-page "← Back …" action goes
  back in history when the screen it names is earlier in this visit, and
  keeps Forward. When that screen is not in the visit (the visitor arrived by
  a direct link), it replaces the current entry instead.
- **What this fixes.** Before, every in-page back added an entry. The next
  browser Back then returned to the screen just left, and Back and Forward
  looped between the two.
- **Reload and shared links keep the search.** The fragment may start with
  the submitted search: `#q=il+faut`, `#q=il+faut&state=active`,
  `#mode=semantic&preset=right-now`. It can be followed by any screen, as in
  `#q=il+faut&concept=1`. A reload therefore keeps both the screen and the
  way back to those results. An unknown preset, a query over 200 characters
  or any other malformed value opens the start, and the address is rewritten
  to `/`.
- **Stable identifiers.** Links use example keys, preset ids and Concept/unit
  IDs only. Rebuilding the artifact from the same catalog gives the same IDs,
  and the artifact's domain fingerprint fixes them.
- **Focus.** Each screen focuses its heading. Returning to the start focuses
  the example card you left from. Returning to search results focuses the
  Concept you opened.

**Walkthrough:**
- **Example screen:** it now shows all four steps. The fourth names the
  learning record, the extraction and the interpretation its units came
  from, and opens the evidence.
- **Step labels:** a Concept or evidence screen opened from an example says
  "Step 3 of 4 · Concept" or "Step 4 of 4 · Source evidence". The Concept
  screen also says what to do next.
- **Failed search:** a search that finds nothing explains how keyword
  matching works. It offers the examples' own queries and "Show all
  Concepts".
- **Empty catalog:** described as the demo build's. It no longer mentions
  Concept Review.
- **Evidence screen:** the recorded time is a UTC date and time in the
  interface language, and the exact stored value is in the element's
  `dateTime`. Two units from one record have distinct accessible names for
  their "View source record" buttons.
- **Languages:** all new text is in English and 简体中文.

**Phone layout** (`web/src/demo/demo.css`):
- **Scope:** every selector starts with `.demo-app`, the demo's root
  element. The shared `styles.css` is unchanged.
- **Wrapping:** demo text, identifiers and button labels wrap.
- **Preset list:** it stays within the screen. Before, it widened the page
  to 594 px on a 390 px phone.
- **Narrow phones:** at 400 px and below, page and panel spacing is tighter,
  so the first example starts on the first screen of a 320 px phone.

**Overflow checks:**
- **Device width:** overflow is measured against the device width. Under
  phone emulation `innerWidth` grows with the content, so the D1 check
  `scrollWidth <= innerWidth` passed a 421 px evidence page on a 390 px
  phone. `demo_refresh/accept_paths.mjs` now uses the device width and names
  the overflowing element.
- **Matrix:** `scripts/validation/demo_ux/accept_matrix.mjs` covers
  320/390/1280 px in both languages: walkthrough, navigation, keyboard, long
  bilingual text, every Concept and evidence screen, the states and private
  routes. A built-in self-test injects the old evidence-row layout and fails
  the run if the check does not catch it.
- **Static guards:** `web/src/demo/demoStyles.test.ts` runs in CI.

## Shared links, the way back and the package check (demo-candidate lane)

**Links that name nothing in this build:**
- **Malformed link** (an unknown example key or preset, a malformed ID, an
  over-long query, a link cut short): the start opens with a notice that the
  link matched nothing, and the address becomes `/`. Before, the start opened
  silently.
- **Well-formed link to an ID this build lacks** (`#concept=999`,
  `#concept=12&unit=999`): the screen says that this demo build does not have
  that Concept or unit and that the link may be mistyped, cut short or from
  another build. It offers "Open the example …", which opens the link's own
  example or the first one, as a new entry with no reload. There is no retry,
  because the server's 404 will not change. A failure that may pass (503, a
  network error) keeps its retry.

**Focus on the way back** (`web/src/demo/history.ts`):
- Opening a screen focuses its heading, as before.
- Coming back to a screen (Back, an in-page back or Forward) focuses the
  control that left it, when that control is on the page again. Examples are
  the "View source record" button used, the example's "Open the Concept"
  button, and the search field after Back undoes a search. Each entry records
  the control's id (`flhFocus`) when it is left.
- Otherwise, for example after a direct link or in a browser that does not
  focus a clicked button, the heading is focused, as when opening.
- The start screen has no heading of its own. Coming back to it when neither
  the control that left it nor the result or example the visitor came back
  from is on the page focuses the heading of what is shown: "Or search the
  library" when a search is shown, otherwise "Start with an example". This
  covers three cases: a missing Concept's back, a link whose search does not
  list its Concept (`#q=il+faut&concept=12`), and a search that failed while
  the visitor was away. Before FLH-153, focus was left on the page body in
  all three. A remembered control that is on the page but cannot take focus
  also falls back to the heading.
- **Before:** the evidence → Concept and Concept → example returns focused the
  heading, and Back past a search left focus on the page body.

**Overflow, measured twice** (`scripts/validation/demo_ux/accept_matrix.mjs`):
- **Document:** the root `scrollWidth` against the device width.
- **Elements:** every rendered element's right edge against the device
  width, even when an ancestor hides the overflow.
- **Self-test:** a second self-test hides the old layout's overflow with
  `overflow-x: hidden`. The document then fits, and the element check must
  still name the `dd`.

**Package check:** `scripts/validation/demo_candidate/check_package.sh PKG
WORK` checks one package from identity to browser, reusing the maintained
tools: `validate-release.sh`, `smoke_package.sh`, `deploy/ctl.sh`, the
write probe and the browser suites. `negative_controls.sh` proves that a
wrong identity, an accepted write and a build that mishandles a malformed
link are detected. See `scripts/validation/demo_candidate/README.md`.

## Searching first, and the learner's own direction (FLH-153 follow-up)

- **Results follow the search form.** In the demo, the paragraphs on how
  search works (terms, scope, semantic and hybrid) come after the results
  instead of inside the form. The "Public demo" note stays next to the
  modes. Before, 700 px of explanation separated the Search button from the
  first result on a 390 px phone.
- **A submitted search shows what it found.** Right after a submitted
  search, the page scrolls just far enough to bring the first result into
  view, or the no-match help, or the error. Focus stays in the form. The
  same happens for a search started from the no-match suggestions. A search
  opened by a link, a reload, Back or Forward does not scroll. Before, Search
  changed nothing on screen in any configuration, desktop included.
- **The learner's text keeps its own direction.** On the example and the
  evidence, the original question is shown with `dir="auto"`, and so is the
  context (an isolating `<bdi>` in the evidence's context row). A question
  that starts in a right-to-left script then reads in its own order.
  French, English and Chinese are unchanged.
- **The private workbench is unchanged.**
- **Checks:** `scripts/validation/demo_ux/accept_matrix.mjs` ("search: the
  first result is on screen after Search", "rtl: …").

## Supported addresses (FLH-153 part 3)

**The page is `/`.** The server serves no other page (there is no SPA
fallback), and the demo boundary refuses every other path with 404. Every
screen is named by the URL fragment, which the browser never sends to the
server. `web/src/demo/deepLink.ts` is the parser.

| Address | Screen |
|---|---|
| `/` | the start: examples, then the search with every Concept listed |
| `/#q=<words>` (optionally `&state=active\|orphaned\|retired`) | the start with that keyword search |
| `/#mode=semantic\|hybrid&preset=<id>` (optionally `&state=…`) | the start with a preset search; `<id>` must be one of the build's presets |
| `/#example=<key>` | a guided example (`en-train-de`, `y-en`, `il-faut-venir`, `imparfait`) |
| `/#example=<key>&step=<1–4>` | the same example at that step of its walkthrough (question, rules, Concept, evidence). A `step` outside 1–4, blank, or on any other screen is left out (R2) |
| `/#compare=<key>` | a comparison of two units (`present-en-train-de`, `imparfait-passe-compose`, `depuis-pendant`) |
| `/#compare=<key>&practice=<n>` | that comparison's practice question `n` (1-based; R3). A `practice` the comparison has no question for, blank or not 1–9, is left out (the pair opens). The link never holds an answer |
| `/#concept=<id>` | a Concept |
| `/#concept=<id>&unit=<id>` | a unit's source evidence, reached from that Concept |
| any search before a Concept or evidence (`/#q=il+faut&concept=1`) | the same screen; its back action returns to that search |
| `example=<key>` before a Concept or evidence (`/#example=y-en&concept=12&unit=12`) | the same screen; its back actions return to that example |
| `compare=<key>` before a Concept or evidence (`/#compare=depuis-pendant&concept=8&unit=9`) | the same screen; its back actions return to that comparison (to its question `n` with `&practice=<n>`, R3). `compare` with `example`, or an unknown key, is malformed |

**Rules:**
- **IDs:** 1–9 digits, no leading zero.
- **Queries:** at most 200 characters. Percent-encoded and raw Unicode are the
  same query.
- **Duplicates:** the first value of a repeated parameter wins.
- **Blank values:** a blank `q` (or one of spaces) is the start's empty
  search. Any other blank required parameter (`#example=`,
  `#concept=12&unit=`) is a link cut short, so the notice opens.
- **Optional parameters (R2, R3):** `step`, `state` and `practice` are tolerated: an
  invalid or blank value is left out and the rest of the link opens, at its
  canonical address. Unknown parameters (`utm_source=…`) are ignored.
- **Canonical address:** on opening, the address is rewritten to the
  screen's own link.

**Anything else** opens the start with "That link does not match anything in
this demo". That covers an unknown key or preset, a malformed or over-long
ID, an over-long query, `unit` without `concept`, and a link cut short. A
well-formed link to an ID this build lacks opens that screen's "not in this
demo" state with a working example and, since R2, "Search the library".

**Behaviour checked for every row:** direct open, reload, a move, Back
(focus on the control used), Forward, and Back out of the demo, at 390 and
1280 px (`docs/validation/FLH-153-routes-part3.md`).

## First visit, search evidence and a smaller bundle (demo refresh, 2026-11-18)

A fresh-browser walk of the packaged demo (390 and 1280 px) found these
points of friction, and the changes below address them. Evidence:
[validation](validation/demo-refresh-public-demo-20261118.md).

**Starting screen:**
- Each example card leads with the learner's question in French (`lang="fr"`,
  unchanged in every interface language), then says what the example shows.
  Before, the cards led with labels such as "One question, two pronouns", and
  the French appeared only in a summary.
- The lead is one sentence.
- `web/src/demo/examples.ts` holds each question verbatim.
  `GuidedExample.test.tsx` fails if it differs from the catalog's
  `original_input`. An opened example still reads everything from the
  server.

**The example shows that the Concept is now searchable.** Step 3 offers
"Search “pronouns”" (the example's own keyword query). It opens the results
as a new history entry, with the Concept listed and the matched words marked.

**Results say what matched.** In the demo, a keyword result names the matched
words next to where they matched, from the search's own `tokens` and
`matched_fields`:
- "Found in title: pronouns."
- For a match in a filed unit's wording: "Found in the explanation of a unit
  filed here, …, not in the Concept's title: viennes. Open the Concept …".

The result carries no unit text, so none is shown or guessed.

**The evidence screen names its Concept.** The way back and the "why this
record" line read "concept #12: the pronouns y and en". The title comes from
one allowlisted Concept read. While that read loads, or if it fails, the
labels show the number only, as before.

**Smaller changes:**
- **Empty curation:** the Concept screen leaves out "Best explanation" when
  no unit was chosen, like the other empty curation sections.
- **Bad links:** the notice for a link that matches nothing now also has
  "Open the example “One question, two pronouns”", which opens as a new
  entry.
- **Narrow phones:** at 480 px and below, an evidence row's label sits above
  its value. Before, at 320 px, the learner's context and the explanation
  wrapped two or three words to a line beside a 110 px label column. A
  Concept named inside a sentence stays inline.

The private workbench's Knowledge Library is unchanged by all of this: each
change is behind the demo mode.

**What a demo build contains** (`vite.config.ts`, demo builds only; the
workbench build is unchanged):
- **No workbench:** `main.tsx`'s import of the private workbench (`./App`)
  resolves to an empty component. The package therefore no longer contains
  or serves workbench code. Before, it served
  `/assets/MockExam-….js` and `/assets/ExperimentDashboard-….js`, and its
  script named private routes such as `POST /captures`.
- **Message catalogs:** they keep only the namespaces the demo's code
  references (`src/demo/catalogScope.ts`):
  `app common demo effective explanationLanguage explanationText inspector
  language library practice status`. That is 443 of 2,144 keys.
- **Guards:** `CatalogScope.test.ts` walks the demo's import graph and fails
  when the list misses a namespace the graph uses, or names one it no longer
  uses. It also fails if the pruner meets a catalog format it does not
  understand.
- **Effect**, on packaged builds with the same artifact:

  | Measure | Kind | Before (`d1118-base`) | After (`d1118-final`) |
  |---|---|---|---|
  | Entry script | asset size (decoded) | 547,523 bytes | 287,580 bytes |
  | Entry script | transferred (gzip, with headers) | 150,131 bytes | 85,647 bytes |
  | Start: page, script, style and both reads | transferred | 172,696 bytes | 108,298 bytes |
  | Start rendered (placeholder replaced) | browser timing | 1.19 s | 0.88 s |
  | First example card on screen | browser timing | 1.60 s | 1.60 s (no measurable change) |

  **Bytes:** Chromium's encoded lengths, body plus headers. Counting with a
  plain HTTP client gives the same within 0.1 %.

  **Times:** each figure is the median of 9 cold runs per build, alternating
  between the builds run by run (2026-11-19). The profile is Chromium 156
  with 390 px phone emulation, 150 ms round trip, 1.6 Mbit/s down and
  750 kbit/s up, a 4× CPU slowdown, and a new browser context (empty cache)
  per run.

  The measurement record, including an earlier 5-run series, is
  [validation/demo-performance-evidence-20261119.md](validation/demo-performance-evidence-20261119.md).

**Packaged gate fixes:**
- **Vectors kind:** `check_package.sh` now passes the vectors kind to
  `accept_guided.mjs`, as its README already said. Before, a CANDIDATE
  package failed the guided suite because it expected the mechanical notice.
- **Package identity:** its live stage now also checks the page actually
  served against `RELEASE.json` `web`: build id, entry script and
  `index.html` SHA-256. The artifact alone does not name a package, because
  packages built from different trees can share one artifact.

## Step-by-step walkthrough (2026-11-19)

Each guided example offers "Walk through it step by step". The whole example
stays on the page. The walkthrough then names the current step ("Step 2 of
4: the rules taken from it"), marks it (`aria-current="step"`), focuses its
heading, and keeps Previous and Next inside that step, so the way on is where
the visitor is reading, also on a phone.

- **Links and history:** each step is its own history entry and link
  (`#example=y-en&step=2`). Back and Forward therefore retrace the steps; a
  shared link opens at its step. The way back from the example's Concept or
  evidence returns to the step the visitor left.
- **What changed:** from step 2, the learner's question marks its words that
  reappear in the extracted rules' wording, and step 2 lists them beside the
  rules. Words compare without case or accents. A rule word of five letters
  or more also marks a longer form ("remplace" marks "remplacent"); shorter
  words must match whole, so "de" never marks "demain".
- **Data:** nothing is fetched beyond the example's existing reads, and
  nothing is recorded.
- **Checks:** `web/src/demo/WalkthroughSteps.test.tsx`. In a real browser, a
  scripted fresh visit reaches the source in 6 clicks and about 1.4 s, in
  English and 简体中文, at 390 and 1280 px. That is a lower bound for a
  person, not a user study.

## Why a result matched, and comparing two examples (2026-11-19)

**Why it matched.** Each keyword result offers "Show why it matched"
(`web/src/demo/EvidenceCard.tsx`). The card explains the match from the
result's own metadata and reads only the existing GETs, on request:
- **Tier:** whether every searched word is in the Concept's own wording
  (`match_tier: identity`) or some only in the wording of units filed under
  it (`unit_evidence`).
- **Each word:** "“remplace” is the whole word remplace", or "“rempl” is the
  beginning of remplace". The search ignores case and accents and matches the
  beginning of words; the page applies that same rule to the text it shows.
  A word the server matched but the page cannot find in that text is said so,
  never guessed.
- **Wording, grouped:** the Concept's matched fields; then, per unit, its
  matched fields (long wording shortened around the match, with "Show the
  whole wording"), the learner's question it was taken from, what it
  supports, and a link to its source record (`#q=…&concept=…&unit=…`). Three
  units first, the rest on request.
- **What it supports:** "Concept #12, “the pronouns y and en”: this unit
  currently supports it", or that the unit is filed there without supporting
  it. This comes from the Concept read's supporting units. A first-visit
  rehearsal (2026-11-19) showed visitors otherwise had to open the Concept
  screen to answer what the evidence supports.
- **Keyboard:** a native toggle (`aria-expanded`, `aria-controls`); Escape
  inside the card closes it and returns focus to the toggle. Back from a
  source returns to the open card with focus on the link that was used.
- **No match details:** a result without `matched_fields` or `tokens` (an
  older server) says that this page cannot tell which wording matched, and
  fetches nothing.

**Comparing two examples.** (R2 replaced the stacked layout described here
on every width; see "Phone comparison, practice and first-visit paths"
below.) The start page offers two comparisons after the
guided examples (`web/src/demo/comparisons.ts`, `CompareScreen.tsx`):
"Imparfait or passé composé?" and "Depuis or pendant?". Each side is found
like a guided example: one keyword query plus wording from exactly one unit,
then the unit's Concept and source. Nothing is written and no account is
involved.
- **Layout:** each card has the same headed rows: the learner's question,
  the stored interpretation of that question, the rule taken from it, its
  example, and the Concept it is filed under, with links to the source record
  and the Concept. From 721 px wide the rows line up across both cards
  (CSS subgrid); narrower screens stack the cards.
- **Address:** `#compare=<key>`, kept on reload. A Concept or source opened
  from it carries `compare=<key>`, so its back action returns to the
  comparison.
- **Incomplete data:** a side this build lacks says so and offers its
  keyword search; a unit whose source cannot be read is shown without its
  question, and the other side is unaffected.

**For a reviewer, in about a minute:** open `/`, choose "Imparfait or passé
composé?", and read the two examples row by row ("Quand j'étais petit, je
jouais au foot." against "Hier, j'ai joué au foot."). Then follow "Open
source record #5" to the learner's original question and use Back, which
returns to the comparison with focus on that link.

**Checks:** `web/src/demo/EvidenceExplorer.test.tsx` and
`web/src/demo/Compare.test.tsx`. On a package, a real-browser probe drives
both by keyboard in English and 简体中文 at 390 and 1280 px, with no write
request.

## Example data and suggested searches (2026-11-19)

**One data file.** `web/src/demo/discovery.json` holds the data of the
guided examples, the comparisons and the suggested searches. Application
text (titles, labels) stays in `web/src/i18n`.

**Suggested searches.** Under the search form, collapsed by default, each
shows one search behaviour: unit wording only, identity details, every word
must match, accents ignored, word beginnings, and one search that finds
nothing (`pronoms`). That one is followed by its own way on: "Search
“pronouns”" and "Open the example “One question, two pronouns”".

**Checked against the package.** The package gate's `examples` stage
(`scripts/validation/demo_candidate/check_examples.py`) resolves every entry
against the served artifact, the way the page does. It writes a support
matrix and fails with one readable line for each stale entry. Evidence:
`docs/validation/demo-discovery-20261119.md`.

**Updating example data:**
1. Edit `discovery.json`.
2. Run `python3 -I scripts/validation/demo_candidate/check_examples.py
   http://127.0.0.1:<port> web/src/demo/discovery.json <out>` against a
   running package.
3. Rebuild the package. A data-only change alters only the web bundle; the
   server binary and the artifact stay the same.

A new example or comparison also needs its title in both catalogs.

**Search recovery (2026-11-19).** Evidence:
`docs/validation/demo-state-identity-20261119.md`.
- **Overtaken searches:** only the newest is shown; its count names the
  query the server executed.
- **Failures:** a failed search keeps the last one that worked below the
  error, and its retry names the search it runs.
- **Refused searches:** a search the server refuses (more than 8 words, more
  than 200 bytes, no word of two letters) names the limit and offers "Edit
  the search".
- **Binding the package:** `package.sh` prints the `SHA256SUMS` digest.
  `check_package.sh --expect-sums <digest>` then refuses any package file
  that differs from the one built, such as another server binary.

**Browser behaviour (2026-11-19).** Evidence:
`docs/validation/demo-browser-ux-20261119.md`.
- **Link names:** each source link names its unit ("Open the source of unit
  #12 (record #9)"), so two units of one record never share a link name.
- **Expired page:** the startup placeholder in `web/index.html` says at once
  that the page is out of date when a file it names is gone from the server.
- **Measured:** the path from a query to evidence, and focus after closing,
  returning, reloading and switching language. Also 320 px with text-spacing
  overrides, a slow response, and reduced motion.

## Checking a served demo against its package (2026-11-19)

`scripts/validation/demo_candidate/check_served.py BASE_URL PKG_DIR` (GETs
only) checks that the page, its entry script and stylesheet bytes, and the
artifact identity served at an address are those of a package.
- **Staged smoke:** run it against the staging address with the package
  installed there.
- **After deploying:** run it against the public address (through the proxy)
  with the released package.
- **After a rollback:** run it with the package rolled back to.

**Tested locally:**
- a package against itself: 7/7;
- another package served: FAIL on build, entry and manifest;
- a stand-in proxy serving stale bytes under the right entry name: FAIL on
  the entry's bytes.

`check_package.sh --expect-sums <digest>` (digest printed by `package.sh`)
binds every file of the package, server binaries included.

**FLH-076 browser acceptance, changed contract.** A server 400 is now shown
naming the limit, with "Edit the search" and no retry, because running a
refused search again cannot succeed. `scripts/demo/flh076/browser/accept.mjs`
checks that. The FLH-076 and FLH-078 validation records describe the earlier
"error with retry" as it was then.

## Real-E5 candidate (owner only)

**Reusing a completed work directory (no embedding call).** If a work
directory for the current plan already exists, skip steps 2 and 3. Whether
one exists depends on two things: step 1's `plan_sha256` equals its
`plan.json`, and `prepare status -work DIR` reports every position
completed. In that case `import` (step 4) builds a new artifact for this
tree's migration ledger and sends nothing. Copy the work directory first,
read-only, and import from the copy. The 2026-11-18 rebuild used the
2026-11-12 work directory this way (23 of 23 receipts, plan `536021a4…`).

**The embedding step (2) is not performed by any agent.** It sends the 23 synthetic catalog texts (14
Concept documents and 9 preset queries) to the owner's E5 service. Nothing in
it uploads, deploys or changes DNS; deployment stays a separate owner
decision ([AWS_DEMO.md](AWS_DEMO.md)).

**Inputs:**

| Input | Value |
|---|---|
| Tree | the integrated commit you will release, checked out clean; `make verify` passes there |
| `REV` | that commit's label (12 characters is enough), for `RELEASE.json` |
| `E5` | your E5 service's `/v1` base URL (loopback or a private address; never a public one) |
| `DEP` | the pinned deployment id, unless you adopt a new one: `multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff` |
| `R` | a new directory outside the repository; it must not exist |
| Browser | Chromium or Chrome (`CHROME`), and a `node_modules` holding `playwright-core` 1.49.1 (`NM`) |

**Commands**, from the repository root:

```sh
mkdir "$R" && go build -o "$R/flh-prepare" ./scripts/demo/flh073/prepare
"$R/flh-prepare" plan                                   # 1
"$R/flh-prepare" embed -work "$R/e5-work" -base-url "$E5" -deployment "$DEP" -dimensions 768 -allow-live   # 2
"$R/flh-prepare" status -work "$R/e5-work"              # 3
"$R/flh-prepare" import -work "$R/e5-work" -out "$R/artifact-e5"                                            # 4
"$R/flh-prepare" validate -artifact "$R/artifact-e5" -release; echo "exit=$?"                              # 5
bash scripts/demo/flh076/package.sh --artifact "$R/artifact-e5" --revision "$REV" --label e5-rc1 \
  --out "$R/packages" --expected-deployment "$DEP"                                                         # 6
PKG="$R/packages/flh-public-demo-e5-rc1"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); a=d["artifact"]; print(d["release_status"], a["real_model"], a["version"], a["manifest_sha256"])' "$PKG/RELEASE.json"   # 7
CHROME=/path/to/chromium bash scripts/validation/demo_candidate/check_package.sh "$PKG" "$R/check" \
  --expect-status CANDIDATE --expect-version <version from 7> --expect-manifest <manifest from 7> \
  --node-modules "$NM" --suites all                                                                        # 8
CHROME=/path/to/chromium bash scripts/validation/demo_candidate/negative_controls.sh "$PKG" "$R/controls" \
  --node-modules "$NM"                                                                                     # 9
```

**Expected output and stop conditions:**

| Step | Expect | Stop if |
|---|---|---|
| 1 `plan` | `"positions": 23`, `"posts_at_batch": 3`, `"plan_sha256": "536021a4aaa5e2211b5c5a6d48263350ef10aa2021861ee9b6af0255b5412ada"`, `"fixtures_sha256": "d7b97b560e34ac6f453033fbeb78e65e16a8f0c84501f1e29ba41fe167ee2ab9"` (catalog of 2026-11-12) | any value differs: the catalog changed, so review that change first |
| 2 `embed` | readiness 200, `/manifest` reports exactly `DEP`; 3 POSTs, 23 receipts; at most 2 probes, 16 POSTs, 64 positions | it refuses (deployment mismatch: adopting a new id is a separate decision; budget short: exit 3, nothing sent); any POST fails (nothing is retried, the POST stays charged; rerunning the same command sends only positions without a receipt) |
| 3 `status` | 23 of 23 positions with valid receipts | fewer |
| 4 `import` | `$R/artifact-e5` created and validated | it refuses (plan differs, or a missing or invalid receipt) |
| 5 `validate -release` | `exit=0` | `exit=3` (mechanical) or `exit=1` (invalid) |
| 6 `package.sh` | `CANDIDATE package: …/flh-public-demo-e5-rc1`, with no `-BLOCKED` | the name ends in `-BLOCKED`, or it refuses the model id or `--expected-deployment` |
| 7 `RELEASE.json` | `CANDIDATE True <version> <manifest>`; record these, the live check after any installation compares against them | anything else |
| 8 `check_package.sh` | `PACKAGE CHECK PASSED (CANDIDATE package)`, exit 0; `summary.json` stages all `PASS` | any stage `FAIL` or `NOT RUN` |
| 9 `negative_controls.sh` | the identity and write controls `DETECTED`, exit 0 (the link control is `NOT RUN` without a pre-fix package) | any `MISSED` |

**Then, by eye:** open the 9 preset results in `$R/check/browser/` (the
matrix and FLH-076 screenshots) and judge their relevance yourself. Mechanical
vectors proved only the mechanics. A passing CANDIDATE is ready for the
separate deployment decision; it is not deployed by any of this.

## Phone comparison, practice and first-visit paths (R2, 2026-11-19)

**For visitors.** The demo follows French learners' questions to the rules
taken from them and the evidence behind each rule. Start with a guided
example, compare two easily confused forms, try one as a question before
reading the answer, or search the whole synthetic library with your own
words. Everything is read-only: nothing you choose is saved or sent.

**First screen.** One row of ways in under the introduction: the 60-second
tour, Examples, Comparisons and Search the library (each moves focus within
the page). The search section says how searching differs from the prepared
paths. The first example is the most beginner-friendly question
(`en-train-de`); a fourth example (`imparfait`, a question written in
English, `lang="en"`) holds the two units of the imparfait comparison, and
the example and the comparison link to each other.

**The 60-second tour** (`web/src/demo/Landing.tsx`): the imparfait example's
question, its comparison, then the source of its first unit. Each step is the
ordinary screen and history entry; the tour bar says where the visitor is and
offers the next step. "Leave the tour and stay here" keeps the screen. The tour
lives in page memory: a reload or a shared link has none.

**The comparison** (`CompareScreen.tsx`):
- **The pair:** each side's unit wording (as its label) and its example
  sentence, compact, so both sentences are read together: 106 px apart on a
  320 × 640 phone (714 px in English and 672 px in Chinese before), in one
  view at 320, 768 and 1280 px, at 200 % zoom, with a 24 px default font and
  with a 200-character French sentence.
- **The evidence:** the learner's question, the stored interpretation, the
  rule and the Concept, behind one "Show the evidence" button
  (`aria-expanded`), open on wide screens and closed on phones. Opening it
  changes neither the address nor the history. Escape closes it and returns
  focus to the button; coming back from a source opened there reopens it with
  focus on that link.
- **Copy a link to this comparison:** `#compare=<key>` only.

**Practice (optional)** for `imparfait-passe-compose`
(`discovery.json` `practice`; `comparisons.ts`):
- From the start page ("Try … as a question first") or the comparison's
  "Try a question". The pair is hidden while a question is unanswered.
- The learner's question and its recorded context come first, then the
  example with its form blanked, then both forms in side order and an
  explicit skip. A form must occur exactly once in its side's example, or
  the item is not offered (`DiscoverySpec.test.ts`, `check_examples.py`).
- After a choice or a skip: the outcome (in a status region, and focused),
  each form's rule with a link to its unit's evidence, and the valid
  alternative with its other meaning. Then "Try the other example".
- **State:** the answers, the item and whether the evidence is open live in
  page memory for the visit (`web/src/demo/visit.ts`): never in the address,
  browser storage, a cookie or a request. Back from a source finds the
  practice as it was; a reload or shared link starts at the pair. No score
  and no record. (Since R3 the question shown is part of the link,
  `&practice=<n>`; answers still are not. See the R3 section.)

**Why it matched** (`EvidenceCard.tsx`): each matched unit carries a label,
"Supports" or "Filed, not supporting", then the sentence. A filed unit
that does not support says why, from its own fields: from an earlier,
replaced extraction (`in_current_extraction: false`), or an admission other
than active. A missing source record reads "No excerpt…" (not a failed
read); a question without the search words says so. "Show the question's
context" shows the recorded context and stored interpretation in place, with
no request. "Copy a link to the source of unit #N" copies
`#concept=<id>&unit=<id>`.

**Accessibility and layout:**
- **Font size:** text follows the browser's font-size setting. Every px size
  of the shared `styles.css` that reaches a demo element is restated in rem
  under `.demo-app`, and `demo.css` sizes nothing in px. At a 24 px default
  font, 0 text elements keep their size, against 580 before
  (`demoStyles.test.ts`).
- **Highlights:** underlined as well as coloured, in dark text (4.6:1 is the
  lowest text contrast on every screen, both languages).
- **Targets:** every control at least 24 × 24 CSS px at 320 px (a link
  inside a sentence excepted).
- **Status:** a search's progress and outcome are announced by one status
  region that is on the page before the search; the visible result lines are
  plain text.
- **Motion:** no transitions or animations.

**Links (R2-084/085):** shared links name a screen, never progress. `step`
and `state` are optional parameters: a bad value is left out (see
"Supported addresses"). A link to a Concept or unit this build lacks offers
the first example and "Search the library".

**What a first visit requests** (R2-059), all same-origin GETs:
1. `GET /`
2. `GET /assets/index-<hash>.js`
3. `GET /assets/index-<hash>.css`
4. `GET /api/knowledge-library/demo`
5. `GET /api/knowledge-library/concepts?q=&state=all`

Nothing else: no fonts, images, other origins, cookies or storage. Each
screen then reads only the knowledge library's GETs (search, Concept, unit
source).

**Package (R2-054, 064–066, 070, 078):**
- **Build assertion:** `package.sh` refuses a web build that fails
  `scripts/validation/demo_candidate/check_bundle.py`. It checks for:
  only `index.html` and assets; one entry script; no workbench-named chunk; no
  private route, content pack, fixture, workbench storage key, local path or
  tailnet value. Private recall practice is compiled out of demo builds.
- **Practice not split:** it costs 1,115 gzip bytes of the entry script
  (1.1 %). A lazily loaded prototype saved 192 bytes, so the package stays a
  single script. On that prototype, a failed chunk showed a retry in place
  that worked without a reload.
- **Pinned manifest:** `check_package.sh --pinned-manifest FILE` checks
  every file against a copy of `SHA256SUMS` kept outside the package and
  names any file that differs.

**Staged HTTPS (R2-077, owner only; nothing here changes DNS or a host):**
- **Host tool:** the staging host serves the package through
  `deploy/aws/host/flh-public-https` (FLH-088; `docs/AWS_DEMO.md`). It runs
  nginx with a Let's Encrypt certificate (`enable HOST --staging` for the
  untrusted dry run), allows only GET and HEAD, and adds HOST to
  `HTTP_ALLOWED_HOSTS`.
- **Owner needs:**
  - a DNS name pointing at the instance's address;
  - inbound TCP 80 and 443;
  - `flh-public-https preflight HOST` passing;
  - the release installed with `flh-release install` and the tarball
    SHA-256.
- **Then check:** `check_served.py https://HOST <package>` must report 7/7.
  `flh-release`'s own identity check binds the artifact only, and two
  releases can share one artifact, so this page check is required.
- **Offline render:** `flh-public-https render DIR HOST CERT` writes the
  nginx files for review without root.

**Owner runbook: the local candidate (R2-088), tested on `d1119-r2`:**

```sh
PKG=/abs/flh-public-demo-d1119-r2; RUN=/abs/runtime-dir
(cd $PKG && ./validate-release.sh)                       # exit 0 = CANDIDATE
PORT=18773 bash $PKG/deploy/ctl.sh start $RUN            # "started (pid …, 127.0.0.1:18773)"
PORT=18773 bash $PKG/deploy/ctl.sh status $RUN
python3 -I scripts/validation/demo_candidate/check_served.py http://127.0.0.1:18773 $PKG   # 7/7
curl -s http://127.0.0.1:18773/ | grep -o 'flh-build" content="[^"]*'     # the package's build_id
PORT=18773 bash $PKG/deploy/ctl.sh stop $RUN             # "stopped"; nothing left listening
```

## A beginner's contrast and links to a question (R3, 2026-11-20)

**For visitors.** New under the first example: "Common mix-up: is « je suis
cuisinant » French? Answer one question". It opens a short question about
saying what is happening now. Choose a form, or ask for a hint first; then see
why each form works or not, with the learner's record it comes from.

**The contrast `present-en-train-de`** (`discovery.json`, `comparisons.ts`):
- **Source:** both units come from the first guided example's record
  (`e-en-train-de` in the synthetic catalog): "présent pour une action en
  cours" (*Je ne peux pas répondre, je cuisine.*) and "être en train de +
  infinitif" (*Je suis en train de cuisiner.*).
- **Links:** the example and the comparison link to each other (the example's
  `compare`).
- **The way in** (`ExampleScreen.tsx`, `CONFUSION` in `comparisons.ts`): it is
  built from the first distractor of the first comparison that has one, and
  sits under the card of the example that comparison comes from (the first),
  as a comparison's practice entry sits under its card.
  - **Placement:** the row of ways in and the first card are where they were
    (first card at 504 px in English and 414 px in 简体中文 on a 320 × 640 phone).
    The entry starts at 656 px (just below the first view) or 565 px (inside it).
  - **Steps:** the path to the answer (path P6) takes 2 steps at 1280 px and in
    简体中文 at 320 px, and 3 steps in English at 320 px (2 taps, 1 swipe). While a
    question is shown the comparison's summary is left out, so on a phone its
    choices come one swipe sooner (it was 4 steps).

**The pair, since R3** (`CompareScreen.tsx`):
- **Evidence link:** under each example, "Where this example comes from:
  unit #N, record #M", the exact unit's source (`#compare=…&concept=…&unit=…`).
- **The learner's question:** "Show the learner's question" (`aria-expanded`)
  opens a panel under the pair with the recorded question and context, once
  per record. It is page memory only, like the evidence, and nothing above it
  moves when it opens.

**Practice, since R3:**
- **Hint:** a hint on request before the answer, under the choices so they
  stay where they were (application text, `COMPARISON_TEXT[…].hints`). `DiscoverySpec.test.ts` checks that no hint
  names an offered form, in either language.
- **Distractor:** a comparison may name `distractors` (here *je suis
  cuisinant*). It is offered first, then the two sides' forms. After a
  choice, its reason is the stored interpretation of the item's record,
  quoted with its evidence link; the page adds only "not a French form".
  Each side's form keeps its rule and evidence link, also a side without a
  question of its own.
  `DiscoverySpec.test.ts` (catalog) and `check_examples.py` (served package)
  require that interpretation to name the distractor.
- **Valid alternative:** each item may carry one; here *je suis en train de
  cuisiner* is also correct and stresses that the action is in progress.
- **Where to continue:** after an answer, the next comparison's question and
  "Search the library". The guided example stays in the comparison's own
  navigation below.
- **Links:** `#compare=<key>&practice=<n>` opens question `n`, unanswered. Its
  "Copy a link to this question" copies exactly that; the answer is never in
  a link.
  - **History:** entering a question is a history entry; moving to another
    question rewrites it. A Concept or source opened from a question carries
    `&practice=<n>`, so Back returns to it. Back and Forward between the pair
    and its question keep this visit's answer.
  - **Focus:** a newly opened screen focuses its title; moving between the
    pair and a question focuses the control that left it, else the heading.

**Cost in steps:** the imparfait question from its comparison card (path P3)
takes one more swipe at 1280 px and in English at 320 px, because the new
comparison is listed first. Other paths are unchanged (`paths_probe`, R3 lane
evidence).

**Removing the contrast** (R3-050), with no other change:
1. In `web/src/demo/discovery.json`, delete the `present-en-train-de`
   comparison and the `"compare": "present-en-train-de"` of the `en-train-de`
   example.
2. In `web/src/demo/comparisons.ts`, delete its `COMPARISON_TEXT` entry.
3. Delete these keys from both `web/src/i18n/en.ts` and `zh-CN.ts`:
   `demo.compare.enTrainDe.{title,summary}`,
   `demo.practice.enTrainDe.{alternate,hint}.1`.
4. In tests: update the comparison list in `DiscoverySpec.test.ts` and delete
   the "beginner's contrast" block of `Compare.test.tsx`.
5. `check_examples.py` then checks 12 entries instead of 13.

The way in under the first example disappears when no comparison has a distractor. The
link parameter and the practice features stay for the imparfait comparison.

## A clearer learning path (R4, 2026-11-20)

**For visitors:**
- The 60-second tour now starts with the first French question, « je suis cuisinant », then its
  comparison and the record its first rule came from.
- Every link to evidence says where it leads.
- A rule that the learner's question does not contain says that it comes from the stored
  interpretation.
- The wrong option in the « je suis cuisinant » question is set against the rule that is
  supported.

**Changes:**
- **Tour** (`KnowledgeLibrary.tsx`, `TOUR`): `en-train-de` → `present-en-train-de` → the source
  of its first unit. It was the imparfait example, whose question is written in English. This
  supersedes the R2 description above.
- **Names of evidence controls:**
  - "See where unit #N came from" was "See where this unit came from";
  - "Open the Concept “…” and its evidence" was the same text for every Concept.
  - So no two controls with one name lead to different places.
- **The source screen's quotation:** it carries `lang` when the question is one of the
  authored examples, which name their language. For any other question no language is claimed.
- **A rule not in the question** (`ExampleScreen.tsx`): under a rule none of whose words is in
  the question (`sharedWords`), one line says it comes from the stored interpretation.
- **The distractor's explanation:** it adds "Tempting: «form»" and "Supported rule (unit #N):
  wording: «form»", all from the data; it stacks below 600 px.
- **Focus after a quick Back:** a screen takes the return-focus id only when that control is its
  own. A screen being left could otherwise take it, and focus fell to the step heading.
- **Repeated-word marking:** letters with their combining marks form one word, so a question
  stored with decomposed accents is marked as whole words too.
- **Demo routes only:** a demo build tests `PUBLIC_DEMO_BUILD` first when choosing a search
  route, so the bundle names only `/knowledge-library/demo/…`. `check_bundle.py` refuses the
  workbench's `/knowledge-library/semantic-search` and `/hybrid-search`.

**Unchanged:** the data contract, the routes, the artifact, the bundle's scripts (one),
storage (none), and the request set (same-origin GETs of the read routes).


## The first-visit journey and the feature gallery (R5, 2026-11-20)

**For visitors:** the **Guided tour** button walks one French learner's question through FLH in five
steps:
1. the question;
2. how it was analysed, and how a person's correction is recorded;
3. the rule taken from it, with its source record;
4. the Concept search;
5. a retry of the mistake.

Below the comparisons, a compact gallery lists the private workbench's other features and says why
the public demo does not run them.

**Fixture replays.** Two steps show what the private workbench does with the learner's own
records. They are replays, each labelled as one where it is shown:
- **Step 2:** a correction of the stored analysis. The section is tagged "Fixture replay" with a
  dashed border, and says it is not from the server and not stored. The fixture is
  `web/src/demo/journeyFixtures.ts`; `Journey.test.tsx` checks that it corrects the catalog's
  analysis, verbatim.
- **Step 5:** the step's hint says it is a fixture replay of a Mistake Notebook retry. The
  question itself is the public comparison question.

Everything else in the journey is read from the demo's server.

**Routes:**

| Step | Route | Screen |
|---|---|---|
| 1 | `#example=en-train-de` | the guided example |
| 2 | `#analysis=en-train-de` (new; it must stand alone, or the link is malformed) | `AnalysisScreen.tsx` |
| 3 | `#example=en-train-de&concept=14&unit=16` | the source of the example's seed unit |
| 4 | `#q=action+en+cours` | the keyword search for the example's own query |
| 5 | `#compare=present-en-train-de&practice=1` (after step 4: `#q=action+en+cours&compare=…&practice=1`) | the comparison's question |

The tour remains page memory: a reload or a shared link opens the screen without the bar.

**Coverage of FLH's major features:**

| Feature | In the demo | Where | Data |
|---|---|---|---|
| Learning entry (question and context, never rewritten) | yes | step 1; every source screen | public synthetic |
| Versioned analysis (category, explanation, confidence, provenance) | yes | step 2, `#analysis=en-train-de` | public synthetic |
| Human feedback and corrections; the effective interpretation | replay | step 2, the "Fixture replay" section | fixture (`journeyFixtures.ts`) |
| Bilingual explanations (FLH-095) | yes | step 2: the stored analysis is labelled "language not recorded"; the replay shows English and Chinese variants | public synthetic and fixture |
| Knowledge extraction (units) and admission | yes | step 3; `#example=…&step=2` | public synthetic |
| Source evidence (record, extraction, interpretation) | yes | step 3 | public synthetic |
| Concepts: support, membership, the orphaned state | yes | step 4 → a Concept; `#concept=11` (orphaned) | public synthetic |
| Knowledge Library keyword search | yes | step 4, `#q=action+en+cours` | public synthetic |
| Semantic and hybrid search | yes (presets only) | gallery → `#mode=semantic&preset=right-now` | precomputed vectors |
| Mistake Notebook retry | replay | step 5 | public question, framed as a replay; retry marks and history are private |
| Comparisons and choose-first practice | yes | start page → Comparisons; `#compare=…&practice=N` | public synthetic |
| Guided walkthrough | yes | `#example=<key>&step=1…4` | public synthetic |
| Review Today (daily review) | gallery | "Mistake Notebook and Review Today" | private only |
| Capture import and CLI | gallery | "Capture a discussion" | private only (writes records) |
| Concept review, relations, AI suggestions | gallery | "Concept review and AI suggestions" (links to a Concept's read view) | private only (writes decisions; AI provider) |
| Recall practice | gallery | "Recall practice" | private only (compiled out of the demo) |
| Listening lessons and daily pull | gallery | "Listening lessons" | private only (AI provider, the learner's transcripts) |
| Reading lessons and mock exams | gallery | "Reading and mock exams" | private only (saves answers) |
| Writing feedback | gallery | "Writing feedback" | private only (AI provider, saves drafts) |
| Speaking practice | gallery | "Speaking practice" | private only (audio and AI providers) |
| Retrieval experiments, annotation inspector, dataset reports | gallery | "Retrieval experiments" | private only (private annotations) |

**Why the private features are omitted:** each of them writes records, needs the learner's own
data, or calls an AI provider. The public boundary serves only GET and HEAD of the knowledge
library's read routes, so they cannot run here, and the demo never imitates them with server
writes. The gallery's cards are text only: no fixture, no request, and a control only where it
leads to a public screen.

**Tests and checks touched:** the boundary tests in `PublicDemoApp.test.tsx` and
`Listening.test.tsx` now exclude the gallery's descriptive text. They still require that no
private control or route appears, and that the Listening card has no control.


## Publication checklist, keyed to one candidate (R4)

Use this list for every public demo candidate. Put the candidate's own values into the variables;
the R4 handoff fills them for its candidate.

```sh
TAR=/abs/flh-public-demo-<label>.tar.gz
TAR_SHA256=<tarball SHA-256 from package.sh>
SUMS_SHA256=<SHA256SUMS digest from package.sh>
VERSION=<artifact version>; MANIFEST=<public artifact manifest SHA-256>
PIN=/abs/pinned-SHA256SUMS            # the copy kept outside the package when it was built
HOSTFILE=/abs/private-host.txt        # the owner's private host value, compared, never printed
```

1. **The exact archive:**
   - `sha256sum "$TAR"` must print `$TAR_SHA256`;
   - extract it into a new, empty directory; `PKG` is the extracted directory.
2. **Identity:**
   - `(cd "$PKG" && ./validate-release.sh)`: exit 0 is CANDIDATE, exit 3 is BLOCKED, which is
     never public;
   - `RELEASE.json` names `$VERSION` and `$MANIFEST`.
3. **Public fields only:** `python3 -I scripts/demo/flh076/public_provenance.py check "$PKG"`
   must print `PUBLIC FIELDS CHECK PASSED`. A failure names the field path, never its value.
4. **The bundle:**
   `python3 -I scripts/validation/demo_candidate/check_bundle.py "$PKG/web" --private-host-file "$HOSTFILE"`
   must print `BUNDLE CHECK PASSED`. This also refuses private routes, including the
   workbench's own semantic and hybrid search.
5. **The gate:**
   `bash scripts/validation/demo_candidate/check_package.sh "$PKG" /abs/new/work --expect-version "$VERSION" --expect-manifest "$MANIFEST" --expect-status CANDIDATE --expect-sums "$SUMS_SHA256" --pinned-manifest "$PIN" --suites all`,
   with `CHROME` and `--node-modules` for the browser stage. Every stage must PASS. A browser
   stage reported NOT RUN is a skipped check, not a pass.
6. **Served identity, after the host serves it:**
   `python3 -I scripts/validation/demo_candidate/check_served.py <base URL> "$PKG"` must report 7/7.
   Run it again after any rollout or rollback.
7. **Rollback target:** a package that passed steps 1–5 itself. Never a package that fails
   step 3: such a package carries private provenance.
8. **Owner decisions:** the stage, DNS and publication (`docs/AWS_DEMO.md`). This checklist
   performs none of them.

## Limits

- **Synthetic data:** 11 questions (3 written in French), 16 units and 14
  Concepts, one of them deliberately orphaned.
- **Presets:** 9 example queries.
- **Keyword search:** prefix matching with AND semantics. Many natural-language
  example queries therefore match nothing by keyword, which the hybrid
  evidence shows.
- **Proven:** route filtering, read-only behaviour and ranking mechanics, by
  local tests and a loopback smoke only. **Not claimed:** relevance, security
  audit or public hosting.
