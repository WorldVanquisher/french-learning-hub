# Public demo browser UX (2026-11-19, items 041–050)

**Setup.** A packaged build of this tree (artifact `97dbe0f215af37e7`,
real-model vectors). Chromium 156, a fresh browser context per check. The
lane probe `ux_probe.mjs` is kept with the handoff. Timings are scripted and
local, so they are lower bounds for a person, not a user study.

## From a query to evidence (041, 042)

**The longest path**, with query `remplace`, whose match is only in a unit's
wording:

| Path | Actions after typing | Screens | Time (390 px / 1280 px) |
|---|---|---|---|
| Through the Concept: Search → open the result → "View source record" on the unit with that wording | 3 | results, Concept, source | 190 / 180 ms |
| Through "Why it matched": Search → "Show why it matched" | 2 | results | 110 / 116 ms |

**Confirmed unnecessary step:** opening the Concept screen. Both paths show
the same learner question with the matched words; the second one stays on
the results. The Concept and source screens are still one link away
("Open the source of unit #12 (record #9)").

## Focus (043, 044)

- **Closing the card:** the toggle button or Escape leaves focus on the
  toggle.
- **Back from a shared source link:** the in-page way back
  (`#q=remplace&concept=12&unit=12` → "Back to results") focuses the result
  for Concept #12. From a source opened from a comparison, it focuses the
  comparison's heading.
- **Reload:** a reload focuses the screen's heading: the comparison's h2, the
  source's h2, or the walkthrough step's h3.
- **Language change:** focus stays on the language control, and the open
  card and the address are kept.

## Large text and long French at 320 px (045)

**Reflow:** at 320 × 640 CSS px, with the WCAG 1.4.12 text-spacing overrides
applied (line height 1.5, letter spacing 0.12 em, word spacing 0.16 em,
paragraph spacing 2 em), six screens show:
- no horizontal scroll;
- nothing wider than the screen;
- no clipped control text.

The six screens are the start with the suggested searches open, results with
"Why it matched", the comparison, walkthrough step 4, a source, and a long
French query.

**Finding: text sizes are in px.** The browser's default font size setting
(16 → 32 px, CDP `Page.setFontSizes`) changes the root size but not the
demo's text: a hint stays at 12 px. The base styles size text in px (80
declarations in `web/src/styles.css`, shared with the workbench). Browser
zoom still enlarges everything, and the reflow above is what 400 % zoom of a
1280 px window gives.

**Owner decision:** convert the shared base styles to `rem`. That changes
the workbench too, so it was not done here.

**Long query:** a query of more than 8 words is refused by the server. See
item 057 for how the page now says so.

## Loading under a slow response (046)

With one route delayed by 1.5 s:
- **Search:** "Searching the knowledge library…" appears alone, with no stale
  results from the previous query, and disappears when the results arrive.
- **"Why it matched":** says "Loading why it matched…" until its Concept
  read arrives.
- **Comparison:** says "Loading the comparison…" until its sources arrive.

No change was needed.

## An expired cached page (047)

**Before:** a copy of the page whose entry script is no longer on the server
kept "Loading…", then after 8 s said the page "could not reach the server or
its files". The second part was inaccurate.

**Now:** the startup placeholder in `web/index.html` listens for a script or
stylesheet that fails to load, and at once says:
- "This copy of the page is out of date: a file it needs is no longer on the
  server, usually because the site was updated. Reload the page to get the
  current version."
- "此页面副本已过期：它需要的文件已不在服务器上，通常是因为网站已更新。请刷新页面以获取当前版本。"

**Probe:** the message is shown 66 ms after load, and a normal load shows no
placeholder. `index.html` is shared with the workbench, which gets the same
message.

## Links and actions (048) and the accessibility failure fixed (050)

**Audit, on seven screens:** every `<a>` has an `href`; no control is nested
in another; every link and button has a name; no link is a button in
disguise; one link name never leads to two addresses.

**Reproduced on the 025 package** (before the fix):
- "Open source record #9" → `…unit=12` and `…unit=13` (Why it matched);
- "Open source record #5" → `…unit=6` and `…unit=7` (comparison).

Two units of one record had links with the same name to different sources
(WCAG 2.4.4 / 2.4.9).

**Fix:** each link names its unit ("Open the source of unit #12 (record #9)",
"打开单元 #12 的来源（记录 #9）"). **Focused test:**
`web/src/demo/LinkNames.test.tsx`. The 050 package passes the audit.

## Reduced motion (049)

With `prefers-reduced-motion: reduce`, on the start, results with the card,
a walkthrough step change, and the comparison: no element animates or
transitions, and no scroll is smooth. The demo's CSS has no animation or
transition (`demoStyles.test.ts`). The startup placeholder's 0 s "animation"
is a timer for showing text, not motion.
