package http

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"

	"french-learning-app/internal/application"
)

type fakeRetrievalComparisonService struct {
	report application.ConceptRetrievalComparisonReport
	err    error
	calls  int
}

func (f *fakeRetrievalComparisonService) BuildV1(context.Context) (application.ConceptRetrievalComparisonReport, error) {
	f.calls++
	return f.report, f.err
}

func retrievalComparisonTestRoutes(service RetrievalComparisonService) http.Handler {
	return NewHandler(
		&fakeService{}, nil, nil, nil, nil, nil, nil, nil, nil, nil,
		WithRetrievalComparison(service),
	).Routes()
}

func comparisonHTTPMetric(value float64) *float64 { return &value }

func TestRetrievalComparisonHandler_ReturnsCompactStableSchemaAndOrder(t *testing.T) {
	service := &fakeRetrievalComparisonService{report: application.ConceptRetrievalComparisonReport{
		SchemaVersion: application.ConceptRetrievalComparisonV1SchemaVersion,
		State:         application.ConceptRetrievalEvaluationStateEvaluated,
		DatasetValid:  true,
		CandidateUniverse: application.ConceptRetrievalCandidateUniverse{
			Concepts: 9,
		},
		EvaluationSamples: application.ConceptRetrievalComparisonSampleInventory{EligibleSamples: 3},
		Retrievers: []application.ConceptRetrievalComparisonRetriever{
			{Retriever: application.ExactSignatureRetrieverV1Name, State: application.ConceptRetrievalEvaluationStateEvaluated, Metrics: application.ConceptRetrievalEvaluationMetrics{RecallAt1: comparisonHTTPMetric(0.1)}},
			{Retriever: application.WeightedLexicalRetrieverV1Name, State: application.ConceptRetrievalEvaluationStateEvaluated, Metrics: application.ConceptRetrievalEvaluationMetrics{RecallAt1: comparisonHTTPMetric(0.2)}},
			{Retriever: application.BM25RetrieverV1Name, State: application.ConceptRetrievalEvaluationStateEvaluated, Metrics: application.ConceptRetrievalEvaluationMetrics{RecallAt1: comparisonHTTPMetric(0.3)}},
			{Retriever: application.EmbeddingRetrieverV1Name, State: application.ConceptRetrievalComparisonRetrieverStateUnavailable},
		},
	}}
	recorder := httptest.NewRecorder()
	retrievalComparisonTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/retrieval-comparison/v1", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	if got := recorder.Header().Get("Content-Type"); !strings.HasPrefix(got, "application/json") {
		t.Fatalf("Content-Type = %q", got)
	}
	var body struct {
		SchemaVersion     string `json:"schema_version"`
		State             string `json:"state"`
		DatasetValid      bool   `json:"dataset_valid"`
		CandidateUniverse struct {
			Concepts int `json:"concepts"`
		} `json:"candidate_universe"`
		EvaluationSamples struct {
			EligibleSamples int `json:"eligible_samples"`
		} `json:"evaluation_samples"`
		Retrievers []struct {
			Retriever string `json:"retriever"`
			State     string `json:"state"`
			Metrics   struct {
				RecallAt1 *float64 `json:"recall_at_1"`
				RecallAt3 *float64 `json:"recall_at_3"`
				RecallAt5 *float64 `json:"recall_at_5"`
				MRR       *float64 `json:"mrr"`
			} `json:"metrics"`
		} `json:"retrievers"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body.SchemaVersion != application.ConceptRetrievalComparisonV1SchemaVersion || body.State != application.ConceptRetrievalEvaluationStateEvaluated || !body.DatasetValid || body.CandidateUniverse.Concepts != 9 || body.EvaluationSamples.EligibleSamples != 3 {
		t.Fatalf("comparison response = %+v", body)
	}
	wantOrder := []string{application.ExactSignatureRetrieverV1Name, application.WeightedLexicalRetrieverV1Name, application.BM25RetrieverV1Name, application.EmbeddingRetrieverV1Name}
	gotOrder := make([]string, 0, len(body.Retrievers))
	for _, row := range body.Retrievers {
		gotOrder = append(gotOrder, row.Retriever)
	}
	if !reflect.DeepEqual(gotOrder, wantOrder) {
		t.Fatalf("retriever order = %v", gotOrder)
	}
	embedding := body.Retrievers[3]
	if embedding.State != application.ConceptRetrievalComparisonRetrieverStateUnavailable || embedding.Metrics.RecallAt1 != nil || embedding.Metrics.RecallAt3 != nil || embedding.Metrics.RecallAt5 != nil || embedding.Metrics.MRR != nil {
		t.Fatalf("unavailable embedding row = %+v", embedding)
	}
	if service.calls != 1 || strings.Contains(recorder.Body.String(), `"samples"`) {
		t.Fatalf("calls = %d, body = %s", service.calls, recorder.Body.String())
	}
}

func TestRetrievalComparisonHandler_BlockedInvalidDatasetReturnsOK(t *testing.T) {
	service := &fakeRetrievalComparisonService{report: application.ConceptRetrievalComparisonReport{
		SchemaVersion: application.ConceptRetrievalComparisonV1SchemaVersion,
		State:         application.ConceptRetrievalEvaluationStateBlockedInvalidDataset,
		DatasetValid:  false,
		Retrievers: []application.ConceptRetrievalComparisonRetriever{
			{Retriever: application.ExactSignatureRetrieverV1Name, State: application.ConceptRetrievalEvaluationStateBlockedInvalidDataset},
		},
	}}
	recorder := httptest.NewRecorder()
	retrievalComparisonTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/retrieval-comparison/v1", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	for _, fragment := range []string{`"state":"blocked_invalid_dataset"`, `"dataset_valid":false`, `"recall_at_1":null`, `"mrr":null`} {
		if !strings.Contains(recorder.Body.String(), fragment) {
			t.Fatalf("body missing %s: %s", fragment, recorder.Body.String())
		}
	}
}

func TestRetrievalComparisonHandler_EmbeddingProviderFailuresAreSafe(t *testing.T) {
	for _, tc := range []struct {
		err    error
		status int
		body   string
	}{
		{err: application.ErrEmbeddingProviderTimeout, status: http.StatusGatewayTimeout, body: "{\"error\":\"embedding provider timed out\"}\n"},
		{err: application.ErrEmbeddingProviderUnavailable, status: http.StatusBadGateway, body: "{\"error\":\"embedding provider unavailable\"}\n"},
	} {
		service := &fakeRetrievalComparisonService{err: errors.Join(tc.err, errors.New("secret provider response"))}
		recorder := httptest.NewRecorder()
		retrievalComparisonTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/retrieval-comparison/v1", nil))
		if recorder.Code != tc.status || recorder.Body.String() != tc.body || strings.Contains(recorder.Body.String(), "secret") {
			t.Fatalf("status = %d, body = %q", recorder.Code, recorder.Body.String())
		}
	}
}

func TestRetrievalComparisonHandler_InternalFailureIsGeneric(t *testing.T) {
	service := &fakeRetrievalComparisonService{err: errors.New("private population mismatch detail")}
	recorder := httptest.NewRecorder()
	retrievalComparisonTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/retrieval-comparison/v1", nil))
	if recorder.Code != http.StatusInternalServerError || !strings.Contains(recorder.Body.String(), "could not build concept retrieval comparison") || strings.Contains(recorder.Body.String(), "private") {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
}

func TestRetrievalComparisonHandler_IsGetOnly(t *testing.T) {
	service := &fakeRetrievalComparisonService{}
	recorder := httptest.NewRecorder()
	retrievalComparisonTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodPost, "/retrieval-comparison/v1", nil))
	if recorder.Code != http.StatusMethodNotAllowed || service.calls != 0 {
		t.Fatalf("status = %d, calls = %d", recorder.Code, service.calls)
	}
}
