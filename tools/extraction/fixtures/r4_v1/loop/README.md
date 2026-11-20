# Learning loop example (`flh_learning_loop_v1`, R4; synthetic)

| File | What it shows |
|---|---|
| `loop-keep.json` | attempt first: recall (wrong, `unaided`) → reveal → read → retry (right, `after_reveal`) → revisit after revision 2 (units changed, item withdrawn `knowledge_changed`, original evidence still verified) → revisit after revision 3 confirmed (units current, evidence moved, can practise) |
| `loop-discard.json` | the learner chose `discard` before answering: outcomes only, `answer: null`, `answer_withheld: learner_opt_out` |
| `loop-opt-out-later.json` | `keep`, then `discard`: the kept answer is removed and a `retention` event records it |
| `loop-read-first.json` | an explain item read before recall: the recall is labelled `after_reading` (experiment r4-retrieval-leakage, branch A) |
| `transcript.txt` | the four loops as text |
| `checks.json` | `loop.validate` on each, the evidence checks and the refused orders |

Contract and limits: `tools/extraction/LOOP.md`. Regenerate with `scripts/r4_loop.py --write`.
