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

// Entry is a single French-learning record.
//
// The original user data (OriginalInput, OriginalContext) is the source of
// truth and must never be overwritten by AI-generated metadata. The AI fields
// are optional and editable.
type Entry struct {
	ID              int64
	OriginalInput   string
	OriginalContext string
	CreatedAt       time.Time
	UpdatedAt       time.Time

	// AI-generated / editable metadata. Nil pointers mean "not set".
	Category    *string
	Explanation *string
	Confidence  *float64
}

// NewEntryInput carries the fields a caller may supply when creating an entry.
// Only the original user data is accepted here; AI metadata is added later
// through a separate path so it can never replace the original record.
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
