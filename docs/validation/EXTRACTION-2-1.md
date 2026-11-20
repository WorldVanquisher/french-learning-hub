# Extraction 2.1: shorter path, second contrast, agent switching, Workbooks feed (2026-11-19)

PROTOTYPE on synthetic data. It follows `EXTRACTION-2.md` (items 111–136) and starts
from HANDOFF-136. Before editing, all 29 of its paths were checked unchanged against
its snapshot. Contract and commands: `tools/extraction/PRACTICE.md` §3, §4, §5, §7, §8.
Every number below comes from a command run in this slice. The raw outputs are in the
owner's sealed handoff `extraction2-20261119/handoff-2.1`, outside Git.

```sh
cd tools/extraction && python3 -B -m flh_extraction practice demo2 --out "$(mktemp -d)/demo" --check
```

## Status

| Asked for | State | Where |
|---|---|---|
| A shorter path from capture to first practice, keeping learner approval and evidence links | implemented and measured | `practice.py` batch review; `practice init / review / decide --approve-batch` |
| The same flow measured before and after on y/en | run (executed, not estimated) | `practice measure`; `expected2/01-steps.*` |
| A second French contrast | added: savoir vs connaître | `fixtures/practice_v1/savoir_connaitre.json` |
| Approve several claims and still spot an unsupported or revised one | implemented and tested | review "Decide yourself"; `expected2/02`, `03`, `04` |
| Agent switching worked example (Codex, learner, Claude Code) | verified offline with fixtures; **live sessions not run** | `PRACTICE.md` §8; `expected2/05`–`08` |
| Exact Codex and Claude Code smoke instructions | written | `PRACTICE.md` §8 |
| Sealed synthetic Workbooks feed and test cases | written and verified | `fixtures/practice_v1/workbooks/` (`verify.py`, `SHA256SUMS`) |
| Runnable demo and sealed handoff | done | `practice demo2 --check`; handoff `handoff-2.1` |

## Shorter path: measured before and after

`practice measure` runs both flows on the same source with the same intent: approve
every supported item and new practice example, and leave the rest. It counts the
commands executed.

| Source | Before | After | Checked equal in both flows |
|---|---|---|---|
| y/en, revision 1 | 9 | 3 | 6 approved items; 5 practice IDs; evidence links of all 5 exercises; one learner decision record per approved item |
| savoir/connaître, revision 1 | 9 | 3 | the same (6, 5, 5 of 5) |
| y/en, revision 2: practise again | 5 | 4 | the same 5 practice IDs return; the 2 changed items are still decided one by one |

**Where the saving comes from.**
- **The batch** saves 5 of the 6 steps: six `decide --item … --approve` commands become one `decide --approve-batch b-…`.
- **The preview** is the sixth step. HANDOFF-136 counted a separate `preview`, although its `init` already printed the draft. Its `init` now also prints the review, so the separate step is gone.
- **Revision 2** saves only that preview step. The changed items are never batched.

**What is preserved.**
- **Learner approval.** Every approved item still has its own decision record, written by the learner's single command. Each record holds the batch ID, the batch size and any items left out.
- **The batch ID binds what was shown.** It hashes the draft ID and each member's item hash, so it is refused after any other decision or revision ("review again").
- **Evidence links.** Each exercise keeps the same `evidence_ids` in both flows (5 of 5).

**Spotting.** The flagged item is named under "Decide yourself, one by one" and stays
pending:
- y/en `k-5ca79503ae78`: UNSUPPORTED, the quote « en goes with every verb of movement » is not in the learner's text;
- savoir/connaître `k-64cf5599890f`: UNSUPPORTED.

On revision 2, both items that cite the changed quote are shown as `CHANGED IN REVISION 2`.
Each shows: quote « Je viens de la boulangerie, j'en viens. »: located in revision 1 → not_found now.
Uncertain evidence (`en_quantite.json`) is never batched either.

## Second contrast: savoir vs connaître

**Draft.** 4 supported, 1 unsupported, 2 generated. The unsupported claim (« savoir »
is for people you know well) is rated `anchored` by the existing lexical heuristic,
and exact grounding flags it. This repeats the y/en finding on a second contrast.

**Practice.** explain 1, choose 2 (options « connais » / « sais »), produce 2; 4 are in
sentences not in the source.

**Grading examples:**
- « Oui, je le connais. » → correct (accepted variant);
- « Oui, je connais nager. » → incorrect (listed wrong answer);
- « Oui, je le connais bien. » → self_check (valid unlisted French);
- « conait » → invalid (not an option).

## Agent switching (offline, with fixtures)

The worked example is `PRACTICE.md` §8, and `demo2` runs it.

1. **Session 1.** Study packet `pk-e2920fe276cb` (v2) for Codex.
2. **Codex's return (fixture), previewed read-only.** `c1` is an accepted candidate; `c2`, the same correction, is a duplicate; `c3`, an exercise, is a candidate.
3. **The learner accepts `c1`.** Decision 8, `edit k-0d3281b28da6 via codex c1`. Accepting `c2` is refused as a duplicate, and so is `c1` a second time.
4. **A miss** on `p-664f7533a19d` (produce).
5. **Session 2.** Packet `pk-afdb387f3af6` (v2, `--previous pk-e2920fe276cb`) for Claude Code. Checked:
   - **Knowledge.** The same 6 knowledge IDs; the accepted wording with `accepted_from`; `continuity` names the change and the new miss.
   - **Last confusion.** « y » vs « en » on `p-664f7533a19d`, without the attempt text or the answer.
   - **Next exercise.** `p-8d5cabf2ab59`, produce, a different sentence; 0 of 9 answer keys are present.
6. **Claude Code's return (fixture).**
   - Its rewrite of the accepted correction is a `conflict`.
   - A correction to `k-40cbe73ae3f5` is an accepted candidate.
   - The packet's own next exercise is a `duplicate`.
   - An invented evidence ID is an `unknown_reference`.

**Empty-directory check.** Each session directory was copied into a new empty directory
with only the four files `export` writes. Each agent fixture was added as
`proposals.json`, and `import-preview` exited 0 in both directories.

**Not run:** a live Codex or Claude Code session. It is a real-agent call, so it is the
owner's smoke (commands in `PRACTICE.md` §8). Locally available: `codex-cli 0.170.0`
(`--sandbox`, `-C`) and `claude 2.1.327` (`[prompt]`), checked with `--help` only.

## Workbooks bundle

`fixtures/practice_v1/workbooks/` holds 14 files, sealed by `SHA256SUMS`, and is read-only for Workbooks.

**Feeds:**
- y/en revision 1: 5 items;
- y/en revision 2: 0 items, 5 `withdrawn`;
- y/en revision 2 re-approved: the same 5 practice IDs;
- savoir/connaître: 5 items.

**Attempt outcomes:** correct, incorrect, self_check, revealed and invalid.

**Cases:**
- **changed source:** the revision hash changes, revision 2 withdraws exactly the revision 1 IDs, and re-approval brings back the same IDs;
- **duplicate correction:** `c2` is classed `duplicate` and refused, and accepting `c1` leaves the feed byte-identical (practice IDs hash knowledge ID + kind);
- **study packet without answers:** 9 answer keys checked, 0 found.

**Verification:**
- `python3 verify.py` exits 0.
- The tests also tamper with copies: a `due_at` key, a broken seal and a leaked answer each make it exit 1.
- `practice workbooks-bundle --check` regenerates it byte for byte.

**Integration proposal (unchanged in substance from HANDOFF-136 §7).** Workbooks reads feeds; scheduling and schema stay theirs. New in 2.1:
- treat `withdrawn` as "stop offering, keep history";
- an ID that reappears resumes its history.

## Decisions (observed vs hypothesis)

- **D9: batch only supported items and generated examples. Observed:** the approved items, practice and evidence links are identical to one-by-one approval on two contrasts, and unsupported, uncertain and revised items are never batched. **Hypothesis H6, not measured:** learners still read each batched item before approving. One command for six items invites rubber-stamping; the learner trial (EXTRACTION-2 decisions §6) should log time spent on the review.
- **D10: packets never carry attempt texts or expected answers, in any mode.** `last_confusion` carries forms and IDs only. This is a design decision, not a result.
- **D11: `flh_next_exercise_rule_v1`.** After a miss, the same contrast in a different sentence, production first. **Hypothesis H7:** switching between the two forms in new sentences helps telling them apart. It is untested here, and the evidence below is mixed, so the rule is a default to test, not an evidence-based choice.
- **D12: practice IDs survive corrections and revisions. Observed:** accepting `c1` left the feed byte-identical, and re-approval in revision 2 restored the same IDs.
- **D13: an agent correction becomes knowledge only by the learner's `accept`,** recorded as an `edit` with provenance. A second agent cannot replace it (`conflict`).

### Research added in 2.1 (for H7)

| ID | Source | Population | Task | Outcome | A1/A2 applicability |
|---|---|---|---|---|---|
| R11 | Pan, Lovelett, Phun & Rickard (2019), *J. Applied Research in Memory and Cognition*, [10.1016/j.jarmac.2019.07.004](https://doi.org/10.1016/j.jarmac.2019.07.004); abstract and method read in the [author PDF](https://sc-pan.github.io/pdf/PLPR_2019.pdf) | English-speaking undergraduates with no prior Spanish (Exp. 1: 103 analysed) | conjugate Spanish verbs in the preterite vs the imperfect; test 48 h later | a random-only or a systematic-only interleaved schedule did not beat blocking (Exp. 1–2); systematic alternation for study plus random order for practice did (Exp. 3–4) | a Romance tense contrast for beginners is close to y/en, but the benefit depended on the schedule, and a single "next exercise" is not a schedule (assumption) |
| R12 | Nakata & Suzuki (2019), *Modern Language Journal* 103(3):629–647, 10.1111/modl.12581: **secondary summaries only**; the publisher page refused the request | reported: 115 Japanese learners of English | reported: 5 English grammar structures, blocked vs interleaved vs increasing | reported: interleaving helped grammar retention | not verified; not used as evidence until read |

## Friction points (measured or observed in this slice)

1. **One sitting, then decisions.** The review shows six items at once. The batch is fast, but the learner must still read them; nothing measures that (H6).
2. **Revised items still cost one step each.** That is deliberate, but a revision that touches many items will be slow.
3. **Only corrections can be accepted.** An agent's exercise proposal stays in the preview. Turning one into practice needs a decision on how a learner approves an exercise.
4. **The batch ID changes after any decision.** Exceptions must be given in the same command (`--except`); otherwise the learner reviews again.
5. **Long agent labels.** Proposal `agent` strings flow into `continuity`. The fixtures use `codex` and `claude-code` and keep the fixture note in a separate field.

## Validation (this run)

| Command | Outcome |
|---|---|
| `python3 -B -X dev -m unittest discover -s tests -t tests` (tools/extraction) | 143 run, OK (7 optional skips, 1 expected failure FLH-154 F1), 0 ResourceWarnings (126 before + 17 in `tests/test_practice_flow.py`) |
| `practice demo2 --out NEW --check` | exit 0: 13 outputs and the 14-file bundle equal the shipped files |
| `practice demo --out NEW --check` | exit 0: the HANDOFF-136 outputs are unchanged (the demo pins packet v1) |
| `practice workbooks-bundle --out NEW --check`; `python3 verify.py` | exit 0; `verify: OK` |
| `practice compare`; `evidence-review` on its fixture | identical to the HANDOFF-136 evidence |
| tools/speaking `run_tests.py -X dev` | 118 run, 28 skipped (dependencies), exit 0 |
| Packet privacy gate over 40 new or changed files; `lab privacy-check` over 32 | 0 findings; 0 findings |

## Owner decisions

- **Bulk approval in the product:** keep the batch (supported items and practice examples only) or require item-by-item (H6).
- **Workbooks adoption** of `withdrawn` and of the bundle's cases (their lane).
- **The live agent smoke** in both directions (`PRACTICE.md` §8).
- **Accepting agent exercises:** how a learner approves one.
- **A native-speaker check** of the savoir/connaître sentences (assumption A4).
- **Unchanged from HANDOFF-136:** persistence (migration) and a quote-emitting extractor (paid).
