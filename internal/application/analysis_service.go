package application

import (
	"context"
	"fmt"

	"french-learning-app/internal/domain"
)

// AnalysisService coordinates producing and persisting versioned analyses for
// learning entries. It validates analyzer output before storage so invalid AI
// metadata never reaches the database, and it never mutates the original entry.
type AnalysisService struct {
	entries  domain.Repository
	analyses domain.AnalysisRepository
	analyzer domain.Analyzer
}

// NewAnalysisService wires the service to its repositories and analyzer.
func NewAnalysisService(entries domain.Repository, analyses domain.AnalysisRepository, analyzer domain.Analyzer) *AnalysisService {
	return &AnalysisService{entries: entries, analyses: analyses, analyzer: analyzer}
}

// AnalyzeEntry loads the entry, runs the analyzer over its original data,
// validates the result, and appends it as a new versioned analysis.
//
// Returns domain.ErrNotFound if the entry does not exist and a wrapped
// domain.ErrValidation if the analyzer produces invalid metadata.
func (s *AnalysisService) AnalyzeEntry(ctx context.Context, entryID int64) (*domain.Analysis, error) {
	entry, err := s.entries.GetByID(ctx, entryID)
	if err != nil {
		return nil, err // includes domain.ErrNotFound
	}

	result, err := s.analyzer.Analyze(ctx, entry)
	if err != nil {
		return nil, fmt.Errorf("analyze entry: %w", err)
	}
	if err := result.Validate(); err != nil {
		return nil, err // wrapped domain.ErrValidation
	}

	return s.analyses.Create(ctx, entryID, result, s.analyzer.Name())
}

// ListAnalyses returns all analyses for an entry, oldest version first. It
// returns domain.ErrNotFound if the entry does not exist.
func (s *AnalysisService) ListAnalyses(ctx context.Context, entryID int64) ([]*domain.Analysis, error) {
	if _, err := s.entries.GetByID(ctx, entryID); err != nil {
		return nil, err // includes domain.ErrNotFound
	}
	return s.analyses.ListByEntry(ctx, entryID)
}
