import type { NotebookItem, Skill, SourceType } from "../types/notebook";

// Notebook to practice (practice_draft_v1, private workbench).
//
// A practice draft is built from one Mistake Notebook record, in the page
// only. Its source text and its provenance are read from that record's stored
// source (the exact exercise item, writing correction or speaking improvement,
// and the revision the learner saw), never from prose. The draft question
// starts as stored French text: the item's question, or the learner's own
// words for a correction. The learner may edit it and the expected action
// before approving. Approving puts the record into Review Today through the
// notebook's existing retry save; the edited wording stays in this page
// (storing it needs a table the owner has not allocated:
// docs/validation/NOTEBOOK-PRACTICE.md).

export const PRACTICE_DRAFT_VERSION = "practice_draft_v1";

export type PracticeAction = "answer_again" | "write_corrected" | "say_corrected";
export const PRACTICE_ACTIONS: PracticeAction[] = ["answer_again", "write_corrected", "say_corrected"];

// The source revision a draft came from: the stored record and the version of
// its source the learner saw. A newer version is reported, never followed.
export interface PracticeProvenance {
  entryId: number;
  type: SourceType;
  recordId: number;
  item: number;
  version: number; // transcript / passage / draft / transcript version
  latestVersion: number | null;
}

export interface PracticeDraft {
  key: string; // `${entryId}:${copy}`
  copy: number; // 1, or 2+ for a deliberate separate version
  skill: Skill;
  title: string;
  sourcePrompt: string; // stored question, task prompt or situation
  sourceWords: string | null; // the learner's own words (writing/speaking) or included answer
  question: string; // editable; starts as stored French text
  action: PracticeAction; // editable
  provenance: PracticeProvenance;
}

// Why a record cannot become a draft, or what the learner should know first.
export type DraftProblem = "missing" | "unusable" | "newer" | null;

export function draftProblem(item: NotebookItem): DraftProblem {
  if (item.source_status === "missing") return "missing";
  if (item.source_status === "unusable") return "unusable";
  if (item.latest_version) return "newer";
  return null;
}

export function sourceVersion(item: NotebookItem): number {
  const l = item.link;
  switch (item.skill) {
    case "listening":
      return l.listening_transcript_version ?? 0;
    case "reading":
      return l.reading_passage_version ?? 0;
    case "writing":
      return l.writing_draft_version ?? 0;
    case "speaking":
      return l.speaking_transcript_version ?? 0;
  }
}

const defaultAction = (skill: Skill): PracticeAction =>
  skill === "writing" ? "write_corrected" : skill === "speaking" ? "say_corrected" : "answer_again";

// buildDraft returns null for a record whose source can no longer be read:
// nothing is guessed in its place.
export function buildDraft(item: NotebookItem, copy = 1): PracticeDraft | null {
  const problem = draftProblem(item);
  if (problem === "missing" || problem === "unusable") return null;
  const words = item.quote ?? item.source.attempt ?? null;
  const correction = item.skill === "writing" || item.skill === "speaking";
  return {
    key: `${item.entry_id}:${copy}`,
    copy,
    skill: item.skill,
    title: item.title,
    sourcePrompt: item.prompt,
    sourceWords: words,
    question: correction && item.quote ? item.quote : item.prompt,
    action: defaultAction(item.skill),
    provenance: {
      entryId: item.entry_id,
      type: item.source.type,
      recordId: item.source.record_id,
      item: item.source.item,
      version: sourceVersion(item),
      latestVersion: item.latest_version,
    },
  };
}

// nextCopy is the number of a deliberate second (third…) version of the same
// record in this page.
export function nextCopy(drafts: PracticeDraft[], entryId: number): number {
  return drafts.filter((d) => d.provenance.entryId === entryId).reduce((n, d) => Math.max(n, d.copy), 0) + 1;
}

// approvalTargets: the distinct records to put into Review Today. Two versions
// of one record are one retry mark (the store holds one mark per record), so
// repeated approval or a second copy never adds a second queue item.
export function approvalTargets(drafts: PracticeDraft[]): number[] {
  return [...new Set(drafts.map((d) => d.provenance.entryId))];
}

// A draft is ready when its question is not blank. Edits keep the text as
// typed (no trimming, case or accent change) apart from that check.
export const draftReady = (d: PracticeDraft) => d.question.trim().length > 0;
