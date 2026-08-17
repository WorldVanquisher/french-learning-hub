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
}

// NewEffectiveAnnotationService wires the read-only annotation projection.
func NewEffectiveAnnotationService(annotations domain.EffectiveAnnotationRepository) *EffectiveAnnotationService {
	return &EffectiveAnnotationService{annotations: annotations}
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
