// Package application contains use cases that coordinate domain objects and
// the repository. It contains no HTTP or SQL details.
package application

import (
	"context"

	"french-learning-app/internal/domain"
)

// EntryService implements the learning-entry use cases on top of a
// domain.Repository.
type EntryService struct {
	repo domain.Repository
}

// NewEntryService wires a service to its repository.
func NewEntryService(repo domain.Repository) *EntryService {
	return &EntryService{repo: repo}
}

// CreateEntry validates the input and persists a new learning entry. The
// returned entry contains the stored original data plus generated timestamps
// and ID. AI metadata is intentionally not set here.
func (s *EntryService) CreateEntry(ctx context.Context, in domain.NewEntryInput) (*domain.Entry, error) {
	if err := in.Validate(); err != nil {
		return nil, err
	}
	return s.repo.Create(ctx, in)
}

// GetEntry returns a single entry by ID.
func (s *EntryService) GetEntry(ctx context.Context, id int64) (*domain.Entry, error) {
	return s.repo.GetByID(ctx, id)
}

// ListEntries returns recent entries, newest first, bounded by limit.
func (s *EntryService) ListEntries(ctx context.Context, limit int) ([]*domain.Entry, error) {
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	return s.repo.List(ctx, limit)
}
