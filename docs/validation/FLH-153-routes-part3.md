# FLH-153 part 3: routes, state and slow responses (items 41–60, 2026-11-17)

**Release status: BLOCKED** (mechanical vectors). This continues
`FLH-153-packaged-demo-verification.md` and `FLH-153-first-visit-followup.md`
in the same worktree and on the same baseline.
- **Fixtures:** local only. Responses were held, failed or rewritten in the
  browser; the server and its data never changed.
- **Not done:** no external E5, no AWS change, no deployment.
- **Browser:** Chromium 156 against the packaged demo's own binary on
  loopback.
- **Waits:** no fixed sleep anywhere. A slow response is held by the probe
  and released on demand, and every wait is on a condition (item 49).

**Result:** no regression was found, so part 3 changes no code. It adds the
"Supported addresses" table to `docs/PUBLIC_DEMO.md` and this record.

## 41. Supported addresses

The page is `/` only. Screens are URL fragments, parsed by
`web/src/demo/deepLink.ts`. The table, the rules (IDs, queries, duplicates,
the canonical address) and what happens to anything else are in
`docs/PUBLIC_DEMO.md`, "Supported addresses".

The server side is the demo boundary
(`internal/transport/http/public_demo.go`):
- **Allowed:** GET and HEAD on `/`, `/assets/…`, `/healthz`, `/readyz`,
  `/knowledge-library/concepts`, `/knowledge-library/concepts/{id}`,
  `/knowledge-library/units/{id}/source` and
  `/knowledge-library/demo{,/semantic-search,/hybrid-search}`, at the root
  and under `/api`.
- **Refused:** every other path is 404, and every other method is 405.

## 42–43. Route and state matrix

Each address was opened in a new document, then:
1. reloaded;
2. one move made from it with the keyboard;
3. Back (recording focus) and Forward;
4. Back again, then Back out of the demo.

This ran at 390 px (phone emulation) and at 1280 px. The figures below are
from 1280 px; 390 px is identical (last column).

| Address | Opens | Focus on open | Reload | Move → | Back: screen, focus | Forward | Back out | 390 / 1280 |
|---|---|---|---|---|---|---|---|---|
| `/` | start | body | start, same address | example | start, `#demo-example-y-en` | example | yes | PASS / PASS |
| `#q=il+faut` | start | body | start, same address | concept | start, `#library-result-1` | concept | yes | PASS / PASS |
| `#q=il+faut&state=active` | start | body | start, same address | concept | start, `#library-result-1` | concept | yes | PASS / PASS |
| `#mode=hybrid&preset=il-faut-que` | start | body | start, same address | concept | start, `#library-result-1` | concept | yes | PASS / PASS |
| `#mode=semantic&preset=subjunctive` | start | body | start, same address | concept | start, `#library-result-12` | concept | yes | PASS / PASS |
| `#example=y-en` | example | h2 | example, same address | concept | example, `#demo-ex-open-concept-12` | concept | yes | PASS / PASS |
| `#concept=12` | concept | h2 | concept, same address | evidence | concept, `#library-source-preferred-12` | evidence | yes | PASS / PASS |
| `#concept=12&unit=12` | evidence | h2 | evidence, same address | concept | evidence, `#demo-source-concept` | concept | yes | PASS / PASS |
| `#example=y-en&concept=12` | concept | h2 | concept, same address | evidence | concept, `#library-source-preferred-12` | evidence | yes | PASS / PASS |
| `#example=y-en&concept=12&unit=12` | evidence | h2 | evidence, same address | concept | evidence, `#demo-source-concept` | concept | yes | PASS / PASS |
| `#q=il+faut&concept=1` | concept | h2 | concept, same address | evidence | concept, `#library-source-preferred-1` | evidence | yes | PASS / PASS |
| `#q=il+faut&concept=1&unit=1` | evidence | h2 | evidence, same address | concept | evidence, `#demo-source-concept` | concept | yes | PASS / PASS |
| `#mode=hybrid&preset=il-faut-que&concept=1` | concept | h2 | concept, same address | evidence | concept, `#library-source-preferred-1` | evidence | yes | PASS / PASS |

- **Focus on open:** a detail screen focuses its heading. A direct load of
  the start leaves focus where the browser puts it (`body`).
- **Back:** it always lands on the control used.
- **One miss on the first run** (not reproduced): at 390 px, Back to
  `#q=il+faut&concept=1` focused the heading instead of the source button.
  It did not recur in 8 targeted repeats (with and without a reload), nor in
  a second full run. The focus log shows the expected order: heading while
  loading, `popstate`, then the source button. The host's load average was
  about 8 on 8 cores. Recorded as unreproduced.

## 44–55. Results (`p3_probe.mjs` on the candidate: 125/125 on the second run)

| # | Check | Result |
|---|---|---|
| 44 | Refresh after Clear; refresh after a language switch | After Clear the address is `/`, and a reload keeps the cleared start (no query, every Concept listed). Back returns to the search Clear undid. On a search, an example, a Concept and evidence: switching to 简体中文 and reloading keeps the screen, the address and the language |
| 45 | An invalid evidence target | `#concept=12&unit=999999` and `#example=y-en&concept=12&unit=999999` show "not in this demo"; "Open the example …" opens a working example. `#concept=999999&unit=12` shows unit 12's evidence; its "← Back to concept #999999" leads to the missing Concept's screen, which offers an example. `#concept=12&unit=abc` and a 10-digit unit open the start with the malformed-link notice |
| 46 | A valid link while the backend is unavailable | With every `/api` request refused (connection refused) or answered 503, `#example=y-en&concept=12&unit=12`, `#q=il+faut&concept=1` and `#example=y-en` each show a message and a retry; the address is kept |
| 47 | Recovery | Once the backend answers again, one "Try again" reaches the linked screen: no reload, no editing of the address (6 of 6) |
| 49 | Slow responses without fixed sleeps | Used throughout: held routes, condition waits, animation frames |
| 50 | An older response never wins | A held "il faut" search, released after a newer "pronouns" search had answered, does not replace its results; the address and form stay on "pronouns". A Concept left while loading (held, then released) does not take over the Concept opened after it. `useLoad` drops a response whose key has changed |
| 51 | Status and focus while loading (en and 简体中文) | Example, Concept and evidence: while held, a status says it is loading and focus is on the screen heading. Once loaded, focus is on the heading |
| 52 | Focus after the evidence, keyboard only (390, 1280) | From evidence reached from an example, a Concept and a search, Shift+Tab to the return button and Enter land on the control used (step 4's button, the "View source record" used), and so does the browser's Back |
| 53 | The phone path with the on-screen keyboard open (emulated: the layout viewport shrinks to 508 px) | en and 简体中文: the field is in view while typing; after Search the first result is in view and focus stays in the field. With the keyboard closed, the path continues to the original record. Not checked on a real phone or with a real keyboard |
| 54 | Long addresses and labels (320, 390) | A 200-character query in the address: the Concept, its return button and the results fit. Nine-digit Concept, unit and record numbers in every evidence label ("View source record #999999999 for unit #999999999", "Where unit #999999999 came from: learning record #999999999") fit |
| 55 | Empty and error states, English vs Chinese (320, 390) | No match, empty catalog, search failed, demo unavailable, Concept failed, evidence failed, missing Concept, missing unit and malformed link all fit in both languages, with the same blocks and the same buttons |

## 56–57. Packaged gate on the final tree

Package `flh-public-demo-flh153-p3-final-BLOCKED`, built offline from the
final tree:

| Field | Value |
|---|---|
| Artifact | `77d0502093f78a56` |
| Manifest | `e57fcbf620b3f50fcfa6fd93c7005a80ef3c3f27a86ff87fb7f774c390808aa5` |
| Tarball SHA-256 | `ac542e6829d00f6541cd646f61bbd1854def64f760ccfbf3a3776a7764b02e4c` |

Part 3 changed documentation only, so every file except `RELEASE.json`,
`demo.db` and the manifest is byte-identical to the follow-up's candidate.

**`check_package.sh --suites all`:** exit 0.

| Stage | Result |
|---|---|
| identity | PASS |
| boundary | PASS (24 smoke checks: allowed reads 200, private routes 404, writes 405 at the root and under `/api`, counters, files unchanged) |
| live | PASS |
| writes | PASS: 14 well-formed writes refused, identity and counters unchanged |
| `demo_ux/accept_matrix.mjs` | 1267/1267 |
| `demo_refresh/accept_paths.mjs` | 112/112 |
| `demo_first_visit/accept_guided.mjs` | 208/208 |
| `demo_first_visit/accept_resilience.mjs` | 41/41 |
| `demo_first_visit/accept_a11y.mjs` | 107/107 |
| `flh076/browser/accept.mjs` | 37/37 |
| stop | PASS |

- **The first run** reported stop FAIL. A second server for the same package,
  started by this lane for the probe below, was still running. The gate
  named that process correctly. After stopping it, the run above passed.
- **Private-route and write probe** (`private_routes.sh`, on the same
  package): 118 of 118.
  - **Private routes:** 27 paths, at the root and under `/api`, answer 404.
    They cover entries, captures, Concept review, datasets, evaluation, the
    non-demo semantic and hybrid search, listening, reading, writing,
    speaking, exams, suggestions, admin, debug and `.env`.
  - **Allowed reads:** the 6 allowed reads answer 200.
  - **Writes:** POST, PUT, PATCH and DELETE on 6 paths answer 405.
  - **Pages:** `/` is 200; `/index.html`, `/workbench` and a deep path are
    404.
  - **Counters:** the demo's counters stayed at 0.

## 58. Mechanical versus real vectors

| Verified | With mechanical vectors (this lane) | With real vectors |
|---|---|---|
| Keyword search, examples, Concepts, evidence, links, history, focus, layout, states, the boundary and writes | yes: every check in the three FLH-153 records | not run: no CANDIDATE was built from this tree |
| Semantic and hybrid preset search mechanics (ranking shown, preset-only, re-checked against the demo database) | yes: links, Back/Forward, layout | not run here |
| Relevance of semantic and hybrid results | **no**: mechanical vectors are hashes of words, and the demo says so on every page | **not verified**: needs the owner's judgement on a real-vector candidate (`docs/PUBLIC_DEMO.md`, "Real-E5 candidate", "Then, by eye") |
| Real-vector artifact for this catalog | n/a | exists (owner-built 2026-11-12, version `97dbe0f215af37e7`, plan `536021a4…`). A copy validates as releasable with this tree's `flh-prepare` (`FLH-153-packaged-demo-verification.md` §17). Approval is not recorded |
| The release gate refuses a mechanical bundle | yes: `validate-release.sh` 3, a forged CANDIDATE 1, and the host installer refuses all three variants | the CANDIDATE path is not exercised by this lane |
| Live site | no | no |

## 59. Release note and the owner's local walkthrough

**Release note.** For visitors who arrive by a shared link or search first:
- **Links:** every supported address opens, reloads and survives Back and
  Forward. A link to something the build lacks offers a working example. A
  temporary backend failure recovers with one "Try again", without editing
  the address.
- **Search:** results appear right away, and a slow, earlier answer never
  replaces them.
- **Focus:** keyboard focus always lands somewhere useful.
- **Direction:** learner text in right-to-left scripts keeps its reading
  order.

The private workbench is unchanged. The demo still runs on mechanical
vectors and is not released until the owner approves real-model vectors.

**Local walkthrough for the owner** (about 5 minutes):
- **Run it:** the candidate package of `FLH-153-first-visit-followup.md` §37
  (tarball SHA-256 `a16ae948…`), served as in step 2 there on
  `127.0.0.1:18975`, in a 390 px window.
- **Steps:**
  1. Open `/`. Scroll to "Or search the library", type `il faut que`, press
     Search: the result shows at once.
  2. Open it, then "View source record #1 for unit #1": the original record.
  3. Copy the address, open it in a private window: the same record. Switch
     to 简体中文 and reload: same record.
  4. Press "← Back to concept #1" with the keyboard: focus is on the button
     you used.
  5. Stop the server, then open "concept #1" from the record: a clear
     error, the address kept, and "Try again". Start the server again and
     press "Try again": the Concept, with no address edit.
  6. Open `/#concept=12&unit=999999`: "not in this demo", then "Open the
     example …".
  7. Open `/#concept=abc`: the start says the link matched nothing.

## Validation commands (run here)

| Command | Result |
|---|---|
| `p3_probe.mjs` on the follow-up candidate | first run 121/125: 3 were probe waits (fixed) and 1 was the unreproduced focus miss of §42–43; second run 125/125 |
| the item-43 sequence repeated 8 times at 390 px (`dbg_43.mjs`) | 8/8 |
| `check_package.sh --suites all` on the part-3 package | exit 0 (§56–57) |
| `private_routes.sh` | 118/118 |
| `TMPDIR=<home volume> NODE_OPTIONS=--no-experimental-webstorage make verify` | exit 0: 24 Go packages ok, vitest 46 files / 502 tests, web build |
