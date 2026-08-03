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
// ErrValidation on failure. When the status is "corrected", at least one of
// corrected_category or corrected_explanation must be present (either or both
// is allowed), so a correction always carries some improved metadata.
// Blank or whitespace-only corrected values count as absent. For "accepted" and
// "rejected", corrected content must be absent so non-corrections never smuggle
// stray metadata.
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
		if in.CorrectedCategory == nil && in.CorrectedExplanation == nil {
			return errWrap("at least one of corrected_category or corrected_explanation is required when status is corrected")
		}
		// A corrected category is a persisted category, so it must use the shared
		// fr_l2_taxonomy_v1 taxonomy. Normalize to lowercase (trimOptional already
		// trimmed) and validate against the single source of truth, not a copy of
		// the list. Store the normalized value.
		if in.CorrectedCategory != nil {
			normalized := strings.ToLower(*in.CorrectedCategory)
			if !ValidCategory(normalized) {
				return errWrap("corrected_category must be one of the " + TaxonomyVersion + " taxonomy values")
			}
			in.CorrectedCategory = &normalized
		}
		if in.CorrectedExplanation != nil && len(*in.CorrectedExplanation) > maxExplanationLen {
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
	// GetLatestByAnalysis returns the single most recent feedback for analysisID,
	// selected deterministically by created_at DESC, id DESC. Returns
	// ErrNotFound if the analysis does not exist, and (nil, nil) when the
	// analysis exists but has no feedback yet.
	GetLatestByAnalysis(ctx context.Context, analysisID int64) (*Feedback, error)
}
