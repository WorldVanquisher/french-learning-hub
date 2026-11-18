# Reviewer sample v1 — held-out references (35 items)

> **OFFLINE ONLY: synthetic, machine-authored references with no model output and no learner data. Nothing here measures a model; only a person's verdict below counts as review.**

Fill `review` and `verdict` in `review-sample-v1.jsonl` (one JSON object per line). Answer **learning intent** (I1–I2) first, then **wording** (W1–W4) for each unit, only when the objective itself is right. A disputed item needs `dispute_position`. `review-agreement` reports intent and wording separately and never counts an unresolved dispute.

Selection (frozen; salt `flh154-review-sample-v1`; slice `de4c61e570909483…`, challenge `b004f6ed1bc82e6f…`): {"objective": 20, "zero": 3, "false_premise": 2, "over_general": 2, "cue_dispute": 3, "challenge": 3, "rb_anchor": 2}; 25 objective points covered; 8 disputed.

## Rubric

| Question | Mark yes, e.g. | Mark no, e.g. |
|---|---|---|
| **I1** Decision: from the learner's text and context alone, is « units » vs « zero units » right? The category and explanation are evidence, not authority. | ext-trn-i2-0153 « Correction demandée : Je vais en Lyon en pied. » → units: the learner asks for a correction. bc-004 « J'ai regardé un film français hier soir, c'était super. » (journal) → zero: correct French with no question, correction or doubt. | bc-001 « Merci beaucoup, c'est beaucoup plus clair maintenant ! » (after a talk on the subjunctive) with a unit on the subjunctive: thanks raise no objective in this interaction. |
| **I2** Objectives: is the set right — none missing, none extra, each unit one objective? | ext-trn-i2-0167 « Ma voisine est petit et blond. » → one unit (adjective agreement): two adjectives, one rule. | ext-trn-00235 « Elle est une acteuse » → « C'est une actrice » labelled with the « -trice » unit only: the « c'est / il est » objective is missing (UNDER_SPLIT). Splitting « vouloir — je veux » and « vouloir — nous voulons » into two units is the opposite error (OVER_SPLIT). |
| **W1** statement: true, and not over-general for what it claims? | « Ne… que means only; it is a restriction, not a negation: je n'ai que dix euros ». | « After a negation, the articles un, une, du, de la, des become de » (ext-trn-i2-0001): false after « être » (« ce n'est pas un problème »). Mark no and write the fix (FALSE_CLAIM). |
| **W2** statement_zh: says the same thing (scope, claim, French forms)? It is a translation of statement, so the two are ONE claim: their agreement never confirms the claim. | « ne… que » 意为“只、仅”，表示限制而不是否定 for the statement above. | EN « grâce à introduces a positive cause » with ZH « grâce à 表示原因 »: the ZH drops « positive ». |
| **W3** canonical: names the objective the learner raised? | ext-trn-00018 « How do I say not anymore in French? » → « ne… plus ». | ext-trn-00377 « Location, c'est l'endroit où se trouve l'hôtel ? » → « louer (deux sens) »: the question is the false friend « location » (= rental), not the two senses of « louer ». |
| **W4** example: correct French that illustrates this objective (or null)? | « Il ne mange jamais de viande. » for « ne… jamais ». | ext-trn-00051 (« J'y pense » corrected to « je pense à lui ») with the example « Ton examen ? J'y pense tous les jours. »: it shows the thing case; the learner's error was the person case. |
| **Dispute** When `dispute.status` is disputed: answer I1–W4 as usual, then write which position you take and why in `dispute_position`. Never change the reference silently; use verdict `quarantine` when reasonable people disagree. | ext-trn-i2-0070 « Merci pour ton aide avec la conjugaison hier soir ! »: the cue says `morphology` (it matched « conjugaison ») while the reference is zero units — two machine sources disagree, so the item stays disputed until a person decides. | A scheduling message whose cue is `other` and whose reference is zero: nothing to dispute. |

Verdict: accept / edit (write the fix) / reject / quarantine; reviewer and date.

Rubric examples come from training, increment and boundary records, never from this sample.

## Items

### 1. `ext-evl-0020` · frozen · objective

- input: Moi : Je n'ai aucunes idées. ⏎ Tuteur : On dit plutôt « Je n'ai aucune idée. ».
- context: Extrait d'une conversation écrite avec mon tuteur.
- cues `frozen`: `grammar` / `accepted` — « Aucun » is normally singular.
- reference unit (grammar) **ne… aucun(e)**: « Ne… aucun(e) » means « not a single, no »: it agrees with the noun and is normally singular: « je n'ai aucune idée ».
  - zh: « ne… aucun(e) » 意为“一个也没有”，与名词配合，通常用单数：« je n'ai aucune idée »。
  - example: Il n'y a aucun problème.
- rationale: A tutor correction in a dialogue; the objective is « ne… aucun(e) ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 2. `ext-evl-0095` · frozen · objective

- input: Ce matin, le bus avait vingt minutes de retard. Après le travail, je retourne chez moi. [?] Samedi matin, je suis allée à la piscine avec ma voisine.
- context: Mon journal ; j'ai mis [?] là où j'ai un doute.
- cues `frozen`: `vocabulary` / `accepted` — The marked sentence should be « Après le travail, je rentre chez moi. ». Going home is « rentrer ».
- reference unit (vocabulary) **rentrer / retourner / revenir**: « Rentrer » means going back home, « retourner » going back to another place, and « revenir » coming back to where the speaker is.
  - zh: « rentrer » 指回家，« retourner » 指回到别的地方，« revenir » 指回到说话人所在的地方。
  - example: Je rentre à la maison à six heures.
- rationale: Only the marked sentence raised a doubt; the objective is « rentrer / retourner / revenir ». The other sentences are correct and not objectives.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 3. `ext-evl-0070` · frozen · objective

- input: « neuf » 的阴性怎么写？
- context: —
- cues `frozen`: `morphology` / `accepted` — « -f » becomes « -ve ».
- reference unit (morphology) **féminin en -ve (neuf → neuve, actif → active)**: Adjectives ending in « -f » form their feminine in « -ve »: « neuf → neuve », « actif → active ».
  - zh: 以 « -f » 结尾的形容词阴性变为 « -ve »：« neuf → neuve »、« actif → active »。
  - example: C'est une personne très active.
- rationale: A question written in Chinese about « féminin en -ve (neuf → neuve, actif → active) »; one objective.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 4. `ext-evl-0118` · frozen · objective

- input: Moi : Merci pour le rapport. Bisous, Léa ⏎ Tuteur : On dit plutôt « Merci pour le rapport. Bonne journée, Léa ».
- context: Extrait d'une conversation écrite avec mon tuteur.
- cues `frozen`: `pragmatics` / `accepted` — « Bisous » is for close relationships only.
- reference unit (usage) **bisous (fin de message familière)**: « Bisous » or « bises » close a message only between family and friends; at work use « Cordialement » or « Bonne journée ».
  - zh: « bisous » 或 « bises » 只用于家人朋友之间的信息结尾；工作中用 « Cordialement » 或 « Bonne journée »。
  - example: À samedi, bisous !
- rationale: A tutor correction in a dialogue; the objective is « bisous (fin de message familière) ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 5. `ext-evl-0135` · frozen · objective

- input: Brouillon de mail : « Bonjour, Il pleut, on reste à la maison ? Tant mieux, je voulais sortir. Merci d'avance. »
- context: Commentaire de ma correctrice : « Tant pis » accepts a disappointment.
- cues `frozen`: `vocabulary` / `accepted` — « Tant pis » accepts a disappointment.
- reference unit (expression) **tant pis / tant mieux**: « Tant mieux » means « good, so much the better » and « tant pis » means « too bad, never mind ».
  - zh: « tant mieux » 意为“那更好”，« tant pis » 意为“算了、真遗憾”。
  - example: Le magasin est fermé ? Tant pis.
- rationale: One correction comment; the objective is « tant pis / tant mieux ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 6. `ext-evl-0043` · frozen · objective

- input: Le soir, nous avons préparé une soupe de légumes. J'ai réussi à cause de mon professeur. [?] Mon collègue m'a prêté un bon livre.
- context: Mon journal ; j'ai mis [?] là où j'ai un doute.
- cues `frozen`: `vocabulary` / `accepted` — The marked sentence should be « J'ai réussi grâce à mon professeur. ». A positive cause takes « grâce à ».
- reference unit (vocabulary) **à cause de / grâce à**: « Grâce à » introduces a positive cause and « à cause de » a negative or neutral one: « grâce à toi », « à cause de la pluie ».
  - zh: « grâce à » 引出积极的原因，« à cause de » 引出消极或中性的原因：« grâce à toi »、« à cause de la pluie »。
  - example: Grâce à ton aide, j'ai réussi.
- rationale: Only the marked sentence raised a doubt; the objective is « à cause de / grâce à ». The other sentences are correct and not objectives.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 7. `ext-evl-0040` · frozen · objective

- input: Après le dîner, j'ai appelé mes parents. Après manger, il est sorti. [?] Il faisait un peu frais, alors j'ai pris un pull.
- context: Mon journal ; j'ai mis [?] là où j'ai un doute.
- cues `frozen`: `grammar` / `accepted` — The marked sentence should be « Après avoir mangé, il est sorti. ». « Après » takes the past infinitive.
- reference unit (grammar) **après + infinitif passé**: « Après » is followed by the past infinitive, « avoir / être » + past participle: « après avoir mangé, il est sorti ».
  - zh: « après » 后接过去不定式，即 « avoir / être » 加过去分词：« après avoir mangé, il est sorti »。
  - example: Après être rentrée, elle a dîné.
- rationale: Only the marked sentence raised a doubt; the objective is « après + infinitif passé ». The other sentences are correct and not objectives.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 8. `ext-evl-0012` · frozen · objective

- input: Brouillon de mail : « Bonjour, Ma voiture et celui de Paul sont rouges. Merci d'avance. »
- context: Commentaire de ma correctrice : « Celle » replaces a feminine noun.
- cues `frozen`: `grammar` / `accepted` — « Celle » replaces a feminine noun.
- reference unit (grammar) **celui / celle (pronoms démonstratifs)**: « Celui, celle, ceux, celles » replace a noun already mentioned and agree with it: « ma voiture et celle de Paul ».
  - zh: « celui, celle, ceux, celles » 替代前面提到的名词，并与之性数一致：« ma voiture et celle de Paul »。
  - example: Je préfère ce pull à celui-là.
- rationale: One correction comment; the objective is « celui / celle (pronoms démonstratifs) ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 9. `ext-evl-0051` · frozen · objective

- input: Moi : J'ai fini à manger. ⏎ Tuteur : On dit plutôt « J'ai fini de manger. ».
- context: Extrait d'une conversation écrite avec mon tuteur.
- cues `frozen`: `grammar` / `accepted` — « Finir » takes « de ».
- reference unit (grammar) **commencer à / finir de + infinitif**: « Commencer » takes « à » and « finir » takes « de » before an infinitive: « je commence à travailler », « je finis de manger ».
  - zh: « commencer » 接不定式时用 « à »，« finir » 用 « de »：« je commence à travailler »、« je finis de manger »。
  - example: Il a commencé à pleuvoir.
- rationale: A tutor correction in a dialogue; the objective is « commencer à / finir de + infinitif ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 10. `ext-evl-0014` · frozen · objective

- input: Dimanche, on a fait une longue promenade au bord du lac. C'est ta valise ou la mien ? [?] Mon cours de français commence à dix-huit heures.
- context: Mon journal ; j'ai mis [?] là où j'ai un doute.
- cues `frozen`: `grammar` / `accepted` — The marked sentence should be « C'est ta valise ou la mienne ? ». The pronoun agrees with « valise »: « la mienne ».
- reference unit (grammar) **le mien / la mienne (pronoms possessifs)**: Possessive pronouns agree with the thing owned: « le mien, la mienne, les miens, les miennes »: « ce n'est pas ton stylo, c'est le mien ».
  - zh: 主有代词与所属物配合：« le mien, la mienne, les miens, les miennes »：« ce n'est pas ton stylo, c'est le mien »。
  - example: Ta maison est plus grande que la mienne.
- rationale: Only the marked sentence raised a doubt; the objective is « le mien / la mienne (pronoms possessifs) ». The other sentences are correct and not objectives.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 11. `ext-evl-0106` · frozen · objective

- input: La bibliothèque du quartier ferme tard le jeudi. Après trois heures d'attente, éventuellement le train est arrivé. [?] Après le dîner, j'ai appelé mes parents.
- context: Mon journal ; j'ai mis [?] là où j'ai un doute.
- cues `frozen`: `vocabulary` / `accepted` — The marked sentence should be « Après trois heures d'attente, finalement le train est arrivé. ». « Éventuellement » = possibly; « finalement » = eventually.
- reference unit (vocabulary) **éventuellement (faux ami)**: « Éventuellement » means « possibly, if need be », not « eventually » (which is « finalement » or « à la fin »).
  - zh: « éventuellement » 意为“可能、必要时”，不是英语 eventually（“最终”应说 « finalement » 或 « à la fin »）。
  - example: Je pourrais éventuellement venir samedi.
- rationale: Only the marked sentence raised a doubt; the objective is « éventuellement (faux ami) ». The other sentences are correct and not objectives.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 12. `ext-evl-0131` · frozen · objective

- input: “小心台阶”怎么说？
- context: —
- cues `frozen`: `vocabulary` / `accepted` — The expression is « faire attention à ».
- reference unit (expression) **faire attention à**: « Faire attention à » means « to pay attention to, to be careful of »: « fais attention à la marche ».
  - zh: « faire attention à » 意为“注意、小心”：« fais attention à la marche »。
  - example: Faites attention aux voitures.
- rationale: A question written in Chinese about « faire attention à »; one objective.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 13. `ext-evl-0124` · frozen · objective

- input: Moi : C'est mieux de partir tôt, il est meilleur. ⏎ Tuteur : On dit plutôt « Il vaut mieux partir tôt. ».
- context: Extrait d'une conversation écrite avec mon tuteur.
- cues `frozen`: `grammar` / `accepted` — The fixed form is « il vaut mieux » + infinitive.
- reference unit (expression) **il vaut mieux + infinitif**: « Il vaut mieux » + infinitive means « it is better to »: « il vaut mieux partir tôt ».
  - zh: « il vaut mieux » 加不定式意为“最好……”：« il vaut mieux partir tôt »。
  - example: Il vaut mieux réserver.
- rationale: A tutor correction in a dialogue; the objective is « il vaut mieux + infinitif ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 14. `ext-evl-0091` · frozen · objective

- input: Moi : Je lis « Ma fille habite en ville. » à voix haute, c'est comme ça ? ⏎ Tuteur : « Ville », « mille », « tranquille » are exceptions.
- context: Extrait d'une conversation écrite avec mon tuteur.
- cues `frozen`: `pronunciation` / `accepted` — « Ville », « mille », « tranquille » are exceptions.
- reference unit (pronunciation) **-ille [ij] (fille) / ville, mille, tranquille [il]**: The spelling « -ille » usually sounds [ij] (« fille », « famille »), but « ville », « mille » and « tranquille » are said with [il].
  - zh: « -ille » 通常读 [ij]（« fille »、« famille »），但 « ville »、« mille »、« tranquille » 读 [il]。
  - example: Ma fille habite en ville.
- rationale: A tutor correction in a dialogue; the objective is « -ille [ij] (fille) / ville, mille, tranquille [il] ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 15. `ext-evl-0073` · frozen · objective

- input: « ils on fini » 对吗？
- context: —
- cues `frozen`: `orthography` / `accepted` — With « ils » the verb is « ont ».
- reference unit (orthography) **on / ont**: « On » is a subject pronoun and « ont » is « avoir » with « ils / elles »: « on a faim », « ils ont faim ».
  - zh: « on » 是主语代词，« ont » 是 « avoir » 与 « ils / elles » 搭配的形式：« on a faim »、« ils ont faim »。
  - example: Ils ont deux enfants.
- rationale: A question written in Chinese about « on / ont »; one objective.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 16. `ext-evl-0100` · frozen · objective

- input: Moi : Je quitte à huit heures. ⏎ Tuteur : On dit plutôt « Je pars à huit heures. ».
- context: Extrait d'une conversation écrite avec mon tuteur.
- cues `frozen`: `grammar` / `accepted` — « Quitter » needs an object; use « partir ».
- reference unit (grammar) **quitter (+ COD) / partir (de)**: « Quitter » needs a direct object (« je quitte la maison »); « partir » has none or takes « de » (« je pars de la maison »).
  - zh: « quitter » 需要直接宾语（« je quitte la maison »）；« partir » 不带宾语或接 « de »（« je pars de la maison »）。
  - example: Il a quitté Paris en 2020.
- rationale: A tutor correction in a dialogue; the objective is « quitter (+ COD) / partir (de) ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 17. `ext-evl-0085` · frozen · objective

- input: Moi : Je lis « Je n'ai plus faim. » à voix haute, c'est comme ça ? ⏎ Tuteur : Negative « plus » has no s sound.
- context: Extrait d'une conversation écrite avec mon tuteur.
- cues `frozen`: `pronunciation` / `accepted` — Negative « plus » has no s sound.
- reference unit (pronunciation) **prononciation de « plus » ([ply] / [plys])**: « Plus » is said [ply] in a negation (« je n'en veux plus ») and usually [plys] when it means « more » at the end of a phrase (« j'en veux plus »).
  - zh: « plus » 在否定中读 [ply]（« je n'en veux plus »），表示“更多”且位于句末时通常读 [plys]（« j'en veux plus »）。
  - example: Je n'ai plus faim.
- rationale: A tutor correction in a dialogue; the objective is « prononciation de « plus » ([ply] / [plys]) ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 18. `ext-evl-0105` · frozen · objective

- input: Moi : Le train m'a manqué ce matin. ⏎ Tuteur : On dit plutôt « J'ai raté le train ce matin. ».
- context: Extrait d'une conversation écrite avec mon tuteur.
- cues `frozen`: `vocabulary` / `accepted` — « Le train m'a manqué » means you missed the train emotionally.
- reference unit (vocabulary) **rater / manquer (un train)**: Missing a train or bus is « rater » or « manquer le train »; « manquer à quelqu'un » means being missed by someone.
  - zh: 错过火车或公交车说 « rater » 或 « manquer le train »；« manquer à quelqu'un » 则是“让某人想念”。
  - example: J'ai raté le dernier métro.
- rationale: A tutor correction in a dialogue; the objective is « rater / manquer (un train) ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 19. `ext-evl-0077` · frozen · objective

- input: Brouillon de mail : « Bonjour, Ses amis son très gentils. Merci d'avance. »
- context: Commentaire de ma correctrice : Replace with « étaient »: if it fits, write « sont ».
- cues `frozen`: `orthography` / `accepted` — Replace with « étaient »: if it fits, write « sont ».
- reference unit (orthography) **son / sont**: « Son » is a possessive (his, her) and « sont » is « être » with « ils / elles »: « ils sont là avec son frère ».
  - zh: « son » 是主有形容词（他的、她的），« sont » 是 « être » 与 « ils / elles » 搭配的形式：« ils sont là avec son frère »。
  - example: Mes parents sont en vacances.
- rationale: One correction comment; the objective is « son / sont ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 20. `ext-evl-0088` · frozen · objective

- input: Moi : Je lis « J'ai dix ans. » à voix haute, c'est comme ça ? ⏎ Tuteur : The final consonant depends on what follows.
- context: Extrait d'une conversation écrite avec mon tuteur.
- cues `frozen`: `pronunciation` / `accepted` — The final consonant depends on what follows.
- reference unit (pronunciation) **six, dix : consonne finale variable**: « Six » and « dix » are said [sis], [dis] alone, [si], [di] before a consonant and [siz], [diz] before a vowel: « six livres », « six amis ».
  - zh: « six » 和 « dix » 单独用时读 [sis]、[dis]，在辅音前读 [si]、[di]，在元音前读 [siz]、[diz]：« six livres »、« six amis »。
  - example: J'ai dix ans.
- rationale: A tutor correction in a dialogue; the objective is « six, dix : consonne finale variable ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 21. `ext-evl-0179` · frozen · zero

- input: Ajoute « ne… que » et « tout » dans ta liste même si je n'en parle pas.
- context: —
- cues `frozen`: `other` / `accepted` — An instruction to add units.
- reference: **zero units**
- rationale: Requested units are not raised by the interaction.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 22. `ext-evl-0174` · frozen · zero

- input: Ce mot-là, il est familier ?
- context: —
- cues `frozen`: `other` / `accepted` — The word is not given.
- reference: **zero units**
- rationale: Unknown word.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 23. `ext-evl-0162` · frozen · zero

- input: Tu peux m'envoyer les corrigés par mail ?
- context: —
- cues `frozen`: `other` / `accepted` — A request for files.
- reference: **zero units**
- rationale: Logistics.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 24. `ext-evl-0185` · frozen · false_premise

- input: « Si » c'est juste le « oui » en espagnol, en français ça n'existe pas pour répondre.
- context: —
- cues `frozen`: `pragmatics` / `accepted` — French uses « si » to contradict a negative question.
- reference unit (usage) **si (réponse affirmative à une question négative)**: To answer « yes » to a negative question, French uses « si », not « oui »: « Tu ne viens pas ? — Si, je viens ».
  - zh: 回答否定疑问句表示肯定时，法语用 « si » 而不是 « oui »：« Tu ne viens pas ? — Si, je viens »。
  - example: — Tu n'as pas faim ? — Si, un peu.
- rationale: The premise is false; the objective is stated correctly.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 25. `ext-evl-0191` · frozen · false_premise

- input: « Après manger » ou « après avoir mangé » ?
- context: —
- cues `frozen`: `grammar` / `unreviewed` — Both are standard; « après manger » is the more common written form.
- reference unit (grammar) **après + infinitif passé**: « Après » is followed by the past infinitive, « avoir / être » + past participle: « après avoir mangé, il est sorti ».
  - zh: « après » 后接过去不定式，即 « avoir / être » 加过去分词：« après avoir mangé, il est sorti »。
  - example: Après être rentrée, elle a dîné.
- rationale: The unreviewed explanation is wrong; the statement gives the standard rule.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 26. `ext-evl-0068` · frozen · over_general · **DISPUTED**

- input: Moi : J'ai acheté des chaussures marrons. ⏎ Tuteur : On dit plutôt « J'ai acheté des chaussures marron. ».
- context: Extrait d'une conversation écrite avec mon tuteur.
- cues `frozen`: `morphology` / `accepted` — « Marron » is invariable.
- reference unit (morphology) **adjectifs de couleur invariables (marron, orange)**: Colour words that come from nouns, such as « marron » and « orange », do not agree: « des chaussures marron ».
  - zh: 由名词转来的颜色词如 « marron »、« orange » 不配合：« des chaussures marron »。
  - example: Elle porte des gants orange.
- rationale: A tutor correction in a dialogue; the objective is « adjectifs de couleur invariables (marron, orange) ».
- dispute (raised by agent reading (FLH-154 agent-review.json)):
  - reference: Colour words that come from nouns, such as « marron » and « orange », do not agree: « des chaussures marron ».
  - agent: « Colour words that come from nouns do not agree » is over-general: « rose, mauve, fauve, écarlate » come from nouns and agree. Suggest « most colour words … such as marron, orange ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 27. `ext-evl-0137` · frozen · over_general · **DISPUTED**

- input: Moi : — Tu ne viens pas ce soir ? — Oui, je viens ! La chaise sur que je suis assis est cassée. ⏎ Tuteur : Deux remarques : « — Tu ne viens pas ce soir ? — Si, je viens ! » et « La chaise sur laquelle je suis assis est cassée. ».
- context: Extrait d'une conversation écrite avec mon tuteur.
- cues `frozen`: `mixed` / `accepted` — After a negative question, « si » contradicts the negation. After « sur » use « laquelle », not « que ».
- reference unit (usage) **si (réponse affirmative à une question négative)**: To answer « yes » to a negative question, French uses « si », not « oui »: « Tu ne viens pas ? — Si, je viens ».
  - zh: 回答否定疑问句表示肯定时，法语用 « si » 而不是 « oui »：« Tu ne viens pas ? — Si, je viens »。
  - example: — Tu n'as pas faim ? — Si, un peu.
- reference unit (grammar) **lequel / laquelle après une préposition**: After a preposition, a relative pronoun referring to a thing is « lequel, laquelle, lesquels, lesquelles »: « la table sur laquelle j'écris ».
  - zh: 介词后指代事物的关系代词用 « lequel, laquelle, lesquels, lesquelles »：« la table sur laquelle j'écris »。
  - example: Voici l'outil avec lequel je travaille.
- rationale: Two distinct corrections: « si (réponse affirmative à une question négative) » and « lequel / laquelle après une préposition ».
- dispute (raised by agent reading (FLH-154 agent-review.json)):
  - reference: After a preposition, a relative pronoun referring to a thing is « lequel, laquelle, lesquels, lesquelles »: « la table sur laquelle j'écris ».
  - agent: Reads as if every preposition takes « lequel »; after « de » French uses « dont » (« duquel » in compound prepositions).
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 28. `chl-g21` · challenge_test · cue_dispute · **DISPUTED**

- input: Merci beaucoup pour tes corrections d'hier, j'ai tout relu ce matin !
- context: —
- cues `aligned`: `other` / `accepted` — Thanks for corrections; no French question.
- cues `conflicting`: `grammar` / `unreviewed` — Possible question about « tout » used as a pronoun (« j'ai tout relu »).
- cues `rb`: `grammar` / `unreviewed` — Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- reference: **zero units**
- rationale: A thank-you message: nothing durable arose; a rule only the explanation names is not an objective.
- dispute (raised by conflicting cue (machine analysis)):
  - reference: zero units (A thank-you message: nothing durable arose; a rule only the explanation names is not an objective.)
  - cue: grammar — Possible question about « tout » used as a pronoun (« j'ai tout relu »). (names « tout », « j'ai tout relu », present in the learner's text)
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 29. `chl-g26` · challenge_test · cue_dispute · **DISPUTED**

- input: Je pars à Lyon samedi avec ma sœur, on va visiter le musée des Confluences.
- context: —
- cues `aligned`: `other` / `accepted` — Weekend plans written in correct French; no question or correction.
- cues `conflicting`: `vocabulary` / `unreviewed` — Prepositions with cities: « à Lyon ».
- cues `rb`: `grammar` / `unreviewed` — Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- reference: **zero units**
- rationale: A correct sentence about plans with no question, correction or uncertainty.
- dispute (raised by conflicting cue (machine analysis)):
  - reference: zero units (A correct sentence about plans with no question, correction or uncertainty.)
  - cue: vocabulary — Prepositions with cities: « à Lyon ». (names « à Lyon », present in the learner's text)
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 30. `chl-g31` · challenge_test · cue_dispute · **DISPUTED**

- input: Combien de leçons reste-t-il avant la fin du module ?
- context: —
- cues `aligned`: `other` / `accepted` — A question about the course schedule.
- cues `conflicting`: `grammar` / `unreviewed` — Question formation with « combien de ».
- cues `rb`: `grammar` / `unreviewed` — Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- reference: **zero units**
- rationale: A question about the course, in correct French; no question, correction or uncertainty about French.
- dispute (raised by conflicting cue (machine analysis)):
  - reference: zero units (A question about the course, in correct French; no question, correction or uncertainty about French.)
  - cue: grammar — Question formation with « combien de ». (names « combien de », present in the learner's text)
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 31. `chl-g10` · challenge_test · challenge

- input: J'ai écrit « J'ai fini à préparer le dîner » et la prof a mis « fini de ». Pourquoi « de » ici ?
- context: —
- cues `aligned`: `grammar` / `accepted` — « Finir » takes « de » before an infinitive.
- cues `conflicting`: `other` / `unreviewed` — Logistics and small talk; nothing to extract.
- cues `rb`: `grammar` / `unreviewed` — Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- reference unit (grammar) **commencer à / finir de + infinitif**: « Commencer » takes « à » and « finir » takes « de » before an infinitive: « je commence à travailler », « je finis de manger ».
  - zh: « commencer » 接不定式时用 « à »，« finir » 用 « de »：« je commence à travailler »、« je finis de manger »。
  - example: Il a commencé à pleuvoir.
- rationale: The learner asks about this objective directly; the reference keeps it whatever the cues say.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 32. `chl-g18` · challenge_test · challenge · **DISPUTED**

- input: Deux corrections dans mon texte : « des rideaux marrons » → « des rideaux marron », et « C'est ton sac ou le mienne ? » → « le mien ». Je ne vois pas la règle pour le premier.
- context: —
- cues `aligned`: `mixed` / `accepted` — Two corrections: « marron » is invariable, and the possessive pronoun agrees with « sac » (« le mien »).
- cues `conflicting`: `other` / `unreviewed` — Logistics and small talk; nothing to extract.
- cues `rb`: `grammar` / `unreviewed` — Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- reference unit (morphology) **adjectifs de couleur invariables (marron, orange)**: Colour words that come from nouns, such as « marron » and « orange », do not agree: « des chaussures marron ».
  - zh: 由名词转来的颜色词如 « marron »、« orange » 不配合：« des chaussures marron »。
  - example: Elle porte des gants orange.
- reference unit (grammar) **le mien / la mienne (pronoms possessifs)**: Possessive pronouns agree with the thing owned: « le mien, la mienne, les miens, les miennes »: « ce n'est pas ton stylo, c'est le mien ».
  - zh: 主有代词与所属物配合：« le mien, la mienne, les miens, les miennes »：« ce n'est pas ton stylo, c'est le mien »。
  - example: Ta maison est plus grande que la mienne.
- rationale: Two separate corrections; the learner asks about the first, the second is reported.
- dispute (raised by agent reading (FLH-154 agent-review.json)):
  - reference: Colour words that come from nouns, such as « marron » and « orange », do not agree: « des chaussures marron ».
  - agent: « Colour words that come from nouns do not agree » is over-general: « rose, mauve, fauve, écarlate » come from nouns and agree. Suggest « most colour words … such as marron, orange ».
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 33. `chl-g32` · challenge_test · challenge

- input: 我下周要出差，课程暂停两周。
- context: —
- cues `aligned`: `other` / `accepted` — The learner pauses the course; no French content.
- cues `conflicting`: `translation` / `unreviewed` — Translation request about a business trip.
- cues `rb`: `vocabulary` / `unreviewed` — Local classification selected "vocabulary" because rule "single_token_fallback" input is a single token with alphabetic content (weak lexical guess).
- reference: **zero units**
- rationale: A scheduling message in Chinese; nothing to extract.
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 34. `ext-evl-0128#rb` · rb · rb_anchor · **DISPUTED**

- input: “你说得对”怎么说？
- context: —
- cues `rb`: `translation` / `unreviewed` — Local classification selected "translation" because rule "explicit_translation_request" matched "怎么说" in the input.
- reference unit (expression) **avoir raison / avoir tort**: French says « avoir raison » (to be right) and « avoir tort » (to be wrong), with « avoir »: « tu as raison ».
  - zh: 法语用 « avoir » 表达“对”和“错”：« avoir raison »、« avoir tort »：« tu as raison »。
  - example: Tu as tort, c'est mardi.
- rationale: A question written in Chinese about « avoir raison / avoir tort »; one objective.
- dispute (raised by heuristic anchoring):
  - reference (inherited from ext-evl-0128): units ['avoir raison / avoir tort']
  - heuristic: under the rb view no French form of this unit is visible; the explanation that spelled it out was replaced by the production analyzer's
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

### 35. `ext-evl-0046#rb` · rb · rb_anchor · **DISPUTED**

- input: 表示“然而”应该用哪个连接词？
- context: —
- cues `rb`: `vocabulary` / `unreviewed` — Local classification selected "vocabulary" because rule "single_token_fallback" input is a single token with alphabetic content (weak lexical guess).
- reference unit (vocabulary) **pourtant (concession)**: « Pourtant » means « yet, and still », marking a contrast with what was expected: « il a beaucoup travaillé, pourtant il a échoué ».
  - zh: « pourtant » 意为“然而、可是”，表示与预期相反的转折：« il a beaucoup travaillé, pourtant il a échoué »。
  - example: Il fait beau, pourtant il fait froid.
- rationale: A question written in Chinese about « pourtant (concession) »; one objective.
- dispute (raised by heuristic anchoring):
  - reference (inherited from ext-evl-0046): units ['pourtant (concession)']
  - heuristic: under the rb view no French form of this unit is visible; the explanation that spelled it out was replaced by the production analyzer's
- I1 ☐ yes ☐ no · I2 ☐ yes ☐ no · W1–W4 per unit · verdict ☐ accept ☐ edit ☐ reject ☐ quarantine

