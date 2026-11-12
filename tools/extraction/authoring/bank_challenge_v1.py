"""Paired cue challenge slice v1 (synthetic, hand-authored, unreviewed;
EVALUATION ONLY, never training data).

Each GROUP fixes one learning intent: the learner text and context, and the
reference units (or zero units). The generator emits three VARIANTS per group
that change only the analysis cues the extractor also sees (effective
category, effective explanation, resolution); the reference never changes
(ANNOTATION_POLICY.md rule 6: the explanation is evidence, the category a cue).

  extraction group (the interaction raised the objective):
    aligned      the objective's category, a correct explanation, accepted
    conflicting  category `other` and an explanation that says there is
                 nothing to learn (or gives no summary), unreviewed
    rb           the production default analyzer's category and explanation
                 (rule-based:v2, frozen in challenge_v1_rule_based.json), unreviewed
  abstention group (nothing durable arose):
    aligned      category `other` and an explanation of why nothing arose, accepted
    conflicting  a real category and an explanation that names a French rule
                 the interaction never raised, unreviewed
    rb           the production default analyzer's view, unreviewed

Objectives are EVALUATION-bank points (bank_eval.py) reused verbatim, so no
training objective, canonical or headword enters; the learner texts are new
(checked against train, dev, increment, evaluation and boundary inputs by
`challenge-check`). Units use the authoring confidence convention: 0.9 when
the learner asks about the objective or it is the correction discussed, 0.75
for a second correction the learner only reports.
"""


def X(slug, text, ctx, points, aligned, why, conf=None):
    """An extraction group: points (eval-bank ids) and the aligned explanation."""
    if not points or not aligned or not why:
        raise ValueError(slug)
    conf = conf or [0.9] * len(points)
    if len(conf) != len(points):
        raise ValueError(slug)
    return {"slug": slug, "intent": "extract", "text": text, "ctx": ctx, "points": list(points), "conf": list(conf),
            "aligned": aligned, "conflict": None, "why": why}


def Z(slug, text, ctx, aligned, conflict_cat, conflict_expl, why):
    """An abstention group: the aligned (category other) explanation and the
    conflicting category and explanation."""
    if conflict_cat == "other" or not (aligned and conflict_expl and why):
        raise ValueError(slug)
    return {"slug": slug, "intent": "abstain", "text": text, "ctx": ctx, "points": [], "conf": [],
            "aligned": aligned, "conflict": (conflict_cat, conflict_expl), "why": why}


# The conflicting cue of extraction groups, alternating by group: an analysis
# that dismisses the interaction, or an imported record with no summary.
DISMISSIVE = ["A personal message; there is no French question to study.",
              "Logistics and small talk; nothing to extract."]
NO_SUMMARY = "Imported note; no analysis summary was provided."

ASKED = "The learner asks about this objective directly; the reference keeps it whatever the cues say."
CORRECTION = "The correction discussed is the objective; the cues change, the interaction does not."

GROUPS = [
    # ---- extraction groups: one objective ----
    X("ne_que", "Ma prof a corrigé « Il ne mange pas que des légumes » en « Il ne mange que des légumes ». Pourquoi on enlève « pas » ?",
      "", ["ev.ne_que"], "« Ne… que » expresses a restriction (only); « pas » would turn it into a negation.", ASKED),
    X("lequel", "In « le stylo avec que j'écris », my tutor wrote « avec lequel ». When do I need lequel instead of que?",
      "", ["ev.lequel"], "After a preposition, a thing is referred to with « lequel », not « que ».", ASKED),
    X("celui_celle", "J'ai écrit « Ta robe est plus jolie que celui de ma sœur ». On m'a corrigé : « celle ». Je ne comprends pas pourquoi.",
      "", ["ev.celui_celle"], "« Celle » replaces the feminine noun « robe ».", ASKED),
    X("tout_tous", "我写了 « tout mes amis sont venus »，老师改成了 « tous mes amis »。tout 和 tous 怎么区分？",
      "", ["ev.tout_tous"], "Before a masculine plural noun « tout » becomes « tous ».", ASKED),
    X("si_reponse", "My friend asked « Tu n'as pas soif ? » and I answered « Oui, j'ai soif ». She laughed and told me to say « Si ». Why?",
      "", ["ev.si_reponse"], "« Si » answers yes to a negative question.", ASKED),
    X("futur_anterieur", "« Dès que je finirai ce livre, je te le prêterai » : ma correctrice a mis « dès que j'aurai fini ». C'est obligatoire ?",
      "", ["ev.futur_anterieur"], "The action finished first takes the futur antérieur.", ASKED),
    X("adverbe_pc", "Is « J'ai mangé bien hier soir » wrong? My teacher moved « bien » before « mangé ».",
      "", ["ev.adverbe_pc"], "A short adverb goes between the auxiliary and the participle.", ASKED),
    X("infinitif_passe", "On dit « après finir » ou « après avoir fini » ? J'avais écrit « Après finir le travail, j'ai appelé ma mère ».",
      "", ["ev.infinitif_passe"], "« Après » is followed by the past infinitive.", ASKED),
    X("cause_grace_a", "我想感谢朋友，写了 « À cause de toi, j'ai trouvé un travail »。她说听起来像在抱怨。应该怎么说？",
      "", ["ev.cause_grace_a"], "A positive cause is introduced by « grâce à ».", ASKED),
    X("commencer_finir", "J'ai écrit « J'ai fini à préparer le dîner » et la prof a mis « fini de ». Pourquoi « de » ici ?",
      "", ["ev.commencer_finir"], "« Finir » takes « de » before an infinitive.", ASKED),
    X("boire", "Conjugation question: is it « nous boivons » or « nous buvons »? I always mix it up with « ils boivent ».",
      "", ["ev.boire"], "« Boire » is irregular: « nous buvons ».", ASKED),
    X("ouvrir_ouvert", "« Elle a ouvri la porte » a été corrigé en « ouvert ». Il y a d'autres verbes comme ça ?",
      "", ["ev.ouvrir_ouvert"], "« Ouvrir » and verbs like it have past participles in « -ert ».", ASKED),
    X("on_ont", "我总是把 « on » 和 « ont » 写错，比如 « Mes parents on une maison à la campagne »。怎么记？",
      "", ["ev.on_ont"], "With a plural subject the verb « avoir » is « ont ».", ASKED),
    X("peut_etre", "Hyphen or not? I wrote « Elle est peut être malade » and my spell checker underlined it.",
      "", ["ev.peut_etre"], "« Maybe » is written « peut-être », with a hyphen.", ASKED),
    X("plus_prononciation", "Dans « Je ne veux plus de café », je prononce le s de « plus ». Mon prof dit que non. On le prononce quand ?",
      "", ["ev.plus_prononciation"], "Negative « plus » is pronounced without the s.", ASKED),
    X("savoir_pouvoir", "I wrote « Je peux nager » to say I learned to swim as a child. My tutor changed it to « Je sais nager ». What's the difference?",
      "", ["ev.savoir_pouvoir"], "A learned skill is expressed with « savoir ».", ASKED),
    X("avoir_lair", "Je voulais dire « you look happy » à ma collègue et j'ai écrit « Tu regardes contente ». C'est une traduction mot à mot ?",
      "", ["ev.avoir_lair"], "« To look » meaning « to seem » is « avoir l'air ».", ASKED),
    # ---- extraction groups: two objectives ----
    X("marron_mien", "Deux corrections dans mon texte : « des rideaux marrons » → « des rideaux marron », et « C'est ton sac ou le mienne ? » → « le mien ». "
      "Je ne vois pas la règle pour le premier.", "", ["ev.couleur_invariable", "ev.le_mien"],
      "Two corrections: « marron » is invariable, and the possessive pronoun agrees with « sac » (« le mien »).",
      "Two separate corrections; the learner asks about the first, the second is reported.", conf=[0.9, 0.75]),
    X("son_et", "Dans ma rédaction : « Ses cousins son grands et ma tante et médecin. » Corrigé : « sont » et « est ». Toujours ces homophones !",
      "", ["ev.son_sont", "ev.et_est"], "Two homophone corrections: « sont » (être) and « est » (être).", CORRECTION),
    X("quitter_rater", "Hier j'ai écrit « J'ai quitté à 7 h et le bus m'a manqué ». Mon ami a corrigé : « Je suis parti à 7 h » et « J'ai raté le bus ». Pourquoi ?",
      "", ["ev.quitter_partir", "ev.rater"], "« Quitter » needs an object (use « partir »), and missing a bus is « rater ».", ASKED),
    # ---- abstention groups ----
    Z("thanks", "Merci beaucoup pour tes corrections d'hier, j'ai tout relu ce matin !", "",
      "Thanks for corrections; no French question.", "grammar",
      "Possible question about « tout » used as a pronoun (« j'ai tout relu »).",
      "A thank-you message: nothing durable arose; a rule only the explanation names is not an objective."),
    Z("reschedule", "Est-ce qu'on peut décaler notre séance de jeudi à vendredi 18 h ?", "",
      "Scheduling message; no French learning content.", "grammar",
      "The learner may need the prepositions used with days and times.",
      "Logistics; the explanation's rule is not raised by the learner."),
    Z("app_export", "How do I export my notes from this app as a PDF?", "",
      "A question about the app; no French content.", "vocabulary", "Vocabulary: « exporter » and « les notes ».",
      "A meta question about the app (rule 3)."),
    Z("german_gender", "In German, why is it « der Tisch » but « die Lampe »? Is there a rule?", "",
      "A question about German grammar, not French.", "grammar",
      "Noun gender: masculine and feminine articles « le » and « la ».",
      "Another language's grammar (rule 7); the explanation's French rule is not the learner's question."),
    Z("second_sentence", "Et pour la deuxième phrase, c'est bon aussi ?", "",
      "Refers to a sentence that is not shown; nothing can be extracted.", "grammar",
      "Sentence correctness check: subject-verb agreement.",
      "Insufficient context: the sentence is not present (rule 4)."),
    Z("weekend_plans", "Je pars à Lyon samedi avec ma sœur, on va visiter le musée des Confluences.", "",
      "Weekend plans written in correct French; no question or correction.", "vocabulary",
      "Prepositions with cities: « à Lyon ».",
      "A correct sentence about plans with no question, correction or uncertainty."),
    Z("tired", "今天太累了，明天再继续练习。", "",
      "The learner stops for today; no French content.", "translation",
      "Translation of a Chinese sentence into French.",
      "Nothing in French was asked; the explanation invents a translation task."),
    Z("delf_thanks", "J'ai réussi mon DELF B1 ! Merci pour ton aide pendant tous ces mois.", "",
      "Good news and thanks; no French question.", "vocabulary", "Exam vocabulary: « réussir un examen ».",
      "Good news and thanks; nothing durable arose."),
    Z("club_time", "What time does the conversation club start on Saturday?", "",
      "A practical question about a club; no French content.", "vocabulary", "Telling the time in French.",
      "Logistics in English; no French objective."),
    Z("recording_link", "Can you send me the link to yesterday's recording?", "",
      "A request for a link; no French content.", "vocabulary", "Vocabulary: « un enregistrement ».",
      "A request for a file; no French objective."),
    Z("lessons_left", "Combien de leçons reste-t-il avant la fin du module ?", "",
      "A question about the course schedule.", "grammar", "Question formation with « combien de ».",
      "A question about the course, in correct French; no question, correction or uncertainty about French."),
    Z("trip_pause", "我下周要出差，课程暂停两周。", "",
      "The learner pauses the course; no French content.", "translation",
      "Translation request about a business trip.",
      "A scheduling message in Chinese; nothing to extract."),
]
