package domain

import (
	"context"
	"errors"
	"strings"
	"time"
)

// ErrConflict is returned when a capture is re-submitted under an existing
// capture_id but with different meaningful content (a different canonical
// fingerprint). It maps to HTTP 409 at the transport boundary. The existing
// capture is never modified.
var ErrConflict = errors.New("capture conflict")

// CaptureSchemaV1 is the only structured-capture schema supported in this
// milestone. It is defined as a constant so the version string is never
// scattered through the codebase.
const CaptureSchemaV1 = "learning_capture_v1"

// maxCaptureIDLen bounds a client-generated idempotency identifier. Capture IDs
// are portable, conservative strings (UUIDs, or stable ids like
// "manual-2026-08-04-001"), not free-form text.
const maxCaptureIDLen = 200

// maxDiscussionSummaryLen bounds the optional discussion summary. It is chosen
// consistently with the other bounded free-form domain fields (user_note is
// 5000; uncertainty is 5000), sitting in the documented 2000-8000 range.
const maxDiscussionSummaryLen = 5000

// CaptureSource is a small typed vocabulary describing where a capture was
// prepared. It is metadata only and must never automatically determine trust:
// an imported analysis is always a candidate that existing feedback governs.
type CaptureSource string

const (
	// CaptureSourceChatGPTWeb marks a capture prepared via the ChatGPT website.
	CaptureSourceChatGPTWeb CaptureSource = "chatgpt-web"
	// CaptureSourceManual marks a capture entered by hand.
	CaptureSourceManual CaptureSource = "manual"
)

// captureSourceSet is the membership set used to validate sources. Unrestricted
// free-form sources are intentionally not accepted in this milestone.
var captureSourceSet = map[CaptureSource]struct{}{
	CaptureSourceChatGPTWeb: {},
	CaptureSourceManual:     {},
}

// ValidCaptureSource reports whether s is a known capture source.
func ValidCaptureSource(s CaptureSource) bool {
	_, ok := captureSourceSet[s]
	return ok
}

// ImportedAnalysisProvenance builds the server-side analyzer provenance for an
// imported analysis. It is the single source of truth for the format
// "imported:<source>:<schema_version>" (e.g.
// "imported:chatgpt-web:learning_capture_v1"). Clients never provide or override
// this value.
func ImportedAnalysisProvenance(source CaptureSource) string {
	return "imported:" + string(source) + ":" + CaptureSchemaV1
}

// captureIDPattern reports whether id uses the conservative portable character
// set: it must start with an alphanumeric and otherwise contain only
// [A-Za-z0-9._:-]. This admits UUIDs and stable manual ids while rejecting
// whitespace, control characters, and surprising punctuation. It is applied
// after trimming and does not itself alter the id.
func captureIDValid(id string) bool {
	if id == "" {
		return false
	}
	for i := 0; i < len(id); i++ {
		c := id[i]
		alnum := (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')
		if i == 0 {
			if !alnum {
				return false
			}
			continue
		}
		if !alnum && c != '.' && c != '_' && c != ':' && c != '-' {
			return false
		}
	}
	return true
}

// NormalizeCaptureID trims and validates a capture id for lookups, applying the
// same rules capture creation uses (trim only, bounded length, portable
// charset). It returns the normalized id or a wrapped ErrValidation. Keeping the
// rule here means creation and lookup can never diverge.
func NormalizeCaptureID(id string) (string, error) {
	id = strings.TrimSpace(id)
	if id == "" {
		return "", errWrap("capture_id is required")
	}
	if len(id) > maxCaptureIDLen {
		return "", errWrap("capture_id exceeds maximum length")
	}
	if !captureIDValid(id) {
		return "", errWrap("capture_id must match [A-Za-z0-9][A-Za-z0-9._:-]*")
	}
	return id, nil
}

// ImportedAnalysisInput is the optional analysis a capture may carry. It is a
// candidate analysis produced during the discussion, converted into the existing
// AnalysisResult and validated with the existing analysis validation — no second
// taxonomy or second validator is introduced.
type ImportedAnalysisInput struct {
	Category    string
	Explanation string
	Confidence  float64
	Uncertainty string
}

// NewLearningCaptureInput is the raw, unvalidated structured capture the
// transport layer decodes. Validation and normalization happen in Validate.
type NewLearningCaptureInput struct {
	SchemaVersion     string
	CaptureID         string
	Source            CaptureSource
	OriginalInput     string
	OriginalContext   string
	Analysis          *ImportedAnalysisInput
	DiscussionSummary string
}

// Validate normalizes the capture in place and checks every field, returning a
// wrapped ErrValidation on failure. On success the input's fields are fully
// normalized (trimmed capture id / summary, validated source and schema, entry
// data normalized by the reused entry validation, and any analysis normalized by
// the reused analysis validation). If the optional analysis fails validation the
// whole capture fails and nothing should be stored.
//
// Note on the schema version: an unsupported schema version is reported through
// a dedicated sentinel so the transport layer can map it to 422 distinctly if it
// wishes; it is still an ErrValidation for uniform handling.
func (in *NewLearningCaptureInput) Validate() error {
	// Schema version: exact match after trimming.
	if strings.TrimSpace(in.SchemaVersion) != CaptureSchemaV1 {
		return errWrap("schema_version must be " + CaptureSchemaV1)
	}
	in.SchemaVersion = CaptureSchemaV1

	// Capture ID: trim only, then validate against the portable charset. Reuses
	// NormalizeCaptureID so creation and lookup share one rule.
	captureID, err := NormalizeCaptureID(in.CaptureID)
	if err != nil {
		return err
	}
	in.CaptureID = captureID

	// Source: typed vocabulary only.
	in.Source = CaptureSource(strings.TrimSpace(string(in.Source)))
	if !ValidCaptureSource(in.Source) {
		return errWrap("source must be one of: chatgpt-web, manual")
	}

	// Original input/context: reuse the entry validation and its limits so the
	// capture never maintains a separate, incompatible set of bounds.
	entryInput := NewEntryInput{OriginalInput: in.OriginalInput, OriginalContext: in.OriginalContext}
	if err := entryInput.Validate(); err != nil {
		return err
	}
	in.OriginalInput = entryInput.OriginalInput
	in.OriginalContext = entryInput.OriginalContext

	// Discussion summary: optional, trimmed, bounded plain text.
	in.DiscussionSummary = strings.TrimSpace(in.DiscussionSummary)
	if len(in.DiscussionSummary) > maxDiscussionSummaryLen {
		return errWrap("discussion_summary exceeds maximum length")
	}

	// Optional analysis: reuse AnalysisResult.Validate (taxonomy, bounds, [0,1]).
	if in.Analysis != nil {
		result := AnalysisResult{
			Category:    in.Analysis.Category,
			Explanation: in.Analysis.Explanation,
			Confidence:  in.Analysis.Confidence,
			Uncertainty: in.Analysis.Uncertainty,
		}
		if err := result.Validate(); err != nil {
			return err
		}
		// Write back the normalized values.
		in.Analysis.Category = result.Category
		in.Analysis.Explanation = result.Explanation
		in.Analysis.Confidence = result.Confidence
		in.Analysis.Uncertainty = result.Uncertainty
	}

	return nil
}

// AsAnalysisResult converts the imported analysis into the shared AnalysisResult
// so persistence reuses exactly the same type the analyzer path produces. It
// must only be called after Validate.
func (a *ImportedAnalysisInput) AsAnalysisResult() AnalysisResult {
	return AnalysisResult{
		Category:    a.Category,
		Explanation: a.Explanation,
		Confidence:  a.Confidence,
		Uncertainty: a.Uncertainty,
	}
}

// PreparedLearningCapture is a fully validated, normalized capture handed to the
// repository. The repository does no domain validation; it enforces storage
// invariants (uniqueness, atomicity) and performs the transaction. Provenance
// and the fingerprint are computed once, in the application layer, and passed in.
type PreparedLearningCapture struct {
	CaptureID          string
	Source             CaptureSource
	SchemaVersion      string
	OriginalInput      string
	OriginalContext    string
	DiscussionSummary  string
	ContentFingerprint string

	// Analysis is the imported version-1 analysis to create, or nil. Provenance
	// is the server-constructed value; the repository stores it verbatim.
	Analysis           *AnalysisResult
	AnalyzerProvenance string
}

// LearningCapture is the stored import receipt. It references the entry and
// optional analysis rather than duplicating their content. The content
// fingerprint is deliberately not part of this struct's public exposure path: it
// is internal and never returned to clients.
type LearningCapture struct {
	ID                int64
	CaptureID         string
	EntryID           int64
	AnalysisID        *int64
	Source            CaptureSource
	SchemaVersion     string
	DiscussionSummary string
	CreatedAt         time.Time
}

// LearningCaptureResult is the outcome of a capture submission. Created is true
// for a newly stored capture and false for an idempotent replay.
type LearningCaptureResult struct {
	CaptureID  string
	EntryID    int64
	AnalysisID *int64
	Created    bool
}

// CaptureRepository is the persistence boundary for structured captures. It
// receives already validated and normalized values and performs the atomic
// creation (entry + optional analysis + receipt) in a single transaction, while
// enforcing idempotency and conflict semantics on capture_id.
type CaptureRepository interface {
	// Create atomically persists a new capture, or resolves a repeat submission.
	// A previously unseen capture_id creates the entry, optional version-1
	// analysis, and receipt (Created=true). A repeat with the same content
	// fingerprint returns the existing result (Created=false). A repeat with a
	// different fingerprint returns ErrConflict without modifying anything.
	Create(ctx context.Context, in PreparedLearningCapture) (LearningCaptureResult, error)
	// GetByCaptureID returns the stored receipt for captureID, or ErrNotFound.
	GetByCaptureID(ctx context.Context, captureID string) (*LearningCapture, error)
}
