# FLH-075 validation: public-demo static confinement and complete domain fingerprint

Date: 2026-10-14. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64, Go 1.26.5, Python
3.13.5). Contract: [plan](../plans/FLH-075-public-demo-integrity.md). Input:
[FLH-074](FLH-074-public-demo-acceptance.md).

**Not used:** Git/GitHub, subagents, a model, AWS, Windows, a GPU, Docker or
publication.

**Not modified:** the FLH-074 report and harness. Earlier artifacts were not
modified either (checked by hash).

**Baseline:** the first attempt (before FLH-074 was integrated) found no
FLH-074 report or harness in the working tree. That was reported, and nothing
was edited. After integration, both were present and are used below
unchanged.

## Before the fix: F1 and F2 reproduced

Fresh binaries, artifact and demo web build in `/tmp/flh075-before/`, built
from the unmodified tree with the FLH-074 README commands. On this Mac there is
no `GOCACHE`/`GOPROXY=off` (ordinary `go build`).

```sh
python3 -B scripts/validation/flh074/accept.py --server …/server --prepare …/prepare --artifact …/artifact --web …/web --output …/independent
python3 -B scripts/validation/flh074/followup.py --evidence /tmp/flh075-before --output /tmp/flh075-before/followup
```

| Harness | Exit | Result | Failing expectation |
| --- | --- | --- | --- |
| `accept.py` | 1 | **867 PASS / 1 FAIL**, 775 requests | `static symlink cannot expose outside web root`: `GET /assets/flh074-outside.txt` → **200**, body `FLH074 unrelated synthetic sentinel\n` |
| `followup.py` | 1 | **6 PASS / 1 FAIL** | `changed admission invalidates unchanged domain fingerprint`: validate exit **0**, and 12 Concept results changed in the changed copy's public library |

Both match the FLH-074 report exactly.

## After the fix: the same harnesses, unchanged

Fresh binaries, artifact and web build in `/tmp/flh075-after/`.

| Harness | Exit | Result | Former defect |
| --- | --- | --- | --- |
| `accept.py` | **0** | **868 PASS / 0 FAIL**, 775 requests | `GET /assets/flh074-outside.txt` → **404** `404 page not found` |
| `followup.py` | **0** | **7 PASS / 0 FAIL** | `prepare validate` on the changed copy → exit **1**, "public demo artifact rejected: database fingerprint differs from the manifest". The server also refuses that artifact at startup (exit 1, same message), so no altered library is served |

**Other harness checks,** unchanged and passing:
- mechanical opt-in;
- the four valid live-provider configurations refused;
- `DB_PATH` untouched;
- listener cleanup;
- route sweeps;
- artifact-hash and logical-dump preservation;
- 32/16 cached lookups;
- static JS/CSS bytes.

## Compatibility

- **A v1 artifact is refused.** The pre-fix artifact
  `/tmp/flh075-before/artifact` (FLH-073 format, fingerprint without a
  version), checked with the new binaries:
  - `prepare validate` exits 1;
  - the server exits 1 at startup;
  - both print "domain fingerprint contract v1 (FLH-073, no version) is not
    flh075_domain_fingerprint_v2: older fingerprints do not cover admission
    recommendations, the current-extraction selection or record order.
    Rebuild the artifact into a new directory: go run
    ./scripts/demo/flh073/prepare build -out NEW_DIR".
  - The artifact's bytes were unchanged afterwards (hash of all files).
- **Rebuild:** the documented steps (PUBLIC_DEMO.md) produced exits 0
  (build), 0 (validate) and **3** (`validate -release`, BLOCKED: mechanical
  vectors). `vectors.json` is identical to the v1 artifact's. The artifact
  version changed from `54386d802b65d2b3` to `c21c0d756ba66c1e`, because the
  fingerprint contract changed.
- **Unchanged:** normal-mode static serving and routing. The existing
  workbench, boundary and demo tests pass.

## Automated results

| Command | Result |
| --- | --- |
| `go test ./internal/transport/http/ -run 'Workbench_\|PublicDemo\|Browser' -count=1` | ok: the 7 existing workbench tests plus 2 new |
| `go test ./internal/publicdemo/ -count=1` | ok: the 6 existing tests (17 tampering subtests) plus 4 new |
| `TMPDIR=/private/tmp/flh075-gotmp make verify` | **exit 0**: gofmt; `go test ./...` all 15 packages ok; `go vet`; builds; frontend 18 files / **219 tests**; production build |
| `bash scripts/demo/flh073/smoke.sh /tmp/flh075-smoke 19878` | **exit 0**, 93 PASS, `SMOKE PASSED`, no servers left |

**`TMPDIR`:** this is the macOS workaround documented in FLH-071, for the
pre-existing `scripts/validation/flh053` symlinked-temp-path refusal.

**Mutation checks** (each change made temporarily, then restored):
- **F2 coverage:** with recommendations removed from the fingerprint, the
  recommendation subtests and the schema-coverage test fail.
- **F1 response code:** the first F1 test run caught a real gap. `os.Root`
  refused the escaping link, but `http.FileServer` answered **500** (no
  content leaked). `fileOnlyFS` now maps every open failure to not-found
  (404).

## What the new tests cover

**F1** (`workbench_symlink_test.go`):
- **Served unchanged:** `/`, `/assets/app.js`, a nested
  `/assets/nested/deep.css`, a relative in-root file link
  (`alias.js → app.js`), and a relative in-root directory link
  (`nested-alias → nested`).
- **Refused** (never `200`, never the sentinel; `404`, or the file server's
  canonical redirect for a directory path):
  - an absolute link to an outside file;
  - a relative `../../` link outside;
  - a linked outside directory, and a nested linked outside directory;
  - an absolute link even to an in-root file;
  - `/assets/`, `/assets/nested`, `/assets/nested/`, `/assets/outdir`, and a
    missing file.
- **Swapped after startup:** a regular file replaced by an outside link while
  the handler runs is refused, so confinement happens per open.
- **Routing:** the `/api` prefix strip and root API passthrough are unchanged.
- **Startup:** an `index.html` resolving outside the root is a startup error.
  A `-web-dir` that is itself a link works.

**F2** (`publicdemo_test.go`): each mutation is applied to a copy with
**`files["demo.db"]` refreshed**. The file checks pass, and the domain
fingerprint is what rejects the change:
- the FLH-074 mutation (all recommendations suppressed), and one
  recommendation reason changed;
- a human admission override added;
- the current extraction pinned;
- a Concept retired;
- link evidence changed;
- a recommendation moved after the links in time (order change only);
- an `annotation_operations` row added.

**Other fingerprint tests:**
- **Uniform time shift accepted:** every timestamp in the database shifted by
  one hour, with the checksum refreshed, still validates. Absolute time
  carries no domain meaning; order does.
- **Version gate:** a v1 manifest (no version) is refused with the rebuild
  text, and an unknown version is refused.
- **Schema coverage:** every table in `sqlite_master` is covered, required
  empty or explicitly exempted; the manifest records v2 with 11
  recommendations.

## NOT RUN and limits

- **Browser:** actual browser interaction was **NOT RUN** (no browser
  automation available). Static checks are HTTP and Go tests only.
- **Not a security audit.** `os.Root` confines symlink resolution. It does not
  address hard links, bind mounts or filesystem aliases made by someone with
  write access to the release directory.
- **The fingerprint detects inconsistent edits, not forgery.** Someone able to
  rewrite the database and recompute the manifest can produce a matching
  artifact. Absolute timestamps (displayed dates) are bound only by the
  database file hash.
- **Release:** the mechanical release remains **BLOCKED**. Real-model
  vectors, deployment and publication remain human-owned and unauthorized
  here.

## Evidence (outside the repository)

- **`/tmp/flh075-before/`:** the before binaries, artifact, web build, and
  `independent/`, `followup/`.
- **`/tmp/flh075-after/`:** the same after the fix, plus `v1-server.log` and
  `release.err`.
- **`/tmp/flh075-smoke/`:** the smoke-run output.
- **Harness hygiene:** the temporary symlink was removed by the harness's
  `finally`, and no test server is left running.
