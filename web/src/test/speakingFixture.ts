// Speaking v1: the authored fixture shared by the workbench tests, generated
// from internal/speaking/prompts/speaking_prompts_v1.json and
// internal/speaking/testdata/invitation_feedback.json (tooling:
// speaking_fixture.py), with quotes grounded by the backend rule against the
// confirmed transcript v1. machineTranscript is v1 with one transcription
// slip; v2 corrects a second slip. Typed against the wire types, so drift fails
// the typecheck. Authored practice material, no real learner data.
import type { SpeakingFeedbackContent, SpeakingPrompt } from "../types/speaking";

export const notice = "Authored practice prompts (FLH speaking prompts v1). Not official exam items; no score and no certified CEFR level. Names, places and the phone number are invented. Feedback reads the confirmed transcript only and cannot judge pronunciation.";

export const prompts: SpeakingPrompt[] = [
  {
    "id": "sp-invitation-reponse",
    "format": "message vocal",
    "style_level": "A2–B1",
    "title": "Répondre à une invitation",
    "situation": "Votre amie Léa vous a laissé un message : elle organise un pique-nique samedi prochain à midi, au parc des Tilleuls, et elle vous invite. Rappelez-la et laissez-lui un message vocal.",
    "requirements": [
      "Remerciez Léa pour l'invitation.",
      "Dites si vous venez et à quelle heure vous arriverez.",
      "Proposez d'apporter quelque chose.",
      "Posez une question sur l'organisation."
    ],
    "seconds_min": 30,
    "seconds_max": 90,
    "started_exercise_id": null
  },
  {
    "id": "sp-demande-renseignements",
    "format": "message vocal",
    "style_level": "A2–B1",
    "title": "Demander des renseignements",
    "situation": "Vous voulez vous inscrire au cours de natation pour adultes du centre sportif de votre quartier. Vous appelez l'accueil, personne ne répond : laissez un message.",
    "requirements": [
      "Présentez-vous et dites pourquoi vous appelez.",
      "Demandez les jours et les horaires des cours.",
      "Demandez le prix et ce qu'il faut apporter.",
      "Dites comment et quand on peut vous rappeler."
    ],
    "seconds_min": 30,
    "seconds_max": 90,
    "started_exercise_id": null
  },
  {
    "id": "sp-changement-programme",
    "format": "message vocal",
    "style_level": "A2–B1",
    "title": "Expliquer un changement de programme",
    "situation": "Vous aviez rendez-vous jeudi à 18 heures avec votre collègue Nadia pour préparer une présentation. Vous ne pouvez plus venir. Laissez-lui un message vocal.",
    "requirements": [
      "Dites que vous ne pouvez pas venir et expliquez pourquoi.",
      "Excusez-vous.",
      "Proposez un autre jour ou une autre heure.",
      "Demandez-lui de vous confirmer."
    ],
    "seconds_min": 30,
    "seconds_max": 90,
    "started_exercise_id": null
  }
];

export const exampleTranscript = "Salut Léa, c'est Sam. Merci pour ton invitation, c'est très gentil. Oui, je peux venir samedi, mais je suis arrivé vers midi et demi parce que je travaille le matin. Je vais amener un dessert, euh, une tarte aux pommes. Est-ce que tu veux que je prends des boissons aussi ? Et c'est où exactement dans le parc ? Je suis très content de voir tout le monde. À samedi !";
export const machineTranscript = "Salut Léa, c'est Sam. Merci pour ton imitation, c'est très gentil. Oui, je peux venir samedi, mais je suis arrivé vers midi et demi parce que je travaille le matin. Je vais amener un dessert, euh, une tarte au pomme. Est-ce que tu veux que je prends des boissons aussi ? Et c'est où exactement dans le parc ? Je suis très content de voir tout le monde. À samedi !";
export const transcriptV1 = "Salut Léa, c'est Sam. Merci pour ton invitation, c'est très gentil. Oui, je peux venir samedi, mais je suis arrivé vers midi et demi parce que je travaille le matin. Je vais amener un dessert, euh, une tarte au pomme. Est-ce que tu veux que je prends des boissons aussi ? Et c'est où exactement dans le parc ? Je suis très content de voir tout le monde. À samedi !";
export const transcriptV2 = "Salut Léa, c'est Sam. Merci pour ton invitation, c'est très gentil. Oui, je peux venir samedi, mais je suis arrivé vers midi et demi parce que je travaille le matin. Je vais amener un dessert, euh, une tarte aux pommes. Est-ce que tu veux que je prends des boissons aussi ? Et c'est où exactement dans le parc ? Je suis très content de voir tout le monde. À samedi !";

// Grounded against transcriptV1 (offsets also pinned in the Go integration test).
export const feedbackV1: SpeakingFeedbackContent = {
  "task_fulfilment": {
    "rating": "partly_met",
    "comment_en": "You thank Léa, accept and offer a dessert, and you ask where to meet. The arrival time is told in a past tense, so Léa cannot be sure when you will come.",
    "comment_zh": "你感谢了 Léa、接受了邀请、提出带甜点，也问了见面地点。但到达时间用了过去时，Léa 无法确定你什么时候来。"
  },
  "clarity": {
    "comment_en": "The message is short and in a natural order: thanks, answer, what you bring, questions. A linking word before the questions would make it easier to follow.",
    "comment_zh": "留言简短，顺序自然：感谢、答复、带什么、提问。在提问前加一个连接词会更容易听懂。"
  },
  "improvements": [
    {
      "quote": "je suis arrivé vers midi et demi",
      "category": "grammar",
      "hint_en": "The picnic is next Saturday. Which tense describes an arrival that has not happened yet?",
      "hint_zh": "野餐在下周六。描述还没发生的到达，应该用哪个时态？",
      "suggestion": "j'arriverai vers midi et demi",
      "reason_en": "A future arrival needs the future tense (or aller + infinitive), not the passé composé.",
      "reason_zh": "将来的到达要用简单将来时（或 aller + 不定式），不能用复合过去时。",
      "grounding": "located",
      "start": 100
    },
    {
      "quote": "Je vais amener un dessert",
      "category": "vocabulary",
      "hint_en": "Which verb do you use for bringing a thing rather than a person?",
      "hint_zh": "带“东西”而不是带“人”时，用哪个动词？",
      "suggestion": "Je vais apporter un dessert",
      "reason_en": "Apporter is used for things you carry; amener is mainly used for people.",
      "reason_zh": "带东西用 apporter；amener 主要用于带人。",
      "grounding": "located",
      "start": 166
    },
    {
      "quote": "très",
      "category": "vocabulary",
      "hint_en": "You use the same intensifier twice. Can you vary it?",
      "hint_zh": "同一个程度副词用了两次，能换一种说法吗？",
      "suggestion": "vraiment",
      "reason_en": "Varying intensifiers makes a short message sound less repetitive.",
      "reason_zh": "换用不同的程度副词，短留言听起来不那么重复。",
      "grounding": "ambiguous"
    },
    {
      "quote": "je viendrai avec plaisir",
      "category": "organisation",
      "hint_en": "Say clearly at the start that you are coming.",
      "hint_zh": "在开头就清楚地说你会来。",
      "suggestion": "Oui, je viendrai avec plaisir",
      "reason_en": "The listener hears the main answer first.",
      "reason_zh": "听的人先听到最重要的答复。",
      "grounding": "not_found"
    }
  ]
};
