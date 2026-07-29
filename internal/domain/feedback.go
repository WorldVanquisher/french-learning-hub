package domain

import (
	"context"
	"strings"
	"time"
)

// maxUserNoteLen bounds the optional free-form user note.
const maxUserNoteLen = 5000

// FeedbackStatus is a human judgment about an analysis.
type FeedbackStatus string

const (
	// FeedbackAccepted marks the analysis as correct as-is.
	FeedbackAccepted FeedbackStatus = "accepted"
	// FeedbackCorrected supplies improved metadata for the analysis.
	FeedbackCorrected FeedbackStatus = "corrected"
	// FeedbackRejected marks the analysis as wrong without a correction.
	FeedbackRejected FeedbackStatus = "rejected"
)

// valid reports whether s is a recognized status.
func (s FeedbackStatus) valid() bool {
	switch s {
	case FeedbackAccepted, FeedbackCorrected, FeedbackRejected:
		return true
	default:
		return false
	}
}

// Feedback is an immutable record of human judgment about a single analysis.
// Multiple feedback records may reference the same analysis so history is
// preserved; feedback never modifies the analysis or the original entry.
type Feedback struct {
	ID         int64
	AnalysisID int64
	Status     FeedbackStatus

	// Populated only when Status is FeedbackCorrected.
	CorrectedCategory    *string
	CorrectedExplanation *string

	UserNote  string
	CreatedAt time.Time
}

// NewFeedbackInput carries the fields a caller may supply when adding feedback.
type NewFeedbackInput struct {
	Status               FeedbackStatus
	CorrectedCategory    *string
	CorrectedExplanation *string
	UserNote             string
}

// Validate normalizes and checks feedback input, returning a wrapped
// ErrValidation on failure. Corrected content is required when the status is
// "corrected" and rejected otherwise, so a correction always carries the
// improved metadata and non-corrections never smuggle stray content.
func (in *NewFeedbackInput) Validate() error {
	if !in.Status.valid() {
		return errWrap("status must be one of: accepted, corrected, rejected")
	}

	in.CorrectedCategory = trimOptional(in.CorrectedCategory)
	in.CorrectedExplanation = trimOptional(in.CorrectedExplanation)
	in.UserNote = strings.TrimSpace(in.UserNote)

	if len(in.UserNote) > maxUserNoteLen {
		return errWrap("user_note exceeds maximum length")
	}

	if in.Status == FeedbackCorrected {
		if in.CorrectedCategory == nil {
			return errWrap("corrected_category is required when status is corrected")
		}
		if in.CorrectedExplanation == nil {
			return errWrap("corrected_explanation is required when status is corrected")
		}
		if len(*in.CorrectedCategory) > 100 {
			return errWrap("corrected_category exceeds maximum length")
		}
		if len(*in.CorrectedExplanation) > maxExplanationLen {
			return errWrap("corrected_explanation exceeds maximum length")
		}
	} else {
		// accepted / rejected must not carry corrected content.
		if in.CorrectedCategory != nil || in.CorrectedExplanation != nil {
			return errWrap("corrected content is only allowed when status is corrected")
		}
	}
	return nil
}

// trimOptional trims a pointer string, returning nil when the input is nil or
// becomes empty after trimming.
func trimOptional(s *string) *string {
	if s == nil {
		return nil
	}
	trimmed := strings.TrimSpace(*s)
	if trimmed == "" {
		return nil
	}
	return &trimmed
}

// FeedbackRepository is the persistence boundary for analysis feedback.
type FeedbackRepository interface {
	// Create appends a feedback record for analysisID.
	// Returns ErrNotFound if the analysis does not exist.
	Create(ctx context.Context, analysisID int64, in NewFeedbackInput) (*Feedback, error)
	// ListByAnalysis returns all feedback for analysisID, oldest first.
	// Returns ErrNotFound if the analysis does not exist (distinct from an
	// existing analysis that simply has no feedback yet).
	ListByAnalysis(ctx context.Context, analysisID int64) ([]*Feedback, error)
}
