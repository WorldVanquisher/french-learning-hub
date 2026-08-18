package http

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"french-learning-app/internal/application"
)

type fakeRetrievalEvaluationService struct {
	report application.ConceptRetrievalEvaluationReport
	err    error
	calls  int
}

func (f *fakeRetrievalEvaluationService) BuildV1(context.Context) (application.ConceptRetrievalEvaluationReport, error) {
	f.calls++
	return f.report, f.err
}

func retrievalEvaluationTestRoutes(service RetrievalEvaluationService) http.Handler {
	return NewHandler(&fakeService{}, nil, nil, nil, nil, nil, nil, nil, nil, nil, WithRetrievalEvaluation(service)).Routes()
}

func TestRetrievalEvaluationHandler_ReturnsVersionedEvaluatedReport(t *testing.T) {
	zero := 0.0
	service := &fakeRetrievalEvaluationService{report: application.ConceptRetrievalEvaluationReport{
		SchemaVersion:    application.ConceptRetrievalEvaluationV1SchemaVersion,
		EvaluationPolicy: application.ConceptRetrievalEvaluationPolicyV1,
		Retriever:        application.ExactSignatureRetrieverV1Name,
		State:            application.ConceptRetrievalEvaluationStateEvaluated,
		DatasetValid:     true,
		Metrics: application.ConceptRetrievalEvaluationMetrics{
			RecallAt1: &zero, RecallAt3: &zero, RecallAt5: &zero, MRR: &zero,
		},
		Samples: []application.ConceptRetrievalEvaluationSample{},
	}}
	recorder := httptest.NewRecorder()
	retrievalEvaluationTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/retrieval-evaluation/v1", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	if got := recorder.Header().Get("Content-Type"); !strings.HasPrefix(got, "application/json") {
		t.Fatalf("Content-Type = %q", got)
	}
	var body struct {
		SchemaVersion    string            `json:"schema_version"`
		EvaluationPolicy string            `json:"evaluation_policy"`
		Retriever        string            `json:"retriever"`
		State            string            `json:"state"`
		DatasetValid     bool              `json:"dataset_valid"`
		Samples          []json.RawMessage `json:"samples"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body.SchemaVersion != application.ConceptRetrievalEvaluationV1SchemaVersion || body.EvaluationPolicy != application.ConceptRetrievalEvaluationPolicyV1 || body.Retriever != application.ExactSignatureRetrieverV1Name || body.State != application.ConceptRetrievalEvaluationStateEvaluated || !body.DatasetValid || body.Samples == nil {
		t.Fatalf("response = %+v; body=%s", body, recorder.Body.String())
	}
	if service.calls != 1 {
		t.Fatalf("BuildV1 calls = %d", service.calls)
	}
}

func TestRetrievalEvaluationHandler_BlockedInvalidDatasetReturnsOKAndNullMetrics(t *testing.T) {
	service := &fakeRetrievalEvaluationService{report: application.ConceptRetrievalEvaluationReport{
		SchemaVersion:    application.ConceptRetrievalEvaluationV1SchemaVersion,
		EvaluationPolicy: application.ConceptRetrievalEvaluationPolicyV1,
		Retriever:        application.ExactSignatureRetrieverV1Name,
		State:            application.ConceptRetrievalEvaluationStateBlockedInvalidDataset,
		DatasetValid:     false,
		Samples:          []application.ConceptRetrievalEvaluationSample{},
	}}
	recorder := httptest.NewRecorder()
	retrievalEvaluationTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/retrieval-evaluation/v1", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	body := recorder.Body.String()
	for _, fragment := range []string{
		`"state":"blocked_invalid_dataset"`, `"dataset_valid":false`,
		`"recall_at_1":null`, `"recall_at_3":null`, `"recall_at_5":null`, `"mrr":null`, `"samples":[]`,
	} {
		if !strings.Contains(body, fragment) {
			t.Fatalf("body missing %s: %s", fragment, body)
		}
	}
}

func TestRetrievalEvaluationHandler_InternalFailureIsGeneric(t *testing.T) {
	service := &fakeRetrievalEvaluationService{err: errors.New("private storage and provider detail")}
	recorder := httptest.NewRecorder()
	retrievalEvaluationTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/retrieval-evaluation/v1", nil))
	if recorder.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d", recorder.Code)
	}
	body := recorder.Body.String()
	if !strings.Contains(body, "could not build concept retrieval evaluation") || strings.Contains(body, "private storage") || strings.Contains(body, "provider detail") {
		t.Fatalf("body = %s", body)
	}
}

func TestRetrievalEvaluationHandler_IsGetOnlyAndHasNoMutationOrProviderCapability(t *testing.T) {
	service := &fakeRetrievalEvaluationService{}
	recorder := httptest.NewRecorder()
	retrievalEvaluationTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodPost, "/retrieval-evaluation/v1", nil))
	if recorder.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusMethodNotAllowed)
	}
	if service.calls != 0 {
		t.Fatalf("BuildV1 calls = %d, want 0", service.calls)
	}
}
