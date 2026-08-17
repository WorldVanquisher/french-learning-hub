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

type fakeAnnotationDatasetQualityService struct {
	report application.ConceptAnnotationQualityReport
	err    error
	calls  int
}

func (f *fakeAnnotationDatasetQualityService) BuildV1(context.Context) (application.ConceptAnnotationQualityReport, error) {
	f.calls++
	return f.report, f.err
}

func qualityTestRoutes(service AnnotationDatasetQualityService) http.Handler {
	return NewHandler(&fakeService{}, nil, nil, nil, nil, nil, nil, nil, nil, nil, service).Routes()
}

func TestAnnotationDatasetQualityHandler_ReturnsStableSchemaAndEmptyCollections(t *testing.T) {
	service := &fakeAnnotationDatasetQualityService{report: application.ConceptAnnotationQualityReport{
		SchemaVersion:        application.ConceptAnnotationQualityReportV1SchemaVersion,
		DatasetSchemaVersion: application.ConceptAnnotationDatasetV1SchemaVersion,
		Valid:                true,
	}}
	recorder := httptest.NewRecorder()
	qualityTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/annotation-dataset/v1/quality", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
	if got := recorder.Header().Get("Content-Type"); !strings.HasPrefix(got, "application/json") {
		t.Fatalf("Content-Type = %q", got)
	}
	var body struct {
		SchemaVersion        string `json:"schema_version"`
		DatasetSchemaVersion string `json:"dataset_schema_version"`
		Valid                bool   `json:"valid"`
		Provenance           struct {
			Extractors                    []json.RawMessage `json:"extractors"`
			ConceptIdentitySchemaVersions []json.RawMessage `json:"concept_identity_schema_versions"`
			HumanLabelResolverVersions    []json.RawMessage `json:"human_label_resolver_versions"`
		} `json:"provenance"`
		Issues []json.RawMessage `json:"issues"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body.SchemaVersion != application.ConceptAnnotationQualityReportV1SchemaVersion || body.DatasetSchemaVersion != application.ConceptAnnotationDatasetV1SchemaVersion || !body.Valid {
		t.Fatalf("response = %+v", body)
	}
	if body.Issues == nil || body.Provenance.Extractors == nil || body.Provenance.ConceptIdentitySchemaVersions == nil || body.Provenance.HumanLabelResolverVersions == nil {
		t.Fatalf("response contains null collection: %s", recorder.Body.String())
	}
	if service.calls != 1 {
		t.Fatalf("BuildV1 calls = %d", service.calls)
	}
}

func TestAnnotationDatasetQualityHandler_InvalidReportStillReturnsOK(t *testing.T) {
	service := &fakeAnnotationDatasetQualityService{report: application.ConceptAnnotationQualityReport{
		SchemaVersion:        application.ConceptAnnotationQualityReportV1SchemaVersion,
		DatasetSchemaVersion: application.ConceptAnnotationDatasetV1SchemaVersion,
		Valid:                false, ErrorCount: 1,
		Issues: []application.ConceptAnnotationQualityIssue{{Severity: "error", Code: "duplicate_unit_id", EntryID: 1, UnitID: 2, Message: "duplicate"}},
	}}
	recorder := httptest.NewRecorder()
	qualityTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/annotation-dataset/v1/quality", nil))
	if recorder.Code != http.StatusOK || !strings.Contains(recorder.Body.String(), `"valid":false`) || !strings.Contains(recorder.Body.String(), `"error_count":1`) {
		t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
	}
}

func TestAnnotationDatasetQualityHandler_FailureIsGeneric(t *testing.T) {
	service := &fakeAnnotationDatasetQualityService{err: errors.New("private dataset failure")}
	recorder := httptest.NewRecorder()
	qualityTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/annotation-dataset/v1/quality", nil))
	if recorder.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d", recorder.Code)
	}
	if got := recorder.Body.String(); !strings.Contains(got, "could not build concept annotation quality report") || strings.Contains(got, "private dataset failure") {
		t.Fatalf("body = %s", got)
	}
}

func TestAnnotationDatasetQualityHandler_IsGetOnlyAndDoesNotInvokeServiceForPost(t *testing.T) {
	service := &fakeAnnotationDatasetQualityService{}
	recorder := httptest.NewRecorder()
	qualityTestRoutes(service).ServeHTTP(recorder, httptest.NewRequest(http.MethodPost, "/annotation-dataset/v1/quality", nil))
	if recorder.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusMethodNotAllowed)
	}
	if service.calls != 0 {
		t.Fatalf("BuildV1 calls = %d, want 0", service.calls)
	}
}
