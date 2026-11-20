# FLH practice packet (v3) pk-0e06b9c6b9c4 — à vs en

Mode: **study**
Source: `a-en-lieux-demo` revision 1. Level: A1/A2 (learner-stated target).

## Learner goal

Choose « à » or « en » before a place name when I say where someone is or goes (A1/A2).

## Where we left off

- Next exercise: `p-cf2ec01246c8` explain: From memory, without looking: when do you use « à » and when « en »? Give one example of each.
  - why: the first exercise not yet answered correctly (flh_next_exercise_rule_v1)

## Rules for an agent using this packet

1. Cite the evidence ID (ev-…) or knowledge ID (k-…) for every claim you make about the learner's material.
2. Ask one question at a time and wait for the answer.
3. Say clearly when something is NOT supported by the packet's evidence; never present it as the learner's material.

## Approved knowledge

- `k-886099054b26` (claim, from the learner's question; evidence ev-75a4d1fa87, ev-371c2bef92): « à » goes before a city name: « à Paris », « à Londres ».
- `k-fb79321ec520` (claim, from the learner's question; evidence ev-2cd24b70b3, ev-906a1a54d7, ev-7c2a34f83e): « en » goes before a feminine country or a continent, and before a country name that begins with a vowel: « en Angleterre », « en Égypte », « en Europe ».
- `k-53a8841fc7d3` (claim, from the learner's question; evidence ev-7962c7e3a2): « aux » (« à » + « les ») goes before a plural place name: « jusqu’aux Indes ».
- `k-edad5a9a03c5` (claim, corrected by the learner; evidence ev-60c96b27d6): In « en débarquant en Égypte », the first « en » makes a gerund (« en » + -ant: while landing); only « en Égypte » is the place preposition.
- `k-d0424fb40a11` (contrast, from the learner's question; evidence ev-75a4d1fa87, ev-2cd24b70b3): Ask what the place is: a city takes « à »; a feminine country or a continent takes « en ».
- `k-32f4087a06b6` (common_error, generated practice example; evidence none): « Japon » is masculine and begins with a consonant, so « à » + « le » gives « au ».
- `k-82761c80f843` (worked_example, generated practice example; evidence none): (answer and explanation withheld: they are the key to p-10a28f330355, p-919b6c108284)
  - example: Où habite ta sœur ? (Lyon) — … (a sentence not in the source)
- `k-edadc7ded432` (worked_example, generated practice example; evidence none): (answer and explanation withheld: they are the key to p-04705161a655, p-f9efb7256976)
  - example: Où vas-tu cet été ? (l’Espagne) — … (a sentence not in the source)

## Evidence excerpts

- `ev-2cd24b70b3` (revision 1, original_context, located): …mpiers, à Paris » ; « je suis [valet de chambre en Angleterre] ». Chapitre 3 : « ont été env…
- `ev-371c2bef92` (revision 1, original_context, located): …t en Europe ». Chapitre 8 : « [Lancer une dépêche à Londres] » ; « filer mon voleur jusqu'…
- `ev-60c96b27d6` (revision 1, original_context, located): …u'aux Indes ». Chapitre 9 : « [en débarquant en Égypte] ».
- `ev-75a4d1fa87` (revision 1, original_context, located): …Verne. Chapitre 1 : « j'étais [sergent de pompiers, à Paris] » ; « je suis valet de chambr…
- `ev-7962c7e3a2` (revision 1, original_context, located): …r une dépêche à Londres » ; « [filer mon voleur jusqu'aux Indes] ». Chapitre 9 : « en débarqua…
- `ev-7c2a34f83e` (revision 1, original_context, located): …hapitre 3 : « ont été envoyés [en Amérique et en Europe] ». Chapitre 8 : « Lancer une …
- `ev-906a1a54d7` (revision 1, original_context, located): …ux Indes ». Chapitre 9 : « en [débarquant en Égypte] ».

## Known confusions

- `k-32f4087a06b6`: not « en Japon » but « au Japon » — « Japon » is masculine and begins with a consonant, so « à » + « le » gives « au ». (evidence ; missed in practice: 0)

## Suggested next exercises

- `p-cf2ec01246c8` explain (unaided recall of the rule): From memory, without looking: when do you use « à » and when « en »? Give one example of each.
- `p-10a28f330355` choose (recognition between confusable forms): Où habite ta sœur ? (Lyon) — Elle habite __ Lyon. Options: à / en.
- `p-f9efb7256976` choose (recognition between confusable forms): Où vas-tu cet été ? (l’Espagne) — Je vais __ Espagne. Options: à / en.
- `p-04705161a655` produce (production in a new sentence): Où vas-tu cet été ? (l’Espagne) Answer with « à » or « en ».
- `p-919b6c108284` produce (production in a new sentence): Où habite ta sœur ? (Lyon) Answer with « à » or « en ».

## Not included

- rejected, pending and needs-review drafts
- the texts of your attempts (only counts of missed items)
- the full question, its context and any chat (only the cited excerpts)
- other sources and unrelated history
- credentials, machine-local paths, session links and e-mail addresses (checked)

## Origin of each exercise

- `p-cf2ec01246c8`: built from the learner's approved knowledge
- `p-10a28f330355`: built from the learner's approved knowledge
- `p-f9efb7256976`: built from the learner's approved knowledge
- `p-04705161a655`: built from the learner's approved knowledge
- `p-919b6c108284`: built from the learner's approved knowledge

## Proposed by an agent, NOT accepted by the learner (not knowledge)

- none

## Use it in a fresh agent session

1. Make an empty directory and copy `packet.md`, `packet.json` and the prompt for your agent into it: `PROMPT-codex.md`, `PROMPT-claude-code.md`, or `PROMPT-any-agent.md` for any other agent that reads Markdown.
2. Codex: `codex --sandbox workspace-write "$(cat PROMPT-codex.md)"`
3. Claude Code: `claude "$(cat PROMPT-claude-code.md)"`
4. Back in FLH, preview what the agent returned (read-only): `python3 -B -m flh_extraction practice2 import-preview --packet packet.json --proposals proposals.json`

## How to return proposals

Return one JSON object with `"packet_id": "pk-0e06b9c6b9c4"`, `"agent"` (your tool's short name) and a `proposals` list. With corrections only, use `"schema": "flh_agent_proposals_v1"`; with any exercise, use `"schema": "flh_agent_proposals_v2"`. Every proposal has `proposal_id`, `type` (`correction` or `exercise`), `rationale` and `evidence_ids` (packet IDs only; leave it empty and say so in the rationale when the packet does not support the proposal). A correction names `target_id` and `text`.

An exercise has `"exercise_schema": "flh_exercise_proposal_v1"`, `kind` (explanation, discrimination or production), `rule_id` (an approved claim or contrast above), `source` (copy this packet's source object), `prompt`; a discrimination adds `options` and `answer`, a production `answer`, `accepted` (every valid variant) and `rubric`, an explanation `reference`. List any case where the rule allows more than one answer under `ambiguity`.
