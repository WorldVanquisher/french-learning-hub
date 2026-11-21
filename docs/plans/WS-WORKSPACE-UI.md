# Private workspace UI (2026-11-21)

Task notes for the private workbench's layout lane (queue UI-001–150). Owner of this file: the
workspace shell lane. Vocabulary's page is Workbooks' (`docs/plans/VOC-VOCABULARY.md`).

## What the workbench looks like now
- **Shell** (`web/src/workspace.tsx`, `web/src/workspace.css`).
  - At ≥ 1024 px: a sticky left rail with grouped sections (Start; Records and knowledge;
    Practice; Curation and research) in the unchanged tab order (`VIEW_GROUPS`,
    `workbenchViews.ts`).
  - Below 1024 px: a one-row section strip.
  - The section buttons, their `aria-pressed` state, `#/<view>` addresses and history are
    unchanged. Language stays at the top of the rail; a skip control is the first keyboard stop.
- **Theme.** Every workspace rule is scoped to `:root[data-shell="workspace"]`, which only the
  private `App` sets, and the stylesheet is imported by `workspace.tsx`. The public demo build
  therefore contains none of it and is byte-identical to before. Colours are tokens, dark by
  default and light under `prefers-color-scheme: light`; the opt-in Endfield theme keeps its own
  colours.
- **Records.** A record's source evidence (the learner's own words, quote-styled, with record
  and time) comes first in reading order. At ≥ 1180 px it is a sticky column beside the analysis
  and extraction.
  - Each extracted candidate has a title ("Candidate #N · kind") and a display-only state tag
    (`unitReviewState`).
  - The extraction says whether it came from a reviewed or an unreviewed analysis (its stored
    `source_feedback_id`).
- **Entry preview** (`web/src/portal.tsx`, `/?portal`, private server only).
  - It names the workflow and states that FLH has no accounts. "Open the private workspace"
    checks `GET /api/readyz` and opens `/#/home`; pending and failure are distinct states.
  - It links the public demo only when the build sets `VITE_FLH_PUBLIC_DEMO_URL` to an https
    URL.

## Behaviour added to the shell
- **Return focus.** After a cross-view "Back to …" (banner or browser Back), focus returns to the
  control the link was followed from, else to the section title.
- **Focus rescue** (`useFocusRescue`).
  - A removed focused control hands focus to its nearest surviving neighbour in the same
    container.
  - A control disabled while focused gets focus back when re-enabled.
  - Opt out with `data-focus-managed` on components that place focus after a re-read
    (`ExplicitAction`, Workbooks' `VocabularyBook`).
- **Scroll memory.** Each kept section keeps its scroll position; other sections open at the top.
- **Escape** closes the innermost open disclosure (`aria-expanded` toggle or `<details>`) and
  keeps focus on its toggle; text fields keep Escape.
- **Loading lines** in the record and review views are announced (`role=status`).
- **Records list.** "Show all records (clear the filters)" appears on an empty filtered result.

## Not changed
No route, API, schema or migration; no annotation semantics. The public demo, its fixtures and
`styles.css` are untouched. Open items stay out of the address (`sectionAddress.ts`).

## Validation
- Browser checks and their evidence: the lane handoff
  `~/flh-handoff/workspace-ui-20261121/` (`HANDOFF.md`, `REPLAY.md`).
- Final tree: `make verify` exit 0 (vitest 85 files / 817 tests); 199/199 browser checks.
- The Vocabulary section is mounted only after the owner combines the branches:
  `integrate_vocabulary.py` in that handoff.

## Proposed text for the shared docs (owner applies at integration; Workbooks also edits them)
- **`README.md` / `README.zh-CN.md`, workbench section:** "The private workbench opens with a
  section rail (a strip on phones), follows the system light/dark preference, and has a local
  entry preview at `/?portal`. Set `VITE_FLH_PUBLIC_DEMO_URL=https://…` at build time to link the
  public demo from it."
- **`docs/ARCHITECTURE.md`, frontend section:** the "What the workbench looks like now" and
  "Behaviour added to the shell" paragraphs above.
- **`CLAUDE.md`:** a "Workspace shell" entry alongside "Workbench theme" summarising the scoping
  (`data-shell`, the stylesheet travels with the workbench module), `data-focus-managed`, and
  `/?portal` (private only).
