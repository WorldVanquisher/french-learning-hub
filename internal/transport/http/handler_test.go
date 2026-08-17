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

// fakeService implements EntryService for handler tests.
type fakeService struct {
	createFn func(ctx context.Context, in domain.NewEntryInput) (*domain.Entry, error)
	getFn    func(ctx context.Context, id int64) (*domain.Entry, error)
	listFn   func(ctx context.Context, limit int) ([]*domain.Entry, error)
}

func (f *fakeService) CreateEntry(ctx context.Context, in domain.NewEntryInput) (*domain.Entry, error) {
	return f.createFn(ctx, in)
}
func (f *fakeService) GetEntry(ctx context.Context, id int64) (*domain.Entry, error) {
	return f.getFn(ctx, id)
}
func (f *fakeService) ListEntries(ctx context.Context, limit int) ([]*domain.Entry, error) {
	return f.listFn(ctx, limit)
}

func newServer(svc EntryService) http.Handler {
	return NewHandler(svc, nil, nil, nil, nil, nil, nil, nil, nil, nil).Routes()
}

func TestCreateEntry_Success(t *testing.T) {
	svc := &fakeService{
		createFn: func(_ context.Context, in domain.NewEntryInput) (*domain.Entry, error) {
			return &domain.Entry{
				ID:              1,
				OriginalInput:   in.OriginalInput,
				OriginalContext: in.OriginalContext,
				CreatedAt:       time.Now().UTC(),
				UpdatedAt:       time.Now().UTC(),
			}, nil
		},
	}
	srv := newServer(svc)

	body := `{"original_input":"Bonjour","original_context":"greeting"}`
	req := httptest.NewRequest(http.MethodPost, "/entries", strings.NewReader(body))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201; body=%s", rec.Code, rec.Body.String())
	}
	var resp entryResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if resp.ID != 1 || resp.OriginalInput != "Bonjour" {
		t.Fatalf("unexpected response: %+v", resp)
	}
}

func TestCreateEntry_ValidationError(t *testing.T) {
	svc := &fakeService{
		createFn: func(_ context.Context, _ domain.NewEntryInput) (*domain.Entry, error) {
			return nil, domain.ErrValidation
		},
	}
	srv := newServer(svc)

	req := httptest.NewRequest(http.MethodPost, "/entries", strings.NewReader(`{"original_input":""}`))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestCreateEntry_InvalidJSON(t *testing.T) {
	svc := &fakeService{}
	srv := newServer(svc)

	req := httptest.NewRequest(http.MethodPost, "/entries", strings.NewReader(`{not json`))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestGetEntry_NotFound(t *testing.T) {
	svc := &fakeService{
		getFn: func(_ context.Context, _ int64) (*domain.Entry, error) {
			return nil, domain.ErrNotFound
		},
	}
	srv := newServer(svc)

	req := httptest.NewRequest(http.MethodGet, "/entries/42", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

func TestGetEntry_InvalidID(t *testing.T) {
	svc := &fakeService{}
	srv := newServer(svc)

	req := httptest.NewRequest(http.MethodGet, "/entries/abc", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestListEntries_Success(t *testing.T) {
	svc := &fakeService{
		listFn: func(_ context.Context, _ int) ([]*domain.Entry, error) {
			return []*domain.Entry{
				{ID: 2, OriginalInput: "b", CreatedAt: time.Now(), UpdatedAt: time.Now()},
				{ID: 1, OriginalInput: "a", CreatedAt: time.Now(), UpdatedAt: time.Now()},
			}, nil
		},
	}
	srv := newServer(svc)

	req := httptest.NewRequest(http.MethodGet, "/entries", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var resp struct {
		Entries []entryResponse `json:"entries"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(resp.Entries) != 2 {
		t.Fatalf("expected 2 entries, got %d", len(resp.Entries))
	}
}

func TestHealth(t *testing.T) {
	srv := newServer(&fakeService{})
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
}
