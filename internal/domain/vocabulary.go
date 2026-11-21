package domain

import (
	"context"
	"errors"
	"time"
)

// Vocabulary (Workbooks, migration 022): the learner's private saved terms.
// A saved term is a bookmark on a durable Knowledge Concept, never on text, so
// two Concepts with the same wording stay two terms and a repeat save of the
// same Concept is the same term. Each save may attach one source example: an
// approved unit currently supporting that Concept, recorded with its learner
// record and its extraction (the source revision) at the time of saving.
// History is append-only; removing a term records a decision and keeps every
// example, the Concept, its units and any review history.

// VocabularyVersion names the read contract of GET /vocabulary.
const VocabularyVersion = "vocabulary_v1"

// VocabularyMark is the learner's current decision on one Concept.
type VocabularyMark struct {
	ConceptID int64
	Saved     bool
	At        time.Time // when this decision was recorded
	FirstAt   time.Time // the first save of this Concept
}

// VocabularyExample is one source example attached to a saved Concept.
type VocabularyExample struct {
	ID                int64
	ConceptID         int64
	UnitID            int64
	EntryID           int64
	ExtractionID      int64
	ExtractionVersion int64
	CreatedAt         time.Time
}

// Reasons a Concept or unit cannot be saved (409 with this code).
const (
	VocabularyConceptRetired    = "concept_retired"
	VocabularyNotVocabulary     = "not_vocabulary"
	VocabularyUnitNotSupporting = "unit_not_supporting"
)

// ErrVocabularyNotSavable is returned with one of the reasons above.
var ErrVocabularyNotSavable = errors.New("not savable as vocabulary")

// VocabularyNotSavableError carries the reason code.
type VocabularyNotSavableError struct{ Reason string }

func (e *VocabularyNotSavableError) Error() string { return "not savable as vocabulary: " + e.Reason }
func (e *VocabularyNotSavableError) Unwrap() error { return ErrVocabularyNotSavable }

// VocabularyRepository stores the marks and examples (append-only).
type VocabularyRepository interface {
	// Save records a save when the Concept is not saved now, and attaches the
	// example when that (Concept, unit) pair has none: one write transaction,
	// and a repeated call changes nothing.
	Save(ctx context.Context, ex VocabularyExample, now time.Time) (mark VocabularyMark, saved bool, exampleAdded bool, err error)
	// Remove records a removal when the Concept is saved now. ErrNotFound when
	// the Concept was never saved; a second removal changes nothing.
	Remove(ctx context.Context, conceptID int64, now time.Time) (VocabularyMark, bool, error)
	// Marks returns the current decision per Concept ever saved.
	Marks(ctx context.Context) (map[int64]VocabularyMark, error)
	// Examples returns the examples of the given Concepts, oldest first.
	Examples(ctx context.Context, conceptIDs []int64) (map[int64][]VocabularyExample, error)
}
