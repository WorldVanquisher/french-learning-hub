// Exam Listening Lesson v1 wire types (private workbench; /listening routes).
// Every field is a backend fact. The French question, answer, transcript and
// excerpts are stored text and are never translated; rationales and notes are
// stored in English and Simplified Chinese.

// "youtube": a saved or pulled video link. "authored_script": written text
// imported from the embedded script pack; it has no link, no video, no audio
// and no timestamp, and the workbench never shows one for it.
export type ListeningSourceKind = "youtube" | "authored_script";

export interface ListeningMaterial {
  id: number;
  source_kind: ListeningSourceKind;
  // YouTube only (null for an authored script).
  video_id: string | null;
  // YouTube only: canonical https://www.youtube.com/watch?v=<video_id>. The
  // server never fetches it. Null for an authored script.
  source_url: string | null;
  // Authored script only: flh_listening_script_pack_v1/<script id>.
  pack_script_id: string | null;
  title: string;
  created_at: string;
}

export interface TranscriptSegment {
  index: number;
  // Set only when the learner's source supplied a timestamp for this line.
  start_seconds: number | null;
  // Authored scripts only: the speaker the script names for this line.
  speaker?: string;
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

export interface ListeningWrongAnswer {
  answer: string;
  why_wrong_en: string;
  why_wrong_zh: string;
}

// A verbatim excerpt that occurs exactly once in the cited segment.
export interface ListeningEvidence {
  segment: number;
  excerpt: string;
}

export interface ListeningItem {
  // Authored scripts only: the workbook question ID.
  id?: string;
  kind: ListeningItemKind;
  question: string;
  expected_answer: string;
  rationale_en: string;
  rationale_zh: string;
  // 1-based segment numbers of the transcript the exercise was generated from.
  segments: number[];
  // Authored scripts only. choices: the options in authored order (single
  // choice); absent for a short answer.
  choices?: string[];
  accepted_alternatives?: string[];
  wrong_answers?: ListeningWrongAnswer[];
  evidence?: ListeningEvidence[];
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
  // The exercise the lesson shows (the server decides): the newest completed
  // one on the latest transcript; for an authored script, always its authored
  // exercise of its current revision. null when there is none.
  current_exercise_id: number | null;
  // Authored script only: its current revision compared with the server's
  // pack (null for YouTube). Older servers omit it.
  script_revision?: ListeningScriptRevisionState | null;
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

// ---- Authored listening scripts (GET /listening/scripts) ----

// One script offered for import: what it is, never its lines or key.
export interface ListeningScriptSummary {
  id: string;
  title: string;
  genre: string;
  style_level: string;
  source_pack: string;
  notice: string;
  lines: number;
  questions: number;
  imported_material_id: number | null;
  // Imported scripts only (null otherwise; older servers omit them).
  imported_revision?: number | null;
  pack_status?: ListeningScriptPackStatus | null;
}

export interface ListeningScripts {
  pack: string;
  scripts: ListeningScriptSummary[];
}

// ---- Revisions of an imported script (explicit, previewed update) ----
//
// Revision N of an imported script is its transcript version N with the
// authored exercise on it. A pack correction never changes a lesson by itself:
// the learner reads the preview and confirms it, and the update appends the
// next revision. Earlier revisions and the Mistake Notebook items saved from
// them stay exactly as they were.

// "title_changed": the pack renamed the script; a lesson's title is fixed, so
// no update is offered. "not_in_pack": this server's pack no longer has it.
export type ListeningScriptPackStatus = "up_to_date" | "update_available" | "title_changed" | "not_in_pack";

export interface ListeningScriptRevisionState {
  script_id: string;
  revision: number;
  fingerprint: string;
  pack_status: ListeningScriptPackStatus;
  pack_fingerprint: string | null;
}

export interface ListeningScriptLine {
  id: string;
  speaker: string;
  text: string;
}

export interface ListeningScriptLineChange {
  line: string;
  change: "changed" | "added" | "removed";
  before: ListeningScriptLine | null;
  after: ListeningScriptLine | null;
}

export type ListeningQuestionField =
  | "kind"
  | "question"
  | "choices"
  | "expected_answer"
  | "accepted_alternatives"
  | "wrong_answers"
  | "rationale"
  | "segments"
  | "evidence"
  | "position";

export interface ListeningScriptQuestionChange {
  item_id: string;
  change: "changed" | "added" | "removed";
  before_position: number | null;
  after_position: number | null;
  fields: ListeningQuestionField[];
  before: ListeningItem | null;
  after: ListeningItem | null;
}

// GET /listening/materials/{id}/script-update (read-only).
export interface ListeningScriptUpdatePreview {
  material_id: number;
  script_id: string;
  current_revision: number;
  current_fingerprint: string;
  pack_status: ListeningScriptPackStatus;
  pack_fingerprint: string;
  // Set only when an update is available.
  next_revision: number | null;
  changes: {
    lines: ListeningScriptLineChange[];
    questions: ListeningScriptQuestionChange[];
    annotations_changed: boolean;
  };
}

// POST /listening/materials/{id}/script-update: 201 updated, 200 replayed
// (the lesson already had the pack's content; nothing written).
export interface ListeningScriptUpdateResult {
  revision: number;
  replayed: boolean;
  lesson: ListeningLesson;
}

// GET /listening/materials/{id}/revisions/{n}: one revision, e.g. the one a
// Mistake Notebook item was saved from.
export interface ListeningScriptRevisionView {
  material_id: number;
  revision: number;
  current_revision: number;
  fingerprint: string;
  transcript: ListeningTranscript;
  exercise: ListeningExercise;
}
