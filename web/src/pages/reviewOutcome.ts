import * as api from "../api/client";
import type { ConceptIdentity, RelationKind } from "../types/concept";
import { msg, type MessageRef } from "../i18n";

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

// The decision vocabulary (SAME, NEW CONCEPT, relation names, DISTINCT, INVALID)
// stays as written in every language; IDs and the drafted target are data.
export function describeDecision(d: Decision): MessageRef {
  switch (d.kind) {
    case "same":
      return msg(d.reassign ? "decision.label.reassign" : "decision.label.same", { id: d.conceptId });
    case "new":
      return msg(d.seedAsSame ? "decision.label.newSame" : "decision.label.new", { target: d.identity.target });
    case "relation":
      return msg("decision.label.relation", { relation: d.relation.toUpperCase(), id: d.conceptId });
    case "distinct":
      return msg("decision.label.distinct", { id: d.conceptId });
    case "invalid":
      return msg("decision.label.invalid");
  }
}

// What an accidental second submission would do, so the reviewer can decide
// whether to allow one while the first outcome is unknown.
export function duplicateRisk(d: Decision): MessageRef {
  switch (d.kind) {
    case "relation":
    case "distinct":
      return msg(d.operationId ? "decision.risk.keyed" : "decision.risk.append");
    case "new":
      return msg("decision.risk.new");
    case "same":
      return msg("decision.risk.same");
    case "invalid":
      return msg("decision.risk.invalid");
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

// sendDecision performs the write once and returns the confirmed success message.
export async function sendDecision(d: Decision): Promise<MessageRef> {
  switch (d.kind) {
    case "same":
      await (d.reassign ? api.reassignSame(d.unitId, d.conceptId) : api.resolveSame(d.unitId, d.conceptId));
      return msg("decision.sent.same", { id: d.conceptId });
    case "new": {
      const res = await api.createConcept(d.identity, d.unitId, d.seedAsSame);
      return msg(d.seedAsSame ? "decision.sent.newSame" : "decision.sent.new", { id: res.concept.id });
    }
    case "relation": {
      const result = await api.recordRelation(d.unitId, d.conceptId, d.relation, undefined, d.operationId);
      const relation = d.relation.toUpperCase();
      if (d.operationId) return msg("decision.sent.relationKeyed", { relation, event: result.id, id: d.conceptId });
      return msg("decision.sent.relation", { relation, id: d.conceptId });
    }
    case "distinct": {
      const result = await api.recordDistinction(d.unitId, d.conceptId, undefined, d.operationId);
      if (d.operationId) return msg("decision.sent.distinctKeyed", { event: result.id, id: d.conceptId });
      return msg("decision.sent.distinct", { id: d.conceptId });
    }
    case "invalid":
      await api.markUnitInvalid(d.unitId);
      return msg("decision.sent.invalid");
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

export type Evidence = { found: boolean; text: MessageRef };

// The stored receipt answers for a different operation than the one saved. The
// message is application text, shown translated (see ReviewQueue).
export class ReceiptMismatchError extends Error {
  constructor() {
    super("Receipt does not match the saved operation.");
  }
}

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
          (d.kind === "relation" && req.relation !== d.relation)) throw new ReceiptMismatchError();
      return { found: true, text: msg("check.receiptCommitted", { event: receipt.result.id }) };
    } catch (e) {
      if (e instanceof api.ApiError && e.status === 404) return { found: false, text: msg("check.receiptUnknown") };
      throw e;
    }
  }
  switch (d.kind) {
    case "same": {
      const m = (await api.getCurrentMembership(d.unitId)).current_membership;
      return m && m.concept_id === d.conceptId
        ? { found: true, text: msg("check.same.found", { id: m.concept_id, link: m.link_id }) }
        : { found: false, text: m ? msg("check.same.otherConcept", { id: m.concept_id, wanted: d.conceptId }) : msg("check.same.none") };
    }
    case "new": {
      if (!d.seedAsSame) {
        const match = (await api.listConcepts()).find((c) => sameIdentity(c, d.identity));
        return match
          ? { found: true, text: msg("check.new.exists", { id: match.id }) }
          : { found: false, text: msg("check.new.missing") };
      }
      const m = (await api.getCurrentMembership(d.unitId)).current_membership;
      if (!m) return { found: false, text: msg("check.same.none") };
      const concept = (await api.getConcept(m.concept_id)).concept;
      return sameIdentity(concept, d.identity)
        ? { found: true, text: msg("check.new.matches", { id: concept.id, target: concept.target }) }
        : { found: false, text: msg("check.new.differs", { id: concept.id, target: concept.target }) };
    }
    case "relation": {
      const links = (await api.getConcept(d.conceptId)).links;
      const stored = links.find(
        (l) => l.unit_id === d.unitId && l.relation === d.relation && l.id > (baseline?.newestEventId ?? 0),
      );
      return stored
        ? { found: true, text: msg("check.relation.found", { relation: d.relation.toUpperCase(), event: stored.id }) }
        : { found: false, text: msg("check.relation.missing", { relation: d.relation.toUpperCase() }) };
    }
    case "distinct": {
      const events = await api.listDistinctions(d.unitId);
      const stored = events.find((e) => e.concept_id === d.conceptId && e.id > (baseline?.newestEventId ?? 0));
      return stored
        ? { found: true, text: msg("check.distinct.found", { event: stored.id }) }
        : { found: false, text: msg("check.distinct.missing") };
    }
    case "invalid": {
      const env = await api.getUnitInvalid(d.unitId);
      const latest = env.history[0];
      return env.invalid
        ? { found: true, text: msg("check.invalid.found", { judgment: latest?.id ?? "?" }) }
        : { found: false, text: msg("check.invalid.missing") };
    }
  }
}
