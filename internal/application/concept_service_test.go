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
	rejectCall      int
	lastRejectUnit  int64
	rejectLink      *domain.UnitConceptLink

	markInvalidCall    int
	lastMarkInvalidHit int64
	markInvalidJudg    *domain.UnitResolutionJudgment
	restoreCall        int
	restoreJudg        *domain.UnitResolutionJudgment
	distinctCall       int
	lastDistinctUnit   int64
	lastDistinctConc   int64
	distinctRecord     *domain.UnitConceptDistinction
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
func (f *fakeConceptRepo) RejectSame(_ context.Context, unitID int64, _ domain.DecisionSource, _ string) (*domain.UnitConceptLink, error) {
	f.rejectCall++
	f.lastRejectUnit = unitID
	return f.rejectLink, nil
}
func (f *fakeConceptRepo) MarkUnitInvalid(_ context.Context, unitID int64, _ domain.DecisionSource, _, _ string) (*domain.UnitResolutionJudgment, error) {
	f.markInvalidCall++
	f.lastMarkInvalidHit = unitID
	return f.markInvalidJudg, nil
}
func (f *fakeConceptRepo) RestoreUnit(context.Context, int64, domain.DecisionSource, string, string) (*domain.UnitResolutionJudgment, error) {
	f.restoreCall++
	return f.restoreJudg, nil
}
func (f *fakeConceptRepo) LatestUnitJudgment(context.Context, int64) (*domain.UnitResolutionJudgment, error) {
	return f.markInvalidJudg, nil
}
func (f *fakeConceptRepo) ListUnitJudgments(context.Context, int64) ([]domain.UnitResolutionJudgment, error) {
	return nil, nil
}
func (f *fakeConceptRepo) RecordDistinction(_ context.Context, unitID, conceptID int64, _ domain.DecisionSource, _ string) (*domain.UnitConceptDistinction, error) {
	f.distinctCall++
	f.lastDistinctUnit = unitID
	f.lastDistinctConc = conceptID
	return f.distinctRecord, nil
}
func (f *fakeConceptRepo) ListDistinctions(context.Context, int64) ([]domain.UnitConceptDistinction, error) {
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

// RejectSame (INVALID) routes to the repository's rejection operation with a human
// source; it does not go through LinkSame or ReassignSame.
func TestRejectSame_RoutesToReject(t *testing.T) {
	repo := &fakeConceptRepo{rejectLink: &domain.UnitConceptLink{ID: 12, UnitID: 7, ConceptID: 1, Relation: domain.RelationSame, Status: domain.LinkRejected}}
	svc := NewConceptService(nil, repo, repo)
	link, err := svc.RejectSame(context.Background(), 7)
	if err != nil {
		t.Fatalf("reject: %v", err)
	}
	if link == nil || link.Status != domain.LinkRejected {
		t.Fatalf("expected the rejection event, got %+v", link)
	}
	if repo.rejectCall != 1 || repo.lastRejectUnit != 7 {
		t.Fatalf("expected one rejection of unit 7, got calls=%d unit=%d", repo.rejectCall, repo.lastRejectUnit)
	}
	if repo.linkSameCall != 0 || repo.reassignCall != 0 {
		t.Fatalf("reject must not route through LinkSame/ReassignSame")
	}
}

// A no-op rejection (unit already had no current membership) returns a nil link
// without error, and the service passes that through unchanged.
func TestRejectSame_NoopReturnsNil(t *testing.T) {
	repo := &fakeConceptRepo{rejectLink: nil}
	svc := NewConceptService(nil, repo, repo)
	link, err := svc.RejectSame(context.Background(), 7)
	if err != nil {
		t.Fatalf("reject no-op: %v", err)
	}
	if link != nil {
		t.Fatalf("expected nil link for a no-op rejection, got %+v", link)
	}
	if repo.rejectCall != 1 {
		t.Fatalf("expected one rejection call, got %d", repo.rejectCall)
	}
}

// MarkUnitInvalid (unit-level INVALID) routes to the repository's unit-level
// operation with a human source; it does NOT route through RejectSame (the
// membership-level correction), which is a distinct concept.
func TestMarkUnitInvalid_RoutesToUnitLevel(t *testing.T) {
	repo := &fakeConceptRepo{markInvalidJudg: &domain.UnitResolutionJudgment{ID: 5, UnitID: 7, Judgment: domain.UnitInvalid, DecisionSource: domain.SourceHuman}}
	svc := NewConceptService(nil, repo, repo)
	j, err := svc.MarkUnitInvalid(context.Background(), 7)
	if err != nil {
		t.Fatalf("mark invalid: %v", err)
	}
	if j == nil || j.Judgment != domain.UnitInvalid {
		t.Fatalf("expected the invalid judgment, got %+v", j)
	}
	if repo.markInvalidCall != 1 || repo.lastMarkInvalidHit != 7 {
		t.Fatalf("expected one unit-level INVALID of unit 7, got calls=%d unit=%d", repo.markInvalidCall, repo.lastMarkInvalidHit)
	}
	// Unit-level INVALID is not the membership-level reject.
	if repo.rejectCall != 0 {
		t.Fatalf("MarkUnitInvalid must not route through RejectSame, got %d reject calls", repo.rejectCall)
	}
}

// RestoreUnit routes to the repository's restore operation; a no-op restore
// (unit not currently invalid) returns nil and is passed through unchanged.
func TestRestoreUnit_RoutesToRestore(t *testing.T) {
	repo := &fakeConceptRepo{restoreJudg: &domain.UnitResolutionJudgment{ID: 6, UnitID: 7, Judgment: domain.UnitRestored}}
	svc := NewConceptService(nil, repo, repo)
	j, err := svc.RestoreUnit(context.Background(), 7)
	if err != nil {
		t.Fatalf("restore: %v", err)
	}
	if j == nil || j.Judgment != domain.UnitRestored {
		t.Fatalf("expected the restored judgment, got %+v", j)
	}
	if repo.restoreCall != 1 {
		t.Fatalf("expected one restore call, got %d", repo.restoreCall)
	}

	repo2 := &fakeConceptRepo{restoreJudg: nil}
	svc2 := NewConceptService(nil, repo2, repo2)
	j2, err := svc2.RestoreUnit(context.Background(), 7)
	if err != nil {
		t.Fatalf("restore no-op: %v", err)
	}
	if j2 != nil {
		t.Fatalf("a no-op restore must return nil, got %+v", j2)
	}
}

// RecordDistinction routes to the repository's distinction operation without
// touching SAME membership (LinkSame/ReassignSame): DISTINCT is an explicit
// negative pair, not a membership.
func TestRecordDistinction_RoutesWithoutMembership(t *testing.T) {
	repo := &fakeConceptRepo{distinctRecord: &domain.UnitConceptDistinction{ID: 3, UnitID: 7, ConceptID: 42, DecisionSource: domain.SourceHuman}}
	svc := NewConceptService(nil, repo, repo)
	d, err := svc.RecordDistinction(context.Background(), 7, 42)
	if err != nil {
		t.Fatalf("record distinction: %v", err)
	}
	if d == nil || d.UnitID != 7 || d.ConceptID != 42 {
		t.Fatalf("expected the distinction record, got %+v", d)
	}
	if repo.distinctCall != 1 || repo.lastDistinctUnit != 7 || repo.lastDistinctConc != 42 {
		t.Fatalf("expected one distinction of (7,42), got calls=%d unit=%d concept=%d", repo.distinctCall, repo.lastDistinctUnit, repo.lastDistinctConc)
	}
	if repo.linkSameCall != 0 || repo.reassignCall != 0 {
		t.Fatalf("DISTINCT must not create or move a SAME membership")
	}
}
