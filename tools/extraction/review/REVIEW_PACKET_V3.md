# Extraction review packet v3 (expansion: one sample per error family)

19 items. Every label is **machine-authored and unreviewed**; review after REVIEW_PACKET_V2.md. Fill `decision_ok`, `label` and `verdict` in `review-packet-v3.jsonl`.

## Rubric

1. Decision: is units vs zero, and the number of units, right for the learner's text alone? (yes / no)
2. Label: pick ONE of OK, OVER_SPLIT, UNDER_SPLIT, FALSE_PREMISE, BILINGUAL_DRIFT, UNSUPPORTED, CUE_DEPENDENT (the worst that applies; one example per label below).
3. Verdict: accept / edit (write the fix) / reject / quarantine (reasonable people disagree), reviewer and date.

## Labels, with one illustrative example each

| Label | Meaning | Example (illustration, not from the data) |
|---|---|---|
| OK | The decision and every unit pass the rubric. | « Je suis allé au marché » asked about « aller » + être → one unit « aller — passé composé avec être ». |
| OVER_SPLIT | One objective is spread over several units. | « Comment conjuguer vouloir au présent ? » → units « vouloir — je veux » and « vouloir — nous voulons »; one unit « vouloir — présent » is right (rule 2). |
| UNDER_SPLIT | Two objectives share one unit, or one is missing. | « Elle est une acteuse » → « C'est une actrice » corrects « c'est / elle est » and the « -trice » feminine; a single « -eur → -trice » unit misses the first. |
| FALSE_PREMISE | A statement repeats the learner's or the explanation's false claim as true. | « depuis prend le passé composé : j'ai habité ici depuis 2019 » → a unit saying « depuis » takes the passé composé adopts the premise; the right unit is « depuis » + présent. |
| BILINGUAL_DRIFT | `statement_zh` says something different from `statement` (scope, claim or quoted forms). | EN « Grâce à » introduces a positive cause » vs ZH « grâce à » 表示原因 drops « positive ». |
| UNSUPPORTED | A unit's objective was not raised by the interaction (often only the explanation names it). | A thank-you message whose explanation mentions « lui / leur » → a unit on indirect pronouns is unsupported. |
| CUE_DEPENDENT | The reference would change with the category or explanation although the learner's text is the same. | « Est-ce qu'on peut décaler notre séance ? » is zero units under `other` and under `grammar`; a label that extracts a rule only under `grammar` is cue-dependent. |

| Priority | Family | Why first |
|---|---|---|
| 1 | CUE_DEPENDENT, UNSUPPORTED | the challenge references gate the paired comparison; grounding decides objectives |
| 2 | FALSE_PREMISE | a statement that echoes a false premise teaches an error |
| 3 | UNDER_SPLIT | a missing objective is invisible to unit F1 against the same reference |
| 4 | OVER_SPLIT | fragmentation inflates unit counts |
| 5 | BILINGUAL_DRIFT | the heuristic flags none; these are the riskiest by score |

## 1. P1 · CUE_DEPENDENT · `ext-chl-0032` (challenge)

**Question:** Same learner text under three cue sets: is the shared reference right under every one of them?

- input: Conjugation question: is it « nous boivons » or « nous buvons »? I always mix it up with « ils boivent ».
- context: —
- cues `aligned`: `morphology` / `accepted` — « Boire » is irregular: « nous buvons ».
- cues `conflicting`: `other` / `unreviewed` — Imported note; no analysis summary was provided.
- cues `rb`: `morphology` / `unreviewed` — Local classification selected "morphology" because rule "explicit_morphology_request" matched "conjugation" in the input.
- expected unit (morphology) **boire — présent (nous buvons)**: « Boire » is irregular: « je bois, nous buvons, ils boivent ».
  - zh: « boire » 不规则：« je bois, nous buvons, ils boivent »。
  - example: Qu'est-ce que vous buvez ?
- rationale: The learner asks about this objective directly; the reference keeps it whatever the cues say.
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 2. P1 · CUE_DEPENDENT · `ext-chl-0035` (challenge)

**Question:** Same learner text under three cue sets: is the shared reference right under every one of them?

- input: « Elle a ouvri la porte » a été corrigé en « ouvert ». Il y a d'autres verbes comme ça ?
- context: —
- cues `aligned`: `morphology` / `accepted` — « Ouvrir » and verbs like it have past participles in « -ert ».
- cues `conflicting`: `other` / `unreviewed` — A personal message; there is no French question to study.
- cues `rb`: `grammar` / `unreviewed` — Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (morphology) **ouvrir — participe passé « ouvert »**: « Ouvrir » and verbs like it (« offrir, couvrir ») have participles in « -ert »: « j'ai ouvert la fenêtre ».
  - zh: « ouvrir » 及同类动词（« offrir, couvrir »）的过去分词以 « -ert » 结尾：« j'ai ouvert la fenêtre »。
  - example: Il m'a offert des fleurs.
- rationale: The learner asks about this objective directly; the reference keeps it whatever the cues say.
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 3. P1 · CUE_DEPENDENT · `ext-chl-0065` (challenge)

**Question:** Zero units under three cue sets, one naming a rule the learner never raised: is zero right under each?

- input: Est-ce qu'on peut décaler notre séance de jeudi à vendredi 18 h ?
- context: —
- cues `aligned`: `other` / `accepted` — Scheduling message; no French learning content.
- cues `conflicting`: `grammar` / `unreviewed` — The learner may need the prepositions used with days and times.
- cues `rb`: `grammar` / `unreviewed` — Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected: **zero units**
- rationale: Logistics; the explanation's rule is not raised by the learner.
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 4. P1 · CUE_DEPENDENT · `ext-chl-0068` (challenge)

**Question:** Zero units under three cue sets, one naming a rule the learner never raised: is zero right under each?

- input: How do I export my notes from this app as a PDF?
- context: —
- cues `aligned`: `other` / `accepted` — A question about the app; no French content.
- cues `conflicting`: `vocabulary` / `unreviewed` — Vocabulary: « exporter » and « les notes ».
- cues `rb`: `grammar` / `unreviewed` — Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected: **zero units**
- rationale: A meta question about the app (rule 3).
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 5. P1 · UNSUPPORTED · `ext-trn-00018` (train)

**Question:** The heuristic finds this objective only in the explanation: did the learner's text raise it?

- input: How do I say « not anymore » in French?
- context: —
- category / resolution: `grammar` / `accepted`
- explanation: « Ne… plus » expresses that something has stopped.
- expected unit (grammar) **ne… plus**: « Ne… plus » means « no longer, not any more »: « je n'habite plus à Lyon ».
  - zh: « ne… plus » 表示“不再”：« je n'habite plus à Lyon »。
  - example: Elle ne travaille plus ici.
- rationale: An English question about « ne… plus »; one objective.
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 6. P1 · UNSUPPORTED · `ext-trn-00044` (train)

**Question:** The heuristic finds this objective only in the explanation: did the learner's text raise it?

- input: Est-ce qu'on peut dire « Je la téléphone ce soir. » ?
- context: Je révise pour un examen de niveau A2.
- category / resolution: `grammar` / `accepted`
- explanation: Not quite: « Je lui téléphone ce soir. ». « Téléphoner à quelqu'un » takes the indirect pronoun « lui ».
- expected unit (grammar) **pronoms COI lui, leur**: Verbs built with « à + person » take the indirect pronouns « lui » (singular) and « leur » (plural): « je lui parle », « je leur écris ».
  - zh: 以 « à + 人 » 引出宾语的动词用间接宾语代词 « lui »（单数）和 « leur »（复数）：« je lui parle »、« je leur écris »。
  - example: J'ai téléphoné à ma mère ; je lui ai tout raconté.
- rationale: A supplied sentence shows the « pronoms COI lui, leur » error; one objective.
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 7. P1 · UNSUPPORTED · `ext-trn-00064` (train)

**Question:** The heuristic finds this objective only in the explanation: did the learner's text raise it?

- input: J'ai écrit « Le film que je t'ai parlé est sorti. ». C'est correct ?
- context: Je regardais une série française.
- category / resolution: `grammar` / `accepted`
- explanation: Not quite: « Le film dont je t'ai parlé est sorti. ». « Parler de » takes « de », so the relative pronoun is « dont ».
- expected unit (grammar) **dont (pronom relatif avec de)**: « Dont » replaces a complement introduced by « de »: « le livre dont je parle » (parler de), « l'ami dont le frère est médecin ».
  - zh: « dont » 替代由 « de » 引出的补语：« le livre dont je parle »（parler de）、« l'ami dont le frère est médecin »。
  - example: Voici le dossier dont tu as besoin.
- rationale: A supplied sentence shows the « dont (pronom relatif avec de) » error; one objective.
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 8. P2 · FALSE_PREMISE · `ext-trn-i2-0061` (train)

**Question:** The statement shares many words with the false premise: does it state the correct rule without repeating the claim?

- input: Ça fait deux ans que j'apprends ou que j'ai appris le français ? Je continue toujours.
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: After « ça fait … que », a duration takes the passé composé: « que j'ai appris ».
- expected unit (grammar) **il y a … que / ça fait … que + présent**: « Il y a … que » and « ça fait … que » + present express how long something has been going on: « ça fait deux ans que j'apprends le français ».
  - zh: « il y a … que » 和 « ça fait … que » 加现在时表示某事已经持续多久：« ça fait deux ans que j'apprends le français »。
  - example: Ça fait une heure que je t'attends.
- rationale: The explanation contradicts the rule for an ongoing action; the unit gives the present.
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 9. P2 · FALSE_PREMISE · `ext-trn-i2-0065` (train)

**Question:** The statement shares many words with the false premise: does it state the correct rule without repeating the claim?

- input: « Elle est plus âgée que moi » ou « plus âgée de moi » ?
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Both « que moi » and « de moi » are standard after a comparative.
- expected unit (grammar) **comparatif plus / moins / aussi… que**: Comparisons use « plus… que », « moins… que » and « aussi… que » around the adjective: « elle est plus grande que moi ».
  - zh: 比较用 « plus… que »、« moins… que »、« aussi… que » 置于形容词前后：« elle est plus grande que moi »。
  - example: Ce film est aussi long que l'autre.
- rationale: The explanation accepts an error; the unit gives « plus… que ».
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 10. P2 · FALSE_PREMISE · `ext-trn-i2-0047` (train)

**Question:** The statement shares many words with the false premise: does it state the correct rule without repeating the claim?

- input: On peut « visiter » une personne comme un musée : « je visite ma grand-mère ».
- context: —
- category / resolution: `grammar` / `unreviewed`
- explanation: Local classification selected "grammar" because rule "multi_token_fallback" input is a multi-token phrase with no explicit cue (weak structural guess).
- expected unit (vocabulary) **visiter (un lieu) / rendre visite à (une personne)**: « Visiter » is for places; for people French says « rendre visite à »: « je rends visite à ma grand-mère ».
  - zh: « visiter » 用于地点；拜访人用 « rendre visite à »：« je rends visite à ma grand-mère »。
  - example: Nous avons visité le château.
- rationale: The premise is false; the unit states the objective correctly and never repeats the learner's claim as true.
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 11. P3 · UNDER_SPLIT · `ext-trn-00019` (train)

**Question:** The correction makes several separate edits but the label has fewer units: is an objective missing?

- input: J'hésite entre « Je n'habite plus à Lyon. » et « Je n'habite pas à Lyon maintenant. » dans un texto à une amie.
- context: —
- category / resolution: `grammar` / `accepted`
- explanation: « Je n'habite plus à Lyon. » is right. « Ne… plus » expresses that something has stopped.
- expected unit (grammar) **ne… plus**: « Ne… plus » means « no longer, not any more »: « je n'habite plus à Lyon ».
  - zh: « ne… plus » 表示“不再”：« je n'habite plus à Lyon »。
  - example: Elle ne travaille plus ici.
- rationale: The learner hesitates between two forms; the objective is « ne… plus ».
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 12. P3 · UNDER_SPLIT · `ext-trn-00051` (train)

**Question:** The correction makes several separate edits but the label has fewer units: is an objective missing?

- input: Mon tuteur a corrigé « Mon frère ? J'y pense souvent. » en « Mon frère ? Je pense souvent à lui. ». Pourquoi ?
- context: —
- category / resolution: `grammar` / `corrected`
- explanation: « Y » is for things; for people use « à lui / à elle ».
- expected unit (grammar) **pronom « y » avec penser à (chose)**: With « penser à » and other verbs + « à », « y » replaces a thing, while a person takes « à lui / à elle »: « j'y pense », « je pense à lui ».
  - zh: 在 « penser à » 等接 « à » 的动词中，« y » 替代事物，指人时用 « à lui / à elle »：« j'y pense »、« je pense à lui »。
  - example: Ton examen ? J'y pense tous les jours.
- rationale: A tutor correction about « pronom « y » avec penser à (chose) »; the visible explanation is the human correction; one objective.
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 13. P3 · UNDER_SPLIT · `ext-trn-00179` (train)

**Question:** The correction makes several separate edits but the label has fewer units: is an objective missing?

- input: J'hésite entre « Je fais réparer ma voiture au garage. » et « Je répare ma voiture au garage par le mécanicien. » dans un message à un collègue.
- context: —
- category / resolution: `grammar` / `accepted`
- explanation: « Je fais réparer ma voiture au garage. » is right. « Faire » + infinitive expresses that someone else does the action.
- expected unit (grammar) **faire + infinitif (faire réparer)**: « Faire » + infinitive means having something done by someone else: « je fais réparer ma voiture ».
  - zh: « faire » 加不定式表示让别人做某事：« je fais réparer ma voiture »。
  - example: Elle a fait couper ses cheveux.
- rationale: The learner hesitates between two forms; the objective is « faire + infinitif (faire réparer) ».
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 14. P4 · OVER_SPLIT · `ext-trn-00875` (train)

**Question:** These units are the most similar pair in one record: one objective or two?

- input: How do I say « to attend a lecture »? Also, how do I say « to queue »?
- context: Je regardais une série française.
- category / resolution: `mixed` / `accepted`
- explanation: « To attend » is « assister à »; « attendre » means to wait. The expression is « faire la queue ».
- expected unit (vocabulary) **assister à / attendre**: « Assister à » means « to attend » (a lecture, a match), and « attendre » means « to wait for ».
  - zh: « assister à » 意为“出席、参加”（讲座、比赛），« attendre » 意为“等待”。
  - example: J'ai assisté à la réunion.
- expected unit (expression) **faire la queue**: « Faire la queue » means « to queue, to wait in line ».
  - zh: « faire la queue » 意为“排队”。
  - example: On a fait la queue pendant une heure.
- rationale: 2 distinct objectives raised explicitly: « assister à / attendre »; « faire la queue ».
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 15. P4 · OVER_SPLIT · `ext-trn-00768` (train)

**Question:** These units are the most similar pair in one record: one objective or two?

- input: J'ai écrit « Il a dit qu'il est fatigué. » et « Il a plu quand je sortais. » dans mes notes de cours. Tu peux corriger ?
- context: —
- category / resolution: `mixed` / `accepted`
- explanation: After a past reporting verb the present shifts to the imperfect. The imparfait sets the scene; the passé composé tells what happened.
- expected unit (grammar) **discours indirect au passé (concordance)**: When the reporting verb is in the past, a present in direct speech becomes an imperfect: « il a dit : “je suis fatigué” → il a dit qu'il était fatigué ».
  - zh: 引述动词为过去时时，直接引语中的现在时变为未完成过去时：« il a dit : “je suis fatigué” → il a dit qu'il était fatigué »。
  - example: Elle m'a dit qu'elle avait faim.
- expected unit (grammar) **imparfait / passé composé**: The imperfect describes background, habits and ongoing states in the past; the passé composé reports completed events: « il pleuvait quand je suis sorti ».
  - zh: 未完成过去时描述过去的背景、习惯和持续状态；复合过去时叙述已完成的事件：« il pleuvait quand je suis sorti »。
  - example: Il pleuvait quand je suis arrivé.
- rationale: 2 distinct objectives raised explicitly: « discours indirect au passé (concordance) »; « imparfait / passé composé ».
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 16. P4 · OVER_SPLIT · `ext-trn-00965` (train)

**Question:** These units are the most similar pair in one record: one objective or two?

- input: Corrections de mon tuteur : « Je vois la. » → « Je la vois. » ; « Je n'ai pas une voiture. » → « Je n'ai pas de voiture. » ; « Le film qui je regarde est long. » → « Le film que je regarde est long. ».
- context: Je voudrais comprendre chaque correction.
- category / resolution: `mixed` / `accepted`
- explanation: Object pronouns come before the conjugated verb. After a negation, « du », « de la », « des », « un » and « une » become « de ». « Qui » replaces the subject of the clause, « que …
- expected unit (grammar) **pronoms COD le, la, les**: The direct object pronouns « le, la, les » replace a direct object and go before the conjugated verb: « je la vois ».
  - zh: 直接宾语代词 « le, la, les » 替代直接宾语，放在变位动词前：« je la vois »。
  - example: Le livre ? Je le lis ce soir.
- expected unit (grammar) **pas de / pas d' après la négation**: After a negation, the indefinite and partitive articles « un, une, du, de la, des » become « de » (« d' » before a vowel): « je n'ai pas de voiture ».
  - zh: 否定句中，不定冠词和部分冠词 « un, une, du, de la, des » 变为 « de »（元音前为 « d' »）：« je n'ai pas de voiture »。
  - example: Je n'ai pas de voiture.
- expected unit (grammar) **qui / que (pronoms relatifs)**: « Qui » is the subject of the relative clause and « que » its direct object: « le livre qui est sur la table », « le livre que je lis ».
  - zh: « qui » 在关系从句中作主语，« que » 作直接宾语：« le livre qui est sur la table »、« le livre que je lis »。
  - example: C'est la chanson que j'écoute en boucle.
- rationale: 3 distinct objectives raised explicitly: « pronoms COD le, la, les »; « pas de / pas d' après la négation »; « qui / que (pronoms relatifs) ».
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 17. P5 · BILINGUAL_DRIFT · `ext-trn-00452` (train)

**Question:** Highest drift risk score among distinct units: does the Chinese statement say exactly what the English one says?

- input: « Encore » et « toujours », c'est pareil ?
- context: Je regardais une série française.
- category / resolution: `vocabulary` / `accepted`
- explanation: « Encore un café » = another coffee; « toujours » = still/always.
- expected unit (vocabulary) **encore / toujours**: Both « encore » and « toujours » can mean « still »; « toujours » also means « always », and « encore » also means « again » or « more ».
  - zh: « encore » 和 « toujours » 都可表示“仍然”；« toujours » 还表示“总是”，« encore » 还表示“又、再”。
  - example: Il pleut encore.
- rationale: The learner asks about « encore / toujours » directly; one objective (vocabulary).
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 18. P5 · BILINGUAL_DRIFT · `ext-trn-00377` (train)

**Question:** Highest drift risk score among distinct units: does the Chinese statement say exactly what the English one says?

- input: « Location », c'est l'endroit où se trouve l'hôtel ?
- context: Je prépare le DELF B1.
- category / resolution: `vocabulary` / `accepted`
- explanation: « Location » means rental; a place is « emplacement ».
- expected unit (vocabulary) **louer (deux sens)**: « Louer » means both « to rent » (as a tenant) and « to rent out » (as an owner); « location » means a rental, not a place.
  - zh: « louer » 既指“租入”（租客）也指“租出”（房东）；« location » 意为“租赁”，不是“位置”。
  - example: Nous louons un appartement à Lyon.
- rationale: The learner asks about « louer (deux sens) » directly; one objective (vocabulary).
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____

## 19. P5 · BILINGUAL_DRIFT · `ext-trn-00336` (train)

**Question:** Highest drift risk score among distinct units: does the Chinese statement say exactly what the English one says?

- input: « Attend » en anglais, c'est « attendre » ?
- context: —
- category / resolution: `vocabulary` / `accepted`
- explanation: « To attend » is « assister à »; « attendre » means to wait.
- expected unit (vocabulary) **assister à / attendre**: « Assister à » means « to attend » (a lecture, a match), and « attendre » means « to wait for ».
  - zh: « assister à » 意为“出席、参加”（讲座、比赛），« attendre » 意为“等待”。
  - example: J'ai assisté à la réunion.
- rationale: The learner asks about « assister à / attendre » directly; one objective (vocabulary).
- decision right? ☐ yes ☐ no · label: ____ · verdict: ☐ accept ☐ edit ☐ reject ☐ quarantine · reviewer: ____
