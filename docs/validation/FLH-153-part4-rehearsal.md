# FLH-153 part 4: first-visit rehearsal, a private marker, and a real backend failure (2026-11-17)

**Release status: BLOCKED** (mechanical vectors). Same worktree and baseline
as the other FLH-153 records.
- **Not done:** no external embedding call, no infrastructure change, no
  deployment.
- **No regression found;** part 4 changes no code.
- **Browser:** Chromium 156 (playwright-core 1.49.1) in a disposable
  container. Each session used a new persistent profile in an empty
  directory. Packages were served by their own `linux-amd64` binary on
  loopback.
- **Waits:** every wait was on a condition, never a fixed sleep.

## Candidate and fixture

| | Package | Tarball SHA-256 | Artifact | Manifest SHA-256 |
|---|---|---|---|---|
| Candidate (the final tree; first visit and shared link) | `flh-public-demo-flh153-p3-final-BLOCKED` | `ac542e6829d00f6541cd646f61bbd1854def64f760ccfbf3a3776a7764b02e4c` (verified before use) | `77d0502093f78a56` | `e57fcbf620b3f50fcfa6fd93c7005a80ef3c3f27a86ff87fb7f774c390808aa5` |
| Fixture package (privacy and failure checks) | `flh-public-demo-flh153-p4-fixture-BLOCKED` | `e0d962e3cf78223ad999be086aaa0eea119fc9325738698ad7f7e098f44d9f34` | `f4cc53d2b3c995c0` | `c55a079c1f42e0fc758acf0eabda1a0d1ff08745e085462efb197433db74004a` |

`validate-release.sh` reports BLOCKED (exit 3) for both.

**The fixture** (synthetic, outside Git; sealed in the lane handoff with its
generator):
- **Public source text.** The repository's catalog plus one entry whose
  original question begins with `FLH153P4-PUBLIC-SOURCE:` ("Pourquoi dit-on «
  je me souviens de cette journée » …"). It has one unit, "se souvenir de +
  nom", under a new Concept "se souvenir de" (Concept 15, unit 17).
- **Private marker.** A random `FLH153P4-PRIVATE-MARKER-<16 hex>`, placed only
  where the demo must never read it:
  1. an extra `private_note` field on that entry, in a second copy of the
     catalog;
  2. a file beside a copy of the artifact;
  3. a disposable database, written by the package's own server in normal
     (non-demo) mode, then given to the demo server as `DB_PATH`;
  4. the demo server's environment.

## First visit and shared link (candidate): 43/43

| Session | Result |
|---|---|
| Desktop 1280, clean profile | Landing (English, nothing stored) → search `pronouns` (the first example's query; the result is on screen and focus stays in the field) → "the pronouns y and en" (heading focused) → "View source record #9 for unit #12" (the original learning record) → Back ×3. Focus lands on the source button, then the result, then the empty search field |
| The evidence link, in a fresh profile | Opens the same evidence (heading focused, English); reload keeps it; switching to 简体中文 keeps the address, with the learner's French untranslated; a reload in 简体中文 keeps it. The in-page back twice reaches the link's Concept, then its search, focused on the result |
| Phone 390 and 320, keyboard | Tab to the search field, type, Enter: the result is on screen and the field keeps focus. Tab/Enter to the result and the source. The evidence offers two ways back ("← Back to concept #12", "← Back to results for “pronouns”"); each, with Shift+Tab and Enter, lands focus on the control used. Forward then Back keeps it (21 key presses in all). The shared link in a fresh profile, with the language switched by the keyboard (arrow key on the selector), survives a reload |

A checkpoint was sealed after these checks, before the fixture work.

## Private marker and public source (fixture package)

| Check | Result |
|---|---|
| Build a catalog carrying the private field | refused: `json: unknown field "private_note"`, exit 1, nothing written |
| Package an artifact with a private file beside it | refused: `unexpected artifact files: private-notes.txt`, no package written |
| The packaged output (18 files, 76 MB): every file, binaries included, and the decompressed tarball stream | marker: 0 occurrences; the public text is in `artifact/fixtures.json` and `artifact/demo.db` only |
| Every row of the artifact database | marker: 0 |
| Every supported public response at the root and under `/api` | 199 responses (191 × 200, 8 × 404 for IDs the build lacks); marker in none. The 8 searches for the marker itself found nothing, and only the visitor's own query was echoed back |
| What those 199 responses covered | at the root and under `/api`: demo info; health; 82 keyword searches (10 queries × 4 states, plus browsing); 15 Concepts each; 17 unit sources each; 18 semantic and 18 hybrid preset searches in all; and the page and its assets |
| The public source through the page (phone 390, clean profile) | search `souvenir` → "se souvenir de" → its original record shows `FLH153P4-PUBLIC-SOURCE…` |
| Marker in the page | absent from the DOM and from all 19 responses the browser received (apart from the echo of a search for it) |
| The private database given as `DB_PATH` | byte-identical before and after (SHA-256 unchanged) through three server restarts; no `-wal`, `-shm` or `-journal` file created; the server logs "DB_PATH not opened" |
| Supported write requests | `write_probe.sh`: 14 of 14 refused with 405, and the demo's identity and counters are unchanged |
| Private routes and methods | `private_routes.sh`: 118/118 (27 private paths 404 at the root and under `/api`, 6 reads 200, 4 write methods × 6 paths 405) |

## A real local backend failure (fixture package, phone 390, clean profile): 11/11 with the checks above

The probe stops the server process itself, then starts it again with the
same arguments.

| Case | Result |
|---|---|
| The server stops while the visitor is on the evidence; they open "concept #15" (keyboard) | An alert: "Could not load concept #15: no response from the server (network error)", with "Try again"; focus on the screen heading |
| The server is back; Tab once to "Try again", Enter | The Concept opens at the same address; browser Back returns to the same evidence, focused on the link used |
| The server is down when the visitor reloads the evidence | The browser's own error (`ERR_CONNECTION_REFUSED`); the address is kept. Once the server is back, a reload shows the same evidence |
| A new tab opened while the server is down | The browser's error page; once the server is back, its Reload reaches the same evidence |

No address was edited in any case.

## Mechanical versus real vectors

| Retrieval check | Vectors |
|---|---|
| All browser checks of part 4 (first visit, shared link, privacy, failure) | none: keyword search only |
| The crawl's 18 semantic and 18 hybrid preset searches (fixture package) | **mechanical** (`mechanical-test`, `flh073-mechanical-hash@1`, 64 dimensions). Their rankings are not semantic; only the absence of the marker and the response mechanics were checked |
| Real-model vectors | **not used** anywhere in part 4. Relevance is unverified |

## Commands

The exact commands are recorded and sealed in the lane handoff
(`firstvisit-command.txt`, `crawl-command.txt`, `privacy-command.txt`), with
their logs and JSON results. The lane tools (`p4_firstvisit.mjs`,
`p4_privacy.mjs`, `p4_crawl.py`, `p4_fixture.py`, `p4_privatedb.sh`,
`p4_serve.sh`, `private_routes.sh`) are sealed with them. The maintained
`scripts/validation/demo_candidate/write_probe.sh` was used unchanged.
