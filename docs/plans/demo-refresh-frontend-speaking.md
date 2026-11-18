# Frontend, delivery and Speaking experience (demo-refresh lane, run 20261117T042813Z)

This note records the discovery and design for the lane's frontend batch: what
the frontend is today, where it is hardest to use, the patterns taken from other
products, and the route map. The evidence for each delivered item is in
[docs/validation/demo-refresh-frontend-speaking.md](../validation/demo-refresh-frontend-speaking.md).

## 1. What exists (audit, items 1 and 9)

**Two applications from one Vite build** (`web/src/main.tsx`):

| Build | Entry | Served by | Where it runs |
|---|---|---|---|
| Workbench (default) | `App.tsx` | `cmd/server -web-dir` (`NewWorkbenchHandler`): `/` = `index.html` (`Cache-Control: no-cache`), `/assets/…`, API at the root and under `/api` | the owner's NAS (Compose, loopback, SSH tunnel); never public |
| Public demo (`VITE_FLH_PUBLIC_DEMO=1`) | `PublicDemoApp.tsx` | the same handler behind `NewPublicDemoBoundary` (GET/HEAD allowlist) | packaged by `scripts/demo/flh076/package.sh`; on AWS one t4g.micro (`deploy/aws`, `flh-release`), private over SSM; optional nginx TLS edge (`deploy/aws/host/flh-public-https`, FLH-088, prepared, not applied) |

**Routes.**
- Server paths: only `/` and `/assets/*` are pages; there is deliberately no SPA
  fallback. Every client address must therefore be a URL fragment.
- **Public demo**: fragment links (`web/src/demo/deepLink.ts`): `#q=…&state=…`,
  `#mode=semantic&preset=…`, `#example=…`, `#concept=N`, `#concept=N&unit=M`.
  Reload, Back and Forward work (FLH-150…153).
- **Workbench**: 12 views switched in component state (`workbenchViews.ts`):
  home, records, library, listening, reading, writing, speaking, notebook, exam,
  review, inspector, experiments. **No address at all**: a reload always opens
  Concept Review, Back leaves the application, and a section cannot be
  bookmarked.

**Build.**
- `make verify`: Go checks plus `tsc -b`, vitest and `vite build`.
- Dockerfile stage `web`: `npm ci`, `npm run build`.
- Demo packaging builds with `VITE_FLH_PUBLIC_DEMO=1`.
- No code splitting. Baseline production sizes (Vite 5.4.21, this worktree):

| Bundle | JS | JS gzip | CSS | CSS gzip |
|---|---|---|---|---|
| Workbench | 766.60 kB | 206.16 kB | 36.89 kB | 7.18 kB |
| Public demo | 460.27 kB | 140.44 kB | 36.89 kB | 7.18 kB |

**Caching.**
- `index.html` is `no-cache`.
- `/assets/*` (content-hashed names) carry **no `Cache-Control`**, so browsers
  fall back to heuristic freshness from `Last-Modified`.
- nginx (FLH-088) passes the upstream headers through.

**Startup.**
- `index.html` has an empty `#root`, so a visitor sees a blank page until the
  bundle has loaded and run.
- A failed bundle load leaves the page blank for good.

**Hosting inventory (item 9).**
- **Path:** EC2 `t4g.micro` (arm64), `flh-public-demo.service` binding
  127.0.0.1:18970, `HTTP_ALLOWED_HOSTS` empty. Access is through an SSM port
  forward only.
- **HTTPS (prepared, not applied):** nginx with Let's Encrypt, GET/HEAD only,
  10 r/s per address with a burst of 20, no-SNI handshake refusal, `nosniff`,
  `no-referrer`, `DENY` framing.
- **What is not there:** no CDN, no S3 website hosting, and no separate
  frontend host. The frontend is part of the release package and is installed
  atomically with the server by `flh-release`. That makes frontend/API skew
  impossible on the server side: one release holds both.
- **Where skew can still happen:** a browser tab that was opened before an
  upgrade and keeps running the old bundle.

## 2. Highest-friction flows (item 2)

Taken from the audit, from the FLH-150…153 browser evidence and from reading
each flow end to end:

1. **Workbench reload or Back** loses the section: you return to Concept Review,
   or leave the application. This is the most frequent daily friction.
2. **Blank page while the bundle loads**, and a permanently blank page if it
   fails. Nothing says what is happening or what to do.
3. **A tab left open across a release**: the old bundle keeps running against
   the new server, with nothing to say a newer version exists.
4. **Speaking**: nothing shows that the microphone actually hears you until you
   play the take back. A microphone held by another application is reported as
   a generic failure.
5. **Library results** say which field matched ("found in: scope") but not the
   matching words.
6. **Searches are not remembered**. The demo's address keeps the latest search
   only.

## 3. Products and interfaces studied (items 3 and 4)

**Mozilla Common Voice** (MPL-2.0), the recording page for speech donations.
Source: [common-voice/common-voice](https://github.com/common-voice/common-voice)
at tree `605c25e48f9fb87cb25ca794cb39bf91d3741f29`.
- **[`audio-web.ts`](https://github.com/common-voice/common-voice/blob/605c25e48f9fb87cb25ca794cb39bf91d3741f29/web/src/components/pages/contribution/speak/audio-web.ts)**:
  - maps `getUserMedia` failures to named states: `NotAllowedError` →
    `NOT_ALLOWED`, `NotFoundError` → `NO_MIC`, `OverconstrainedError` →
    `NO_SUPPORT`;
  - has `EMPTY_RECORDING`;
  - drives a live **volume callback** from an `AnalyserNode`;
  - asks for explicit `ideal` constraints (mono, echo cancellation, auto gain).
- **[`speak-error-content.tsx`](https://github.com/common-voice/common-voice/blob/605c25e48f9fb87cb25ca794cb39bf91d3741f29/web/src/components/pages/contribution/speak/speak-error-content.tsx)**:
  one message per error state, each with a recovery step.
- **Taken:**
  - a live input level while recording;
  - a "the take is silent" warning before saving;
  - a distinct message when the microphone is busy (`NotReadableError`, see
    [MDN `getUserMedia` exceptions](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia#exceptions)).
- **Not taken:** reloading the page to re-ask for permission. FLH keeps the file
  and typed fallbacks instead.

**Algolia DocSearch** (MIT), the documentation search modal.
Source: [algolia/docsearch](https://github.com/algolia/docsearch) at tree
`1412418c58fc2a404b2bd4b5c450f318579877dd`.
- **[`stored-searches.ts`](https://github.com/algolia/docsearch/blob/1412418c58fc2a404b2bd4b5c450f318579877dd/packages/docsearch-react/src/stored-searches.ts)**:
  - keeps **recent searches** in `localStorage` under one key;
  - de-duplicates them by moving a repeat to the front;
  - caps the list (`limit = 5`);
  - removes single items.
- **Taken:**
  - a small, capped, de-duplicated recent-search list stored only in this
    browser;
  - a remove control for each item and one that clears all;
  - a visible statement of where the list is kept.

**Algolia InstantSearch routing** (MIT;
[React routing guide](https://www.algolia.com/doc/guides/building-search-ui/going-further/routing-urls/react/)).
- It synchronises "UI state with the browser URL" so people can "copy the URL,
  and share it". The back and next buttons then "keep track of previous
  searches".
- It maps state explicitly with `stateToRoute`/`routeToState`.
- **Taken:** an explicit, validated mapping between the address and the view.
  The demo already does this for search. The workbench gets the same for its
  sections: one canonical fragment per section, parsed strictly, and anything
  unknown opens the default.

**Vite load-error handling**
([Building for Production → Load Error Handling](https://vite.dev/guide/build#load-error-handling)).
- Vite "emits `vite:preloadError` event when it fails to load dynamic
  imports", because a deployment may delete the previous deployment's assets.
- The guide's advice: set `Cache-Control: no-cache` on the HTML.
- **Taken:**
  - lazy chunks report a failed load as "a newer version is available", with a
    reload button, never an automatic reload loop;
  - the HTML stays `no-cache`;
  - hashed assets become long-lived (`immutable`).

## 4. Visual direction (item 5)

**Keep the existing product language.** The building blocks stay as they are:
- `.panel` cards;
- `.view-tabs` with `aria-pressed`;
- `.banner info|error` with roles;
- `.hint` secondary text;
- the system font stack;
- the opt-in Endfield theme (private workbench only).

The batch adds no new library, font or image.

**Refinements are limited to:**
- the current section's name in the page title, so history entries and
  bookmarks are readable;
- a visible current-tab state that does not rely on colour alone (an inset bar
  in addition to `aria-pressed`);
- a calm startup placeholder in the page's own colours, with a
  `prefers-reduced-motion` guard;
- a recording meter that is a plain bar with a text equivalent.

## 5. Route map (item 6)

Workbench addresses (fragments; the server never sees them):

| Address | Opens |
|---|---|
| (none), `#/review` | Concept Review (unchanged default) |
| `#/home` | Learning home |
| `#/records` · `#/library` · `#/listening` · `#/reading` · `#/writing` · `#/speaking` · `#/notebook` · `#/exam` · `#/inspector` · `#/experiments` | that section |

- **Inside a section**, a deeper address (an open Concept, lesson or take) is
  left to later slices. This first slice names sections only.
- **Cross-view "Back to …" banners** keep working as before. Browser Back
  returns to the previous section.
- **Public demo:** unchanged. The demo's fragment grammar (`deepLink.ts`)
  remains the only demo addressing.

The learning, search and Speaking routes in daily use are:
- **Learning:** `#/home`, then the chosen section.
- **Search:** `#/library`, or, in the demo, `#q=…`.
- **Speaking:** `#/speaking`, then an exercise, then a take, then a confirmed
  version, then feedback.

## 6. First slice (items 7 and 8)

**Workbench section addresses.**
- Choosing a section pushes `#/<section>`.
- Back and Forward move between sections, and a reload reopens the section.
- An unknown fragment opens the default section and corrects the address.
- **Kept state:** state that views keep only in memory (a mounted view's
  filters, recorded audio) stays as it was. A reload still discards it, as
  before.
- **Unchanged:**
  - the default view;
  - the cross-view banners;
  - every API call;
  - storage: the address is the only new state, and nothing is written to
    browser storage.
