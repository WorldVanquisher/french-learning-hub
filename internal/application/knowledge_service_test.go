package application

import (
	"context"
	"errors"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

// ---- fakes ----

type fakeEntryRepo struct {
	entry *domain.Entry
	err   error
}

func (f *fakeEntryRepo) Create(context.Context, domain.NewEntryInput) (*domain.Entry, error) {
	return f.entry, f.err
}
func (f *fakeEntryRepo) GetByID(_ context.Context, id int64) (*domain.Entry, error) {
	if f.err != nil {
		return nil, f.err
	}
	return f.entry, nil
}
func (f *fakeEntryRepo) List(context.Context, int) ([]*domain.Entry, error) { return nil, nil }

type fakeAnalysisRepo struct {
	analyses []*domain.Analysis
	err      error
}

func (f *fakeAnalysisRepo) Create(context.Context, int64, domain.AnalysisResult, string) (*domain.Analysis, error) {
	return nil, nil
}
func (f *fakeAnalysisRepo) ListByEntry(context.Context, int64) ([]*domain.Analysis, error) {
	return f.analyses, f.err
}
func (f *fakeAnalysisRepo) GetByID(context.Context, int64) (*domain.Analysis, error) {
	return nil, nil
}

type fakeKFeedbackRepo struct {
	latest *domain.Feedback
	err    error
}

func (f *fakeKFeedbackRepo) Create(context.Context, int64, domain.NewFeedbackInput) (*domain.Feedback, error) {
	return nil, nil
}
func (f *fakeKFeedbackRepo) ListByAnalysis(context.Context, int64) ([]*domain.Feedback, error) {
	return nil, nil
}
func (f *fakeKFeedbackRepo) GetLatestByAnalysis(context.Context, int64) (*domain.Feedback, error) {
	return f.latest, f.err
}

type fakeExtractionRepo struct {
	gotInput *domain.NewExtractionInput
	view     *domain.ExtractionView
	err      error
}

func (f *fakeExtractionRepo) Create(_ context.Context, in domain.NewExtractionInput) (*domain.ExtractionView, error) {
	f.gotInput = &in
	if f.view != nil {
		return f.view, f.err
	}
	return &domain.ExtractionView{Extraction: domain.KnowledgeExtraction{ID: 1, EntryID: in.EntryID, Version: 1}}, f.err
}
func (f *fakeExtractionRepo) ListByEntry(context.Context, int64) ([]*domain.ExtractionView, error) {
	return nil, f.err
}
func (f *fakeExtractionRepo) GetByID(context.Context, int64) (*domain.ExtractionView, error) {
	return f.view, f.err
}

type fakeOverrideRepo struct{}

func (f *fakeOverrideRepo) Create(context.Context, int64, domain.NewAdmissionOverrideInput) (*domain.AdmissionOverride, error) {
	return &domain.AdmissionOverride{ID: 1}, nil
}
func (f *fakeOverrideRepo) ListByUnit(context.Context, int64) ([]*domain.AdmissionOverride, error) {
	return nil, nil
}
func (f *fakeOverrideRepo) GetAdmission(context.Context, int64) (*domain.AdmissionState, error) {
	return &domain.AdmissionState{}, nil
}

// fakeExtractor records the source it was handed and returns scripted results.
type fakeExtractor struct {
	gotSource domain.ExtractionSource
	result    domain.ExtractionResult
	err       error
}

func (f *fakeExtractor) Name() string { return "fake:test:knowledge_extraction_v1" }
func (f *fakeExtractor) Extract(_ context.Context, s domain.ExtractionSource) (domain.ExtractionResult, error) {
	f.gotSource = s
	return f.result, f.err
}

func analysis(id int64) *domain.Analysis {
	return &domain.Analysis{ID: id, EntryID: 1, Version: 1, Category: "grammar", Explanation: "orig", Confidence: 0.8}
}

func TestExtract_DisabledReturnsError(t *testing.T) {
	svc := NewKnowledgeService(&fakeEntryRepo{entry: &domain.Entry{ID: 1}}, &fakeAnalysisRepo{}, &fakeKFeedbackRepo{}, &fakeExtractionRepo{}, &fakeOverrideRepo{}, nil)
	_, err := svc.Extract(context.Background(), 1)
	if !errors.Is(err, domain.ErrExtractorDisabled) {
		t.Fatalf("expected ErrExtractorDisabled, got %v", err)
	}
}

func TestExtract_UnanalyzedNotEligible(t *testing.T) {
	svc := NewKnowledgeService(
		&fakeEntryRepo{entry: &domain.Entry{ID: 1}},
		&fakeAnalysisRepo{analyses: nil}, // no analysis
		&fakeKFeedbackRepo{},
		&fakeExtractionRepo{}, &fakeOverrideRepo{}, &fakeExtractor{},
	)
	_, err := svc.Extract(context.Background(), 1)
	if !errors.Is(err, domain.ErrNotEligible) {
		t.Fatalf("expected ErrNotEligible for unanalyzed entry, got %v", err)
	}
}

func TestExtract_RejectedNotEligible(t *testing.T) {
	svc := NewKnowledgeService(
		&fakeEntryRepo{entry: &domain.Entry{ID: 1}},
		&fakeAnalysisRepo{analyses: []*domain.Analysis{analysis(3)}},
		&fakeKFeedbackRepo{latest: &domain.Feedback{ID: 5, AnalysisID: 3, Status: domain.FeedbackRejected}},
		&fakeExtractionRepo{}, &fakeOverrideRepo{}, &fakeExtractor{},
	)
	_, err := svc.Extract(context.Background(), 1)
	if !errors.Is(err, domain.ErrNotEligible) {
		t.Fatalf("expected ErrNotEligible for rejected analysis, got %v", err)
	}
}

func TestExtract_AcceptedUsesOriginalEffectiveValues(t *testing.T) {
	ex := &fakeExtractor{}
	svc := NewKnowledgeService(
		&fakeEntryRepo{entry: &domain.Entry{ID: 1, OriginalInput: "Je veux"}},
		&fakeAnalysisRepo{analyses: []*domain.Analysis{analysis(3)}},
		&fakeKFeedbackRepo{latest: &domain.Feedback{ID: 5, AnalysisID: 3, Status: domain.FeedbackAccepted}},
		&fakeExtractionRepo{}, &fakeOverrideRepo{}, ex,
	)
	if _, err := svc.Extract(context.Background(), 1); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// Accepted -> effective equals the original analysis values, provenance
	// records both the analysis id and the feedback id.
	if ex.gotSource.EffectiveCategory != "grammar" || ex.gotSource.EffectiveExplanation != "orig" {
		t.Fatalf("expected original effective values, got %+v", ex.gotSource)
	}
	if ex.gotSource.SourceAnalysisID != 3 {
		t.Fatalf("source analysis id = %d, want 3", ex.gotSource.SourceAnalysisID)
	}
	if ex.gotSource.SourceFeedbackID == nil || *ex.gotSource.SourceFeedbackID != 5 {
		t.Fatalf("expected feedback provenance 5, got %v", ex.gotSource.SourceFeedbackID)
	}
}

func TestExtract_CorrectedUsesCorrectedEffectiveValues(t *testing.T) {
	ex := &fakeExtractor{}
	correctedCat := "vocabulary"
	correctedExp := "corrected explanation"
	svc := NewKnowledgeService(
		&fakeEntryRepo{entry: &domain.Entry{ID: 1}},
		&fakeAnalysisRepo{analyses: []*domain.Analysis{analysis(3)}},
		&fakeKFeedbackRepo{latest: &domain.Feedback{
			ID: 5, AnalysisID: 3, Status: domain.FeedbackCorrected,
			CorrectedCategory: &correctedCat, CorrectedExplanation: &correctedExp,
		}},
		&fakeExtractionRepo{}, &fakeOverrideRepo{}, ex,
	)
	if _, err := svc.Extract(context.Background(), 1); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if ex.gotSource.EffectiveCategory != "vocabulary" || ex.gotSource.EffectiveExplanation != "corrected explanation" {
		t.Fatalf("corrected extraction should use corrected effective values, got %+v", ex.gotSource)
	}
}

func TestExtract_UnreviewedIsEligible(t *testing.T) {
	ex := &fakeExtractor{}
	svc := NewKnowledgeService(
		&fakeEntryRepo{entry: &domain.Entry{ID: 1}},
		&fakeAnalysisRepo{analyses: []*domain.Analysis{analysis(3)}},
		&fakeKFeedbackRepo{latest: nil}, // no feedback -> unreviewed
		&fakeExtractionRepo{}, &fakeOverrideRepo{}, ex,
	)
	if _, err := svc.Extract(context.Background(), 1); err != nil {
		t.Fatalf("unreviewed should be eligible, got %v", err)
	}
	if ex.gotSource.SourceFeedbackID != nil {
		t.Fatalf("unreviewed extraction should have no feedback provenance")
	}
}

func TestExtract_AppliesRulesetAndPersists(t *testing.T) {
	repo := &fakeExtractionRepo{}
	ex := &fakeExtractor{result: domain.ExtractionResult{Units: []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "a", Statement: "s", Confidence: 0.9},
		{Kind: domain.KindGrammar, Canonical: "a", Statement: "s2", Confidence: 0.9}, // duplicate
	}}}
	svc := NewKnowledgeService(
		&fakeEntryRepo{entry: &domain.Entry{ID: 1}},
		&fakeAnalysisRepo{analyses: []*domain.Analysis{analysis(3)}},
		&fakeKFeedbackRepo{latest: &domain.Feedback{ID: 5, AnalysisID: 3, Status: domain.FeedbackAccepted}},
		repo, &fakeOverrideRepo{}, ex,
	)
	if _, err := svc.Extract(context.Background(), 1); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if repo.gotInput == nil {
		t.Fatal("expected persistence to be called")
	}
	if len(repo.gotInput.Recommendations) != 2 {
		t.Fatalf("expected 2 recommendations, got %d", len(repo.gotInput.Recommendations))
	}
	// The ruleset should have flagged the second unit as an exact duplicate.
	if repo.gotInput.Recommendations[1].State != domain.AdmissionSuppressed {
		t.Fatalf("expected duplicate suppressed, got %+v", repo.gotInput.Recommendations[1])
	}
	if repo.gotInput.Extractor != ex.Name() {
		t.Fatalf("extractor provenance = %q, want %q", repo.gotInput.Extractor, ex.Name())
	}
}

func TestExtract_ProviderErrorPropagates(t *testing.T) {
	ex := &fakeExtractor{err: domain.ErrProviderTimeout}
	svc := NewKnowledgeService(
		&fakeEntryRepo{entry: &domain.Entry{ID: 1}},
		&fakeAnalysisRepo{analyses: []*domain.Analysis{analysis(3)}},
		&fakeKFeedbackRepo{latest: &domain.Feedback{ID: 5, AnalysisID: 3, Status: domain.FeedbackAccepted}},
		&fakeExtractionRepo{}, &fakeOverrideRepo{}, ex,
	)
	_, err := svc.Extract(context.Background(), 1)
	if !errors.Is(err, domain.ErrProviderTimeout) {
		t.Fatalf("expected ErrProviderTimeout to propagate, got %v", err)
	}
}

func TestExtract_EntryNotFound(t *testing.T) {
	svc := NewKnowledgeService(
		&fakeEntryRepo{err: domain.ErrNotFound},
		&fakeAnalysisRepo{}, &fakeKFeedbackRepo{},
		&fakeExtractionRepo{}, &fakeOverrideRepo{}, &fakeExtractor{},
	)
	_, err := svc.Extract(context.Background(), 99)
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestAddOverride_ValidatesInput(t *testing.T) {
	svc := NewKnowledgeService(&fakeEntryRepo{}, &fakeAnalysisRepo{}, &fakeKFeedbackRepo{}, &fakeExtractionRepo{}, &fakeOverrideRepo{}, &fakeExtractor{})
	// Suppressed without a reason is invalid and must not reach the repo.
	_, err := svc.AddOverride(context.Background(), 1, domain.NewAdmissionOverrideInput{Decision: domain.HumanAdmitSuppressed})
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation, got %v", err)
	}
}

// guard against unused import of time when the fakes evolve.
var _ = time.Now
