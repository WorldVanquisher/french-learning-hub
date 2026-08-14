package application

import (
	"context"
	"errors"
	"testing"

	"french-learning-app/internal/domain"
)

// fakeConceptRepo is a hand-written in-memory stand-in for both
// domain.ConceptRepository and domain.CurrentExtractionRepository. It records
// LinkSame calls so tests can assert whether the auto-resolver created a
// membership.
type fakeConceptRepo struct {
	unit         *domain.KnowledgeUnit
	unitErr      error
	bySignature  []domain.KnowledgeConcept
	linkSameCall int
	lastLinkedTo int64
}

func (f *fakeConceptRepo) UnitByID(context.Context, int64) (*domain.KnowledgeUnit, error) {
	if f.unitErr != nil {
		return nil, f.unitErr
	}
	return f.unit, nil
}
func (f *fakeConceptRepo) FindActiveBySignature(context.Context, string) ([]domain.KnowledgeConcept, error) {
	return f.bySignature, nil
}
func (f *fakeConceptRepo) CreateConcept(context.Context, domain.NewConceptInput) (*domain.KnowledgeConcept, error) {
	return &domain.KnowledgeConcept{ID: 1, State: domain.ConceptActive}, nil
}
func (f *fakeConceptRepo) GetConcept(context.Context, int64) (*domain.ConceptView, error) {
	return &domain.ConceptView{}, nil
}
func (f *fakeConceptRepo) ListConcepts(context.Context, *domain.ConceptState) ([]domain.KnowledgeConcept, error) {
	return nil, nil
}
func (f *fakeConceptRepo) LinkSame(_ context.Context, unitID, conceptID int64, _ domain.DecisionSource, score *float64, _ string) (*domain.UnitConceptLink, error) {
	f.linkSameCall++
	f.lastLinkedTo = conceptID
	return &domain.UnitConceptLink{ID: 10, UnitID: unitID, ConceptID: conceptID, Relation: domain.RelationSame, Status: domain.LinkAccepted, Score: score}, nil
}
func (f *fakeConceptRepo) LinkRelation(context.Context, int64, int64, domain.ConceptRelation, domain.DecisionSource, string) (*domain.UnitConceptLink, error) {
	return &domain.UnitConceptLink{}, nil
}
func (f *fakeConceptRepo) SetPreferredUnit(context.Context, int64, int64) (*domain.KnowledgeConcept, error) {
	return &domain.KnowledgeConcept{}, nil
}
func (f *fakeConceptRepo) ListReviewableUnits(context.Context, *int64) ([]domain.ReviewableUnit, error) {
	return nil, nil
}
func (f *fakeConceptRepo) ActiveSupportUnitIDs(context.Context, int64) ([]int64, error) {
	return nil, nil
}
func (f *fakeConceptRepo) GetCurrentExtractionID(context.Context, int64) (*int64, error) {
	return nil, nil
}
func (f *fakeConceptRepo) SetCurrentExtraction(context.Context, int64, int64) error { return nil }

func sampleUnit() *domain.KnowledgeUnit {
	return &domain.KnowledgeUnit{ID: 7, Kind: domain.KindGrammar, Canonical: "vouloir + inf", Statement: "s"}
}

func TestAutoResolve_LinksOnSingleMatch(t *testing.T) {
	repo := &fakeConceptRepo{
		unit:        sampleUnit(),
		bySignature: []domain.KnowledgeConcept{{ID: 42, State: domain.ConceptActive}},
	}
	svc := NewConceptService(nil, repo, repo)

	outcome, link, err := svc.AutoResolve(context.Background(), 7)
	if err != nil {
		t.Fatalf("auto resolve: %v", err)
	}
	if outcome.Kind != domain.ResolutionMatched {
		t.Fatalf("expected matched, got %q", outcome.Kind)
	}
	if link == nil || repo.linkSameCall != 1 || repo.lastLinkedTo != 42 {
		t.Fatalf("expected an automatic SAME link to concept 42, calls=%d", repo.linkSameCall)
	}
}

func TestAutoResolve_NoMatchDoesNotLink(t *testing.T) {
	repo := &fakeConceptRepo{unit: sampleUnit(), bySignature: nil}
	svc := NewConceptService(nil, repo, repo)

	outcome, link, err := svc.AutoResolve(context.Background(), 7)
	if err != nil {
		t.Fatalf("auto resolve: %v", err)
	}
	if outcome.Kind != domain.ResolutionNoMatch {
		t.Fatalf("expected no_match, got %q", outcome.Kind)
	}
	if link != nil || repo.linkSameCall != 0 {
		t.Fatalf("no_match must not create a link")
	}
}

func TestAutoResolve_AmbiguousDoesNotLink(t *testing.T) {
	// Two active concepts share the signature: the resolver must NOT force-merge.
	repo := &fakeConceptRepo{
		unit:        sampleUnit(),
		bySignature: []domain.KnowledgeConcept{{ID: 1, State: domain.ConceptActive}, {ID: 2, State: domain.ConceptActive}},
	}
	svc := NewConceptService(nil, repo, repo)

	outcome, link, err := svc.AutoResolve(context.Background(), 7)
	if err != nil {
		t.Fatalf("auto resolve: %v", err)
	}
	if outcome.Kind != domain.ResolutionAmbiguous {
		t.Fatalf("expected ambiguous, got %q", outcome.Kind)
	}
	if link != nil || repo.linkSameCall != 0 {
		t.Fatalf("ambiguous must stay reviewable, not force-merge")
	}
}

func TestResolveCandidate_UnitNotFound(t *testing.T) {
	repo := &fakeConceptRepo{unitErr: domain.ErrNotFound}
	svc := NewConceptService(nil, repo, repo)
	if _, err := svc.ResolveCandidate(context.Background(), 99); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestListConcepts_RejectsUnknownState(t *testing.T) {
	repo := &fakeConceptRepo{}
	svc := NewConceptService(nil, repo, repo)
	bad := domain.ConceptState("bogus")
	if _, err := svc.ListConcepts(context.Background(), &bad); !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation for unknown state, got %v", err)
	}
}
