package http_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strconv"
	"testing"

	"french-learning-app/internal/analyzer"
	"french-learning-app/internal/application"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

// setupServer wires the real layers (sqlite + analyzer + services + handlers)
// over a temporary database and returns a running test server.
func setupServer(t *testing.T) *httptest.Server {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "it.db")
	db, err := sqlite.Open(dbPath)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	t.Cleanup(func() { db.Close() })

	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	entrySvc := application.NewEntryService(entryRepo)
	analysisSvc := application.NewAnalysisService(entryRepo, analysisRepo, analyzer.NewRuleBased())
	feedbackSvc := application.NewFeedbackService(feedbackRepo)

	srv := httptest.NewServer(transporthttp.NewHandler(entrySvc, analysisSvc, feedbackSvc).Routes())
	t.Cleanup(srv.Close)
	return srv
}

func TestIntegration_EntryAnalysisWorkflow(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	// 1. Create an entry.
	createBody := `{"original_input":"Qu'est-ce que c'est?","original_context":"overheard"}`
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, srv.URL+"/entries", bytes.NewBufferString(createBody))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("create entry status = %d, want 201", resp.StatusCode)
	}
	var entry struct {
		ID int64 `json:"id"`
	}
	decodeBody(t, resp, &entry)
	if entry.ID == 0 {
		t.Fatal("expected non-zero entry id")
	}

	// 2. Analyze it twice; versions should increment.
	first := postAnalysis(t, ctx, srv.URL, entry.ID)
	if first.Version != 1 {
		t.Fatalf("first analysis version = %d, want 1", first.Version)
	}
	if first.Category != "question" {
		t.Fatalf("expected category 'question', got %q", first.Category)
	}
	if first.Analyzer != "rule-based" {
		t.Fatalf("expected analyzer 'rule-based', got %q", first.Analyzer)
	}

	second := postAnalysis(t, ctx, srv.URL, entry.ID)
	if second.Version != 2 {
		t.Fatalf("second analysis version = %d, want 2", second.Version)
	}

	// 3. List analyses; expect both, oldest first.
	req, _ = http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/entries/"+itoa(entry.ID)+"/analyses", nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("list analyses: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("list status = %d, want 200", resp.StatusCode)
	}
	var listed struct {
		Analyses []struct {
			Version int64 `json:"version"`
		} `json:"analyses"`
	}
	decodeBody(t, resp, &listed)
	if len(listed.Analyses) != 2 {
		t.Fatalf("expected 2 analyses, got %d", len(listed.Analyses))
	}
	if listed.Analyses[0].Version != 1 || listed.Analyses[1].Version != 2 {
		t.Fatalf("unexpected version order: %+v", listed.Analyses)
	}

	// 4. Original entry data must be unchanged after analysis.
	req, _ = http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/entries/"+itoa(entry.ID), nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get entry: %v", err)
	}
	var reloaded struct {
		OriginalInput   string `json:"original_input"`
		OriginalContext string `json:"original_context"`
	}
	decodeBody(t, resp, &reloaded)
	if reloaded.OriginalInput != "Qu'est-ce que c'est?" || reloaded.OriginalContext != "overheard" {
		t.Fatalf("original entry data changed: %+v", reloaded)
	}
}

func TestIntegration_AnalyzeMissingEntry(t *testing.T) {
	srv := setupServer(t)
	req, _ := http.NewRequestWithContext(context.Background(), http.MethodPost, srv.URL+"/entries/999/analysis", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", resp.StatusCode)
	}
	resp.Body.Close()
}

// TestIntegration_FeedbackWorkflow exercises the full stack: create entry ->
// analyze -> add multiple feedback records -> list them, and proves that
// feedback never alters the original entry or the analysis it references.
func TestIntegration_FeedbackWorkflow(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	// Create entry + analysis.
	createBody := `{"original_input":"Je mange une pomme","original_context":"describing lunch"}`
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, srv.URL+"/entries", bytes.NewBufferString(createBody))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}
	var entry struct {
		ID int64 `json:"id"`
	}
	decodeBody(t, resp, &entry)

	analysis := postAnalysisFull(t, ctx, srv.URL, entry.ID)

	// Add three feedback records of different statuses.
	postFeedback(t, ctx, srv.URL, analysis.ID, `{"status":"rejected","user_note":"not a phrase"}`, http.StatusCreated)
	postFeedback(t, ctx, srv.URL, analysis.ID,
		`{"status":"corrected","corrected_category":"grammar","corrected_explanation":"present tense of manger"}`,
		http.StatusCreated)
	postFeedback(t, ctx, srv.URL, analysis.ID, `{"status":"accepted"}`, http.StatusCreated)

	// List feedback; history preserved, oldest first.
	req, _ = http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/analyses/"+itoa(analysis.ID)+"/feedback", nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("list feedback: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("list feedback status = %d, want 200", resp.StatusCode)
	}
	var listed struct {
		Feedback []struct {
			Status               string  `json:"status"`
			CorrectedCategory    *string `json:"corrected_category"`
			CorrectedExplanation *string `json:"corrected_explanation"`
		} `json:"feedback"`
	}
	decodeBody(t, resp, &listed)
	if len(listed.Feedback) != 3 {
		t.Fatalf("expected 3 feedback records, got %d", len(listed.Feedback))
	}
	if listed.Feedback[0].Status != "rejected" || listed.Feedback[2].Status != "accepted" {
		t.Fatalf("unexpected feedback order: %+v", listed.Feedback)
	}
	if listed.Feedback[1].CorrectedCategory == nil || *listed.Feedback[1].CorrectedCategory != "grammar" {
		t.Fatalf("correction not preserved: %+v", listed.Feedback[1])
	}

	// Prove immutability: the analysis is unchanged despite the "corrected" feedback.
	req, _ = http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/entries/"+itoa(entry.ID)+"/analyses", nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("list analyses: %v", err)
	}
	var analyses struct {
		Analyses []struct {
			ID          int64  `json:"id"`
			Category    string `json:"category"`
			Explanation string `json:"explanation"`
		} `json:"analyses"`
	}
	decodeBody(t, resp, &analyses)
	if len(analyses.Analyses) != 1 {
		t.Fatalf("expected 1 analysis, got %d", len(analyses.Analyses))
	}
	if analyses.Analyses[0].Category != analysis.Category || analyses.Analyses[0].Explanation != analysis.Explanation {
		t.Fatalf("analysis mutated by feedback: got %+v, want category=%q explanation=%q",
			analyses.Analyses[0], analysis.Category, analysis.Explanation)
	}

	// And the original entry is unchanged.
	req, _ = http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/entries/"+itoa(entry.ID), nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get entry: %v", err)
	}
	var reloaded struct {
		OriginalInput   string `json:"original_input"`
		OriginalContext string `json:"original_context"`
	}
	decodeBody(t, resp, &reloaded)
	if reloaded.OriginalInput != "Je mange une pomme" || reloaded.OriginalContext != "describing lunch" {
		t.Fatalf("original entry changed: %+v", reloaded)
	}
}

func TestIntegration_FeedbackMissingAnalysis(t *testing.T) {
	srv := setupServer(t)
	body := bytes.NewBufferString(`{"status":"accepted"}`)
	req, _ := http.NewRequestWithContext(context.Background(), http.MethodPost, srv.URL+"/analyses/999/feedback", body)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", resp.StatusCode)
	}
	resp.Body.Close()
}

// ---- helpers ----

type analysisBody struct {
	Version  int64  `json:"version"`
	Category string `json:"category"`
	Analyzer string `json:"analyzer"`
}

func postAnalysis(t *testing.T, ctx context.Context, baseURL string, entryID int64) analysisBody {
	t.Helper()
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, baseURL+"/entries/"+itoa(entryID)+"/analysis", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("post analysis: %v", err)
	}
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("post analysis status = %d, want 201", resp.StatusCode)
	}
	var body analysisBody
	decodeBody(t, resp, &body)
	return body
}

type analysisFull struct {
	ID          int64  `json:"id"`
	Category    string `json:"category"`
	Explanation string `json:"explanation"`
}

// postAnalysisFull creates an analysis and returns its id and metadata.
func postAnalysisFull(t *testing.T, ctx context.Context, baseURL string, entryID int64) analysisFull {
	t.Helper()
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, baseURL+"/entries/"+itoa(entryID)+"/analysis", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("post analysis: %v", err)
	}
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("post analysis status = %d, want 201", resp.StatusCode)
	}
	var body analysisFull
	decodeBody(t, resp, &body)
	return body
}

// postFeedback posts a feedback body to an analysis and asserts the status.
func postFeedback(t *testing.T, ctx context.Context, baseURL string, analysisID int64, body string, wantStatus int) {
	t.Helper()
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, baseURL+"/analyses/"+itoa(analysisID)+"/feedback", bytes.NewBufferString(body))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("post feedback: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != wantStatus {
		t.Fatalf("post feedback status = %d, want %d", resp.StatusCode, wantStatus)
	}
}

func decodeBody(t *testing.T, resp *http.Response, v any) {
	t.Helper()
	defer resp.Body.Close()
	if err := json.NewDecoder(resp.Body).Decode(v); err != nil {
		t.Fatalf("decode body: %v", err)
	}
}

func itoa(n int64) string {
	return strconv.FormatInt(n, 10)
}
