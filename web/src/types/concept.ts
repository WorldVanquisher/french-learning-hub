// Wire types mirroring the Go transport DTOs (internal/transport/http/concept.go).
// These are the exact JSON shapes the backend returns; keep them in sync with the
// Go structs. Nothing here infers current membership from history — see MembershipEnvelope.

// A concept's identity under the explicit versioned schema.
export interface ConceptIdentity {
  target: string;
  pedagogical_intent: string;
  scope: string;
  identity_features: Record<string, string>;
}

// One durable concept. `state` is the effective derived state; `lifecycle_state`
// and `support_state` make the derivation explicit for the review UI.
export interface Concept {
  id: number;
  identity_schema_version: string;
  target: string;
  pedagogical_intent: string;
  scope: string;
  identity_features: Record<string, string>;
  signature: string;
  preferred_unit_id: number | null;
  state: "active" | "orphaned" | "retired";
  lifecycle_state: "normal" | "retired";
  support_state: "supported" | "orphaned";
  created_at: string;
  updated_at: string;
}

// One immutable append-only resolution event. `relation="same"`+`status="rejected"`
// is the INVALID judgment; `supersedes_link_id` is the correction back-pointer.
export interface UnitConceptLink {
  id: number;
  unit_id: number;
  concept_id: number;
  relation: "same" | "broader" | "narrower" | "related";
  status: "accepted" | "superseded" | "rejected";
  decision_source: string;
  resolver_version: string;
  score: number | null;
  evidence: string;
  supersedes_link_id: number | null;
  created_at: string;
}

// A concept plus its FULL append-only event history (newest first).
export interface ConceptView {
  concept: Concept;
  links: UnitConceptLink[];
}

// One current-extraction unit awaiting SAME resolution, with its derived default
// candidate identity to seed the identity editor.
export interface ReviewableUnit {
  unit_id: number;
  kind: string;
  canonical: string;
  statement: string;
  example: string | null;
  confidence: number;
  candidate_identity: ConceptIdentity;
  signature: string;
}

// The deterministic resolver's read-only decision for a unit and the concepts that
// share its exact signature. Records nothing.
export interface ResolutionOutcome {
  unit_id: number;
  candidate_identity: ConceptIdentity;
  signature: string;
  decision: "matched" | "no_match" | "ambiguous";
  matches: Concept[];
}

// The CURRENT SAME membership read model. `current_membership` is null when the
// unit belongs to no concept. This is the ONLY authority for current membership;
// never infer it from UnitConceptLink history.
export interface CurrentMembership {
  concept_id: number;
  link_id: number;
  updated_at: string;
}

export interface MembershipEnvelope {
  unit_id: number;
  current_membership: CurrentMembership | null;
}

// The concept-relations the reviewer can assert as non-membership decisions.
export type RelationKind = "broader" | "narrower" | "related";
