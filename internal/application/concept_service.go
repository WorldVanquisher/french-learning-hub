package application

import (
	"context"
	"encoding/json"
	"fmt"

	"french-learning-app/internal/domain"
)

// ConceptService coordinates knowledge-concept resolution: turning immutable
// KnowledgeUnit evidence into durable KnowledgeConcept learning identities. It
// runs the deterministic v1 resolver, records append-only resolution decisions,
// manages preferred representation separately from membership, and exposes the
// per-entry current-extraction selection. It never deletes or rewrites units or
// historical links, and it uses no ML: resolution is exact-signature matching
// only.
type ConceptService struct {
	units    domain.KnowledgeExtractionRepository
	concepts domain.ConceptRepository
	current  domain.CurrentExtractionRepository
}

// NewConceptService wires the service to its repositories. The units repository
// is used read-only, to load a unit before resolving it.
func NewConceptService(
	units domain.KnowledgeExtractionRepository,
	concepts domain.ConceptRepository,
	current domain.CurrentExtractionRepository,
) *ConceptService {
	return &ConceptService{units: units, concepts: concepts, current: current}
}

// ResolutionOutcome is the result of running the deterministic resolver over one
// unit's candidate identity. It reports the candidate identity, the resolver's
// deterministic decision kind, and any active concepts that share the exact
// signature (zero, one, or — only in the ambiguous case — more).
type ResolutionOutcome struct {
	UnitID    int64
	Candidate domain.ConceptIdentity
	Kind      domain.ResolutionKind
	Matches   []domain.KnowledgeConcept
}

// ResolveCandidate runs the deterministic resolver for a unit without recording
// any decision. It derives the unit's default v1 identity, looks up active
// concepts with the identical normalized signature, and reports the resolver's
// decision. It is read-only and never force-merges.
func (s *ConceptService) ResolveCandidate(ctx context.Context, unitID int64) (*ResolutionOutcome, error) {
	unit, err := s.concepts.UnitByID(ctx, unitID)
	if err != nil {
		return nil, err // includes domain.ErrNotFound
	}
	candidate := domain.DeriveCandidateIdentity(*unit)
	return s.resolveIdentity(ctx, unitID, candidate)
}

// resolveIdentity is the shared resolver core for a known candidate identity.
func (s *ConceptService) resolveIdentity(ctx context.Context, unitID int64, candidate domain.ConceptIdentity) (*ResolutionOutcome, error) {
	if err := candidate.Validate(); err != nil {
		return nil, err
	}
	matches, err := s.concepts.FindActiveBySignature(ctx, candidate.Signature())
	if err != nil {
		return nil, err
	}
	kind := domain.ResolveConcept(candidate, matches)
	return &ResolutionOutcome{UnitID: unitID, Candidate: candidate, Kind: kind, Matches: matches}, nil
}

// AutoResolve runs the resolver for a unit and, only when the decision is an
// unambiguous single match, records an automatic accepted SAME link to that
// concept. For no-match or ambiguous outcomes it records nothing and returns the
// outcome so the caller can route the unit to human review. This is the only
// place an automatic SAME is created, and only on an exact complete-signature
// match with no conflict.
func (s *ConceptService) AutoResolve(ctx context.Context, unitID int64) (*ResolutionOutcome, *domain.UnitConceptLink, error) {
	outcome, err := s.ResolveCandidate(ctx, unitID)
	if err != nil {
		return nil, nil, err
	}
	if outcome.Kind != domain.ResolutionMatched {
		return outcome, nil, nil
	}
	score := 1.0
	evidence := mustEvidence(map[string]any{
		"reason":          "exact_signature_match",
		"signature":       outcome.Candidate.Signature(),
		"resolver":        domain.ConceptResolverVersion,
		"identity_schema": domain.ConceptIdentitySchemaVersion,
	})
	link, err := s.concepts.LinkSame(ctx, unitID, outcome.Matches[0].ID, domain.SourceResolverAutomatic, &score, evidence)
	if err != nil {
		return outcome, nil, err
	}
	return outcome, link, nil
}

// ResolveSame records an explicit human accepted SAME membership from a unit to an
// existing concept when the unit has NO current SAME membership. It enforces the
// at-most-one-current-SAME invariant in the repository. Returns
// domain.ErrConceptConflict when the unit already has a current SAME to a different
// concept — the caller should use ReassignSame to correct an existing membership.
func (s *ConceptService) ResolveSame(ctx context.Context, unitID, conceptID int64) (*domain.UnitConceptLink, error) {
	evidence := mustEvidence(map[string]any{"reason": "human_same", "resolver": domain.ConceptResolverVersion})
	return s.concepts.LinkSame(ctx, unitID, conceptID, domain.SourceHuman, nil, evidence)
}

// ReassignSame moves a unit's CURRENT SAME membership to a different concept as an
// explicit human correction, even when the unit already belongs SAME to another
// concept. The prior decision is preserved as immutable history; the new decision
// supersedes it and becomes current. This is the human-final-authority operation:
// it may override an automatic or a previous human SAME. It is idempotent when the
// unit already belongs to the target concept.
func (s *ConceptService) ReassignSame(ctx context.Context, unitID, conceptID int64) (*domain.UnitConceptLink, error) {
	evidence := mustEvidence(map[string]any{"reason": "human_same_correction", "resolver": domain.ConceptResolverVersion})
	return s.concepts.ReassignSame(ctx, unitID, conceptID, domain.SourceHuman, evidence)
}

// RejectSame records an explicit human INVALID judgment for a unit: its candidate
// does not belong to any concept. It clears the unit's current SAME membership
// while preserving the judgment as immutable negative evidence (an append-only
// rejection event referencing the superseded SAME). It never deletes history and
// never invents a membership relation. When the unit already has no current SAME
// membership the postcondition holds and the call is an idempotent no-op returning
// (nil, nil). Returns domain.ErrNotFound if the unit does not exist.
func (s *ConceptService) RejectSame(ctx context.Context, unitID int64) (*domain.UnitConceptLink, error) {
	evidence := mustEvidence(map[string]any{"reason": "human_invalid", "resolver": domain.ConceptResolverVersion})
	return s.concepts.RejectSame(ctx, unitID, domain.SourceHuman, evidence)
}

// MarkUnitInvalid records an explicit unit-level INVALID judgment: the candidate
// KnowledgeUnit should not participate in concept resolution. Unlike RejectSame
// (a membership-level correction that only clears an existing SAME), this is
// recordable even for a freshly extracted unit that never had a SAME membership —
// so a human can reject garbage extraction candidates. To keep product state
// internally consistent it also clears any current SAME membership atomically (a
// unit is never both SAME to a concept and invalid). The judgment is append-only
// and reversible via RestoreUnit; marking an already-invalid unit is idempotent.
// Returns domain.ErrNotFound if the unit does not exist.
func (s *ConceptService) MarkUnitInvalid(ctx context.Context, unitID int64) (*domain.UnitResolutionJudgment, error) {
	evidence := mustEvidence(map[string]any{"reason": "human_unit_invalid", "resolver": domain.ConceptResolverVersion})
	return s.concepts.MarkUnitInvalid(ctx, unitID, domain.SourceHuman, "", evidence)
}

// RestoreUnit withdraws a prior INVALID judgment, returning the unit to the review
// queue without deleting the historical judgment. It does not recreate any SAME
// membership a prior MarkUnitInvalid cleared: the unit simply becomes unresolved
// and reviewable again. Restoring a unit that is not currently invalid is an
// idempotent no-op returning (nil, nil). Returns domain.ErrNotFound if the unit
// does not exist.
func (s *ConceptService) RestoreUnit(ctx context.Context, unitID int64) (*domain.UnitResolutionJudgment, error) {
	evidence := mustEvidence(map[string]any{"reason": "human_unit_restored", "resolver": domain.ConceptResolverVersion})
	return s.concepts.RestoreUnit(ctx, unitID, domain.SourceHuman, "", evidence)
}

// LatestUnitJudgment returns the unit's most recent judgment (or nil when it has
// none), so a UI can show the effective invalid state. Read-only.
func (s *ConceptService) LatestUnitJudgment(ctx context.Context, unitID int64) (*domain.UnitResolutionJudgment, error) {
	return s.concepts.LatestUnitJudgment(ctx, unitID)
}

// ListUnitJudgments returns a unit's full append-only judgment history (newest
// first) for a provenance UI. Read-only.
func (s *ConceptService) ListUnitJudgments(ctx context.Context, unitID int64) ([]domain.UnitResolutionJudgment, error) {
	return s.concepts.ListUnitJudgments(ctx, unitID)
}

// RecordDistinction records an explicit human DISTINCT judgment: the unit is NOT
// the same learning identity as the concept. It is an append-only negative pair
// for future ML training; it creates no membership and no relation and never
// changes SAME membership, so the unit stays reviewable. Returns
// domain.ErrNotFound if the unit or concept does not exist.
func (s *ConceptService) RecordDistinction(ctx context.Context, unitID, conceptID int64) (*domain.UnitConceptDistinction, error) {
	evidence := mustEvidence(map[string]any{"reason": "human_distinct", "resolver": domain.ConceptResolverVersion})
	return s.concepts.RecordDistinction(ctx, unitID, conceptID, domain.SourceHuman, evidence)
}

// ListDistinctions returns a unit's full append-only DISTINCT history (newest
// first). Read-only.
func (s *ConceptService) ListDistinctions(ctx context.Context, unitID int64) ([]domain.UnitConceptDistinction, error) {
	return s.concepts.ListDistinctions(ctx, unitID)
}

// CreateConcept creates a new durable concept from an explicit identity (and an
// optional seed unit). The repository checks — inside one transaction — that no
// non-retired concept already owns the same durable identity signature, returning
// domain.ErrConceptConflict if one does. When SeedUnitID is set and linkSeedAsSame
// is true, the SAME repository transaction also records the seed unit's accepted
// SAME membership, so create-and-attach is atomic: if the seed link fails, no
// concept persists either.
func (s *ConceptService) CreateConcept(ctx context.Context, identity domain.ConceptIdentity, seedUnitID *int64, linkSeedAsSame bool) (*domain.KnowledgeConcept, *domain.UnitConceptLink, error) {
	in := domain.NewConceptInput{
		Identity:       identity,
		SeedUnitID:     seedUnitID,
		LinkSeedAsSame: seedUnitID != nil && linkSeedAsSame,
		SeedSource:     domain.SourceHuman,
		SeedEvidence:   mustEvidence(map[string]any{"reason": "seed_unit_same", "resolver": domain.ConceptResolverVersion}),
	}
	return s.concepts.CreateConcept(ctx, in)
}

// RecordRelation records a non-membership BROADER/NARROWER/RELATED decision. It
// never affects SAME membership or automatic support. RelationSame is rejected
// with domain.ErrValidation (use ResolveSame).
func (s *ConceptService) RecordRelation(ctx context.Context, unitID, conceptID int64, relation domain.ConceptRelation) (*domain.UnitConceptLink, error) {
	evidence := mustEvidence(map[string]any{"reason": "human_relation", "relation": string(relation)})
	return s.concepts.LinkRelation(ctx, unitID, conceptID, relation, domain.SourceHuman, evidence)
}

// SetPreferredUnit selects a concept's preferred representation. The unit must
// have an accepted SAME membership to the concept (validated in the repository),
// and the concept id is unchanged. Membership and preferred representation are
// deliberately separate decisions.
func (s *ConceptService) SetPreferredUnit(ctx context.Context, conceptID, unitID int64) (*domain.KnowledgeConcept, error) {
	return s.concepts.SetPreferredUnit(ctx, conceptID, unitID)
}

// GetConcept returns one concept with its resolution links. Read-only.
func (s *ConceptService) GetConcept(ctx context.Context, conceptID int64) (*domain.ConceptView, error) {
	return s.concepts.GetConcept(ctx, conceptID)
}

// GetCurrentMembership returns a unit's CURRENT SAME membership (or nil when it has
// none), read from the membership projection. It is the read model a UI must use
// to show current authority: it never infers currency from the append-only
// resolution events, which are historical evidence. Read-only; makes no AI call.
func (s *ConceptService) GetCurrentMembership(ctx context.Context, unitID int64) (*domain.CurrentConceptMembership, error) {
	return s.concepts.GetCurrentMembership(ctx, unitID)
}

// ListConcepts returns concepts filtered by optional state, newest first.
// Read-only.
func (s *ConceptService) ListConcepts(ctx context.Context, state *domain.ConceptState) ([]domain.KnowledgeConcept, error) {
	if state != nil && !domain.ValidConceptState(*state) {
		return nil, fmt.Errorf("%w: unknown concept state", domain.ErrValidation)
	}
	return s.concepts.ListConcepts(ctx, state)
}

// ListReviewableUnits returns current-extraction units awaiting SAME resolution,
// optionally scoped to one entry. Read-only.
func (s *ConceptService) ListReviewableUnits(ctx context.Context, entryID *int64) ([]domain.ReviewableUnit, error) {
	return s.concepts.ListReviewableUnits(ctx, entryID)
}

// GetCurrentExtraction returns the entry's selected current extraction id (nil
// when the entry has no successful extraction). Read-only.
func (s *ConceptService) GetCurrentExtraction(ctx context.Context, entryID int64) (*int64, error) {
	return s.current.GetCurrentExtractionID(ctx, entryID)
}

// SetCurrentExtraction explicitly selects a successful extraction as current
// (human rollback). The extraction must belong to the entry. Concept support is
// recomputed by the repository.
func (s *ConceptService) SetCurrentExtraction(ctx context.Context, entryID, extractionID int64) error {
	return s.current.SetCurrentExtraction(ctx, entryID, extractionID)
}

// mustEvidence encodes a small structured evidence map to JSON. The inputs are
// composed only of strings/numbers the service controls, so marshalling cannot
// fail; on the impossible error it falls back to an empty object rather than
// panicking. Evidence never contains secrets or raw provider payloads.
func mustEvidence(m map[string]any) string {
	b, err := json.Marshal(m)
	if err != nil {
		return "{}"
	}
	return string(b)
}
