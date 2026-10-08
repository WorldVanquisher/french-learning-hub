# FLH-021 — Workbench mutation lifecycle under StrictMode

Owner: Claude Code (implementation). Status: implemented, awaiting human review.

## Finding

`web/src/main.tsx` renders the app in `StrictMode`. In development React mounts
each component, runs its effect cleanups, and runs its effect setups again.
`AnalysisRequest`, `ExtractionPanel` and `FeedbackPanel` created
`mounted = useRef(true)` and only cleared it in an effect cleanup; nothing set it
back. After the replay it stayed `false`, so the `if (!mounted.current) return;`
after each response skipped clearing `pending` and showing the outcome. The
production build does not replay effects, which is why earlier browser runs
against `server -web-dir` passed. `CaptureImport` has no such ref and was not
affected.

A related defect: `RecordDetail` passed write callbacks to its children. When
`RecordDetail` switched records without remounting, a late analysis response
for the earlier record still re-read the newly shown record and marked it as
refreshing.

## Change

- The three components now set `mounted.current = true` in effect setup and
  `false` in cleanup. A replay ends mounted; a real unmount ends unmounted.
- `RecordDetail` keeps a ref to the shown entry. The analysis and feedback
  callbacks still report the change for their own record (so the list row is
  refreshed), but do not re-read or mark a different record.
- No other refactoring. `main.tsx` keeps `StrictMode`.

Files: `web/src/components/AnalysisRequest.tsx`, `ExtractionPanel.tsx`,
`FeedbackPanel.tsx`, `RecordDetail.tsx`, and the new
`web/src/components/StrictModeLifecycle.test.tsx`.

## Evidence

New tests render inside `StrictMode`, as `main.tsx` does: 13 tests covering
Capture, Analysis, Feedback and Extraction (settling after replay, unknown
outcomes without resubmission, duplicate prevention, record and version
switches, a real unmount, per-version drafts).

| Run | Result |
| --- | --- |
| New tests against the pre-fix code (recreated in a scratch copy) | 8 failed, 5 passed. Failures: no outcome because pending never cleared, and record 9 re-read by record 8's late analysis response |
| New tests against the fix | 13 passed |
| Full frontend suite (`npx vitest run`) | 12 files, 143 tests passed |
| `npm run typecheck` / `npm run build` | exit 0 / exit 0 |
| `make verify` in an isolated copy (no `.env`, `data/`, `.git`) after `npm ci` | exit 0 |

The 5 tests that pass on the pre-fix code are regression coverage, not evidence
of the defect: capture has no `mounted` ref, extraction across a record switch
and a real unmount already discarded updates, and feedback callbacks were
already isolated by analysis ID.

### Vite development server in real Chrome

Google Chrome (headless, throwaway profile) driven by `playwright-core` against
`npx vite` dev servers (StrictMode active; `/src/main.tsx` served as a module).
Each server proxied to its own API-only backend with a scratch database, an
empty working directory, the rule-based analyzer, and extraction disabled. No
provider was called and no personal data was used.

| Step | Pre-fix code | Fixed code |
| --- | --- | --- |
| Request analysis (local rule-based) | FAIL: no outcome within 5 s | PASS: outcome, re-read reported, button available |
| Accept feedback on the latest version | FAIL | PASS: outcome, both re-reads, draft cleared |
| Request extraction (disabled, 503) | FAIL | PASS: 503 outcome, button available |
| Import a capture | PASS | PASS |

Each run sent exactly one POST per action and logged no unexpected console
errors. All servers were stopped and scratch data removed afterwards.

## NOT RUN

- Real analyzer, extractor or embedding providers.
- The Docker container path.
- Screen readers and touch devices.
- `make verify` in the working tree itself (no `web/node_modules`).
