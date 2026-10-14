# FLH-074 — independent public-demo acceptance

**Overall: FAIL. Release: BLOCKED.** Two reproducible boundary/integrity defects;
no production fix made. Date: 2026-10-14. Owner: NAS Codex. Actual pwd:
`/home/worldvanquisher/workspace/flh-nas-codex`. Branch label supplied by human:
`test/flh-074-public-demo-acceptance`; no Git/GitHub commands or subagents used.
Read actual AGENTS.md, FLH-073 plan/validation and PUBLIC_DEMO.md.

| Contract area | Result | Independent evidence |
| --- | --- | --- |
| Production startup / mode separation | PASS | Actual Go binary; fresh demo and normal frontend builds. Mechanical flag required. Four fully valid live-provider configurations explicitly refused before wiring. Normal mode creates its own DB, accepts synthetic Entry creation, retains keyword and disabled-semantic behavior, and has no demo API. |
| Root and `/api` server boundary | PASS | Enumerated 53 actual route registrations / 43 distinct patterns; invoked registered methods and six denied methods across every pattern under both prefixes. Only allowlisted reads reach services. Encoded/noncanonical paths, provider-triggering GETs and free-text preset bypasses refused. |
| Read-only / no live-provider capability | PASS | Artifact bytes and full SQLite logical dump unchanged; no WAL/SHM or demo `DB_PATH`. Preset counters exactly 32 accepted lookups / 0 refused, then 16 / 0 after restart. Wiring has no live provider client. |
| Artifact validation / release gate | FAIL / gate PASS | 26 malformed/incompatible copies rejected; valid original retained. Admission authority can change without invalidating the declared domain fingerprint (F2). Mechanical `validate -release` exits 3. |
| Static / provenance isolation | FAIL | Built JS/CSS and Concept/source endpoints work; ordinary file/traversal attempts denied. An asset symlink exposes a file outside the web directory (F1). |
| Restart / presentation | PASS mechanics; browser NOT RUN | All 16 semantic/hybrid preset responses reproduce exactly after restart; identity unchanged. Demo bundle contains mechanical notice and demo title; normal bundle does not. Existing JSDOM tests pass. No real browser executable/cache available. |

All data and vectors were synthetic; mechanical rankings prove no relevance.
No Docker, Qdrant, Windows, GPU, AWS, live model, downloads, public hosting,
DNS or reverse-proxy changes. No general security or relevance-quality claim.

## Reproducible defects

| ID / severity | Expected | Actual / consequence | Shortest reproduction against retained evidence |
| --- | --- | --- | --- |
| F1 / medium, conditional on local deployment layout | Static asset reads cannot leave the configured web root. | `GET /assets/flh074-outside.txt` returns **200**, body `FLH074 unrelated synthetic sentinel\n`, through a symlink to an owned file outside `web/`. `NewWorkbenchHandler` uses `os.DirFS`; `fileOnlyFS` rejects directories but follows file symlinks. This can disclose readable external files if a release contains such a link. No remote symlink creation or arbitrary filesystem browsing was demonstrated. | Create the link and start the server as below; GET the path. Raw response: `independent/http.jsonl`. |
| F2 / medium, incomplete domain identity | Changed admission authority invalidates an unchanged domain fingerprint even if the DB file checksum is refreshed. | Suppressing all 11 machine recommendations in a **copy**, updating only `manifest.files["demo.db"]`, leaves fingerprint `e0cefd…ce769` valid. Validator exits **0**; actual server starts. Ten active Concepts become orphaned and supporting-unit counts fall to zero, with unchanged artifact version, fingerprint and vectors. `fingerprintQueries` omits `knowledge_admission_recommendations`. This permits misleading domain-equivalence evidence; it requires a local DB change and manifest checksum update. Ordinary unrehash-ed corruption is rejected. | `/tmp/flh074-evidence/prepare validate -artifact /tmp/flh074-evidence/followup/changed-admission` exits 0. `followup.py` reproduces the mutation and fresh-process before/after reads. |

F1 reproduction (commands for the human; processes were already stopped):

```sh
ln -s /tmp/flh074-evidence/independent/unrelated-synthetic.txt /tmp/flh074-evidence/web/assets/flh074-outside.txt
(cd /tmp/flh074-evidence && env -i PATH=/usr/bin:/bin LISTEN_HOST=127.0.0.1 PORT=19874 ./server -public-demo-artifact /tmp/flh074-evidence/artifact -public-demo-allow-mechanical -web-dir /tmp/flh074-evidence/web)
# In another terminal:
curl --noproxy '*' http://127.0.0.1:19874/assets/flh074-outside.txt
# Stop that foreground server; remove only the synthetic link:
rm /tmp/flh074-evidence/web/assets/flh074-outside.txt
```

F2's retained `followup/admission-rows.json`, `changed-admission-validate.json`
and `changed-public-results.json` show exact changes and expected/actual outcomes.
The fresh manifest SHA changes, as it should: this is a fingerprint coverage
failure, **not** an unsigned-manifest authentication bypass. Local file hashes
and self-declared model identity cannot cryptographically prove model provenance.

## Commands and results

Cached dependencies only; binaries, web output and databases outside repository:

```sh
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off go build -o /tmp/flh074-evidence/server ./cmd/server
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off go build -o /tmp/flh074-evidence/prepare ./scripts/demo/flh073/prepare
/tmp/flh074-evidence/prepare build -out /tmp/flh074-evidence/artifact -fixtures scripts/demo/flh073/fixtures/catalog.json
(cd web && VITE_FLH_PUBLIC_DEMO=1 ./node_modules/.bin/vite build --outDir /tmp/flh074-evidence/web)
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off go test -json ./internal/publicdemo ./cmd/server ./internal/transport/http -run 'Test(Build_|OpenArtifact_|OpenReadOnly_|PresetProvider|PublicDemo|Workbench_|BrowserBoundary)' -count=1 > /tmp/flh074-evidence/go-tests.jsonl
(cd web && ./node_modules/.bin/vitest run src/PublicDemoApp.test.tsx src/pages/KnowledgeLibrary.test.tsx)
python3 -B scripts/validation/flh074/accept.py --server /tmp/flh074-evidence/server --prepare /tmp/flh074-evidence/prepare --artifact /tmp/flh074-evidence/artifact --web /tmp/flh074-evidence/web --output /tmp/flh074-evidence/independent
python3 -B scripts/validation/flh074/followup.py --evidence /tmp/flh074-evidence --output /tmp/flh074-evidence/followup
(cd web && VITE_FLH_PUBLIC_DEMO=0 ./node_modules/.bin/vite build --outDir /tmp/flh074-evidence/normal-web)
PYTHONPYCACHEPREFIX=/tmp/flh074-evidence/pycache python3 -m py_compile scripts/validation/flh074/accept.py scripts/validation/flh074/followup.py
```

- Both Go builds, artifact build and two frontend builds: exit 0. An initial
  Vite invocation from repository root failed resolving `index.html`; corrected
  working directory to `web` before building/testing. No production change.
- Existing suites run once: **25 top-level Go tests + 366 subtests PASS**,
  **0 skips** (publicdemo 6+17, cmd/server 3, transport 16+349).
  Frontend **12 tests / 2 files PASS**, JSDOM only. Syntax compilation: exit 0.
- Main harness: **867 PASS / 1 FAIL**, **775 recorded HTTP requests**,
  35 recorded command invocations, exit **1**, F1 only.
- Focused follow-up: **6 PASS / 1 FAIL**, exit **1**, F2 only; four fully
  configured provider-refusal checks, DB_PATH isolation and listener cleanup pass.
  Total independent expectations: **873 PASS / 2 FAIL**. Harness exit alone
  was not used as acceptance evidence.

The first main-harness analyzer/extractor/Qdrant configurations failed ordinary
configuration validation (missing required settings). Follow-up supplied invented
settings and required the explicit `public demo refuses live providers` diagnostic
for all four configurations. No real key or credentials were read.

## Boundary, state and presentation observations

- Both preset endpoints reject `q`, unknown parameters, duplicate preset/limit/
  state, malformed encodings, missing/unknown presets and invalid limits before
  vector lookup. Unknown preset is 404; malformed/invalid input is 400.
  Keyword retains its existing first-value behavior for duplicate parameters and
  ignores unknown parameters; it remains SQL-only. This is compatibility evidence,
  not a claim of stricter keyword parameter validation.
- Denied registered GETs include extraction/resolution/evaluation/comparison and
  free-text semantic/hybrid. Registered write methods and POST/PUT/PATCH/DELETE/
  OPTIONS/TRACE sweeps are 405. The existing recording-inner-handler test verifies
  refusal before dispatch. Foreign Host and forwarded-host spoofing return 403;
  cross-origin POST returns 403 from the outer browser boundary before demo 405.
  OPTIONS returns 405, no CORS grant. Existing boundary suites provide additional
  browser-header coverage; no authentication/security-audit claim.
- Mechanical API identity: 64 dimensions, model `flh073-mechanical-hash@1`,
  `real_model:false`, source `mechanical-test`, release
  `blocked_mechanical_vectors`, explicit notice. Eight presets use exactly their
  recorded texts. Two modes × eight presets × two prefixes = 32 cached lookups.
  No refused lookup, no document embedding or embedding computation. After
  restart, 16 reproduced searches give 16 lookups, counters correctly reset.
- Inspected `cmd/server/public_demo.go`: early demo branch avoids normal DB and
  analyzer/extractor/HTTP-embedding/Qdrant construction; write services passed
  nil. Actual library/semantic/hybrid services receive SQLite read interfaces,
  `ArtifactPublication`, `ArtifactIndex`, `PresetQueryVectors`. Inspected latter
  implementations: no network operations; exact envelope-to-vector map only;
  index mutation methods return `ErrReadOnlyIndex`. This is wiring plus counter
  evidence, not packet capture or a host-wide network audit.
- All four artifact hashes and complete SQLite dump match before/after denied,
  accepted and restart requests. No migration, annotation, membership, preference,
  cache or index-state write. No WAL/SHM. Normal-mode writes affect only its
  separate synthetic `independent/normal.db`.
- Missing manifest/DB/vectors/fixtures, corrupt JSON/DB checksum, mismatched
  model/representations, wrong dimensions, zero/NaN/float32-overflow vectors,
  missing/foreign/duplicate Concepts, document hash, preset text/envelope hash,
  duplicate/excess/empty presets, fingerprint mismatch, changed source domain and
  altered migration ledger: **26/26 copies rejected**, including deeper probes
  with refreshed file checksums. Original still validates afterwards.
- Fresh hashed JS/CSS bytes match served responses. Concept 1/source 1 reads work
  at both prefixes. Ordinary artifact/root paths and encoded traversal return
  404; directories are not listed. F1 is the exception to static isolation.
  No existing browser executable or Playwright cache: actual preset selection,
  mode switching, details/back and notice rendering in a browser are **NOT RUN**.
  JSDOM and bundle inspection remain separate evidence.

## Retained evidence, cleanup and release handoff

Evidence: `/tmp/flh074-evidence/`, **222 files** in `artifact-sha256.json`
(excludes Python compilation cache and the inventory itself). Inventory SHA-256:
`0bb4100f11554a9b71e1b76c317c6e868508832c1ddfd8aa07f3f485ae47592d`.

| Artifact | SHA-256 |
| --- | --- |
| Production server binary | `d4bffcaa6fee0b29f7b85ce4ff13041031c91fd96e31efc5d4e7f2b96849fd63` |
| Original manifest | `ae51056f9c7215f86e930599acbc4769bd6491758e9094edeb90949948f12063` |
| Original demo.db | `6d42a1eb440a733eff41ff67689948ac2229644a2ab438d4547b4f0f6668938e` |
| Original vectors.json | `0b8ec37999c7415816f2c4633c9f4fb02949b9ad849b69491fe2d90f41da3a2d` |
| Main raw HTTP evidence | `921eff3ff5470ee0bf6ef20290a742cfba7eaf7341e10dce71442e833b15bf12` |
| Changed public results | `64baeab4f02bbd8092fcf62ea3ffd5f3a1a91607a862319ef0ae48014f257ae7` |

`source-preservation.json`: **243 source/config/fixture files unchanged**.
All five owned long-running server instances stopped (three main, two follow-up);
ports **19874/19875/19876 closed**. Temporary symlink removed; synthetic copies,
logs, builds and normal DB retained outside repository. No unrelated service
signalled. No publication or remote deployment occurred.

Remaining human-owned deployment steps: resolve F1/F2 and repeat focused
acceptance; separately authorize and retain real-model artifact provenance;
require release validation exit 0; perform actual browser acceptance; review
release files (including symlink policy), dedicated-user/read-only permissions,
explicit environment, loopback listener, Host policy and bounded TLS proxy;
then separately decide publication/DNS. This mechanical test artifact remains
**BLOCKED for release**, regardless of passing route/ranking mechanics.

Only FLH-074 report and new harness directory changed. Human staging suggestion
(displayed only; not executed):

```sh
git add -- docs/validation/FLH-074-public-demo-acceptance.md scripts/validation/flh074/README.md scripts/validation/flh074/accept.py scripts/validation/flh074/followup.py
```

Suggested commit message:
test: record public demo acceptance and integrity defects
