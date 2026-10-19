# FLH-083 — Optional Simplified Chinese UI localization (handoff)

Owner: NAS Claude Code. Branch (human-prepared): `feat/flh-083-ui-language-switch`.
Scope: frontend (`web/`), its tests and documentation. No backend, API, schema,
artifact or published package changed.

## Result

Every workbench view and the public demo have an **English / 简体中文** selector
in the header.

**Covered views:**
- Learning Records, including capture import, record detail, analysis,
  feedback and extraction;
- Knowledge Library;
- Concept Review;
- Annotation Inspector;
- the FLH-082 unit inspection with corrections;
- Experiment Dashboard;
- the public demo.

**Behaviour:**
- **Default:** English on first use, regardless of browser locale.
  `navigator.language` is never read.
- **Persistence:** an explicit choice is stored in `localStorage` under
  `flh.ui-locale.v1`. Unavailable storage, or any value other than `en` or
  `zh-CN`, means English. If saving fails, the choice still applies and the
  selector says it is not saved.
- **Switching:** happens in place, and `document.documentElement.lang`
  follows.
  - The providers sit above all view state, so drafts, navigation,
    selections, pending writes and unknown outcomes are kept.
  - Outcome banners, notices, reconciliation and refresh texts are stored as
    message references or render functions, so text shown before a switch
    re-renders in the new language.
  - Nothing is re-sent.
- **English text:** byte-identical to before, except one hybrid-search
  sentence, which was split into two complete sentences so it is not
  assembled from fragments. All 230 pre-existing tests pass unchanged, apart
  from three data-shape assertions; FLH-076 browser-acceptance strings are
  preserved.

## Boundaries

**Translated (application text):**
- navigation, controls, labels and placeholders;
- confirmations and explanations;
- empty, loading and error states;
- outcome and refresh banners;
- accessibility labels;
- display labels for known status values (record and resolution states,
  Concept state, lifecycle, support, admission, annotation status, selection
  mode, experiment and index-run states). The raw value still drives logic,
  filter option values, requests and CSS classes.

**Never translated:**
- learner input and context, and French examples;
- unit text;
- analyzer explanations and categories;
- Concept targets and identity fields;
- human notes;
- IDs;
- wire values and API fields;
- provider, retriever and model names;
- provenance (`analysis #`, `feedback #`, event IDs, decision sources,
  resolver versions);
- schema versions and metric names;
- demo preset labels and texts;
- the decision vocabulary (SAME, NEW CONCEPT, BROADER, NARROWER, RELATED,
  DISTINCT, INVALID, RESTORE, REASSIGN, CURRENT SAME).

**Server errors:** raw details (`(status) message`) appear verbatim inside the
translated surrounding sentence.

**Kept distinct:** confirmed, rejected, unknown ("Outcome unknown." /
"结果未知。") and failed-refresh states each keep their own message and banner
role.

## Mechanism

- **`web/src/i18n/en.ts`:** the typed English reference catalog, 783 keys.
- **`web/src/i18n/zh-CN.ts`:** typed `Record<MessageKey, string>`, so a
  missing or extra key fails the typecheck.
- **`web/src/i18n/index.tsx`:** `LocaleProvider`, `useI18n()` and
  `LanguageSelect`.
  - `t(key, vars)` interpolates `{name}`.
  - `tp(base, count)` selects `.one`/`.other`.
  - `tn(key, nodes)` fills a whole-sentence template's placeholders with React
    nodes, so no markup lives inside strings.
  - `status(value)` gives display labels.
  - `msg()`/`MessageRef` is used for helpers outside React; `render()` shows
    any stored message.
- **Outside a provider:** text is English, so components rendered alone keep
  their behaviour.
- **No dependency added.** No translation service, model or network call.

The helper modules `reviewOutcome.ts` and `unitCorrection.ts` now return
message references instead of English strings. `checkDecision` raises a typed
`ReceiptMismatchError` whose message is shown translated.

## Files

**New:**
- `web/src/i18n/index.tsx`
- `web/src/i18n/en.ts`
- `web/src/i18n/zh-CN.ts`
- `web/src/i18n/i18n.test.tsx`

**Modified, `web/src`:**
- `App.tsx`, `PublicDemoApp.tsx`, `styles.css` (selector styles);
- `components/`: `AnalysisRequest`, `CandidateConceptCard`, `CaptureImport`,
  `ExplicitAction`, `ExtractionPanel`, `FeedbackPanel`, `HistoryPanel`,
  `IdentityEditor`, `MembershipPanel`, `RecordDetail`, `ResolutionActions`,
  `UnitCard`;
- `pages/`: `AnnotationInspector`, `ExperimentDashboard`, `KnowledgeLibrary`,
  `RecordsBrowser`, `ReviewQueue`, `UnitCorrections`, `UnitInspection`;
- `pages/reviewOutcome.ts`, `pages/unitCorrection.ts`;
- tests: `pages/ReviewOutcomes.test.tsx` and `pages/annotationOperation.test.ts`.
  Three assertions now compare `formatEn(evidence.text)` with the same English
  strings.

**Documentation:**
- `README.md`, `README.zh-CN.md`, `web/README.md`;
- `docs/ARCHITECTURE.md` §10.4, `docs/PUBLIC_DEMO.md`;
- `AGENTS.md` = `CLAUDE.md` (an FLH-083 section);
- this report.

## Validation

Environment: NAS, Linux x86_64, Node v26.9.0, npm 12.0.2. Commands run in `web/`
with the existing `node_modules`; no dependency was installed.

| Command | Result |
| --- | --- |
| `npm run typecheck` | passed |
| `NODE_OPTIONS=--no-experimental-webstorage npm test` (the documented setting for Node 25+) | **20 files, 243 tests passed**: 230 existing and 13 new |
| `npm test` without the flag | 40 failed / 203 passed. The failures are exactly the pre-existing ones documented in FLH-082 (`annotationOperation.test.ts`, `ReviewOutcomes.test.tsx`, `ReviewQueue.test.tsx`: Node 26's own `localStorage` shadows jsdom's). The 13 FLH-083 tests pass with or without the flag; they install an in-memory `Storage` |
| `npm run build` | passed (writes the git-ignored `web/dist/`) |
| `python3 -B scripts/validation/flh079/run.py --work <scratch> --port 18994` | **OVERALL PASS, 210/0.** It builds the public-demo bundle from this tree and runs its HTTP, routing, provenance and denied-route checks. Browser stage **NOT RUN**: no browser on this host |

**The 13 new tests (`i18n.test.tsx`):**
- **Default:** English even with `navigator.language`/`languages` set to
  `zh-CN`, through the real App in StrictMode. Nothing is saved before an
  explicit choice.
- **Switching:** the switch is immediate, `<html lang>` updates, the choice
  persists across a remount (a reload), and switching back works.
- **Bad storage:** invalid saved values give English. With unavailable
  storage the page is English by default, switching still works, and the
  "not saved" notice appears.
- **Catalog parity:** identical keys; identical placeholder sets for every
  message; non-empty translations; `.one`/`.other` pairs; no markup in any
  message; the decision vocabulary is untranslated.
- **Formatting:** interpolation, nested message references with a raw server
  error, a missing variable left visible, English plurals, node templates.
- **Data boundaries:** in Chinese, a stored Concept target and type stay as
  stored; a status display label keeps the raw CSS class; a raw 500 server
  message appears verbatim inside the translated error; filter option values
  stay wire values (`state=accepted` reaches the request).
- **Switching mid-task:** a capture draft and its unknown outcome survive a
  switch, the banner re-renders in Chinese and back to English, and "Check
  import status" stays available. A Concept Review INVALID with an unknown
  outcome stays blocked and visible across a switch, with learner text and a
  search draft unchanged, and is never re-sent (exactly one POST).

**Breaking the implementation on purpose, in a temporary copy of `web/`:**

| Break | Caught by |
|---|---|
| Honouring the browser locale | 1 test |
| Not persisting the choice | 2 tests |
| Rendering message-reference banners in English only | The switch-with-unknown-outcome test |
| Dropping a Chinese key | The typecheck |

## Limits and risks

- **Not checked in a real browser:** there is no browser on the NAS. The
  FLH-076 `accept.mjs` acceptance checks the English default (title,
  `lang="en"`, texts); it was not re-run here. jsdom does not lay out the
  page, so how longer Chinese strings look visually was not checked.
- **Translation quality:** no native-speaker review. Terminology (概念, 单元,
  学习记录, 提取, 收录状态) is consistent but may need tuning.
- **Pre-existing:** the static `index.html` still declares `lang="fr"`, until
  the provider sets the UI language on mount.
- **Process:** during final validation, one read-only Git command
  (`git status --porcelain`, output discarded) was run by mistake, against the
  no-Git instruction. It changed nothing; no other Git command was run.
