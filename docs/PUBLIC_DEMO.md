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
| `/#compare=<key>` | a comparison of two units (`imparfait-passe-compose`, `depuis-pendant`) |
| `/#concept=<id>` | a Concept |
| `/#concept=<id>&unit=<id>` | a unit's source evidence, reached from that Concept |
| any search before a Concept or evidence (`/#q=il+faut&concept=1`) | the same screen; its back action returns to that search |
| `example=<key>` before a Concept or evidence (`/#example=y-en&concept=12&unit=12`) | the same screen; its back actions return to that example |
| `compare=<key>` before a Concept or evidence (`/#compare=depuis-pendant&concept=8&unit=9`) | the same screen; its back actions return to that comparison. `compare` with `example`, or an unknown key, is malformed |

**Rules:**
- **IDs:** 1–9 digits, no leading zero.
- **Queries:** at most 200 characters. Percent-encoded and raw Unicode are the
  same query.
- **Duplicates:** the first value of a repeated parameter wins.
- **Blank values:** a blank `q` (or one of spaces) is the start's empty
  search. Any other blank required parameter (`#example=`,
  `#concept=12&unit=`) is a link cut short, so the notice opens.
- **Optional parameters (R2):** `step` and `state` are tolerated: an
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
  and no record.

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
