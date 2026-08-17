package application

import (
	"context"
	"errors"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

type stubEffectiveAnnotationRepo struct {
	latest       *domain.UnitResolutionJudgment
	membership   *domain.CurrentConceptMembership
	links        []domain.UnitConceptLink
	distinctions []domain.UnitConceptDistinction
	unit         *domain.KnowledgeUnit
	currentUnits []domain.KnowledgeUnit

	latestErr       error
	membershipErr   error
	linksErr        error
	distinctionsErr error
	unitErr         error
	currentUnitsErr error
}

func (s *stubEffectiveAnnotationRepo) LatestUnitJudgment(context.Context, int64) (*domain.UnitResolutionJudgment, error) {
	return s.latest, s.latestErr
}

func (s *stubEffectiveAnnotationRepo) GetCurrentMembership(context.Context, int64) (*domain.CurrentConceptMembership, error) {
	return s.membership, s.membershipErr
}

func (s *stubEffectiveAnnotationRepo) ListUnitConceptLinks(context.Context, int64) ([]domain.UnitConceptLink, error) {
	return s.links, s.linksErr
}

func (s *stubEffectiveAnnotationRepo) ListDistinctions(context.Context, int64) ([]domain.UnitConceptDistinction, error) {
	return s.distinctions, s.distinctionsErr
}

func (s *stubEffectiveAnnotationRepo) UnitByID(context.Context, int64) (*domain.KnowledgeUnit, error) {
	return s.unit, s.unitErr
}

func (s *stubEffectiveAnnotationRepo) ListCurrentExtractionUnits(context.Context) ([]domain.KnowledgeUnit, error) {
	return s.currentUnits, s.currentUnitsErr
}

func TestEffectiveAnnotationService_ComposesPersistedFacts(t *testing.T) {
	createdAt := time.Date(2026, time.January, 1, 0, 0, 0, 0, time.UTC)
	same := domain.UnitConceptLink{
		ID:              11,
		UnitID:          7,
		ConceptID:       42,
		Relation:        domain.RelationSame,
		Status:          domain.LinkAccepted,
		DecisionSource:  domain.SourceResolverAutomatic,
		ResolverVersion: domain.ConceptResolverVersion,
		Evidence:        `{"reason":"exact_signature_match"}`,
		CreatedAt:       createdAt,
	}
	repo := &stubEffectiveAnnotationRepo{
		membership: &domain.CurrentConceptMembership{UnitID: 7, ConceptID: 42, LinkID: 11, UpdatedAt: createdAt},
		links: []domain.UnitConceptLink{
			{ID: 12, UnitID: 7, ConceptID: 50, Relation: domain.RelationRelated, Status: domain.LinkAccepted, DecisionSource: domain.SourceHuman, CreatedAt: createdAt},
			same,
		},
		distinctions: []domain.UnitConceptDistinction{
			{ID: 21, UnitID: 7, ConceptID: 60, DecisionSource: domain.SourceHuman, CreatedAt: createdAt},
		},
	}

	snapshot, err := NewEffectiveAnnotationService(repo, repo).GetEffectiveAnnotationSnapshot(context.Background(), 7)
	if err != nil {
		t.Fatalf("GetEffectiveAnnotationSnapshot: %v", err)
	}
	if snapshot.Status != domain.EffectiveAnnotationResolved || snapshot.CurrentSame == nil {
		t.Fatalf("expected resolved snapshot, got %+v", snapshot)
	}
	if snapshot.CurrentSame.Decision.DecisionSource != domain.SourceResolverAutomatic {
		t.Fatalf("automatic SAME provenance was lost: %+v", snapshot.CurrentSame.Decision)
	}
	if len(snapshot.Distinctions) != 1 || snapshot.Distinctions[0].ConceptID != 60 {
		t.Fatalf("effective distinction not composed: %+v", snapshot.Distinctions)
	}
	if len(snapshot.Relations) != 1 || snapshot.Relations[0].ConceptID != 50 {
		t.Fatalf("effective relation not composed: %+v", snapshot.Relations)
	}
}

func TestEffectiveAnnotationService_PropagatesRepositoryErrors(t *testing.T) {
	want := errors.New("read links")
	repo := &stubEffectiveAnnotationRepo{linksErr: want}
	_, err := NewEffectiveAnnotationService(repo, repo).GetEffectiveAnnotationSnapshot(context.Background(), 7)
	if !errors.Is(err, want) {
		t.Fatalf("error = %v, want %v", err, want)
	}
}

func TestEffectiveAnnotationService_RejectsCorruptMembershipProvenance(t *testing.T) {
	repo := &stubEffectiveAnnotationRepo{
		membership: &domain.CurrentConceptMembership{UnitID: 7, ConceptID: 42, LinkID: 99},
		links:      nil,
	}
	_, err := NewEffectiveAnnotationService(repo, repo).GetEffectiveAnnotationSnapshot(context.Background(), 7)
	if !errors.Is(err, domain.ErrEffectiveAnnotationCorrupt) {
		t.Fatalf("expected ErrEffectiveAnnotationCorrupt, got %v", err)
	}
}

func TestEffectiveAnnotationService_GetIncludesUnitEvidence(t *testing.T) {
	unit := &domain.KnowledgeUnit{ID: 7, Kind: domain.KindGrammar, Canonical: "vouloir", Statement: "statement"}
	repo := &stubEffectiveAnnotationRepo{unit: unit}
	item, err := NewEffectiveAnnotationService(repo, repo).GetEffectiveAnnotation(context.Background(), 7)
	if err != nil {
		t.Fatalf("GetEffectiveAnnotation: %v", err)
	}
	if item.Unit.ID != 7 || item.Unit.Canonical != "vouloir" {
		t.Fatalf("unit evidence not preserved: %+v", item.Unit)
	}
	if item.Snapshot.Status != domain.EffectiveAnnotationUnresolved {
		t.Fatalf("snapshot status = %q, want unresolved", item.Snapshot.Status)
	}
}

func TestEffectiveAnnotationService_GetPropagatesMissingUnit(t *testing.T) {
	repo := &stubEffectiveAnnotationRepo{unitErr: domain.ErrNotFound}
	_, err := NewEffectiveAnnotationService(repo, repo).GetEffectiveAnnotation(context.Background(), 999)
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestEffectiveAnnotationService_ListsCurrentUnitsWithSnapshots(t *testing.T) {
	repo := &stubEffectiveAnnotationRepo{
		currentUnits: []domain.KnowledgeUnit{
			{ID: 7, Kind: domain.KindGrammar, Canonical: "a"},
			{ID: 8, Kind: domain.KindVocabulary, Canonical: "b"},
		},
	}
	items, err := NewEffectiveAnnotationService(repo, repo).ListEffectiveAnnotations(context.Background())
	if err != nil {
		t.Fatalf("ListEffectiveAnnotations: %v", err)
	}
	if len(items) != 2 || items[0].Unit.ID != 7 || items[1].Unit.ID != 8 {
		t.Fatalf("unexpected items: %+v", items)
	}
	for _, item := range items {
		if item.Snapshot.Status != domain.EffectiveAnnotationUnresolved || item.Snapshot.UnitID != item.Unit.ID {
			t.Fatalf("unit/snapshot mismatch: %+v", item)
		}
	}
}
