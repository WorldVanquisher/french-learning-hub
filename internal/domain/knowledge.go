package domain

import (
	"context"
	"errors"
	"strings"
	"time"
)

// ErrExtractorDisabled is returned when a knowledge-extraction run is requested
// but no extractor is configured (EXTRACTOR_PROVIDER=disabled, the default). It
// is distinct from ErrProviderUnavailable (a configured provider that failed):
// the feature is simply switched off, so the transport layer reports it as a
// service-unavailable condition rather than a bad-gateway one, and never silently
// falls back to another provider.
var ErrExtractorDisabled = errors.New("knowledge extractor disabled")

// KnowledgeKindVersion identifies the dedicated knowledge-unit vocabulary this
// milestone uses. It is deliberately separate from TaxonomyVersion (the
// interaction-classification taxonomy): a knowledge unit answers "what learning
// objective arose here", which is a different question from "what kind of
// interaction was this". The version is part of extractor provenance.
const KnowledgeKindVersion = "fr_l2_knowledge_v1"

// Field bounds for a knowledge unit. A unit is meant to be small and reviewable,
// so canonical is a short label and statement is a concise knowledge statement,
// not a long explanation.
const (
	maxCanonicalLen = 200
	maxStatementLen = 2000
	maxExampleLen   = 2000
)

// KnowledgeKind is the category of a knowledge unit. The v1 vocabulary is fixed
// and small; it is not the interaction taxonomy (Category / fr_l2_taxonomy_v1).
type KnowledgeKind string

const (
	// KindVocabulary is a word, meaning, collocation, or lexical fact.
	KindVocabulary KnowledgeKind = "vocabulary"
	// KindGrammar is a structural rule (word order, negation, agreement rules).
	KindGrammar KnowledgeKind = "grammar"
	// KindMorphology is an inflectional fact (conjugation, gender, number).
	KindMorphology KnowledgeKind = "morphology"
	// KindOrthography is spelling, accents, apostrophes, capitalization.
	KindOrthography KnowledgeKind = "orthography"
	// KindPronunciation is a phonological fact (liaison, sounds, IPA).
	KindPronunciation KnowledgeKind = "pronunciation"
	// KindUsage is register, appropriateness, or contextual usage.
	KindUsage KnowledgeKind = "usage"
	// KindExpression is a fixed expression, idiom, or set phrase.
	KindExpression KnowledgeKind = "expression"
)

// knowledgeKinds is the membership/order set for validation and schema enums.
var knowledgeKinds = []KnowledgeKind{
	KindVocabulary,
	KindGrammar,
	KindMorphology,
	KindOrthography,
	KindPronunciation,
	KindUsage,
	KindExpression,
}

// KnowledgeKinds returns the v1 kinds in a stable order. It is the single source
// of truth for callers that enumerate them (e.g. building the extractor's output
// schema enum), so the list is never duplicated.
func KnowledgeKinds() []KnowledgeKind {
	out := make([]KnowledgeKind, len(knowledgeKinds))
	copy(out, knowledgeKinds)
	return out
}

// KnowledgeKindStrings returns the v1 kinds as plain strings, for building a
// JSON-schema enum without duplicating the vocabulary.
func KnowledgeKindStrings() []string {
	out := make([]string, len(knowledgeKinds))
	for i, k := range knowledgeKinds {
		out[i] = string(k)
	}
	return out
}

// ValidKnowledgeKind reports whether k is a known v1 kind.
func ValidKnowledgeKind(k KnowledgeKind) bool {
	for _, v := range knowledgeKinds {
		if v == k {
			return true
		}
	}
	return false
}

// NormalizeCanonical produces the comparison key used for exact-duplicate
// detection: trimmed, lowercased, with internal whitespace runs collapsed to a
// single space. Accents are deliberately preserved — French meaning depends on
// them (e.g. "a" vs "à", "ou" vs "où"), so stripping them would merge distinct
// objectives. This is a plain textual normalization; it does no stemming,
// lemmatization, or semantic comparison.
func NormalizeCanonical(s string) string {
	return strings.Join(strings.Fields(strings.ToLower(s)), " ")
}

// ExtractedUnit is one knowledge unit as produced by an extractor, before it is
// persisted (no database identity or ordinal yet). It is the smallest useful
// independently reviewable learning objective, not the smallest linguistic
// token: "vouloir — présent de l'indicatif" is normally one unit, not six forms.
type ExtractedUnit struct {
	Kind       KnowledgeKind
	Canonical  string
	Statement  string
	Example    *string
	Confidence float64
}

// Validate normalizes and checks a single extracted unit, returning a wrapped
// ErrValidation on failure. It trims fields and enforces bounds; it performs no
// silent repair beyond trimming surrounding whitespace. Confidence is the
// extractor's heuristic confidence that this is a genuine learning objective
// (not a calibrated mastery probability), so it is only range-checked to [0, 1].
func (u *ExtractedUnit) Validate() error {
	if !ValidKnowledgeKind(u.Kind) {
		return errWrap("kind must be one of the " + KnowledgeKindVersion + " knowledge kinds")
	}

	u.Canonical = strings.TrimSpace(u.Canonical)
	if u.Canonical == "" {
		return errWrap("canonical is required")
	}
	if len(u.Canonical) > maxCanonicalLen {
		return errWrap("canonical exceeds maximum length")
	}

	u.Statement = strings.TrimSpace(u.Statement)
	if u.Statement == "" {
		return errWrap("statement is required")
	}
	if len(u.Statement) > maxStatementLen {
		return errWrap("statement exceeds maximum length")
	}

	u.Example = trimOptional(u.Example)
	if u.Example != nil && len(*u.Example) > maxExampleLen {
		return errWrap("example exceeds maximum length")
	}

	if u.Confidence < 0 || u.Confidence > 1 {
		return errWrap("confidence must be between 0 and 1")
	}
	return nil
}

// ExtractionResult is the full set of units an extractor produced for one
// source. Zero units is a valid result: not every interaction yields a durable
// learning objective, and the extractor is instructed never to manufacture units
// merely to avoid an empty result.
type ExtractionResult struct {
	Units []ExtractedUnit
}

// Validate normalizes and checks every unit and rejects exact duplicates within
// the result. It returns a wrapped ErrValidation on the first failure.
//
// Exact-duplicate policy (documented, deterministic, auditable): two units are
// exact duplicates when their Kind and normalized Canonical, Statement, and
// Example all match. Such a result is rejected rather than silently de-duplicated
// so the extractor's output is never quietly rewritten before storage. (This is
// distinct from the admission ruleset's looser duplicate rule, which only
// compares kind + normalized canonical across genuinely different units and
// suppresses rather than rejects.)
func (r *ExtractionResult) Validate() error {
	seen := make(map[string]struct{}, len(r.Units))
	for i := range r.Units {
		if err := r.Units[i].Validate(); err != nil {
			return err
		}
		u := &r.Units[i]
		example := ""
		if u.Example != nil {
			example = NormalizeCanonical(*u.Example)
		}
		key := string(u.Kind) + "\x00" + NormalizeCanonical(u.Canonical) +
			"\x00" + NormalizeCanonical(u.Statement) + "\x00" + example
		if _, dup := seen[key]; dup {
			return errWrap("duplicate knowledge unit in extraction result")
		}
		seen[key] = struct{}{}
	}
	return nil
}

// ExtractionSource is the immutable input handed to an Extractor. It carries BOTH
// the original learning entry and the current effective interpretation, so the
// extractor sees what the learner actually wrote and how it is currently
// understood. Provenance fields record exactly which analysis and feedback the
// effective interpretation came from; they are persisted with the extraction so
// staleness can later be derived by comparison (never stored as a mutable flag).
type ExtractionSource struct {
	EntryID         int64
	OriginalInput   string
	OriginalContext string

	// Effective interpretation to extract from. Category/Explanation are the
	// current effective values (the corrected values when the analysis was
	// corrected, otherwise the original analysis values).
	EffectiveCategory    string
	EffectiveExplanation string

	// Provenance of the effective interpretation used.
	SourceAnalysisID int64
	SourceFeedbackID *int64
	Resolution       Resolution
}

// Extractor converts an extraction source into zero or more knowledge units. The
// interface is intentionally small and free of any HTTP/provider types, so
// implementations (a real OpenAI extractor, test fakes) are interchangeable.
type Extractor interface {
	// Name returns stable provenance identifying provider, model, and schema
	// version, e.g. "openai:gpt-4o-mini:knowledge_extraction_v1".
	Name() string
	// Extract returns the validated units for source. An empty result is valid.
	Extract(ctx context.Context, source ExtractionSource) (ExtractionResult, error)
}

// KnowledgeUnit is a persisted knowledge unit belonging to one extraction. Its
// Ordinal is assigned deterministically from the extractor's output order.
// Canonical is a stable, concise human label; it is NOT a database identity and
// carries no global uniqueness constraint.
type KnowledgeUnit struct {
	ID           int64
	ExtractionID int64
	Ordinal      int
	Kind         KnowledgeKind
	Canonical    string
	Statement    string
	Example      *string
	Confidence   float64
	CreatedAt    time.Time
}

// KnowledgeExtraction is an immutable, per-entry versioned record of one
// extraction run. It records the exact effective-analysis provenance that was
// used (SourceAnalysisID, SourceFeedbackID). A later analysis or feedback never
// mutates an existing extraction; re-running extraction appends a new version.
// No staleness is stored and none is computed here: this provenance is merely
// sufficient to derive staleness later by comparing it against the entry's
// current effective interpretation.
type KnowledgeExtraction struct {
	ID               int64
	EntryID          int64
	Version          int64
	SourceAnalysisID int64
	SourceFeedbackID *int64
	Extractor        string
	CreatedAt        time.Time
}

// KnowledgeExtractionRepository is the persistence boundary for extractions and
// their units. Implementations live in the storage layer and keep all SQL there.
type KnowledgeExtractionRepository interface {
	// Create persists one extraction, all of its units, and the initial machine
	// admission recommendation for each unit, in a single transaction. It assigns
	// the next per-entry version. Either everything commits or nothing does.
	Create(ctx context.Context, in NewExtractionInput) (*ExtractionView, error)
	// ListByEntry returns every extraction for an entry (each with its units and
	// admission state), newest version first. Returns ErrNotFound if the entry
	// does not exist.
	ListByEntry(ctx context.Context, entryID int64) ([]*ExtractionView, error)
	// GetByID returns one extraction with its units and admission state, or
	// ErrNotFound.
	GetByID(ctx context.Context, extractionID int64) (*ExtractionView, error)
}

// NewExtractionInput is the validated bundle the service hands to the repository
// to persist atomically. Recommendations is aligned with Units by index: the
// machine admission recommendation for Units[i] is Recommendations[i].
type NewExtractionInput struct {
	EntryID          int64
	SourceAnalysisID int64
	SourceFeedbackID *int64
	Extractor        string
	Units            []ExtractedUnit
	Recommendations  []AdmissionRecommendation
}

// ExtractionView is the read model for one extraction together with its units and
// each unit's admission state. It is assembled by the repository from the stored
// rows; it is not itself a table.
type ExtractionView struct {
	Extraction KnowledgeExtraction
	Units      []KnowledgeUnitView
}

// KnowledgeUnitView is one unit plus its resolved admission state (machine
// recommendation, latest human override if any, and effective state).
type KnowledgeUnitView struct {
	Unit      KnowledgeUnit
	Admission AdmissionState
}
