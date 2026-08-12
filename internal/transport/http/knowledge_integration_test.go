package http_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

// stubExtractor is a deterministic in-memory extractor for the full-stack test:
// it returns scripted units without contacting any network, so the HTTP ->
// service -> ruleset -> storage path is exercised end to end.
type stubExtractor struct {
	units []domain.ExtractedUnit
	err   error
}

func (s *stubExtractor) Name() string { return "stub:test:knowledge_extraction_v1" }
func (s *stubExtractor) Extract(context.Context, domain.ExtractionSource) (domain.ExtractionResult, error) {
	if s.err != nil {
		return domain.ExtractionResult{}, s.err
	}
	return domain.ExtractionResult{Units: s.units}, nil
}

func setupKnowledgeServer(t *testing.T, ex domain.Extractor) (*httptest.Server, *sqlite.EntryRepository, *sqlite.AnalysisRepository, *sqlite.FeedbackRepository) {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "kit.db")
	db, err := sqlite.Open(dbPath)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	t.Cleanup(func() { db.Close() })

	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	inventoryRepo := sqlite.NewInventoryRepository(db)
	captureRepo := sqlite.NewCaptureRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	admissionRepo := sqlite.NewAdmissionRepository(db)

	entrySvc := application.NewEntryService(entryRepo)
	analysisSvc := application.NewAnalysisService(entryRepo, analysisRepo, nil)
	feedbackSvc := application.NewFeedbackService(feedbackRepo)
	effectiveSvc := application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo)
	inventorySvc := application.NewInventoryService(inventoryRepo)
	captureSvc := application.NewCaptureService(captureRepo)
	knowledgeSvc := application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, admissionRepo, ex)

	handler := transporthttp.NewHandler(entrySvc, analysisSvc, feedbackSvc, effectiveSvc, inventorySvc, captureSvc, knowledgeSvc)
	srv := httptest.NewServer(handler.Routes())
	t.Cleanup(srv.Close)
	return srv, entryRepo, analysisRepo, feedbackRepo
}

// seedAnalyzedEntry creates an entry with an accepted analysis so it is eligible
// for extraction.
func seedAnalyzedEntry(t *testing.T, entries *sqlite.EntryRepository, analyses *sqlite.AnalysisRepository) int64 {
	t.Helper()
	ctx := context.Background()
	entry, err := entries.Create(ctx, domain.NewEntryInput{OriginalInput: "Je veux aller au marché"})
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}
	if _, err := analyses.Create(ctx, entry.ID, domain.AnalysisResult{
		Category: "grammar", Explanation: "vouloir + infinitive", Confidence: 0.8,
	}, "rule-based:test"); err != nil {
		t.Fatalf("create analysis: %v", err)
	}
	return entry.ID
}

func TestIntegration_ExtractAndAdmissionOverride(t *testing.T) {
	ex := &stubExtractor{units: []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "vouloir + inf", Statement: "vouloir takes a bare infinitive", Confidence: 0.9},
	}}
	srv, entries, analyses, _ := setupKnowledgeServer(t, ex)
	entryID := seedAnalyzedEntry(t, entries, analyses)

	// Extract.
	resp, err := http.Post(srv.URL+"/entries/"+itoa(entryID)+"/extractions", "application/json", nil)
	if err != nil {
		t.Fatalf("POST extractions: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("status = %d, want 201", resp.StatusCode)
	}
	var extraction struct {
		ID    int64 `json:"id"`
		Units []struct {
			ID        int64 `json:"id"`
			Admission struct {
				Effective string `json:"effective_state"`
			} `json:"admission"`
		} `json:"units"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&extraction); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(extraction.Units) != 1 {
		t.Fatalf("expected 1 unit, got %d", len(extraction.Units))
	}
	unitID := extraction.Units[0].ID
	if extraction.Units[0].Admission.Effective != "active" {
		t.Fatalf("expected active, got %q", extraction.Units[0].Admission.Effective)
	}

	// Human override: suppress as mastered.
	body := `{"decision":"suppressed","reason":"mastered"}`
	oResp, err := http.Post(srv.URL+"/knowledge-units/"+itoa(unitID)+"/admission-overrides", "application/json", bytes.NewReader([]byte(body)))
	if err != nil {
		t.Fatalf("POST override: %v", err)
	}
	defer oResp.Body.Close()
	if oResp.StatusCode != http.StatusCreated {
		t.Fatalf("override status = %d, want 201", oResp.StatusCode)
	}

	// Effective admission now follows the human decision.
	aResp, err := http.Get(srv.URL + "/knowledge-units/" + itoa(unitID) + "/admission")
	if err != nil {
		t.Fatalf("GET admission: %v", err)
	}
	defer aResp.Body.Close()
	var admission struct {
		MachineState string `json:"machine_state"`
		Effective    string `json:"effective_state"`
	}
	if err := json.NewDecoder(aResp.Body).Decode(&admission); err != nil {
		t.Fatalf("decode admission: %v", err)
	}
	if admission.MachineState != "active" {
		t.Fatalf("machine state should be unchanged (active), got %q", admission.MachineState)
	}
	if admission.Effective != "suppressed" {
		t.Fatalf("effective should follow human override (suppressed), got %q", admission.Effective)
	}
}

func TestIntegration_ExtractUnanalyzedNotEligible(t *testing.T) {
	srv, entries, _, _ := setupKnowledgeServer(t, &stubExtractor{})
	// Entry with no analysis.
	entry, err := entries.Create(context.Background(), domain.NewEntryInput{OriginalInput: "unanalyzed"})
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}
	resp, err := http.Post(srv.URL+"/entries/"+itoa(entry.ID)+"/extractions", "application/json", nil)
	if err != nil {
		t.Fatalf("POST: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("status = %d, want 409 (not eligible)", resp.StatusCode)
	}
}

func TestIntegration_ExtractDisabled(t *testing.T) {
	// nil extractor => disabled.
	srv, entries, analyses, _ := setupKnowledgeServer(t, nil)
	entryID := seedAnalyzedEntry(t, entries, analyses)
	resp, err := http.Post(srv.URL+"/entries/"+itoa(entryID)+"/extractions", "application/json", nil)
	if err != nil {
		t.Fatalf("POST: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503 (extractor disabled)", resp.StatusCode)
	}
}
