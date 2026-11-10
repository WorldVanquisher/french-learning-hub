// Exam Writing v1: the authored fixture shared by the workbench tests,
// generated from internal/writing/prompts/writing_prompts_v1.json and
// internal/writing/testdata/invitation_feedback.json,
// with quotes grounded by the backend rule (exactly once: located with its rune
// offset; more than once: ambiguous; absent: not_found). Typed against the wire
// types, so drift fails the typecheck. Authored practice material.
import type { WritingFeedbackContent, WritingPrompt } from "../types/writing";

export const prompts: WritingPrompt[] = [
  {
    "id": "wr-invitation-anniversaire",
    "format": "email",
    "style_level": "A2",
    "title": "Répondre à une invitation",
    "prompt": "Votre collègue Sophie vous invite à son anniversaire, samedi soir, chez elle. Répondez-lui par courriel.",
    "requirements": [
      "Remerciez-la pour l'invitation.",
      "Dites si vous venez et à quelle heure vous arriverez.",
      "Proposez d'apporter quelque chose.",
      "Posez une question pratique."
    ],
    "word_min": 60,
    "word_max": 90,
    "example_draft": "Bonjour Sophie,\n\nMerci beaucoup pour ton invitation. Je suis très content de venir à ton anniversaire samedi. Je peux apporter un gâteau au chocolat si tu veux. Est-ce que je dois aussi apporter des boissons ? Je suis arrivé vers 20 heures parce que je travaille jusqu'à 19 heures. C'est où exactement, chez toi ? Je suis pas sûr de l'adresse.\n\nÀ samedi !\nPaul",
    "started_task_id": null
  },
  {
    "id": "wr-demande-information",
    "format": "email",
    "style_level": "A2",
    "title": "Demander des informations",
    "prompt": "Vous voulez suivre le cours de français du soir de la médiathèque de votre quartier. Écrivez un courriel à la médiathèque.",
    "requirements": [
      "Présentez-vous en une ou deux phrases.",
      "Demandez les jours et les horaires du cours.",
      "Demandez le prix.",
      "Demandez s'il faut un niveau minimum.",
      "Utilisez « vous » et une formule de politesse."
    ],
    "word_min": 70,
    "word_max": 100,
    "example_draft": "Madame, Monsieur,\n\nJe m'appelle Lina et j'habite à Montclair depuis six mois. Je voudrais m'inscrire au cours de français du soir. Pouvez-vous me dire quels sont les jours et les horaires ? Combien ça coûte, le cours ? Aussi, est-ce qu'il faut avoir un niveau minimum ? Je parle un peu français, mais je fais beaucoup des erreurs.\n\nMerci d'avance pour votre réponse.\nCordialement,\nLina Haddad",
    "started_task_id": null
  },
  {
    "id": "wr-changement-programme",
    "format": "message",
    "style_level": "A2",
    "title": "Expliquer un changement de programme",
    "prompt": "Vous deviez aller au cinéma avec votre ami Marc vendredi soir, mais vous ne pouvez plus. Écrivez-lui un message.",
    "requirements": [
      "Dites que vous ne pouvez pas venir et expliquez pourquoi.",
      "Excusez-vous.",
      "Proposez une autre date ou une autre heure."
    ],
    "word_min": 50,
    "word_max": 80,
    "example_draft": "Salut Marc,\n\nJe suis désolé, mais je ne peux pas venir au cinéma vendredi. Mon chef m'a demandé de travailler tard parce que on a un projet important. Je suis vraiment désolé. Est-ce que tu es libre samedi après-midi ? On peut voir le même film à 16 heures. Dis-moi si ça te va.\n\nÀ bientôt,\nThéo",
    "started_task_id": null
  }
];

export const notice = "Authored practice tasks (FLH writing prompts v1). Not official exam items; no score and no certified CEFR level. Names and places are invented.";

// The invitation example draft (version 1) and the learner's revision (version 2):
// the two located mistakes fixed from the hints.
export const draftV1 = "Bonjour Sophie,\n\nMerci beaucoup pour ton invitation. Je suis très content de venir à ton anniversaire samedi. Je peux apporter un gâteau au chocolat si tu veux. Est-ce que je dois aussi apporter des boissons ? Je suis arrivé vers 20 heures parce que je travaille jusqu'à 19 heures. C'est où exactement, chez toi ? Je suis pas sûr de l'adresse.\n\nÀ samedi !\nPaul";
export const draftV2 = "Bonjour Sophie,\n\nMerci beaucoup pour ton invitation. Je suis très content de venir à ton anniversaire samedi. Je peux apporter un gâteau au chocolat si tu veux. Est-ce que je dois aussi apporter des boissons ? J'arriverai vers 20 heures parce que je travaille jusqu'à 19 heures. C'est où exactement, chez toi ? Je ne suis pas sûr de l'adresse.\n\nÀ samedi !\nPaul";
export const wordsV1 = 62;
export const wordsV2 = 61;

// Feedback on version 1 as the server stores it after grounding.
export const feedbackV1: WritingFeedbackContent = {
  "task_fulfilment": {
    "rating": "partly_met",
    "comment_en": "You thank Sophie, accept, offer to bring a cake and ask practical questions; the arrival time is in a past tense although Saturday is still to come.",
    "comment_zh": "你感谢了 Sophie，接受了邀请，提出带蛋糕，也问了实际问题；但星期六还没到，到达时间却用了过去时。"
  },
  "clarity": {
    "comment_en": "Clear and easy to follow; three sentences start the same way.",
    "comment_zh": "清楚易懂；有三个句子的开头一样。"
  },
  "corrections": [
    {
      "quote": "Je suis arrivé vers 20 heures",
      "category": "grammar",
      "hint_en": "Saturday has not happened yet: which tense talks about the future?",
      "hint_zh": "星期六还没到：哪个时态表示将来？",
      "suggestion": "J'arriverai vers 20 heures",
      "reason_en": "An arrival planned for Saturday needs the futur simple, not the passé composé.",
      "reason_zh": "计划在星期六到达，要用简单将来时，不能用复合过去时。",
      "grounding": "located",
      "start": 210
    },
    {
      "quote": "Je suis pas sûr",
      "category": "register",
      "hint_en": "In writing, a negation keeps both of its parts.",
      "hint_zh": "书面语中，否定要保留两个部分。",
      "suggestion": "Je ne suis pas sûr",
      "reason_en": "Dropping « ne » belongs to spoken French; an email keeps it.",
      "reason_zh": "省略 « ne » 是口语用法，邮件里要保留。",
      "grounding": "located",
      "start": 314
    },
    {
      "quote": "Je suis",
      "category": "vocabulary",
      "hint_en": "Three sentences start the same way; can you vary one of them?",
      "hint_zh": "有三个句子开头相同，能换一种说法吗？",
      "suggestion": "J'ai hâte",
      "reason_en": "Varied sentence openings read more naturally.",
      "reason_zh": "句子开头有变化，读起来更自然。",
      "grounding": "ambiguous"
    },
    {
      "quote": "je viendrai avec plaisir",
      "category": "grammar",
      "hint_en": "Start the reply by accepting clearly.",
      "hint_zh": "回信开头要明确表示接受。",
      "suggestion": "Je viendrai avec plaisir !",
      "reason_en": "A clear acceptance answers the invitation first.",
      "reason_zh": "先明确接受，才算回应了邀请。",
      "grounding": "not_found"
    }
  ]
};
