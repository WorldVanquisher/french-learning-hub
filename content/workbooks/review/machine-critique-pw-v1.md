# Machine critique: productive workbook v1

**What this is:** a machine review by the same model that wrote the material
(Claude Code, claude-opus-5-5, 2026-11-10). It is a self-review, not independent
expert validation. No teacher or native speaker has read the workbook.

## Method

1. **Gates** (`python3 -m flh_workbooks check`):
   - API limits;
   - sample word counts (re-counted in Go with `domain.CountWritingWords`);
   - coverage of every content point by an excerpt that occurs exactly once;
   - retry spans (unique, non-overlapping, applied cleanly);
   - Chinese present in every explanation;
   - telephone numbers in ranges reserved for fiction.
2. **Reading pass.** Every sample, every retry draft and its corrected text, and
   every practice item were read as they were written. The corrected drafts were
   also read after the corrections were applied automatically.

## Fixed during the pass

- **Two Chinese explanations had no Chinese text** (u02-g02, u03-g01). Rewritten.
- **One sample note quoted a phrase absent from its transcript** (u03). Re-anchored.
- **The u09 review contradicted itself:** "no parking", then "book a parking
  space". Now it advises the station car park.
- **One retry candidate was not an error and was not used.** « le concert a été
  génial » is correct French. The u07 draft uses « beaucoup des gens » instead.

## Known limits

- Samples are one possible answer each. They are not model answers for scoring,
  and the rubric gives no score or level.
- Several practice items accept more than one correct answer. Only the forms
  listed in `accepted` are recorded, and a teacher should accept other correct
  forms.
- Feminine forms are assumed in some answers (« me suis inscrite », « je suis
  allée »). The masculine forms are listed as accepted where relevant.
- The speaking tasks have no audio, and a transcript cannot show pronunciation.
- Level fit and naturalness have not been checked with learners.
