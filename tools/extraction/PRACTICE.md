# Practice prototype (Extraction 2.0): from a French question to practice and a portable packet

**PROTOTYPE.** Offline, standard library only, synthetic data. It changes no FLH table,
route or provider and needs no migration. Research and decisions:
[`docs/plans/EXTRACTION-2-practice-decisions.md`](../../docs/plans/EXTRACTION-2-practice-decisions.md).
Run evidence: [`docs/validation/EXTRACTION-2.md`](../../docs/validation/EXTRACTION-2.md).

```sh
cd tools/extraction
python3 -B -m flh_extraction practice2 demo3 --out "$(mktemp -d)/demo" --check # Extraction 2.2 (§9-§14), checked byte for byte
python3 -B -m flh_extraction practice demo2 --out "$(mktemp -d)/demo" --check  # Extraction 2.1, checked byte for byte
python3 -B -m flh_extraction practice demo --out "$(mktemp -d)/demo" --check   # the HANDOFF-136 sequence, unchanged
```

`demo` (Extraction 2.0) runs the sequence once and writes every step to `--out`:
1. capture;
2. inspect the evidence;
3. approve, reject and correct, one item at a time;
4. build practice;
5. answer, then reveal;
6. export a study packet, and a tutor packet with rubrics;
7. preview an agent's proposed corrections.

`demo2` (Extraction 2.1) covers:
- the same path with one batch approval: steps measured before and after (§3);
- a second contrast;
- spotting an unsupported claim and a revised one;
- switching from Codex to Claude Code with one updated packet (§8);
- the sealed Workbooks bundle (§7).

`demo3` (Extraction 2.2, `practice2` commands; run evidence in
[`docs/validation/EXTRACTION-2-2.md`](../../docs/validation/EXTRACTION-2-2.md)) covers:
- reliable approval: quote or paraphrase, word cues, conflicts, material changes, no silent reactivation (§9);
- agent exercise proposals, accepted or rejected by the learner (§10);
- packet v3 for any agent, a minimal variant and a share preview with omissions (§11);
- recall measurement and a delayed probe (§12);
- feed additions and the storage round trip for Workbooks (§13, §14).

## 1. Contract (owned by the extraction lane)

| Schema | What it is | Who writes it |
|---|---|---|
| `flh_practice_source_v1` | one question (`learning_capture_v1` fields), an optional learner goal, a revision number and a **proposal** of items, each citing exact **quotes** of the source | a proposer: here a hand-written synthetic fixture; never a provider call in this lane |
| `flh_practice_draft_v1` | the proposal grounded against the learner's own text; stable IDs; support per item | `practice init` / `revise` (deterministic) |
| `flh_practice_decision_v1` (JSONL, append-only) | approve, reject or edit (a learner correction) per item, with the item hash it was made on | the learner |
| `flh_practice_items_v1` | practice built from approved items; answers under `hidden` | `practice build` |
| `flh_practice_attempt_v1` (JSONL, append-only) | attempts and reveals with their outcome | the learner |
| `flh_practice_packet_v1` | the portable packet (JSON; the Markdown is rendered from it) | `practice export` |
| `flh_agent_proposals_v1` | what an agent sends back | an agent (Codex, Claude Code, …) |
| `flh_agent_import_preview_v1` | the read-only classification of that return | `practice import-preview` |
| `flh_practice_review_feed_v1` | approved practice items and attempt outcomes for Workbooks; `withdrawn` when made against a previous feed | `practice feed` |
| `flh_practice_batch_review_v1` | the pending items split into one batch (supported items and new practice examples) and the items the learner decides one by one, with why and, for a revised item, what changed | `practice init / revise / review` |
| `flh_practice_packet_v2` | packet v1 plus `last_confusion`, `next_exercise` and `continuity`; `knowledge[].accepted_from` | `practice export` (default; `--packet-version 1` keeps v1) |
| `flh_practice_steps_v1` | commands from capture to first practice, before vs after, with the invariants checked | `practice measure` |
| `flh_practice_workbooks_bundle_v1` | the sealed synthetic Workbooks bundle: feeds, cases, `verify.py`, `SHA256SUMS` | `practice workbooks-bundle` |

**Item types.**
- `claim`: a statement; optional `kind`, `canonical` and `statement_zh` mirror the `knowledge_extraction_v2` unit.
- `contrast`: two forms `a` / `b`, each with a `use`, plus the `distinction`.
- `worked_example`: `question`, `answer`, `accepted` variants, optional `wrong` answers, `cloze`, `choices`, `target` and `explanation`.
- `common_error`: `wrong`, `right` and `why`.

**IDs.**
- An item ID is `k-` + 12 hex characters of SHA-256(source_id, type, normalised content key). It never hashes the revision.
- An evidence ID is `ev-` + 10 hex characters of SHA-256(source_id, field, quote, occurrence).
- Practice IDs are `p-…`; draft IDs `d-…` hash the revision SHA-256; packet IDs `pk-…` hash the packet.
- Every evidence entry carries `source_revision`. Offsets index the NFC text with apostrophes unified.

**Grounding (per quote).**
- `located`: exactly once in the learner's input or context.
- `ambiguous`: repeated, so no single position supports it.
- `explanation_only`: only in the machine explanation shown to the learner.
- `not_found`.

**Support (per item).**
- `supported`: every quote is located.
- `uncertain`: a quote is ambiguous or explanation-only.
- `unsupported`: a quote is not found.
- `no_evidence`: no quote at all.
- `generated`: a new practice example the source never claimed.

The existing `evidence_review` heuristic class is recorded beside every claim.

**Origin.**
- `source`: proposed from the question.
- `learner`: corrected by the learner; the proposal is kept beside it.
- `generated`.

Uncertain and unsupported items stay visible, marked "still a draft, decide explicitly", until the learner decides.

**Batch review (2.1).** `init`, `revise` and `review` print the draft beside its
evidence, then the review:
- **Approve together:** the pending items that are `supported` (every quote located exactly once) or `generated` (new practice examples). Their batch ID `b-…` hashes the draft ID and exactly those items with their hashes.
- **Decide yourself, one by one:** every unsupported, uncertain or no-evidence item, and every item that changed since a decision (with the changed quote's status before and after). These are never in a batch.

`decide --approve-batch b-…` writes one ordinary `approve` decision per member, with
`batch: {batch_id, size, excepted}`. It is refused if the batch is no longer the one
shown, for example after a revision or another decision. `--except k-…` leaves an
item out. An accepted agent correction is an `edit` decision with
`via: {kind: agent_proposal, agent, packet_id, proposal_id, rationale, evidence_ids, flags}`.

**Revisions.** A decision carries forward to a new revision only while the item hash is
unchanged. The hash covers the content and each quote's grounding status, not positions.
Otherwise the item is `needs_review`, and practice is built only from approved or
corrected items.

## 2. Practice and grading

| Kind | Built from | Measures | Grading |
|---|---|---|---|
| `explain` | an approved contrast and the claims it applies to | unaided recall of the rule | always `self_check` against the approved statements |
| `choose` | an approved worked example with a cloze, options = `choices` or the contrast forms | recognition between confusable forms | exact; another option is `incorrect`, anything else `invalid` |
| `produce` | an approved worked example with `accepted` variants | production in a new sentence (`new_sentence` is computed against the source) | an accepted variant (case, punctuation and apostrophes ignored) is `correct`; a listed wrong answer or common error is `incorrect`; anything else is `self_check`, because it may still be correct French |

Before an attempt, `practice build` and `public()` show prompts and options only. An
attempt or an explicit `--reveal` shows the following, and a reveal is recorded as
`revealed`, never as an attempt:
- the answer and the accepted variants;
- the explanation;
- each supporting excerpt with its evidence ID.

## 3. Step by step (local work directory; nothing leaves it unless you export)

**The short path (2.1): three steps from capture to the first practice.**

```sh
W=$(mktemp -d)/w
python3 -B -m flh_extraction practice init   --source fixtures/practice_v1/y_en.r1.json --work $W   # draft beside its evidence, then the review
python3 -B -m flh_extraction practice decide --work $W --approve-batch b-d877ea1aeb14              # the batch ID printed by init
python3 -B -m flh_extraction practice build  --work $W                                              # prompts only
python3 -B -m flh_extraction practice decide --work $W --item k-5ca79503ae78 --reject --reason "not in my text"   # the flagged claim, when you like
```

Measured by `practice measure` (it runs both flows; same intent: approve every
supported item and new practice example):

| Source | Before (HANDOFF-136) | After (2.1) | Unchanged |
|---|---|---|---|
| y/en, revision 1 | 9 | 3 | approved items (6), practice IDs (5), evidence links (5 of 5 exercises), one learner decision per approved item |
| savoir/connaître, revision 1 | 9 | 3 | the same (6, 5, 5 of 5) |
| y/en, revision 2 (practise again) | 5 | 4 | the 2 changed items are still decided one by one; the same practice IDs return |

Of the 6 steps saved on revision 1, 5 come from the batch (six decisions become one).
The sixth is the separate `preview`, which `init` already printed in HANDOFF-136. The
flagged item stays pending and named in the review; nothing is approved for the learner.

**One decision per item (the HANDOFF-136 path, still available).**

```sh
W=$(mktemp -d)/w
python3 -B -m flh_extraction practice init    --source fixtures/practice_v1/y_en.r1.json --work $W   # draft + side-by-side preview
python3 -B -m flh_extraction practice decide  --work $W --item k-5ca79503ae78 --reject --reason "my friend corrected this"
python3 -B -m flh_extraction practice decide  --work $W --item k-6c4760ebee9d --edit "« y » replaces where you go or where you are …"
python3 -B -m flh_extraction practice decide  --work $W --item k-0d3281b28da6 --approve      # … one decision per item
python3 -B -m flh_extraction practice preview --work $W
python3 -B -m flh_extraction practice build   --work $W                                       # prompts only
python3 -B -m flh_extraction practice answer  --work $W --item p-… --text "Oui, on y va !"    # or --reveal
python3 -B -m flh_extraction practice export  --work $W --mode study --preview               # what would be shared
python3 -B -m flh_extraction practice export  --work $W --mode tutor --include-rubrics --out NEW_DIR
python3 -B -m flh_extraction practice revise  --work $W --source fixtures/practice_v1/y_en.r2.json
python3 -B -m flh_extraction practice import-preview --packet NEW_DIR/packet.json --proposals proposals.json
python3 -B -m flh_extraction practice accept  --work $W --packet NEW_DIR/packet.json --proposals proposals.json --proposal c1
python3 -B -m flh_extraction practice compare                                                 # prototype vs evidence-review
python3 -B -m flh_extraction practice measure --out "$(mktemp -d)/m"                         # steps before vs after
```

Exit codes:
- 0: success;
- 2: invalid input, an unknown ID, or a non-empty work or packet directory;
- 3: the export was refused by the privacy gate.

## 4. Packets (125–127)

| Mode | Contains | Never contains |
|---|---|---|
| `study` | goal; approved knowledge with origin and support; evidence excerpts with IDs; known confusions; items missed in practice, by ID only; suggested next exercises, most-missed first; the return format | answer keys or rubrics. A worked example that is the key to a listed exercise shows only its question |
| `tutor` | the same, the four tutoring rules, and the proposed text beside each learner correction | rubrics and answer keys, **unless** the learner passes `--include-rubrics` (an explicit choice) |

Every mode excludes:
- rejected, pending and needs-review drafts;
- attempt texts;
- the full question, its context and any chat; only the cited excerpts go out;
- other sources.

The privacy gate refuses (exit 3) a packet with:
- a home path, macOS user path or Windows user path;
- a claude.ai link or an e-mail address;
- a credential-like string or a private-key header.

`export --preview` writes nothing.

**Packet v2 (the default since 2.1)** adds a "Where we left off" section and three fields:
- `last_confusion` comes from the latest incorrect attempt on approved knowledge.
  - It gives the confused forms (from the contrast), the exercise ID, kind and prompt, the attempt's `seq`, whether a later attempt fixed it, and the known-confusion ID when the attempt matched one.
  - It never contains the attempt text or the expected answer.
- `next_exercise` follows `flh_next_exercise_rule_v1`.
  - After an unresolved miss: the same contrast in a different worked example, `produce` before `choose`, not yet answered correctly. Failing that, the contrast's `explain` item; failing that, the missed exercise.
  - Without a miss: the first exercise not yet answered correctly.
  - The rule is a hypothesis, untested here. The interleaving evidence for grammar is mixed: in Pan et al. 2019 it helped only with a combined schedule (`docs/validation/EXTRACTION-2-1.md`, R11–R12).
- `continuity`, only with `--previous PACKET`, holds:
  - the previous packet ID;
  - knowledge IDs kept, added or dropped;
  - the items whose text changed, and why (for example, "the learner accepted proposal c1 from codex");
  - new misses.

`--packet-version 1` writes the v1 packet unchanged; `demo` pins it.

## 5. Using the same packet in a fresh agent session (128) and returning proposals (129)

1. Make an empty directory and copy `packet.md`, `packet.json`, `PROMPT-codex.md` and
   `PROMPT-claude-code.md` into it. `export --out` writes exactly those four files.
2. **Codex:** `codex --sandbox workspace-write "$(cat PROMPT-codex.md)"`.
3. **Claude Code:** `claude "$(cat PROMPT-claude-code.md)"`. That prompt names `@packet.md` and `@packet.json`.
4. Both prompts ask the agent to:
   - cite `ev-…`/`k-…` IDs;
   - ask one question at a time;
   - label anything "not in the packet";
   - never show an answer first;
   - on "done", write `proposals.json`.
5. Back in FLH: `practice import-preview --packet packet.json --proposals proposals.json`.
6. To take one correction: `practice accept --work W --packet packet.json --proposals proposals.json --proposal ID`. This is the learner's decision, recorded as an `edit` with its provenance. Acceptance is refused unless:
   - the preview classes the proposal `accepted_candidate`;
   - the return names this packet;
   - the packet is about the current source revision;
   - the learner's current knowledge does not already say the same and holds no correction of their own on that item.

   An exercise proposal stays in the preview. Then run `practice build`, and export with `--previous packet.json` for the next session.

`flh_agent_proposals_v1`:
- Top level: `{"schema", "packet_id", "agent", "proposals": [...]}`.
- Each proposal has `proposal_id`, `type` (`correction` | `exercise`), `rationale` and `evidence_ids` (empty = unsupported).
- A correction adds `target_id` and `text`.
- An exercise adds `knowledge_ids`, `kind` and `prompt`, plus `options` and `answer` (choose) or `accepted` (produce).

The preview classifies each proposal and applies nothing:

| Class | When |
|---|---|
| `accepted_candidate` | valid and new; it still needs the learner's approval. Flag `cites no evidence` when `evidence_ids` is empty |
| `duplicate` | same wording as the current item, the same prompt as a packet exercise, or an earlier proposal |
| `conflict` | it would replace a **learner** correction; an expected answer uses a known confusion; or a choose answer is not among its options |
| `unknown_reference` | a target, knowledge or evidence ID that is not in the packet |
| `invalid` | missing `proposal_id`, `type`, `rationale` or `evidence_ids`, or an incomplete correction or exercise |

## 6. Fixtures (131)

| Fixture | Covers |
|---|---|
| `fixtures/practice_v1/y_en.r1.json` | grammar contrast y vs en: two supported claims, one unsupported claim (rejected in the demo), contrast, common error, two generated new-sentence examples with valid alternates (« nous » / « on ») |
| `fixtures/practice_v1/y_en.r2.json` | revised source: one quote changed. The learner correction and three approvals carry forward; the claim and contrast that cite the changed quote need review |
| `fixtures/practice_v1/en_quantite.json` | ambiguous evidence (« en » occurs 7 times), explanation-only evidence, valid alternate answers (« J'en ai trois. »), a valid unlisted answer → self-check, full-form choices (« j'en » / « je les ») |
| `fixtures/practice_v1/agent_return.json` | one hand-written agent return covering every preview class (no agent was run) |
| `fixtures/practice_v1/expected/` | the demo's 14 outputs, checked byte for byte by `demo --check` |
| `fixtures/practice_v1/savoir_connaitre.json` | the second contrast (2.1): « savoir » vs « connaître ». Two supported claims, one unsupported claim that lexical anchoring still rates `anchored`, a common error, and two generated new-sentence examples with alternates (« Oui, je le connais. ») |
| `fixtures/practice_v1/switch/codex-return.json` | session 1 (Codex), hand-written for packet `pk-e2920fe276cb`: a correction (accepted by the learner), the same correction again (duplicate), an exercise |
| `fixtures/practice_v1/switch/claude-code-return.json` | session 2 (Claude Code), hand-written for packet `pk-afdb387f3af6`: a rewrite of the accepted correction (conflict), a correction (candidate), the packet's own next exercise (duplicate), an unknown evidence ID |
| `fixtures/practice_v1/expected2/` | `demo2`'s 13 outputs, checked byte for byte by `demo2 --check` |
| `fixtures/practice_v1/workbooks/` | the sealed Workbooks bundle (§7) |

All French sentences are synthetic A1/A2 examples written for this prototype. They need a native-speaker check before learner use.

## 7. Workbooks integration (proposal, read-only; 134)

The extraction lane owns the practice-content contract. Review Today, scheduling and any
schema stay with the Workbooks lane. `practice feed --work W --out F` writes
`flh_practice_review_feed_v1`; the sample payload is `fixtures/practice_v1/expected/07-workbooks-feed.json`.
- `source`: `source_id`, `revision`, `revision_sha256`, `capture_id`.
- `items[]`: the public practice item, with `practice_id`, `kind`, `measures`, `prompt`, `options?`, `knowledge_ids`, `evidence_ids`, `new_sentence` and `grading`.
- `items[].outcomes[]`: `seq`, `action` (`attempt` | `reveal`) and `outcome` (`correct` | `incorrect` | `self_check` | `revealed` | `invalid`).
- It never contains a due date, interval or schedule (Workbooks decides those), answer keys, or attempt texts.

Proposed read-only use by Workbooks, their decision:
- Review Today lists a feed item as a new source `practice` with reason `practice_outcome`.
- `NextRecommendation` can count `attempt` outcomes as completed attempts.
- `revealed` and `self_check` are kept apart from `correct`.
- A changed `revision_sha256` means the items came from a revised source; the extraction side rebuilds them.

`practice feed --previous EARLIER_FEED` adds `previous` (revision and hash) and `withdrawn`.
`withdrawn` lists the practice IDs no longer offered, with the reason. They are typically
built on knowledge that changed in a revision and await the learner's review. Without
`--previous` the feed is exactly the HANDOFF-136 shape.

**Sealed synthetic bundle (2.1): `fixtures/practice_v1/workbooks/`.** See its `README.md`. It holds:
- four feeds: y/en revision 1, revision 2 (all 5 items withdrawn), revision 2 after re-approval (the same 5 practice IDs), and savoir/connaître;
- stable IDs, source revisions and the three exercise kinds;
- attempt examples covering every outcome (`correct`, `incorrect`, `self_check`, `revealed`, `invalid`);
- three test cases: a changed source, a duplicate correction, and a study packet without answers.

`python3 verify.py` (standard library only, read-only) checks:
- the seal;
- that no feed carries a schedule, an answer or an attempt text;
- every case.

`practice workbooks-bundle --out NEW --check` regenerates the bundle byte for byte.

Persisting decisions, attempts or practice needs a migration. That is an owner decision; this prototype runs without one.

## 8. Switching agents with one packet (2.1, worked example)

`demo2` runs this offline. The two agent returns are hand-written fixtures; no agent is called.

1. **Short path on y/en.** Batch `b-d877ea1aeb14` approves 6 items, and the learner rejects the flagged claim `k-5ca79503ae78`. One answer: `p-22a947cd7f5c` choose, correct.
2. **Session 1 with Codex.** Study packet `pk-e2920fe276cb` (v2): no last confusion; next exercise `p-2ea892e5eaa0` (explain).
3. **Codex returns** (`switch/codex-return.json`):
   - `c1`, a wider wording of the contrast `k-0d3281b28da6`. It is labelled "not in the packet" where it goes beyond the evidence.
   - `c2`, the same correction again: classed `duplicate`.
   - `c3`, an exercise: it stays in the preview.
4. **The learner accepts `c1`.** `practice accept … --proposal c1` records decision 8 (`edit`, via codex `c1`). Accepting `c2` is refused as a duplicate, and so is `c1` a second time ("already says this").
5. **A later miss.** `p-664f7533a19d` produce: « Oui, j'y reviens. » matches a known wrong answer.
6. **Session 2 with Claude Code.** `practice export --previous session-1/packet.json` writes packet `pk-afdb387f3af6`:
   - the same 6 knowledge IDs;
   - `k-0d3281b28da6` with the accepted wording and `accepted_from: codex c1 (pk-e2920fe276cb)`;
   - `continuity` naming that change and the new miss;
   - `last_confusion` « y » vs « en » on `p-664f7533a19d` (no attempt text, no answer);
   - `next_exercise` `p-8d5cabf2ab59`, produce « Vous allez à la piscine ce soir ? »: the same contrast in a different sentence;
   - 0 of 9 answer keys present.
7. **Claude Code returns** (`switch/claude-code-return.json`): its rewrite of `k-0d3281b28da6` is a `conflict`, so the second agent cannot replace the learner's accepted correction.

**Owner smoke** (live sessions: real-agent calls, not run by the prototype). Use a
scratch copy of `tools/extraction`, and record what each step shows.

```sh
cd tools/extraction; R=$(mktemp -d)
python3 -B -m flh_extraction practice init   --source fixtures/practice_v1/y_en.r1.json --work $R/w
python3 -B -m flh_extraction practice decide --work $R/w --approve-batch b-d877ea1aeb14
python3 -B -m flh_extraction practice decide --work $R/w --item k-5ca79503ae78 --reject --reason "not in my text"
python3 -B -m flh_extraction practice build  --work $R/w
python3 -B -m flh_extraction practice answer --work $R/w --item p-22a947cd7f5c --text y
python3 -B -m flh_extraction practice export --work $R/w --out $R/s1                    # session 1 packet (v2)
(cd $R/s1 && codex --sandbox workspace-write "$(cat PROMPT-codex.md)")                  # tutor a little, propose one correction, type: done
python3 -B -m flh_extraction practice import-preview --packet $R/s1/packet.json --proposals $R/s1/proposals.json
python3 -B -m flh_extraction practice accept --work $R/w --packet $R/s1/packet.json --proposals $R/s1/proposals.json --proposal ID
python3 -B -m flh_extraction practice build  --work $R/w
python3 -B -m flh_extraction practice answer --work $R/w --item p-664f7533a19d --text "Oui, j'y reviens."
python3 -B -m flh_extraction practice export --work $R/w --previous $R/s1/packet.json --out $R/s2
(cd $R/s2 && claude "$(cat PROMPT-claude-code.md)")                                       # fresh session; type: done
python3 -B -m flh_extraction practice import-preview --packet $R/s2/packet.json --proposals $R/s2/proposals.json
```

To run the sessions the other way round, start session 1 with `claude` and session 2
with `codex`; the packets are the same.

Record per session:
- Did the agent start from "Where we left off"? Session 2 should name the accepted change and give `p-8d5cabf2ab59` first.
- Did it cite `ev-`/`k-` IDs?
- Did it ask one question at a time?
- Did it label claims "not in the packet"?
- Did it avoid asking for earlier answers?
- Does `proposals.json` parse as `flh_agent_proposals_v1` with the right `packet_id`?
- Is a rewrite of the accepted correction classed `conflict`?

## 9. Reliable approval (2.2, `practice2`)

A 2.2 work directory (`practice22.Work2`) keeps every 2.1 file and adds `sources/rN.json`,
`exercise-decisions.jsonl` and `packets/`. The 2.1 commands and outputs are unchanged.

```sh
python3 -B -m flh_extraction practice2 init   --source fixtures/practice_v1/a_en_lieux.json --work W
python3 -B -m flh_extraction practice2 review --work W [--select k-…,k-…] [--except k-…] [--json R.json]
python3 -B -m flh_extraction practice2 decide --work W --item k-… --approve [--attest-paraphrase] | --reject | --edit TEXT  [--reason …]
python3 -B -m flh_extraction practice2 decide --work W --approve-batch b2-… [--select k-…,k-…] [--except k-…]
python3 -B -m flh_extraction practice2 repair --work W        # after an interrupted write; sets the torn bytes aside
python3 -B -m flh_extraction practice2 revise --source S2 --work W
```

**What the review shows.** Every line beside an item is labelled:
- `QUOTE`: the learner's exact words, with grounding and evidence ID;
- `PARAPHRASE`: a restatement of one quote, never evidence;
- `CUE`: a word check (`flh_quote_scope_cues_v1`) that a located quote may not carry the
  claim. Two cues: a generalising word ("every", "always", "toujours"…), and « en » + a word
  in -ant (often a gerund). A cue proves nothing either way: a non-entailing claim without
  such a word is not caught (tested);
- `CONFLICT`: an item presents as correct what a common error lists as wrong;
- `MOVED`: a quote located at another position than in the previous revision. It is still
  located, so the decision is kept; its evidence ID changes, and the old ID is shown.

**Batch v2** (`flh_practice_batch_plan_v1`). The plan lists the batched items explicitly
(`[x]`) and its effect: how many items become approved knowledge, one decision record each,
and the practice count before and after, with the new practice IDs.

Never batched:
- revised items (`CHANGED`, `RESTORED`);
- unsupported, uncertain and evidence-free items;
- items with a cue;
- both sides of an open conflict (until one side is rejected);
- items with a paraphrase (approve with `--attest-paraphrase`, recorded as the learner's).

`--select` approves fewer members; the batch ID still binds every member shown.
- **Retry.** A retry with the same ID writes only the members still missing.
- **Stale ID.** An ID whose members or hashes changed is refused.
- **Torn write.** A torn last line refuses every read until `repair`.

**Across revisions.** A decision records the item's `material_hash` (content, paraphrases and
quote statuses after NFC, apostrophe and whitespace normalisation) and the draft ID.

| What happened since the decision | State now |
|---|---|
| nothing material (spacing, apostrophes) | the decision holds (`normalized_only` is shown) |
| absent from one revision, back unchanged | the decision holds (`reappeared_after`) |
| a material change | `needs_review` (changed): what changed is shown with values |
| changed, then back to the decided state | `needs_review` (restored): never reactivated silently |
| a claim's statement rewritten | a new item ID, pending: no approval transfers |

A rejection keeps its reason with the revision that caused it. When the item changes later,
the review shows "your reason then (revision N)". All 24 transitions are executed by
`practice2 matrix --out DIR` (`expected3/17-acceptance-matrix.md`).

## 10. Agent exercise proposals (2.2)

An agent returns exercises in `flh_agent_proposals_v2`. Corrections may stay in v1. Each
exercise is `flh_exercise_proposal_v1`:

| Field | Rule |
|---|---|
| `kind` | `explanation` (unaided recall), `discrimination` (choose) or `production` (a sentence) |
| `rule_id` | an approved claim or contrast of the packet |
| `source` | the packet's source object, unchanged (revision and SHA-256) |
| `prompt`, `rationale`, `evidence_ids` | evidence IDs from the packet only |
| discrimination | `options`, `answer` (one of the options) |
| production | `answer`, `accepted` (every valid variant), `rubric` |
| explanation | `reference` |
| `ambiguity` | optional: where the rule allows more than one answer |

```sh
python3 -B -m flh_extraction practice2 import-preview --work W --packet P --proposals R   # read-only
python3 -B -m flh_extraction practice2 exercise --work W --packet P --proposals R --proposal e1 --approve [--prompt …] [--accepted V …] [--answer …]
python3 -B -m flh_extraction practice2 exercise --work W --packet P --proposals R --proposal q2 --reject --reason …
```

**Preview classes.**

| Class | Meaning |
|---|---|
| `candidate` | shows the answer, variants, rubric and ambiguities; the ambiguities are the agent's own plus word checks (prompt contains the answer, one accepted variant only, duplicate variants, both contrast forms accepted) |
| `decided` | the learner already decided it |
| `duplicate` | the same prompt is in the packet, in this return, or already accepted from any agent |
| `withdrawn` | its rule is no longer approved; says which decision fixes it |
| `wrong_revision` | names another source revision than the packet |
| `unknown_reference` | cites an ID the packet does not have |
| `conflict` | the answer is not an option, or an expected answer uses a known confusion |
| `invalid` | missing fields or malformed IDs |
| `unsupported_version` | not `flh_agent_proposals_v2` or not `flh_exercise_proposal_v1` |

**Decisions.**
- Decisions are `flh_practice_exercise_decision_v1`, keyed by (agent, packet, proposal).
- The same decision repeated writes nothing; a different one is refused.
- The practice ID hashes the rule, the kind and the proposed prompt, so a learner's edit keeps it.
- An accepted exercise is practice with:
  - `origin: agent_proposal`;
  - `support: agent_proposed`;
  - provenance (agent, packet, proposal, "accepted by the learner").
- Its evidence is only the packet's own IDs it cited. The agent's rationale is never evidence.
- It is offered only while its rule is approved. Otherwise it is listed under "Accepted
  exercises not offered now" and withdrawn from the feed.

## 11. Packet v3, adapters and the owner smoke (2.2)

```sh
python3 -B -m flh_extraction practice2 export --work W --preview [--variant minimal] [--omit learner_goal|evidence_text|practice_history|last_confusion]
python3 -B -m flh_extraction practice2 export --work W --out DIR [--agent codex|claude-code|any-agent] [--previous FILE|latest] [--awaiting PACKET RETURN]
```

`flh_practice_packet_v3` = v2 plus:
- `variant`;
- `omitted_by_learner`;
- each exercise's `origin` (and `accepted_from`);
- `exercises_not_offered`;
- `awaiting_learner`: proposals previewed but not accepted. They are rendered under
  "Proposed by an agent, NOT accepted by the learner (not knowledge)" and are never in `knowledge`;
- both return formats.

The packet is the same bytes for every agent, in normal form (NFC, LF, no trailing spaces).
The adapter is only the prompt: `PROMPT-codex.md`, `PROMPT-claude-code.md`, or
`PROMPT-any-agent.md` for any other tool that reads Markdown (it can ask the learner to
paste `packet.md` and print the JSON instead of writing it).

**Other packet features.**
- **Minimal packet.** Goal, rules, last confusion, next exercise (never its answer) and the
  return format, in "Where we left off" form. About 1.6 KB of Markdown in the demo, against
  7.1 KB for the full packet.
- **Kept packets.** Every written packet is kept in `W/packets/`, so `--previous latest`
  continues even when the first session's directory is gone.
- **Older packets.** v1 and v2 packets with their original returns are still previewed
  exactly as 2.1 did.

**Owner smoke checklist (real tools; not run by the prototype).** Use a scratch copy, and
record each answer.

```sh
cd tools/extraction; R=$(mktemp -d); F=fixtures/practice_v1; X="python3 -B -m flh_extraction practice2"
$X init --source $F/a_en_lieux.json --work $R/w
$X decide --work $R/w --item k-1ef55be82232 --reject --reason "au Japon: Japon is masculine"
$X decide --work $R/w --item k-32f4087a06b6 --approve
$X decide --work $R/w --item k-edad5a9a03c5 --edit "In « en débarquant en Égypte », the first « en » makes a gerund (« en » + -ant: while landing); only « en Égypte » is the place preposition."
$X decide --work $R/w --item k-53a8841fc7d3 --approve --attest-paraphrase
$X decide --work $R/w --approve-batch b2-adcf5ee59182
$X export --work $R/w --out $R/s1 --agent codex                       # expect packet pk-0e06b9c6b9c4
(cd $R/s1 && codex --sandbox workspace-write "$(cat PROMPT-codex.md)") # tutor; ask it for one new exercise; type: done
$X import-preview --work $R/w --packet $R/s1/packet.json --proposals $R/s1/proposals.json
$X exercise --work $R/w --packet $R/s1/packet.json --proposals $R/s1/proposals.json --proposal ID --approve
$X revise --work $R/w --source $F/a_en_lieux.r2.json
rm -r $R/s1                                                          # the first session is gone
$X export --work $R/w --previous latest --out $R/s2 --agent claude-code
(cd $R/s2 && claude "$(cat PROMPT-claude-code.md)")                  # fresh session; type: done
$X import-preview --work $R/w --packet $R/s2/packet.json --proposals $R/s2/proposals.json
```

For the other direction, use `--agent claude-code` for session 1 and `--agent codex` for
session 2. For any other agent, `--agent any-agent`.

Record per session:
1. Did it start from "Where we left off"? In session 2 it should name the dropped rule
   `k-886099054b26` and the exercise that is not offered.
2. Did it cite `ev-`/`k-` IDs and ask one question at a time?
3. Did it label anything outside the packet "not in the packet"?
4. Did it never ask for earlier answers and never show an answer first?
5. Does `proposals.json` parse (v2 when it proposes an exercise) and name the right `packet_id`?
6. Is each exercise classed as you expect, with its ambiguities shown?
7. Is an exercise for `k-886099054b26` in session 2 `unknown_reference` (that rule is not in
   packet 2)?

## 12. Recall measurement (2.2)

| Outcome | Exercise | Graded |
|---|---|---|
| `unassisted_recall` | explain, no options and no source sentence | self-check only |
| `assisted_recall` | choose: the options are a cue | exactly |
| `transfer` | produce in a sentence that is in neither the source, the practice nor any study packet | accepted variants / listed errors / self-check |

**The probe.** `fixtures/practice_v1/probe/y_en_probe_v1.json` has 12 synthetic items:
1 unassisted, 2 assisted and 9 transfer, three per difficulty level:
- L1: the source's verbs, a new place;
- L2: another verb with the same preposition;
- L3: passé composé, or the future of « aller », where « y » is usually dropped.

**Checks run by the tests:**
- **Novelty.** No prompt or answer occurs in the source, the practice or any study packet;
  the longest shared word sequence is reported per item.
- **No answers in study packets.**
- **Order.** A seeded, deterministic shuffle that refuses a repeated example.

**Response statuses.**
- `completed`: an answer the probe can score;
- `revealed`: shown on purpose;
- `skipped`;
- `unsupported`: not an option, or a production with neither form, so it cannot be scored
  for this contrast;
- `missing`: planned with no response.

Summaries give every rate with its denominator: correct of completed, and correct of planned.

```sh
python3 -B -m flh_extraction practice2 trial --out DIR [--check]   # sheet, key, response template, dry-run summary, checks (= probe/expected/)
```

The dry run uses synthetic responses and equals the hand-computed totals in
`probe/expected-totals.json`. It checks arithmetic, not learning. It cannot support any
claim about long-term retention: one session, no spacing, no control.

## 13. Feed additions for Workbooks (2.2)

`practice2 feed --work W --out F --seq N [--previous F0]` writes the unchanged v1 feed plus
optional fields (`contract_additions: flh_practice_feed_additions_v1`).

**Per item:**
- `source_revision`;
- `recall_type`;
- `origin` (with provenance for an agent exercise).

**Per feed:**
- `feed_seq` and `feed_id` (a hash of the feed);
- `withdrawn`: each entry has a `reason_code`, one of `knowledge_changed`,
  `awaiting_confirmation`, `rejected`, `rule_not_approved` or `absent`. It is repeated in every
  later feed until the ID is offered again;
- `restored`;
- `added`.

The 2.1 bundle is unchanged. `fixtures/practice_v1/workbooks2/` (sealed) holds:
- five feeds: new, newly approved, withdrawn, awaiting confirmation, restored;
- replay cases;
- `check_feed_compat.py`: the contract, the increment-4 consumer's rules and a reference
  client;
- the storage files (§14).

**Known gap.** The increment-4 consumer refuses a feed with no items (the 2.1 all-withdrawn
feed).

## 14. Storage planning (2.2)

`practice2 storage --work W` maps a work directory onto the Workbooks proposal (four
append-only tables, pinned copy in `fixtures/practice_v1/storage/`) in an in-memory SQLite
database. It runs twice, with their SQL as proposed and with the extraction lane's amendment
(an `agent_exercise` subject kind and a `provenance_json` column). Results, the events that
must survive a reload, the ID map, the revision-during-review rule, answer-text export and
retention, and retracted evidence: `workbooks2/STORAGE-DECISION-RECORD.md`. Workbooks can run
`check_storage_rows.py` without this package.
