package application

import (
	"context"
	"fmt"
	"french-learning-app/internal/domain"
)

func (s *ConceptService) CommitAnnotationOperation(ctx context.Context, id string, in domain.AnnotationOperationInput) (*domain.AnnotationOperation, bool, error) {
	id, err := domain.NormalizeAnnotationOperationID(id)
	if err != nil {
		return nil, false, err
	}
	if err := in.Validate(); err != nil {
		return nil, false, err
	}
	repo, ok := s.concepts.(domain.AnnotationOperationRepository)
	if !ok {
		return nil, false, fmt.Errorf("annotation operations unavailable")
	}
	evidence := mustEvidence(map[string]any{"reason": "human_distinct", "resolver": domain.ConceptResolverVersion})
	if in.Action == "relation" {
		evidence = mustEvidence(map[string]any{"reason": "human_relation", "relation": string(in.Relation)})
	}
	return repo.CommitAnnotationOperation(ctx, id, in, evidence)
}
func (s *ConceptService) GetAnnotationOperation(ctx context.Context, id string) (*domain.AnnotationOperation, error) {
	id, err := domain.NormalizeAnnotationOperationID(id)
	if err != nil {
		return nil, err
	}
	repo, ok := s.concepts.(domain.AnnotationOperationRepository)
	if !ok {
		return nil, fmt.Errorf("annotation operations unavailable")
	}
	return repo.GetAnnotationOperation(ctx, id)
}
