// Exam Writing v1 wire types (private workbench; /writing routes). Every field
// is a backend fact. The learner's French, the prompt and suggestions are
// stored text and are never translated; comments, hints and reasons are
// stored in English and Simplified Chinese.

export interface WritingTask {
  id: number;
  title: string;
  prompt: string;
  requirements: string[];
  word_min: number;
  word_max: number;
  origin: "learner" | "authored";
  prompt_id: string | null;
  created_at: string;
}

export interface WritingDraft {
  id: number;
  version: number; // immutable; a revision is a new version
  text: string;
  word_count: number;
  created_at: string;
}

// Decided by the server against the exact draft text, never by the model.
export type WritingGrounding = "located" | "ambiguous" | "not_found";

export interface WritingCorrection {
  quote: string;
  category: "grammar" | "vocabulary" | "spelling" | "register" | "punctuation" | "organisation";
  hint_en: string;
  hint_zh: string;
  suggestion: string;
  reason_en: string;
  reason_zh: string;
  grounding: WritingGrounding;
  start?: number; // rune offset, located only
}

export interface WritingFeedbackContent {
  task_fulfilment: { rating: "met" | "partly_met" | "not_met"; comment_en: string; comment_zh: string };
  clarity: { comment_en: string; comment_zh: string };
  corrections: WritingCorrection[];
}

export interface WritingFeedback {
  id: number;
  draft_id: number; // the one version this report is about
  status: "completed" | "failed";
  failure_code: "provider_timeout" | "provider_unavailable" | "invalid_output" | null;
  generator: string;
  created_at: string;
  content: WritingFeedbackContent | null;
}

export interface WritingRequest {
  id: number;
  operation_id: string;
  draft_id: number;
  after_unknown: boolean;
  started_at: string;
  deadline_at: string;
  finished_at: string | null;
  state: "in_progress" | "completed" | "failed" | "unknown";
  feedback_id: number | null;
}

export interface WritingTaskView {
  task: WritingTask;
  drafts: WritingDraft[]; // oldest first
  feedback: WritingFeedback[]; // newest first
  requests: WritingRequest[]; // newest first
  generation: { enabled: boolean; generator: string | null };
  word_convention: string;
}

export interface WritingTaskSummary {
  task: WritingTask;
  versions: number;
  feedback: number;
}

export interface WritingPrompt {
  id: string;
  format: string;
  style_level: string;
  title: string;
  prompt: string;
  requirements: string[];
  word_min: number;
  word_max: number;
  example_draft: string;
  started_task_id: number | null;
}

export interface WritingPrompts {
  set: string;
  notice: string;
  prompts: WritingPrompt[];
}

export interface WritingFeedbackResult {
  request: WritingRequest | null;
  feedback: WritingFeedback | null;
}
