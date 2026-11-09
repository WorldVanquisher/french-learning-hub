// Exam Reading v1: the authored fixture shared by the workbench tests,
// generated from internal/reading/pack/reading_pack_v1.json (passage
// rd-email-chaudiere). Typed against the wire types, so drift fails the
// typecheck. Authored practice material, not an official exam item.
import type { ReadingExercise, ReadingItem, ReadingLessonView, ReadingSegment } from "../types/reading";

export const segments: ReadingSegment[] = [
  {
    "id": "p1",
    "text": "Bonjour Madame Lefèvre, comme chaque année, la chaudière de votre appartement doit être révisée avant l'hiver. Le technicien de l'entreprise Thermo-Services passera le mardi 14 octobre, entre 9 h et 12 h."
  },
  {
    "id": "p2",
    "text": "La visite dure environ quarante-cinq minutes. Il faudra simplement libérer l'accès au placard de la cuisine, où se trouve la chaudière. Vous n'avez rien à payer : l'entretien est compris dans les charges."
  },
  {
    "id": "p3",
    "text": "Si vous n'êtes pas disponible ce jour-là, merci de me prévenir avant jeudi soir. Passé ce délai, je ne pourrai plus modifier le rendez-vous, et le technicien ne reviendra pas dans l'immeuble avant le mois de décembre."
  },
  {
    "id": "p4",
    "text": "Vous pouvez aussi laisser une clé à la gardienne, qui accompagnera le technicien. Bien cordialement, Paul Moreau, propriétaire"
  }
];

export const items: ReadingItem[] = [
  {
    "id": "rd-email-chaudiere:q1",
    "kind": "main_idea",
    "question": "Pourquoi M. Moreau écrit-il à Mme Lefèvre ?",
    "reference_answer": "Pour l'informer de la visite annuelle d'entretien de sa chaudière, le mardi 14 octobre au matin.",
    "accepted_alternatives": [
      "Pour annoncer la révision de la chaudière le 14 octobre entre 9 h et 12 h."
    ],
    "wrong_answers": [
      {
        "answer": "Pour lui demander de payer une réparation.",
        "why_wrong_en": "The visit is routine maintenance and costs nothing (p2).",
        "why_wrong_zh": "这是例行保养，而且不收费（p2）。"
      }
    ],
    "evidence": [
      {
        "segment": "p1",
        "excerpt": "la chaudière de votre appartement doit être révisée avant l'hiver"
      },
      {
        "segment": "p1",
        "excerpt": "passera le mardi 14 octobre, entre 9 h et 12 h"
      }
    ],
    "explanation_en": "The email announces a yearly service visit and gives its date; the other paragraphs are practical details.",
    "explanation_zh": "邮件通知每年一次的保养上门时间，其余段落是具体安排。"
  },
  {
    "id": "rd-email-chaudiere:q2",
    "kind": "detail",
    "question": "Que doit faire Mme Lefèvre si elle ne peut pas être là le 14 octobre ?",
    "reference_answer": "Prévenir M. Moreau avant jeudi soir, ou laisser une clé à la gardienne.",
    "accepted_alternatives": [
      "Prévenir le propriétaire avant jeudi soir.",
      "Laisser une clé à la gardienne."
    ],
    "wrong_answers": [
      {
        "answer": "Appeler l'entreprise Thermo-Services.",
        "why_wrong_en": "She is asked to tell the landlord (« me prévenir »), not the company.",
        "why_wrong_zh": "邮件请她通知房东（« me prévenir »），而不是联系公司。"
      }
    ],
    "evidence": [
      {
        "segment": "p3",
        "excerpt": "merci de me prévenir avant jeudi soir"
      },
      {
        "segment": "p4",
        "excerpt": "laisser une clé à la gardienne"
      }
    ],
    "explanation_en": "Two options are given: warn the landlord before Thursday evening, or leave a key with the caretaker. Either one alone is an acceptable answer.",
    "explanation_zh": "邮件给出了两个办法：周四晚上之前通知房东，或者把钥匙留给门房。只答出其中一个也算对。"
  },
  {
    "id": "rd-email-chaudiere:q3",
    "kind": "inference",
    "question": "Pourquoi est-il dans l'intérêt de Mme Lefèvre de répondre rapidement ?",
    "reference_answer": "Parce que, sans réponse avant jeudi soir, l'entretien ne pourrait pas être fait avant décembre, c'est-à-dire probablement après le début de l'hiver.",
    "accepted_alternatives": [
      "Sinon, la révision serait repoussée à décembre, trop tard pour l'hiver."
    ],
    "wrong_answers": [
      {
        "answer": "Parce qu'elle devra payer une pénalité.",
        "why_wrong_en": "No penalty is mentioned; the only consequence is the delay to December.",
        "why_wrong_zh": "邮件没有提到罚款，唯一的后果是推迟到十二月。"
      }
    ],
    "evidence": [
      {
        "segment": "p1",
        "excerpt": "doit être révisée avant l'hiver"
      },
      {
        "segment": "p3",
        "excerpt": "Passé ce délai, je ne pourrai plus modifier le rendez-vous"
      },
      {
        "segment": "p3",
        "excerpt": "le technicien ne reviendra pas dans l'immeuble avant le mois de décembre"
      }
    ],
    "explanation_en": "Inference: the text never says « répondez vite », but the deadline, the December delay and « avant l'hiver » together imply it.",
    "explanation_zh": "这是推断：原文没有直接说“快回复”，但截止时间、推迟到十二月以及 « avant l'hiver » 放在一起，就能推出这一点。"
  }
];

export const passageText = segments.map((s) => s.text).join("\n\n");

export const authoredExercise = (id = 1, passageId = 1): ReadingExercise => ({
  id,
  passage_id: passageId,
  status: "completed",
  failure_code: null,
  generator: "authored:flh_reading_pack_v1",
  created_at: "2026-11-09T09:00:00Z",
  content: { items },
});

// generatedItems is what a model would return: no IDs, no wrong answers.
export const generatedItems: ReadingItem[] = items.map(({ id: _id, ...rest }) => ({ ...rest, wrong_answers: [] }));

export function lessonView(overrides: Partial<ReadingLessonView> = {}): ReadingLessonView {
  return {
    lesson: { id: 1, title: "Objet : visite d'entretien de la chaudière", source_url: null, origin: "authored", pack_passage_id: "flh_reading_pack_v1/rd-email-chaudiere", created_at: "2026-11-09T09:00:00Z" },
    passage: { id: 1, version: 1, segments, created_at: "2026-11-09T09:00:00Z" },
    versions: 1,
    exercises: [authoredExercise()],
    preparations: [],
    state: "prepared",
    generation: { enabled: true, generator: "openai:fake-model:reading_exercise_v1" },
    ...overrides,
  };
}
