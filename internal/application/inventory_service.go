package application

import (
	"context"

	"french-learning-app/internal/domain"
)

// Inventory limit bounds. The list endpoint returns a modest page by default;
// the export endpoint allows larger batches since it streams line-by-line.
const (
	defaultListLimit   = 50
	maxListLimit       = 200
	defaultExportLimit = 500
	maxExportLimit     = 5000
)

// InventoryService provides the read-only cross-entry learning inventory. It
// validates and normalizes queries and delegates retrieval to the repository. It
// contains no SQL and no HTTP concerns: filter parsing lives in the transport
// layer, and the actual latest-analysis/latest-feedback projection lives in the
// storage layer behind domain.InventoryRepository.
type InventoryService struct {
	repo domain.InventoryRepository
}

// NewInventoryService wires the service to its repository.
func NewInventoryService(repo domain.InventoryRepository) *InventoryService {
	return &InventoryService{repo: repo}
}

// ListRecords normalizes q with list-endpoint limits, then returns the matching
// records (one per entry, entry id descending) together with the applied
// (bounded) limit. The transport layer uses the applied limit to decide whether
// a next-page cursor exists, so the limit constants stay in this layer. A
// normalization failure is a wrapped domain.ErrValidation; repository errors are
// passed through.
func (s *InventoryService) ListRecords(ctx context.Context, q domain.LearningRecordQuery) ([]*domain.LearningRecord, int, error) {
	if err := q.Normalize(defaultListLimit, maxListLimit); err != nil {
		return nil, 0, err
	}
	records, err := s.repo.ListLearningRecords(ctx, q)
	if err != nil {
		return nil, 0, err
	}
	return records, q.Limit, nil
}

// ExportRecords normalizes q with the larger export-endpoint limits, then returns
// the matching records. The transport layer is responsible for streaming them as
// JSONL; the service only bounds and retrieves. Same validation/error semantics
// as ListRecords.
func (s *InventoryService) ExportRecords(ctx context.Context, q domain.LearningRecordQuery) ([]*domain.LearningRecord, error) {
	if err := q.Normalize(defaultExportLimit, maxExportLimit); err != nil {
		return nil, err
	}
	return s.repo.ListLearningRecords(ctx, q)
}

// Summary returns aggregate counts across all learning entries.
func (s *InventoryService) Summary(ctx context.Context) (*domain.LearningInventorySummary, error) {
	return s.repo.SummarizeLearningRecords(ctx)
}
