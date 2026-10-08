// The single place all backend requests are constructed. Keeping request logic
// here (not in components) makes it unit-testable and keeps the endpoint contract
// in one file. All calls go through the "/api" prefix, which Vite proxies to the Go
// backend in development (see vite.config.ts).

import type {
  Concept,
  ConceptIdentity,
  ConceptView,
  EffectiveAnnotationItem,
  MarkInvalidResponse,
  MembershipEnvelope,
  RelationKind,
  ResolutionOutcome,
  ReviewableUnit,
  UnitConceptLink,
  UnitDistinction,
  UnitInvalidEnvelope,
} from "../types/concept";
import type {
  AnnotationDatasetQualityReport,
  RetrievalComparisonReport,
} from "../types/experiment";
import type {
  Analysis,
  CaptureReceipt,
  CaptureResult,
  CurrentExtraction,
  EffectiveAnalysis,
  Entry,
  Extraction,
  Feedback,
  LearningRecordPage,
  NewFeedback,
  LearningRecordState,
} from "../types/learning";

// ApiError carries the HTTP status so callers can react specifically — most
// importantly to 409 Conflict, after which the UI must refresh the unit's current
// membership because another operation may have changed authority.
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
  get isConflict(): boolean {
    return this.status === 409;
  }
  get isNotFound(): boolean {
    return this.status === 404;
  }
}

// NetworkError means no HTTP response was received (connection refused, reset,
// or dropped). For a write request the outcome is therefore UNKNOWN: the server
// may or may not have stored it. Callers must say so instead of reporting a
// failure, and must never resubmit automatically.
export class NetworkError extends Error {
  readonly method: string;
  constructor(method: string) {
    super("no response from the server (network error)");
    this.name = "NetworkError";
    this.method = method;
  }
}

// RawJsonBody sends a JSON document exactly as the user supplied it, so the
// backend (not the browser) validates its content, unknown fields, and trailing
// data, exactly as for the capture CLI.
class RawJsonBody {
  constructor(readonly text: string) {}
}

// The base prefix. Overridable for tests; defaults to the proxied "/api".
const BASE = "/api";

// request performs a fetch and decodes JSON, translating non-2xx responses into a
// typed ApiError whose message prefers the backend's {"error": "..."} field.
async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  fetchImpl: typeof fetch = fetch,
): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body !== undefined) {
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
    init.body = body instanceof RawJsonBody ? body.text : JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetchImpl(`${BASE}${path}`, init);
  } catch {
    throw new NetworkError(method);
  }

  // 204 or empty body: return undefined as T.
  const text = await res.text();
  let parsed: unknown = undefined;
  if (text.length > 0) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }

  if (!res.ok) {
    const message =
      parsed && typeof parsed === "object" && "error" in parsed
        ? String((parsed as { error: unknown }).error)
        : `request failed with status ${res.status}`;
    throw new ApiError(res.status, message, parsed);
  }
  return parsed as T;
}

// ---- read endpoints ----

// LearningRecordQuery selects one page of the read-only learning inventory. The
// state filter and cursor are passed through unchanged; the backend validates
// them and owns the page-size bounds.
export interface LearningRecordQuery {
  state?: LearningRecordState;
  limit?: number;
  beforeEntryId?: number;
}

// listLearningRecords reads one page of GET /learning-records (newest first). The
// returned cursor is passed back as beforeEntryId to read the next, older page.
export async function listLearningRecords(
  query: LearningRecordQuery = {},
  fetchImpl: typeof fetch = fetch,
): Promise<LearningRecordPage> {
  const params = new URLSearchParams();
  if (query.state) params.set("state", query.state);
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.beforeEntryId !== undefined) params.set("before_entry_id", String(query.beforeEntryId));
  const q = params.toString();
  const data = await request<LearningRecordPage>(
    "GET",
    `/learning-records${q ? `?${q}` : ""}`,
    undefined,
    fetchImpl,
  );
  return { records: data.records ?? [], next_before_entry_id: data.next_before_entry_id ?? null };
}

// getEntry reads the learner-authored source record (original input and context).
export function getEntry(entryId: number, fetchImpl: typeof fetch = fetch): Promise<Entry> {
  return request<Entry>("GET", `/entries/${entryId}`, undefined, fetchImpl);
}

// listAnalyses reads every immutable analysis version for an entry, oldest first.
export async function listAnalyses(entryId: number, fetchImpl: typeof fetch = fetch): Promise<Analysis[]> {
  const data = await request<{ analyses: Analysis[] }>("GET", `/entries/${entryId}/analyses`, undefined, fetchImpl);
  return data.analyses ?? [];
}

// getEffectiveAnalysis reads the backend-resolved interpretation of one analysis
// (original values plus its latest feedback). The frontend never recomputes it.
export function getEffectiveAnalysis(analysisId: number, fetchImpl: typeof fetch = fetch): Promise<EffectiveAnalysis> {
  return request<EffectiveAnalysis>("GET", `/analyses/${analysisId}/effective`, undefined, fetchImpl);
}

// listReviewableUnits returns current-extraction units with no CURRENT SAME
// membership that are not effectively INVALID. Optionally scoped to one entry.
export async function listReviewableUnits(
  entryId?: number,
  fetchImpl: typeof fetch = fetch,
): Promise<ReviewableUnit[]> {
  const q = entryId ? `?entry_id=${entryId}` : "";
  const data = await request<{ reviewable_units: ReviewableUnit[] }>(
    "GET",
    `/reviewable-units${q}`,
    undefined,
    fetchImpl,
  );
  return data.reviewable_units ?? [];
}

// listConcepts reads the existing durable-concept catalog. The annotation UI uses
// it only for reviewer-visible discovery; this read creates no resolution evidence.
export async function listConcepts(fetchImpl: typeof fetch = fetch): Promise<Concept[]> {
  const data = await request<{ concepts: Concept[] }>("GET", "/concepts", undefined, fetchImpl);
  return data.concepts ?? [];
}

// listEffectiveAnnotations reads every unit from the current extraction(s) with
// its backend-derived M11-A effective annotation. Filtering stays client-side.
export async function listEffectiveAnnotations(
  fetchImpl: typeof fetch = fetch,
): Promise<EffectiveAnnotationItem[]> {
  const data = await request<{ effective_annotations: EffectiveAnnotationItem[] }>(
    "GET",
    "/effective-annotations",
    undefined,
    fetchImpl,
  );
  return data.effective_annotations ?? [];
}

// getAnnotationDatasetQuality reads the backend-owned M11-D structural quality
// report. The frontend does not infer validity or rebuild any of its counts.
export function getAnnotationDatasetQuality(
  fetchImpl: typeof fetch = fetch,
): Promise<AnnotationDatasetQualityReport> {
  return request<AnnotationDatasetQualityReport>(
    "GET",
    "/annotation-dataset/v1/quality",
    undefined,
    fetchImpl,
  );
}

// getRetrievalComparison reads the compact M13-A0 report in its backend-provided
// row order. The frontend does not select retrievers or calculate metrics.
export function getRetrievalComparison(
  fetchImpl: typeof fetch = fetch,
): Promise<RetrievalComparisonReport> {
  return request<RetrievalComparisonReport>(
    "GET",
    "/retrieval-comparison/v1",
    undefined,
    fetchImpl,
  );
}

// getEffectiveAnnotation reads one unit and its effective annotation projection.
// It is exposed for focused inspection without creating annotation authority.
export function getEffectiveAnnotation(
  unitId: number,
  fetchImpl: typeof fetch = fetch,
): Promise<EffectiveAnnotationItem> {
  return request<EffectiveAnnotationItem>(
    "GET",
    `/knowledge-units/${unitId}/effective-annotation`,
    undefined,
    fetchImpl,
  );
}

// resolveUnit runs the deterministic resolver for a unit (records nothing) so the
// UI can show any exact-signature candidate concept.
export function resolveUnit(unitId: number, fetchImpl: typeof fetch = fetch): Promise<ResolutionOutcome> {
  return request<ResolutionOutcome>("GET", `/knowledge-units/${unitId}/concept-resolution`, undefined, fetchImpl);
}

// getCurrentMembership reads the CURRENT SAME membership from the projection. This
// is the ONLY authority for current membership; never infer it from history.
export function getCurrentMembership(unitId: number, fetchImpl: typeof fetch = fetch): Promise<MembershipEnvelope> {
  return request<MembershipEnvelope>("GET", `/knowledge-units/${unitId}/concept-membership`, undefined, fetchImpl);
}

// getConcept returns a concept with its full append-only event history.
export function getConcept(conceptId: number, fetchImpl: typeof fetch = fetch): Promise<ConceptView> {
  return request<ConceptView>("GET", `/concepts/${conceptId}`, undefined, fetchImpl);
}

// ---- capture, analysis, and extraction workflow ----

// importCapture posts one learning_capture_v1 document unchanged to POST /captures.
// HTTP 201 (new) and 200 (identical replay) both resolve; `created` tells them
// apart. 400/409/422 reject with an ApiError carrying the backend message.
export function importCapture(rawJson: string, fetchImpl: typeof fetch = fetch): Promise<CaptureResult> {
  return request<CaptureResult>("POST", "/captures", new RawJsonBody(rawJson), fetchImpl);
}

// getCaptureReceipt reads a stored capture receipt; 404 means it is not stored.
export function getCaptureReceipt(captureId: string, fetchImpl: typeof fetch = fetch): Promise<CaptureReceipt> {
  return request<CaptureReceipt>("GET", `/captures/${encodeURIComponent(captureId)}`, undefined, fetchImpl);
}

// createAnalysis explicitly asks the server's configured analyzer for a new,
// immutable analysis version. Not idempotent: every success appends a version.
export function createAnalysis(entryId: number, fetchImpl: typeof fetch = fetch): Promise<Analysis> {
  return request<Analysis>("POST", `/entries/${entryId}/analysis`, undefined, fetchImpl);
}

// createExtraction explicitly asks the configured (possibly billed) extractor for
// a new extraction version. Not idempotent; eligibility is decided by the backend.
export function createExtraction(entryId: number, fetchImpl: typeof fetch = fetch): Promise<Extraction> {
  return request<Extraction>("POST", `/entries/${entryId}/extractions`, undefined, fetchImpl);
}

// listExtractions reads every stored extraction version for an entry.
export async function listExtractions(entryId: number, fetchImpl: typeof fetch = fetch): Promise<Extraction[]> {
  const data = await request<{ extractions: Extraction[] }>("GET", `/entries/${entryId}/extractions`, undefined, fetchImpl);
  return data.extractions ?? [];
}

// getCurrentExtraction reads which extraction the backend treats as current.
export function getCurrentExtraction(entryId: number, fetchImpl: typeof fetch = fetch): Promise<CurrentExtraction> {
  return request<CurrentExtraction>("GET", `/entries/${entryId}/current-extraction`, undefined, fetchImpl);
}

// listFeedback reads every immutable feedback record for one analysis, in the
// backend's order (oldest first). 404 means the analysis does not exist.
export async function listFeedback(analysisId: number, fetchImpl: typeof fetch = fetch): Promise<Feedback[]> {
  const data = await request<{ feedback: Feedback[] }>("GET", `/analyses/${analysisId}/feedback`, undefined, fetchImpl);
  return data.feedback ?? [];
}

// createFeedback appends one human judgment to an analysis. It never changes the
// analysis or the entry; the latest feedback decides the effective interpretation.
export function createFeedback(
  analysisId: number,
  feedback: NewFeedback,
  fetchImpl: typeof fetch = fetch,
): Promise<Feedback> {
  return request<Feedback>("POST", `/analyses/${analysisId}/feedback`, feedback, fetchImpl);
}

// setCurrentExtraction explicitly pins one stored extraction version as the
// entry's current extraction (PUT /entries/{id}/current-extraction). The 200 body
// is built from the request (selection_mode "pinned"), not read back; callers
// must re-read with getCurrentExtraction before presenting the stored state. 422
// means the version does not exist or belongs to another entry.
export function setCurrentExtraction(
  entryId: number,
  extractionId: number,
  fetchImpl: typeof fetch = fetch,
): Promise<CurrentExtraction> {
  return request<CurrentExtraction>(
    "PUT",
    `/entries/${entryId}/current-extraction`,
    { extraction_id: extractionId },
    fetchImpl,
  );
}

// clearCurrentExtraction removes an explicit selection (DELETE
// /entries/{id}/current-extraction) so the backend resumes automatic latest
// selection. It deletes no extraction, unit, or label and runs no extraction.
// Repeating it is harmless (200); callers still re-read to present stored state.
export function clearCurrentExtraction(entryId: number, fetchImpl: typeof fetch = fetch): Promise<CurrentExtraction> {
  return request<CurrentExtraction>("DELETE", `/entries/${entryId}/current-extraction`, undefined, fetchImpl);
}

// getLearningRecord re-reads one inventory row through the existing cursor: the
// inventory is ordered by entry_id descending and before_entry_id is exclusive,
// so the first row before entryId + 1 is that entry. Returns null if absent.
export async function getLearningRecord(entryId: number, fetchImpl: typeof fetch = fetch) {
  const page = await listLearningRecords({ limit: 1, beforeEntryId: entryId + 1 }, fetchImpl);
  const record = page.records[0];
  return record && record.entry_id === entryId ? record : null;
}

// ---- decision endpoints (the seven explicit human actions) ----

// resolveSame records an explicit human SAME for a unit that has NO current SAME
// membership. A 409 means it already has one — the caller should reassign instead.
export function resolveSame(unitId: number, conceptId: number, fetchImpl: typeof fetch = fetch): Promise<UnitConceptLink> {
  return request<UnitConceptLink>(
    "POST",
    `/knowledge-units/${unitId}/concept-links/same`,
    { concept_id: conceptId },
    fetchImpl,
  );
}

// reassignSame is the explicit human correction that MOVES an existing current SAME
// membership to a different concept. Used instead of create+seed whenever the unit
// already has a membership.
export function reassignSame(unitId: number, conceptId: number, fetchImpl: typeof fetch = fetch): Promise<UnitConceptLink> {
  return request<UnitConceptLink>(
    "PUT",
    `/knowledge-units/${unitId}/concept-membership`,
    { concept_id: conceptId },
    fetchImpl,
  );
}

// createConcept creates a new durable concept from a reviewed identity, atomically
// seeding SAME for an unresolved unit when seedUnitId is given with linkSeedAsSame.
// This ESTABLISHES membership only for an unresolved unit; it never reassigns.
export function createConcept(
  identity: ConceptIdentity,
  seedUnitId: number | null,
  linkSeedAsSame: boolean,
  fetchImpl: typeof fetch = fetch,
): Promise<{ concept: Concept; link: UnitConceptLink | null }> {
  return request<{ concept: Concept; link: UnitConceptLink | null }>(
    "POST",
    `/concepts`,
    { identity, seed_unit_id: seedUnitId, link_seed_as_same: linkSeedAsSame },
    fetchImpl,
  );
}

// recordRelation records a non-membership BROADER/NARROWER/RELATED decision. It does
// NOT make the unit a SAME member of the concept.
export function recordRelation(
  unitId: number,
  conceptId: number,
  relation: RelationKind,
  fetchImpl: typeof fetch = fetch,
): Promise<UnitConceptLink> {
  return request<UnitConceptLink>(
    "POST",
    `/knowledge-units/${unitId}/concept-links/relation`,
    { concept_id: conceptId, relation },
    fetchImpl,
  );
}

// rejectSameMembership records a membership-LEVEL correction: it clears the unit's
// CURRENT SAME membership and preserves the rejection as immutable negative evidence.
// It is a no-op (null link) when the unit is already unresolved, so it cannot express
// "this candidate is invalid" for a never-resolved unit — that is markUnitInvalid.
// Kept available as an explicit membership-clear action, distinct from INVALID.
export function rejectSameMembership(
  unitId: number,
  fetchImpl: typeof fetch = fetch,
): Promise<{ unit_id: number; current_membership: null; link: UnitConceptLink | null }> {
  return request<{ unit_id: number; current_membership: null; link: UnitConceptLink | null }>(
    "POST",
    `/knowledge-units/${unitId}/concept-membership/reject`,
    undefined,
    fetchImpl,
  );
}

// markUnitInvalid records the unit-LEVEL INVALID judgment: the KnowledgeUnit itself is
// an invalid candidate for concept resolution. Unlike rejectSameMembership it works
// for a freshly extracted, never-resolved unit (no membership required), and it also
// atomically clears any current SAME membership so the unit is never both SAME and
// invalid. This is the primary INVALID action. Reversible via restoreUnit.
export function markUnitInvalid(unitId: number, fetchImpl: typeof fetch = fetch): Promise<MarkInvalidResponse> {
  return request<MarkInvalidResponse>("POST", `/knowledge-units/${unitId}/invalid`, undefined, fetchImpl);
}

// restoreUnit withdraws a prior INVALID judgment, returning the unit to the review
// queue. It never deletes the historical judgment and never recreates a cleared SAME
// membership. Idempotent (null judgment) when the unit is not currently invalid.
export function restoreUnit(unitId: number, fetchImpl: typeof fetch = fetch): Promise<MarkInvalidResponse> {
  return request<MarkInvalidResponse>("POST", `/knowledge-units/${unitId}/invalid/restore`, undefined, fetchImpl);
}

// getUnitInvalid reads the effective invalid state plus the full append-only judgment
// history for a unit.
export function getUnitInvalid(unitId: number, fetchImpl: typeof fetch = fetch): Promise<UnitInvalidEnvelope> {
  return request<UnitInvalidEnvelope>("GET", `/knowledge-units/${unitId}/invalid`, undefined, fetchImpl);
}

// recordDistinction records an explicit DISTINCT negative pair: the unit is NOT the
// same learning identity as the concept. It creates no membership and no relation and
// never changes SAME membership, so the unit stays reviewable and the reviewer can
// then pick another concept, create a NEW one, or mark the unit INVALID.
export function recordDistinction(
  unitId: number,
  conceptId: number,
  fetchImpl: typeof fetch = fetch,
): Promise<UnitDistinction> {
  return request<UnitDistinction>(
    "POST",
    `/knowledge-units/${unitId}/concept-distinctions`,
    { concept_id: conceptId },
    fetchImpl,
  );
}
