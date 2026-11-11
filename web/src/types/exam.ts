// Mock Exam v1 wire types (private workbench; /exam routes). Keys,
// explanations, reasons and evidence exist only in `result`, which the server
// sends once a session is submitted or its deadline has passed.

export type ExamState = "in_progress" | "submitted" | "expired";

export interface ExamForm {
  id: string;
  title: string;
  section: string;
  duration_seconds: number;
  description: string;
  question_count: number;
}

export interface ExamForms {
  schema_version: string;
  notice: string;
  pack: string;
  forms: ExamForm[];
}

export interface ExamPassage {
  id: string;
  title: string;
  format: string;
  style_level: string;
  segments: { id: string; text: string }[];
}

export interface ExamQuestion {
  position: number;
  passage_id: string;
  kind: string;
  question: string;
  choices: string[];
}

export interface ExamResultItem {
  position: number;
  choice: number | null;
  key: number;
  correct: boolean;
  explanation_en: string;
  explanation_zh: string;
  why_wrong: { en: string; zh: string } | null;
  evidence: { segment: string; excerpt: string }[];
  source: { pack: string; passage_id: string; question_id: string; pack_item: number; content_sha256: string };
}

export interface ExamView {
  session: {
    id: number;
    kind: "exam" | "retry";
    form_id: string;
    title: string;
    retry_of: { session_id: number; position: number } | null;
    duration_seconds: number;
    started_at: string;
    deadline_at: string;
    forms_sha256: string;
    pack_sha256: string;
  };
  state: ExamState;
  server_now: string;
  remaining_seconds: number;
  notice: string;
  passages: ExamPassage[];
  questions: ExamQuestion[];
  answers: { position: number; choice: number | null; saved_at: string }[];
  result: null | { closed: ExamState; closed_at: string; correct: number; total: number; items: ExamResultItem[] };
  replayed?: boolean;
}

export interface ExamSessionRow {
  id: number;
  kind: "exam" | "retry";
  form_id: string;
  title: string;
  retry_of: { session_id: number; position: number } | null;
  state: ExamState;
  started_at: string;
  deadline_at: string;
  question_count: number;
  result: { correct: number; total: number } | null;
}
