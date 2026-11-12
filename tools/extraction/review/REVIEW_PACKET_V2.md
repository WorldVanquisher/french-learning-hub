# Extraction review packet (prioritized, 25 items)

Every label below is **machine-authored and unreviewed**. Fill `verdict` in the JSONL twin of this file; only `accept` (or a re-checked `edit`) may move a label to `human_reviewed`.

Rubric: decision right? · per unit: grounded / true / atomic / granularity / kind / canonical / EN–ZH agree / example · verdict: accept / edit / reject / quarantine.

| Priority | Meaning |
|---|---|
| 1 | Decisions behind many labels: zero units under production categories; inherited probe references |
| 2 | New false-premise and wrong-explanation labels (highest authoring risk) |
| 3 | Splitting boundaries (two errors, several edits of one rule, fragmentation) |
| 4 | Base labels flagged by the audit as possibly under-split |
| 5 | Explanations that add rules the learner did not raise |

## 1. P1 · `ext-trn-i2-0070` (increment)

**Question:** Is zero units right although the production analyzer gives a non-`other` category?

- input: Merci pour ton aide avec la conjugaison hier soir !
- context: —
- category / resolution: `morphology` / `unreviewed`
- explanation: Local classification selected "morphology" because rule "explicit_morphology_request" matched "conjugaison" in the input.
- expected: **zero units**
- rationale: Thanks naming a past topic; nothing new is asked, corrected or revealed. The analyzer's category is a cue, not an objective.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 2. P1 · `ext-trn-i2-0072` (increment)

**Question:** Is zero units right although the production analyzer gives a non-`other` category?

- input: Thanks! The pronunciation videos you sent were great.
- context: —
- category / resolution: `pronunciation` / `unreviewed`
- explanation: Local classification selected "pronunciation" because rule "explicit_pronunciation_request" matched "pronunciation" in the input.
- expected: **zero units**
- rationale: Thanks about resources; no objective.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 3. P1 · `ext-trn-i2-0076` (increment)

**Question:** Is zero units right for this input under the rule-based fallback category?

- input: Tu peux m'envoyer les exercices de grammaire en PDF ?
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "explicit_grammar_request" matched "grammaire" in the input.
- expected: **zero units**
- rationale: A file request; no objective.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 4. P1 · `ext-evl-0173#rb` (probe-rb)

**Question:** Does the inherited zero-unit reference still hold with the production analyzer's view?

- input: Et là, il faut un accord ?
- context: —
- category / resolution: `morphology` / `unreviewed`
- explanation: Local classification selected "morphology" because rule "explicit_morphology_request" matched "accord" in the input.
- expected: **zero units**
- rationale: Unseen sentence.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 5. P1 · `ext-evl-0191#rb` (probe-rb)

**Question:** With the wrong explanation replaced by the analyzer's, is the inherited unit still the objective?

- input: « Après manger » ou « après avoir mangé » ?
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (grammar) **après + infinitif passé**: « Après » is followed by the past infinitive, « avoir / être » + past participle: « après avoir mangé, il est sorti ».
  - zh: « après » 后接过去不定式，即 « avoir / être » 加过去分词：« après avoir mangé, il est sorti »。
  - example: Après être rentrée, elle a dîné.
- rationale: The unreviewed explanation is wrong; the statement gives the standard rule.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 6. P1 · `ext-evl-0002#rb` (probe-rb)

**Question:** A Chinese question with only the analyzer's fallback explanation: is the inherited unit still right?

- input: « ne… que » 是否定吗？
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (grammar) **ne… que (restriction = seulement)**: « Ne… que » means « only »; it is a restriction, not a negation: « je n'ai que dix euros ».
  - zh: « ne… que » 意为“只、仅”，表示限制而不是否定：« je n'ai que dix euros »。
  - example: Il ne boit que de l'eau.
- rationale: A question written in Chinese about « ne… que (restriction = seulement) »; one objective.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 7. P2 · `ext-trn-i2-0001` (increment)

**Question:** Is the premise really false, and does the unit correct it without repeating it?

- input: Après « pas », on garde « un » ou « une » : « je n'ai pas une voiture », c'est la forme normale.
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (grammar) **pas de / pas d' après la négation**: After a negation, the indefinite and partitive articles « un, une, du, de la, des » become « de » (« d' » before a vowel): « je n'ai pas de voiture ».
  - zh: 否定句中，不定冠词和部分冠词 « un, une, du, de la, des » 变为 « de »（元音前为 « d' »）：« je n'ai pas de voiture »。
  - example: Je n'ai pas de voiture.
- rationale: The premise is false; the unit states the objective correctly and never repeats the learner's claim as true.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 8. P2 · `ext-trn-i2-0008` (increment)

**Question:** Is the premise really false, and does the unit correct it without repeating it?

- input: Le « t » dans « a-t-il », c'est une faute de frappe qu'on voit partout.
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (orthography) **inversion avec -t- (a-t-il)**: In an inverted question, a « -t- » is inserted between a verb ending in a vowel and « il, elle, on »: « a-t-il », « parle-t-elle ».
  - zh: 倒装疑问句中，以元音结尾的动词与 « il, elle, on » 之间要加 « -t- »：« a-t-il »、« parle-t-elle »。
  - example: Où va-t-elle ce soir ?
- rationale: The premise is false; the unit states the objective correctly and never repeats the learner's claim as true.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 9. P2 · `ext-trn-i2-0017` (increment)

**Question:** Is the premise really false, and does the unit correct it without repeating it?

- input: Tous les verbes en -er sont réguliers au futur, même « aller » : « j'allerai ».
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (morphology) **futurs irréguliers (irai, ferai, serai, aurai)**: Some verbs have irregular future stems: « aller → j'irai », « faire → je ferai », « être → je serai », « avoir → j'aurai », « venir → je viendrai ».
  - zh: 有些动词的将来时词干不规则：« aller → j'irai »、« faire → je ferai »、« être → je serai »、« avoir → j'aurai »、« venir → je viendrai »。
  - example: J'irai chez le dentiste lundi.
- rationale: The premise is false; the unit states the objective correctly and never repeats the learner's claim as true.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 10. P2 · `ext-trn-i2-0019` (increment)

**Question:** Is the premise really false, and does the unit correct it without repeating it?

- input: En France, « je veux un café » est aussi poli que « je voudrais un café ».
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (usage) **conditionnel de politesse**: The conditional makes a request polite: « je voudrais », « pourriez-vous », « j'aimerais ».
  - zh: 条件式可以让请求更礼貌：« je voudrais »、« pourriez-vous »、« j'aimerais »。
  - example: Pourriez-vous m'aider, s'il vous plaît ?
- rationale: The premise is false; the unit states the objective correctly and never repeats the learner's claim as true.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 11. P2 · `ext-trn-i2-0039` (increment)

**Question:** Is the premise really false, and does the unit correct it without repeating it?

- input: Dans « ils parlent », on entend un son « an » à la fin, à cause de « -ent ».
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (pronunciation) **-ent muet des verbes (ils parlent)**: The verb ending « -ent » of the « ils » form is silent: « ils parlent » sounds like « il parle ».
  - zh: 动词 « ils » 形式的词尾 « -ent » 不发音：« ils parlent » 读音与 « il parle » 相同。
  - example: Ils chantent bien.
- rationale: The premise is false; the unit states the objective correctly and never repeats the learner's claim as true.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 12. P2 · `ext-trn-i2-0044` (increment)

**Question:** Is the premise really false, and does the unit correct it without repeating it?

- input: « Librairie » veut dire « library » : c'est là qu'on emprunte des livres.
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (vocabulary) **librairie / bibliothèque**: « Une librairie » is a bookshop; a library is « une bibliothèque ».
  - zh: « une librairie » 是书店；图书馆是 « une bibliothèque »。
  - example: J'emprunte des livres à la bibliothèque.
- rationale: The premise is false; the unit states the objective correctly and never repeats the learner's claim as true.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 13. P2 · `ext-trn-i2-0055` (increment)

**Question:** Is the explanation really wrong, and is the unit the correct rule?

- input: J'ai écrit « Bien qu'il est malade, il est venu. ». C'est bon ?
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Correct: « bien que » takes the indicative because the illness is a real fact.
- expected unit (grammar) **bien que + subjonctif**: « Bien que » (although) is always followed by the subjunctive: « bien qu'il soit fatigué, il travaille ».
  - zh: « bien que »（虽然）后面总是接虚拟式：« bien qu'il soit fatigué, il travaille »。
  - example: Bien qu'il pleuve, nous sortons.
- rationale: The unreviewed explanation is wrong; the unit gives the standard rule and the example is not the learner's error.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 14. P2 · `ext-trn-i2-0056` (increment)

**Question:** Is the explanation really wrong, and is the unit the correct rule?

- input: Pourquoi « la maison a été construite » et pas « la maison a construit » ?
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Both are possible: with « avoir » the passive is formed directly from the participle.
- expected unit (grammar) **voix passive : être + participe passé (par)**: The passive is formed with « être » + past participle, which agrees with the subject; the agent is introduced by « par »: « la lettre a été écrite par Paul ».
  - zh: 被动语态由 « être » 加过去分词构成，过去分词与主语配合；施动者由 « par » 引出：« la lettre a été écrite par Paul »。
  - example: Le pont a été construit en 1890.
- rationale: The explanation invents a passive with « avoir »; the unit states the « être » + participle rule.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 15. P2 · `ext-trn-i2-0057` (increment)

**Question:** Is the explanation really wrong, and is the unit the correct rule?

- input: Le futur de « aller » : j'irai ou j'allerai ?
- context: —
- category / resolution: `morphology` / `unreviewed`
- explanation: « Aller » is regular in the future: « j'allerai ».
- expected unit (morphology) **futurs irréguliers (irai, ferai, serai, aurai)**: Some verbs have irregular future stems: « aller → j'irai », « faire → je ferai », « être → je serai », « avoir → j'aurai », « venir → je viendrai ».
  - zh: 有些动词的将来时词干不规则：« aller → j'irai »、« faire → je ferai »、« être → je serai »、« avoir → j'aurai »、« venir → je viendrai »。
  - example: J'irai chez le dentiste lundi.
- rationale: The explanation is wrong; the unit gives the irregular stem « ir- ».
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 16. P3 · `ext-trn-i2-0153` (increment)

**Question:** Are there exactly two distinct objectives (no third error, no shared rule)?

- input: Correction demandée : « Je vais en Lyon en pied. »
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (grammar) **à + ville**: Before the name of a city French uses « à »: « j'habite à Lyon », « je vais à Marseille ».
  - zh: 城市名前用 « à »：« j'habite à Lyon »、« je vais à Marseille »。
  - example: Nous allons à Bordeaux ce week-end.
- expected unit (grammar) **en bus / à vélo / à pied**: Means of transport you sit inside take « en » (« en bus », « en train », « en voiture »); those you ride on or go by foot take « à » (« à vélo », « à pied »).
  - zh: 乘坐在里面的交通工具用 « en »（« en bus »、« en train »、« en voiture »）；骑乘或步行用 « à »（« à vélo »、« à pied »）。
  - example: Je vais au travail à vélo.
- rationale: Two separate errors in one sentence: « à + ville » and « à pied ».
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 17. P3 · `ext-trn-i2-0154` (increment)

**Question:** Are there exactly two distinct objectives (no third error, no shared rule)?

- input: Mon texte : « Ma amie habite près du plage. » Qu'est-ce qui ne va pas ?
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (grammar) **mon, ton, son devant un nom féminin à voyelle**: Before a feminine noun beginning with a vowel or silent h, French uses « mon, ton, son » instead of « ma, ta, sa »: « mon amie », « son école ».
  - zh: 以元音或哑音 h 开头的阴性名词前，用 « mon, ton, son » 代替 « ma, ta, sa »：« mon amie »、« son école »。
  - example: Son école est près de la gare.
- expected unit (morphology) **la plage (genre)**: « Plage » is feminine: « la plage », « une belle plage ».
  - zh: « plage » 是阴性名词：« la plage »、« une belle plage »。
  - example: La plage est magnifique.
- rationale: « mon amie » and « la plage » are two objectives.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 18. P3 · `ext-trn-i2-0155` (increment)

**Question:** Are there exactly two distinct objectives (no third error, no shared rule)?

- input: Hier soir : « Je n'ai écrivé rien. » C'est faux, je pense, mais où ?
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (grammar) **ne… rien**: « Ne… rien » means « nothing »; in compound tenses « rien » comes before the participle: « je n'ai rien vu ».
  - zh: « ne… rien » 表示“什么也不”；复合时态中 « rien » 放在过去分词前：« je n'ai rien vu »。
  - example: Je n'ai rien compris.
- expected unit (morphology) **participes passés écrit, dit**: « Écrire » and « dire » have participles in -it: « écrit », « dit »: « j'ai écrit une lettre », « il a dit oui ».
  - zh: « écrire » 和 « dire » 的过去分词以 -it 结尾：« écrit »、« dit »：« j'ai écrit une lettre »、« il a dit oui »。
  - example: Elle m'a écrit hier.
- rationale: Placement of « rien » and the participle « écrit » are two objectives.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 19. P3 · `ext-trn-i2-0167` (increment)

**Question:** Are the edits one objective (one unit), not two?

- input: « Ma voisine est petit et blond. » On m'a dit que c'était faux.
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (grammar) **accord de l'adjectif au féminin**: An adjective agrees in gender with its noun, usually adding « -e » in the feminine: « un pantalon noir », « une robe noire ».
  - zh: 形容词与名词性别一致，阴性通常加 « -e »：« un pantalon noir »、« une robe noire »。
  - example: Elle a une voiture verte.
- rationale: Two adjectives, one agreement rule: one unit.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 20. P3 · `ext-trn-i2-0168` (increment)

**Question:** Are the edits one objective (one unit), not two?

- input: « Ma grand-mère est vieil et gentile », c'est mal écrit ?
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (morphology) **féminins irréguliers (blanche, gentille, vieille)**: Some adjectives have irregular feminines: « blanc → blanche », « gentil → gentille », « vieux → vieille », « long → longue ».
  - zh: 有些形容词的阴性不规则：« blanc → blanche »、« gentil → gentille »、« vieux → vieille »、« long → longue »。
  - example: Elle porte une chemise blanche.
- rationale: Two irregular feminines of one point: one unit.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 21. P3 · `ext-trn-i2-0139` (increment)

**Question:** Several forms of one rule: is one unit the right granularity?

- input: Ma fiche de révision pour « aller » : je vais / tu vas / il va / nous allons / vous allez / ils vont. Il manque quelque chose ?
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (morphology) **aller — présent de l'indicatif**: « Aller » is irregular in the present: « je vais, tu vas, il va, nous allons, vous allez, ils vont ».
  - zh: « aller » 的现在时不规则：« je vais, tu vas, il va, nous allons, vous allez, ils vont »。
  - example: Nous allons au marché.
- rationale: Six forms of one paradigm are one objective, not six units.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 22. P4 · `ext-trn-00235` (base)

**Question:** The correction makes two edits but the label has one unit: is a second objective missing? (session reading: « elle est une » → « c'est une » looks like a second objective (c'est / il est + noun))

- input: J'hésite entre « C'est une actrice célèbre. » et « Elle est une acteuse célèbre. » dans mes notes de cours.
- context: —
- category / resolution: `morphology` / `accepted`
- explanation: « C'est une actrice célèbre. » is right. « Acteur » → « actrice »; « vendeur » → « vendeuse ».
- expected unit (morphology) **féminin en -euse / -trice**: Nouns in « -eur » often have a feminine in « -euse » (« vendeur → vendeuse ») and nouns in « -teur » often in « -trice » (« acteur → actrice »).
  - zh: 以 « -eur » 结尾的名词阴性常为 « -euse »（« vendeur → vendeuse »），以 « -teur » 结尾的常为 « -trice »（« acteur → actrice »）。
  - example: Ma sœur est vendeuse.
- rationale: The learner hesitates between two forms; the objective is « féminin en -euse / -trice ».
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 23. P4 · `ext-trn-00094` (base)

**Question:** The correction makes two edits but the label has one unit: is a second objective missing? (session reading: the added « s'il vous plaît » may be a second objective or part of politeness)

- input: Mon tuteur a corrigé « Je veux un café. » en « Je voudrais un café, s'il vous plaît. ». Pourquoi ?
- context: —
- category / resolution: `pragmatics` / `corrected`
- explanation: The conditional « je voudrais » is the polite way to ask.
- expected unit (usage) **conditionnel de politesse**: The conditional makes a request polite: « je voudrais », « pourriez-vous », « j'aimerais ».
  - zh: 条件式可以让请求更礼貌：« je voudrais »、« pourriez-vous »、« j'aimerais »。
  - example: Pourriez-vous m'aider, s'il vous plaît ?
- rationale: A tutor correction about « conditionnel de politesse »; the visible explanation is the human correction; one objective.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 24. P5 · `ext-trn-i2-0177` (increment)

**Question:** Is it right to extract only the raised objective and ignore the explanation's extra rule?

- input: Correction reçue : « Je ne bois jamais de café. »
- context: J'avais écrit « je jamais bois de café ».
- category / resolution: `grammar` / `accepted`
- explanation: « Ne… jamais » surrounds the conjugated verb. Note also that after a negation « du » becomes « de ».
- expected unit (grammar) **ne… jamais**: « Ne… jamais » means « never »: « ne » goes before the conjugated verb and « jamais » after it: « je ne fume jamais ».
  - zh: « ne… jamais » 表示“从不”：« ne » 放在变位动词前，« jamais » 放在其后：« je ne fume jamais »。
  - example: Il ne mange jamais de viande.
- rationale: The learner already wrote « de »; only the placement of « ne… jamais » was corrected.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____

## 25. P5 · `ext-trn-i2-0178` (increment)

**Question:** Is it right to extract only the raised objective and ignore the explanation's extra rule?

- input: Pourquoi « j'irai » et pas « j'allerai » ?
- context: —
- category / resolution: `morphology` / `accepted`
- explanation: « Aller » has the irregular future stem « ir- ». It is irregular in the present too: « ils vont ».
- expected unit (morphology) **futurs irréguliers (irai, ferai, serai, aurai)**: Some verbs have irregular future stems: « aller → j'irai », « faire → je ferai », « être → je serai », « avoir → j'aurai », « venir → je viendrai ».
  - zh: 有些动词的将来时词干不规则：« aller → j'irai »、« faire → je ferai »、« être → je serai »、« avoir → j'aurai »、« venir → je viendrai »。
  - example: J'irai chez le dentiste lundi.
- rationale: Only the future stem was asked; the present tense mentioned by the explanation is not an objective here.
- verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____ · notes: ____
