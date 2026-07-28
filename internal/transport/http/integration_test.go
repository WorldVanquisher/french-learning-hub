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
	entrySvc := application.NewEntryService(entryRepo)
	analysisSvc := application.NewAnalysisService(entryRepo, analysisRepo, analyzer.NewRuleBased())

	srv := httptest.NewServer(transporthttp.NewHandler(entrySvc, analysisSvc).Routes())
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
