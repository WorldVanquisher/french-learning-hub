// Exam Listening Lesson v1 wire types (private workbench; /listening routes).
// Every field is a backend fact. The French question, answer, transcript and
// excerpts are stored text and are never translated; rationales and notes are
// stored in English and Simplified Chinese.

export interface ListeningMaterial {
  id: number;
  video_id: string;
  // Canonical https://www.youtube.com/watch?v=<video_id>. The server never fetches it.
  source_url: string;
  title: string;
  created_at: string;
}

export interface TranscriptSegment {
  index: number;
  // Set only when the learner's source supplied a timestamp for this line.
  start_seconds: number | null;
  text: string;
}

export interface ListeningTranscript {
  id: number;
  version: number;
  has_timestamps: boolean;
  segments: TranscriptSegment[];
  created_at: string;
}

export type ListeningItemKind = "main_idea" | "detail" | "inference";

export interface ListeningItem {
  kind: ListeningItemKind;
  question: string;
  expected_answer: string;
  rationale_en: string;
  rationale_zh: string;
  // 1-based segment numbers of the transcript the exercise was generated from.
  segments: number[];
}

export interface ListeningAnnotation {
  kind: "vocabulary" | "grammar";
  segment: number;
  excerpt: string;
  note_en: string;
  note_zh: string;
}

export type ListeningFailureCode = "provider_timeout" | "provider_unavailable" | "invalid_output";

export interface ListeningExercise {
  id: number;
  transcript_id: number;
  status: "completed" | "failed";
  failure_code: ListeningFailureCode | null;
  generator: string;
  created_at: string;
  // Present on lesson reads; omitted (null) on list rows and failures.
  content: { items: ListeningItem[]; annotations: ListeningAnnotation[] } | null;
}

export interface ListeningGeneration {
  enabled: boolean;
  generator: string | null;
}

export interface ListeningLesson {
  material: ListeningMaterial;
  transcript: ListeningTranscript | null;
  // Newest first; failed attempts are kept.
  exercises: ListeningExercise[];
  generation: ListeningGeneration;
}

export interface ListeningSummary {
  material: ListeningMaterial;
  transcript_version: number | null;
  segment_count: number;
  latest_exercise: ListeningExercise | null;
}

export interface ListeningList {
  materials: ListeningSummary[];
  generation: ListeningGeneration;
}
