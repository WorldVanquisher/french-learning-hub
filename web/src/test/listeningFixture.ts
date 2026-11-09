// Exam Listening Lesson v1: the authored, synthetic French fixture shared by the
// workbench tests. The transcript is examples/listening/synthetic-lesson.fr.txt;
// the exercise is what the local fake provider in the Go integration test
// returns for it. Typed against the wire types, so drift fails the typecheck.
// Nothing here is a real learner record or a real video.
import type { ListeningExercise, ListeningLesson, ListeningMaterial, TranscriptSegment } from "../types/listening";

export const transcriptText = `[00:00] Bonjour à tous, et bienvenue dans « La minute du quartier ».
[00:04] Aujourd'hui, je vous parle de la nouvelle bibliothèque qui ouvre samedi, rue des Lilas.
[00:10] Elle sera ouverte du mardi au dimanche, de dix heures à dix-neuf heures.
[00:16] L'inscription est gratuite pour les habitants du quartier ; il suffit d'apporter un justificatif de domicile.
[00:23] Il y aura aussi un atelier de conversation en français le mercredi soir.
[00:29] Franchement, je trouve que c'est une excellente nouvelle, surtout pour les familles.
[00:35] Alors, n'hésitez pas à passer samedi : il y aura même un petit concert dans le jardin.
[00:41] À la semaine prochaine !`;

// parseTranscript mirrors the server's rules closely enough for the fake
// server: one segment per non-empty line, with an optional leading [mm:ss].
export function parseTranscript(text: string): TranscriptSegment[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line, i) => {
      const m = /^\[(\d{1,2}):(\d{2})\]\s+(.*)$/.exec(line);
      return m
        ? { index: i + 1, start_seconds: Number(m[1]) * 60 + Number(m[2]), text: m[3] }
        : { index: i + 1, start_seconds: null, text: line };
    });
}

export const segments = parseTranscript(transcriptText);

export const material: ListeningMaterial = {
  id: 1,
  video_id: "FLHlisten01",
  source_url: "https://www.youtube.com/watch?v=FLHlisten01",
  title: "La minute du quartier",
  created_at: "2026-11-08T09:00:00Z",
};

export const content: NonNullable<ListeningExercise["content"]> = {
  items: [
    {
      kind: "main_idea",
      question: "Quel est le sujet principal de cette chronique ?",
      expected_answer: "L'ouverture d'une nouvelle bibliothèque dans le quartier, samedi.",
      rationale_en: "Segment 2 announces the opening.",
      rationale_zh: "第2段宣布了开馆。",
      segments: [2],
    },
    {
      kind: "detail",
      question: "Que faut-il apporter pour s'inscrire ?",
      expected_answer: "Un justificatif de domicile.",
      rationale_en: "Segment 4 states the condition.",
      rationale_zh: "第4段说明了条件。",
      segments: [4],
    },
    {
      kind: "inference",
      question: "Quelle est l'attitude du chroniqueur ?",
      expected_answer: "Il est enthousiaste et encourage les auditeurs à venir.",
      rationale_en: "« Une excellente nouvelle » and « n'hésitez pas » show it.",
      rationale_zh: "« une excellente nouvelle » 和 « n'hésitez pas » 表明了这一点。",
      segments: [6, 7],
    },
  ],
  annotations: [
    { kind: "vocabulary", segment: 4, excerpt: "justificatif de domicile", note_en: "proof of address", note_zh: "住址证明" },
    { kind: "grammar", segment: 7, excerpt: "n'hésitez pas à", note_en: "imperative + à + infinitive: don't hesitate to", note_zh: "命令式 + à + 不定式：不要犹豫……" },
  ],
};

export function lesson(overrides: Partial<ListeningLesson> = {}): ListeningLesson {
  return {
    material,
    transcript: { id: 10, version: 1, has_timestamps: true, segments, created_at: "2026-11-08T09:00:00Z" },
    exercises: [],
    generation: { enabled: true, generator: "openai:fake-model:listening_exercise_v1" },
    ...overrides,
  };
}

export const completed = (id = 100): ListeningExercise => ({
  id,
  transcript_id: 10,
  status: "completed",
  failure_code: null,
  generator: "openai:fake-model:listening_exercise_v1",
  created_at: "2026-11-08T09:05:00Z",
  content,
});
