# A knowledge library that shows its sources, and a demo that tells the truth

> Retrospective draft, prepared 2026-10-10. Not yet published. The reports cited
> here are dated 2026-10-09 and 2026-10-10; the original Library plan is
> undated.

By this point the project could store questions, interpret them, extract units
and organize them into Concepts. What it lacked was a way to read that knowledge
back — "what do I know about the subjunctive, and where did it come from?" — and
a short demo that someone else could follow. Building the library was
straightforward. Making the demo honest took three more rounds.

## A read-only library on top of existing authority

The Knowledge Library (FLH-034) adds a workbench tab and three GET endpoints. Its
service holds only read interfaces, so it cannot write. It invents no new
rules; everything it shows comes from authority that already existed:

- derived support;
- the current-membership projection;
- the effective annotation resolver;
- the provenance each extraction recorded.

**Search** is the smallest deterministic contract that works:

- case- and accent-insensitive keyword *prefix* matching over Concept identity
  and the wording of units currently filed under each Concept;
- identity matches ranked before wording matches, then active before orphaned;
- bounded results (20 by default, 50 at most).

There is no stemming, no synonyms and no semantic retrieval, and the
documentation lists those limits.

**The Concept page** puts every unit in exactly one section: currently
supporting, filed here but not supporting (with the reason), linked by a
relation, or history. **The source page** shows what the learner wrote and the
exact analysis and feedback the extraction used, so a later reinterpretation is
visible without rewriting provenance.

The demo seeds four synthetic records and seven Concepts through the public API
only, using a local stub extractor, so it needs no API key. A scripted browser
walkthrough checks every step and fails if the page sends any non-GET request.

## What independent acceptance found

A separate acceptance pass (FLH-035, 2026-10-09) ran the integrated demo and
found five defects. None was in the library's core contract, which passed its
checks. They were in the edges:

1. **Wording versus behaviour.** The plan said units from older extractions
   were not searched. In fact search correctly followed current membership,
   which includes such units, and result labels implied "current support".
2. **A loopback claim that was not true.** The demo said it was loopback-only,
   but the server listened on all interfaces.
3. **Duplicate React keys.** These appeared when one unit legitimately held two
   relations to the same Concept.
4. **`stop` trusted a raw PID.** Given a PID file pointing at an unrelated
   process, it would signal that process.
5. **Setup reported success after failing.** When the port was already taken,
   setup sent its seed requests to whatever was listening, the seed failed, and
   a `tee` pipeline hid the failure, so setup still exited 0.

## The fixes (FLH-036, 2026-10-09)

- **Search wording.** The search stayed the same and the documentation and
  labels changed to match it.
- **Binding.** The server gained an optional `LISTEN_HOST` setting. The default
  is unchanged, a hostname is rejected, and the demo binds `127.0.0.1`. The
  socket was then checked directly, not just the URL.
- **React keys.** Relation rows are keyed by their link id. A component test
  fails on React's duplicate-key warning without the fix.
- **Process ownership.** A process is identified by its PID, its kernel start
  time and its command line naming the demo directory. Linux uses `/proc` and
  macOS uses `ps` and `lsof`; other platforms are refused. A stale or reused
  PID is never signalled.
- **Setup failure.** Occupied ports are refused before anything launches, so the
  demo's seed requests never go to another program. Readiness counts only the
  started child's own loopback listener, and a failed seed exits non-zero and
  stops what setup started.

Each fix was exercised against task-owned sentinel processes and listeners on
macOS. A final Linux acceptance run (FLH-037, 2026-10-10) passed 84 probe
groups with no defects. That run did not include a real browser or a human
presentation, and the report says so instead of substituting automated timing.

## A demo people could actually follow

The owner then completed all six manual demo steps successfully, and reported
that the French grammar titles and explanations were hard to follow. That is a
usability finding, not a bug, and it changed the demo (FLH-038, 2026-10-10):

- Concept titles, explanations and the learner's questions became English,
  while every French example sentence and the useful French grammar terms were
  kept.
- The page explains membership versus support in plain words: a unit can be
  *filed under* a Concept without *currently supporting* it.
- No behaviour, API or search rule changed.

The English titles had to satisfy one more constraint. The existing acceptance
harness asserts exact search results on the demo data: browse order,
`déclencheur`, `vue d'ensemble`, and that `irreg` matches only through unit
wording. The titles were chosen, and two explanations reworded to avoid the word
"subject" (which prefix-matches `subj`), so that every one of those
expectations still held. That was checked by replaying the harness's searches
over HTTP; the Linux harness itself was not rerun in that task.

## What it does not claim

The library is not semantic search, has no index (each search scans all
Concepts, which is fine at personal scale), keeps no URL state, and does not
list DISTINCT pairs. Browser walkthroughs were run on macOS by the implementing
agent; the Linux acceptance covered HTTP, process and mocked-UI evidence. The
two-minute presentation was never formally timed.

## Sources in the repository

- `docs/ARCHITECTURE.md` §9, `docs/DEMO.md`
- `docs/history/06-knowledge-library-and-demo.md`
- `docs/plans/FLH-034-knowledge-library.md`, `docs/plans/FLH-036-knowledge-demo.md`,
  `docs/plans/FLH-038-english-demo-experience.md`
- `docs/validation/FLH-035-knowledge-library-acceptance.md`,
  `docs/validation/FLH-036-knowledge-demo.md`,
  `docs/validation/FLH-037-knowledge-demo-final.md`,
  `docs/validation/FLH-038-english-demo-experience.md`
