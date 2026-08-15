// The single place all backend requests are constructed. Keeping request logic
// here (not in components) makes it unit-testable and keeps the endpoint contract
// in one file. All calls go through the "/api" prefix, which Vite proxies to the Go
// backend in development (see vite.config.ts).

import type {
  Concept,
  ConceptIdentity,
  ConceptView,
  MembershipEnvelope,
  RelationKind,
  ResolutionOutcome,
  ReviewableUnit,
  UnitConceptLink,
} from "../types/concept";

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
    init.body = JSON.stringify(body);
  }
  const res = await fetchImpl(`${BASE}${path}`, init);

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

// listReviewableUnits returns current-extraction units with no current SAME
// membership. Optionally scoped to one entry.
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

// ---- decision endpoints (the six human actions) ----

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

// rejectInvalid records the explicit human INVALID judgment: the candidate belongs
// to no concept. It clears any current SAME membership and preserves the rejection
// as immutable negative evidence. Idempotent (null link when already unresolved).
export function rejectInvalid(
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
