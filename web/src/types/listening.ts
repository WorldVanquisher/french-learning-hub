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

// Derived by the backend from the latest transcript and the latest attempt.
export type ListeningMaterialState =
  | "waiting_for_transcript"
  | "ready_to_prepare"
  | "in_progress"
  | "prepared"
  | "failed"
  | "outcome_unknown";

// "unknown": the request reached the provider but no usable answer was stored
// (a timeout, a lost response, or an attempt left unfinished past its deadline).
// It may have been processed and billed; only an acknowledged, explicit retry
// calls again.
export type ListeningAttemptState = "in_progress" | "completed" | "failed" | "unknown";

export interface ListeningPreparation {
  id: number;
  operation_id: string;
  material_id: number;
  transcript_id: number;
  trigger: "explicit" | "pull";
  pull_run_id: number | null;
  after_unknown: boolean;
  started_at: string;
  deadline_at: string;
  finished_at: string | null;
  state: ListeningAttemptState;
  exercise_id: number | null;
}

export type ListeningNotificationState = "in_progress" | "sent" | "failed" | "unknown";
export type ListeningNotificationFailure = "not_sent" | "refused" | "no_response";

export interface ListeningNotification {
  id: number;
  operation_id: string;
  exercise_id: number;
  channel: string;
  trigger: "pull" | "explicit";
  pull_run_id: number | null;
  after_unknown: boolean;
  started_at: string;
  deadline_at: string;
  finished_at: string | null;
  state: ListeningNotificationState;
  failure_code: ListeningNotificationFailure | null;
}

export interface ListeningNotifySettings {
  enabled: boolean;
  channel: string | null;
}

export interface ListeningLesson {
  material: ListeningMaterial;
  transcript: ListeningTranscript | null;
  // Newest first; failed attempts are kept.
  exercises: ListeningExercise[];
  generation: ListeningGeneration;
  state: ListeningMaterialState;
  // The video is in the configured playlist (a pull created or matched it).
  in_playlist: boolean;
  // Newest first, explicit and pull attempts alike.
  preparations: ListeningPreparation[];
  // Newest first, for this material's exercises.
  notifications: ListeningNotification[];
  notification: ListeningNotifySettings;
}

export interface ListeningSummary {
  material: ListeningMaterial;
  transcript_version: number | null;
  segment_count: number;
  latest_exercise: ListeningExercise | null;
  state: ListeningMaterialState;
  in_playlist: boolean;
}

// One explicit Prepare request: the attempt and, once finished, its exercise
// (without content; the lesson read has it).
export interface ListeningPreparationResult {
  preparation: ListeningPreparation | null;
  exercise: ListeningExercise | null;
}

export type ListeningSourceFailure = "source_timeout" | "source_unavailable" | "source_refused" | "invalid_response";
export type ListeningPrepareOutcome = "disabled" | "nothing_to_prepare" | "daily_cap_reached" | "completed" | "failed" | "unknown";
export type ListeningNotifyOutcome = "disabled" | "nothing_ready" | "sent" | "failed" | "unknown";

// One pull: the workbench's "Pull now" or the operator command (timer).
export interface ListeningPullRun {
  id: number;
  operation_id: string;
  trigger: "manual" | "scheduled";
  // A running run past its lease is reported as interrupted.
  status: "running" | "finished" | "interrupted";
  started_at: string;
  lease_expires_at: string;
  finished_at: string | null;
  source: { outcome: "disabled" | "ok" | "failed" | null; failure: ListeningSourceFailure | null };
  items: { seen: number; created: number; known: number; skipped: number };
  preparation: { outcome: ListeningPrepareOutcome | null; attempt: ListeningPreparation | null };
  notification: { outcome: ListeningNotifyOutcome | null; attempt: ListeningNotification | null };
}

export interface ListeningDaily {
  pull_enabled: boolean;
  source: { enabled: boolean; name: string | null };
  preparation: {
    enabled: boolean;
    generator: string | null;
    daily_cap: number;
    timezone: string;
    today: string;
    used_today: number;
  };
  notification: ListeningNotifySettings;
  last_run: ListeningPullRun | null;
}

export interface ListeningList {
  materials: ListeningSummary[];
  generation: ListeningGeneration;
}
