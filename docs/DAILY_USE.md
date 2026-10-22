# Private daily use with real providers

This is the repeatable way to run your own workbench on your own data, with the
OpenAI-backed analyzer and extractor that already exist. It reuses the
personal-use release ([RELEASE.md](RELEASE.md)): one Docker image, one Compose
service on `127.0.0.1`, SQLite in a host directory. The only addition is
`scripts/daily/flh-daily.sh`, which runs that same Compose service with **one
settings file, every time**.

The settings file is needed because plain `docker compose` takes its values
from your shell or from a `.env` next to `compose.yaml`. A `docker compose up`
run without them, including RELEASE.md's restore step, recreates the container
with the defaults:
- the rule-based analyzer;
- extraction disabled;
- **`./data/release`, a different database.**

The script always passes the same settings file. It ignores inherited shell
values for those variables, and refuses to start when anything required is
missing.

## Daily use versus acceptance sessions

| | Daily use (this page) | Acceptance session (FLH-092) |
|---|---|---|
| Command | `scripts/daily/flh-daily.sh` | `scripts/validation/flh092/serve.sh` |
| Database | your persistent `FLH_DATA_DIR/app.db` | a disposable `WORK_DIR/fixture.db` |
| Data | your real questions | 1,000 synthetic records, seeded |
| Providers | your settings: `openai` (or explicitly local) | rule-based analyzer, local stub extractor, fake key |
| Special input | none | `[fx:N]` markers for the stub |
| Port | `FLH_HOST_PORT` (default 8080) | 18990 / 18991 |

Never point one at the other's directory. `flh-daily.sh` refuses a data
directory that contains the acceptance markers (`flh092-session`,
`fixture.db`, `seed.json`).

## 1. One-time setup [NAS]

You need Docker with the Compose plugin, `sqlite3` and `sha256sum`, plus this
repository checkout.

1. **A private data directory outside the repository.** The example uses
   `~/flh-daily-data`; any absolute path works.

   ```bash
   install -d -m 700 ~/flh-daily-data
   ```

2. **Your settings file**, outside the repository and readable only by you:

   ```bash
   install -d -m 700 ~/.config/flh
   install -m 600 ~/workspace/flh-nas-claude/scripts/daily/daily.env.example ~/.config/flh/daily.env
   ```

3. **Edit `~/.config/flh/daily.env` in an editor.** Don't put the key on a
   command line, where it would be saved in shell history. Set:

   | Setting | What to put |
   |---|---|
   | `FLH_DATA_DIR` | the absolute path from step 1, e.g. `/home/<you>/flh-daily-data` |
   | `FLH_UID`, `FLH_GID` | your `id -u` and `id -g` (the owner of the data directory) |
   | `AI_PROVIDER`, `EXTRACTOR_PROVIDER` | `openai` for real analysis and extraction. `rule-based` / `disabled` keep a step local or off. Both must be stated |
   | `OPENAI_MODEL` | the model **you** choose; nothing here picks one |
   | `OPENAI_API_KEY` | your key, in single quotes |
   | `OPENAI_TIMEOUT`, `HTTP_WRITE_TIMEOUT` | the template's `60` / `75`; the provider timeout must stay below the write timeout |
   | `FLH_HOST_PORT` | `8080` unless that port is taken |

   To use another settings file, set `FLH_DAILY_ENV=/path/to/file` in front of
   each command.

4. **Check the settings.** Nothing starts and no provider is called:

   ```bash
   cd ~/workspace/flh-nas-claude
   bash scripts/daily/flh-daily.sh check
   ```

   The check prints only non-secret facts, for example:

   ```text
   analysis:   openai — explicit requests call the provider and may be billed
   extraction: openai — explicit requests call the provider and may be billed
   OPENAI_MODEL: set · OPENAI_API_KEY: set · OPENAI_BASE_URL: default (public OpenAI API) · timeouts: provider 60s < write 75s
   database:   /home/<you>/flh-daily-data/app.db
   browser:    http://127.0.0.1:8080/  (loopback only)
   ```

   It refuses, naming the problem, when:
   - the file is missing or readable by others;
   - a provider is not stated explicitly;
   - a key or model is missing;
   - the data directory is missing, not private, inside the repository, or an
     acceptance session;
   - the timeouts are inverted.

5. **Existing data (optional).** If you already have a daily database, first
   make a verified backup of it with RELEASE.md's **Migrate the daily
   database** block. Then restore that backup here:
   `bash scripts/daily/flh-daily.sh restore <that backup directory>`.

## 2. Start, stop, restart [NAS]

```bash
cd ~/workspace/flh-nas-claude
bash scripts/daily/flh-daily.sh up        # build if needed, start, wait until healthy
bash scripts/daily/flh-daily.sh status    # settings summary + docker compose ps
bash scripts/daily/flh-daily.sh logs -f   # follow the server log (never shows keys)
bash scripts/daily/flh-daily.sh stop      # stop; container and data kept
bash scripts/daily/flh-daily.sh start     # start the stopped container again
bash scripts/daily/flh-daily.sh restart
```

- **`up`:** prints `ready at http://127.0.0.1:8080/` and the tunnel command.
- **Rebuilding:** run `up` again after updating the checkout. **Back up first**:
  a newer image may migrate the database (see Section 5).
- **Same container as plain Compose:** this is the Compose project from
  `compose.yaml` (`french-learning-hub`), so `docker compose ps` shows the same
  container.
- **Don't mix in plain `up`:** don't run plain `docker compose up` for daily
  use, because it would drop your settings.

## 3. Browse from another machine [Mac]

The service listens on the NAS loopback only. Replace `<NAS_SSH_HOST>` with the
alias or `user@address` you use for `ssh`:

```bash
ssh -N -L 8080:127.0.0.1:8080 <NAS_SSH_HOST>
```

Then open `http://127.0.0.1:8080/`.
- **Same origin:** the browser's Host and Origin are both `127.0.0.1:8080`, so
  saving and decisions work without any extra origin setting.
- **Port taken on the Mac:** use another local port
  (`-L 18080:127.0.0.1:8080`) and open that port instead.

## 4. What calls a model, and what never does

| Step in the workbench | Model call? | Result |
|---|---|---|
| 1. **Add a learning question** → **Save question** | **No** | A record with your text as typed (outer whitespace trimmed), state `unanalyzed` |
| 2. **Capture JSON** → **Import capture** | **No** | The record and, if the JSON has one, its analysis as an `unreviewed` candidate (`imported:<source>:…` provenance). Importing never means you accepted it |
| 3. **Request analysis…** → **Create a new analysis version** | **Yes**, once, `AI_PROVIDER` | A new immutable analysis version, `unreviewed`, provenance `openai:<your model>:fr_l2_taxonomy_v1.explanation_en_zh_v1`, with English and Chinese explanations from the same call. **Accept**, **Correct** or **Reject** are your separate decisions and call nothing |
| 4. **Request extraction…** → **Send to the extraction provider** | **Yes**, once, `EXTRACTOR_PROVIDER` | Refused before any call when the record has no analysis or its latest analysis was rejected. Otherwise a new extraction version with **zero or more** units, provenance `openai:<your model>:knowledge_extraction_v2`, each statement in English and Chinese from the same call |
| 5. **Concept Review**: SAME, NEW CONCEPT, … | **No** | Only your explicit decision is recorded. Nothing is filed automatically |

Every request is sent once and never retried automatically. If no response
arrives, the workbench says the outcome is unknown rather than failed. Use
its check or explicit resend controls; the server shows whether a new version
was stored. Each analysis or extraction request may be billed by your
provider.

## 5. Backup and restore [NAS]

```bash
bash scripts/daily/flh-daily.sh backup
```

**What it does:**
- stops the service if it is running;
- copies `app.db` and its present WAL/SHM files into
  `<FLH_DATA_DIR>.backups/flh-<UTC time>/` (mode 700);
- requires `PRAGMA integrity_check` to be exactly `ok`;
- writes `SHA256SUMS`;
- starts the service again if it was running.

On any failure it stops and leaves the service stopped. Copy backups off the
NAS as well. Back up before every image upgrade.

```bash
bash scripts/daily/flh-daily.sh restore <FLH_DATA_DIR>.backups/flh-<UTC time>
```

**What it does:**
1. Stops the service and verifies `SHA256SUMS`.
2. Copies the backup into a staging directory and checks its integrity.
3. Renames the current data directory to `<FLH_DATA_DIR>.before-restore-<time>`.
   That copy is kept, never deleted.
4. Moves the staged copy into place.
5. Recreates the container **with the same settings file**.

A checksum or integrity failure changes no data, but the service stays stopped
until you run `start`. After a restore, check the records you expect.

## 6. Shortest real-question walkthrough

1. **[NAS]** `bash scripts/daily/flh-daily.sh up`.
2. **[Mac]** Run the tunnel, then open `http://127.0.0.1:8080/`. Click
   **Learning Records**, then **Add a learning question**.
3. Type a real question under **Your question**, add the context, and click
   **Save question**. Nothing is sent to a model. Then click
   **Open saved record #N**.
4. Click **Request analysis…**, then **Create a new analysis version**. That
   is one provider call. Read it, then **Accept**, **Correct** or **Reject**.
5. Click **Request extraction…**, then **Send to the extraction provider**.
   That is one provider call. Zero units is a valid result.
6. For each unit, click **Review unit #N in Concept Review**:
   - read the unit and its original question;
   - inspect a candidate's contents;
   - decide SAME or NEW CONCEPT explicitly.
7. **[NAS]** `bash scripts/daily/flh-daily.sh backup` when you finish a session.

## Troubleshooting

| Symptom | Cause / action |
|---|---|
| `flh-daily: … must be set` / `refused` | Fix the named setting in your settings file, then run `check` |
| Service restarts repeatedly | A configuration error (e.g. `AI_PROVIDER=openai requires OPENAI_API_KEY to be set`); see `logs`. Values are never logged |
| `unable to open database file` | `FLH_UID`/`FLH_GID` do not own `FLH_DATA_DIR` |
| Extraction says it is not enabled | `EXTRACTOR_PROVIDER` is `disabled` in the settings, or the browser reached another server (check the tunnel's port) |
| Analysis or extraction reports a provider failure | Nothing was stored. Check the model name, key, quota and network; request again explicitly |
| An outcome is "unknown" | No response arrived; often a provider slower than `OPENAI_TIMEOUT`. Use the workbench's check, or raise both timeouts, keeping the provider timeout below the write timeout |
| `request host is not allowed` (403) | Browse through the tunnel at `127.0.0.1` or `localhost` |
| Port in use | Change `FLH_HOST_PORT` in the settings file and the tunnel |
