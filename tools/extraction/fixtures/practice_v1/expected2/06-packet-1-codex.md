# FLH practice packet pk-e2920fe276cb — y vs en

Mode: **study**
Source: `y-en-demo` revision 1. Level: A1/A2 (learner-stated target).

## Learner goal

Choose between « y » and « en » when I answer a question about a place (A1/A2).

## Where we left off

- Next exercise: `p-2ea892e5eaa0` explain: From memory, without looking: when do you use « y » and when « en »? Give one example of each.
  - why: the first exercise not yet answered correctly (flh_next_exercise_rule_v1)

## Rules for an agent using this packet

1. Cite the evidence ID (ev-…) or knowledge ID (k-…) for every claim you make about the learner's material.
2. Ask one question at a time and wait for the answer.
3. Say clearly when something is NOT supported by the packet's evidence; never present it as the learner's material.

## Approved knowledge

- `k-6c4760ebee9d` (claim, from the learner's question; evidence ev-fd704f2740, ev-6659b658b9): « y » replaces a place introduced by « à »: « Tu vas à la boulangerie ? — Oui, j'y vais. »
- `k-40cbe73ae3f5` (claim, from the learner's question; evidence ev-17c9dfcc08): « en » replaces a place introduced by « de »: « Je viens de la boulangerie, j'en viens. »
- `k-0d3281b28da6` (contrast, from the learner's question; evidence ev-fd704f2740, ev-17c9dfcc08): Ask which preposition the place takes: « à » gives « y », « de » gives « en ».
- `k-232ca0f26098` (common_error, from the learner's question; evidence ev-053a01e463): « aller à » takes « y »; « en » would mean « from there ».
- `k-d1c9732336a2` (worked_example, generated practice example; evidence none): (answer and explanation withheld: they are the key to p-22a947cd7f5c, p-8d5cabf2ab59)
  - example: Vous allez à la piscine ce soir ? — … (a sentence not in the source)
- `k-cb9627cc7213` (worked_example, generated practice example; evidence none): (answer and explanation withheld: they are the key to p-0e74504cf958, p-664f7533a19d)
  - example: Tu reviens du marché ? — … (a sentence not in the source)

## Evidence excerpts

- `ev-053a01e463` (revision 1, original_context, located): …langerie ? » J'ai répondu : « [Oui, j'en vais.] » Elle m'a corrigée : « On di…
- `ev-17c9dfcc08` (revision 1, original_context, located): …. » Plus tard, elle a dit : « [Je viens de la boulangerie, j'en viens.] »
- `ev-6659b658b9` (revision 1, original_context, located): …vais. » Elle m'a corrigée : « [On dit : oui, j'y vais.] » Plus tard, elle a dit : « J…
- `ev-fd704f2740` (revision 1, original_context, located): Mon amie m'a demandé : « [Tu vas à la boulangerie ?] » J'ai répondu : « Oui, j'en …

## Known confusions

- `k-232ca0f26098`: not « j'en vais » but « j'y vais » — « aller à » takes « y »; « en » would mean « from there ». (evidence ev-053a01e463; missed in practice: 0)

## Suggested next exercises

- `p-2ea892e5eaa0` explain (unaided recall of the rule): From memory, without looking: when do you use « y » and when « en »? Give one example of each.
- `p-0e74504cf958` choose (recognition between confusable forms): Tu reviens du marché ? — Oui, j'__ reviens. Options: y / en.
- `p-22a947cd7f5c` choose (recognition between confusable forms): Vous allez à la piscine ce soir ? — Oui, nous __ allons. Options: y / en.
- `p-664f7533a19d` produce (production in a new sentence): Tu reviens du marché ? Answer with « y » or « en ».
- `p-8d5cabf2ab59` produce (production in a new sentence): Vous allez à la piscine ce soir ? Answer with « y » or « en ».

## Not included

- rejected, pending and needs-review drafts
- the texts of your attempts (only counts of missed items)
- the full question, its context and any chat (only the cited excerpts)
- other sources and unrelated history
- credentials, machine-local paths, session links and e-mail addresses (checked)

## Use it in a fresh agent session

1. Make an empty directory and copy `packet.md`, `packet.json`, `PROMPT-codex.md` and `PROMPT-claude-code.md` into it.
2. Codex: `codex --sandbox workspace-write "$(cat PROMPT-codex.md)"`
3. Claude Code: `claude "$(cat PROMPT-claude-code.md)"`
4. Back in FLH, preview what the agent returned (read-only): `python3 -B -m flh_extraction practice import-preview --packet packet.json --proposals proposals.json`

## How to return proposals

Return one JSON object with `"schema": "flh_agent_proposals_v1"`, `"packet_id": "pk-e2920fe276cb"` and a `proposals` list. Each proposal has `proposal_id`, `type` (`correction` or `exercise`), `rationale` and `evidence_ids`. A correction names `target_id` and `text`; an exercise names `knowledge_ids`, `kind`, `prompt` and, for choose, `options` and `answer`, or for produce, `accepted`. Mark a proposal with no supporting evidence by leaving `evidence_ids` empty and saying so in the rationale.
