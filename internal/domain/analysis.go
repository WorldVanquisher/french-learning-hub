package domain

import (
	"context"
	"errors"
	"strings"
	"time"
)

// ErrProviderTimeout is returned when an external analyzer provider does not
// respond within its configured timeout (or the request context is canceled by
// a deadline). It maps to HTTP 504 at the transport boundary.
var ErrProviderTimeout = errors.New("analyzer provider timeout")

// ErrProviderUnavailable is returned when an external analyzer provider fails
// in a way that is not the caller's fault: network failure, an upstream HTTP
// error (401/403/429/5xx), or a structurally unusable response (malformed JSON,
// missing/refused/incomplete output). It maps to HTTP 502 at the transport
// boundary. Output that is well-formed but fails domain validation is reported
// as ErrValidation instead, not as this error.
var ErrProviderUnavailable = errors.New("analyzer provider unavailable")

// maxExplanationLen bounds a stored explanation.
const maxExplanationLen = 20000

// maxUncertaintyLen bounds the stored uncertainty note.
const maxUncertaintyLen = 5000

// TaxonomyVersion identifies the pedagogical category taxonomy every persisted
// analysis must use. It is a domain concept, not a provider detail: the database
// stores only these categories regardless of which analyzer produced them.
const TaxonomyVersion = "fr_l2_taxonomy_v1"

// Category is a pedagogical classification for a learning entry. Only the
// members of the fr_l2_taxonomy_v1 taxonomy below are valid.
type Category = string

// The fr_l2_taxonomy_v1 categories. Analyzers (rule-based or provider-backed)
// must map their output onto exactly these values before storage.
const (
	CategoryVocabulary    Category = "vocabulary"
	CategoryGrammar       Category = "grammar"
	CategoryMorphology    Category = "morphology"
	CategoryOrthography   Category = "orthography"
	CategoryPronunciation Category = "pronunciation"
	CategoryPragmatics    Category = "pragmatics"
	CategoryDiscourse     Category = "discourse"
	CategoryComprehension Category = "comprehension"
	CategoryTranslation   Category = "translation"
	CategoryMixed         Category = "mixed"
	CategoryOther         Category = "other"
)

// categorySet is the membership set used to validate categories.
var categorySet = map[Category]struct{}{
	CategoryVocabulary:    {},
	CategoryGrammar:       {},
	CategoryMorphology:    {},
	CategoryOrthography:   {},
	CategoryPronunciation: {},
	CategoryPragmatics:    {},
	CategoryDiscourse:     {},
	CategoryComprehension: {},
	CategoryTranslation:   {},
	CategoryMixed:         {},
	CategoryOther:         {},
}

// Categories returns the taxonomy in a stable order. It is the single source of
// truth for callers that need the list (e.g. an analyzer building a JSON-schema
// enum), so the taxonomy is never duplicated per provider.
func Categories() []Category {
	return []Category{
		CategoryVocabulary, CategoryGrammar, CategoryMorphology, CategoryOrthography,
		CategoryPronunciation, CategoryPragmatics, CategoryDiscourse, CategoryComprehension,
		CategoryTranslation, CategoryMixed, CategoryOther,
	}
}

// ValidCategory reports whether c is a member of the taxonomy.
func ValidCategory(c Category) bool {
	_, ok := categorySet[c]
	return ok
}

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
	// Normalize the category to the canonical lowercase taxonomy form before
	// checking membership, so "Grammar" or "  grammar " are accepted as grammar.
	r.Category = strings.ToLower(strings.TrimSpace(r.Category))
	r.Explanation = strings.TrimSpace(r.Explanation)
	r.Uncertainty = strings.TrimSpace(r.Uncertainty)

	if r.Category == "" {
		return errWrap("category is required")
	}
	if !ValidCategory(r.Category) {
		return errWrap("category must be one of the " + TaxonomyVersion + " taxonomy values")
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
