# Public demo performance claims: evidence and re-measurement (2026-11-19)

This record traces the performance statements made for the public demo. It
checks them against the retained artifacts and re-measures them. It
corrects two of them: the "about 60 % faster" wording, and the "first
example card" figure with its run count in the 2026-11-18 record. Earlier
validation records are kept as they were.

## 1. "Cold load about 60 % faster on a slow phone profile"

**Source.** The squash commit of the frontend batch (`dfb6742`, #152) used
that wording. It summarised item 50 of
[demo-refresh-frontend-speaking.md](demo-refresh-frontend-speaking.md):
"Time to render: −57 % (demo) and −64 % (workbench)". The cause was
server-side gzip of hashed assets. No current document, README or
`PUBLIC_DEMO.md` section carries the percentage.

**Raw data:** the lane handoff's `perf-before.json` and `perf-after.json`
(2026-11-17).
- **Runs:** 3 cold runs per route, before and after measured one after the
  other, not alternating.
- **Profile:** 390 px, 150 ms RTT, 1.6 Mbit/s, 4× CPU.
- **Not recorded:** the files name no URL or build. The package build
  times identify the builds:

| Side | Package | Tarball SHA-256 | Source label | Artifact |
|---|---|---|---|---|
| Before (no gzip) | `flh-public-demo-fe4-BLOCKED` (built 18:31, measured 18:32) | `3cf7e09d1d78fe80d6076da5d8c4b0da14e973008688f57b240a06007a4ecb35` | not kept (deleted at cleanup) | mechanical |
| After (gzip) | `flh-public-demo-fe5-BLOCKED` (built 18:36, measured 18:36) | `18d182ec84618f0a52baf4c5f4ee66e5d22f7c3db0fc7e13e699f5d3f20f2f76` | `198b23f1+demo-refresh-fe5` | `77d0502093f78a56`, manifest `9e9c4b44…` |

The workbench builds behind −64 % were served from the working tree,
never packaged or kept. That figure cannot be reproduced.

**What the data supports for the demo:**

| Metric | Before | After | Change |
|---|---|---|---|
| Rendered | 3,282 ms | 1,425 ms | −57 % |
| Ready | 3,880 ms | 2,091 ms | −46 % |
| Transferred | 573 KiB | 167 KiB | |

"60 % faster" mixes two applications, and it states a reduction in time
as a speed-up. A supported wording for the demo: "the time to render fell
by 57 %, from 3.3 s to 1.4 s".

**Re-measured on 2026-11-19 with the retained fe5 package, same build:**

| | Uncompressed (`Accept-Encoding: identity`, the state before the fix) | gzip |
|---|---|---|
| Rendered | 3,237 ms | 1,221 ms (−62 %) |
| Ready | 3,770 ms | 1,645 ms (−56 %) |
| First-visit bytes, plain HTTP count | 589,679 | 169,788 |

Timings: 5 runs per side, alternating, medians. The mechanism and its size
reproduce.

## 2. The 2026-11-18 pair, `d1118-base` → `d1118-final`

| | Base | Final |
|---|---|---|
| Package | `flh-public-demo-d1118-base` | `flh-public-demo-d1118-final` |
| Tarball SHA-256 | `1bdc99f071e170fcc15d3b9d6bba12aae6e7c550d038bb425b0e305782224d9a` | `dc4ec693377956168a69adea412f3a2c6c4d9d943575e781a05ac356a23581cc` |
| Source label | `tree-8837595eca0f` | `tree-77a5b85dc8b8` |
| Artifact (both) | `97dbe0f215af37e7`, manifest `1be0ebca…`, real-model vectors | same |
| Entry script | `/assets/index-Cs4qxe4J.js` | `/assets/index-9Vz1JoZF.js` |

**Three different metrics, kept apart.** Byte figures were checked with a
plain HTTP client, each response fetched with and without gzip:

| Metric | Base | Final | What it is |
|---|---|---|---|
| Entry script, asset size | 547,523 | 287,580 | Decoded file size. This is the "548 KB → 288 KB" figure |
| Entry script, transferred | 150,131 (client: 149,782 body + 297 headers) | 85,647 (85,314 + 297) | Bytes on the wire with gzip |
| First visit, transferred (page, script, style, demo read, Concept list) | 172,696 (client: 172,599) | 108,298 (client: 108,217) | All first-visit responses on the wire |

**Reconciliation.** "548 → 288 KB" (asset size) and "172,696 → 108,298
bytes" (transfer) describe the same two builds in different units of
account. The first-visit total fell by 64,398 bytes:

| Response | Change (bytes) |
|---|---|
| Entry script | −64,484 |
| Stylesheet | +85 |
| Page | +1 |
| **Total** | **−64,398** |

The script's transferred saving (−43 %) is smaller than its size saving
(−47 %), because text compresses well either way.

**Timing, 2026-11-19.**
- **Runs:** 9 cold runs per build, alternating run by run.
- **Profile:** Chromium 156, 390 px phone emulation, 150 ms RTT,
  1.6 Mbit/s down and 750 kbit/s up, 4× CPU, a new browser context per run.
- **Host load average:** 4.6–5.3.

| Median (range) | Base | Final |
|---|---|---|
| First contentful paint | 476 ms (456–520) | 488 ms (456–540) |
| Rendered (startup placeholder replaced) | 1,187 ms (1,166–1,237) | 884 ms (852–985) |
| First example card on screen | 1,597 ms (1,581–1,645) | 1,597 ms (1,109–1,674) |

**Supported:** rendering is about 0.3 s (25 %) sooner. **Not supported:**
any change in when the first example card appears, which waits for the
demo description read after rendering.

**Corrections to the 2026-11-18 record:**
- It says "medians of 7". Its files hold 5 runs per target, because the
  lane's runner did not pass the run count into the browser container.
- Its "first example card 1.84 → 1.66 s" (5 runs, load average 7.5–9.7)
  was not reproduced.

`PUBLIC_DEMO.md` now shows the 9-run series.

## 3. The packaged gate on the final package

**Run on 2026-11-19:** `check_package.sh … --suites matrix` on
`flh-public-demo-d1118-final` passed:

| Stage | Result |
|---|---|
| identity | passed |
| boundary | 24 smoke checks |
| live | passed |
| writes | 14 refused |
| browser (`accept_matrix`) | 1261/1261 checks, 312 screens |
| stop | package files unchanged |

**Not run on the final package:** `accept_paths`, `accept_guided`,
`accept_resilience`, `accept_a11y` and the FLH-076 acceptance (`--suites
all`). Each passed on candidate `d1118-c2`, which differs from the final
package only in `RELEASE.json`, `SHA256SUMS`, and the build id and entry
name inside `index.html` and the entry script. Binaries, artifact,
stylesheet and deploy files are byte-identical.

**Gate identity.** The live stage compared only the artifact (version,
manifest, model flag, fingerprint). Packages built from different trees
can share an artifact, and `d1118-base`, `-c2` and `-final` all do, so a
gate run could pass while another of them answered. It now also compares
the served page with `RELEASE.json` `web`: build id, entry script and
`index.html` SHA-256. Checked against running servers: with the final
package's `RELEASE.json`, the final server passes and the base server fails
on all three.

## 4. Real-E5 receipts and privacy

**Receipts.** The 2026-11-12 work directory and its copy are
byte-identical. With this tree, `prepare plan` is still `536021a4…`,
`prepare status` reports 23 of 23 positions and sends nothing, and
`prepare import` reproduces artifact `97dbe0f215af37e7`. The fingerprint,
`vectors.json`, `provenance.json` and `fixtures.json` are identical; only
`demo.db`'s migration timestamps differ. `validate -release` exits 0. No
embedding call was made.

**Privacy.** The measurement and evidence files hold no private host
address and no learner data. They were scanned for the embedding service's
host name and tailnet addresses: none found. The only test marker present
is the privacy crawl's random synthetic string. As FLH-076 designs it, the
host name exists only inside the package (`RELEASE.json`,
`artifact/provenance.json`) and the receipt state, and no public response
contains it.
