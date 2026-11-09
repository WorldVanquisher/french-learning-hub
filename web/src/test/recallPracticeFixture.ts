// Recall practice v1: an authored, synthetic French-learning fixture shaped like
// the real Knowledge Library responses (typed against the wire types, so drift
// fails the typecheck). It is test data only: nothing here is a real learner's
// record, and it is never served by the backend.
//
// Concept #21 "the pronoun en" is currently supported by two units that come
// from two different original questions (records #31 and #32). Around them sit
// the evidence practice must never offer:
// - unit #204: record #31's unit from an older extraction (filed, not supporting);
// - unit #205: first filed here, then reassigned to Concept #22 "the pronoun y"
//   (history, now someone else's support);
// - unit #206: a RELATED relation (not membership, no support);
// - Concept #22 itself, unrelated to the questions being practised.
import type { Concept } from "../types/concept";
import type { LibraryConcept, LibrarySource, LibraryUnit } from "../types/library";

export const PRACTICE_CONCEPT_ID = 21;
export const OTHER_CONCEPT_ID = 22;

const concept = (id: number, target: string, features: Record<string, string>): Concept => ({
  id,
  identity_schema_version: "fr_l2_concept_identity_v1",
  target,
  pedagogical_intent: "grammar",
  scope: "",
  identity_features: features,
  signature: "{}",
  preferred_unit_id: null,
  state: "active",
  lifecycle_state: "normal",
  support_state: "supported",
  created_at: "2026-11-01T09:00:00Z",
  updated_at: "2026-11-01T09:00:00Z",
});

export const conceptEn = concept(PRACTICE_CONCEPT_ID, "pronom « en » : remplacer une quantité ou un partitif", { pronoun: "en" });
export const conceptY = concept(OTHER_CONCEPT_ID, "pronom « y » : remplacer à + lieu", { pronoun: "y" });

const unit = (u: Partial<LibraryUnit> & Pick<LibraryUnit, "unit_id" | "entry_id" | "canonical" | "statement">): LibraryUnit => ({
  kind: "grammar",
  statements: { en: u.statement, zh: null },
  example: null,
  extraction_id: u.unit_id * 10,
  extraction_version: 2,
  in_current_extraction: true,
  admission: "active",
  ...u,
});

// The two supporting units: the answers that stay hidden until revealed.
export const unitQuantity = unit({
  unit_id: 201,
  entry_id: 31,
  canonical: "en + quantité",
  statement: "« en » replaces a noun introduced by a number or a quantity; the number stays after the verb.",
  statements: {
    en: "« en » replaces a noun introduced by a number or a quantity; the number stays after the verb.",
    zh: "「en」代替由数字或数量词引出的名词，数字保留在动词后面。",
  },
  example: "Des pommes ? J'en ai deux.",
});
export const unitPartitive = unit({
  unit_id: 202,
  entry_id: 32,
  canonical: "en + partitif",
  statement: "« en » replaces du / de la / des + noun, so « du café » becomes « en ».",
  statements: {
    en: "« en » replaces du / de la / des + noun, so « du café » becomes « en ».",
    zh: "「en」代替 du / de la / des + 名词，所以 « du café » 变成 « en »。",
  },
  example: "Tu veux du pain ? Oui, j'en veux bien.",
});
// Evidence that must never be offered as a question.
export const unitOldExtraction = unit({
  unit_id: 204,
  entry_id: 31,
  canonical: "en (ancienne extraction)",
  statement: "OLD-EXTRACTION statement: « en » means “of it”.",
  extraction_version: 1,
  in_current_extraction: false,
});
export const unitReassigned = unit({
  unit_id: 205,
  entry_id: 34,
  canonical: "y + lieu",
  statement: "REASSIGNED statement: « y » replaces à + a place.",
  example: "Tu vas à Paris ? Oui, j'y vais.",
});
export const unitRelated = unit({
  unit_id: 206,
  entry_id: 35,
  canonical: "en + pays",
  statement: "RELATED statement: the preposition « en » before a feminine country.",
});

export const questions: Record<number, { input: string; context: string }> = {
  31: {
    input: "Pourquoi dit-on « J'en ai deux » et pas « J'ai deux » quand on parle de pommes ?",
    // The context gives the answer away; practice must keep it hidden.
    context: "Au marché. Mon professeur a dit plus tard que « en » remplace « de pommes ».",
  },
  32: {
    input: "Dans « Tu veux du café ? — Oui, j'en veux », que remplace « en » ?",
    context: "Petit-déjeuner dans ma famille d'accueil.",
  },
  34: { input: "Je vais à Paris demain : « J'y vais » ou « J'en vais » ?", context: "Message à une amie." },
  35: { input: "On dit « en France » mais « au Canada » : pourquoi ?", context: "Cours de géographie." },
};

export const conceptEnDetail: LibraryConcept = {
  schema_version: "knowledge_library_concept_v1",
  concept: conceptEn,
  preferred_unit: null,
  supporting_units: [unitQuantity, unitPartitive],
  non_supporting_members: [unitOldExtraction],
  current_relations: [{ relation: "related", link_id: 61, decision_source: "human", decided_at: "2026-11-02T10:00:00Z", unit: unitRelated }],
  historical_units: [
    {
      unit: unitReassigned,
      latest_event: {
        id: 71, unit_id: 205, concept_id: OTHER_CONCEPT_ID, relation: "same", status: "accepted", decision_source: "human",
        resolver_version: "", score: null, evidence: "", supersedes_link_id: 70, created_at: "2026-11-03T08:00:00Z",
      },
      effective_status: "resolved",
      current_concept_id: OTHER_CONCEPT_ID,
    },
  ],
  history_event_count: 5,
};

export const conceptYDetail: LibraryConcept = {
  schema_version: "knowledge_library_concept_v1",
  concept: conceptY,
  preferred_unit: null,
  supporting_units: [unitReassigned],
  non_supporting_members: [],
  current_relations: [],
  historical_units: [],
  history_event_count: 2,
};

// source builds GET /knowledge-library/units/{id}/source for one unit.
export function source(u: LibraryUnit, currentConceptId: number | null, status: "resolved" | "invalid" = "resolved"): LibrarySource {
  const q = questions[u.entry_id] ?? { input: "", context: "" };
  return {
    schema_version: "knowledge_library_source_v1",
    unit: u,
    entry: { id: u.entry_id, original_input: q.input, original_context: q.context, created_at: "2026-10-30T18:00:00Z", updated_at: "2026-10-30T18:00:00Z" },
    extraction: { id: u.extraction_id, version: u.extraction_version, extractor: "openai:fixture:knowledge_extraction_v2", source_analysis_id: u.entry_id * 10, source_feedback_id: null, created_at: "2026-10-31T08:00:00Z" },
    current_extraction: { extraction_id: u.extraction_id, selection_mode: "automatic" },
    source_interpretation: {
      analysis: { id: u.entry_id * 10, entry_id: u.entry_id, version: 1, category: "grammar", explanation: "Stored analysis.", confidence: 0.9, uncertainty: "", analyzer: "openai:fixture:fr_l2_taxonomy_v1", created_at: "2026-10-30T18:01:00Z" },
      feedback: null,
      effective: { analysis_id: u.entry_id * 10, entry_id: u.entry_id, version: 1, original: { category: "grammar", explanation: "Stored analysis." }, effective: { category: "grammar", explanation: "Stored analysis." }, resolution: "unreviewed", feedback_id: null },
    },
    latest_analysis: { id: u.entry_id * 10, version: 1, created_at: "2026-10-30T18:01:00Z" },
    annotation: { status, current_concept_id: currentConceptId },
  };
}

// The responses a backend holding this fixture would give, by /api path.
export function fixtureResponses(): Record<string, unknown> {
  return {
    "/api/knowledge-library/concepts": {
      schema_version: "knowledge_library_search_v1", query: "", tokens: [], state: "all", limit: 20, total_matches: 2, truncated: false,
      results: [
        { concept: conceptEn, match_tier: "browse", matched_fields: [], current_member_count: 3, supporting_unit_count: 2 },
        { concept: conceptY, match_tier: "browse", matched_fields: [], current_member_count: 1, supporting_unit_count: 1 },
      ],
    },
    [`/api/knowledge-library/concepts/${PRACTICE_CONCEPT_ID}`]: conceptEnDetail,
    [`/api/knowledge-library/concepts/${OTHER_CONCEPT_ID}`]: conceptYDetail,
    "/api/knowledge-library/units/201/source": source(unitQuantity, PRACTICE_CONCEPT_ID),
    "/api/knowledge-library/units/202/source": source(unitPartitive, PRACTICE_CONCEPT_ID),
    "/api/knowledge-library/units/204/source": source(unitOldExtraction, PRACTICE_CONCEPT_ID),
    "/api/knowledge-library/units/205/source": source(unitReassigned, OTHER_CONCEPT_ID),
    "/api/knowledge-library/units/206/source": source(unitRelated, null),
  };
}
