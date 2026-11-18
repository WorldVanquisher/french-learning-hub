# Review sheet v1: how to fill `REVIEW_SHEET_V1.csv`

> **OFFLINE ONLY.** The sheet holds the 35 items of `review-sample-v1` (fixed; see
> `REVIEW_SAMPLE_V1.md` for the rubric and its examples). They are synthetic,
> machine-authored references with no model output and no learner data.

Open the CSV in a spreadsheet as UTF-8 with comma separators. There is one row per
reference unit (37 rows); a zero-unit item has a single row with `unit` 0. **Do
not edit, add, remove or reorder rows or columns.** The import refuses a sheet whose
fixed columns (`item` … `example`) changed.

| Group | Columns | Where | Question |
|---|---|---|---|
| A intent | `A_intent_decision_ok`, `A_intent_objectives_ok` (+ `missing` / `extra` text) | first row of the item | From the learner's text alone: is « units » vs « zero » right? Is the set of objectives right? |
| B evidence | `B_evidence_raised_by_learner`, `B_evidence_claim_true` | every unit row | Did the learner's text raise this objective (not only the explanation)? Is the statement true and not over-general? |
| C wording | `C_wording_canonical_ok`, `C_wording_zh_same`, `C_wording_example_ok` (+ `C_wording_fix`) | every unit row | Does the canonical name the objective? Does the Chinese say the same thing? Is the example correct French for this objective? |
| D verdict | `D_verdict`, `D_dispute_position`, `D_note`, `D_reviewer`, `D_date` | first row of the item | accept / edit / reject / quarantine |

Rules:

- **Answers.** Write `yes`, `no` or leave the cell blank.
- **Verdicts need answers.** A verdict needs its answers: `reject` and `quarantine`
  need A; `accept` and `edit` also need B and C for every unit. `edit` needs a fix
  or a note. A verdict with a blank answer is refused, never guessed.
- **Disputed items.** Rows whose `dispute` column starts with `OPEN DISPUTE` show
  the competing positions. Such an item counts only with `accept`, `edit` or
  `reject` **and** a written `D_dispute_position`. `quarantine` keeps it open.
- **Partial progress.** Leave `D_verdict` blank on items you have not finished;
  they import as `NO VERDICT` and are never counted.

```sh
cd tools/extraction
cp review/REVIEW_SHEET_V1.csv OUT/my-review.csv                          # fill the copy, keep the committed blank sheet
python3 -B -m flh_extraction review-sheet import --packet review/review-sample-v1.jsonl \
  --sheet OUT/my-review.csv --out OUT/review-sample-v1.filled.jsonl       # prints COUNTED / OPEN DISPUTE / NO VERDICT
python3 -B -m flh_extraction review-agreement --packet OUT/review-sample-v1.filled.jsonl --out OUT/review-agreement
```

The import writes a filled copy and never changes `review-sample-v1.jsonl`.
`review-agreement` reports intent, evidence and wording agreement as separate
numbers. Pass the filled copy, not the blank packet, to `decision-report --review`
and `experimental-report --review`. Both count only `COUNTED` items.
