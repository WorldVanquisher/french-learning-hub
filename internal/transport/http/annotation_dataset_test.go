package http

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

type fakeAnnotationDatasetService struct {
	records []application.ConceptAnnotationDatasetRecord
	err     error
	calls   int
}

func (f *fakeAnnotationDatasetService) ListV1(context.Context) ([]application.ConceptAnnotationDatasetRecord, error) {
	f.calls++
	return f.records, f.err
}

func annotationDatasetServer(service AnnotationDatasetService) http.Handler {
	return NewHandler(&fakeService{}, nil, nil, nil, nil, nil, nil, nil, nil, service).Routes()
}

func annotationDatasetTestRecord(unitID, conceptID int64) application.ConceptAnnotationDatasetRecord {
	createdAt := time.Date(2026, time.February, 3, 4, 5, 6, 0, time.UTC)
	concept := domain.KnowledgeConcept{
		ID: conceptID, IdentitySchemaVersion: domain.ConceptIdentitySchemaVersion,
		Target: "conditionnel présent", PedagogicalIntent: "polite request",
		IdentityFeatures: map[string]string{"mood": "conditional"}, Signature: "signature",
		Lifecycle: domain.LifecycleNormal, Support: domain.SupportSupported,
		State: domain.ConceptActive, CreatedAt: createdAt, UpdatedAt: createdAt,
	}
	decision := domain.UnitConceptLink{
		ID: 501, UnitID: unitID, ConceptID: conceptID, Relation: domain.RelationSame,
		Status: domain.LinkAccepted, DecisionSource: domain.SourceHuman,
		ResolverVersion: domain.ConceptResolverVersion, Evidence: `{"reason":"human_same"}`, CreatedAt: createdAt,
	}
	membership := domain.CurrentConceptMembership{
		UnitID: unitID, ConceptID: conceptID, LinkID: decision.ID, UpdatedAt: createdAt,
	}
	admission := domain.ResolveAdmission(domain.AdmissionRecommendation{
		Ruleset: domain.AdmissionRulesetName, State: domain.AdmissionActive, Reason: domain.ReasonDefaultActive,
	}, nil)
	return application.ConceptAnnotationDatasetRecord{
		SchemaVersion: application.ConceptAnnotationDatasetV1SchemaVersion,
		Unit: domain.KnowledgeUnit{
			ID: unitID, ExtractionID: 9, Ordinal: 1, Kind: domain.KindGrammar,
			Canonical: "conditionnel présent", Statement: "Used for polite requests.",
			Confidence: 0.95, CreatedAt: createdAt,
		},
		Source: application.ConceptAnnotationDatasetSource{
			EntryID: 7, ExtractionID: 9, ExtractionVersion: 2,
			SourceAnalysisID: 8, Extractor: "openai:test:knowledge_extraction_v1",
			ExtractionCreatedAt: createdAt,
		},
		Admission: admission,
		EffectiveAnnotation: application.ConceptAnnotationDatasetEffectiveAnnotation{
			UnitID: unitID, Status: domain.EffectiveAnnotationResolved,
			CurrentSame: &application.ConceptAnnotationDatasetSame{
				Concept: concept, Membership: membership, Decision: decision,
			},
			Distinctions: []application.ConceptAnnotationDatasetDistinction{},
			Relations:    []application.ConceptAnnotationDatasetRelation{},
		},
		HumanLabels: application.ConceptAnnotationHumanLabels{
			Same: &application.HumanSameLabel{
				ConceptID: conceptID, EventID: decision.ID,
				ResolverVersion: decision.ResolverVersion, CreatedAt: createdAt,
			},
			Distinctions: []application.HumanDistinctLabel{},
			Relations:    []application.HumanRelationLabel{},
		},
	}
}

func TestAnnotationDatasetJSONAndJSONLAreEquivalentVersionedRecords(t *testing.T) {
	records := []application.ConceptAnnotationDatasetRecord{
		annotationDatasetTestRecord(101, 20),
		annotationDatasetTestRecord(102, 21),
	}
	service := &fakeAnnotationDatasetService{records: records}
	server := annotationDatasetServer(service)

	jsonRequest := httptest.NewRequest(http.MethodGet, "/annotation-dataset/v1", nil)
	jsonRecorder := httptest.NewRecorder()
	server.ServeHTTP(jsonRecorder, jsonRequest)
	if jsonRecorder.Code != http.StatusOK {
		t.Fatalf("JSON status = %d, body=%s", jsonRecorder.Code, jsonRecorder.Body.String())
	}
	var jsonBody annotationDatasetResponse
	if err := json.Unmarshal(jsonRecorder.Body.Bytes(), &jsonBody); err != nil {
		t.Fatalf("decode JSON endpoint: %v", err)
	}
	if jsonBody.SchemaVersion != application.ConceptAnnotationDatasetV1SchemaVersion || len(jsonBody.Records) != 2 {
		t.Fatalf("JSON envelope = %+v", jsonBody)
	}
	first := jsonBody.Records[0]
	if first.Source.EntryID != 7 || first.Admission.Effective != "active" || first.EffectiveAnnotation.CurrentSame == nil {
		t.Fatalf("provenance/admission/SAME missing: %+v", first)
	}
	if first.EffectiveAnnotation.CurrentSame.Concept.Target != "conditionnel présent" || first.HumanLabels.Same == nil {
		t.Fatalf("Concept or human SAME missing: %+v", first)
	}

	exportRequest := httptest.NewRequest(http.MethodGet, "/annotation-dataset/v1/export", nil)
	exportRecorder := httptest.NewRecorder()
	server.ServeHTTP(exportRecorder, exportRequest)
	if exportRecorder.Code != http.StatusOK {
		t.Fatalf("export status = %d, body=%s", exportRecorder.Code, exportRecorder.Body.String())
	}
	if contentType := exportRecorder.Header().Get("Content-Type"); contentType != "application/x-ndjson; charset=utf-8" {
		t.Fatalf("Content-Type = %q", contentType)
	}

	var exported []annotationDatasetRecordResponse
	scanner := bufio.NewScanner(strings.NewReader(exportRecorder.Body.String()))
	for scanner.Scan() {
		var record annotationDatasetRecordResponse
		if err := json.Unmarshal(scanner.Bytes(), &record); err != nil {
			t.Fatalf("decode JSONL line: %v", err)
		}
		if record.SchemaVersion != application.ConceptAnnotationDatasetV1SchemaVersion {
			t.Fatalf("JSONL schema_version = %q", record.SchemaVersion)
		}
		exported = append(exported, record)
	}
	if err := scanner.Err(); err != nil {
		t.Fatalf("scan JSONL: %v", err)
	}
	if !reflect.DeepEqual(exported, jsonBody.Records) {
		t.Fatalf("JSONL records differ from JSON records:\nJSON=%+v\nJSONL=%+v", jsonBody.Records, exported)
	}
	if service.calls != 2 {
		t.Fatalf("ListV1 calls = %d, want once per endpoint", service.calls)
	}
}

func TestAnnotationDatasetEmptyJSONUsesEmptyArray(t *testing.T) {
	server := annotationDatasetServer(&fakeAnnotationDatasetService{records: []application.ConceptAnnotationDatasetRecord{}})
	req := httptest.NewRequest(http.MethodGet, "/annotation-dataset/v1", nil)
	rec := httptest.NewRecorder()
	server.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), `"schema_version":"concept_annotation_dataset_v1"`) || !strings.Contains(rec.Body.String(), `"records":[]`) {
		t.Fatalf("empty response = %s", rec.Body.String())
	}
}

func TestAnnotationDatasetInternalErrorsReturnGeneric500(t *testing.T) {
	server := annotationDatasetServer(&fakeAnnotationDatasetService{
		err: errors.New("SQL detail and secret-provider-value"),
	})
	for _, path := range []string{"/annotation-dataset/v1", "/annotation-dataset/v1/export"} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		rec := httptest.NewRecorder()
		server.ServeHTTP(rec, req)
		if rec.Code != http.StatusInternalServerError {
			t.Fatalf("%s status = %d", path, rec.Code)
		}
		if strings.Contains(rec.Body.String(), "SQL detail") || strings.Contains(rec.Body.String(), "secret-provider-value") {
			t.Fatalf("%s leaked internal error: %s", path, rec.Body.String())
		}
	}
}

func TestAnnotationDatasetRoutesAreGETOnly(t *testing.T) {
	service := &fakeAnnotationDatasetService{}
	server := annotationDatasetServer(service)
	for _, path := range []string{"/annotation-dataset/v1", "/annotation-dataset/v1/export"} {
		req := httptest.NewRequest(http.MethodPost, path, strings.NewReader(`{}`))
		rec := httptest.NewRecorder()
		server.ServeHTTP(rec, req)
		if rec.Code != http.StatusMethodNotAllowed {
			t.Fatalf("POST %s status = %d, want 405", path, rec.Code)
		}
	}
	if service.calls != 0 {
		t.Fatalf("GET-only service invoked by mutation method: %d", service.calls)
	}
}
