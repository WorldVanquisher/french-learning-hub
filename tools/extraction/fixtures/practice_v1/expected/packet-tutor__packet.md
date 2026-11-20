# FLH practice packet pk-e6edb4e2ae2c — y vs en

Mode: **tutor** (answer keys and rubrics included by the learner's choice)
Source: `y-en-demo` revision 1. Level: A1/A2 (learner-stated target).

## Learner goal

Choose between « y » and « en » when I answer a question about a place (A1/A2).

## Rules for an agent using this packet

1. Cite the evidence ID (ev-…) or knowledge ID (k-…) for every claim you make about the learner's material.
2. Ask one question at a time and wait for the answer.
3. Say clearly when something is NOT supported by the packet's evidence; never present it as the learner's material.
4. Propose corrections and new exercises only in the flh_agent_proposals_v1 format; the learner decides.

## Approved knowledge

- `k-6c4760ebee9d` (claim, corrected by the learner; evidence ev-fd704f2740, ev-6659b658b9): « y » replaces where you go or where you are (à la boulangerie, chez Paul, dans le parc): « Oui, j'y vais. »
  - originally proposed: « y » replaces a place introduced by « à »: « Tu vas à la boulangerie ? — Oui, j'y vais. »
- `k-40cbe73ae3f5` (claim, from the learner's question; evidence ev-17c9dfcc08): « en » replaces a place introduced by « de »: « Je viens de la boulangerie, j'en viens. »
- `k-0d3281b28da6` (contrast, from the learner's question; evidence ev-fd704f2740, ev-17c9dfcc08): Ask which preposition the place takes: « à » gives « y », « de » gives « en ».
- `k-232ca0f26098` (common_error, from the learner's question; evidence ev-053a01e463): « aller à » takes « y »; « en » would mean « from there ».
- `k-d1c9732336a2` (worked_example, generated practice example; evidence none): « aller à la piscine »: the place takes « à », so « y ».
  - example: Vous allez à la piscine ce soir ? — Oui, nous y allons. (a sentence not in the source)
- `k-cb9627cc7213` (worked_example, generated practice example; evidence none): « revenir du marché » (de + le): the place takes « de », so « en ».
  - example: Tu reviens du marché ? — Oui, j'en reviens. (a sentence not in the source)

## Evidence excerpts

- `ev-053a01e463` (revision 1, original_context, located): …langerie ? » J'ai répondu : « [Oui, j'en vais.] » Elle m'a corrigée : « On di…
- `ev-17c9dfcc08` (revision 1, original_context, located): …. » Plus tard, elle a dit : « [Je viens de la boulangerie, j'en viens.] »
- `ev-6659b658b9` (revision 1, original_context, located): …vais. » Elle m'a corrigée : « [On dit : oui, j'y vais.] » Plus tard, elle a dit : « J…
- `ev-fd704f2740` (revision 1, original_context, located): Mon amie m'a demandé : « [Tu vas à la boulangerie ?] » J'ai répondu : « Oui, j'en …

## Known confusions

- `k-232ca0f26098`: not « j'en vais » but « j'y vais » — « aller à » takes « y »; « en » would mean « from there ». (evidence ev-053a01e463; missed in practice: 1)
- missed in practice (1×, answer text not shared): `p-664f7533a19d` produce: Tu reviens du marché ? Answer with « y » or « en ».

## Suggested next exercises

- `p-664f7533a19d` produce (production in a new sentence): Tu reviens du marché ? Answer with « y » or « en ».
  - rubric: accepted: Oui, j'en reviens. | Oui, j'en reviens à l'instant. | Non, je n'en reviens pas.; answer: Oui, j'en reviens.; explanation: « revenir du marché » (de + le): the place takes « de », so « en ».; grading: accepted_variants_else_self_check; known_errors: Oui, j'y reviens. | j'en vais
- `p-2ea892e5eaa0` explain (unaided recall of the rule): From memory, without looking: when do you use « y » and when « en »? Give one example of each.
  - rubric: explanation: Ask which preposition the place takes: « à » gives « y », « de » gives « en ».; grading: self_check; reference: Ask which preposition the place takes: « à » gives « y », « de » gives « en ». | « y » replaces where you go or where you are (à la boulangerie, chez Paul, dans le parc): « Oui, j'y vais. » | « en » replaces a place introduced by « de »: « Je viens de la boulangerie, j'en viens. »
- `p-0e74504cf958` choose (recognition between confusable forms): Tu reviens du marché ? — Oui, j'__ reviens. Options: y / en.
  - rubric: answer: en; explanation: « revenir du marché » (de + le): the place takes « de », so « en ».; grading: exact
- `p-22a947cd7f5c` choose (recognition between confusable forms): Vous allez à la piscine ce soir ? — Oui, nous __ allons. Options: y / en.
  - rubric: answer: y; explanation: « aller à la piscine »: the place takes « à », so « y ».; grading: exact
- `p-8d5cabf2ab59` produce (production in a new sentence): Vous allez à la piscine ce soir ? Answer with « y » or « en ».
  - rubric: accepted: Oui, nous y allons. | Oui, on y va. | Non, nous n'y allons pas. | Non, on n'y va pas.; answer: Oui, nous y allons.; explanation: « aller à la piscine »: the place takes « à », so « y ».; grading: accepted_variants_else_self_check; known_errors: Oui, nous en allons. | Oui, on en va. | j'en vais

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

Return one JSON object with `"schema": "flh_agent_proposals_v1"`, `"packet_id": "pk-e6edb4e2ae2c"` and a `proposals` list. Each proposal has `proposal_id`, `type` (`correction` or `exercise`), `rationale` and `evidence_ids`. A correction names `target_id` and `text`; an exercise names `knowledge_ids`, `kind`, `prompt` and, for choose, `options` and `answer`, or for produce, `accepted`. Mark a proposal with no supporting evidence by leaving `evidence_ids` empty and saying so in the rationale.
