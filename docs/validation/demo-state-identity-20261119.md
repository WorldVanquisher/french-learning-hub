# Public demo search recovery and package identity (2026-11-19, items 051–060, 071–075)

Package `flh-public-demo-d1119-st75`, artifact `97dbe0f215af37e7`. Browser
checks: lane probe `state_probe.mjs`, a fresh context each, 6/6. Unit tests:
`web/src/demo/SearchState.test.tsx`.

## Search state and recovery (051–060)

| Item | Behaviour | Evidence |
|---|---|---|
| 051, 052 | A slow search (2 s) overtaken by a fast one: only the fast one's list, count ("1 concept matching “depuis”.") and address, also after the slow answer arrives. A load is keyed by mode, query, state, preset and limit, and a late answer is dropped (`useLoad`). The count and the "no match" line now name the query the server executed (`data.query`) | probe; unit test with a held answer |
| 053 | A failed search (503) keeps the last search that worked below the error, labelled "Below: the results of “remplace”, the last search that worked.", and still usable ("Why it matched" opens) | probe; unit test |
| 054 | The retry names what it runs ("Search “pass” again"). While a newer search is pending, only that one is shown, with no retry for the failed one | probe; unit test |
| 055 | A blank `q` (or one of spaces) is the start's empty search. Any other blank parameter (`#example=`, `#compare=`, `#state=`, `#mode=`, `#concept=`, `…&unit=`, `…&step=`) is a link cut short: the start opens with the notice. Before this change, `#example=` and `#compare=` opened the start silently | unit test |
| 056 | Percent-encoded, raw and decomposed (NFD) accents find the same Concepts (`marché`: 2). `+` is a space, `%2B` a plus. An encoded `&concept=1` stays inside the query. Every canonical address reads back as the same search | probe; unit test |
| 057 | The server's limits: at most 200 bytes of UTF-8 (an accented letter counts 2), 8 different words, and a word of two or more letters or digits. A refused search now names the limit ("“…” has 9 different words; the search uses at most 8…") and offers "Edit the search" (focus on the field) instead of a retry that cannot succeed | probe on the real server; unit test |
| 058 | A navigation sweep (44 requests: walkthrough, evidence, Back ×4, Forward ×2, comparison, card, source, reload, language, follow-up) makes only GETs, to `/`, its two assets and the read API | probe |
| 059 | The status filter survives the link and Back; Back focuses the result that was opened | unit test |
| 060 | Every invalid or stale link tried (`#concept=abc`, `#compare=`, `#example=nope`, `#q=x&state=`, `#concept=99999`, a missing unit) offers a way to a working example, and it opens | probe |

## Package identity and boundaries (071–075)

| Item | Result |
|---|---|
| 071 | `page_identity_cases.sh` on this package's gate capture: each of build id, entry script and `index.html` digest, wrong alone, fails on that field alone. An older `RELEASE.json` without `web` passes with "page=not recorded"; an empty or missing build meta fails. 7/7 as intended |
| 072 | A different server binary (from `d1118-final`) in a copy of this package, with the same artifact: **refused** by the identity stage (the package's own checksums differ). **With its `SHA256SUMS` regenerated**, the package agrees with itself and the gate **passes**. The gate's new `--expect-sums <digest>` (the SHA-256 of `SHA256SUMS`, now printed by `package.sh`) **refuses** it: "identity mismatch: SHA256SUMS digest … != expected …". The owner should pass `--expect-sums` (or rely on the tarball SHA-256 that `flh-release` requires) |
| 073 | All 118 routes the server source registers, probed at the root and under `/api` (236 probes). Only the allowlisted reads answer 200 (health, readiness, search, Concept, unit source, demo description, `/`). Every other GET is 404 and every write 405 |
| 074 | `privacy_crawl.py`: a random marker written to a stand-in private database, which the demo server is then started with. The marker is in none of 127 public responses. A search for it finds nothing. The embedding service's private host is in no response. The public script names no private route. 44 private routes are 404. Both databases are byte-identical afterwards. 8/8 |
| 075 | The gate's writes stage: 14 representative writes (`/captures`, `/entries`, `/concepts`, `/knowledge-library/concepts`, current-extraction PUT/DELETE, PATCH; root and `/api`) all 405, and the demo is unchanged. The route sweep refuses all 44 write routes, at the root and under `/api` |
