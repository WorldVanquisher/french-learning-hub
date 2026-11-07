// The stage of one learning record in the daily journey, derived on every render
// from backend reads the record detail already makes. Nothing here is stored and
// nothing is a second workflow state: each step only restates server facts
// (latest analysis and its effective resolution, the current extraction, the
// backend's reviewable-unit list and each decided unit's effective annotation).
//
// The three steps are deliberately separate, because they answer different
// questions:
// - Analysis describes and classifies the question. It is not knowledge yet.
// - Extraction produces the knowledge statements (units).
// - Concept decisions file those units under durable Concepts.

import type { AnalysisResolution } from "../types/learning";

export type Known<T> = { status: "loading" } | { status: "unknown" } | ({ status: "ready" } & T);

export type AnalysisFacts = Known<{
  // null when the record has no analysis.
  latest: { version: number; resolution: AnalysisResolution } | null;
}>;

// What ExtractionPanel read for this record. `current` is null when no
// extraction is current; `awaiting` lists the current units the backend still
// lists as awaiting Concept Review; `decided` holds, for every other current
// unit, its effective annotation status (or null while unread / unreadable).
export type ExtractionFacts = Known<{
  anyStored: boolean;
  current: { id: number; version: number; unitIds: number[] } | null;
  awaiting: number[] | null;
  decided: Record<number, "resolved" | "invalid" | "unresolved" | null>;
}>;

export type StepState = "done" | "pending" | "blocked" | "unknown";

export type NextAction =
  | { kind: "loading" }
  | { kind: "unknown" }
  | { kind: "analyze" }
  | { kind: "reanalyze"; version: number }
  | { kind: "reviewAnalysis"; version: number }
  | { kind: "extract" }
  | { kind: "selectExtraction" }
  | { kind: "zeroUnits"; version: number }
  | { kind: "reviewUnit"; unitId: number; extractionId: number; extractionVersion: number; awaiting: number; total: number }
  | { kind: "complete"; total: number; filed: number | null; invalid: number | null };

export interface RecordStage {
  analysis: { state: StepState; facts: AnalysisFacts };
  extraction: { state: StepState; facts: ExtractionFacts };
  decisions: {
    state: StepState;
    // Units of the current extraction and how many still await a decision.
    total: number | null;
    awaiting: number | null;
    filed: number | null;
    invalid: number | null;
  };
  next: NextAction;
  // The analysis is still unreviewed although later steps already ran; shown as
  // a reminder, never as a blocker (the server allows extraction from it).
  analysisReviewPending: boolean;
}

// deriveRecordStage combines the facts into the three steps and one next action.
export function deriveRecordStage(analysis: AnalysisFacts, extraction: ExtractionFacts): RecordStage {
  const latest = analysis.status === "ready" ? analysis.latest : undefined;
  const analysisState: StepState =
    analysis.status !== "ready"
      ? "unknown"
      : latest === null
        ? "pending"
        : latest!.resolution === "rejected"
          ? "blocked"
          : latest!.resolution === "unreviewed"
            ? "pending"
            : "done";

  const ex = extraction.status === "ready" ? extraction : null;
  const current = ex?.current ?? null;
  const extractionState: StepState = !ex ? "unknown" : current ? "done" : "pending";

  let total: number | null = null;
  let awaiting: number | null = null;
  let filed: number | null = null;
  let invalid: number | null = null;
  let decisionsState: StepState = "unknown";
  if (ex && current) {
    total = current.unitIds.length;
    if (ex.awaiting !== null) {
      const waiting = new Set(ex.awaiting);
      awaiting = current.unitIds.filter((id) => waiting.has(id)).length;
      const decided = current.unitIds.filter((id) => !waiting.has(id)).map((id) => ex.decided[id] ?? null);
      if (decided.every((s) => s !== null)) {
        filed = decided.filter((s) => s === "resolved").length;
        invalid = decided.filter((s) => s === "invalid").length;
      }
      decisionsState = awaiting > 0 ? "pending" : "done";
    } else if (total === 0) {
      awaiting = 0;
      decisionsState = "done";
    }
  } else if (ex && !current) {
    decisionsState = "pending";
  }

  const next = nextAction(analysis, latest, extraction, current, awaiting, total, filed, invalid);
  return {
    analysis: { state: analysisState, facts: analysis },
    extraction: { state: extractionState, facts: extraction },
    decisions: { state: decisionsState, total, awaiting, filed, invalid },
    next,
    analysisReviewPending: latest?.resolution === "unreviewed" && current !== null,
  };
}

function nextAction(
  analysis: AnalysisFacts,
  latest: { version: number; resolution: AnalysisResolution } | null | undefined,
  extraction: ExtractionFacts,
  current: { id: number; version: number; unitIds: number[] } | null,
  awaiting: number | null,
  total: number | null,
  filed: number | null,
  invalid: number | null,
): NextAction {
  if (analysis.status === "loading") return { kind: "loading" };
  if (analysis.status === "unknown") return { kind: "unknown" };
  if (latest === null) return { kind: "analyze" };
  if (latest!.resolution === "rejected") return { kind: "reanalyze", version: latest!.version };
  if (extraction.status === "loading") return { kind: "loading" };
  if (extraction.status === "unknown") return { kind: "unknown" };
  const ex = extraction;
  if (!current) {
    // Extraction from an unreviewed analysis is allowed, but reviewing first
    // means the knowledge statements are built from an interpretation you checked.
    if (latest!.resolution === "unreviewed") return { kind: "reviewAnalysis", version: latest!.version };
    return ex.anyStored ? { kind: "selectExtraction" } : { kind: "extract" };
  }
  if (current.unitIds.length === 0) return { kind: "zeroUnits", version: current.version };
  if (awaiting === null || total === null || ex.awaiting === null) return { kind: "unknown" };
  if (awaiting > 0) {
    const waiting = new Set(ex.awaiting);
    const first = current.unitIds.find((id) => waiting.has(id))!;
    return { kind: "reviewUnit", unitId: first, extractionId: current.id, extractionVersion: current.version, awaiting, total };
  }
  return { kind: "complete", total, filed, invalid };
}
