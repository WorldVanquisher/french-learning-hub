# FLH-039 Documentation consolidation and development history

Owner: local Claude Code, sole documentation writer. Branch label supplied:
`docs/flh-039-documentation-consolidation`. No Git/GitHub command or subagent
was used. Production code, migrations, fixtures, manifests, historical task
reports and validation harnesses were not modified.

## Inventory before editing

| Category | Where it was | Problem |
| --- | --- | --- |
| Current setup and operations | README (quick start, configuration, running, release), QUICKSTART, RELEASE, DEMO, LOCAL_LEARNING_WORKFLOW.zh-CN, CAPTURE_PROMPT.zh-CN | Setup was repeated in README and QUICKSTART; QUICKSTART said the workbench had four views (it has five) and pointed to README for API examples and history |
| Current architecture and contracts | ARCHITECTURE (organized by milestone), README API section (about 1,100 lines), README FLH-029/FLH-034 sections, AGENTS.md | Most topics were explained twice (README API prose and ARCHITECTURE); ARCHITECTURE had no section on the browser boundary, workbench serving, `.env`, `LISTEN_HOST` or the Experiment Dashboard, and kept a first-milestone "Future possibilities" list |
| Historical milestones | README "Milestone history" paragraph (M1–M13-A1), milestone-titled ARCHITECTURE sections | History and current behaviour were interleaved; no dates are recorded for milestones |
| Validation evidence and limits | docs/plans/, docs/validation/ (dated 2026-10-07 to 2026-10-10 where stated) | No index; status words (delivered, merged, verified) used inconsistently across reports |
| Repeated, obsolete or contradictory | see "Inconsistencies" below | |

## Structure adopted

- `README.md` / `README.zh-CN.md` — companion entry points: problem, workflow,
  capabilities, non-goals, prerequisites, quick start, synthetic demo, release
  summary, configuration defaults, status, documentation map, layout,
  development commands, MIT license. No screenshot exists in the repository, so
  none is included.
- `docs/ARCHITECTURE.md` — canonical current design, one section per topic
  (§1–12), with the HTTP API reference as Appendix A.
- `docs/history/` — an index (status vocabulary, dated report table, undated
  milestone table) and six thematic narratives separating initial
  implementation, later corrections and current behaviour.
- `docs/blog/` — an index and five retrospective drafts.
- `LICENSE` — MIT, Copyright (c) 2026 Sirui Liu. No existing license or
  conflicting license statement was found.
- `docs/QUICKSTART.md` — factual correction (five workbench views, Knowledge
  Library bullet) and updated references.
- `AGENTS.md` — the "Documentation" list now names the canonical documents,
  history and blog directories.

RELEASE.md and DEMO.md were already canonical for their topics and were not
changed. Historical plans and validation reports were left in place, unedited.

## Relocation map

| Former location | Now |
| --- | --- |
| README v1.0 overview, core pipeline, capabilities | README (rewritten); pipeline detail in ARCHITECTURE §2 |
| README milestone history | docs/history/ (themes 1–3), README "Project status" summary |
| README layout, analyzer providers, configuration notes, running with `-web-dir`, health | ARCHITECTURE §2, §3.3, §10.1–10.2; defaults table also summarized in README |
| README API sections (entries … extraction, capture CLI usage) | ARCHITECTURE Appendix A.1–A.9 (duplicate semantic prose replaced by links to §3–5) |
| README research endpoints (M11-C … M13-A0) | Semantics in ARCHITECTURE §8 (already present); curl list in Appendix A.12 |
| README Experiment Dashboard (13-A1) | ARCHITECTURE §8.9 |
| README "Research and evaluation" caveat | ARCHITECTURE §8.8 |
| README FLH-029 recovery section | ARCHITECTURE §7.5 |
| README Knowledge Library section | ARCHITECTURE §9 and Appendix A.13 |
| README development commands, release summary | README (kept) |
| README knowledge-extraction "out of scope" list, ARCHITECTURE "Future possibilities" | ARCHITECTURE §12 |
| ARCHITECTURE milestone sections | Same text regrouped under topics §3–9; narrative openings rewritten to describe current behaviour |
| ARCHITECTURE concept API list | Appendix A.10 |
| Old README.zh-CN technical sections (Chinese translation of the API/architecture text) | Not translated into the new structure; the English canonical text in ARCHITECTURE preserves the content. The Chinese companion mirrors the new English README. |

A line-by-line comparison of the old ARCHITECTURE against the new one found
that every missing line was a rewritten narrative opening, the replaced search
bullets, the superseded FLH-029 UI paragraph, or the "Future possibilities"
list now summarized in §12. Old README lines absent from ARCHITECTURE are
either in the new README, in docs/history, or duplicates of canonical
ARCHITECTURE text.

## Inconsistencies found (not fixed here)

- `.env.example` does not list `LISTEN_HOST`, while documentation calls it the
  variable reference (file outside this task's ownership). ARCHITECTURE §10.2
  states the gap.
- `docs/plans/FLH-034-knowledge-library.md` still quotes the FLH-036 label
  wording ("member unit wording"), superseded by FLH-038's plain-English copy.
- `docs/plans/FLH-008-release.md` and `FLH-009-env.md` still say "awaiting
  review"; later reports (FLH-011, FLH-013) exercised them.
- `seed_demo.py` and `captures/` were undocumented; the READMEs now list them,
  noting that the script writes to the backend it is pointed at.
- Historical reports contain machine-local absolute paths (for example the NAS
  workspace). They are historical records and were not rewritten.
- `web/README.md` (outside ownership) still describes some behaviour per task
  label; it remains the workbench reference.

## Checks

Recorded in the handoff: Markdown link and anchor check over all repository
Markdown, README companion comparison, and verification of documented commands
against the Makefile, `demo.sh`, configuration code and Compose file.
