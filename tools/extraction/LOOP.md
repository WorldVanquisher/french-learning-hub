# Learning loop and agent exchange (R4; PROTOTYPE, offline, synthetic)

Two small contracts connect reviewed, evidence-grounded knowledge to practice and to
Claude Code / Codex sessions. Both are standard-library Python in `flh_extraction/`.

**Out of scope.** They do not touch FLH's database, routes or providers. They schedule
nothing, score no mastery and call no model.

**Data.** Every example is synthetic. The French needs a native-speaker check before learner use.

| Contract | Module | Fixture (regenerate / check) |
|---|---|---|
| `flh_learning_loop_v1` | `loop.py` | `fixtures/r4_v1/loop/` (`scripts/r4_loop.py --write` / `--check`) |
| `flh_agent_context_v1`, `flh_agent_corrections_v1` | `exchange.py` | `fixtures/r4_v1/exchange/` (`scripts/r4_exchange.py --write` / `--check`) |

## 1. Learning loop (`flh_learning_loop_v1`)

One learner's loop over one practice item.

```json
{"schema": "flh_learning_loop_v1", "loop_id": "lp-…", "session": "<caller label, e.g. a UUID>",
 "retention": "keep | discard",
 "pointer": {"practice_id": "p-…", "kind": "explain | choose | produce", "unit_ids": ["k-…"],
             "evidence": [{"evidence_id": "ev-…", "source_id": "…", "source_revision": 1, "field": "original_context",
                           "start": 25, "end": 50, "quote": "…"}],
             "source": {"source_id": "…", "revision": 1, "revision_sha256": "…"}},
 "events": [{"seq": 1, "event": "read", …}, …]}
```

### Events

Events are append-only, numbered 1, 2, 3, … in order.

| Event | Records | Order rule |
|---|---|---|
| `read` | each unit (state, approved or corrected text) and each evidence entry sliced from the learner's own source text, with `verified` | any time |
| `recall` | `outcome` (practice grading: exact for choose, accepted variants else self-check for produce, self-check for explain), `retrieval` (`unaided`, or `after_reading` when this loop showed the units first) and the answer, or `null` | before any reveal |
| `reveal` | the reference answer and explanation, the evidence again, `after_recall` | any time; without a recall it is recorded as such |
| `retry` | as recall, with `retrieval: after_reveal` | after a reveal |
| `revisit` | the pointer re-checked against the **current** review: each unit `current`, `changed`, `rejected` or `absent`; each evidence quote `current`, `moved` (with its new location) or `absent`; the practice item `offered` or `withdrawn` with the feed's reason code; the original evidence again; `can_practise` | after a recall or a reveal; learner-started, never scheduled |
| `retention` | the learner's new choice and how many kept answers it removed | any time |

**Attempt first (R4 experiment `r4-retrieval-leakage`, branch A).** In the pre-registered run,
the `read` view showed the full reference answer for all 4 explain items (M2 = 0.20 of 20
items; no prompt leaked its answer, M1 = 0).

`loop.next_step` therefore offers:
1. recall;
2. reveal;
3. read;
4. retry, and later revisit.

A recall after a read is kept but labelled `after_reading`; it is never counted as unaided.
`validate` refuses an `unaided` recall that follows a read.

Pre-registration and result: `experiments/r4-retrieval-leakage.{prereg,result}.json`.

### The pointer (R4-EXT-027)

`loop.pointer` refuses an item whose units are not approved or corrected. Each evidence entry
keeps the revision it was located in.

`loop.resolve` slices that revision's own text at `[start, end)`:
- it returns the excerpt only when the words there are still the quote (`verified`);
- the learner can always go back to what they wrote, even after later revisions.

The `revisit` check finds a quote by field and words in the current review. A moved quote is
reported with its new evidence ID and offsets.

### Answer retention (R4-EXT-028)

| Setting | What is stored |
|---|---|
| `keep` (default, as practice attempts today) | the answer text |
| `discard` | `answer: null` and `answer_withheld: "learner_opt_out"`; grading happens in memory before the text is dropped |

`set_retention(loop, "discard")` later removes every kept answer. It adds a `retention` event
with the count; no text is kept anywhere in the document. `validate` refuses a `discard` loop
that still holds an answer.

**Feeds never carry answer texts** in either mode, and service requests need outcomes only.

### Example and known limits (R4-EXT-029, R4-EXT-030)

`fixtures/r4_v1/loop/loop-keep.json`, on the y/en source:
1. attempt first: recall (wrong, `unaided`), reveal, read, retry (right, `after_reveal`);
2. revision 2: a revisit finds one unit changed and the item withdrawn with
   `knowledge_changed`, while the revision-1 evidence is still verified;
3. revision 3 confirmed: a revisit finds both units current, the evidence moved, and the item
   can be practised again.

`loop-discard.json` and `loop-opt-out-later.json` show retention. `loop-read-first.json` shows an
explain item read before recall, so the recall is labelled `after_reading`.

Known limits:
- One item per loop. A session over several items is several loops: the caller groups them.
- No schedule, interval, due date or mastery score. A revisit is the learner's action.
- `explain` is a self-check; `produce` outside the accepted variants is a self-check.
- `revisit` needs the current review, practice and the source revisions the pointer names.
  Without the old revision's source, an evidence entry stays unverified (never guessed).
- The loop document is a value: whether and where to keep it is the caller's decision (Workbooks).
- `session` is the caller's label. Two loops with the same inputs and label have the same ID.

## 2. Agent exchange

### Context packet (R4-EXT-031, `flh_agent_context_v1`)

The smallest context for one reviewed exercise:
- `exercise`: practice ID, kind, prompt, options, what it measures, grading. **No answer, no
  rubric** (`answer_included: false`).
- `units`: the reviewed units with state, text and material hash.
- `evidence`: quote, excerpt and location, verified against the source text.
- `last_outcome`: only the outcome, never the answer.
- `learner_goal`: only with `--include-goal`; otherwise `omitted` lists it.
- `return`: the return schema and rules.

`context_id` hashes the packet. An edited packet is refused (`altered_context`). A privacy gate
refuses local paths, session links, e-mail addresses and credential-like strings.

### Markdown (R4-EXT-032)

`exchange.markdown(ctx, agent)` renders the JSON only. **The body is byte-identical for Claude
Code and Codex**; the first line names the agent and the file it writes (`corrections.json`).
The return template is a JSON block at the end.

### Return and import (R4-EXT-033, `flh_agent_corrections_v1`)

```json
{"schema": "flh_agent_corrections_v1", "context_id": "cx-…", "agent": "claude-code | codex | any-agent",
 "corrections": [{"correction_id": "c1", "unit_id": "k-…", "proposed_text": "…", "evidence_ids": ["ev-…"], "rationale": "…"}]}
```

`import_preview(ctx, return, current_review)` classifies each correction and **applies
nothing** (`applied: false`):

| Class | Meaning |
|---|---|
| `candidate` | waits for the learner |
| `duplicate` | equal to the current text |
| `unknown_unit` | not a unit of this packet |
| `uncited` | cites no evidence of this packet |
| `outdated` | the unit changed or is not approved in the current review |
| `invalid` | breaks the correction format |

`accept(preview, correction_id, …)` is the learner's explicit act. It returns an ordinary
`flh_practice_decision_v1` edit whose `via` holds:
- agent, context, correction and source;
- evidence IDs;
- `accepted_by: learner`.

The caller writes it, or does not.

### Versions and recovery (R4-EXT-034)

Each refusal raises `ExchangeError` (CLI exit 2) with a `recovery:` line:

| Code | When | Recovery |
|---|---|---|
| `malformed_return` | not JSON, or agent/corrections wrong | `python3 -m json.tool RETURN.json`, fix, preview again |
| `unsupported_return` | another return schema (for example `…_v2`) | have the agent use the packet's template; `exchange import-preview …` |
| `other_context` | the return answers another packet | preview it with the packet it names |
| `unsupported_context` | another packet schema (for example `…_v0`) | `exchange export --work DIR --practice-id P --out NEW.json` |
| `altered_context` | the packet was edited after export | export again |

### Round trip (R4-EXT-035)

`scripts/r4_exchange.py` runs the round trip with two local stand-ins. They are scripted
functions, not models, playing Claude Code and Codex, and each reads only its Markdown:
- **Preview.** Both returns are previewed and nothing is applied.
- **Accept.** One candidate from each is accepted. Both units become `corrected`, and a
  re-export shows the accepted texts.
- **Provenance.** It has the same fields for both agents.
- **Outdated.** Against revision 2, the correction on the changed unit is `outdated`.

### Not the 2.2 packet

`portable.export3` (`flh_practice_packet_v3`) stays the packet for a whole source.
`flh_agent_context_v1` is exercise-scoped, and its corrections must cite the packet's evidence.

**Choice:** a separate schema in a new module, so the service identity and the sealed 2.2
outputs are unchanged.

**Reversal:** make it a `variant: "exercise"` of packet v3 in `portable.py`. That changes the
service code identity and needs Workbooks' agreement.
