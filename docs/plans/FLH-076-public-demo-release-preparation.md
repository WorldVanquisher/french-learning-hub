# FLH-076 Public demo release preparation

Owner: local Claude Code (sole implementation owner). Branch label supplied:
`feat/flh-076-public-demo-release-preparation`. No Git/GitHub command or
subagent was used. Evidence:
[validation](../validation/FLH-076-public-demo-release-preparation.md).

**Builds on:**
- FLH-073 (demo mode);
- FLH-074 (independent acceptance; its harness is reused unchanged);
- FLH-075 (`os.Root` static confinement, fingerprint v2).

**Not authorized:**
- publication, DNS changes, or installing/enabling services;
- AWS/Titan calls, model downloads, or Windows changes;
- edits to existing harnesses or reports, migrations, normal-mode search, or
  `AGENTS.md`.

## 1. Real-vector artifact pipeline (`internal/publicdemo`, `prepare`)

**Plan** (`prepare plan`): one position per Concept document and per preset,
in a fixed order, derived from the same fixtures through the same seeding as
`build`.

| Position | Text | Representation | E5 role |
| --- | --- | --- | --- |
| `concept:<id>` | `BuildSemanticIndexDocument(c).Text` | `concept_embedding_text_v1` (`type: concept`) | `passage` |
| `preset:<id>` | `ConceptSearchQueryEmbeddingText(text)` | `concept_search_query_v2` (`type: query`) | `query` |

Each position records `text_sha256`. The plan's SHA-256 binds them all. The
catalog has 12 documents and 8 presets, so 20 positions.

**Embed** (`prepare embed -work DIR -base-url URL -deployment ID -dimensions N
-allow-live`):
1. Creates the work directory, or resumes it.
2. **Probe:** one readiness probe per run: `GET /readyz` (must be 200) and
   `GET /manifest` (its `deployment_id` must equal `-deployment`). It is
   counted in a persistent ledger, capped at 2 per work directory.
3. **Budget check before sending anything:**
   - pending = plan positions with no receipt;
   - required POSTs = ceil(pending / batch), with batch ≤ 8;
   - refused with nothing sent if the used plus required amounts would exceed
     `-max-positions` (≤ 64) or `-max-posts` (≤ 16).
4. **Each POST** is reserved in the ledger before it is sent. It uses the
   production `embedding.HTTPProvider` (`POST /embeddings`, `{"model": ID,
   "input": [...]}`).
5. **Each returned vector is checked:** exactly N dimensions, finite, and an L2
   norm within 1e-3 of 1. It is then written to `receipts.json`, with its
   text, deployment, dimensions, vector SHA-256 and POST sequence number.
6. **On failure:** stop. There is no retry, and the reserved POST stays
   charged.
7. **On resume:** completed receipts are never resent. A position counts as
   complete only when its text, deployment and dimensions match. Only
   positions with no receipt are sent.

**Import** (`prepare import -work DIR -out NEW_DIR`):
1. Re-derives the plan from the fixtures and requires it to equal the work
   directory's plan.
2. Requires exactly one receipt per position: no missing, extra or mismatched
   receipt, and the same deployment and dimensions.
3. Builds the artifact in a temporary sibling directory, with
   `vectors.json` `source: "model"`, `real_model: true`, and
   `generator: flh076_e5_http_v1`. It adds **`provenance.json`** (schema
   `flh076_vector_provenance_v1`): the plan hash, the deployment, the reported
   manifest hash, the readiness evidence, the per-position text/vector hashes,
   and the POST and accounting record.
4. Validates the result with the server's loader, then renames it to
   `NEW_DIR`. `NEW_DIR` must not exist, so old artifacts are untouched.

**Loader rules** (`LoadArtifact`):
- **Mechanical artifacts:** exactly the three FLH-073 files and no
  provenance.
- **Model artifacts:** they *must* carry `provenance.json`, and it must match
  everything:
  - each document's `text_sha256` equals the document content hash recomputed
    from the database;
  - each preset's equals its envelope hash;
  - every `vector_sha256` matches `vectors.json`;
  - the deployment and dimensions equal the vector identity.
- **Relabelling a mechanical artifact as `model` is refused** (no provenance,
  or provenance that does not match).
- **Trust boundary:** this binds vectors to what the preparation recorded. It
  is not a cryptographic proof of what produced them. Someone able to rewrite
  every file could fabricate consistent receipts.

## 2. Bounded real E5 preparation

- **Budget:** at most two readiness probes in total for this task, then at
  most 64 positions and 16 POSTs, to the existing E5 service only.
- **This run:** one probe was used, to `100.118.109.6:8765/readyz`. It timed
  out, and Tailscale showed the Windows host offline, so **real artifact
  generation is BLOCKED**. The pipeline is completed and tested against a
  deterministic in-process fake E5 instead.
- **Continuation:** a single command, recorded in the validation report and
  in PUBLIC_DEMO.md.

## 3. Actual browser acceptance (`scripts/demo/flh076/browser/`)

- **Tooling:** `playwright-core`, installed in a task-local directory under
  `/tmp` (no browser download). It drives the installed Google Chrome,
  headless, with a temporary profile.
- **What it exercises** on the demo build, against a running demo server:
  - presets, and the keyword, semantic and hybrid modes;
  - result evidence, Concept detail, source, and back navigation;
  - empty and error behaviour;
  - the synthetic, mechanical and model notices;
  - the absence of editing controls.
- **What it records:** console errors and every network request, which must
  be GET-only to allowlisted paths. It also takes screenshots.
- **Mechanical mode** proves UI mechanics only.

## 4. Portable release package (`scripts/demo/flh076/package.sh`)

**Layout** (`flh-public-demo-<label>[-BLOCKED]/`):

| Path | Contents |
| --- | --- |
| `bin/linux-amd64/`, `bin/linux-arm64/` | `flh-server` and `flh-prepare` |
| `artifact/` | The validated artifact |
| `web/` | The demo build |
| `deploy/` | systemd and nginx examples, plus `ctl.sh` (start, status, stop) |
| `RELEASE.json` | Label, the human-supplied source revision, Go version, artifact identity and provenance summary, release status |
| `SHA256SUMS` | Checksums of every other file |
| `README.md` | Instructions |

**Refused:**
- symlinks, unexpected files, `.env`, or databases other than the artifact's;
- an artifact that fails validation.

**Mechanical artifacts** produce only a package named `…-BLOCKED`, with
`release_status: BLOCKED`. Its `validate-release.sh` exits non-zero.

**`validate-release.sh`** (inside the package) checks:
- `SHA256SUMS`;
- that there are no symlinks;
- `flh-prepare validate -release`.

**Runtime needs:** Linux and the files above. No encoder, Windows, Qdrant or
cloud credentials.

## 5. Deployment handoff (examples only; nothing installed)

- **systemd unit:**
  - a dedicated user, `ProtectSystem=strict`, read-only paths and no writable
    state;
  - a loopback listener, an explicit environment, and
    `HTTP_ALLOWED_HOSTS=<host>`.
- **nginx server block:** TLS, GET/HEAD only, `client_max_body_size 0`
  (bodies refused), timeouts, rate limits, and Host pinning.
- **Final operator inputs and steps** are listed in PUBLIC_DEMO.md.

## Files

- **Changed:**
  - `internal/publicdemo/` (`artifact.go`: provenance rules; `build.go`:
    atomic publication);
  - `scripts/demo/flh073/prepare/main.go` (the new commands);
  - `docs/PUBLIC_DEMO.md`.
- **New:**
  - `internal/publicdemo/realvectors.go`, `realvectors_test.go`;
  - `scripts/demo/flh076/` (`package.sh`, `smoke_package.sh`, the `browser/`
    acceptance, the `deploy/` templates, `README.md`);
  - this plan and the validation report.
