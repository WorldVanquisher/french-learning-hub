// Package domain holds the core learning-record entities and the repository
// interface. It has no knowledge of HTTP, SQL, or AI providers.
package domain

import (
	"context"
	"errors"
	"strings"
	"time"
)

// ErrValidation is returned when input fails domain validation.
var ErrValidation = errors.New("validation error")

// ErrNotFound is returned when a requested entry does not exist.
var ErrNotFound = errors.New("entry not found")

// maxInputLen bounds a single field to protect storage and keep records sane.
const maxInputLen = 10000

// Entry is the learner-authored source record for one French-learning
// interaction. AI interpretation is not part of Entry: it lives exclusively in
// immutable, versioned Analysis records and their read projections.
type Entry struct {
	ID              int64
	OriginalInput   string
	OriginalContext string
	CreatedAt       time.Time
	UpdatedAt       time.Time
}

// NewEntryInput carries the fields a caller may supply when creating an entry.
// Only learner-authored source data is accepted here. AI interpretation is
// created separately through the versioned Analysis workflow.
type NewEntryInput struct {
	OriginalInput   string
	OriginalContext string
}

// Validate normalizes and checks the input, returning a wrapped ErrValidation
// on failure. It trims surrounding whitespace and enforces length bounds.
func (in *NewEntryInput) Validate() error {
	in.OriginalInput = strings.TrimSpace(in.OriginalInput)
	in.OriginalContext = strings.TrimSpace(in.OriginalContext)

	if in.OriginalInput == "" {
		return errWrap("original_input is required")
	}
	if len(in.OriginalInput) > maxInputLen {
		return errWrap("original_input exceeds maximum length")
	}
	if len(in.OriginalContext) > maxInputLen {
		return errWrap("original_context exceeds maximum length")
	}
	return nil
}

func errWrap(msg string) error {
	return errors.Join(ErrValidation, errors.New(msg))
}

// Repository is the persistence boundary for entries. Implementations live in
// the storage layer; callers depend only on this interface.
type Repository interface {
	Create(ctx context.Context, in NewEntryInput) (*Entry, error)
	GetByID(ctx context.Context, id int64) (*Entry, error)
	List(ctx context.Context, limit int) ([]*Entry, error)
}
