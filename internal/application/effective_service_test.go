package application

import (
	"context"
	"errors"
	"testing"

	"french-learning-app/internal/domain"
)

// stubAnalysisRepo is a minimal domain.AnalysisRepository for effective-analysis
// service tests. Only GetByID is exercised.
type stubAnalysisRepo struct {
	analysis *domain.Analysis
	getErr   error
}

func (s *stubAnalysisRepo) Create(context.Context, int64, domain.AnalysisResult, string) (*domain.Analysis, error) {
	return nil, errors.New("unused")
}
func (s *stubAnalysisRepo) ListByEntry(context.Context, int64) ([]*domain.Analysis, error) {
	return nil, errors.New("unused")
}
func (s *stubAnalysisRepo) GetByID(_ context.Context, _ int64) (*domain.Analysis, error) {
	return s.analysis, s.getErr
}

// stubFeedbackRepo is a minimal domain.FeedbackRepository; only
// GetLatestByAnalysis is exercised.
type stubFeedbackRepo struct {
	latest    *domain.Feedback
	latestErr error
}

func (s *stubFeedbackRepo) Create(context.Context, int64, domain.NewFeedbackInput) (*domain.Feedback, error) {
	return nil, errors.New("unused")
}
func (s *stubFeedbackRepo) ListByAnalysis(context.Context, int64) ([]*domain.Feedback, error) {
	return nil, errors.New("unused")
}
func (s *stubFeedbackRepo) GetLatestByAnalysis(_ context.Context, _ int64) (*domain.Feedback, error) {
	return s.latest, s.latestErr
}

func baseAnalysis() *domain.Analysis {
	return &domain.Analysis{ID: 12, EntryID: 5, Version: 2, Category: "grammar", Explanation: "Original explanation"}
}

func newEffectiveSvc(a *domain.Analysis, f *domain.Feedback) *EffectiveAnalysisService {
	return NewEffectiveAnalysisService(
		&stubAnalysisRepo{analysis: a},
		&stubFeedbackRepo{latest: f},
	)
}

func TestEffectiveService_Unreviewed(t *testing.T) {
	svc := newEffectiveSvc(baseAnalysis(), nil)
	eff, err := svc.Resolve(context.Background(), 12)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if eff.Resolution != domain.ResolutionUnreviewed {
		t.Fatalf("resolution = %q, want unreviewed", eff.Resolution)
	}
	if eff.Effective == nil || eff.Effective.Category != "grammar" {
		t.Fatalf("effective should equal original, got %+v", eff.Effective)
	}
	if eff.FeedbackID != nil {
		t.Fatalf("feedback id should be nil, got %v", *eff.FeedbackID)
	}
}

func TestEffectiveService_Accepted(t *testing.T) {
	fb := &domain.Feedback{ID: 7, AnalysisID: 12, Status: domain.FeedbackAccepted}
	svc := newEffectiveSvc(baseAnalysis(), fb)
	eff, err := svc.Resolve(context.Background(), 12)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if eff.Resolution != domain.ResolutionAccepted {
		t.Fatalf("resolution = %q, want accepted", eff.Resolution)
	}
	if eff.Effective.Category != "grammar" || eff.Effective.Explanation != "Original explanation" {
		t.Fatalf("accepted effective should equal original, got %+v", eff.Effective)
	}
	if eff.FeedbackID == nil || *eff.FeedbackID != 7 {
		t.Fatalf("feedback id = %v, want 7", eff.FeedbackID)
	}
}

func TestEffectiveService_CorrectedBothFields(t *testing.T) {
	fb := &domain.Feedback{ID: 9, AnalysisID: 12, Status: domain.FeedbackCorrected,
		CorrectedCategory: strptr("morphology"), CorrectedExplanation: strptr("Corrected explanation")}
	svc := newEffectiveSvc(baseAnalysis(), fb)
	eff, _ := svc.Resolve(context.Background(), 12)
	if eff.Resolution != domain.ResolutionCorrected {
		t.Fatalf("resolution = %q, want corrected", eff.Resolution)
	}
	if eff.Effective.Category != "morphology" || eff.Effective.Explanation != "Corrected explanation" {
		t.Fatalf("both fields should override, got %+v", eff.Effective)
	}
}

func TestEffectiveService_CorrectedCategoryOnly(t *testing.T) {
	fb := &domain.Feedback{ID: 9, AnalysisID: 12, Status: domain.FeedbackCorrected, CorrectedCategory: strptr("morphology")}
	svc := newEffectiveSvc(baseAnalysis(), fb)
	eff, _ := svc.Resolve(context.Background(), 12)
	if eff.Effective.Category != "morphology" {
		t.Fatalf("category should override, got %q", eff.Effective.Category)
	}
	if eff.Effective.Explanation != "Original explanation" {
		t.Fatalf("explanation should retain original, got %q", eff.Effective.Explanation)
	}
}

func TestEffectiveService_CorrectedExplanationOnly(t *testing.T) {
	fb := &domain.Feedback{ID: 9, AnalysisID: 12, Status: domain.FeedbackCorrected, CorrectedExplanation: strptr("Corrected explanation")}
	svc := newEffectiveSvc(baseAnalysis(), fb)
	eff, _ := svc.Resolve(context.Background(), 12)
	if eff.Effective.Category != "grammar" {
		t.Fatalf("category should retain original, got %q", eff.Effective.Category)
	}
	if eff.Effective.Explanation != "Corrected explanation" {
		t.Fatalf("explanation should override, got %q", eff.Effective.Explanation)
	}
}

func TestEffectiveService_Rejected(t *testing.T) {
	fb := &domain.Feedback{ID: 21, AnalysisID: 12, Status: domain.FeedbackRejected}
	svc := newEffectiveSvc(baseAnalysis(), fb)
	eff, _ := svc.Resolve(context.Background(), 12)
	if eff.Resolution != domain.ResolutionRejected {
		t.Fatalf("resolution = %q, want rejected", eff.Resolution)
	}
	if eff.Effective != nil {
		t.Fatalf("rejected effective must be nil, got %+v", eff.Effective)
	}
	if eff.Original.Category != "grammar" {
		t.Fatalf("original must be preserved, got %+v", eff.Original)
	}
}

func TestEffectiveService_MissingAnalysis(t *testing.T) {
	svc := NewEffectiveAnalysisService(
		&stubAnalysisRepo{getErr: domain.ErrNotFound},
		&stubFeedbackRepo{},
	)
	_, err := svc.Resolve(context.Background(), 999)
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestEffectiveService_DoesNotMutateOriginalAnalysis(t *testing.T) {
	a := baseAnalysis()
	fb := &domain.Feedback{ID: 9, AnalysisID: 12, Status: domain.FeedbackCorrected,
		CorrectedCategory: strptr("morphology"), CorrectedExplanation: strptr("Corrected explanation")}
	svc := newEffectiveSvc(a, fb)
	if _, err := svc.Resolve(context.Background(), 12); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if a.Category != "grammar" || a.Explanation != "Original explanation" {
		t.Fatalf("original analysis was mutated: %+v", a)
	}
}
