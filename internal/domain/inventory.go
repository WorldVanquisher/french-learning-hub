package domain

import (
	"context"
	"strings"
	"time"
)

// LearningRecordState is the current inventory state of a learning entry: the
// combination of whether it has been analyzed and, if so, its latest feedback
// resolution. It is derived on read and never stored.
//
// It is deliberately a separate type from Resolution: "unanalyzed" describes the
// absence of any analysis for an entry, which is an inventory concept, not an
// effective-analysis resolution. The other four states correspond one-to-one to
// the Resolution values.
type LearningRecordState string

const (
	// LearningRecordUnanalyzed means the entry has no analysis at all.
	LearningRecordUnanalyzed LearningRecordState = "unanalyzed"
	// LearningRecordUnreviewed means the latest analysis has no feedback yet.
	LearningRecordUnreviewed LearningRecordState = "unreviewed"
	// LearningRecordAccepted means the latest feedback accepted the analysis.
	LearningRecordAccepted LearningRecordState = "accepted"
	// LearningRecordCorrected means the latest feedback corrected the analysis.
	LearningRecordCorrected LearningRecordState = "corrected"
	// LearningRecordRejected means the latest feedback rejected the analysis.
	LearningRecordRejected LearningRecordState = "rejected"
)

// learningRecordStates is the membership/order set for validation and summaries.
var learningRecordStates = []LearningRecordState{
	LearningRecordUnanalyzed,
	LearningRecordUnreviewed,
	LearningRecordAccepted,
	LearningRecordCorrected,
	LearningRecordRejected,
}

// LearningRecordStates returns the inventory states in a stable order. It is the
// single source of truth for callers that need to enumerate them (e.g. building
// a summary map with every key present).
func LearningRecordStates() []LearningRecordState {
	out := make([]LearningRecordState, len(learningRecordStates))
	copy(out, learningRecordStates)
	return out
}

// ValidLearningRecordState reports whether s is a known inventory state.
func ValidLearningRecordState(s LearningRecordState) bool {
	for _, v := range learningRecordStates {
		if v == s {
			return true
		}
	}
	return false
}

// StateFromResolution maps an effective-analysis Resolution onto the
// corresponding inventory state. It never returns LearningRecordUnanalyzed,
// which only applies when there is no analysis to resolve.
func StateFromResolution(r Resolution) LearningRecordState {
	switch r {
	case ResolutionUnreviewed:
		return LearningRecordUnreviewed
	case ResolutionAccepted:
		return LearningRecordAccepted
	case ResolutionCorrected:
		return LearningRecordCorrected
	case ResolutionRejected:
		return LearningRecordRejected
	default:
		return ""
	}
}

// LearningRecord is the read-model for one learning entry combined with its
// latest analysis and effective interpretation. It is a cross-entity projection
// derived on demand and never persisted; the original entry, analyses, and
// feedback are never modified to produce it.
//
// The analysis-related pointer fields are nil for an unanalyzed entry. Effective
// is nil for a rejected record (a rejected analysis has no current
// interpretation) as well as for an unanalyzed entry. Original is nil only for
// an unanalyzed entry.
type LearningRecord struct {
	EntryID         int64
	OriginalInput   string
	OriginalContext string
	EntryCreatedAt  time.Time

	// Latest-analysis metadata; nil when State is unanalyzed.
	AnalysisID        *int64
	AnalysisVersion   *int64
	Analyzer          *string
	Confidence        *float64
	Uncertainty       *string
	AnalysisCreatedAt *time.Time

	State LearningRecordState

	// Original is the latest analysis as stored (nil when unanalyzed).
	Original *AnalysisValues
	// Effective is the current interpretation (nil when unanalyzed or rejected).
	Effective *AnalysisValues
	// FeedbackID is the feedback that determined the state (nil when unanalyzed
	// or unreviewed).
	FeedbackID *int64
}

// LearningInventorySummary holds aggregate counts across all learning entries.
// Map keys use the shared taxonomy / state vocabularies. Every state key is
// always present (zero when none match); category and analyzer maps contain only
// observed keys.
type LearningInventorySummary struct {
	TotalEntries      int64
	AnalyzedEntries   int64
	UnanalyzedEntries int64

	ByState             map[LearningRecordState]int64
	ByEffectiveCategory map[Category]int64
	ByAnalyzer          map[string]int64
}

// LearningRecordQuery is a validated filter + pagination request for the
// inventory. A nil filter pointer means "no filter on that dimension".
type LearningRecordQuery struct {
	State         *LearningRecordState
	Category      *Category
	Analyzer      *string
	Limit         int
	BeforeEntryID *int64
}

// Normalize validates and normalizes the query in place, returning a wrapped
// ErrValidation on failure. Limit handling is normalizing, not rejecting: a
// non-positive limit becomes defaultLimit and a limit above maxLimit is clamped
// to maxLimit, so callers always get a bounded, sane page size. State and
// category filters are trimmed/lowercased before validation; the analyzer filter
// is trimmed but matched exactly (case-sensitive), since provenance strings are
// case-sensitive.
func (q *LearningRecordQuery) Normalize(defaultLimit, maxLimit int) error {
	if q.State != nil {
		normalized := LearningRecordState(strings.ToLower(strings.TrimSpace(string(*q.State))))
		if !ValidLearningRecordState(normalized) {
			return errWrap("state must be one of: unanalyzed, unreviewed, accepted, corrected, rejected")
		}
		q.State = &normalized
	}
	if q.Category != nil {
		normalized := strings.ToLower(strings.TrimSpace(*q.Category))
		if !ValidCategory(normalized) {
			return errWrap("category must be one of the " + TaxonomyVersion + " taxonomy values")
		}
		q.Category = &normalized
	}
	if q.Analyzer != nil {
		trimmed := strings.TrimSpace(*q.Analyzer)
		if trimmed == "" {
			q.Analyzer = nil
		} else {
			q.Analyzer = &trimmed
		}
	}
	if q.BeforeEntryID != nil && *q.BeforeEntryID <= 0 {
		return errWrap("before_entry_id must be a positive entry id")
	}
	if q.Limit <= 0 {
		q.Limit = defaultLimit
	}
	if q.Limit > maxLimit {
		q.Limit = maxLimit
	}
	return nil
}

// NewValidationError builds a wrapped ErrValidation carrying msg. It lets
// adapter layers (e.g. HTTP query-string parsing) produce the same validation
// error type the domain uses internally, so transport can map every validation
// failure to 400 through a single errors.Is(err, ErrValidation) check.
func NewValidationError(msg string) error {
	return errWrap(msg)
}

// InventoryRepository is the persistence boundary for the read-only learning
// inventory. Implementations live in the storage layer and keep all SQL there.
type InventoryRepository interface {
	// ListLearningRecords returns one record per learning entry matching q,
	// ordered by entry id descending. The query is expected to be already
	// normalized (bounded limit, validated filters).
	ListLearningRecords(ctx context.Context, q LearningRecordQuery) ([]*LearningRecord, error)
	// SummarizeLearningRecords returns aggregate counts across all entries.
	SummarizeLearningRecords(ctx context.Context) (*LearningInventorySummary, error)
}
