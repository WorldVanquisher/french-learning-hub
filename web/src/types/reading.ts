// Exam Reading v1 wire types (private workbench; /reading routes). Every field
// is a backend fact. The French passage, questions and answers are stored text
// and are never translated; explanations and reasons are stored in English and
// Simplified Chinese.

export interface ReadingSegment {
  id: string; // stable paragraph ID: p1, p2, ...
  text: string; // exact wording
}

export interface ReadingLesson {
  id: number;
  title: string;
  // https, stored as text; the server never fetches it.
  source_url: string | null;
  origin: "learner" | "authored";
  pack_passage_id: string | null;
  created_at: string;
}

export interface ReadingPassage {
  id: number;
  version: number;
  segments: ReadingSegment[];
  created_at: string;
}

export interface ReadingEvidence {
  segment: string;
  // Occurs exactly once in that paragraph (validated before storage).
  excerpt: string;
}

export interface ReadingWrongAnswer {
  answer: string;
  why_wrong_en: string;
  why_wrong_zh: string;
}

export type ReadingItemKind = "main_idea" | "detail" | "inference";

export interface ReadingItem {
  id?: string;
  kind: ReadingItemKind;
  question: string;
  reference_answer: string;
  accepted_alternatives: string[];
  // Authored exercises list plausible wrong answers; generated ones may not.
  wrong_answers: ReadingWrongAnswer[];
  evidence: ReadingEvidence[];
  explanation_en: string;
  explanation_zh: string;
}

export interface ReadingExerciseContent {
  items: ReadingItem[];
  no_inference_reason?: string;
}

export type ReadingFailureCode = "provider_timeout" | "provider_unavailable" | "invalid_output";

export interface ReadingExercise {
  id: number;
  passage_id: number;
  status: "completed" | "failed";
  failure_code: ReadingFailureCode | null;
  // authored:flh_reading_pack_v1 or openai:<model>:reading_exercise_v1
  generator: string;
  created_at: string;
  content: ReadingExerciseContent | null;
}

export type ReadingAttemptState = "in_progress" | "completed" | "failed" | "unknown";

export interface ReadingPreparation {
  id: number;
  operation_id: string;
  passage_id: number;
  after_unknown: boolean;
  started_at: string;
  deadline_at: string;
  finished_at: string | null;
  state: ReadingAttemptState;
  exercise_id: number | null;
}

export type ReadingLessonState = "ready_to_prepare" | "in_progress" | "prepared" | "failed" | "outcome_unknown";

export interface ReadingGeneration {
  enabled: boolean;
  generator: string | null;
}

export interface ReadingLessonView {
  lesson: ReadingLesson;
  passage: ReadingPassage; // latest version
  versions: number;
  exercises: ReadingExercise[]; // newest first, every version
  preparations: ReadingPreparation[]; // newest first
  state: ReadingLessonState;
  generation: ReadingGeneration;
}

export interface ReadingSummary {
  lesson: ReadingLesson;
  passage_version: number;
  paragraphs: number;
  state: ReadingLessonState;
}

export interface ReadingList {
  lessons: ReadingSummary[];
  generation: ReadingGeneration;
}

export interface ReadingExample {
  id: string;
  title: string;
  format: string;
  style_level: string;
  paragraphs: number;
  questions: number;
  has_inference: boolean;
  imported_lesson_id: number | null;
}

export interface ReadingExamples {
  pack: string;
  notice: string;
  examples: ReadingExample[];
}

export interface ReadingPreparationResult {
  preparation: ReadingPreparation | null;
  exercise: ReadingExercise | null;
}
