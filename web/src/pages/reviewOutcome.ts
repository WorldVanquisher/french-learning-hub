import * as api from "../api/client";
import type { ConceptIdentity, RelationKind } from "../types/concept";

// One explicit Concept Review decision, with everything needed to send it once
// and, if its outcome is unknown, to check the backend for its effect later.
export type Decision = (
  | { kind: "same"; unitId: number; conceptId: number; reassign: boolean }
  | { kind: "new"; unitId: number; identity: ConceptIdentity; seedAsSame: boolean }
  | { kind: "relation"; unitId: number; conceptId: number; relation: RelationKind }
  | { kind: "distinct"; unitId: number; conceptId: number }
  | { kind: "invalid"; unitId: number }) & { operationId?: string };

// Decisions that, once stored, take the unit out of the review queue.
export const resolvesUnit = (d: Decision) =>
  d.kind === "same" || d.kind === "invalid" || (d.kind === "new" && d.seedAsSame);

export function describeDecision(d: Decision): string {
  switch (d.kind) {
    case "same":
      return `${d.reassign ? "REASSIGN SAME" : "SAME"} → concept #${d.conceptId}`;
    case "new":
      return `NEW CONCEPT "${d.identity.target}"${d.seedAsSame ? " with SAME" : ""}`;
    case "relation":
      return `${d.relation.toUpperCase()} → concept #${d.conceptId}`;
    case "distinct":
      return `DISTINCT from concept #${d.conceptId}`;
    case "invalid":
      return "INVALID";
  }
}

// What an accidental second submission would do, so the reviewer can decide
// whether to allow one while the first outcome is unknown.
export function duplicateRisk(d: Decision): string {
  switch (d.kind) {
    case "relation":
    case "distinct":
      return d.operationId ? "Retry uses the saved key and payload; the server appends at most once. An unknown receipt does not mean canceled." : "Each submission of this decision appends a new event, so sending it again after the first was stored records it twice.";
    case "new":
      return "If the first request created the concept, the server refuses an identical second one, but the unit may already belong to it.";
    case "same":
      return "If the first request was stored, the unit already belongs to that concept; the server refuses or repeats the same membership.";
    case "invalid":
      return "If the first request was stored, the unit is already INVALID; the server does not record it twice.";
  }
}

// The newest event ID of the decision's own kind before it was sent. Only an
// event newer than this proves that an append-only write was stored.
export type Baseline = { newestEventId: number } | null;

const newest = (ids: number[]) => ids.reduce((max, id) => Math.max(max, id), 0);

export async function readBaseline(d: Decision): Promise<Baseline> {
  if (d.operationId) return null;
  if (d.kind === "relation") {
    const view = await api.getConcept(d.conceptId);
    return {
      newestEventId: newest(view.links.filter((l) => l.unit_id === d.unitId && l.relation === d.relation).map((l) => l.id)),
    };
  }
  if (d.kind === "distinct") {
    const events = await api.listDistinctions(d.unitId);
    return { newestEventId: newest(events.filter((e) => e.concept_id === d.conceptId).map((e) => e.id)) };
  }
  // SAME, NEW CONCEPT with SAME, and INVALID are checked against current authority,
  // which the unit did not yet have while it was awaiting review.
  return null;
}

// sendDecision performs the write once and returns the confirmed success text.
export async function sendDecision(d: Decision): Promise<string> {
  switch (d.kind) {
    case "same":
      await (d.reassign ? api.reassignSame(d.unitId, d.conceptId) : api.resolveSame(d.unitId, d.conceptId));
      return `Recorded SAME → concept #${d.conceptId}.`;
    case "new": {
      const res = await api.createConcept(d.identity, d.unitId, d.seedAsSame);
      return d.seedAsSame
        ? `Created concept #${res.concept.id} and seeded SAME.`
        : `Created concept #${res.concept.id} (membership unchanged; use REASSIGN to move it).`;
    }
    case "relation": {
      const result = await api.recordRelation(d.unitId, d.conceptId, d.relation, undefined, d.operationId);
      if (d.operationId) return `Recorded ${d.relation.toUpperCase()} event #${result.id} for concept #${d.conceptId} (historical request result; current authority refreshed separately).`;
      return `Recorded ${d.relation.toUpperCase()} → concept #${d.conceptId}.`;
    }
    case "distinct": {
      const result = await api.recordDistinction(d.unitId, d.conceptId, undefined, d.operationId);
      if (d.operationId) return `Recorded DISTINCT event #${result.id} for concept #${d.conceptId} (historical request result; current authority refreshed separately).`;
      return `Recorded DISTINCT: unit is NOT concept #${d.conceptId}. Pick another concept, create a NEW one, or mark INVALID.`;
    }
    case "invalid":
      await api.markUnitInvalid(d.unitId);
      return "Marked the unit INVALID: removed from the review queue.";
  }
}

// Identity comparison mirrors the server's documented normalization for display
// purposes only (lowercase, collapsed whitespace); it never decides identity.
const norm = (v: string) => v.trim().replace(/\s+/g, " ").toLowerCase();
function sameIdentity(a: ConceptIdentity, b: ConceptIdentity): boolean {
  const features = (f: Record<string, string>) =>
    JSON.stringify(Object.entries(f ?? {}).map(([k, v]) => [norm(k), norm(v)]).sort());
  return (
    norm(a.target) === norm(b.target) &&
    norm(a.pedagogical_intent) === norm(b.pedagogical_intent) &&
    norm(a.scope) === norm(b.scope) &&
    features(a.identity_features) === features(b.identity_features)
  );
}

export type Evidence = { found: boolean; text: string };

// checkDecision reads the backend authority or history the decision would have
// changed. `found: true` means the stored state shows the decision's effect.
// `found: false` never proves the request failed: it may still be in progress on
// the server, or something else may have changed the unit.
export async function checkDecision(d: Decision, baseline: Baseline): Promise<Evidence> {
  if (d.operationId) {
    try {
      const receipt = await api.getAnnotationOperation(d.operationId);
      const req = receipt.request;
      if (receipt.id !== d.operationId || req.action !== d.kind || req.unit_id !== d.unitId ||
          !("conceptId" in d) || req.concept_id !== d.conceptId ||
          (d.kind === "relation" && req.relation !== d.relation)) throw new Error("Receipt does not match the saved operation.");
      return { found: true, text: `This request committed event #${receipt.result.id}. This historical result is separate from current authority.` };
    } catch (e) {
      if (e instanceof api.ApiError && e.status === 404) return { found: false, text: "Receipt unknown. The original request may still commit; retry only with its saved key and payload." };
      throw e;
    }
  }
  switch (d.kind) {
    case "same": {
      const m = (await api.getCurrentMembership(d.unitId)).current_membership;
      return m && m.concept_id === d.conceptId
        ? { found: true, text: `The unit's current SAME membership is concept #${m.concept_id} (link #${m.link_id}).` }
        : { found: false, text: m ? `The unit's current SAME membership is concept #${m.concept_id}, not #${d.conceptId}.` : "The unit has no current SAME membership." };
    }
    case "new": {
      if (!d.seedAsSame) {
        const match = (await api.listConcepts()).find((c) => sameIdentity(c, d.identity));
        return match
          ? { found: true, text: `Concept #${match.id} with this identity exists.` }
          : { found: false, text: "No concept with this identity exists." };
      }
      const m = (await api.getCurrentMembership(d.unitId)).current_membership;
      if (!m) return { found: false, text: "The unit has no current SAME membership." };
      const concept = (await api.getConcept(m.concept_id)).concept;
      return sameIdentity(concept, d.identity)
        ? { found: true, text: `The unit now belongs to concept #${concept.id} ("${concept.target}"), matching the drafted identity.` }
        : { found: false, text: `The unit now belongs to concept #${concept.id} ("${concept.target}"), whose identity differs from the draft.` };
    }
    case "relation": {
      const links = (await api.getConcept(d.conceptId)).links;
      const stored = links.find(
        (l) => l.unit_id === d.unitId && l.relation === d.relation && l.id > (baseline?.newestEventId ?? 0),
      );
      return stored
        ? { found: true, text: `A new ${d.relation.toUpperCase()} event #${stored.id} for this unit is stored.` }
        : { found: false, text: `No ${d.relation.toUpperCase()} event newer than the one before sending is stored.` };
    }
    case "distinct": {
      const events = await api.listDistinctions(d.unitId);
      const stored = events.find((e) => e.concept_id === d.conceptId && e.id > (baseline?.newestEventId ?? 0));
      return stored
        ? { found: true, text: `A new DISTINCT event #${stored.id} is stored.` }
        : { found: false, text: "No DISTINCT event newer than the one before sending is stored." };
    }
    case "invalid": {
      const env = await api.getUnitInvalid(d.unitId);
      const latest = env.history[0];
      return env.invalid
        ? { found: true, text: `The unit is INVALID (judgment #${latest?.id ?? "?"}).` }
        : { found: false, text: "The unit is not INVALID." };
    }
  }
}
