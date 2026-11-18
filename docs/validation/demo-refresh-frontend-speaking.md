# Frontend, delivery and Speaking experience: validation (demo-refresh lane, run 20261117T042813Z)

Design and research: [docs/plans/demo-refresh-frontend-speaking.md](../plans/demo-refresh-frontend-speaking.md).

**Status words:** implemented and verified; already covered (exercised, no
change needed); blocked (with the exact reason); deferred (with the reason).

**Browser:** Chromium 156.0.8078.79 in a Debian container (`node:22-bookworm-slim`
plus `chromium` and `fonts-noto-cjk`), playwright-core 1.49.1, loopback servers
only.

**Builds:** offline (`GOPROXY=off`, `GOFLAGS=-mod=readonly`).

## Handoff 1: discovery, design and frontend delivery (items 1–16)

| # | Item | Status | Result |
|---|---|---|---|
| 1 | Audit routes, components, build, deployment | done | plan §1. One Vite build makes two applications. The workbench has 12 views and had no address; the demo uses fragment links. Baseline bundles: workbench 766.60 kB JS (206.16 kB gzip), demo 460.27 kB (140.44 kB gzip). Hashed assets carried no `Cache-Control` |
| 2 | Highest-friction flows | done | plan §2: workbench reload or Back loses the section; blank page while loading and after a failed load; stale tabs; no microphone level; no match snippets; no remembered searches |
| 3–4 | Three products, with exact source links | done | plan §3: Common Voice `audio-web.ts` and `speak-error-content.tsx` (MPL-2.0, tree `605c25e4…`), DocSearch `stored-searches.ts` (MIT, tree `1412418c…`), the InstantSearch routing guide, Vite load-error handling, MDN `getUserMedia` exceptions |
| 5 | Visual direction | done | plan §4: keep panels, tabs, banners and the system font. Refinements: section titles, a current tab that does not rely on colour alone, a startup placeholder |
| 6 | Route map | done | plan §5: `#/<section>` for the workbench; the demo's fragment grammar is unchanged |
| 7 | First slice of the highest-value missing feature | implemented | **Workbench section addresses** (`web/src/sectionAddress.ts`, `App.tsx`): choosing a section pushes `#/<section>`; Back and Forward move between sections; reload reopens the section; an unknown fragment opens Concept Review and is corrected in place; the page title names the section. No storage and no request |
| 8 | Verify in a real browser | verified | 22/22 at 1280×900 and 390×844 (phone): open by address, reload, two sections add two entries, Back, Back, Forward (no new entry), unknown and plain addresses, no storage, GET only, no page errors. Unit tests: `SectionAddress.test.tsx` (6) |
| 9 | Inventory of AWS frontend hosting and proxy | done | plan §1: EC2 t4g.micro, Go server on loopback, SSM-only access; FLH-088 nginx TLS edge prepared, not applied; no CDN. Frontend and API ship in one package |
| 10 | Build with explicit staging API configuration | implemented | `vite.config.ts`: `VITE_FLH_API_BASE` (same-origin path only; anything else stops the build) and `VITE_FLH_BUILD_ID` (validated; `<meta name="flh-build">`, `<html data-flh-build>`). `package.sh` sets both and records `RELEASE.json` `web` |
| 11 | Deep-link reloads with the selected hosting | verified | Fragments need no server fallback. Through the HTTPS stand-in, `#q=…`, `#concept=N` and `#concept=N&unit=M` survive reload on desktop and phone, in 3 of 3 runs |
| 12 | Asset caching and versioned URLs | implemented | `NewWorkbenchHandler`: content-hashed `/assets/*` are `public, max-age=31536000, immutable`; other assets `no-cache`; a missing asset is never cacheable; `index.html` stays `no-cache`. Go test `TestWorkbench_AssetCachingPolicy`. Through nginx, the second visit loads 0 assets from the network |
| 13 | Stale frontend/API incompatibility | implemented | `web/src/freshness.tsx`: when a tab is shown again, or a lazy chunk fails, the page compares its entry script with `GET /`'s. On a difference it shows "A newer version … Reload" (the workbench text warns that memory-only drafts and audio are lost). It never reloads by itself. Verified in the browser across a fe2 → fe3 package swap; `Freshness.test.tsx` (5) |
| 14 | Startup loading state | implemented | `index.html`: a bilingual "Loading…" status inside `#root`; after 8 s it adds what to do. CSS only. Verified with a delayed bundle |
| 15 | Failed asset or API load and recovery | verified | Aborted bundle: the 8-second hint appears and a reload recovers. A 503 on the demo description shows the reason, and Try again recovers |
| 16 | Seal a browser-tested staging candidate and hosting instructions | sealed | `flh-public-demo-fe2-BLOCKED`: smoke passed; `validate-release.sh` exit 3 (mechanical, as designed). Handoff `STAGING.md`: owner paths for AWS, with the exact blockers (no budget; agents may not run AWS or Terraform; `IamHostRoleOnlyWithBoundary` and `S3CreateArtifactBucket` for another name prefix; package not CANDIDATE) |

## Handoff 2: learning, search and the Speaking recorder (items 17–32)

**Data and fixtures.**
- **Workbench data:** a workbench built from this tree with its own database,
  seeded through the public API only:
  - the FLH-034 seed with its stub extractor: 7 Concepts;
  - one authored Listening script, one Reading example, one Writing task with
    a draft, and one Speaking exercise.
- **Speaking providers:** a local fixture API on loopback (transcription and
  feedback). It uses the shared batch-5 fixture transcript, and every sentence
  it writes is labelled "Local fixture". Provenance:
  `openai:fixture-transcriber:speaking_transcription_v1` and
  `openai:local-fixture:speaking_feedback_v1`.
- **Shared fixture:** `speaking-take-001.wav` (3 s tone) was used for the file
  path.
- **Microphone:** Chromium's fake capture device (a synthetic tone).

| # | Item | Status | Result |
|---|---|---|---|
| 17 | Continue-learning entry point | implemented | `web/src/pages/ContinueLearning.tsx` on the learning home. Reads the four existing lists; per section it takes the newest item the learner started (`created_at`; a Listening lesson needs a transcript). Newest first, and each opens the item itself. A section that fails is named and the rest are shown. Nothing is stored. Browser: 4 items, newest first, Speaking opens the exercise, Back returns Home |
| 18 | Primary search action obvious | already covered, verified | The Search button is `.primary` (blue), next to the box, in view and at least 37–41 px tall at 1280 and 390 px. No change |
| 19 | Search filters on existing backend fields | covered and extended | The status filter is the backend's only filter field and was already there. Added the backend's `limit`: a truncated search offers "Show up to N" (at most 50) |
| 20 | Filters in shareable URLs | implemented | Workbench: `#/library?q=…&state=…`. Reload and bookmarks keep the search and status. Back/Forward and an edited address apply the search they name. Strict parsing: unknown or repeated parameters, or a query on another section, open the default. The demo's `#q=…&state=…` was already covered |
| 21 | Snippets showing why an entry matched | implemented | `web/src/pages/libraryHighlight.tsx`: the server's own `tokens` mark the matching words (prefix, case- and accent-insensitive) in a matched title, type or scope. Matched identity details are shown as "key: value" with marks. Unit-evidence matches keep their existing explanation; their text is not in the search response |
| 22 | Result → original source evidence | already covered, verified | Result → Concept → "Where unit #N came from: learning record #M" (original record) and back, at both widths |
| 23 | Recent searches with clear storage behaviour | implemented | `web/src/pages/recentSearches.ts` (after DocSearch `stored-searches.ts`): at most 5, newest first, a repeat moves to the front, per-item remove and clear-all. Stored only in `localStorage` (`flh.library.recent.v1`), with a note on the page; refused storage is stated. No request carries the list |
| 24 | Empty, loading, error and populated states | verified | Browser at 1280 and 390: loading ("Searching…"), populated (marks), empty (names the query), error 500 with Try again recovering, Continue loading and empty states (unit tests) |
| 25 | Speaking capabilities and contract | done | Speaking v1 (§4.7, A.19) as built. Batch-5 contract v1: additive API changes only; `web/src/pages/Speaking*`, `web/src/api/*` and `web/src/i18n/*` are shared frontend/learning-api anchors. The extraction speaking lane had published no checkpoint at this point. **No contract change was requested or needed** |
| 26 | Exercise selection with the supported task types | already covered, verified | Three authored prompts (`message vocal`, 30–90 s); Start or Open; Continue opens the started one |
| 27 | Microphone capability and permission feedback | implemented | Before recording, the Permissions API states allowed, will ask, or blocked (with what to do); unknown shows nothing. A **busy** microphone (`NotReadableError`/`AbortError`) has its own message. While recording, a **live input level** (`<meter>`) with a text equivalent ("Sound is reaching the microphone"), after Common Voice's volume meter |
| 28 | Start, stop, playback, re-record | already covered, verified | Real browser: 2.5 s recording, local playback (`currentTime` advanced), no request, discard and record again |
| 29 | Duration and size limits visible and enforced | already covered, verified | "At most 2:00 and 8.0 MB per take; stops by itself at 2:00"; the elapsed/max timer; file checks (type, size, duration). The shared WAV shows `0:03 · 94 KB · audio/wav` before saving |
| 30 | Upload and processing progress | fixed | Saving used to hide the recording and show only disabled buttons. Now it keeps the preview and says "Saving take N…" (also announced). Transcription and feedback keep their existing sending, in-progress and check-again states |
| 31 | Recovery: permission denial, failed upload, interrupted processing | fixed and verified | A failed save used to **discard the recording**; now it keeps it, and the retry saves it. A lost answer offers "Check whether it was saved", which re-reads the exercise and matches the take by its SHA-256, so it never saves twice. Browser: 500, then a lost response (saved once, found); transcription failure, lost transcription (explicit retry after an unknown outcome), success; denied permission keeps both fallbacks |
| 32 | Seal a browser-tested Speaking recording flow with a local fixture API | sealed | 16/16 browser checks (`speaking-probe.json`); unit tests `SpeakingRecorder.test.tsx` 9/9, `Speaking.test.tsx` 11/11 |

**Announcements (prepares item 47).** The recorder's elapsed time was inside a
live region updated every 200 ms. Now:
- the timer and the meter are visual only;
- one `aria-live="polite"` region announces recording started, stopped
  (silent or not) and saved.

## Handoff 3: Speaking feedback, visual and accessibility (items 33–48)

| # | Item | Status | Result |
|---|---|---|---|
| 33 | Transcript feedback in the agreed schema | already covered, verified | `speaking_feedback_v1` rendered from the local fixture API: task rating (not a score), clarity, grounded improvements with hints before the suggestion, and a "not found in this transcript" section. Real browser (`speaking-feedback-1280.png`) |
| 34 | Link feedback to a sentence or audio segment | covered for text; audio unsupported | "Show in version N" marks a `located` quote in that exact version (browser: keyboard Enter marks it). Audio segments are **not supported by the contract**: the transcription adapter reads only `text`, with no timestamps (§4.7). Nothing is invented |
| 35 | Uncertainty and unavailable scoring explicit | already covered, verified | "Based on the words of this transcript only: nothing here is about pronunciation"; "no score, mark or level"; ambiguous quotes are not shown as grounded; a failed or unknown request says so. New comparison caption: "Ratings are practice feedback, not scores" |
| 36 | Retry keeping the exercise context | implemented | A report offers "Record take N with these points in mind". The recorder, under the exercise's prompt, lists the report's grounded quotes with their categories, takes focus, and keeps them until the take is saved or "Hide these points". Page state only. `SpeakingFeedbackFlow.test.tsx`; browser keyboard path |
| 37 | Before/after comparison from available evidence | implemented | Beside the word diff, a table of recorded length (the browser's measurement), word count, task rating and points raised on each version's latest completed feedback. No derived score |
| 38 | Saved and unsaved recordings distinguishable | implemented | The preview carries a visible "Not saved yet" (or "Saving…") tag and the "Recorded take, not saved yet" group name. Saved takes are listed under Takes, and their detail says "Recorded here" while the audio is in memory |
| 39 | Retention and deletion at the relevant action | implemented | At "Use as take N": "Saving sends only the take's length, size, type and digest. The audio stays in this tab … until you reload or close it, and cannot be recovered after that." The transcription confirm panel already names the provider and "not stored on this server"; Discard removes the local recording |
| 40 | Fixture feedback labelled in demo mode | verified | Fixture output names `openai:local-fixture:speaking_feedback_v1` in the report, and every fixture sentence starts "Local fixture". Speaking is never in the public demo (existing test) |
| 41 | Typography, spacing, hierarchy | refined | Section titles in page titles; phone navigation compacted (below); Speaking comparison table; retry box; tags for unsaved state |
| 42 | Responsive navigation and active-route feedback | implemented | At ≤ 620 px the 12 sections are a two-column grid with 44 px targets: navigation height 298 px (was 12 full-width rows), so the section content starts on the first screen. The current section is bold with an inset bar, not colour alone (the Endfield theme keeps its own) |
| 43 | Keyboard access through recording and feedback | verified | Keyboard only, in a real browser: open exercise → Start recording → Stop → Use as take → Send audio… → Send audio → Confirm version → Request feedback → Show in version 1 → Record take N with these points in mind |
| 44 | Visible focus, predictable after navigation | implemented and verified | Focus ring present on all 10 actions reached. After Back/Forward to another section, focus goes to the section's title (`h1`, `tabIndex=-1`); after "with these points in mind", to the points box |
| 45 | Phone layout with the on-screen keyboard open | fixed | Viewport 390×420 with a field focused: the search box was partly under the keyboard. `web/src/keepFieldInView.ts` brings a focused text field into view (nearest) when the viewport shrinks. Re-run: search field and transcript field in view; Enter submits |
| 46 | Long French text and Chinese labels at narrow widths | verified | 简体中文 at 320 px: no horizontal overflow on all 12 sections; a 70-character French word wraps |
| 47 | Accessible audio controls and status announcements | implemented and verified | Every `<audio>` named ("Play back take N"); the level `<meter>` named "Input level" with a text equivalent. The timer is not a live region; one polite region announces started, stopped and saved |
| 48 | Screenshots and a short reviewer walkthrough | sealed | Handoff `REVIEWER-WALKTHROUGH.md` with screenshots from `evidence/item08`, `item10-15`, `item17-24`, `item25-40`, `item41-47` |

## Handoff 4: performance, deployment and final integration (items 49–64)

**Measurement profile:** a production build, a phone viewport, a cold browser
profile, 150 ms round trip, 1.6 Mbit/s down, a 4× CPU slowdown, the median of
3 runs. "Rendered" is when the application replaced the startup placeholder;
"ready" is when the route's content appeared.

| Route | Rendered before → after | Ready before → after | Transferred before → after |
|---|---|---|---|
| Public demo `/` (through the local HTTPS edge) | 3282 → 1425 ms | 3880 → 2091 ms | 573 → 167 KB |
| Workbench `#/home` | 4797 → 1722 ms | 5321 → 1977 ms | 874 → 217 KB |
| Workbench `#/library?q=subjonctif` | 4795 → 1736 ms | 5315 → 2465 ms | 875 → 220 KB |
| Workbench `#/speaking` | 4731 → 1676 ms | 5100 → 1895 ms | 875 → 217 KB |

| # | Item | Status | Result |
|---|---|---|---|
| 49 | Measure the main routes with the production build | done | Table above (`perf-before.json`, `perf-after.json`). Composition from source maps: the two i18n catalogs are 44 % of the demo's source and 22 % of the workbench's; react-dom is 129 KiB |
| 50 | Address the largest measured bottleneck | fixed | **Assets were sent uncompressed**, by the Go server and by the nginx edge (875 KB per cold workbench load). `NewWorkbenchHandler` now gzips hashed `.js`/`.css`/`.svg`/`.json` once in memory and serves them with `Content-Encoding: gzip` and `Vary: Accept-Encoding` when accepted (Go test `TestWorkbench_CompressesHashedTextAssets`). Time to render: −57 % (demo) and −64 % (workbench) |
| 51 | Lazy-load an expensive optional route | implemented | Mock Exam and Experiment Dashboard load on first use (`React.lazy` + `LazySection`, with a loading line and a reload message when the chunk is gone). Annotation Inspector stays in the main file because `UnitInspection` uses part of it. The split is modest (23 kB raw); compression was the real gain |
| 52 | Slow API responses and overlapping searches | verified | A 3-second search overtaken by a fast one: workbench and demo show the latest results, input and address; leaving Home during 2.5-second reads and returning gives a complete list with no error (`overlap-probe.json`) |
| 53 | Stale responses never replace the latest state | already covered, verified | The library's `useLoad` drops superseded responses (an active flag plus a key match); Continue and Speaking use the same pattern. No change needed |
| 54 | Deploy the isolated staging frontend within AWS authorization | **blocked** | No budget for new AWS resources in this run; agents may not run AWS or Terraform (AGENTS.md); a separate prefix is denied by `IamHostRoleOnlyWithBoundary` and `S3CreateArtifactBucket`; the package is BLOCKED (mechanical vectors), and `flh-release` installs only CANDIDATE with `real_model: true`. Exact owner commands: handoff `STAGING.md` |
| 55 | Verify HTTPS, routing, API connectivity, candidate identity | verified locally | The final candidate `fe6` behind the repository's own nginx TLS config (local stand-in, self-signed `staging.flh.test`): delivery probe 17/17; headers; identity `flh-public-demo-fe6-BLOCKED` in the page, `RELEASE.json` and the demo endpoint. On AWS: blocked (54) |
| 56 | Record deployment results and keep diagnostic logs | done | Local stand-in: nginx access log, server log per package (fe1–fe6), package build logs, header captures (handoff `evidence/`) |
| 57 | Public routes and read-only demo behaviour | verified | Packaged gate on `fe6`: identity, boundary (24 smoke checks), live, writes (14 refused), browser suites (see 59) |
| 58 | Private data and internal routes excluded from public output | verified | `fe6` with a private database holding a marker as `DB_PATH`: 197 public responses crawled (root and `/api`), marker found in none; `/speaking/*` and `/learning-records` 404; writes 405 |
| 59 | Packaged browser gate on the final candidate | passed (fe6 partly re-run) | `check_package.sh --suites all` passed in full on `fe5`: identity, boundary (24), live, writes (14), accept_matrix 1267/1267, accept_paths 112/112, accept_guided 208/208, accept_resilience 41/41, accept_a11y 107/107, FLH-076 acceptance 37/37. On the final `fe6`, the same command passed identity, boundary, live, writes, accept_matrix 1267/1267, accept_paths 112/112 and accept_guided 208/208. Claude Code then stopped it because the host ran critically low on memory (other workloads), and it was not restarted. `fe6` has the same server binaries, artifact and CSS as `fe5`; its JS differs only in the chunk graph (Annotation Inspector no longer split) and the build name. Re-run: handoff `START-HERE.md` |
| 60 | Fresh session, reload, Back, Forward | verified | The demo through the gate's suites (fresh profiles, links, Back/Forward); the workbench with the section-address probe (22/22) and the library probe (reload, Back) |
| 61 | Reproducible staging deployment and rollback commands | done | Handoff `STAGING.md`: local stand-in start, swap (rollback) and stop; owner AWS paths A (existing private host) and B (separate stack), with `flh-release rollback` |
| 62 | Resource usage; clean up temporary billable resources | done | AWS: none created. Local: the lane's processes stopped and its containers removed at the end (handoff `START-HERE.md`) |
| 63 | Seal frontend/API compatibility requirements | sealed | Handoff `COMPATIBILITY.md`: caching and compression headers, build inputs, API fields read, browser storage, owned files and shared anchors |
| 64 | Feature notes, browser evidence, next three improvements | delivered | Handoff `START-HERE.md` (final section) |

**Final re-runs on the final tree** (after handoff 4, the host under memory
pressure; lower test parallelism):
- `make verify`: exit 0, with Go `-p=2` and vitest 1–2 workers. Go
  formatting, tests (24 packages) and vet; builds; typecheck; vitest 54 files
  / 541 tests; production build. A first attempt with only a worker maximum
  set was refused by vitest's pool before running any test. One later full run
  had a 1-second timeout in `demo/Navigation.test.tsx` at load average 13–30;
  that file passed 3 of 3 times alone, and the full suite then passed 540/540.
- **Real-browser probes on the final workbench build:**
  - section addresses: 22/22;
  - library and continue: 28/28;
  - Speaking: 16/16;
  - accessibility and visual: 13/13. The handoff-3 note said 14/14: the probe
    has 13 checks, and all passed then too.
- **One product fix found by the final re-run:** while recording, the level
  text used the instantaneous level, so a pause after speech read "No sound is
  reaching the microphone yet". It now follows whether sound has been heard
  during this recording (unit test added). The meter still shows the live
  level.
