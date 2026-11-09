# Daily Listening: Pull, Prepare, and Notify — validation

Owner: Claude Code (sole implementation owner). Date: 2026-11-09 (UTC).
Branch: `feat/daily-listening-delivery` (prepared by the owner from `main` after
Exam Listening Lesson v1 merged).

**Status: implemented and tested** against local fakes of the YouTube Data
API, the OpenAI Responses API and the Telegram Bot API, with real SQLite, the
real handler, the real adapters, and the real server and command binaries.
- **Real services:** not contacted. No real key, token or notification was used.
- **Live timer:** not installed or enabled; the unit files were only verified offline.
- **Daily database:** not opened. Every run used a disposable database.

Contract: [ARCHITECTURE.md §4.4](../ARCHITECTURE.md#44-daily-listening-pull-prepare-notify)
and Appendix A.16. Owner guide: [DAILY_USE.md §10](../DAILY_USE.md#10-daily-listening-pull-prepare-notify).

## 1. What was built

- **One pull:** `ListeningDailyService.Pull`, used by **Pull now**
  (`POST /listening/pull`) and by `cmd/listening-pull` (`/app/listening-pull`,
  `flh-daily.sh listening-pull [--scheduled]`). Both are built by
  `listening.NewServices` from one configuration.
- **Source:** YouTube Data API v3 `playlistItems.list`, official metadata only.
  It is bounded: 1–200 items, 50 per request, a per-request timeout, 1 MiB per
  response, no redirects, and the key in a header.
- **Deduplication:** by video ID (`listening_playlist_items`). A video saved by
  hand is matched, never duplicated, and a new video waits for its transcript.
- **Preparation:** `LISTENING_AUTO_PREPARE=daily` allows at most one attempt
  per local day in `LISTENING_TIMEZONE`, enforced by a partial unique index. It
  uses the same `prepare` path as the explicit button.
- **Notification:** `LISTENING_NOTIFY=telegram`, title only, and only for the
  lesson that pull prepared.
- **Receipts:** migration `015_listening_daily.sql` adds `listening_pull_runs`
  (one running row, with a lease), `listening_playlist_items`,
  `listening_preparations` and `listening_notifications`. Each attempt is
  inserted before its outside call and finished once.
- **Unknown outcomes:** a timeout, or a lost response after sending, is
  `unknown`; "sent" is decided by `httptrace.WroteRequest`. Nothing retries
  automatically. An explicit retry after an unknown outcome needs
  `confirm_unknown_retry`.
- **Lost responses:** clients look the stored result up by key and resend only
  the same key. The handlers detach the work from the client's cancellation.
- **Explicit Prepare (Listening v1):** now goes through the same path, with an
  optional `Idempotency-Key`. Its `201` body is now `{preparation, exercise}`,
  where v1 returned the exercise alone; the workbench was updated with it.
- **Operations:** `compose.yaml` forwards the new settings. The image ships
  `/app/listening-pull`, and `make verify` builds it. `flh-daily.sh` validates
  the settings, prints a summary without values, and adds `listening-pull` and
  `listening-status`. Example units are in `scripts/daily/systemd/`.
- **Public demo:** startup refuses any Daily Listening part enabled, the routes
  are not allowlisted, and the four tables must be empty.
- **Workbench:** a **Daily listening** panel (settings, today's use, last pull,
  **Pull now**), backend-derived row states with **From your playlist**, a
  keyed **Prepare exercise** with lookup, and acknowledged retry and lesson
  **Notifications** with an explicit, acknowledged resend.

## 2. Acceptance checks

| Requirement | Test | Result |
|---|---|---|
| Playlist adapter: official metadata, bounded requests | `TestYouTubePlaylist_ReadsOfficialMetadataWithinBounds` (120 of 130 items in 3 requests of 50/50/20, `part`, page tokens, no key in the URL); `…SkipsPrivateDeletedAndMalformedEntries`; `…FailuresAreClassifiedWithoutSecrets` (refused, unavailable, invalid, dropped, timeout; no key or URL in errors) | pass |
| Dedupe by video ID | `TestDailyListening_PullDedupesAndWaitsForTranscript`: a manually saved video is matched, a private one skipped, and a second pull creates nothing; the real-binary smoke repeats it | pass |
| Waiting for transcript; no ASR or scraping; no notification | same test: new videos are `waiting_for_transcript`, with **0 model and 0 Telegram calls**; the only outside request is `playlistItems` | pass |
| Explicitly enabled preparation, at most 1 lesson per day | `…PreparesOneLessonPerLocalDayAndNotifies`: the second pull that day reports `daily_cap_reached` with no call; at 00:05 Paris (still the 9th in UTC) the next lesson is prepared; the cap is shared by button and command (`TestListeningPull_SharesThePullWithTheButtonAndNeverOverlaps`, smoke) | pass |
| Manual pulls and scheduled runs share the dedup and preparation path | the command and an in-process "server" on separate connections to one database file share the cap and the lease (`TestListeningPull_*`); the smoke runs the built command and the button against the same server | pass |
| Timer example with timezone | `systemd-analyze verify --user` on copies of both units: exit 0, no warnings; `systemd-analyze calendar '*-*-* 07:30:00 Europe/Paris'` gives 06:30 UTC. Nothing installed or enabled | pass |
| No overlapping runs | `…RunsNeverOverlapAndInterruptedRunsAreReported`: a second pull during the first answers `409 busy` and records nothing; a run past its lease reads `interrupted` and is marked so; the command exits 4 while a run holds its lease (Go test and smoke) | pass |
| Last outcome visible | `GET /listening/daily` `last_run`; `listening-pull status`; the workbench **Last pull** (jsdom) | pass |
| Generation timeout or lost response: check the stored result first; unknown needs explicit retry | `…UnknownGenerationOutcomesNeedAnExplicitRetry` (timeout gives `unknown` with nothing announced; later pulls never retry it and it does not block another lesson; an explicit Prepare without acknowledgement gives `409 outcome_unknown` with no call; with it, one call and `after_unknown`; a dropped connection gives `unknown`, not `failed`); `…LostResponsesAreCheckedByKeyBeforeAnyRetry` (an impatient client loses the answer, a second click gives `409 in_progress` with no call, the key lookup shows `in_progress` then `completed`, and a same-key resend gives `200` replay with no call; the same for a pull) | pass |
| Ambiguous Telegram sends: same rule | `…AmbiguousTelegramSendsNeedAnExplicitRetry` (a dropped connection gives `unknown` / `no_response`; a later pull never resends; an explicit resend needs acknowledgement; same-key replay; after `sent`, `not_retryable`); `…RefusedAndUnsentNotificationsAreFailuresWithoutRetry` (HTTP 400 gives `refused`, connection refused gives `not_sent`, no automatic resend) | pass |
| Notify only when ready; no transcript or credentials | message is `«title»` only: no transcript words, link, key or token (Go test and smoke) | pass |
| Separate status | `prepare_outcome` and `notify_outcome` are recorded per run; preparations and notifications have their own rows and states | pass |
| Source failure | `…SourceFailureIsRecordedAndPreparationStillRuns`: `failed/source_refused`, preparation and notification still run, no key or URL in the run | pass |
| Disabled and public demo | `…DisabledAndDemo`: `503`, nothing recorded, no outside call; demo GET `404` and POST `405` on every new route at root and `/api`; demo startup refuses any part enabled (`TestPublicDemo_RefusesLiveProvidersAndMechanicalReleaseArtifacts`); publicdemo coverage needs the four tables empty | pass |
| Configuration | `TestLoad_ListeningDaily*`: defaults off; every dependency (key, playlist, generator, preparation before notify, IANA zone, chat ID, token shape, https except loopback) refused without echoing a secret or the chat ID | pass |
| Workbench | 7 new jsdom tests: Pull now (key, no body, waiting rows, no exercise POST); lost pull answer looked up, then the same key resent only on click; busy; off; lost Prepare answer found by key; unknown outcome needs **Retry preparation (may be billed again)** with `confirm_unknown_retry`; unknown notification resent only with **Send again anyway** | pass |

## 3. Commands and results

Go 1.27.3, Node v26.13.0, run in `~/workspace/flh-nas-claude`.

| Command | Result |
|---|---|
| `go test -count=1 ./internal/config` (with `listening_daily_test.go`) | ok |
| `go test -count=1 ./internal/listening/...` (adapters against `listeningfake`) | ok |
| `go test -race -count=1 -run 'DailyListening\|ListeningLesson' ./internal/transport/http` | ok (10 Daily Listening and 6 Listening v1 tests) |
| `go test -race -count=1 ./cmd/listening-pull ./internal/listening/... ./internal/application` | ok |
| `bash scripts/validation/flh094/test_wrapper.sh <scratch>` (docker shim; only `docker compose config` is real) | `{"failures": 0}`, 67 checks, including the new Daily Listening settings and `listening-pull` / `listening-status` command lines and exit-status pass-through |
| `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/pages/Listening.test.tsx src/i18n/i18n.test.tsx` | 28 passed (15 Listening, 13 i18n parity) |
| Backend mutations, each restored: cap 2; pull retries unknown; candidate ignores unknown; retry without acknowledgement; notification resend without acknowledgement; prepare or pull canceled with the client; Telegram drop classed as failed; OpenAI drop classed as failed; no dedupe against hand-saved material; notify without a prepared lesson; no busy check; cap day in UTC | all 13 caught. "Candidate ignores unknown" was first missed; the test now covers an unknown attempt on an older transcript and shows it would starve other lessons |
| Frontend mutations, each restored: auto-resend a lost pull; resend with a new key; retry without acknowledgement; skip the key lookup; notification resend without acknowledgement; unknown shown as failed | all 6 caught |
| Real-binary smoke (scratch script, not committed): `go build` server and `listening-pull`; under `unshare -rn` with loopback only, `env -i`, a disposable database, and Python fakes of YouTube, OpenAI and Telegram on loopback | **20 PASS, 0 FAIL**: scheduled command, button pull, shared cap, lost response looked up then replayed, overlapping command exits 4, status, restart, ledger `015`, no key or token in any log or output |
| Doc links (edited Markdown) | 155 checked, 0 problems |
| `set -o pipefail; NODE_OPTIONS=--no-experimental-webstorage make verify` | **exit 0**: gofmt, Go tests (20 packages ok), vet, builds (now including `listening-pull`), typecheck, **27 files / 344 tests**, production build |

## 4. Not verified, and limits

- **Real services:** the YouTube Data API, OpenAI and Telegram were never
  contacted. The adapters follow the documented request and response shapes,
  but those shapes were reproduced by local fakes, not checked against the
  services. In particular:
  - the `fields` filter and the privacy status values of real deleted or
    private playlist entries;
  - quota errors (assumed `403`);
  - Telegram's answers for a wrong chat ID.
- **Real browser and image:** the workbench is tested in jsdom only. The Docker
  image was not built here, so `/app/listening-pull` inside the image and
  `docker compose exec` were not run; the wrapper test checks only the command
  line.
- **Live timer:** never installed. `systemd-analyze` checks syntax and the
  calendar only, not that a user manager runs it, lingering, or the NAS's systemd version.
- **The cap counts attempts.** A failed or unknown attempt uses the day.
- **An unknown attempt blocks automatic preparation of that video** (any
  transcript version) until the learner retries explicitly.
- **A slow Pull now can exceed `HTTP_WRITE_TIMEOUT`.** The run still finishes,
  and the workbench finds it by key; `check` prints a note.
- **The playlist read is bounded, not complete:** only the first
  `LISTENING_PLAYLIST_MAX_ITEMS` entries in playlist order.
- **Notification wording is fixed** (English and Chinese lines plus the title).
- **The public demo:** a demo artifact built before migration `015` is refused
  by a server that has it (ledger check). The deployed demo runs its own pinned
  release and was not touched.
