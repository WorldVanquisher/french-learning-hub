# Daily workflow v1.0 release candidate — validation

Owner: NAS Claude Code, sole implementation owner, working tree
`~/workspace/flh-nas-claude`. Date: 2026-11-07.

**Status: implemented. Automated evidence only.**
- **Fake provider:** every provider call went to a local fake OpenAI-compatible
  server on loopback. No paid provider was called and no real key was used.
- **No browser:** no browser was run; the UI evidence comes from jsdom tests.
- **No real Docker:** no real `docker compose up` was run; the wrapper was
  tested through its docker shim.
- **Pending:** the owner's manual walkthrough (§5) and release publication.

## 1. Gaps found and what changed

| Gap (observed in the code before the change) | Change |
|---|---|
| A record showed analysis, feedback and extraction as separate panels. Nothing said which step was pending or what to do next. Decided units only said "already resolved or marked INVALID" | **Where this record stands**: three steps (analysis → extraction → Concept decisions) and one **Next:** action. Derived on render from reads the page already makes, plus one effective-annotation GET per decided current unit. Nothing is persisted |
| No way to see which Concept a record's unit was filed under, or to get there | Decided current units show "Filed under Concept #N (CURRENT SAME, event #L, source)" or INVALID, with **Open Concept #N in Knowledge Library**. Reviewed-unit inspection has the same link |
| Knowledge Library sources could not reach their record; AI suggestions could not reach a unit's record or Concept; leaving AI suggestions dropped the open run | **Open record #N in Learning Records** on a source. **Open record #N** / **Open Concept #N** on suggestions. A **← Back to …** banner returns to the view that was left, which stays mounted. AI suggestions stay mounted and re-read the run list, the open run and the queue on return |
| Wording did not separate analysis from extraction where users decide | The analysis panel says it describes and classifies the question; the extraction panel says it produces the units that are filed. The stage steps repeat this |
| Advisory and history semantics only per item | A completed run states it recorded nothing; a confirmed, still-current item says it can later become history; **Leave unused** says it is not DISTINCT or any label. "No suitable candidate … only the listed candidates" was already present |

**Contracts:**
- **Backend:** none changed. No endpoint, DTO, migration, provider prompt,
  provider default or API semantics.
- **Frontend (internal props only):**
  - `RecordsBrowser.onOpenConcept` / `openRequest`;
  - `RecordDetail.onOpenConcept`;
  - `ExtractionPanel.onOpenConcept` / `onFacts`;
  - `KnowledgeLibrary.openRequest` / `onOpenRecord`;
  - `UnitInspection.onOpenConcept`;
  - `ConceptSuggestions.refreshEpoch` / `onOpenRecord` / `onOpenConcept`.
- **Public demo:** it passes none of the new props, so it shows no
  record links.

**Files:**
- **Frontend code:** `web/src/App.tsx`, `web/src/components/{RecordDetail,ExtractionPanel}.tsx`,
  `web/src/components/{RecordStage.tsx,recordStage.ts}` (new),
  `web/src/pages/{RecordsBrowser,KnowledgeLibrary,ConceptSuggestions,UnitInspection}.tsx`,
  `web/src/i18n/{en,zh-CN}.ts` (62 new keys each), `web/src/styles.css`.
- **Frontend tests:** `web/src/DailyJourney.test.tsx` (new).
- **Fixture:** `scripts/validation/daily_v1_rc/{run.sh,journey.py,fake_openai.py,cases.json}`.
- **Docs:** `docs/DAILY_USE.md`, `README.md`, `README.zh-CN.md`, `web/README.md`,
  `docs/LOCAL_LEARNING_WORKFLOW.zh-CN.md`, this report.

## 2. Disposable acceptance fixture

```bash
bash scripts/validation/daily_v1_rc/run.sh <empty directory outside the repo>
```

**How it runs:**
- It builds `cmd/server`, then works inside `unshare -rn` (loopback only).
- It starts `fake_openai.py` and the server on a fresh `fixture.db`, with
  `AI_PROVIDER`, `EXTRACTOR_PROVIDER` and `SUGGESTION_PROVIDER` set to
  `openai` and pointed at the fake.
- `journey.py` drives the public HTTP API the way the workbench does.

**How it checks:**
- "Nothing changed" claims compare read-only SQLite snapshots of every
  authority table: memberships, links, judgments, distinctions, Concepts,
  admission overrides, annotation receipts, suggestion confirmations and
  current-extraction pins.

**Cases** (authored, in `cases.json`):

| Case | Expected |
|---|---|
| 1. « Tu as du pain ? Oui, j'en ai. » | Save (0 calls) → analysis (1) → Accept (0) → extraction (1, one unit) → explicit NEW CONCEPT `en` with seed human SAME |
| 2. « Elle boit de l'eau ? Oui, elle en boit. » | Unit with different wording. The suggestion (BM25 candidate) recommends Concept `en`. Generation changes no authority table. Confirm SAME → human SAME with `human_same_ai_suggestion` evidence. The Concept is supported by both units, each tracing to its own record with the original question byte-identical |
| 3. « Tu vas à Paris ? Oui, j'y vais. » | Deliberately unsuitable recommendation of `en`, left unused. Zero membership/link/judgment/distinction rows for the unit; item still `open`; unit still awaiting review |
| Stale boundary: « Vous avez des frères ? Oui, j'en ai deux. » | Its suggestion goes stale after an explicit re-extraction (v2). The item reads `stale` (`unit_not_in_current_extraction`); confirmation → `409`; authority tables unchanged; neither unit filed |

**Result of the run on 2026-11-07:**
- `43 passed, 0 failed`.
- `/healthz` → `{"status":"ok"}`, `/readyz` → `{"status":"ready"}`.
- Server stop status 0; `PRAGMA integrity_check` = `ok`.
- No output contains the placeholder key.
- Provider calls by schema: 4 `analysis_result`, 5 `knowledge_units`,
  1 `concept_suggestions`. The same-key replay and both confirmations made
  none.
- The stale refusal body:
  `{"error":"suggestion is stale: unit_not_in_current_extraction","stale_reasons":["unit_not_in_current_extraction"]}`.
- About 15 s wall time, including the build.

**Mutation checks** (scratch copies, not committed):
- Recording a DISTINCT for the `y` unit in case 3 fails 2 case-3 checks.
- Confirming the stale item before the re-extraction fails 3 stale checks.

**What the fixture proves:** HTTP-level mechanics on a real server binary and
database. Fake-provider text proves nothing about language quality or
suggestion recall.

**Reused FLH-097 regression tests** (unchanged; they still pass inside
`make verify`):
- `TestConceptSuggestions_GenerateIsAdvisoryReplayableAndReopenable`;
- `…_StaleStateBlocksConfirmation` (6 stale cases);
- `…_ConfirmRecordsAttributedHumanSameOnce`;
- `…_ReplayAfterCorrectionIsHistoricalOnly`;
- `…_AnnotationAndEvaluationBoundaries`;
- `web/src/ConceptSuggestions.test.tsx`.

## 3. Automated results (agent-run, 2026-11-07)

| Command | Result |
|---|---|
| `cd web && NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/DailyJourney.test.tsx` | 10 passed: 6 stage-logic tests; 4 App-level journeys (stage from reads, record → Concept → source → record → back, return re-reads review status and restores focus, suggestions advisory/links/back with run re-read). Each journey asserts **no write request** |
| `cd web && NODE_OPTIONS=--no-experimental-webstorage npx vitest run` | 25 files, **322 passed** (312 before; every existing test unchanged) |
| `unshare -rn bash -c 'ip link set lo up; GOPROXY=off GOFLAGS=-mod=readonly GOTOOLCHAIN=local NODE_OPTIONS=--no-experimental-webstorage make verify'` | **exit 0**: gofmt clean, Go tests, vet, server/capture/semantic-index builds, frontend typecheck, 322 tests, production build |
| `bash scripts/validation/daily_v1_rc/run.sh <scratch>/rc1` | **43 passed, 0 failed** (§2) |
| `python3 -B -m unittest discover -s scripts/validation/flh079 -p 'test_*.py'` | 25 tests OK |
| `python3 -B scripts/validation/flh079/run.py --work <scratch>/demo-accept --port 18990` | **OVERALL PASS: 210 checks, 0 failed**; browser stage **NOT RUN** (no Chrome/Chromium on this host). Run because the served library bundle changed |
| `bash scripts/validation/flh094/test_wrapper.sh <scratch>/wrapper` | **32 PASS, 0 failures** (docker shim; only `docker compose config` ran for real) |

## 4. Backup, upgrade, health and recovery

These commands are documented in [DAILY_USE.md §6](../DAILY_USE.md#6-backup-and-restore-nas).

| Command | How it was verified |
|---|---|
| `flh-daily.sh backup` / `restore DIR` | `test_wrapper.sh`: verified copy, `SHA256SUMS`, mode 700, stop/start around backup, mismatched checksum refused with data untouched, restore keeps the previous data and recreates with the same settings file |
| `flh-daily.sh up` / `check` / `status` | `test_wrapper.sh` (shim): exact `docker compose --env-file <settings> up -d --build`, refusals before any start |
| `curl -fsS http://127.0.0.1:<port>/healthz` and `/readyz` | Fixture run against the real binary: `{"status":"ok"}` / `{"status":"ready"}` |
| Upgrade: `backup` → update checkout → `check` → `up` → `/readyz` | Composed from verified commands; a real image upgrade was not run |
| Rollback: `stop` → previous checkout → `docker compose build app` → `restore <pre-upgrade backup>` → `/readyz` | **Derived from code, not run.** `restore` ends with `up -d --force-recreate` and no `--build` (`scripts/daily/flh-daily.sh`), so it starts whatever image is built. Restoring before rebuilding the older image would let the newer image migrate the restored database again. The guide now states this order |

## 5. Owner walkthrough on the NAS (real model, manual)

Use your daily settings with `SUGGESTION_PROVIDER=openai`. Expect about 7
billed calls: 2 analyses, 2 extractions, 1 or 2 suggestion runs.

**Set up:**
1. **Start.** On the NAS, run `bash scripts/daily/flh-daily.sh backup`, then
   `bash scripts/daily/flh-daily.sh up`. Open the tunnel and the workbench.

**First question: create the Concept**

2. **Save it.** In **Learning Records → Add a learning question**, save a
   question about one use of `en`, for example the partitive « Oui, j'en ai. ».
   **Check:** the stage says *Next: Request analysis below*.
3. **Analyze.** Request analysis, read it, **Accept** (or Correct).
   **Check:** step 1 is *done*; the next step is extraction.
4. **Extract.** Request extraction.
   **Check:** step 2 shows the unit count, and the units are knowledge
   statements, not the analysis text.
5. **Create the Concept.** **Open unit #N in Concept Review** → **NEW CONCEPT**
   with a reviewed identity → **← Back to record #N**.
   **Check:** the unit says *Filed under Concept #C (CURRENT SAME …)*; the
   stage says nothing is left to decide.

**Second question: the positive SAME path**

6. **Repeat with a second question** about the **same** use of `en`, in
   different words, through extraction. Don't decide the unit yet.
7. **Generate.** **Concept Review → AI suggestions**: select only the new
   unit, then **Generate suggestions**.
   **Check:** the run says it recorded nothing; the record's stage still shows
   the unit awaiting a decision.
8. **Confirm.** If the model proposes Concept #C, read the reason and the
   Concept content, then **Confirm SAME to Concept #C**.
   - **Check:** the item says it is the CURRENT SAME now and can later become
     history.
   - **If it proposes something else** or *no suitable candidate*, record
     that as a real-model result. Then leave it unused, which records nothing.
9. **Check both sources.** **Open Concept #C in Knowledge Library**.
   **Check:** both units are listed as supporting. For each, click **View
   source record #N** and confirm that the original question is exactly what
   you typed, and that the two records differ.
10. **Return.** **Open record #N in Learning Records**, then **← Back to
    Knowledge Library**, then **← Back to AI suggestions**.
    **Check:** each view is as you left it.

**Finish:**

11. **Back up.** Run `bash scripts/daily/flh-daily.sh backup`.

**Report separately:** browser layout, keyboard and language switch
(English / 简体中文); the real model's choice and reason; and any step whose
wording was unclear.

## 6. Remaining blockers for `v1.0.0`

1. **Owner walkthrough (§5) not done.** It covers the real-model positive SAME
   path from suggestion through confirmation to both sources. It was not
   established before this task either.
2. **No browser check.** The new stage summary, links and banners have not
   been seen in a real browser (jsdom only). The public-demo browser stage was
   also not run.
3. **No real image upgrade or rollback.** Neither has been exercised with real
   Docker. The rollback order in DAILY_USE.md is derived from the wrapper's
   code.

**Not blockers; noted:**
- The stage summary makes one extra GET per decided current unit.
- AI suggestion re-reads on return reload the queue's first page only.
- A confirmation that lands before a re-extraction leaves CURRENT SAME on a
  now-historical unit. That is existing FLH-097 behaviour: membership is not
  support.
