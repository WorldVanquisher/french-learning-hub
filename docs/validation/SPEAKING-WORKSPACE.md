# Speaking practice workspace (2026-11-19)

Synthetic fixture and fake microphone (jsdom); providers are fakes. Nothing stores audio.

| Item | What exists | Evidence |
|---|---|---|
| Resume from Review Today | A Speaking row's action is **Resume take N**. It opens the exercise at that take, with focus on it | `ReviewToday.test.tsx`; the walkthrough's "Resume take 1 lands on take 1" |
| Compare two takes | Two learner-selected confirmed transcripts, earlier → later (existing). It now says both answered the same stored prompt revision and its requirements: an exercise keeps the wording it was started with | `Speaking practice workspace` test 4 |
| Attribution | Each version says who wrote it: the machine transcript (transcriber) as confirmed, your correction, or typed. Feedback names its generator (existing) | test 1 |
| Edited spans | A corrected version shows your edits against the machine transcript, labelled "machine transcript:" and "your text:". The page says the comparison is text only and is not a pronunciation check or a score | test 1 |
| Missing audio or transcript | Each take lists what this page has: audio here (never stored), not here (choose the same file), or none (typed); and the transcript version or "none yet" | test 1, existing reattach test |
| First take kept during a second | In-page audio is kept per take. Recording, stopping and discarding a second take revokes only its own URL; take 1 keeps playing | test 2 |
| States with a next action | Every attempt state has a sentence: Next, In progress, Recoverable, Interrupted or Completed. The symbol beside the state is `aria-hidden`; the words carry the meaning | test 3 |
| Cancelled recording, then replay | Covered in test 2 | test 2 |
| Raw audio access | No audio in localStorage or sessionStorage. No request body carries audio bytes except the explicit, confirmed transcription request (existing test) | test 2; "records and plays back…" |

**Blocked (047), owner decision:** a personal correction (your transcript edit) cannot enter
Review Today. A notebook record needs a `source_ref` type, and
`learning_capture_sources.source_type` is a CHECK list (migration 019). A new
`speaking_transcript_edit` type needs a migration that rebuilds that table. It is also not
proposed as a capture without a source, because such a record never reaches Review Today.
Feedback improvements can already be saved (existing).

**Proposal for 047 (owner allocates the migration):**
- **Schema:** rebuild `learning_capture_sources` with `speaking_transcript_edit` added to the
  `source_type` CHECK list. `record_id` is the corrected transcript version's id; `item` is the
  1-based edited span in `DiffWords` order. The rebuild follows migration 021's pattern (same
  ids, foreign keys settled by statement order).
- **Resolver:** `MistakeSourceResolver` reads the version and the machine transcript (or the
  previous version), and refuses a span that no longer exists.
- **Forward:** existing rows are copied unchanged, and new rows appear only on an explicit
  "Practise this correction later".
- **Rollback:** restore the pre-upgrade backup (`docs/RELEASE.md`). An older build would reject
  the new type, so rows of that type are lost with the restore.
