# FLH-095 — Bilingual learning explanations

Owner: NAS Claude Code. Same working tree as FLH-092 to FLH-094; their
uncommitted work is kept (overlaps in §5).

**Status: implemented. Validated with fake providers, isolated synthetic
databases, Go tests and jsdom tests only.**
- **No real model call:** no real provider was called, so real-model
  bilingual quality has **not** been evaluated.
- **No browser:** no browser was run, so browser behaviour is unverified.
- **Not acceptance:** this is not owner acceptance.

## 1. Contract

**Which fields have variants.** Only generated explanatory text:

| Field | English / Chinese |
| --- | --- |
| Analysis explanation | `explanation_en` / `explanation_zh` |
| Knowledge-unit statement | `statement_en` / `statement_zh` |

**Unchanged:**
- category, uncertainty, the unit's canonical label and kind;
- French examples, learner input and context, imported source text;
- IDs, Concept identity, signatures, membership;
- admission, retrieval and embedding representations.

### 1.1 Storage: migration `012_bilingual_explanations.sql` (additive)

- `entry_analyses`: `explanation_en TEXT NULL`, `explanation_zh TEXT NULL`.
- `knowledge_units`: `statement_en TEXT NULL`, `statement_zh TEXT NULL`.
- `analysis_feedback`:
  - `corrected_explanation_en TEXT NULL`, `corrected_explanation_zh TEXT NULL`;
  - `reviewed_explanation_languages TEXT NULL`, with a `CHECK` limiting it to
    `en`, `zh` or `en,zh`.
- **No backfill and no rewrite.** NULL means the language was not recorded: every
  earlier row, imported Capture analyses, and fixture units. Rows stay immutable;
  the new columns are written once, on insert.
- **Primary text:** `explanation` and `statement` stay the primary text for every
  existing consumer. When `*_en` is present it must equal the primary text
  (domain-validated).

### 1.2 Providers: same explicit request, no translation calls

| Producer | Output | Provenance |
| --- | --- | --- |
| OpenAI analyzer | `explanation` (English) + `explanation_zh` | `openai:<model>:fr_l2_taxonomy_v1.explanation_en_zh_v1` |
| OpenAI extractor | per unit `statement` (English) + `statement_zh` | `openai:<model>:knowledge_extraction_v2` |
| Rule-based analyzer | its existing English text, recorded as `en` only | unchanged `rule-based:v2:fr_l2_taxonomy_v1` |
| Capture import | unchanged `learning_capture_v1`; no language recorded | unchanged |

- **Strict schemas:** both strict schemas require the Chinese field.
- **Rejected output:** a missing, null or blank Chinese field is rejected as
  `422`, and nothing is stored.
- **Prompts:**
  - the Chinese text must carry the same content as the English;
  - French quotations stay verbatim in French.
- **Unchanged otherwise:** the same configured provider and model, with no
  retries, no fallback, and no background generation.

### 1.3 Human feedback and effective values

| Request field | Meaning |
| --- | --- |
| `reviewed_explanation_languages` | The explanation languages shown when the decision was made: a subset of `["en","zh"]`, without repeats; canonical order is stored. Each must be stored on that analysis, checked in the feedback transaction, else `422` |
| `corrected_explanation_en` / `_zh` | Per-language corrections, `corrected` only |
| `corrected_explanation` | Unchanged: the language-unspecified correction, never combined with the per-language fields |

**Per-language effective explanation** (derived on read):

| Basis | When |
| --- | --- |
| `corrected` | the person supplied text in that language |
| `reviewed` | accepted, or only the category corrected, while that language was shown |
| `not_reviewed` | feedback exists, but that language was not shown, or no languages were recorded |
| `outdated` | the explanation was corrected in another or an unspecified language; the generated text is kept, flagged |
| `unreviewed` | no feedback |
| `unavailable` | nothing stored in that language |

- **Rejected:** no effective explanation in any language (unchanged).
- **Language-independent `effective.explanation`:** read by extraction and the
  inventory. It is the corrected text in any language (unspecified, then
  English, then Chinese), else the original. The inventory SQL applies the same
  order.

### 1.4 HTTP (additive)

- **Analysis responses:** `explanations: {en, zh}`.
- **Units** (extraction, reviewable queue, effective annotation, library unit
  and source): `statements: {en, zh}`.
- **Feedback request and response:** the three fields above.
- **Effective analysis:** `original_explanations` and `effective_explanations`
  (per language `{text, basis}`, or null when rejected).
- **Library source view:** reuses these shapes.

### 1.5 Workbench

- **Explanation language** selector in the header: Both stored languages /
  English / 中文.
  - Stored as `flh.explanation-language.v1`; the default is Both.
  - Separate from the UI **Language**: switching the UI to 简体中文 does not
    change the explanations shown, and switching the explanation language does
    not change the application text.
  - Read-only: no request, and drafts, selections, position and pending or
    unknown outcomes stay as they were.
- **Text without a recorded language** is labelled "language not recorded".
- **A missing variant** is stated ("No Chinese explanation is stored for this
  version."), never replaced by the other language.
- **Effective interpretation:** shows each language's basis. A correction whose
  language was not recorded is labelled.
- **Feedback on a bilingual analysis:**
  - English and 中文 correction fields;
  - the panel states which languages the decision will record as shown.
- **Feedback on a legacy analysis:** keeps the single field and sends no
  languages.
- **Where the variants appear:** record analysis and effective interpretation,
  extracted units, the Concept Review unit card, Concept contents (FLH-093) and
  the Annotation Inspector.
- **Not changed:** the Knowledge Library pages and the public demo still show
  the primary statement.

## 2. Files

| Area | Files |
| --- | --- |
| Migration | `migrations/012_bilingual_explanations.sql` |
| Domain | `internal/domain/explanation.go` (new), `analysis.go`, `feedback.go`, `effective.go`, `knowledge.go` |
| Storage | `internal/storage/sqlite/analysis_repository.go`, `feedback_repository.go`, `knowledge_repository.go`, `concept_repository.go`, `inventory_repository.go` |
| Providers | `internal/analyzer/openai.go`, `rulebased.go`, `internal/extractor/openai.go` |
| HTTP | `internal/transport/http/explanations.go` (new), `handler.go`, `knowledge.go`, `concept.go`, `effective_annotation.go`, `knowledge_library.go` |
| Go tests | `internal/domain/explanation_test.go`, `internal/storage/sqlite/bilingual_explanations_test.go`, `internal/transport/http/bilingual_integration_test.go` (new); `internal/analyzer/openai_test.go`, `rulebased_test.go`, `internal/extractor/openai_test.go`, `internal/transport/http/integration_test.go` (updated) |
| Frontend | `web/src/explanationLanguage.tsx`, `web/src/components/ExplanationText.tsx` (new); `App.tsx`, `components/RecordDetail.tsx`, `FeedbackPanel.tsx`, `ExtractionPanel.tsx`, `UnitCard.tsx`, `ConceptContent.tsx`, `pages/AnnotationInspector.tsx`, `types/learning.ts`, `types/concept.ts`, `types/library.ts`, `i18n/en.ts`, `i18n/zh-CN.ts`, `styles.css` |
| Frontend tests | `web/src/BilingualExplanations.test.tsx` (new) |
| Local stubs / fakes | `scripts/demo/flh034/stub_extractor.py`, `scripts/validation/flh089/stub_extractor.py`, `scripts/validation/flh093/stub_extractor.py`, `scripts/validation/flh093/check.py`, `scripts/validation/flh094/fake_openai.py`, `scripts/validation/flh094/wiring.py` |
| Docs | `docs/ARCHITECTURE.md` (§3.9, §11, A.4), `AGENTS.md` (CLAUDE.md is a symlink to it), `README.md`, `README.zh-CN.md`, `web/README.md`, `docs/DAILY_USE.md`, this report |

## 3. Validation

| Command | Result |
| --- | --- |
| `go test ./internal/...` | all packages pass |
| `go test ./internal/transport/http/ ./internal/domain/ -run 'Bilingual\|CaptureImportHasNo\|Variants\|ExplanationBasis' -v` | 7 new tests pass |
| `go test ./internal/storage/sqlite/ -run Bilingual -v` | 2 new tests pass |
| `cd web && NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/BilingualExplanations.test.tsx` | 10 passed |
| `bash scripts/validation/flh093/run.sh <scratchpad>/flh095/flh093` | 18 PASS, 0 FAIL (adds a Chinese-statement check) |
| `bash scripts/validation/flh094/run_wiring.sh <scratchpad>/flh095/flh094` | 21 + 5 restart checks, 0 failures; the same call stored both languages |
| `bash scripts/validation/flh089/run.sh <scratchpad>/flh095/flh089` | seed as before (1,000 records, 3,000 units); `workflow.py` 30 passed, 0 failed; all 3,003 units have both statement variants; 967 of 968 analyses record English (the remaining one is the workflow's Capture import, which records no language) |
| `NODE_OPTIONS=--no-experimental-webstorage make verify` | exit 0: gofmt, Go tests, vet, builds; frontend typecheck, **302 tests in 23 files**, production build |

**What the tests prove:**
- **Legacy records:** a database built through migration 011 (with a legacy
  analysis, a legacy correction, an extraction and a unit) upgrades under 012
  with:
  - text unchanged;
  - no language recorded;
  - the effective explanation unchanged;
  - **no column backfilled**.
- **Capture import:**
  - the imported analysis has `explanations: {en: null, zh: null}`;
  - claiming a reviewed language on it is refused with `422`;
  - its effective basis is `unavailable`, with the text unchanged.
- **Valid and malformed output:**
  - bilingual analyzer and extractor output is stored with both variants;
  - a missing, null or blank Chinese field (including one unit of two) is
    rejected as `422`;
  - both schemas require the Chinese field;
  - an English variant different from the primary text is rejected.
- **Existing validation tests:** the extractor validation tests now exercise the
  rule they name. Before the test helper supplied a Chinese statement, they were
  being rejected by the missing Chinese field instead.
- **Human corrections and effective projections:**
  - the full basis matrix;
  - accepting with English shown leaves Chinese `not_reviewed`;
  - a Chinese-only correction makes English `outdated` and becomes the
    language-independent effective explanation, in both the record and the
    inventory;
  - a legacy unspecified correction makes both languages `outdated`;
  - a reviewed language not stored on the analysis is refused, and nothing is
    stored.
- **Version history and sources:**
  - feedback history keeps both decisions;
  - the analysis and the entry are unchanged;
  - the FLH-093 checks still show every unit keeping its own original question.
- **Language switching:**
  - switching shows and hides stored text only, with no request;
  - the preference is stored under its own key, and the UI locale doesn't
    change it;
  - Concept Review keeps the position, selection and identity draft, and every
    request is a GET;
  - correction drafts survive a switch;
  - the feedback body records only the languages shown.
- **Identity and embedding:**
  - `DeriveCandidateIdentity` and its signature are identical with or without
    variants;
  - retrieval and embedding builders read only `statement` (unchanged code
    paths);
  - existing retrieval, embedding and semantic tests pass unchanged.

## 4. Compatibility

- **Older clients:** an API client that sends only the old feedback fields keeps
  working. On a bilingual analysis its accept leaves both languages
  `not_reviewed` (no false approval). Its unspecified correction marks both
  `outdated`.
- **Provenance strings change** for new provider output only. Stored rows keep
  their provenance.
- **Public demo artifacts:**
  - the demo checks the migration ledger exactly, so an artifact built before
    012 is refused by a server that includes 012;
  - rebuild the artifact with the current tree;
  - release packages pair their own binary with their artifact, so a packaged
    release is unaffected;
  - the domain-fingerprint queries list explicit columns and are unchanged.
- **Embedding and semantic index:** the vector-defining text is unchanged, so no
  re-embedding is needed.

## 5. Overlap with uncommitted earlier work

These files were changed by this task as well as by an earlier uncommitted task:

| File | Earlier task | FLH-095 change |
| --- | --- | --- |
| `scripts/validation/flh093/stub_extractor.py`, `check.py` | FLH-093 | Statements rewritten to English (French forms quoted) plus `statement_zh`, and one Chinese-statement check |
| `scripts/validation/flh094/fake_openai.py`, `wiring.py` | FLH-094 | Chinese fields; new provenance strings; one bilingual check |
| `docs/DAILY_USE.md` | FLH-094 | Provenance strings in the call table |
| `web/src/components/ConceptContent.tsx`, `UnitCard.tsx` | FLH-093 | Statement rendering through `StoredText` |
| `README.md`, `README.zh-CN.md`, `web/README.md`, `docs/ARCHITECTURE.md` | FLH-093/094 | One feature bullet each, a §3.9 section, a migration row, API notes |

Also changed, previously committed: `scripts/validation/flh089/stub_extractor.py`
(FLH-089) and `scripts/demo/flh034/stub_extractor.py` (FLH-034). Both now return
`statement_zh`, because the v2 extractor contract rejects units without it.

`docs/validation/FLH-094-real-daily-workflow.md` is a historical report and
keeps the provenance strings that were true when it ran.

## 6. Remaining owner decisions and gaps

- **Real-model quality:** whether the chosen model produces faithful Chinese
  explanations has not been evaluated. Judge the first real analyses and
  extractions yourself; nothing here measures translation fidelity.
- **Cost:** asking for two languages makes each response longer, which may
  raise token cost and latency. `OPENAI_TIMEOUT` may need headroom (see
  `docs/DAILY_USE.md`).
- **Existing records:** they stay single-language by design. Getting Chinese
  for them means a new explicit analysis or extraction version, or a human
  per-language correction. There is no bulk backfill.
- **Unit statements** have no human correction path (units are immutable
  evidence, as before).
- **Not changed:**
  - Knowledge Library, public demo and inventory list rows still show the
    primary text only;
  - library keyword search does not search Chinese statements.
- **Browser:** layout of stacked variants and basis labels, and keyboard flow
  through the new selector, are unverified.
- **Public demo:** existing artifacts must be rebuilt before a server with
  migration 012 can serve them (§4).

## 7. Review findings closed before commit (2026-10-21)

The pre-commit review raised six items. The owner made these decisions, and
this section records what was changed.

| # | Finding | Decision and outcome |
| --- | --- | --- |
| 1 | `corrected_explanation_en/_zh` were accepted on analyses with no recorded language (pre-`012` rows, Capture imports) | **Fixed.** The feedback transaction (`internal/storage/sqlite/feedback_repository.go`) now refuses them with `422` when the analysis has neither variant, and nothing is stored. The language-unspecified `corrected_explanation` is unchanged. Per-language corrections on language-recorded analyses are unchanged, including a Chinese correction of an English-only rule-based analysis. No language is inferred from a correction. |
| 2 | A Chinese-only correction becomes the language-independent effective explanation, which extraction reads | **Kept as documented** (§1.3), with its existing tests. |
| 3 | Migration `012` is forward-only | No change. `docs/RELEASE.md` already requires a backup before upgrading and forbids running an older image on a newer database. |
| 4 | A server with `012` refuses demo artifacts built before it | **Documented** in `docs/PUBLIC_DEMO.md` ("Migration 012 (FLH-095) and existing artifacts") and `docs/AWS_DEMO.md` §5. The ledger must match the binary exactly in both directions. Self-contained packages that are already built or deployed are unaffected. The deployed AWS package was not touched. |
| 5 | The public-demo CI job had not been run after FLH-095 | **Run** (§7.2). |
| 6 | The `012` variant columns are outside the demo domain fingerprint | **Not expanded (owner decision).** `docs/PUBLIC_DEMO.md` now says these columns are protected only by the `files["demo.db"]` hash, and that the coverage test checks tables, not columns. |

**Rows written before the guard.** Before this fix, a per-language correction
on an analysis without recorded languages could be stored, but only by a
direct API call: the workbench sends per-language fields only when the analysis
has a recorded variant (`FeedbackPanel.tsx`). No owner data was scanned or
modified, and no cleanup migration was added. If such a row exists, it still
reads consistently:
- the corrected language has basis `corrected` with that text;
- the other language is `unavailable`, because the analysis stores no variant;
- the language-independent `effective.explanation` is the correction, chosen
  in the order unspecified, then English, then Chinese, by both the domain and
  the inventory SQL;
- `original.explanation` is still the stored primary text.

### 7.1 Tests added

- `internal/storage/sqlite/bilingual_explanations_test.go`,
  `TestBilingual_PerLanguageCorrectionNeedsRecordedLanguages`:
  - an English, Chinese or English-plus-Chinese correction on a
    no-language analysis returns `ErrValidation`, and 0 rows are stored;
  - a legacy `corrected_explanation` is stored;
  - a Chinese correction of an English-only analysis is stored.
- `internal/transport/http/bilingual_integration_test.go`,
  `TestIntegration_CaptureImportHasNoRecordedLanguage` (extended):
  - three per-language corrections on a Capture import return `422`, and the
    feedback list stays empty;
  - a legacy `corrected_explanation` returns `201`, and the effective
    explanation is the correction with both languages `unavailable`.
- Bilingual correction is still covered by
  `TestIntegration_BilingualAnalysisFeedbackAndEffective`.

### 7.2 Validation run for this fix

All runs used synthetic data, isolated temporary directories and no provider.

| Command | Result |
| --- | --- |
| `go test ./internal/storage/sqlite/ -run Bilingual -v` | 3 passed |
| `go test ./internal/transport/http/ -run 'Bilingual\|CaptureImportHasNo' -v` | 3 passed |
| `gofmt -l cmd internal migrations scripts` | no output |
| `go vet ./...` | no findings |
| `go test ./...` | exit 0 |
| `python3 -B -m unittest discover -s scripts/validation/flh079 -p 'test_*.py'` | 25 tests OK |
| `python3 -B scripts/validation/flh079/run.py --work <scratchpad>/accept --port 18990` | exit 0, **OVERALL PASS: 210 checks, 0 failed**. Stages preflight, build, artifact (synthetic mechanical artifact built from this tree, including `012`), web, serve-http, restart and final passed. **Browser: NOT RUN**, because this host has no Chrome or Chromium. CI runs the same script with `--require-browser`. |
| `python3 -B scripts/validation/flh079/failure_probe.py --work <scratchpad>/probe --port 18992` | FAILURE PROBE PASS: the assertion case exits 1, the interrupt exits 143, cleanup is verified and no process is left behind |

The frontend was not changed by this fix, so its suites were not rerun. The
last `make verify` result in §3 still applies to the frontend.

### 7.3 Browser status (correction)

The earlier review said no real browser had been used. That was too broad: the
owner exercised some workbench paths and supplied a Concept Review screenshot.
**Full browser acceptance is still incomplete.** The FLH-092 result table is
not filled in, and the layout of stacked variants and basis labels, keyboard
flow through the Explanation-language selector, and the public-demo browser
stage on this tree are unverified. Real-model bilingual quality is also still
unverified.
