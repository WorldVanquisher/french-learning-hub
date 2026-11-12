// Mistake Notebook v1 wire types (private workbench; /mistake-notebook routes
// and GET /entries/{id}/source). Every field is a backend fact read from the
// stored source item, never from a record's prose.

export type Skill = "listening" | "reading" | "writing" | "speaking";
export type SourceType = "listening_item" | "reading_item" | "writing_correction" | "speaking_improvement";

// The source_ref a save path sends with its learning_capture_v1 capture.
export interface SourceRef {
  type: SourceType;
  record_id: number;
  item: number; // 1-based
  attempt?: string; // listening/reading only, when the learner chose to include it
}

export interface SourceLink {
  listening_material_id?: number;
  listening_exercise_id?: number;
  listening_transcript_version?: number;
  reading_lesson_id?: number;
  reading_passage_version?: number;
  reading_exercise_id?: number;
  writing_task_id?: number;
  writing_draft_id?: number;
  writing_draft_version?: number;
  writing_feedback_id?: number;
  speaking_exercise_id?: number;
  speaking_take_id?: number;
  speaking_take_number?: number;
  speaking_transcript_id?: number;
  speaking_transcript_version?: number;
  speaking_feedback_id?: number;
}

export interface NotebookItem {
  entry_id: number;
  capture_id: string;
  saved_at: string;
  skill: Skill;
  source: { type: SourceType; record_id: number; item: number; attempt: string | null };
  title: string;
  prompt: string;
  category: string;
  quote: string | null; // writing/speaking: the learner's own words in that version
  reference: string;
  explanation_en: string;
  explanation_zh: string;
  hint_en: string | null;
  hint_zh: string | null;
  link: SourceLink;
  record: { original_input: string; original_context: string };
  retry: { marked: boolean; since: string | null };
  // FLH sections v1. A source that can no longer be read is "missing" or
  // "unusable": the item then carries only its stored reference, nothing guessed.
  source_status: "resolved" | "missing" | "unusable";
  // Who wrote the reference: an authored pack, or a model nobody reviewed.
  reference_origin: "authored" | "generated" | "";
  generator: string;
  // The source's newer version, when the item came from an older one.
  latest_version: number | null;
}

export interface NotebookList {
  items: NotebookItem[];
  unlinked_notice: string;
}

export type EntrySource = { entry_id: number; linked: true; item: NotebookItem } | { entry_id: number; linked: false; notice: string };

export type KindView = "grammar" | "vocabulary" | "unclassified";

export interface KindConcept {
  concept_id: number;
  target: string;
  pedagogical_intent: string;
  scope: string;
  state: string;
  class: KindView;
  reason: "no_supporting_unit" | "mixed_kinds" | "other_kind" | null;
  kinds: string[];
  supporting_unit_count: number;
  match_tier: string;
}

export interface KindConcepts {
  rule: string;
  kind: KindView;
  query: string;
  tokens: string[];
  classified: number;
  truncated: boolean;
  concepts: KindConcept[];
}

// SourceOpen asks a skill view to open the exact item a notebook record names.
export type SourceOpen =
  | { skill: "listening"; materialId: number; exerciseId: number; item: number; version: number }
  | { skill: "reading"; lessonId: number; exerciseId: number; item: number; version: number }
  | { skill: "writing"; taskId: number; draftVersion: number }
  | { skill: "speaking"; exerciseId: number; takeId: number; transcriptVersion: number };

export function sourceOpen(item: NotebookItem): SourceOpen | null {
  const l = item.link;
  if (item.source_status !== "resolved") return null;
  switch (item.skill) {
    case "listening":
      return l.listening_material_id && l.listening_exercise_id
        ? { skill: "listening", materialId: l.listening_material_id, exerciseId: l.listening_exercise_id, item: item.source.item, version: l.listening_transcript_version ?? 0 }
        : null;
    case "reading":
      return l.reading_lesson_id && l.reading_exercise_id
        ? { skill: "reading", lessonId: l.reading_lesson_id, exerciseId: l.reading_exercise_id, item: item.source.item, version: l.reading_passage_version ?? 0 }
        : null;
    case "writing":
      return l.writing_task_id && l.writing_draft_version ? { skill: "writing", taskId: l.writing_task_id, draftVersion: l.writing_draft_version } : null;
    case "speaking":
      return l.speaking_exercise_id && l.speaking_take_id && l.speaking_transcript_version
        ? { skill: "speaking", exerciseId: l.speaking_exercise_id, takeId: l.speaking_take_id, transcriptVersion: l.speaking_transcript_version }
        : null;
  }
}
