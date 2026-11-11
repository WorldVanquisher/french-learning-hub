# Endfield preview theme — validation

Owner: Claude Code (overnight stack, 2026-11-10 UTC). Presentation only: no
API, schema or stored-data change. Reference: the public design notes, tokens
and templates of `hhikr/endfield-ui-skill` at revision
`96702a36317b4c76538d1a20ed6beaae4e6067e2` (read only; it states no licence,
so nothing was copied). `Statrue/endfield-design-skill` at
`16f195e506612940da53a8679a45cac9de3ff9d2` (MIT) was listed but not needed.
No game art, logos, fonts or images are used; every face is a system font.

| Requirement | Evidence | Result |
|---|---|---|
| Selectable; the existing theme stays the default | `theme.test.tsx` (default, choose, remembered, unknown value, storage blocked) | pass |
| Never in the public demo | `theme.test.tsx` (no selector, attribute not set even with a stored choice) | pass |
| Every rule scoped; no `clip-path`, fonts or `url()`; reduced motion turns transitions off; focus ring rule present | `theme.test.tsx` reads `theme-endfield.css` | pass |
| Navigation, learning home, the seven sections and the exam flow; calm reading surfaces; French accents; readable Chinese; focus; reduced motion; 390 px without horizontal scroll | packaged Chromium on the assembled stack, en and zh-CN at 1360 and 390 px, with screenshots | see the overnight handoff's `START-HERE.md` |
| `NODE_OPTIONS=--no-experimental-webstorage make verify` | exit 0 | pass |

Design rules taken from the reference: paper and ink; one yellow signal used
only as a fill with ink text (current view, tags, timer, highlighter); no red
alarms (errors use an ink edge and a small yellow marker; SAME/INVALID keep
their colours in Concept Review); square corners with small cut corners on
actions; hairline rules; a dark command bar; a thin three-colour strip.
