package http

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

// fakeAnalysisService implements AnalysisService for handler tests.
type fakeAnalysisService struct {
	analyzeFn func(ctx context.Context, entryID int64) (*domain.Analysis, error)
	listFn    func(ctx context.Context, entryID int64) ([]*domain.Analysis, error)
}

func (f *fakeAnalysisService) AnalyzeEntry(ctx context.Context, entryID int64) (*domain.Analysis, error) {
	return f.analyzeFn(ctx, entryID)
}
func (f *fakeAnalysisService) ListAnalyses(ctx context.Context, entryID int64) ([]*domain.Analysis, error) {
	return f.listFn(ctx, entryID)
}

func newAnalysisServer(a AnalysisService) http.Handler {
	return NewHandler(&fakeService{}, a).Routes()
}

func TestCreateAnalysis_Success(t *testing.T) {
	svc := &fakeAnalysisService{
		analyzeFn: func(_ context.Context, entryID int64) (*domain.Analysis, error) {
			return &domain.Analysis{
				ID:          10,
				EntryID:     entryID,
				Version:     1,
				Category:    "vocabulary",
				Explanation: "means hello",
				Confidence:  0.7,
				Uncertainty: "placeholder",
				Analyzer:    "rule-based",
				CreatedAt:   time.Now().UTC(),
			}, nil
		},
	}
	srv := newAnalysisServer(svc)

	req := httptest.NewRequest(http.MethodPost, "/entries/5/analysis", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201; body=%s", rec.Code, rec.Body.String())
	}
	var resp analysisResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if resp.EntryID != 5 || resp.Version != 1 || resp.Analyzer != "rule-based" {
		t.Fatalf("unexpected response: %+v", resp)
	}
}

func TestCreateAnalysis_EntryNotFound(t *testing.T) {
	svc := &fakeAnalysisService{
		analyzeFn: func(_ context.Context, _ int64) (*domain.Analysis, error) {
			return nil, domain.ErrNotFound
		},
	}
	srv := newAnalysisServer(svc)

	req := httptest.NewRequest(http.MethodPost, "/entries/5/analysis", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

func TestCreateAnalysis_ValidationError(t *testing.T) {
	svc := &fakeAnalysisService{
		analyzeFn: func(_ context.Context, _ int64) (*domain.Analysis, error) {
			return nil, domain.ErrValidation
		},
	}
	srv := newAnalysisServer(svc)

	req := httptest.NewRequest(http.MethodPost, "/entries/5/analysis", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("status = %d, want 422", rec.Code)
	}
}

func TestCreateAnalysis_InvalidID(t *testing.T) {
	srv := newAnalysisServer(&fakeAnalysisService{})
	req := httptest.NewRequest(http.MethodPost, "/entries/abc/analysis", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestListAnalyses_Success(t *testing.T) {
	svc := &fakeAnalysisService{
		listFn: func(_ context.Context, entryID int64) ([]*domain.Analysis, error) {
			return []*domain.Analysis{
				{ID: 1, EntryID: entryID, Version: 1, Category: "vocabulary", Explanation: "e", Confidence: 0.5, Analyzer: "rule-based", CreatedAt: time.Now()},
				{ID: 2, EntryID: entryID, Version: 2, Category: "phrase", Explanation: "e", Confidence: 0.6, Analyzer: "rule-based", CreatedAt: time.Now()},
			}, nil
		},
	}
	srv := newAnalysisServer(svc)

	req := httptest.NewRequest(http.MethodGet, "/entries/5/analyses", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var resp struct {
		Analyses []analysisResponse `json:"analyses"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(resp.Analyses) != 2 {
		t.Fatalf("expected 2 analyses, got %d", len(resp.Analyses))
	}
}

func TestListAnalyses_EntryNotFound(t *testing.T) {
	svc := &fakeAnalysisService{
		listFn: func(_ context.Context, _ int64) ([]*domain.Analysis, error) {
			return nil, domain.ErrNotFound
		},
	}
	srv := newAnalysisServer(svc)

	req := httptest.NewRequest(http.MethodGet, "/entries/5/analyses", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}
