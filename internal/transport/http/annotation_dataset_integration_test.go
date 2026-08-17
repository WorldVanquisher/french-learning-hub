package http_test

import (
	"encoding/json"
	"net/http"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

func TestIntegration_AnnotationDatasetUsesCurrentExtractionAndPreservesProvenance(t *testing.T) {
	srv, entryID := setupConceptServer(t, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "vouloir + infinitif", Statement: "first", Confidence: 0.9},
		{Kind: domain.KindGrammar, Canonical: "vouloir + infinitif", Statement: "duplicate", Confidence: 0.9},
		{Kind: domain.KindVocabulary, Canonical: "éphémère", Statement: "low confidence", Confidence: 0.2},
	})
	historicalIDs := extractUnits(t, srv, entryID)
	currentIDs := extractUnits(t, srv, entryID)
	if len(historicalIDs) != 3 || len(currentIDs) != 3 {
		t.Fatalf("unit ids: historical=%v current=%v", historicalIDs, currentIDs)
	}

	resp, err := http.Get(srv.URL + "/annotation-dataset/v1")
	if err != nil {
		t.Fatalf("GET annotation dataset: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	var body struct {
		SchemaVersion string `json:"schema_version"`
		Records       []struct {
			SchemaVersion string `json:"schema_version"`
			Unit          struct {
				ID           int64 `json:"id"`
				ExtractionID int64 `json:"extraction_id"`
				Ordinal      int   `json:"ordinal"`
			} `json:"unit"`
			Source struct {
				EntryID             int64  `json:"entry_id"`
				ExtractionID        int64  `json:"extraction_id"`
				ExtractionVersion   int64  `json:"extraction_version"`
				SourceAnalysisID    int64  `json:"source_analysis_id"`
				Extractor           string `json:"extractor"`
				ExtractionCreatedAt string `json:"extraction_created_at"`
			} `json:"source"`
			Admission struct {
				Ruleset       string `json:"ruleset"`
				MachineState  string `json:"machine_state"`
				MachineReason string `json:"machine_reason"`
				Effective     string `json:"effective_state"`
			} `json:"admission"`
			EffectiveAnnotation struct {
				Status string `json:"status"`
			} `json:"effective_annotation"`
		} `json:"records"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode annotation dataset: %v", err)
	}
	if body.SchemaVersion != application.ConceptAnnotationDatasetV1SchemaVersion || len(body.Records) != 3 {
		t.Fatalf("dataset envelope = %+v", body)
	}
	wantAdmission := []string{"active", "suppressed", "needs_review"}
	for i, record := range body.Records {
		if record.SchemaVersion != application.ConceptAnnotationDatasetV1SchemaVersion {
			t.Fatalf("records[%d] schema = %q", i, record.SchemaVersion)
		}
		if record.Unit.ID != currentIDs[i] || record.Unit.Ordinal != i+1 {
			t.Fatalf("records[%d] unit = %+v, current=%v", i, record.Unit, currentIDs)
		}
		for _, historicalID := range historicalIDs {
			if record.Unit.ID == historicalID {
				t.Fatalf("historical unit %d leaked into dataset", historicalID)
			}
		}
		if record.Source.EntryID != entryID || record.Source.ExtractionVersion != 2 || record.Source.SourceAnalysisID == 0 || record.Source.Extractor == "" || record.Source.ExtractionCreatedAt == "" {
			t.Fatalf("records[%d] source provenance = %+v", i, record.Source)
		}
		if record.Unit.ExtractionID == 0 || record.Source.ExtractionID != record.Unit.ExtractionID {
			t.Fatalf("records[%d] extraction mismatch: unit=%+v source=%+v", i, record.Unit, record.Source)
		}
		if record.Admission.Ruleset != domain.AdmissionRulesetName || record.Admission.MachineState != wantAdmission[i] || record.Admission.Effective != wantAdmission[i] {
			t.Fatalf("records[%d] admission = %+v", i, record.Admission)
		}
		if record.Admission.MachineReason == "" || record.EffectiveAnnotation.Status != "unresolved" {
			t.Fatalf("records[%d] admission/annotation = %+v %+v", i, record.Admission, record.EffectiveAnnotation)
		}
	}
}

func TestIntegration_AnnotationDatasetEmptyWithoutCurrentExtractions(t *testing.T) {
	srv, _ := setupConceptServer(t, []domain.ExtractedUnit{{
		Kind: domain.KindGrammar, Canonical: "unused", Statement: "unused", Confidence: 0.9,
	}})

	resp, err := http.Get(srv.URL + "/annotation-dataset/v1")
	if err != nil {
		t.Fatalf("GET annotation dataset: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	var body struct {
		SchemaVersion string            `json:"schema_version"`
		Records       []json.RawMessage `json:"records"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.SchemaVersion != application.ConceptAnnotationDatasetV1SchemaVersion || body.Records == nil || len(body.Records) != 0 {
		t.Fatalf("empty dataset = %+v", body)
	}
}

func TestIntegration_AnnotationDatasetQualityConsumesRealCurrentDataset(t *testing.T) {
	srv, entryID := setupConceptServer(t, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "vouloir + infinitif", Statement: "grammar", Confidence: 0.9},
		{Kind: domain.KindVocabulary, Canonical: "éphémère", Statement: "vocabulary", Confidence: 0.9},
	})
	extractUnits(t, srv, entryID)

	resp, err := http.Get(srv.URL + "/annotation-dataset/v1/quality")
	if err != nil {
		t.Fatalf("GET annotation dataset quality: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	var body struct {
		SchemaVersion        string `json:"schema_version"`
		DatasetSchemaVersion string `json:"dataset_schema_version"`
		Valid                bool   `json:"valid"`
		ErrorCount           int    `json:"error_count"`
		Summary              struct {
			TotalRecords     int `json:"total_records"`
			TotalEntries     int `json:"total_entries"`
			TotalExtractions int `json:"total_extractions"`
			EffectiveStatus  struct {
				Unresolved int `json:"unresolved"`
			} `json:"effective_status"`
		} `json:"summary"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode quality report: %v", err)
	}
	if body.SchemaVersion != application.ConceptAnnotationQualityReportV1SchemaVersion || body.DatasetSchemaVersion != application.ConceptAnnotationDatasetV1SchemaVersion {
		t.Fatalf("schema versions = %q, %q", body.SchemaVersion, body.DatasetSchemaVersion)
	}
	if !body.Valid || body.ErrorCount != 0 || body.Summary.TotalRecords != 2 || body.Summary.TotalEntries != 1 || body.Summary.TotalExtractions != 1 || body.Summary.EffectiveStatus.Unresolved != 2 {
		t.Fatalf("quality report = %+v", body)
	}
}
