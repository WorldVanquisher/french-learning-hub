package domain

import (
	"context"
	"strings"
	"time"
)

// maxExplanationLen bounds a stored explanation.
const maxExplanationLen = 20000

// maxUncertaintyLen bounds the stored uncertainty note.
const maxUncertaintyLen = 5000

// Analysis is a versioned, immutable record of AI-generated metadata for a
// single learning entry. Multiple analyses may exist per entry; each new one
// is appended with an incrementing version and never overwrites the original
// entry or an earlier analysis.
type Analysis struct {
	ID          int64
	EntryID     int64
	Version     int64
	Category    string
	Explanation string
	Confidence  float64
	Uncertainty string
	Analyzer    string
	CreatedAt   time.Time
}

// AnalysisResult is the raw output an Analyzer produces for an entry, before
// it is validated and persisted as a versioned Analysis.
type AnalysisResult struct {
	Category    string
	Explanation string
	Confidence  float64
	Uncertainty string
}

// Validate normalizes and checks analyzer output, returning a wrapped
// ErrValidation on failure. It must be called before storage so invalid or
// unbounded AI output never reaches the database.
func (r *AnalysisResult) Validate() error {
	r.Category = strings.TrimSpace(r.Category)
	r.Explanation = strings.TrimSpace(r.Explanation)
	r.Uncertainty = strings.TrimSpace(r.Uncertainty)

	if r.Category == "" {
		return errWrap("category is required")
	}
	if len(r.Category) > 100 {
		return errWrap("category exceeds maximum length")
	}
	if r.Explanation == "" {
		return errWrap("explanation is required")
	}
	if len(r.Explanation) > maxExplanationLen {
		return errWrap("explanation exceeds maximum length")
	}
	if r.Confidence < 0 || r.Confidence > 1 {
		return errWrap("confidence must be between 0 and 1")
	}
	if len(r.Uncertainty) > maxUncertaintyLen {
		return errWrap("uncertainty exceeds maximum length")
	}
	return nil
}

// Analyzer produces AI-style metadata for a learning entry. Implementations
// live outside the domain (e.g. a rule-based analyzer for local development or,
// later, an external AI provider). The domain depends only on this interface.
type Analyzer interface {
	// Name identifies the analyzer that produced a result (stored for audit).
	Name() string
	// Analyze inspects the entry's original data and returns proposed metadata.
	Analyze(ctx context.Context, entry *Entry) (AnalysisResult, error)
}

// AnalysisRepository is the persistence boundary for entry analyses.
type AnalysisRepository interface {
	// Create appends a new analysis for entryID, assigning the next version.
	// Returns ErrNotFound if the entry does not exist.
	Create(ctx context.Context, entryID int64, result AnalysisResult, analyzer string) (*Analysis, error)
	// ListByEntry returns all analyses for entryID, oldest version first.
	ListByEntry(ctx context.Context, entryID int64) ([]*Analysis, error)
}
