# Extraction lane interface notes (2026-11-21; one owner: the extraction lane)

Notes for other lanes about extraction outputs they may consume. Nothing here changes another lane's files.

## UI lane: review inbox (EXT-020)

There is no separate UI session; Workbooks owns the web prototype, so this note also went to Workbooks.

- **Contract:** `flh_review_inbox_v1` (`tools/extraction/UNITS.md` §5).
- **Example:** `tools/extraction/fixtures/xsubject_v1/expected/inbox/inbox-r2.json`. It is synthetic music theory in
  English and sealed in `expected/SHA256SUMS`.
- **Fields a UI needs:**
  - `to_review[]`: `unit_id`, `type`, `text`, `state`, `support`, `reasons[]` ({code, detail}), `evidence[]`
    ({evidence_id, status, quote, field, start, end}), `priority`;
  - `rejected[]`;
  - `reason_counts`;
  - `priority_order`.
- **Rules:**
  - show `reasons[].detail` as human text; key behaviour on `code` only;
  - treat an unknown code like `undecided`;
  - the full source text is never present.
- **Integration status:** pending, because no UI consumes the inbox yet.

## Vocabulary lane: reference fixture (EXT-049)

There is no Vocabulary session (ListAgents, 2026-11-21), so delivery to a live lane is blocked. The fixture is on disk:

- **Contract:** `flh_vocabulary_reference_v1` (`flh_extraction/units.py` `vocabulary_reference`).
- **Example:** `tools/extraction/fixtures/xsubject_v1/expected/vocabulary/terms-music-thirds.json` (synthetic, sealed).
- **Each entry:**
  - `term` and `value` from the claim's `canonical` (`TERM = VALUE`);
  - `definition`: the reviewed claim text;
  - `evidence[]`: evidence_id, evidence_key, field, start, end, quote;
  - `recall[]`: recall_id, kind, prompt; answers stay out of this file.
- **Rule:** only approved or corrected claims are included, and nothing is inferred.
- **Integration status:** pending until a Vocabulary lane exists.
