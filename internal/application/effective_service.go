package application

import (
	"context"

	"french-learning-app/internal/domain"
)

// EffectiveAnalysisService resolves the current effective interpretation of a
// single immutable analysis by combining it with its latest feedback. It is
// read-only: it loads records and applies deterministic resolution rules, never
// mutating the analysis or the feedback history and never persisting the result.
type EffectiveAnalysisService struct {
	analyses domain.AnalysisRepository
	feedback domain.FeedbackRepository
}

// NewEffectiveAnalysisService wires the service to its repositories.
func NewEffectiveAnalysisService(analyses domain.AnalysisRepository, feedback domain.FeedbackRepository) *EffectiveAnalysisService {
	return &EffectiveAnalysisService{analyses: analyses, feedback: feedback}
}

// Resolve loads the analysis and its latest feedback, then derives the effective
// analysis. Returns domain.ErrNotFound if the analysis does not exist. All SQL
// stays in the repositories; this method only orchestrates and applies the pure
// domain resolution rules.
func (s *EffectiveAnalysisService) Resolve(ctx context.Context, analysisID int64) (domain.EffectiveAnalysis, error) {
	analysis, err := s.analyses.GetByID(ctx, analysisID)
	if err != nil {
		return domain.EffectiveAnalysis{}, err // includes domain.ErrNotFound
	}

	latest, err := s.feedback.GetLatestByAnalysis(ctx, analysisID)
	if err != nil {
		return domain.EffectiveAnalysis{}, err
	}

	return domain.ResolveEffective(analysis, latest), nil
}
