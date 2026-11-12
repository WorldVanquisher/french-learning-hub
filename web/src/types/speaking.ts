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
}

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
  example_transcript: string;
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
