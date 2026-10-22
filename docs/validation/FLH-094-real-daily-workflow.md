# FLH-094 — Prepare the real private daily-use workflow

Owner: NAS Claude Code. Same working tree as FLH-092 and FLH-093; their files
are unchanged.

**Status: implemented. Evidence is configuration and wiring only.**
- **Fake provider:** every provider call went to a local fake OpenAI-compatible
  server. No real provider was called, no real key was used, and no model was
  chosen or evaluated.
- **No real Compose start:** `docker compose up` was not run, because it would
  rebuild `french-learning-hub:local` and create the real daily project's
  container. Docker was used only for `docker compose config`.
- **No owner data:** the owner's daily database was not opened, located or
  copied.
- **No language claims:** nothing here says anything about language quality.

## 1. Inspection findings

| Area | Existing behaviour |
|---|---|
| Release | `compose.yaml`: one service, `127.0.0.1:${FLH_HOST_PORT:-8080}`, fixed container `DB_PATH=/data/app.db`, host data `${FLH_DATA_DIR:-./data/release}` (must exist), healthcheck on `/readyz` |
| Config precedence | The server reads the process environment, then `.env` in its working directory (none in the container). Compose fills `${...}` from the shell, then from `.env` beside `compose.yaml` (or `--env-file`); the shell wins |
| Provider selection | `AI_PROVIDER` (`rule-based` default, or `openai`) and `EXTRACTOR_PROVIDER` (`disabled` default, or `openai`) are independent. Both share `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL` and `OPENAI_TIMEOUT` |
| Strictness | `openai` without a key or model stops startup (`AI_PROVIDER=openai requires OPENAI_API_KEY to be set`); the server never falls back silently. Confirmed in §3.1 |
| Backup / restore | RELEASE.md blocks: stop, file-only copy, `integrity_check` = `ok`, `SHA256SUMS`, staged restore with the old directory kept |

**F1 — demonstrated operational cause of a silent fallback (not in the
server).** Compose can recreate the container with the defaults whenever its
inputs are missing. This happens when the inputs live in the shell, or in a
`.env` at the repository root, which is the shared agent working tree, and
someone runs `docker compose up`. RELEASE.md's own Restore step
(`docker compose up -d --force-recreate`) does exactly that. The defaults are:
- `AI_PROVIDER=rule-based`: analyses are stored as rule-based, visible only in
  their provenance;
- `EXTRACTOR_PROVIDER=disabled`;
- `FLH_DATA_DIR=./data/release`: a different, empty database.

A shell export of the same variables also silently overrides the file.

**F2 — timeouts.** The defaults are `OPENAI_TIMEOUT=8` and
`HTTP_WRITE_TIMEOUT=10`. Real extraction can exceed 8 s. Raising only the
provider timeout, to the write timeout or above, lets a stored result reach the
browser as a lost response, which the workbench shows as an unknown outcome.

**Fix chosen.** No server, migration, dependency or default-policy change. A
small wrapper over the same Compose service:
- always passes one owner settings file, kept outside the repository;
- drops the inherited shell values of every variable `compose.yaml`
  interpolates;
- validates the resolved configuration without printing values.

## 2. Files

| File | Change |
|---|---|
| `scripts/daily/flh-daily.sh` | New. Commands: `check`, `up`, `stop`, `start`, `restart`, `status`, `logs`, `backup`, `restore DIR` |
| `scripts/daily/daily.env.example` | New. Placeholder template only |
| `docs/DAILY_USE.md` | New. The owner guide |
| `scripts/validation/flh094/fake_openai.py` | New. Fake OpenAI-compatible provider |
| `scripts/validation/flh094/wiring.py` | New. Server wiring checks |
| `scripts/validation/flh094/run_wiring.sh` | New. Runs the wiring checks in a loopback-only namespace |
| `scripts/validation/flh094/test_wrapper.sh` | New. Wrapper checks with a docker shim |
| `docs/RELEASE.md` | Pointer in Configuration; note in Restore |
| `README.md`, `README.zh-CN.md` | Daily-use paragraph and documentation-table row, in both languages |
| This report | — |

**Wrapper contract.**
- **Settings file:** `FLH_DAILY_ENV`, default `~/.config/flh/daily.env`. It must
  exist, be owned by the user, not be readable by group or others, and be
  outside the repository.
- **How Compose is called:** every command runs
  `docker compose --env-file <settings>`, with the variables `compose.yaml`
  interpolates and `COMPOSE_PROJECT_NAME`/`COMPOSE_FILE`/`COMPOSE_ENV_FILES`/`COMPOSE_PROFILES`
  removed from the inherited environment.
- **Validation:** it reads `docker compose config --format json` and
  `config --environment` through a pipe; values are never written or printed.
  It requires:
  - `AI_PROVIDER` and `EXTRACTOR_PROVIDER` stated explicitly, with known values;
  - key and model when either is `openai`;
  - `FLH_DATA_DIR` stated, absolute, existing, mode 700, owned by `FLH_UID`,
    outside the repository, and not an acceptance directory;
  - the effective provider timeout below the effective write timeout.
- **Project:** the existing project name `french-learning-hub` is kept, so it
  manages the same container as plain Compose. It never starts a second
  writer.
- **Backup and restore:** implement RELEASE.md's procedures on the resolved
  data path. Backups go to `<FLH_DATA_DIR>.backups/`. The final recreate uses
  the same settings file.

**Contracts unchanged:** API, schema, providers, provider defaults, versioning,
eligibility, confirmation, unknown-outcome behaviour, the FLH-092 launcher, and
the FLH-093 UI.

## 3. Validation

### 3.1 Server wiring with a fake provider

`bash scripts/validation/flh094/run_wiring.sh <scratchpad>/flh094/wiring1`
runs inside `unshare -rn`, so only loopback is reachable. The real server
binary is configured as the settings file would configure it:
- `AI_PROVIDER=openai` and `EXTRACTOR_PROVIDER=openai`;
- an explicit model placeholder and a placeholder key;
- `OPENAI_BASE_URL` set to the fake provider;
- timeouts 60/75 s;
- a fresh database in the scratch directory.

Result: **20 PASS, 0 FAIL**, plus the startup and log checks below.

| Step | Evidence |
|---|---|
| 1. Save a plain question (`POST /captures`, manual, no analysis) | 201, **0 provider calls**, `unanalyzed`, text with its line break unchanged |
| 2. Import Capture JSON with an analysis | 201, **0 calls**, `unreviewed`, provenance `imported:chatgpt-web:…` |
| Extraction of an unanalyzed record | Refused, **0 calls** |
| 3. Explicit analysis | **Exactly 1 call**: schema `analysis_result`, the configured model, a bearer token present. Stored as `openai:<model>:fr_l2_taxonomy_v1`, `unreviewed` |
| Human feedback | Stored, **0 calls** |
| 4. Explicit extraction | **Exactly 1 call**: schema `knowledge_units`, the configured model. Provenance `openai:<model>:knowledge_extraction_v1`, 2 units |
| 4. Zero units | Stored as a valid version 1 with `[]` |
| Provider failure (fake 500) | Error response, **no analysis stored**, **exactly 1 call** (no retry), no key in the response |
| 5. Membership | Extracted units are listed for review with **no** CURRENT SAME. Queue and resolution reads make 0 calls. An explicit NEW CONCEPT is recorded with 0 calls |
| Graceful stop | SIGTERM, exit status 0 (both runs) |
| Restart on the same database | Records, analysis, extraction provenance and membership persist. **Starting made 0 calls**. A new explicit analysis is version 2 through the configured provider |
| Missing key | `AI_PROVIDER=openai` without a key: exit 1 with `AI_PROVIDER=openai requires OPENAI_API_KEY to be set`, and **no database file created** |
| Logs | The placeholder key appears in no log |

### 3.2 Wrapper checks

`bash scripts/validation/flh094/test_wrapper.sh <scratchpad>/flh094/wrapper1`
uses a docker shim. Only `docker compose … config` reaches the real Docker CLI;
it interpolates and changes no daemon state. Every other docker invocation is
recorded, not executed.

Result: **26 PASS, 0 FAIL**:
- **Refused, nothing started or stopped:**
  - missing settings file;
  - settings file mode 644;
  - implicit `AI_PROVIDER`;
  - a real provider without a key, or without a model;
  - missing `FLH_DATA_DIR`;
  - a data directory that doesn't exist, or that is mode 755;
  - an acceptance-session directory;
  - `OPENAI_TIMEOUT` not below `HTTP_WRITE_TIMEOUT`.
- **Accepted:**
  - the default timeouts (8 s < 10 s);
  - explicitly local providers, labelled "local" / "off".
- **Shell overrides ignored:**
  - exported `AI_PROVIDER=rule-based`, `EXTRACTOR_PROVIDER=disabled`,
    `FLH_DATA_DIR=/tmp/elsewhere` and `OPENAI_MODEL=wrong` do not change the
    result: it still reports `openai`, `openai` and the configured database;
  - docker sees none of the inherited values.
- **`up`:** runs `docker compose --env-file <settings> up -d --build`, then
  prints the loopback URL and the tunnel command.
- **`backup` on a real SQLite file:**
  - stops the running service, then starts it again;
  - the copy has the data, a valid `SHA256SUMS` and mode 700.
- **`restore`:**
  - a tampered backup is refused, and the active data is untouched;
  - a valid backup becomes active, and the previous data is kept in
    `.before-restore-*`;
  - the container is recreated with `--env-file <settings> up -d --force-recreate`.
- **Secrets:** the placeholder key appears in no output and no docker command
  line.

### 3.3 Commands

| Command | Result |
|---|---|
| `bash -n` on `flh-daily.sh`, `run_wiring.sh`, `test_wrapper.sh`; `python3 -m py_compile` on the Python helpers | passed |
| `bash scripts/validation/flh094/run_wiring.sh <scratchpad>/flh094/wiring1` | 20 PASS, 0 FAIL, plus startup and log checks |
| `bash scripts/validation/flh094/test_wrapper.sh <scratchpad>/flh094/wrapper1` | 26 PASS, 0 FAIL |

`make verify` was not rerun: no Go, frontend or build input changed.

## 4. Awaiting the owner

1. **Settings:** create the private data directory and the settings file, and
   set **your** model and key (`docs/DAILY_USE.md` §1). Then run
   `bash scripts/daily/flh-daily.sh check`.
2. **First real start:** `bash scripts/daily/flh-daily.sh up` builds the image
   from the current tree and starts the container. Not executed by the agent.
3. **First real provider run:** one analysis and one extraction on a real
   question. Each may be billed. This is the first evidence that your model and
   key work with the existing adapters, including structured-output support
   and latency within `OPENAI_TIMEOUT`.
4. **Existing data, if any:** a verified backup with RELEASE.md's
   **Migrate the daily database**, then `flh-daily.sh restore <backup>`.

## 5. Limitations

- **One model:** the analyzer and extractor share `OPENAI_MODEL` and
  `OPENAI_BASE_URL` (existing contract). Separate models per step would need a
  configuration change.
- **No real Compose start:** whether the container becomes healthy with real
  settings is verified by the owner's first `up`, not here.
- **Validation is not a preflight call:** whether the provider accepts the
  chosen model, the key or the structured-output schema is only known at the
  first explicit request. No preflight call is made, by design.
- **Untested refusal:** the inside-the-repository check for the settings file
  and data directory was reviewed in code but not exercised. Doing so would
  have required creating files in the working tree.
- **Backups stay on the NAS:** they sit next to the data directory. Copying
  them off the NAS is the owner's step.
- **Language quality:** none. Bilingual generated explanations remain the next
  separate task.
