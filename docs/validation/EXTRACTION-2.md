# Extraction 2.0 practice prototype: validation record (items 111–136, 2026-11-19)

PROTOTYPE on synthetic data. Contract and usage: `tools/extraction/PRACTICE.md`. Research
and decisions: `docs/plans/EXTRACTION-2-practice-decisions.md`. Every number below comes
from a command run in this batch; the sealed handoff holds the raw outputs.

## Status

| Items | State | Label | Where |
|---|---|---|---|
| 111–114 research, tools, exercise mix | done | online research; sources verified as stated per row | decisions §1–§3 |
| 115 audit of the current path | done | read from code and docs | decisions §4 |
| 116 decision record | done | observed vs hypothesis per decision | decisions §5 |
| 117–118 representation, origin, support | implemented | prototype | `flh_extraction/practice.py` |
| 119 draft preview with approve / reject / edit | implemented (CLI text preview; no web UI) | prototype | `practice init / preview / decide` |
| 120 stable drafts: replay, revision, carried correction | implemented and tested | prototype | `tests/test_practice.py` |
| 121–123 three practice types, hidden answers, variants and self-check | implemented and tested | prototype | `practice build / answer` |
| 124 y/en end-to-end demo | implemented | prototype | `practice demo --check` |
| 125–127 packets, preview, study and tutor modes, exclusions | implemented and tested | prototype | `flh_extraction/packet.py` |
| 128 Codex and Claude Code prompts | written | prototype | `tools/extraction/practice_prompts/` |
| 129 agent return format and read-only import preview | implemented and tested | prototype | `practice import-preview` |
| 130 handoff from an empty directory | format verified with a fixture; **live agent sessions not run** | owner-only smoke | below |
| 131 fixtures | done | synthetic | `fixtures/practice_v1/` |
| 132 side by side with existing extraction | run | counts, not quality | below |
| 133 learner trial | designed, not run | design only | decisions §6 |
| 134 Workbooks payload and contract | proposal | owner-review (Workbooks lane) | `PRACTICE.md` §7, `fixtures/practice_v1/expected/07-workbooks-feed.json` |
| 135 full sequence from one command; regressions | run | — | below |
| 136 sealed handoff | written | — | the owner's handoff directory, `extraction2-20261119/handoff-136` |

## 132: the prototype next to the existing extraction review

`python3 -B -m flh_extraction practice compare`. It runs on the same proposal for each
fixture and approves every supported or generated item:

| Fixture | Claims | New flow: supported / uncertain / unsupported | Existing `evidence_review` | Exercises tied to evidence (new / existing) | Steps to first practice (new / existing) |
|---|---|---|---|---|---|
| `y_en.r1.json` | 3 | 2 / 0 / 1 | anchored 3 | 5 / 0 | 9 / 6 |
| `y_en.r2.json` (revised) | 3 | 1 / 0 / 2 | anchored 3 | 0 / 0 | 7 / 6 |
| `en_quantite.json` | 3 | 1 / 2 / 0 | anchored 3 | 5 / 0 | 8 / 6 |

Findings:
- **Exact grounding vs lexical anchoring.** Lexical anchoring rates the unsupported claim "« en » goes with every verb of movement" as `anchored`, because the claim shares the words « en » and « vais » with the source. It also keeps rating a claim `anchored` after its quote disappears in revision 2. Exact-quote grounding catches both, but only when the proposer cites quotes. A claim with no quote is `no_evidence`, never `supported`.
- **No exercises before.** The existing path has no stored exercise. Recall Practice builds its questions in the browser from unit statements, and nothing ties them to evidence.
- **More steps.** The new flow needs more steps, because every approval is an explicit learner decision (see friction 1). The existing count does not include the provider call that extraction needs.

## 130: agent handoff from an empty scratch directory

- **Setup:** a new empty directory received only the four files `export --out` writes: `packet.md`, `packet.json`, `PROMPT-codex.md` and `PROMPT-claude-code.md`.
- **Stand-in reply:** `fixtures/practice_v1/agent_return.json` was copied in as `proposals.json`. It is a hand-written return; no agent wrote it.
- **Preview:** `practice import-preview --packet packet.json --proposals proposals.json`, run inside that directory, exited 0. Counts: accepted_candidate 3 (one flagged "cites no evidence"), duplicate 1, conflict 2, unknown_reference 1, invalid 1.
- **Not run:** a live Codex or Claude Code session. Both CLIs are installed (`codex-cli 0.170.0`, `claude 2.1.327`), but a live session is a real-agent call, and the owner controls those.

Owner smoke, from a fresh empty directory:

```sh
cp NEW_DIR/packet.md NEW_DIR/packet.json NEW_DIR/PROMPT-*.md . && codex --sandbox workspace-write "$(cat PROMPT-codex.md)"
# or: claude "$(cat PROMPT-claude-code.md)"
# answer a few questions, write "done", then:
python3 -B -m flh_extraction practice import-preview --packet packet.json --proposals proposals.json
```

What to record from the smoke:
- did the agent cite `ev-`/`k-` IDs;
- did it ask one question at a time;
- did it label claims "not in the packet";
- does `proposals.json` parse as `flh_agent_proposals_v1`.

## 135: full sequence and regressions (this run)

| Command | Outcome |
|---|---|
| `cd tools/extraction && python3 -B -m flh_extraction practice demo --out NEW --check` (clean directory) | exit 0; every one of 14 outputs equals the shipped expected file |
| `python3 -B -X dev -m unittest discover -s tests -t tests` (tools/extraction) | 126 run, OK (7 optional skips, 1 expected failure FLH-154 F1), 0 ResourceWarnings |
| `python3 -B -m flh_extraction evidence-review` (fixture A vs B) | exit 0; report identical to the lab-100 evidence |
| `cd tools/speaking && python3 -B -X dev scripts/run_tests.py` | 112 run, 28 skipped (dependencies), exit 0 |
| `lab demo --check`; `lab candidate-review-demo --out NEW --check` | exit 0; exit 0 |

The demo sequence (synthetic y/en):
1. capture `synthetic-y-en-001`;
2. draft `d-22ff0c49f9d7`: 4 supported, 1 unsupported, 2 generated;
3. the unsupported claim `k-5ca79503ae78` is rejected, `k-6c4760ebee9d` is corrected by the learner, and 5 items are approved;
4. practice: explain 1, choose 2, produce 2, four of them in new sentences;
5. answers: explain → self_check, choose → correct, « Oui, on y va ! » → correct (an alternate variant), « Oui, j'y reviens. » → incorrect (a listed wrong answer), one reveal;
6. study packet `pk-3cc014313f28` has no answer keys; tutor packet `pk-e6edb4e2ae2c` has rubrics, by explicit choice;
7. the agent return preview.

## Measured friction points

1. **One decision per item.** The first practice takes 9 steps for y/en, against 6 documented steps today. A bulk "approve every supported item" would cut that, but it weakens the explicit-decision rule. That is an owner decision.
2. **A changed quote blocks practice.** In revision 2 one changed quote reopens the claim and the contrast, so no practice can be built until the learner reviews them again (0 exercises).
3. **Exact grounding needs quotes.** It depends on the proposer citing exact quotes. Today's extractor (`knowledge_extraction_v2`) emits none, so a real proposer needs a contract change (owner, paid calls).
4. **Self-check is necessary but costs effort.** Valid unlisted French such as « Oui, on va y aller ce soir. » is a self-check, not correct. That is honest, but every unlisted answer costs the learner a judgment.
5. **Withheld examples are less readable.** Keyless packets withhold any worked example that is an exercise key, so the study packet shows those examples as questions only.
6. **No web view.** The preview is CLI text; the workbench is not changed in this lane.

## Owner decisions

- **Persistence.** Decisions, attempts and practice are files in a local work directory. Storing them in FLH needs a migration number and tables (schema owner).
- **A real proposer.** It means an extractor version that emits quotes, contrasts, worked examples and common errors. That is paid provider work, so the owner decides, and it means a contract change in `internal/extractor`.
- **Workbooks adoption.** The `flh_practice_review_feed_v1` source in Review Today, and whether attempt outcomes feed `NextRecommendation`, are the Workbooks lane's decision.
- **French check.** A native speaker should check every synthetic sentence (assumption A4).
- **Bulk approval:** whether to allow it (friction 1).
- **Agent smoke:** the live Codex and Claude Code runs (130).
