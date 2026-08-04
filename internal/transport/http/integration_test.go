package http_test

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"french-learning-app/internal/analyzer"
	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

// setupServer wires the real layers over a temporary database using the default
// rule-based analyzer, and returns a running test server.
func setupServer(t *testing.T) *httptest.Server {
	return setupServerWithAnalyzer(t, analyzer.NewRuleBased())
}

// setupServerWithAnalyzer is like setupServer but lets a test inject any
// domain.Analyzer (e.g. an OpenAI analyzer pointed at a fake provider), so the
// full HTTP -> service -> analyzer -> storage path can be exercised.
func setupServerWithAnalyzer(t *testing.T, an domain.Analyzer) *httptest.Server {
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
	inventoryRepo := sqlite.NewInventoryRepository(db)
	entrySvc := application.NewEntryService(entryRepo)
	analysisSvc := application.NewAnalysisService(entryRepo, analysisRepo, an)
	feedbackSvc := application.NewFeedbackService(feedbackRepo)
	effectiveSvc := application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo)
	inventorySvc := application.NewInventoryService(inventoryRepo)

	srv := httptest.NewServer(transporthttp.NewHandler(entrySvc, analysisSvc, feedbackSvc, effectiveSvc, inventorySvc).Routes())
	t.Cleanup(srv.Close)
	return srv
}

func TestIntegration_EntryAnalysisWorkflow(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	// 1. Create an entry. An explicit whole-utterance comprehension request:
	// a bare "?" no longer forces the comprehension category (milestone 6).
	createBody := `{"original_input":"What does this sentence mean?","original_context":"overheard"}`
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
	if first.Category != "comprehension" {
		t.Fatalf("expected category 'comprehension', got %q", first.Category)
	}
	if first.Analyzer != wantRuleBasedProvenance {
		t.Fatalf("expected analyzer %q, got %q", wantRuleBasedProvenance, first.Analyzer)
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
	if reloaded.OriginalInput != "What does this sentence mean?" || reloaded.OriginalContext != "overheard" {
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

// TestIntegration_FeedbackCorrectedSingleField proves that, over the full HTTP
// stack with real validation, a "corrected" feedback carrying only one of the
// two corrected fields is accepted and stored.
func TestIntegration_FeedbackCorrectedSingleField(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, srv.URL+"/entries",
		bytes.NewBufferString(`{"original_input":"Je mange","original_context":"lunch"}`))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}
	var entry struct {
		ID int64 `json:"id"`
	}
	decodeBody(t, resp, &entry)

	analysis := postAnalysisFull(t, ctx, srv.URL, entry.ID)

	// Category only: accepted (201).
	req, _ = http.NewRequestWithContext(ctx, http.MethodPost, srv.URL+"/analyses/"+itoa(analysis.ID)+"/feedback",
		bytes.NewBufferString(`{"status":"corrected","corrected_category":"grammar"}`))
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("post feedback: %v", err)
	}
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("category-only correction status = %d, want 201", resp.StatusCode)
	}
	var created struct {
		Status               string  `json:"status"`
		CorrectedCategory    *string `json:"corrected_category"`
		CorrectedExplanation *string `json:"corrected_explanation"`
	}
	decodeBody(t, resp, &created)
	if created.Status != "corrected" {
		t.Fatalf("status = %q, want corrected", created.Status)
	}
	if created.CorrectedCategory == nil || *created.CorrectedCategory != "grammar" {
		t.Fatalf("corrected_category not stored: %v", created.CorrectedCategory)
	}
	if created.CorrectedExplanation != nil {
		t.Fatalf("corrected_explanation should be absent, got %v", created.CorrectedExplanation)
	}

	// Explanation only: also accepted (201).
	postFeedback(t, ctx, srv.URL, analysis.ID, `{"status":"corrected","corrected_explanation":"present tense"}`, http.StatusCreated)
}

// fakeProviderResponse builds a well-formed OpenAI Responses API body whose
// structured output encodes the given analysis fields.
func fakeProviderResponse(t *testing.T, category, explanation string, confidence float64) string {
	t.Helper()
	inner, err := json.Marshal(map[string]any{
		"category":    category,
		"explanation": explanation,
		"confidence":  confidence,
		"uncertainty": "",
	})
	if err != nil {
		t.Fatalf("marshal inner payload: %v", err)
	}
	outer, err := json.Marshal(map[string]any{
		"status": "completed",
		"output": []map[string]any{{
			"type": "message",
			"content": []map[string]any{{
				"type": "output_text",
				"text": string(inner),
			}},
		}},
	})
	if err != nil {
		t.Fatalf("marshal outer response: %v", err)
	}
	return string(outer)
}

// wantRuleBasedProvenance is the versioned provenance the local rule engine
// stores (milestone 6): "rule-based:<ruleset>:<taxonomy>".
const wantRuleBasedProvenance = "rule-based:v2:fr_l2_taxonomy_v1"

// TestIntegration_DefaultProviderRuleBased confirms the default wiring uses the
// local rule-based analyzer, the safe no-cost default, and records its versioned
// provenance.
func TestIntegration_DefaultProviderRuleBased(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Bonjour","original_context":""}`)
	a := postAnalysis(t, ctx, srv.URL, entryID)
	if a.Analyzer != wantRuleBasedProvenance {
		t.Fatalf("default analyzer = %q, want %q", a.Analyzer, wantRuleBasedProvenance)
	}
}

// TestIntegration_OpenAISuccessCreatesOneAnalysis exercises the full stack with
// an OpenAI analyzer pointed at a fake provider: one analysis is created and the
// stored provenance carries provider/model/prompt version.
func TestIntegration_OpenAISuccessCreatesOneAnalysis(t *testing.T) {
	provider := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, fakeProviderResponse(t, "grammar", "present tense", 0.85))
	}))
	t.Cleanup(provider.Close)

	an := analyzer.NewOpenAIWithClient("sk-test", "gpt-test", provider.URL, provider.Client())
	srv := setupServerWithAnalyzer(t, an)
	ctx := context.Background()

	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Je mange","original_context":"lunch"}`)

	// Create one analysis; provenance should identify the OpenAI provider.
	a := postAnalysis(t, ctx, srv.URL, entryID)
	if a.Category != "grammar" {
		t.Fatalf("category = %q, want grammar", a.Category)
	}
	wantProvenance := "openai:gpt-test:fr_l2_taxonomy_v1"
	if a.Analyzer != wantProvenance {
		t.Fatalf("provenance = %q, want %q", a.Analyzer, wantProvenance)
	}

	// Exactly one analysis stored.
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/entries/"+itoa(entryID)+"/analyses", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("list analyses: %v", err)
	}
	var listed struct {
		Analyses []struct {
			Analyzer string `json:"analyzer"`
		} `json:"analyses"`
	}
	decodeBody(t, resp, &listed)
	if len(listed.Analyses) != 1 {
		t.Fatalf("expected 1 analysis, got %d", len(listed.Analyses))
	}

	// Original entry data is unchanged after an OpenAI analysis.
	req, _ = http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/entries/"+itoa(entryID), nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get entry: %v", err)
	}
	var reloaded struct {
		OriginalInput   string `json:"original_input"`
		OriginalContext string `json:"original_context"`
	}
	decodeBody(t, resp, &reloaded)
	if reloaded.OriginalInput != "Je mange" || reloaded.OriginalContext != "lunch" {
		t.Fatalf("original entry changed: %+v", reloaded)
	}
}

// TestIntegration_OpenAIProviderFailureCreatesNoAnalysis proves a provider 500
// yields HTTP 502 and stores no analysis row.
func TestIntegration_OpenAIProviderFailureCreatesNoAnalysis(t *testing.T) {
	provider := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		io.WriteString(w, `{"error":{"message":"boom"}}`)
	}))
	t.Cleanup(provider.Close)

	an := analyzer.NewOpenAIWithClient("sk-test", "gpt-test", provider.URL, provider.Client())
	srv := setupServerWithAnalyzer(t, an)
	ctx := context.Background()

	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Je mange","original_context":"lunch"}`)

	// Provider 5xx -> 502.
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, srv.URL+"/entries/"+itoa(entryID)+"/analysis", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("post analysis: %v", err)
	}
	if resp.StatusCode != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502", resp.StatusCode)
	}
	resp.Body.Close()

	// No analysis stored.
	req, _ = http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/entries/"+itoa(entryID)+"/analyses", nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("list analyses: %v", err)
	}
	var listed struct {
		Analyses []json.RawMessage `json:"analyses"`
	}
	decodeBody(t, resp, &listed)
	if len(listed.Analyses) != 0 {
		t.Fatalf("expected 0 analyses after provider failure, got %d", len(listed.Analyses))
	}
}

// TestIntegration_OpenAITimeoutMapsTo504 proves a provider timeout maps to 504.
func TestIntegration_OpenAITimeoutMapsTo504(t *testing.T) {
	// The handler stalls longer than the client's timeout so the client aborts
	// first (producing the 504). It returns on context cancellation or a bounded
	// timer, whichever comes first, so provider.Close() never deadlocks.
	provider := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-r.Context().Done():
		case <-time.After(2 * time.Second):
		}
	}))
	t.Cleanup(provider.Close)

	an := analyzer.NewOpenAIWithClient("sk-test", "gpt-test", provider.URL,
		&http.Client{Timeout: 50 * time.Millisecond})
	srv := setupServerWithAnalyzer(t, an)
	ctx := context.Background()

	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Je mange","original_context":"lunch"}`)

	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, srv.URL+"/entries/"+itoa(entryID)+"/analysis", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("post analysis: %v", err)
	}
	if resp.StatusCode != http.StatusGatewayTimeout {
		t.Fatalf("status = %d, want 504", resp.StatusCode)
	}
	resp.Body.Close()
}

// effectiveBody mirrors the effective-analysis response shape.
type effectiveBody struct {
	AnalysisID int64 `json:"analysis_id"`
	EntryID    int64 `json:"entry_id"`
	Version    int64 `json:"version"`
	Original   struct {
		Category    string `json:"category"`
		Explanation string `json:"explanation"`
	} `json:"original"`
	Effective *struct {
		Category    string `json:"category"`
		Explanation string `json:"explanation"`
	} `json:"effective"`
	Resolution string `json:"resolution"`
	FeedbackID *int64 `json:"feedback_id"`
}

// getEffective fetches and decodes the effective analysis for an analysis id.
func getEffective(t *testing.T, ctx context.Context, baseURL string, analysisID int64) effectiveBody {
	t.Helper()
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, baseURL+"/analyses/"+itoa(analysisID)+"/effective", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get effective: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("effective status = %d, want 200", resp.StatusCode)
	}
	var body effectiveBody
	decodeBody(t, resp, &body)
	return body
}

func TestIntegration_Effective_Unreviewed(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Je mange une pomme","original_context":"lunch"}`)
	analysis := postAnalysisFull(t, ctx, srv.URL, entryID)

	eff := getEffective(t, ctx, srv.URL, analysis.ID)
	if eff.Resolution != "unreviewed" {
		t.Fatalf("resolution = %q, want unreviewed", eff.Resolution)
	}
	if eff.Effective == nil {
		t.Fatal("effective should be present for unreviewed")
	}
	if eff.Effective.Category != analysis.Category || eff.Effective.Explanation != analysis.Explanation {
		t.Fatalf("effective should equal original: got %+v, orig cat=%q expl=%q", eff.Effective, analysis.Category, analysis.Explanation)
	}
	if eff.FeedbackID != nil {
		t.Fatalf("feedback id should be null, got %d", *eff.FeedbackID)
	}
}

func TestIntegration_Effective_Accepted(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Je mange une pomme","original_context":"lunch"}`)
	analysis := postAnalysisFull(t, ctx, srv.URL, entryID)

	fbID := postFeedback(t, ctx, srv.URL, analysis.ID, `{"status":"accepted"}`, http.StatusCreated)

	eff := getEffective(t, ctx, srv.URL, analysis.ID)
	if eff.Resolution != "accepted" {
		t.Fatalf("resolution = %q, want accepted", eff.Resolution)
	}
	if eff.Effective == nil || eff.Effective.Category != analysis.Category || eff.Effective.Explanation != analysis.Explanation {
		t.Fatalf("accepted effective should equal original, got %+v", eff.Effective)
	}
	if eff.FeedbackID == nil || *eff.FeedbackID != fbID {
		t.Fatalf("feedback id = %v, want %d (the accepted feedback)", eff.FeedbackID, fbID)
	}
}

func TestIntegration_Effective_CorrectedCategoryOnly(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Je mange une pomme","original_context":"lunch"}`)
	analysis := postAnalysisFull(t, ctx, srv.URL, entryID)

	fbID := postFeedback(t, ctx, srv.URL, analysis.ID, `{"status":"corrected","corrected_category":"morphology"}`, http.StatusCreated)

	eff := getEffective(t, ctx, srv.URL, analysis.ID)
	if eff.Resolution != "corrected" {
		t.Fatalf("resolution = %q, want corrected", eff.Resolution)
	}
	if eff.Effective.Category != "morphology" {
		t.Fatalf("effective category = %q, want morphology", eff.Effective.Category)
	}
	if eff.Effective.Explanation != analysis.Explanation {
		t.Fatalf("effective explanation should retain original %q, got %q", analysis.Explanation, eff.Effective.Explanation)
	}
	// Original must still reflect the stored analysis.
	if eff.Original.Category != analysis.Category || eff.Original.Explanation != analysis.Explanation {
		t.Fatalf("original mutated: got %+v, want cat=%q expl=%q", eff.Original, analysis.Category, analysis.Explanation)
	}
	if eff.FeedbackID == nil || *eff.FeedbackID != fbID {
		t.Fatalf("feedback id = %v, want %d", eff.FeedbackID, fbID)
	}
}

func TestIntegration_Effective_CorrectedBothFields(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Je mange une pomme","original_context":"lunch"}`)
	analysis := postAnalysisFull(t, ctx, srv.URL, entryID)

	fbID := postFeedback(t, ctx, srv.URL, analysis.ID, `{"status":"corrected","corrected_category":"morphology","corrected_explanation":"present tense of manger"}`, http.StatusCreated)

	eff := getEffective(t, ctx, srv.URL, analysis.ID)
	if eff.Resolution != "corrected" {
		t.Fatalf("resolution = %q, want corrected", eff.Resolution)
	}
	// Both supplied corrected fields must override their originals.
	if eff.Effective.Category != "morphology" || eff.Effective.Explanation != "present tense of manger" {
		t.Fatalf("both corrected fields should override, got %+v", eff.Effective)
	}
	// The original pair must be preserved and must differ from the effective one.
	if eff.Original.Category != analysis.Category || eff.Original.Explanation != analysis.Explanation {
		t.Fatalf("original mutated: got %+v", eff.Original)
	}
	if eff.FeedbackID == nil || *eff.FeedbackID != fbID {
		t.Fatalf("feedback id = %v, want %d", eff.FeedbackID, fbID)
	}
}

func TestIntegration_Effective_CorrectedExplanationOnly(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Je mange une pomme","original_context":"lunch"}`)
	analysis := postAnalysisFull(t, ctx, srv.URL, entryID)

	fbID := postFeedback(t, ctx, srv.URL, analysis.ID, `{"status":"corrected","corrected_explanation":"present tense of manger"}`, http.StatusCreated)

	eff := getEffective(t, ctx, srv.URL, analysis.ID)
	if eff.Resolution != "corrected" {
		t.Fatalf("resolution = %q, want corrected", eff.Resolution)
	}
	if eff.Effective.Explanation != "present tense of manger" {
		t.Fatalf("effective explanation = %q, want corrected", eff.Effective.Explanation)
	}
	if eff.Effective.Category != analysis.Category {
		t.Fatalf("effective category should retain original %q, got %q", analysis.Category, eff.Effective.Category)
	}
	// Original unchanged.
	if eff.Original.Category != analysis.Category || eff.Original.Explanation != analysis.Explanation {
		t.Fatalf("original mutated: got %+v", eff.Original)
	}
	if eff.FeedbackID == nil || *eff.FeedbackID != fbID {
		t.Fatalf("feedback id = %v, want %d", eff.FeedbackID, fbID)
	}
}

func TestIntegration_Effective_Rejected(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Je mange une pomme","original_context":"lunch"}`)
	analysis := postAnalysisFull(t, ctx, srv.URL, entryID)

	fbID := postFeedback(t, ctx, srv.URL, analysis.ID, `{"status":"rejected","user_note":"not a phrase"}`, http.StatusCreated)

	eff := getEffective(t, ctx, srv.URL, analysis.ID)
	if eff.Resolution != "rejected" {
		t.Fatalf("resolution = %q, want rejected", eff.Resolution)
	}
	if eff.Effective != nil {
		t.Fatalf("rejected effective must be null, got %+v", eff.Effective)
	}
	// Original analysis must still be returned.
	if eff.Original.Category != analysis.Category || eff.Original.Explanation != analysis.Explanation {
		t.Fatalf("original should be preserved for rejected, got %+v", eff.Original)
	}
	if eff.FeedbackID == nil || *eff.FeedbackID != fbID {
		t.Fatalf("feedback id = %v, want %d (the rejected feedback)", eff.FeedbackID, fbID)
	}
}

// TestIntegration_Effective_LatestWins proves only the latest feedback decides
// the result: an older accepted/corrected record is ignored after a later
// rejection.
func TestIntegration_Effective_LatestWins(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Je mange une pomme","original_context":"lunch"}`)
	analysis := postAnalysisFull(t, ctx, srv.URL, entryID)

	// Order matters: accepted, then corrected, then rejected last.
	postFeedback(t, ctx, srv.URL, analysis.ID, `{"status":"accepted"}`, http.StatusCreated)
	postFeedback(t, ctx, srv.URL, analysis.ID, `{"status":"corrected","corrected_category":"morphology"}`, http.StatusCreated)
	rejectedID := postFeedback(t, ctx, srv.URL, analysis.ID, `{"status":"rejected"}`, http.StatusCreated)

	eff := getEffective(t, ctx, srv.URL, analysis.ID)
	if eff.Resolution != "rejected" {
		t.Fatalf("latest feedback should win: resolution = %q, want rejected", eff.Resolution)
	}
	if eff.Effective != nil {
		t.Fatalf("no older accepted/corrected record should be used after rejection, got %+v", eff.Effective)
	}
	// The resolving feedback must be the final rejected record, not an older one.
	if eff.FeedbackID == nil || *eff.FeedbackID != rejectedID {
		t.Fatalf("resolving feedback id = %v, want the final rejected feedback %d", eff.FeedbackID, rejectedID)
	}
}

// TestIntegration_Effective_Immutability proves resolving the effective analysis
// changes neither the entry, the analysis, nor the feedback history.
func TestIntegration_Effective_Immutability(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Je mange une pomme","original_context":"lunch"}`)
	analysis := postAnalysisFull(t, ctx, srv.URL, entryID)

	postFeedback(t, ctx, srv.URL, analysis.ID, `{"status":"corrected","corrected_category":"morphology","corrected_explanation":"changed"}`, http.StatusCreated)
	postFeedback(t, ctx, srv.URL, analysis.ID, `{"status":"rejected"}`, http.StatusCreated)

	// Resolve twice to be sure repeated reads don't mutate anything.
	_ = getEffective(t, ctx, srv.URL, analysis.ID)
	_ = getEffective(t, ctx, srv.URL, analysis.ID)

	// Entry unchanged.
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/entries/"+itoa(entryID), nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get entry: %v", err)
	}
	var entry struct {
		OriginalInput   string `json:"original_input"`
		OriginalContext string `json:"original_context"`
	}
	decodeBody(t, resp, &entry)
	if entry.OriginalInput != "Je mange une pomme" || entry.OriginalContext != "lunch" {
		t.Fatalf("entry mutated: %+v", entry)
	}

	// Analysis unchanged (still one row, original category/explanation).
	req, _ = http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/entries/"+itoa(entryID)+"/analyses", nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("list analyses: %v", err)
	}
	var analyses struct {
		Analyses []struct {
			Category    string `json:"category"`
			Explanation string `json:"explanation"`
		} `json:"analyses"`
	}
	decodeBody(t, resp, &analyses)
	if len(analyses.Analyses) != 1 {
		t.Fatalf("expected 1 analysis, got %d", len(analyses.Analyses))
	}
	if analyses.Analyses[0].Category != analysis.Category || analyses.Analyses[0].Explanation != analysis.Explanation {
		t.Fatalf("analysis mutated: got %+v", analyses.Analyses[0])
	}

	// Feedback history unchanged (still two records, oldest first).
	req, _ = http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/analyses/"+itoa(analysis.ID)+"/feedback", nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("list feedback: %v", err)
	}
	var fb struct {
		Feedback []struct {
			Status string `json:"status"`
		} `json:"feedback"`
	}
	decodeBody(t, resp, &fb)
	if len(fb.Feedback) != 2 {
		t.Fatalf("expected 2 feedback records preserved, got %d", len(fb.Feedback))
	}
	if fb.Feedback[0].Status != "corrected" || fb.Feedback[1].Status != "rejected" {
		t.Fatalf("feedback history changed: %+v", fb.Feedback)
	}
}

func TestIntegration_Effective_MissingAnalysis(t *testing.T) {
	srv := setupServer(t)
	req, _ := http.NewRequestWithContext(context.Background(), http.MethodGet, srv.URL+"/analyses/9999/effective", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", resp.StatusCode)
	}
	resp.Body.Close()
}

func TestIntegration_Effective_InvalidID(t *testing.T) {
	srv := setupServer(t)
	req, _ := http.NewRequestWithContext(context.Background(), http.MethodGet, srv.URL+"/analyses/abc/effective", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", resp.StatusCode)
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

// postFeedback posts a feedback body to an analysis, asserts the status, and
// returns the created feedback id (0 for non-201 responses). Callers that only
// need the status may ignore the return value.
func postFeedback(t *testing.T, ctx context.Context, baseURL string, analysisID int64, body string, wantStatus int) int64 {
	t.Helper()
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, baseURL+"/analyses/"+itoa(analysisID)+"/feedback", bytes.NewBufferString(body))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("post feedback: %v", err)
	}
	if resp.StatusCode != wantStatus {
		resp.Body.Close()
		t.Fatalf("post feedback status = %d, want %d", resp.StatusCode, wantStatus)
	}
	var fb struct {
		ID int64 `json:"id"`
	}
	decodeBody(t, resp, &fb)
	return fb.ID
}

// createEntry posts a new entry and returns its id.
func createEntry(t *testing.T, ctx context.Context, baseURL, body string) int64 {
	t.Helper()
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, baseURL+"/entries", bytes.NewBufferString(body))
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
	return entry.ID
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
