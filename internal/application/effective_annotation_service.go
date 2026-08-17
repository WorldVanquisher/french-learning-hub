package application

import (
	"context"

	"french-learning-app/internal/domain"
)

// EffectiveAnnotationService composes persisted annotation facts into the
// deterministic current snapshot for one KnowledgeUnit. It is read-only: storage
// retrieves facts and the domain layer decides their effective semantics.
type EffectiveAnnotationService struct {
	annotations domain.EffectiveAnnotationRepository
	units       domain.EffectiveAnnotationUnitRepository
}

// NewEffectiveAnnotationService wires the read-only annotation projection.
func NewEffectiveAnnotationService(
	annotations domain.EffectiveAnnotationRepository,
	units domain.EffectiveAnnotationUnitRepository,
) *EffectiveAnnotationService {
	return &EffectiveAnnotationService{annotations: annotations, units: units}
}

// EffectiveAnnotationItem combines immutable unit evidence with its M11-A
// effective snapshot for the read-only inspector.
type EffectiveAnnotationItem struct {
	Unit     domain.KnowledgeUnit
	Snapshot domain.EffectiveAnnotationSnapshot
}

// GetEffectiveAnnotationSnapshot loads current authority plus append-only history
// and resolves it without persisting or rewriting anything.
func (s *EffectiveAnnotationService) GetEffectiveAnnotationSnapshot(
	ctx context.Context,
	unitID int64,
) (domain.EffectiveAnnotationSnapshot, error) {
	latest, err := s.annotations.LatestUnitJudgment(ctx, unitID)
	if err != nil {
		return domain.EffectiveAnnotationSnapshot{}, err
	}
	membership, err := s.annotations.GetCurrentMembership(ctx, unitID)
	if err != nil {
		return domain.EffectiveAnnotationSnapshot{}, err
	}
	links, err := s.annotations.ListUnitConceptLinks(ctx, unitID)
	if err != nil {
		return domain.EffectiveAnnotationSnapshot{}, err
	}
	distinctions, err := s.annotations.ListDistinctions(ctx, unitID)
	if err != nil {
		return domain.EffectiveAnnotationSnapshot{}, err
	}

	return domain.ResolveEffectiveAnnotation(unitID, latest, membership, links, distinctions)
}

// GetEffectiveAnnotation returns one unit plus its effective snapshot. The unit
// lookup establishes existence before the projection reads are composed.
func (s *EffectiveAnnotationService) GetEffectiveAnnotation(
	ctx context.Context,
	unitID int64,
) (*EffectiveAnnotationItem, error) {
	unit, err := s.units.UnitByID(ctx, unitID)
	if err != nil {
		return nil, err
	}
	snapshot, err := s.GetEffectiveAnnotationSnapshot(ctx, unitID)
	if err != nil {
		return nil, err
	}
	return &EffectiveAnnotationItem{Unit: *unit, Snapshot: snapshot}, nil
}

// ListEffectiveAnnotations returns every unit in every entry's CURRENT extraction
// with its effective snapshot. Historical extraction units are excluded by the
// unit repository; no annotation-status filtering is applied here.
func (s *EffectiveAnnotationService) ListEffectiveAnnotations(
	ctx context.Context,
) ([]EffectiveAnnotationItem, error) {
	units, err := s.units.ListCurrentExtractionUnits(ctx)
	if err != nil {
		return nil, err
	}
	items := make([]EffectiveAnnotationItem, 0, len(units))
	for _, unit := range units {
		snapshot, err := s.GetEffectiveAnnotationSnapshot(ctx, unit.ID)
		if err != nil {
			return nil, err
		}
		items = append(items, EffectiveAnnotationItem{Unit: unit, Snapshot: snapshot})
	}
	return items, nil
}
