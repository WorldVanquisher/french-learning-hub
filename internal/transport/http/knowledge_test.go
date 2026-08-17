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

// fakeKnowledge implements KnowledgeService for handler tests.
type fakeKnowledge struct {
	extractFn      func(ctx context.Context, entryID int64) (*domain.ExtractionView, error)
	listFn         func(ctx context.Context, entryID int64) ([]*domain.ExtractionView, error)
	getFn          func(ctx context.Context, extractionID int64) (*domain.ExtractionView, error)
	addOverrideFn  func(ctx context.Context, unitID int64, in domain.NewAdmissionOverrideInput) (*domain.AdmissionOverride, error)
	getAdmissionFn func(ctx context.Context, unitID int64) (*domain.AdmissionState, error)
	listOverFn     func(ctx context.Context, unitID int64) ([]*domain.AdmissionOverride, error)
}

func (f *fakeKnowledge) Extract(ctx context.Context, entryID int64) (*domain.ExtractionView, error) {
	return f.extractFn(ctx, entryID)
}
func (f *fakeKnowledge) ListExtractions(ctx context.Context, entryID int64) ([]*domain.ExtractionView, error) {
	return f.listFn(ctx, entryID)
}
func (f *fakeKnowledge) GetExtraction(ctx context.Context, extractionID int64) (*domain.ExtractionView, error) {
	return f.getFn(ctx, extractionID)
}
func (f *fakeKnowledge) AddOverride(ctx context.Context, unitID int64, in domain.NewAdmissionOverrideInput) (*domain.AdmissionOverride, error) {
	return f.addOverrideFn(ctx, unitID, in)
}
func (f *fakeKnowledge) GetAdmission(ctx context.Context, unitID int64) (*domain.AdmissionState, error) {
	return f.getAdmissionFn(ctx, unitID)
}
func (f *fakeKnowledge) ListOverrides(ctx context.Context, unitID int64) ([]*domain.AdmissionOverride, error) {
	return f.listOverFn(ctx, unitID)
}

func knowledgeServer(k KnowledgeService) http.Handler {
	return NewHandler(&fakeService{}, nil, nil, nil, nil, nil, k, nil, nil).Routes()
}

func sampleView() *domain.ExtractionView {
	return &domain.ExtractionView{
		Extraction: domain.KnowledgeExtraction{ID: 10, EntryID: 1, Version: 1, SourceAnalysisID: 3, Extractor: "openai:test:knowledge_extraction_v1", CreatedAt: time.Now().UTC()},
		Units: []domain.KnowledgeUnitView{{
			Unit: domain.KnowledgeUnit{ID: 100, ExtractionID: 10, Ordinal: 1, Kind: domain.KindGrammar, Canonical: "vouloir", Statement: "s", Confidence: 0.9, CreatedAt: time.Now().UTC()},
			Admission: domain.AdmissionState{
				Recommendation: domain.AdmissionRecommendation{Ruleset: domain.AdmissionRulesetName, State: domain.AdmissionActive, Reason: domain.ReasonDefaultActive},
				Effective:      domain.AdmissionActive,
			},
		}},
	}
}

func TestHandleCreateExtraction_Success(t *testing.T) {
	k := &fakeKnowledge{extractFn: func(_ context.Context, _ int64) (*domain.ExtractionView, error) {
		return sampleView(), nil
	}}
	srv := knowledgeServer(k)

	req := httptest.NewRequest(http.MethodPost, "/entries/1/extractions", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201; body=%s", rec.Code, rec.Body.String())
	}
	var resp extractionResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if resp.ID != 10 || len(resp.Units) != 1 || resp.Units[0].Admission.Effective != "active" {
		t.Fatalf("unexpected response: %+v", resp)
	}
}

func TestHandleCreateExtraction_ErrorMappings(t *testing.T) {
	cases := map[string]struct {
		err  error
		want int
	}{
		"disabled":     {domain.ErrExtractorDisabled, http.StatusServiceUnavailable},
		"not found":    {domain.ErrNotFound, http.StatusNotFound},
		"not eligible": {domain.ErrNotEligible, http.StatusConflict},
		"validation":   {domain.ErrValidation, http.StatusUnprocessableEntity},
		"timeout":      {domain.ErrProviderTimeout, http.StatusGatewayTimeout},
		"unavailable":  {domain.ErrProviderUnavailable, http.StatusBadGateway},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			k := &fakeKnowledge{extractFn: func(_ context.Context, _ int64) (*domain.ExtractionView, error) {
				return nil, tc.err
			}}
			srv := knowledgeServer(k)
			req := httptest.NewRequest(http.MethodPost, "/entries/1/extractions", nil)
			rec := httptest.NewRecorder()
			srv.ServeHTTP(rec, req)
			if rec.Code != tc.want {
				t.Fatalf("status = %d, want %d", rec.Code, tc.want)
			}
		})
	}
}

func TestHandleCreateExtraction_InvalidID(t *testing.T) {
	srv := knowledgeServer(&fakeKnowledge{})
	req := httptest.NewRequest(http.MethodPost, "/entries/abc/extractions", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestHandleListExtractions_Success(t *testing.T) {
	k := &fakeKnowledge{listFn: func(_ context.Context, _ int64) ([]*domain.ExtractionView, error) {
		return []*domain.ExtractionView{sampleView()}, nil
	}}
	srv := knowledgeServer(k)
	req := httptest.NewRequest(http.MethodGet, "/entries/1/extractions", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var resp struct {
		Extractions []extractionResponse `json:"extractions"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(resp.Extractions) != 1 {
		t.Fatalf("expected 1 extraction, got %d", len(resp.Extractions))
	}
}

func TestHandleGetExtraction_NotFound(t *testing.T) {
	k := &fakeKnowledge{getFn: func(_ context.Context, _ int64) (*domain.ExtractionView, error) {
		return nil, domain.ErrNotFound
	}}
	srv := knowledgeServer(k)
	req := httptest.NewRequest(http.MethodGet, "/extractions/999", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

func TestHandleCreateOverride_Success(t *testing.T) {
	var gotInput domain.NewAdmissionOverrideInput
	k := &fakeKnowledge{addOverrideFn: func(_ context.Context, _ int64, in domain.NewAdmissionOverrideInput) (*domain.AdmissionOverride, error) {
		gotInput = in
		return &domain.AdmissionOverride{ID: 1, UnitID: 100, Decision: in.Decision, Reason: in.Reason, CreatedAt: time.Now().UTC()}, nil
	}}
	srv := knowledgeServer(k)

	body := `{"decision":"suppressed","reason":"mastered","note":"already know this"}`
	req := httptest.NewRequest(http.MethodPost, "/knowledge-units/100/admission-overrides", strings.NewReader(body))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201; body=%s", rec.Code, rec.Body.String())
	}
	if gotInput.Decision != domain.HumanAdmitSuppressed || gotInput.Reason != "mastered" {
		t.Fatalf("service got unexpected input: %+v", gotInput)
	}
}

func TestHandleCreateOverride_ValidationError(t *testing.T) {
	k := &fakeKnowledge{addOverrideFn: func(_ context.Context, _ int64, _ domain.NewAdmissionOverrideInput) (*domain.AdmissionOverride, error) {
		return nil, domain.ErrValidation
	}}
	srv := knowledgeServer(k)
	req := httptest.NewRequest(http.MethodPost, "/knowledge-units/100/admission-overrides", strings.NewReader(`{"decision":"suppressed"}`))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("status = %d, want 422", rec.Code)
	}
}

func TestHandleCreateOverride_UnitNotFound(t *testing.T) {
	k := &fakeKnowledge{addOverrideFn: func(_ context.Context, _ int64, _ domain.NewAdmissionOverrideInput) (*domain.AdmissionOverride, error) {
		return nil, domain.ErrNotFound
	}}
	srv := knowledgeServer(k)
	req := httptest.NewRequest(http.MethodPost, "/knowledge-units/100/admission-overrides", strings.NewReader(`{"decision":"active"}`))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

func TestHandleCreateOverride_InvalidJSON(t *testing.T) {
	srv := knowledgeServer(&fakeKnowledge{})
	req := httptest.NewRequest(http.MethodPost, "/knowledge-units/100/admission-overrides", strings.NewReader(`{bad`))
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestHandleGetAdmission_Success(t *testing.T) {
	k := &fakeKnowledge{getAdmissionFn: func(_ context.Context, _ int64) (*domain.AdmissionState, error) {
		return &domain.AdmissionState{
			Recommendation: domain.AdmissionRecommendation{Ruleset: domain.AdmissionRulesetName, State: domain.AdmissionActive, Reason: domain.ReasonDefaultActive},
			Effective:      domain.AdmissionActive,
		}, nil
	}}
	srv := knowledgeServer(k)
	req := httptest.NewRequest(http.MethodGet, "/knowledge-units/100/admission", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var resp admissionResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if resp.Effective != "active" || resp.Ruleset != domain.AdmissionRulesetName {
		t.Fatalf("unexpected admission response: %+v", resp)
	}
}

func TestHandleListOverrides_Success(t *testing.T) {
	k := &fakeKnowledge{listOverFn: func(_ context.Context, _ int64) ([]*domain.AdmissionOverride, error) {
		return []*domain.AdmissionOverride{
			{ID: 1, UnitID: 100, Decision: domain.HumanAdmitSuppressed, Reason: "mastered", CreatedAt: time.Now().UTC()},
			{ID: 2, UnitID: 100, Decision: domain.HumanAdmitActive, CreatedAt: time.Now().UTC()},
		}, nil
	}}
	srv := knowledgeServer(k)
	req := httptest.NewRequest(http.MethodGet, "/knowledge-units/100/admission-overrides", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var resp struct {
		Overrides []admissionOverrideResponse `json:"overrides"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(resp.Overrides) != 2 {
		t.Fatalf("expected 2 overrides, got %d", len(resp.Overrides))
	}
}
