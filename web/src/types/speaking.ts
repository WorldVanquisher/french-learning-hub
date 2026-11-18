// Speaking v1 wire types (private workbench; /speaking routes). Every field is
// a backend fact. Audio never appears here: a take carries only metadata. The
// learner's French, the situation and suggestions are stored text and are never
// translated; comments, hints and reasons are stored in English and Simplified
// Chinese.

export interface SpeakingExercise {
  id: number;
  prompt_id: string;
  title: string;
  situation: string;
  requirements: string[];
  seconds_min: number;
  seconds_max: number;
  created_at: string;
  // The prompt's identity: its set, the fingerprint of the stored wording, and
  // whether the set still holds exactly that wording. The exercise always keeps
  // the wording the learner answered.
  prompt_set: string;
  content_fingerprint: string;
  pack_status: SpeakingPackStatus;
}

export type SpeakingPackStatus = "current" | "changed" | "removed";

export interface SpeakingCurrentPrompt {
  title: string;
  situation: string;
  requirements: string[];
  seconds_min: number;
  seconds_max: number;
  content_fingerprint: string;
}

// A take's attempt state, derived by the backend from its records.
export type SpeakingAttemptState =
  | "awaiting_transcript"
  | "transcribing"
  | "transcription_failed"
  | "transcription_unknown"
  | "transcript_to_confirm"
  | "awaiting_feedback"
  | "feedback_in_progress"
  | "feedback_failed"
  | "feedback_unknown"
  | "feedback_ready";

export type SpeakingAudioSource = "recording" | "file" | "none";

export interface SpeakingTake {
  id: number;
  number: number;
  audio_source: SpeakingAudioSource;
  audio_mime: string | null;
  audio_bytes: number | null;
  audio_sha256: string | null;
  duration_ms: number | null; // measured by the browser
  created_at: string;
  state?: SpeakingAttemptState;
}

export type SpeakingFailure = "provider_timeout" | "provider_unavailable" | "invalid_output";

export interface SpeakingTranscription {
  id: number;
  take_id: number;
  status: "completed" | "failed";
  failure_code: SpeakingFailure | null;
  transcriber: string;
  text: string | null; // the machine transcript; completed only
  created_at: string;
}

export interface SpeakingTranscript {
  id: number;
  take_id: number;
  version: number; // immutable; a correction is a new version
  text: string;
  word_count: number;
  origin: "transcription" | "corrected" | "typed";
  transcription_id: number | null;
  created_at: string;
}

// Decided by the server against the exact transcript, never by the model.
export type SpeakingGrounding = "located" | "ambiguous" | "not_found";

export interface SpeakingImprovement {
  quote: string;
  category: "grammar" | "vocabulary" | "register" | "organisation";
  hint_en: string;
  hint_zh: string;
  suggestion: string;
  reason_en: string;
  reason_zh: string;
  grounding: SpeakingGrounding;
  start?: number; // rune offset, located only
}

export interface SpeakingFeedbackContent {
  task_fulfilment: { rating: "met" | "partly_met" | "not_met"; comment_en: string; comment_zh: string };
  clarity: { comment_en: string; comment_zh: string };
  improvements: SpeakingImprovement[];
}

export interface SpeakingFeedback {
  id: number;
  transcript_id: number; // the one confirmed version this report is about
  status: "completed" | "failed";
  failure_code: SpeakingFailure | null;
  generator: string;
  created_at: string;
  content: SpeakingFeedbackContent | null;
}

export interface SpeakingRequest {
  id: number;
  operation_id: string;
  take_id?: number;
  transcript_id?: number;
  after_unknown: boolean;
  started_at: string;
  deadline_at: string;
  finished_at: string | null;
  state: "in_progress" | "completed" | "failed" | "unknown";
  result_id: number | null;
}

export interface SpeakingProviders {
  transcription: { enabled: boolean; name: string | null };
  feedback: { enabled: boolean; name: string | null };
}

export interface SpeakingLimits {
  max_audio_bytes: number;
  max_duration_ms: number;
  accepted_types: string[];
  max_transcript_chars: number;
  max_takes: number;
  max_transcript_versions: number;
}

export interface SpeakingExerciseView {
  exercise: SpeakingExercise;
  takes: SpeakingTake[];
  transcriptions: SpeakingTranscription[]; // newest first
  transcription_requests: SpeakingRequest[]; // newest first
  transcripts: SpeakingTranscript[]; // by take, then version
  feedback: SpeakingFeedback[]; // newest first
  feedback_requests: SpeakingRequest[]; // newest first
  example_transcript: string | null; // only while the stored prompt is the set's current one
  // The set's corrected wording, only when pack_status is "changed"; the
  // exercise and its takes keep the stored wording (exercise.*). The server
  // always sends it (null otherwise); optional here so hand-built test views
  // in other lanes' files need no change.
  current_prompt?: SpeakingCurrentPrompt | null;
  providers: SpeakingProviders;
  limits: SpeakingLimits;
  word_convention: string;
}

export interface SpeakingPrompt {
  id: string;
  format: string;
  style_level: string;
  title: string;
  situation: string;
  requirements: string[];
  seconds_min: number;
  seconds_max: number;
  started_exercise_id: number | null;
  started_pack_status: SpeakingPackStatus | null;
}

export interface SpeakingPrompts {
  set: string;
  notice: string;
  prompts: SpeakingPrompt[];
  providers: SpeakingProviders;
  limits: SpeakingLimits;
}

export interface SpeakingExerciseSummary {
  exercise: SpeakingExercise;
  takes: number;
}

export interface SpeakingTranscriptionResult {
  request: SpeakingRequest | null;
  transcription: SpeakingTranscription | null;
}

export interface SpeakingFeedbackResult {
  request: SpeakingRequest | null;
  feedback: SpeakingFeedback | null;
}

export interface NewSpeakingTake {
  audio_source: SpeakingAudioSource;
  audio_mime?: string;
  audio_bytes?: number;
  audio_sha256?: string;
  duration_ms?: number;
}

// The response to a saved take: the view plus the take saved. The same audio
// sent again names the existing take (replayed).
export interface SpeakingTakeSaved extends SpeakingExerciseView {
  take_id: number;
  replayed: boolean;
}

export type SpeakingQueueReason =
  | "check_unknown_outcome"
  | "request_failed"
  | "confirm_transcript"
  | "add_transcript"
  | "request_feedback"
  | "review_without_feedback" // checked transcript, feedback off: review it yourself
  | "answer_again"
  | "start_first_take"
  | "request_in_progress" // a request is running: check again in a moment
  | "not_started";

export interface SpeakingQueueItem {
  reason: SpeakingQueueReason;
  priority: number; // ordinal, 0 = most urgent
  prompt_id: string;
  title: string;
  exercise_id: number | null; // null: the prompt is not started yet
  take_id: number | null;
  take_number: number | null;
  state: SpeakingAttemptState | null;
  improvements: number;
  since: string | null;
  // The provider request this step concerns (null when none applies, e.g. a
  // typed take awaiting its transcript) and whether it can be sent now.
  request: "transcription" | "feedback" | null;
  request_enabled: boolean;
  pack_status: SpeakingPackStatus | null; // null for a prompt not started
}

export interface SpeakingAttemptSummary {
  take_id: number;
  take_number: number;
  state: SpeakingAttemptState;
  transcript_versions: number;
  latest_version: number | null;
  feedback_id: number | null;
  feedback_rating: string | null;
  improvements: number;
  activity_at: string;
  take_created_at: string;
  audio_source: SpeakingAudioSource;
  transcript_origin: string | null;
}

export interface SpeakingPracticeSummary {
  prompts: number;
  started: number;
  takes: number;
  completed: number; // feedback ready on the take's latest confirmed version
  exercises_completed: number;
  awaiting_transcript: number;
  awaiting_feedback: number;
  in_progress: number;
  failed: number;
  unknown: number;
  last_completed_at: string | null;
}

// GET /speaking/practice: read-only, derived from the stored records.
export interface SpeakingPractice {
  schema_version: "speaking_practice_v1";
  generated_at: string;
  summary: SpeakingPracticeSummary;
  queue: SpeakingQueueItem[];
  // The queue item of the most recently active exercise whose latest take is
  // not complete; null when every started exercise is complete.
  resume: SpeakingQueueItem | null;
  exercises: { exercise: SpeakingExercise; takes: number; completed: number; latest: SpeakingAttemptSummary | null; last_activity_at: string }[];
  providers: SpeakingProviders;
}
