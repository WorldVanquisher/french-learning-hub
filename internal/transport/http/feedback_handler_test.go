package http

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

// fakeFeedbackService implements FeedbackService for handler tests.
type fakeFeedbackService struct {
	addFn  func(ctx context.Context, analysisID int64, in domain.NewFeedbackInput) (*domain.Feedback, error)
	listFn func(ctx context.Context, analysisID int64) ([]*domain.Feedback, error)
}

func (f *fakeFeedbackService) AddFeedback(ctx context.Context, analysisID int64, in domain.NewFeedbackInput) (*domain.Feedback, error) {
	return f.addFn(ctx, analysisID, in)
}
func (f *fakeFeedbackService) ListFeedback(ctx context.Context, analysisID int64) ([]*domain.Feedback, error) {
	return f.listFn(ctx, analysisID)
}

func newFeedbackServer(f FeedbackService) http.Handler {
	return NewHandler(&fakeService{}, nil, f, nil, nil, nil).Routes()
}

func TestCreateFeedback_Success(t *testing.T) {
	svc := &fakeFeedbackService{
		addFn: func(_ context.Context, analysisID int64, in domain.NewFeedbackInput) (*domain.Feedback, error) {
			return &domain.Feedback{
				ID:         7,
				AnalysisID: analysisID,
				Status:     in.Status,
				UserNote:   in.UserNote,
				CreatedAt:  time.Now().UTC(),
			}, nil
		},
	}
	srv := newFeedbackServer(svc)

	body := `{"status":"accepted","user_note":"looks right"}`
	req := httptest.NewRequest(http.MethodPost, "/analyses/3/feedback", strings.NewReader(body))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201; body=%s", rec.Code, rec.Body.String())
	}
	var resp feedbackResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if resp.AnalysisID != 3 || resp.Status != "accepted" {
		t.Fatalf("unexpected response: %+v", resp)
	}
}

func TestCreateFeedback_AnalysisNotFound(t *testing.T) {
	svc := &fakeFeedbackService{
		addFn: func(_ context.Context, _ int64, _ domain.NewFeedbackInput) (*domain.Feedback, error) {
			return nil, domain.ErrNotFound
		},
	}
	srv := newFeedbackServer(svc)

	req := httptest.NewRequest(http.MethodPost, "/analyses/3/feedback", strings.NewReader(`{"status":"accepted"}`))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

func TestCreateFeedback_ValidationError(t *testing.T) {
	svc := &fakeFeedbackService{
		addFn: func(_ context.Context, _ int64, _ domain.NewFeedbackInput) (*domain.Feedback, error) {
			return nil, domain.ErrValidation
		},
	}
	srv := newFeedbackServer(svc)

	req := httptest.NewRequest(http.MethodPost, "/analyses/3/feedback", strings.NewReader(`{"status":"corrected"}`))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("status = %d, want 422", rec.Code)
	}
}

func TestCreateFeedback_InvalidJSON(t *testing.T) {
	srv := newFeedbackServer(&fakeFeedbackService{})
	req := httptest.NewRequest(http.MethodPost, "/analyses/3/feedback", strings.NewReader(`{bad`))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestCreateFeedback_UnknownField(t *testing.T) {
	srv := newFeedbackServer(&fakeFeedbackService{})
	req := httptest.NewRequest(http.MethodPost, "/analyses/3/feedback", strings.NewReader(`{"status":"accepted","bogus":1}`))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestCreateFeedback_InvalidID(t *testing.T) {
	srv := newFeedbackServer(&fakeFeedbackService{})
	req := httptest.NewRequest(http.MethodPost, "/analyses/abc/feedback", strings.NewReader(`{"status":"accepted"}`))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestListFeedback_Success(t *testing.T) {
	svc := &fakeFeedbackService{
		listFn: func(_ context.Context, analysisID int64) ([]*domain.Feedback, error) {
			return []*domain.Feedback{
				{ID: 1, AnalysisID: analysisID, Status: domain.FeedbackRejected, CreatedAt: time.Now()},
				{ID: 2, AnalysisID: analysisID, Status: domain.FeedbackAccepted, CreatedAt: time.Now()},
			}, nil
		},
	}
	srv := newFeedbackServer(svc)

	req := httptest.NewRequest(http.MethodGet, "/analyses/3/feedback", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var resp struct {
		Feedback []feedbackResponse `json:"feedback"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(resp.Feedback) != 2 {
		t.Fatalf("expected 2 feedback records, got %d", len(resp.Feedback))
	}
}

func TestListFeedback_AnalysisNotFound(t *testing.T) {
	svc := &fakeFeedbackService{
		listFn: func(_ context.Context, _ int64) ([]*domain.Feedback, error) {
			return nil, domain.ErrNotFound
		},
	}
	srv := newFeedbackServer(svc)

	req := httptest.NewRequest(http.MethodGet, "/analyses/3/feedback", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}
