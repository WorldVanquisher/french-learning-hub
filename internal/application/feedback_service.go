package application

import (
	"context"

	"french-learning-app/internal/domain"
)

// FeedbackService coordinates adding and listing immutable human feedback for
// analyses. It validates input before storage and never mutates the referenced
// analysis or the original entry.
type FeedbackService struct {
	feedback domain.FeedbackRepository
}

// NewFeedbackService wires the service to its repository.
func NewFeedbackService(feedback domain.FeedbackRepository) *FeedbackService {
	return &FeedbackService{feedback: feedback}
}

// AddFeedback validates the input and appends a feedback record for analysisID.
// Returns domain.ErrNotFound if the analysis does not exist and a wrapped
// domain.ErrValidation if the input is invalid.
func (s *FeedbackService) AddFeedback(ctx context.Context, analysisID int64, in domain.NewFeedbackInput) (*domain.Feedback, error) {
	if err := in.Validate(); err != nil {
		return nil, err
	}
	return s.feedback.Create(ctx, analysisID, in)
}

// ListFeedback returns all feedback for an analysis, oldest first. Returns
// domain.ErrNotFound if the analysis does not exist.
func (s *FeedbackService) ListFeedback(ctx context.Context, analysisID int64) ([]*domain.Feedback, error) {
	return s.feedback.ListByAnalysis(ctx, analysisID)
}
