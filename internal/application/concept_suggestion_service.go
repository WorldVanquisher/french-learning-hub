package application

import (
	"context"
	"errors"
	"fmt"
	"sync"

	"french-learning-app/internal/domain"
)

// ConceptSuggestionService runs FLH-097 explicit, bounded Concept membership
// suggestions. Generation is advisory: it selects bounded candidates with the
// existing exact-signature and BM25 retrievers, makes at most one provider call
// per request, validates the output against the request and stores it apart
// from every authority. Confirmation is a separate explicit human action that
// the repository revalidates atomically. Nothing here runs on startup, in the
// background, on a timer or because something was read.
type ConceptSuggestionService struct {
	repo      domain.ConceptSuggestionRepository
	suggester domain.ConceptSuggester // nil when SUGGESTION_PROVIDER=disabled
	exact     ConceptRetriever
	lexical   ConceptRetriever
	inFlight  sync.Map // operation ID -> struct{}
}

// NewConceptSuggestionService wires the service. suggester may be nil.
func NewConceptSuggestionService(repo domain.ConceptSuggestionRepository, suggester domain.ConceptSuggester) *ConceptSuggestionService {
	return &ConceptSuggestionService{
		repo: repo, suggester: suggester,
		exact: NewExactSignatureConceptRetriever(), lexical: NewBM25ConceptRetriever(),
	}
}

// Enabled reports whether a suggester is configured.
func (s *ConceptSuggestionService) Enabled() bool { return s.suggester != nil }

// Generator is the configured generator provenance, or "" when disabled.
func (s *ConceptSuggestionService) Generator() string {
	if s.suggester == nil {
		return ""
	}
	return s.suggester.Name()
}

// GenerationError reports a provider or output failure whose failed run was
// stored (Run) so an unknown-outcome client can find it by its key.
type GenerationError struct {
	Run *domain.ConceptSuggestionRun
	Err error
}

func (e *GenerationError) Error() string { return e.Err.Error() }
func (e *GenerationError) Unwrap() error { return e.Err }

// Generate handles one explicit request under its Idempotency-Key. An existing
// run for the key is returned as a replay (replay=true) for the same unit_ids
// and is a conflict for different ones, even when the suggester is now
// disabled. Otherwise every unit must be reviewable now; candidates are chosen;
// oversized text is rejected; and the provider is called once for the units
// that have candidates. A provider or output failure stores a failed run and
// returns *GenerationError. No membership, Concept, judgment, distinction,
// admission or preferred unit is ever written.
func (s *ConceptSuggestionService) Generate(ctx context.Context, operationID string, unitIDs []int64) (*domain.ConceptSuggestionRun, bool, error) {
	operationID, err := domain.NormalizeAnnotationOperationID(operationID)
	if err != nil {
		return nil, false, err
	}
	if err := domain.ValidateSuggestionUnitIDs(unitIDs); err != nil {
		return nil, false, err
	}
	prior, err := s.repo.GetSuggestionRunByOperation(ctx, operationID)
	if err == nil {
		if !domain.SameUnitIDs(prior.RequestUnitIDs, unitIDs) {
			return nil, false, fmt.Errorf("%w: it names a run for different unit_ids", domain.ErrSuggestionKeyConflict)
		}
		return prior, true, nil
	}
	if !errors.Is(err, domain.ErrNotFound) {
		return nil, false, err
	}
	if s.suggester == nil {
		return nil, false, domain.ErrSuggesterDisabled
	}
	if _, busy := s.inFlight.LoadOrStore(operationID, struct{}{}); busy {
		return nil, false, domain.ErrSuggestionInProgress
	}
	defer s.inFlight.Delete(operationID)

	plan, err := s.prepare(ctx, unitIDs)
	if err != nil {
		return nil, false, err
	}
	run := domain.NewSuggestionRun{
		OperationID: operationID, RequestUnitIDs: unitIDs, Status: domain.SuggestionRunCompleted,
		Generator: s.suggester.Name(),
	}
	proposals := map[int64]domain.SuggestionProposal{}
	if len(plan.request.Units) > 0 {
		// No SQLite transaction is open during this call.
		run.ProviderCalled = true
		got, perr := s.suggester.Suggest(ctx, plan.request)
		if perr == nil {
			got, perr = domain.ValidateSuggestionProposals(plan.request, got)
		}
		if perr != nil {
			code := failureCode(perr)
			run.Status, run.FailureCode = domain.SuggestionRunFailed, &code
			stored, replay, cerr := s.repo.CommitSuggestionRun(ctx, run)
			if cerr != nil {
				return nil, false, cerr
			}
			if replay {
				return stored, true, nil
			}
			return nil, false, &GenerationError{Run: stored, Err: perr}
		}
		for _, p := range got {
			proposals[p.UnitID] = p
		}
	}
	for _, u := range plan.units {
		item := domain.NewSuggestionItem{
			UnitID: u.source.Unit.ID, EntryID: u.source.EntryID, SourceExtractionID: u.source.Unit.ExtractionID,
			Candidates: u.candidates,
		}
		if len(u.candidates) == 0 {
			item.Outcome = domain.SuggestionNoCandidates
		} else {
			p := proposals[u.source.Unit.ID]
			item.Outcome, item.SuggestedConceptID, item.Reason = p.Outcome, p.ConceptID, p.Reason
		}
		run.Items = append(run.Items, item)
	}
	return s.repo.CommitSuggestionRun(ctx, run)
}

func failureCode(err error) domain.SuggestionFailureCode {
	switch {
	case errors.Is(err, domain.ErrProviderTimeout):
		return domain.SuggestionFailureTimeout
	case errors.Is(err, domain.ErrValidation):
		return domain.SuggestionFailureInvalidOutput
	default:
		return domain.SuggestionFailureUnavailable
	}
}

type plannedUnit struct {
	source     domain.SuggestionSourceUnit
	candidates []domain.SuggestionCandidate
}

type suggestionPlan struct {
	units   []plannedUnit
	request domain.SuggestionRequest
}

// prepare loads the units, selects candidates and builds the bounded request.
func (s *ConceptSuggestionService) prepare(ctx context.Context, unitIDs []int64) (*suggestionPlan, error) {
	sources, err := s.repo.SuggestionSourceUnits(ctx, unitIDs)
	if err != nil {
		return nil, err
	}
	catalog, err := s.repo.SuggestionCatalog(ctx)
	if err != nil {
		return nil, err
	}
	byID := make(map[int64]domain.KnowledgeConcept, len(catalog))
	for _, c := range catalog {
		byID[c.ID] = c
	}
	plan := &suggestionPlan{}
	needed := map[int64]bool{}
	for _, src := range sources {
		if n := (domain.SuggestionUnitInput{Canonical: src.Unit.Canonical, Statement: src.Unit.Statement, Example: src.Unit.Example}).TextChars(); n > domain.MaxSuggestionUnitTextChars {
			return nil, fmt.Errorf("%w: unit %d text has %d characters; the limit is %d", domain.ErrValidation, src.Unit.ID, n, domain.MaxSuggestionUnitTextChars)
		}
		docs := make([]ConceptRetrievalDocument, 0, len(catalog))
		for _, c := range catalog {
			if !src.DistinctConceptIDs[c.ID] {
				docs = append(docs, toConceptRetrievalDocument(c))
			}
		}
		candidates, err := s.selectCandidates(ctx, toConceptRetrievalQuery(src.Unit), docs, byID)
		if err != nil {
			return nil, err
		}
		for _, c := range candidates {
			needed[c.ConceptID] = true
		}
		plan.units = append(plan.units, plannedUnit{source: src, candidates: candidates})
	}
	ids := make([]int64, 0, len(needed))
	for id := range needed {
		ids = append(ids, id)
	}
	examples, err := s.repo.ConceptMemberExamples(ctx, ids, domain.SuggestionMemberExamples)
	if err != nil {
		return nil, err
	}
	for _, pu := range plan.units {
		if len(pu.candidates) == 0 {
			continue
		}
		in := domain.SuggestionUnitInput{
			UnitID: pu.source.Unit.ID, Kind: pu.source.Unit.Kind, Canonical: pu.source.Unit.Canonical,
			Statement: pu.source.Unit.Statement, Example: pu.source.Unit.Example,
		}
		for _, c := range pu.candidates {
			concept := byID[c.ConceptID]
			ci := domain.SuggestionConceptInput{
				ConceptID: concept.ID, Target: concept.Target, PedagogicalIntent: concept.PedagogicalIntent,
				Scope: concept.Scope, IdentityFeatures: concept.IdentityFeatures, MemberExamples: examples[concept.ID],
			}
			if ci.IdentityFeatures == nil {
				ci.IdentityFeatures = map[string]string{}
			}
			if ci.MemberExamples == nil {
				ci.MemberExamples = []domain.SuggestionMemberExample{}
			}
			if n := ci.TextChars(); n > domain.MaxSuggestionConceptTextChars {
				return nil, fmt.Errorf("%w: candidate concept %d text has %d characters; the limit is %d", domain.ErrValidation, concept.ID, n, domain.MaxSuggestionConceptTextChars)
			}
			in.Candidates = append(in.Candidates, ci)
		}
		plan.request.Units = append(plan.request.Units, in)
	}
	return plan, nil
}

// selectCandidates applies concept_suggestion_candidates_v1: exact signature
// matches first, then BM25 by rank, deduplicated, at most
// SuggestionCandidatesPerUnit.
func (s *ConceptSuggestionService) selectCandidates(ctx context.Context, q ConceptRetrievalQuery, docs []ConceptRetrievalDocument, byID map[int64]domain.KnowledgeConcept) ([]domain.SuggestionCandidate, error) {
	limit := domain.SuggestionCandidatesPerUnit
	out := []domain.SuggestionCandidate{}
	seen := map[int64]bool{}
	add := func(results []ConceptRetrievalCandidate, source string) {
		for _, r := range results {
			if len(out) >= limit || seen[r.ConceptID] {
				continue
			}
			seen[r.ConceptID] = true
			c := byID[r.ConceptID]
			out = append(out, domain.SuggestionCandidate{
				ConceptID: c.ID, Rank: len(out) + 1, Source: source, Signature: c.Signature, Target: c.Target,
			})
		}
	}
	exact, err := s.exact.Retrieve(ctx, q, docs, limit)
	if err != nil {
		return nil, err
	}
	add(exact, "exact_signature")
	lexical, err := s.lexical.Retrieve(ctx, q, docs, limit)
	if err != nil {
		return nil, err
	}
	add(lexical, "bm25")
	return out, nil
}

// Confirm records the explicit human SAME for one suggested item, after the
// repository revalidates the current state in the same transaction. A repeated
// confirmation of the same item replays the original event.
func (s *ConceptSuggestionService) Confirm(ctx context.Context, itemID, conceptID int64) (*domain.ConceptSuggestionItem, *domain.UnitConceptLink, bool, error) {
	if itemID <= 0 || conceptID <= 0 {
		return nil, nil, false, fmt.Errorf("%w: item and concept ids must be positive", domain.ErrValidation)
	}
	return s.repo.ConfirmSuggestion(ctx, itemID, conceptID)
}

// GetRun returns one stored run with derived item states. Read-only.
func (s *ConceptSuggestionService) GetRun(ctx context.Context, id int64) (*domain.ConceptSuggestionRun, error) {
	return s.repo.GetSuggestionRun(ctx, id)
}

// GetRunByOperation returns the committed run for a key. Read-only. 404 means
// nothing was committed under it (yet); it never means canceled.
func (s *ConceptSuggestionService) GetRunByOperation(ctx context.Context, operationID string) (*domain.ConceptSuggestionRun, error) {
	operationID, err := domain.NormalizeAnnotationOperationID(operationID)
	if err != nil {
		return nil, err
	}
	return s.repo.GetSuggestionRunByOperation(ctx, operationID)
}

// ListRuns returns recent runs, newest first. Read-only.
func (s *ConceptSuggestionService) ListRuns(ctx context.Context, limit int) ([]domain.ConceptSuggestionRun, error) {
	if limit <= 0 {
		limit = domain.DefaultSuggestionRunsListLimit
	}
	if limit > domain.MaxSuggestionRunsListed {
		limit = domain.MaxSuggestionRunsListed
	}
	return s.repo.ListSuggestionRuns(ctx, limit)
}
