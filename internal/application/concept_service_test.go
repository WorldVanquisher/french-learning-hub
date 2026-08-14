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
	unit            *domain.KnowledgeUnit
	unitErr         error
	bySignature     []domain.KnowledgeConcept
	linkSameCall    int
	lastLinkedTo    int64
	reassignCall    int
	lastReassignTo  int64
	createSeedError error // when set, atomic create+attach fails after the concept insert
	createCall      int
	seedLinked      int
	membership      *domain.CurrentConceptMembership
	membershipCall  int
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

// CreateConcept models the repository's atomic create-and-attach: if a seed SAME
// is requested and createSeedError is set, the whole operation fails and no
// concept is returned (mirroring the transaction rolling back).
func (f *fakeConceptRepo) CreateConcept(_ context.Context, in domain.NewConceptInput) (*domain.KnowledgeConcept, *domain.UnitConceptLink, error) {
	f.createCall++
	if in.LinkSeedAsSame {
		if f.createSeedError != nil {
			return nil, nil, f.createSeedError
		}
		f.seedLinked++
		link := &domain.UnitConceptLink{ID: 10, UnitID: *in.SeedUnitID, ConceptID: 1, Relation: domain.RelationSame, Status: domain.LinkAccepted}
		return &domain.KnowledgeConcept{ID: 1, State: domain.ConceptActive}, link, nil
	}
	return &domain.KnowledgeConcept{ID: 1, State: domain.ConceptActive}, nil, nil
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
func (f *fakeConceptRepo) ReassignSame(_ context.Context, unitID, conceptID int64, _ domain.DecisionSource, _ string) (*domain.UnitConceptLink, error) {
	f.reassignCall++
	f.lastReassignTo = conceptID
	return &domain.UnitConceptLink{ID: 11, UnitID: unitID, ConceptID: conceptID, Relation: domain.RelationSame, Status: domain.LinkAccepted}, nil
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
func (f *fakeConceptRepo) GetCurrentMembership(_ context.Context, unitID int64) (*domain.CurrentConceptMembership, error) {
	f.membershipCall++
	return f.membership, nil
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

// ReassignSame routes to the repository's reassignment operation (human correction),
// not to LinkSame.
func TestReassignSame_RoutesToReassign(t *testing.T) {
	repo := &fakeConceptRepo{}
	svc := NewConceptService(nil, repo, repo)
	if _, err := svc.ReassignSame(context.Background(), 7, 42); err != nil {
		t.Fatalf("reassign: %v", err)
	}
	if repo.reassignCall != 1 || repo.lastReassignTo != 42 {
		t.Fatalf("expected one reassignment to concept 42, got calls=%d to=%d", repo.reassignCall, repo.lastReassignTo)
	}
	if repo.linkSameCall != 0 {
		t.Fatalf("reassignment must not go through LinkSame")
	}
}

// Create-and-attach is delegated to the repository as one atomic operation: the
// service passes LinkSeedAsSame through and does not make a second LinkSame call.
func TestCreateConcept_AtomicSeedLink(t *testing.T) {
	repo := &fakeConceptRepo{}
	svc := NewConceptService(nil, repo, repo)
	seed := int64(7)
	concept, link, err := svc.CreateConcept(context.Background(), domain.ConceptIdentity{Target: "t", PedagogicalIntent: "grammar"}, &seed, true)
	if err != nil {
		t.Fatalf("create+attach: %v", err)
	}
	if concept == nil || link == nil {
		t.Fatalf("expected concept and seed link, got %v %v", concept, link)
	}
	if repo.seedLinked != 1 || repo.createCall != 1 {
		t.Fatalf("seed link must be created inside the single CreateConcept call, got create=%d seed=%d", repo.createCall, repo.seedLinked)
	}
	if repo.linkSameCall != 0 {
		t.Fatalf("create+attach must not issue a separate LinkSame call (non-atomic), got %d", repo.linkSameCall)
	}
}

// When the atomic seed link fails, CreateConcept returns the error and no concept:
// the repository transaction rolls the concept back too.
func TestCreateConcept_SeedLinkFailureLeavesNothing(t *testing.T) {
	repo := &fakeConceptRepo{createSeedError: domain.ErrConceptConflict}
	svc := NewConceptService(nil, repo, repo)
	seed := int64(7)
	concept, link, err := svc.CreateConcept(context.Background(), domain.ConceptIdentity{Target: "t", PedagogicalIntent: "grammar"}, &seed, true)
	if !errors.Is(err, domain.ErrConceptConflict) {
		t.Fatalf("expected the seed-link error to propagate, got %v", err)
	}
	if concept != nil || link != nil {
		t.Fatalf("no concept or link must be returned on atomic failure, got %v %v", concept, link)
	}
}

// GetCurrentMembership is a read-only pass-through to the projection read model.
func TestGetCurrentMembership_ReadsProjection(t *testing.T) {
	repo := &fakeConceptRepo{membership: &domain.CurrentConceptMembership{UnitID: 7, ConceptID: 42, LinkID: 11}}
	svc := NewConceptService(nil, repo, repo)
	m, err := svc.GetCurrentMembership(context.Background(), 7)
	if err != nil {
		t.Fatalf("get current membership: %v", err)
	}
	if m == nil || m.ConceptID != 42 || m.LinkID != 11 {
		t.Fatalf("expected the projection membership, got %+v", m)
	}
	if repo.membershipCall != 1 {
		t.Fatalf("expected one projection read, got %d", repo.membershipCall)
	}

	// No membership => nil, still read-only.
	repo2 := &fakeConceptRepo{membership: nil}
	svc2 := NewConceptService(nil, repo2, repo2)
	m2, err := svc2.GetCurrentMembership(context.Background(), 7)
	if err != nil {
		t.Fatalf("get current membership (none): %v", err)
	}
	if m2 != nil {
		t.Fatalf("expected nil membership, got %+v", m2)
	}
}
