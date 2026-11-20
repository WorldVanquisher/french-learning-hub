# Practice storage: the extraction lane's decision record (PROPOSAL, 2026-11-19)

This record answers the Workbooks lane's storage proposal (`workbooks-increment-4`,
`PRACTICE-STORAGE-DECISION.md`, status PROPOSED, option B: four append-only tables). It
changes no Workbooks file, adds no migration and allocates no number. `storage-proposed-0NN.sql`
in this bundle is a pinned copy of their SQL, with the SHA-256 of their document in its header.

```sh
python3 -I -B check_storage_rows.py     # in-memory SQLite only: their SQL as proposed, then amended
```

## 1. The proposal against the extraction contract (R2-061)

| Extraction record | Proposed table | Fits as proposed? | What is missing |
|---|---|---|---|
| learner decision (approve / reject / edit) | `practice_decisions` (`extraction_item`) | yes | the 2.2 context: `draft_id`, `material_hash`, batch membership, agent provenance (`via`), paraphrase attestation |
| agent exercise decision | `practice_decisions` | **no**: `subject_kind` allows only `extraction_item` and `notebook_draft` | a subject kind and the proposal's provenance |
| attempt or reveal | `practice_attempts` | yes | the matched variant or known error (recomputable only when the answer text is stored) |
| accepted agent correction | `practice_decisions` (edit) | partly | where the wording came from (`via`) |
| deferred items, personal corrections | `review_defers`, `personal_corrections` | not used by this lane | — |

**Proposed amendment.** Two changes before a migration number is allocated:
- add `agent_exercise` to `practice_decisions.subject_kind`;
- add one nullable column, `practice_decisions.provenance_json` (`AMENDMENT` in `storage_rt.py`).

No other table changes.

## 2. What must survive a browser reload (R2-062)

| Event | Today | Survives? | Idempotent? |
|---|---|---|---|
| learner decision | `decisions.jsonl` | must | no: a later decision on the same item is a new event; the latest wins |
| batch approval | one decision per member, with the batch | must | yes: the same batch ID writes only missing members |
| accepted agent correction | an edit with `via` | must | yes: a second accept is refused as a duplicate |
| exercise decision | `exercise-decisions.jsonl` | must | yes: keyed by (agent, packet, proposal) |
| attempt | `attempts.jsonl` | must | no: each attempt is intentionally new |
| reveal | `attempts.jsonl` | must | no: each reveal is intentionally new; never correct |
| exported packet | `packets/pk-….json` | should | yes: the ID hashes the content |
| drafts and sources per revision | `drafts/`, `sources/` | rebuildable | yes |
| practice, feeds | `practice.json`, written feeds | rebuildable | yes: a feed ID hashes the feed |

## 3. Cross-lane IDs (R2-063)

| Extraction ID | Column (amended proposal) |
|---|---|
| `k-…` item ID | `practice_decisions.subject_id` (`extraction_item`) |
| `item_hash` | `practice_decisions.item_hash` |
| revision SHA-256 | `source_revision_sha256` (the revision number is derived from the drafts) |
| `p-…` practice ID | `practice_attempts.practice_id`; `practice_decisions.subject_id` for `agent_exercise` |
| `material_hash`, `draft_id`, `b2-…` batch, `via`, attestation | `provenance_json` |
| `ev-…` evidence ID | not stored: rebuilt from the source; a moved quote gets a new ID |
| `pk-…` packet ID | not stored by Workbooks; kept in the extraction work directory |

`operation_key` is derived deterministically: a hash of the source, the record kind and its
sequence number. A resend of the same record is therefore refused by the UNIQUE constraint.

## 4. A revision arrives during an open review (R2-064)

**Rule: refuse and re-show, never merge.**
- A batch ID binds the draft and each member's item and material hashes. A revision changes the
  draft ID, so the open batch is refused ("review again").
- Decisions already written stay. Each one carries its `item_hash` and `material_hash`:
  - an unchanged item keeps its decision;
  - a materially changed item needs review;
  - an item that changed and came back needs confirmation (`awaiting_confirmation` in the feed).
- A half-applied batch resumes only on the same draft.

Tested: the acceptance matrix, and the `Approval` tests in `tests/test_practice22.py`.

## 5. Answer text (R2-066, R2-069)

**Export.** When the text is omitted (the default), an exported attempt has no `text` key and
carries `"text_omitted": true`:
- no hash or length is kept, because a short answer would be guessable from either;
- the outcome and the action stay.

Packets and feeds never carry attempt texts in any mode.

**Retention (proposal).**
- `answer_text` is stored only locally, and only if the owner chooses to store it at all.
- Deleting it is a redaction: a new row, or a null, recorded as the learner's action. The
  attempt's outcome history stays.
- Without the text, two things are lost:
  - the matched variant or known error cannot be recomputed;
  - the packet's "known confusion" link for that miss is lost.

  The round trip below shows both.

## 6. Retracted evidence in practice history (R2-068)

- When a revision removes the evidence an exercise rests on, the feed lists the practice ID under
  `withdrawn` with a reason code, in every later feed until it is offered again.
- Its earlier outcomes stay: they were recorded against the evidence of their own revision, and
  each attempt records that revision.
- The extraction history view (`storage_rt.history`) labels the item `retracted`, with the
  revision and reason. It never deletes it.

## 7. The round trip (R2-067, R2-070)

The rows come from this demo's à/en work directory: 10 learner decisions, 2 exercise decisions and
2 attempts, with the answer text stored.

| Variant | Refused by constraints | Fields with no column | Learner-visible differences after reading back |
|---|---|---|---|
| as proposed | 2 (both exercise decisions) | the 2.2 context of every decision, and the matched variant of each attempt | 5: the attestation and batch provenance disappear |
| amended | 0 | the matched variant or known error (recomputable from the stored text) | 0 |
| amended, without answer text | 0 | the matched variant or known error (gone) | 0 for knowledge states |

In both variants, a resend with the same `operation_key` is refused.

## 8. Owner decisions

- Adopt the amendment before a migration number is allocated, or keep exercise decisions local
  to the extraction lane.
- Whether `answer_text` is stored at all (the Workbooks proposal's default: yes, locally).
- Whether the extraction lane's JSONL moves into these tables, which needs this record's
  agreement. Until then the JSONL stays authoritative for the extraction prototype.
