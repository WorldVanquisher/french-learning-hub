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
  a newer image may migrate the database (see Section 6).
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
| 6. **Concept Review → AI suggestions** → select at most 10 units → **Generate suggestions** | **Yes**, once per request, `SUGGESTION_PROVIDER` (optional, default `disabled`) | A stored suggestion run, provenance `openai:<your model>:concept_suggestion_v1`: for each unit an existing Concept from at most 5 candidates, *no suitable candidate* or *uncertain*, with a short reason. Nothing is filed. A unit with no candidate is not sent |
| 7. **Confirm SAME to Concept #n** on one suggestion | **No** | A human SAME, recorded only if the unit and Concept are still in the state the suggestion saw; otherwise it is refused as stale. **Leave unused** records nothing: the item stays open and it is not DISTINCT or any other label |
| 8. Any **Open …** / **← Back to …** link between views | **No** | Opens a read-only view; nothing is recorded |

Suggestion requests use more tokens than one analysis (up to 10 units and 5
candidates each), so allow `OPENAI_TIMEOUT` headroom as for extraction.

Every request is sent once and never retried automatically. If no response
arrives, the workbench says the outcome is unknown rather than failed. Use
its check or explicit resend controls; the server shows whether a new version
was stored. Each analysis or extraction request may be billed by your
provider.

## 5. Where a record stands, and what to do next

Every record detail starts with **Where this record stands**. It is read from
the server's current records each time the record is shown; nothing in it is
stored.

| Step | What it is | When it is done |
|---|---|---|
| 1. **Analysis** | Describes and classifies your question (category and explanation). It is **not** knowledge yet | You accepted or corrected the latest version |
| 2. **Extraction** | Produces the knowledge statements (**units**). The units, not the analysis, are what you file | A current extraction exists (zero units is a valid result) |
| 3. **Concept decisions** | Your explicit SAME / NEW CONCEPT (files the unit) or INVALID (sets it aside) per unit | No current unit awaits review |

The **Next:** line names one action:

| Next says | Do this |
|---|---|
| Request analysis below | **Request analysis…** (one provider call) |
| Review analysis vN below | **Accept**, **Correct** or **Reject**, then request extraction. Extraction is allowed without review, but it then uses an unchecked interpretation |
| The latest analysis was rejected | Request a new analysis; extraction is refused until then |
| Request extraction below | **Request extraction…** (one provider call) |
| Nothing to file: extraction vN found no knowledge statements | Nothing; request another extraction only if you expected units |
| N of M units await a decision | **Open unit #N in Concept Review**, or select those units under **AI suggestions** |
| Nothing is left to decide | Done. Each filed unit says **Filed under Concept #N (CURRENT SAME …)** and links to it |

**Moving between views without losing your place:**
- **Open Concept #N in Knowledge Library** on a filed unit (or in a reviewed
  unit's inspection) opens that Concept.
- On the Concept, **View source record #N** shows the unit's original question.
  **Open record #N in Learning Records** opens that record.
- An AI suggestion offers **Open record #N** and, once the unit is filed,
  **Open Concept #N**.
- The **← Back to …** banner returns to the record, AI suggestions or the
  library exactly as you left them. Leaving AI suggestions keeps the open run;
  coming back re-reads it.

**Three distinctions to keep in mind:**
- **A suggestion is advisory.** Generating suggestions records nothing. Only
  **Confirm SAME** on one item records a human SAME, after the server re-checks
  the state.
- **A confirmed SAME can later become history.** The unit's CURRENT SAME is
  what counts now. A later correction moves it, and the earlier decision stays
  visible as history.
- **"No suitable candidate"** applies only to the at most 5 candidates the
  model was shown. Another Concept may still fit.

## 6. Backup and restore [NAS]

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

### Health check [NAS]

```bash
bash scripts/daily/flh-daily.sh status          # settings summary + "(healthy)" in docker compose ps
curl -fsS http://127.0.0.1:8080/healthz         # {"status":"ok"}: the process answers
curl -fsS http://127.0.0.1:8080/readyz          # {"status":"ready"}: SQLite is reachable
```

Use your `FLH_HOST_PORT` instead of `8080`. `up`, `start`, `restart`, `backup`
and `restore` already wait for the container's own `/readyz` healthcheck.

### Upgrade [NAS]

Migrations are forward-only (RELEASE.md, **Upgrades and migration rollback
limits**). Always back up first, and keep the image that works under a second
tag. That is what you go back to if the upgrade fails:

```bash
bash scripts/daily/flh-daily.sh backup          # note the printed backup directory
docker image tag french-learning-hub:local french-learning-hub:before-upgrade
# update the checkout to the new version (your own Git step)
bash scripts/daily/flh-daily.sh check
bash scripts/daily/flh-daily.sh up              # rebuilds the image, starts, waits until healthy
curl -fsS http://127.0.0.1:8080/readyz
```

When `up` fails, it says so after 60 s: "the service did not become healthy
… See: … logs". `bash scripts/daily/flh-daily.sh logs --tail 50` shows why.

### Roll back a failed upgrade [NAS]

`restore` recreates the container from the image currently tagged
`french-learning-hub:local`; it does not rebuild. If that is still the newer
image, it would migrate the restored database again. Never start an older
image on a newer database. Use this order:

```bash
bash scripts/daily/flh-daily.sh stop                                        # 1. stop the failed service
docker image tag french-learning-hub:before-upgrade french-learning-hub:local  # 2. the known-good image
bash scripts/daily/flh-daily.sh restore <FLH_DATA_DIR>.backups/flh-<time of the pre-upgrade backup>  # 3.
curl -fsS http://127.0.0.1:8080/readyz
```

- **Check out the previous version** (your own Git step) before the next `up`,
  because `up` rebuilds the image from the checkout.
- **No `before-upgrade` tag?** In step 2, check out the previous version and
  run `docker compose build app` in the repository directory instead. Building
  needs no settings and starts nothing.
- **Data written after that backup is not carried back.** The replaced data
  stays in `<FLH_DATA_DIR>.before-restore-<time>`.
- **Rehearsed:** this order was exercised end to end with real Docker in an
  isolated project. See
  [V1-RELEASE-REHEARSAL](validation/V1-RELEASE-REHEARSAL.md).

## 7. Shortest real-question walkthrough

1. **[NAS]** `bash scripts/daily/flh-daily.sh up`.
2. **[Mac]** Run the tunnel, then open `http://127.0.0.1:8080/`. Click
   **Learning Records**, then **Add a learning question**.
3. Type a real question under **Your question**, add the context, and click
   **Save question**. Nothing is sent to a model. Then click
   **Open saved record #N**. **Where this record stands** says
   "Next: Request analysis below".
4. Click **Request analysis…**, then **Create a new analysis version**. That
   is one provider call. Read it, then **Accept**, **Correct** or **Reject**.
5. Click **Request extraction…**, then **Send to the extraction provider**.
   That is one provider call. Zero units is a valid result.
6. For each unit, click **Open unit #N in Concept Review** (in the stage
   summary) or **Review unit #N in Concept Review**:
   - read the unit and its original question;
   - inspect a candidate's contents;
   - decide SAME or NEW CONCEPT explicitly.
   Optionally, **Concept Review → AI suggestions** proposes an existing
   Concept for selected units; confirm one item at a time or leave it unused.
7. **← Back to record #N**: the stage now says the unit is filed. Click
   **Open Concept #N in Knowledge Library** to see the Concept and each unit's
   source record.
8. **[NAS]** `bash scripts/daily/flh-daily.sh backup` when you finish a session.

## 8. Recall practice from a Concept

Recall practice reads only. It sends no write and calls no model, so it needs
no backup.

1. **[Mac]** Open **Knowledge Library** and then a Concept that at least two
   of your questions support, such as the `en` Concept from the positive SAME
   walkthrough.
2. Under **Recall practice**, click **Start recall practice…**. Tick the
   questions that make good prompts (up to 5), then **Start practice**.
3. For each question, answer aloud or in **Your attempt**, then click
   **Reveal stored explanation**. Compare, click **Open the original source**
   if you want the record, and **← Back to practice**.
4. Mark **Recalled**, **Try again** or **Skip**. At the end, run the second
   pass over the **Try again** items, or **End practice**.

**Limitations:**
- **The reveal is the explanation stored for the unit.** Reusing it does not
  establish its linguistic quality, and practising does not demonstrate
  learning gains. Nothing judges your answer.
- **Nothing is remembered.** There is no score, schedule or history; leaving
  practice, switching the Concept or reloading the page discards the session.
- **Only current support is offered,** at most the first 10 supporting units,
  in the order the Library lists them, without shuffling.
- **The question is your record as written.** A question that gives the answer
  away, or a context that you need, is your choice to skip; the context is
  shown only on the source screen.

## 9. Listening practice with your own transcript

**Saving, browsing and opening a video read only.** Only **Prepare exercise**
calls the provider, and only when `LISTENING_PROVIDER=openai` is in your
settings file (then `check` shows `listening:  openai — explicit requests call
the provider and may be billed`). **Save learning record** creates one ordinary
learning record.

1. **[Mac]** Open **Listening**. Paste a YouTube video link, a title and the
   French transcript you have; then **Save material**. Without a transcript the
   lesson says **Waiting for a transcript** until you paste one.
2. Click **Prepare exercise**: one request. The lesson shows two to four French
   questions; the transcript, answers and notes stay hidden.
3. Watch the video (**Open the video on YouTube ↗**), answer, then click
   **Reveal answers and evidence**. Compare with the reference answer, its
   reason (Explanation language applies) and the cited lines of your transcript;
   a timestamp link opens the video at that point when your source gave one.
4. On a question you missed, click **Save as a learning question…**, write what
   you missed or want to ask, check the attached context, and click
   **Save learning record**. **Open record #N in Learning Records** shows it; it
   then follows the usual analysis → extraction → Concept path.

**A synthetic rehearsal** (no real video, no billed call): the Go test
`TestListeningLesson_PrepareReopenAndSaveMissedPoint` runs this whole path
against a local fake provider with the authored transcript in
[examples/listening/](../examples/listening/). To see it in the workbench
without a provider, save that transcript with any well-formed link (for
example `https://youtu.be/FLHlisten01`, which is not a real video) and leave
`LISTENING_PROVIDER=disabled`: the lesson says preparation is off.

**Limitations:**
- **You supply the transcript.** Nothing is transcribed, downloaded or read
  from YouTube captions. Timestamps exist only where your source gave them.
- **The exercise is generated.** Its references are checked against your
  transcript (existing lines, verbatim excerpts, no invented times), but the
  quality of its questions and French has not been evaluated with a real
  model. It is a self-check, not an exam score or a CEFR level.
- **Answers and self-checks are not saved.** Leaving the page discards them.
- **A failed preparation is shown, never retried.** Click again only if you
  want another (possibly billed) request; a lost response may already have
  stored an exercise, so reload the lesson first.

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
