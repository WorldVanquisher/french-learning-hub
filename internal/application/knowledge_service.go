package application

import (
	"context"
	"fmt"

	"french-learning-app/internal/domain"
)

// KnowledgeService coordinates knowledge extraction and admission. It builds the
// extraction source from BOTH the immutable original entry and its current
// effective interpretation, enforces explicit eligibility, runs the configured
// extractor, applies the fixed knowledge_admission_v1 ruleset, and persists the
// extraction, its units, and their machine recommendations atomically. It also
// records append-only human admission overrides. It never mutates the original
// entry, analysis, or feedback, and never auto-runs extraction as a side effect
// of another workflow.
type KnowledgeService struct {
	entries     domain.Repository
	analyses    domain.AnalysisRepository
	feedback    domain.FeedbackRepository
	extractions domain.KnowledgeExtractionRepository
	overrides   domain.AdmissionOverrideRepository
	// extractor may be nil when EXTRACTOR_PROVIDER=disabled. Read operations still
	// work; only Extract reports the feature as unavailable.
	extractor domain.Extractor
}

// NewKnowledgeService wires the service to its repositories and extractor. A nil
// extractor means extraction is disabled; the read paths remain fully functional.
func NewKnowledgeService(
	entries domain.Repository,
	analyses domain.AnalysisRepository,
	feedback domain.FeedbackRepository,
	extractions domain.KnowledgeExtractionRepository,
	overrides domain.AdmissionOverrideRepository,
	extractor domain.Extractor,
) *KnowledgeService {
	return &KnowledgeService{
		entries:     entries,
		analyses:    analyses,
		feedback:    feedback,
		extractions: extractions,
		overrides:   overrides,
		extractor:   extractor,
	}
}

// Extract runs a new knowledge extraction for one entry and persists it as a new
// per-entry version. The flow is: load the entry, derive its current effective
// interpretation, enforce eligibility, run the extractor over the combined
// source, validate the result, apply the admission ruleset, and persist
// everything in one atomic transaction.
//
// Errors:
//   - domain.ErrExtractorDisabled when no extractor is configured.
//   - domain.ErrNotFound when the entry does not exist.
//   - domain.ErrNotEligible when the entry is unanalyzed or its current analysis
//     is rejected.
//   - a wrapped provider error (timeout/unavailable) on extractor failure.
//   - a wrapped domain.ErrValidation when the extractor returns invalid units.
func (s *KnowledgeService) Extract(ctx context.Context, entryID int64) (*domain.ExtractionView, error) {
	if s.extractor == nil {
		return nil, domain.ErrExtractorDisabled
	}

	entry, err := s.entries.GetByID(ctx, entryID)
	if err != nil {
		return nil, err // includes domain.ErrNotFound
	}

	source, err := s.buildSource(ctx, entry)
	if err != nil {
		return nil, err // includes domain.ErrNotEligible
	}

	result, err := s.extractor.Extract(ctx, source)
	if err != nil {
		return nil, fmt.Errorf("extract knowledge: %w", err)
	}
	// Validate again before storage; the extractor validates too, but the service
	// is the authority that data reaching the repository is well-formed.
	if err := result.Validate(); err != nil {
		return nil, err // wrapped domain.ErrValidation
	}

	// Apply the fixed admission ruleset in output order, one recommendation per
	// unit, aligned by index. Zero units yields zero recommendations, which the
	// repository persists as an extraction with no units.
	recommendations := domain.ApplyAdmissionV1(result.Units)

	return s.extractions.Create(ctx, domain.NewExtractionInput{
		EntryID:          entryID,
		SourceAnalysisID: source.SourceAnalysisID,
		SourceFeedbackID: source.SourceFeedbackID,
		Extractor:        s.extractor.Name(),
		Units:            result.Units,
		Recommendations:  recommendations,
	})
}

// buildSource derives the extraction source for an entry: its original data plus
// the current effective interpretation of its latest analysis. It enforces
// eligibility explicitly. An entry with no analysis, or whose current analysis is
// rejected, is not eligible and yields domain.ErrNotEligible. For a corrected
// analysis the corrected (effective) values are used; for accepted/unreviewed the
// original analysis values are used. ResolveEffective encapsulates that choice.
func (s *KnowledgeService) buildSource(ctx context.Context, entry *domain.Entry) (domain.ExtractionSource, error) {
	analyses, err := s.analyses.ListByEntry(ctx, entry.ID)
	if err != nil {
		return domain.ExtractionSource{}, err
	}
	if len(analyses) == 0 {
		// Unanalyzed: nothing to interpret, so not eligible.
		return domain.ExtractionSource{}, fmt.Errorf("%w: entry has no analysis", domain.ErrNotEligible)
	}
	// ListByEntry is ordered oldest-first; the latest analysis is the last one.
	latest := analyses[len(analyses)-1]

	feedback, err := s.feedback.GetLatestByAnalysis(ctx, latest.ID)
	if err != nil {
		return domain.ExtractionSource{}, err
	}

	eff := domain.ResolveEffective(latest, feedback)
	if eff.Resolution == domain.ResolutionRejected || eff.Effective == nil {
		// A rejected current analysis has no effective interpretation to extract
		// from, so the entry is not eligible.
		return domain.ExtractionSource{}, fmt.Errorf("%w: current analysis is rejected", domain.ErrNotEligible)
	}

	return domain.ExtractionSource{
		EntryID:              entry.ID,
		OriginalInput:        entry.OriginalInput,
		OriginalContext:      entry.OriginalContext,
		EffectiveCategory:    eff.Effective.Category,
		EffectiveExplanation: eff.Effective.Explanation,
		SourceAnalysisID:     latest.ID,
		SourceFeedbackID:     eff.FeedbackID,
		Resolution:           eff.Resolution,
	}, nil
}

// ListExtractions returns every extraction for an entry, newest version first. It
// is read-only and performs no AI call. Returns domain.ErrNotFound if the entry
// does not exist.
func (s *KnowledgeService) ListExtractions(ctx context.Context, entryID int64) ([]*domain.ExtractionView, error) {
	return s.extractions.ListByEntry(ctx, entryID)
}

// GetExtraction returns one extraction with its units and admission state. It is
// read-only. Returns domain.ErrNotFound if the extraction does not exist.
func (s *KnowledgeService) GetExtraction(ctx context.Context, extractionID int64) (*domain.ExtractionView, error) {
	return s.extractions.GetByID(ctx, extractionID)
}

// AddOverride records an append-only human admission override for a unit. It
// validates the input and never mutates the machine recommendation. Returns
// domain.ErrNotFound if the unit does not exist and a wrapped domain.ErrValidation
// for invalid input.
func (s *KnowledgeService) AddOverride(ctx context.Context, unitID int64, in domain.NewAdmissionOverrideInput) (*domain.AdmissionOverride, error) {
	if err := in.Validate(); err != nil {
		return nil, err // wrapped domain.ErrValidation
	}
	return s.overrides.Create(ctx, unitID, in)
}

// GetAdmission returns the resolved admission state for a unit (machine
// recommendation + latest override + effective state). Read-only. Returns
// domain.ErrNotFound if the unit does not exist.
func (s *KnowledgeService) GetAdmission(ctx context.Context, unitID int64) (*domain.AdmissionState, error) {
	return s.overrides.GetAdmission(ctx, unitID)
}

// ListOverrides returns the full append-only override history for a unit, oldest
// first. Read-only. Returns domain.ErrNotFound if the unit does not exist.
func (s *KnowledgeService) ListOverrides(ctx context.Context, unitID int64) ([]*domain.AdmissionOverride, error) {
	return s.overrides.ListByUnit(ctx, unitID)
}
