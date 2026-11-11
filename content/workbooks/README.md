# FLH French workbooks (v1)

**Synthetic and unreviewed.** These are original practice materials written by
Claude Code (claude-opus-5-5) on 2026-11-10 in local authoring modules. No
provider or API generated them. No teacher or native speaker has reviewed them.
Levels (A2, B1) are authoring targets, not certified CEFR levels. Nothing here is
an official exam item. People, places and procedures are fictional unless a
notice says otherwise.

| File | What it is |
|---|---|
| `reading_listening_v1.json` | 12 units: one reading text and one listening **script** each, 20 questions per unit (240), vocabulary, follow-up |
| `productive_v1.json` | 12 units: a writing task and a speaking task, annotated samples, 6 grammar/vocabulary items, 3 common mistakes and a retry draft per unit; shared rubric (no score) |
| `adapters/` | The same content in formats the application already validates (see below) |
| `authoring/` | Source of truth: hand-written Python modules (`rl_units_*.py`, `pw_units_*.py`, `pw_rubric.py`, `wb.py`) |
| `review/` | Machine-critique notes: a self-review, not independent validation |

The JSON files and adapters are generated from `authoring/`. To change content,
edit the authoring module, then run `python3 -m flh_workbooks build` in
`tools/workbooks/`. `check` fails when a generated file is stale.

## Listening

The listening material is **written scripts**. There is no audio, no timestamp
and no evidence about listening quality. The line numbers `s1`, `s2`… point to
lines of the script, not to times. The production checklist
(`python3 -m flh_workbooks render`) lists what recording would require.

## Adapters and what the application accepts today

| Adapter | Status |
|---|---|
| `reading_learner_lessons_rl_v1.json` | Request bodies for the existing `POST /reading/lessons`. Each creates a learner lesson (passage only), and its paragraphs keep the workbook's `p1…pN` ids. |
| `reading_pack_workbook_rl_v1.json` | Valid `flh_reading_pack_v1` (Go `ParseReadingPack` test). **Not importable**: the server embeds only its own pack. Using it needs a deliberate pack change. |
| `writing_tasks_pw_v1.json` | Request bodies for the existing `POST /writing/tasks` (Go `NormalizeWritingTask` test). |
| `writing_prompts_workbook_pw_v1.json` | Valid `flh_writing_prompts_v1` (Go `ParseWritingPrompts` test). **Not embedded.** Each example draft is the unit's retry draft, which contains deliberate mistakes. |
| `speaking_prompts_workbook_pw_v1.json` | `flh_speaking_prompts_v1`, the format of the Speaking section. That section is not in this tree, so the file is only checked against it outside this patch. |
| Listening | **No adapter.** `POST /listening/materials` requires a YouTube link, and inventing one is not allowed. |
| Captures | `python3 -m flh_workbooks capture --question ID --text "…"` prints a `learning_capture_v1` (`source: manual`, no analysis) built around the learner's own question. |

Importing anything creates ordinary learner records. It implies no human
acceptance, no review and no mastery. Feedback, extraction and notebook entries
happen only through explicit learner actions.
