# Public demo performance after the discovery features (2026-11-19, items 061–070)

**Rules for this record:**
- Every number comes from this run.
- Every comparison holds everything constant except the builds compared. Each
  sample names its build and entry script, and each target reports its actual
  sample count (`check_runs.py`: RUNS CHECK PASS).
- A percentage is given only between two builds measured in the same run with
  the same tool and profile (070).

## First-visit bytes, six local packages (061, 062)

`bytes_check.py` (stdlib HTTP client, no browser) requests what the start
page loads: `/`, the page's assets, `/api/knowledge-library/demo` and the
Concept list. All six packages serve artifact `97dbe0f215af37e7`.

**Asset file sizes** (decoded, identity), in bytes:

| Package | Entry script | Stylesheet | `index.html` |
|---|---|---|---|
| `d1118-base` | 547,523 | 38,495 | 1,940 |
| `d1118-final` | 287,580 | 38,995 | 1,941 |
| `d1119-walk` (010) | 292,393 | 39,628 | 1,940 |
| `d1119-ev25` (025) | 316,211 | 42,380 | 1,940 |
| `d1119-ux50` (050) | 320,311 | 42,599 | 3,068 |
| `d1119-st75` (075) | 324,177 | 42,599 | 3,068 |

**Transferred** (gzip, as a browser asks), in bytes:

| Package | Entry script | Stylesheet | API (2 responses, uncompressed) | First-visit body total |
|---|---|---|---|---|
| `d1118-base` | 149,782 | 7,425 | 12,392 | 171,539 |
| `d1118-final` | 85,314 | 7,510 | 12,392 | 107,157 |
| `d1119-walk` | 86,694 | 7,607 | 12,392 | 108,633 |
| `d1119-ev25` | 92,533 | 7,970 | 12,392 | 114,835 |
| `d1119-ux50` | 93,606 | 8,005 | 12,392 | 117,071 |
| `d1119-st75` | 94,942 | 8,005 | 12,392 | 118,407 |

**From 010 to 075** (walkthrough package to this package): the entry script
grew 31,784 bytes (+10.9 %), 8,248 bytes gzip (+9.5 %); the first visit
transfers 9,774 more bytes (+9.0 %).

`index.html` grew 1,128 bytes with the expired-page message and its listener.
It is not compressed. Neither are the two API responses (the server gzips
only static files).

## Timing, interleaved (063–065)

**Profile:** Chromium 156; 390 × 844 phone emulation; 150 ms RTT; 1.6 Mbit/s
down and 750 kbit/s up; 4× CPU slowdown; a new browser context per run;
targets alternating run by run. Values are medians.

**Metrics, each measured separately:**
- first contentful paint;
- "rendered": the application has replaced the startup placeholder;
- "first card": the first example card is shown;
- KB transferred.

| Build (entry) | Runs | First paint | Rendered | First card | KB |
|---|---|---|---|---|---|
| `flh-public-demo-d1119-walk` (`index-CeuADGyM.js`) | 9 | 464 ms | 860 ms | 1,540 ms | 107 |
| `flh-public-demo-d1119-st75` (`index-BLIS-5Iu.js`) | 9 | 464 ms | 901 ms | 1,575 ms | 117 |

**Reading:** the walkthrough, evidence, comparison, suggested searches and
recovery features cost about 10 KB, and 35–41 ms before the first card, on
this profile. First paint is unchanged.

## What could be deferred (066)

Source-map attribution of the 075 entry script (`bundle_sources.mjs`):

| Source | Raw bytes | gzip (alone) | Deferrable? |
|---|---|---|---|
| react-dom | 129,418 | ~41,400 | no |
| `i18n/en.ts` | 42,438 | ~11,400 | no: the first visit is English |
| `pages/KnowledgeLibrary.tsx` | 41,641 | ~10,200 | no: the start screen |
| `i18n/zh-CN.ts` | 41,164 | ~12,300 | **yes**: only needed once 简体中文 is chosen |
| `pages/RecallPractice.tsx` | 11,517 | ~3,600 | yes: never offered in the demo, but bundled by a static import |

**The largest safely deferrable asset is the 简体中文 catalog.** Deferring it
changes how a stored 简体中文 preference starts (it would wait for one more
file, or show English first). That is an owner decision; it was not done here.

## One lazy-loaded element, measured (067, 068; optional prototype)

**Prototype:** the comparison screen loaded with `React.lazy` in a scratch
copy. It is handed off as `optional-patches/067-lazy-compare.diff`; the tree
is unchanged.
- **Size:** the entry script shrinks from 324,163 to 321,164 bytes; the
  5,283-byte comparison chunk loads only on that route.
- **Timing** (n = 5 each, interleaved, same profile): the start page's first
  card is at 1,574 vs 1,579 ms, and the comparison route is ready at 2,091
  vs 2,051 ms. Neither difference is outside run-to-run spread.
- **Recommendation:** do not merge. A 3 KB saving does not justify a second
  request on the route.
- **With the chunk unavailable (068):** the default visit works (examples,
  search, "Why it matched"). Opening a comparison says "This part of the demo
  could not be loaded. If the demo was just updated, reload the page…", and
  Reload recovers.

## Cold and warm visits (069)

Same profile, one context: a new tab for the second visit.

| Visit | First card | Bytes transferred | From the cache |
|---|---|---|---|
| Cold | 1,246 ms | 119,548 | nothing |
| Warm | 593 ms | 12,816 | both assets (disk). `/` revalidated (137 bytes) |

**Caching as served:**
- `/assets/*`: `public, max-age=31536000, immutable` (content-hashed names);
- `/`: `no-cache`;
- the API responses: no cache header, not compressed.

Those two API responses make up nearly all of the warm visit.

**Owner decision for a public deployment:** compress `application/json` at
the proxy (for example nginx `gzip_types application/json`). Measured with
gzip level 6 on the two responses, 12,392 bytes become 2,427. The warm visit
would then transfer about 2,851 bytes instead of 12,816.

## Percentages (070)

The only percentages above compare `d1119-walk` with `d1119-st75`, measured
in the same `bytes_check.py` run. The earlier percentages in
`demo-performance-evidence-20261119.md` were audited in that record against
matched builds and are unchanged. `PUBLIC_DEMO.md` carries no performance
percentage.
