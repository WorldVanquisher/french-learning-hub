# Public demo first visit, search evidence, bundle scope and real-E5 rebuild (2026-11-18)

Lane: demo-refresh (public demo, its packaged assets and browser evidence).
Behaviour: [PUBLIC_DEMO.md](../PUBLIC_DEMO.md), sections "First visit, search
evidence and a smaller bundle" and "Real-E5 candidate (owner only)".

The final package, `flh-public-demo-d1118-final`, was built before the last
edits to this file and to `PUBLIC_DEMO.md`. A package built from the tree
that contains this file, with the same label and artifact, is byte-identical
apart from `RELEASE.json`'s revision label and build time (and
`SHA256SUMS`, which covers it). The tarball checksum is recorded in the
lane's handoff. Everything below was measured on packages built from this
lane's working tree with the artifact rebuilt on 2026-11-18.

## Artifact (items 16–17)

| | Value |
|---|---|
| Catalog plan | `536021a4…` (23 positions: 14 Concept documents, 9 presets); unchanged since 2026-11-12 |
| Model | `multilingual-e5-base@d128750…/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff`, 768 dimensions |
| Receipts reused | One complete work directory from 2026-11-12: 23/23 valid receipts, 3 POSTs, 1 readiness probe. Copied read-only; `prepare status` showed nothing pending |
| Rebuild | `prepare import` with this tree; **no embedding call**. Migration ledger: 21 migrations, `001` … `021` |
| Result | artifact `97dbe0f215af37e7`, manifest `1be0ebca7502d5351be8bf6fd367142be9b636c0ba3cd320bb2f8f557b9e4f34`, domain fingerprint `8c06d309…`; `validate -release` exit 0 |
| Not reusable | The FLH-078/081/087 artifacts (plan `083a35ef…`, 20 positions, the catalog before the French examples) |

Packages built with this artifact are `CANDIDATE` (real-model vectors). They
carry the working tree's tree id as their revision label, so the owner
repackages from the committed tree (the same `import` and `package.sh`
commands, offline) before any deployment.

## Items

| # | Status | Evidence |
|---|---|---|
| 1 | Done | Fresh browser at 390 and 1280 px. Guided path: evidence in 2 taps; search-first path: 3 taps; no page errors. Six frictions listed in PUBLIC_DEMO.md, the first being cards that lead with labels instead of the French question |
| 2 | Done | Cards lead with the catalog question (`lang="fr"`); one-sentence lead; `GuidedExample.test.tsx` pins the wording to the catalog |
| 3 | Done | Step 3 shows that the Concept is now found by its keyword query, with marked words in the results |
| 4 | Done | "Found in {fields}: {words}" from `tokens` and `matched_fields`; a unit-wording variant; no unit text invented |
| 5 | Done | The malformed-link notice offers the first example. No-match searches already offered concrete searches |
| 6 | Covered | Links to a result, Concept and evidence panel already exist; the data contract has no finer anchor |
| 7 | Covered, verified | 7 link forms × 2 widths: open, reload, language switch, reload; Back ×3 and Forward ×3 across a language switch: 25/25 with item 8 |
| 8 | Covered, verified | 2 Tabs to the first example; heading focus on every new screen; focus returns to the "View source record" used, by the in-page back and by Back; `accept_a11y` 107/107 |
| 9 | Done | Evidence rows stack at ≤ 480 px; 0 overflow at 320 and 390 px in both languages |
| 10 | Done | 66 screens (11 × 3 widths × 2 languages), before and after: 0 overflow, 0 page errors, 0 raw message keys. The evidence screen names its Concept; the empty "Best explanation" panel is left out |
| 11 | Done | Entry script 95 % of first-visit bytes; catalogs about 64 % of it |
| 12 | Done | Demo builds keep 443 of 2,144 message keys and no workbench code.<br>• **Entry script:** 547,523 → 287,580 bytes raw; 150,131 → 85,647 bytes as sent.<br>• **Start, all first-visit responses:** 172,696 → 108,298 bytes.<br>• **Evidence deep link:** 175,000 → 112,535 bytes, including the new 1,933-byte Concept read.<br>Timings: 390 px, 150 ms RTT, 1.6 Mbit/s, 4× CPU, 7 cold runs per target alternating run by run, medians, load average 7.5–9.7:<br>• start rendered 1,274 → 961 ms; first example card 1,838 → 1,657 ms;<br>• evidence deep link ready 2,145 → 1,803 ms |
| 13 | Done | Baseline → final package through the repository's nginx TLS configuration, run locally:<br>• the final package passes 17/17: identity, assets from the cache on a second visit, deep links surviving reload, startup placeholder, failed bundle and API reads;<br>• headers: `index.html` `no-cache`; the hashed script `public, max-age=31536000, immutable`, gzip with `Vary`; a missing asset 404; the baseline's workbench chunk 404;<br>• a tab left open on the baseline showed the "newer version" notice when revisited, and Reload ran the final build and kept `#q=il+faut` (6/6) |
| 14 | Done | `accept_resilience` 41/41: slow, failed, out-of-order and empty reads; recovery in place. On the final package through the TLS edge, a slower earlier search ("être", 3 s) never replaced the later one ("subjonctif") |
| 15 | Done | Crawl with an isolated private database as `DB_PATH`. A random marker is in none of the 127 public responses, and neither is the embedding service's private host. 44 private routes → 404; 16 writes → 405; databases byte-identical afterwards. The baseline's script named private routes and the package served a workbench file; neither does now |
| 16–17 | Done | Above |
| 18 | Partly run | `check_package.sh --suites all` on the final package:<br>• identity, boundary (24 smoke checks), live and writes (14 refused) passed;<br>• the browser stage was stopped by Claude Code's handler for low host memory (not a failure) and was not restarted.<br>Each browser suite passed on the previous candidate, whose bundle differs from the final one only in its build-id string: matrix 1261, paths 108, guided 200, resilience 41, a11y 107, FLH-076 37. The rerun command is in the handoff |
| 19 | In the handoff | 60-second walkthrough with screenshots and these measurements |
| 20 | In the handoff | Revision, artifact identity, package checksum, gate results, deployment and rollback |

## Gate corrections

- **`check_package.sh`:** it now passes the vectors kind to
  `accept_guided.mjs`. Before, a CANDIDATE failed the guided suite, which
  waited for the mechanical notice.
- **FLH-076 `accept.mjs`:** the unit-wording label check ignores the case of
  "Concept".

## Tests

| Check | Result |
|---|---|
| `npx tsc -b --noEmit` | 0 |
| vitest, demo, i18n and pages | 32 files, 326 tests |
| `CatalogScope.test.ts` | 5 tests: graph scope, exact namespaces, unchanged text, refusal of unknown formats, the pinned `./App` import |
| `make verify` | exit 0: Go formatting, 24 packages, vet, four server builds, typecheck, vitest 55 files and 563 tests, workbench build |
