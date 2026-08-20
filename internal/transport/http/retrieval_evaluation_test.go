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

type fakeRetrievalEvaluationService struct {
	report application.ConceptRetrievalEvaluationReport
	err    error
	calls  int
	names  []string
}

func (f *fakeRetrievalEvaluationService) BuildV1WithRetriever(_ context.Context, name string) (application.ConceptRetrievalEvaluationReport, error) {
	f.calls++
	f.names = append(f.names, name)
	if name == "unknown" {
		return application.ConceptRetrievalEvaluationReport{}, application.ErrUnknownConceptRetriever
	}
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
	if !reflect.DeepEqual(service.names, []string{""}) {
		t.Fatalf("retriever selections = %v", service.names)
	}
}

func TestRetrievalEvaluationHandler_PassesExplicitRetrieverSelection(t *testing.T) {
	for _, name := range []string{application.ExactSignatureRetrieverV1Name, application.WeightedLexicalRetrieverV1Name} {
		t.Run(name, func(t *testing.T) {
			service := &fakeRetrievalEvaluationService{report: application.ConceptRetrievalEvaluationReport{
				Retriever: name, Samples: []application.ConceptRetrievalEvaluationSample{},
			}}
			recorder := httptest.NewRecorder()
			path := "/retrieval-evaluation/v1?retriever=" + name
			retrievalEvaluationTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, path, nil))
			if recorder.Code != http.StatusOK {
				t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
			}
			if !reflect.DeepEqual(service.names, []string{name}) || !strings.Contains(recorder.Body.String(), `"retriever":"`+name+`"`) {
				t.Fatalf("selection = %v, body = %s", service.names, recorder.Body.String())
			}
		})
	}
}

func TestRetrievalEvaluationHandler_RejectsUnknownAndDuplicateRetriever(t *testing.T) {
	t.Run("unknown", func(t *testing.T) {
		service := &fakeRetrievalEvaluationService{}
		recorder := httptest.NewRecorder()
		retrievalEvaluationTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/retrieval-evaluation/v1?retriever=unknown", nil))
		if recorder.Code != http.StatusBadRequest || recorder.Body.String() != "{\"error\":\"unknown retriever\"}\n" {
			t.Fatalf("status = %d, body = %q", recorder.Code, recorder.Body.String())
		}
	})

	t.Run("duplicate", func(t *testing.T) {
		service := &fakeRetrievalEvaluationService{}
		recorder := httptest.NewRecorder()
		path := "/retrieval-evaluation/v1?retriever=" + application.ExactSignatureRetrieverV1Name + "&retriever=" + application.WeightedLexicalRetrieverV1Name
		retrievalEvaluationTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, path, nil))
		if recorder.Code != http.StatusBadRequest || service.calls != 0 {
			t.Fatalf("status = %d, calls = %d, body = %q", recorder.Code, service.calls, recorder.Body.String())
		}
	})
}

func TestRetrievalEvaluationHandler_BlockedInvalidDatasetReturnsOKAndNullMetrics(t *testing.T) {
	for _, name := range []string{application.ExactSignatureRetrieverV1Name, application.WeightedLexicalRetrieverV1Name} {
		t.Run(name, func(t *testing.T) {
			service := &fakeRetrievalEvaluationService{report: application.ConceptRetrievalEvaluationReport{
				SchemaVersion:    application.ConceptRetrievalEvaluationV1SchemaVersion,
				EvaluationPolicy: application.ConceptRetrievalEvaluationPolicyV1,
				Retriever:        name,
				State:            application.ConceptRetrievalEvaluationStateBlockedInvalidDataset,
				DatasetValid:     false,
				Samples:          []application.ConceptRetrievalEvaluationSample{},
			}}
			recorder := httptest.NewRecorder()
			path := "/retrieval-evaluation/v1?retriever=" + name
			retrievalEvaluationTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, path, nil))
			if recorder.Code != http.StatusOK {
				t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
			}
			body := recorder.Body.String()
			for _, fragment := range []string{
				`"state":"blocked_invalid_dataset"`, `"dataset_valid":false`, `"retriever":"` + name + `"`,
				`"recall_at_1":null`, `"recall_at_3":null`, `"recall_at_5":null`, `"mrr":null`, `"samples":[]`,
			} {
				if !strings.Contains(body, fragment) {
					t.Fatalf("body missing %s: %s", fragment, body)
				}
			}
		})
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
