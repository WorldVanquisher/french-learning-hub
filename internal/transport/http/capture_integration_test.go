package http_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/url"
	"testing"
)

// captureResult mirrors the POST /captures response.
type captureResult struct {
	CaptureID  string `json:"capture_id"`
	EntryID    int64  `json:"entry_id"`
	AnalysisID *int64 `json:"analysis_id"`
	Created    bool   `json:"created"`
}

// captureLookup mirrors the GET /captures/{capture_id} response.
type captureLookup struct {
	CaptureID         string `json:"capture_id"`
	SchemaVersion     string `json:"schema_version"`
	Source            string `json:"source"`
	EntryID           int64  `json:"entry_id"`
	AnalysisID        *int64 `json:"analysis_id"`
	DiscussionSummary string `json:"discussion_summary"`
	CreatedAt         string `json:"created_at"`
}

// postCapture posts a capture body, asserts the status, and returns the decoded
// result (zero value for non-2xx responses, which the caller should not decode).
func postCapture(t *testing.T, ctx context.Context, baseURL, body string, wantStatus int) captureResult {
	t.Helper()
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, baseURL+"/captures", bytes.NewBufferString(body))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("post capture: %v", err)
	}
	if resp.StatusCode != wantStatus {
		resp.Body.Close()
		t.Fatalf("post capture status = %d, want %d", resp.StatusCode, wantStatus)
	}
	if resp.StatusCode >= 300 {
		resp.Body.Close()
		return captureResult{}
	}
	var out captureResult
	decodeBody(t, resp, &out)
	return out
}

// captureWithAnalysis is a valid learning_capture_v1 body with an analysis.
const captureWithAnalysis = `{
  "schema_version": "learning_capture_v1",
  "capture_id": "cap-http-1",
  "source": "chatgpt-web",
  "original_input": "Je parle japonais ou je parle le japonais ?",
  "original_context": "Whether language names take an article after parler.",
  "analysis": {
    "category": "grammar",
    "explanation": "After parler a language name is normally used without an article.",
    "confidence": 0.9,
    "uncertainty": "Usage may vary."
  },
  "discussion_summary": "Compared parler japonais with apprendre le japonais."
}`

// captureNoAnalysis is a valid body without an analysis.
const captureNoAnalysis = `{
  "schema_version": "learning_capture_v1",
  "capture_id": "cap-http-noan",
  "source": "manual",
  "original_input": "Comment dit-on 'apple' ?",
  "original_context": "vocabulary lookup",
  "discussion_summary": "Asked for the French word for apple."
}`

func TestIntegration_CreateCapture_WithAnalysis(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	res := postCapture(t, ctx, srv.URL, captureWithAnalysis, http.StatusCreated)
	if !res.Created {
		t.Fatal("expected created=true")
	}
	if res.EntryID == 0 || res.AnalysisID == nil {
		t.Fatalf("expected entry and analysis ids, got %+v", res)
	}

	// The entry is retrievable via the existing entry API with the original data.
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/entries/"+itoa(res.EntryID), nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get entry: %v", err)
	}
	var entry struct {
		OriginalInput   string `json:"original_input"`
		OriginalContext string `json:"original_context"`
	}
	decodeBody(t, resp, &entry)
	if entry.OriginalInput != "Je parle japonais ou je parle le japonais ?" {
		t.Fatalf("entry input wrong: %q", entry.OriginalInput)
	}

	// The analysis is retrievable via the existing analyses API, version 1, with
	// server-constructed imported provenance.
	req, _ = http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/entries/"+itoa(res.EntryID)+"/analyses", nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("list analyses: %v", err)
	}
	var listed struct {
		Analyses []struct {
			Version  int64  `json:"version"`
			Category string `json:"category"`
			Analyzer string `json:"analyzer"`
		} `json:"analyses"`
	}
	decodeBody(t, resp, &listed)
	if len(listed.Analyses) != 1 {
		t.Fatalf("expected 1 analysis, got %d", len(listed.Analyses))
	}
	if listed.Analyses[0].Version != 1 {
		t.Fatalf("imported analysis version = %d, want 1", listed.Analyses[0].Version)
	}
	if listed.Analyses[0].Analyzer != "imported:chatgpt-web:learning_capture_v1" {
		t.Fatalf("provenance = %q", listed.Analyses[0].Analyzer)
	}
}

func TestIntegration_CreateCapture_WithoutAnalysis(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	res := postCapture(t, ctx, srv.URL, captureNoAnalysis, http.StatusCreated)
	if !res.Created || res.EntryID == 0 {
		t.Fatalf("unexpected result: %+v", res)
	}
	if res.AnalysisID != nil {
		t.Fatalf("expected null analysis_id, got %d", *res.AnalysisID)
	}

	// No analysis exists for the entry.
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/entries/"+itoa(res.EntryID)+"/analyses", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("list analyses: %v", err)
	}
	var listed struct {
		Analyses []json.RawMessage `json:"analyses"`
	}
	decodeBody(t, resp, &listed)
	if len(listed.Analyses) != 0 {
		t.Fatalf("expected no analyses, got %d", len(listed.Analyses))
	}
}

func TestIntegration_CreateCapture_IdempotentReplay(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	first := postCapture(t, ctx, srv.URL, captureWithAnalysis, http.StatusCreated)
	// Exact repeat -> 200, created=false, same ids, no new rows.
	second := postCapture(t, ctx, srv.URL, captureWithAnalysis, http.StatusOK)
	if second.Created {
		t.Fatal("replay should have created=false")
	}
	if second.EntryID != first.EntryID {
		t.Fatalf("replay entry id = %d, want %d", second.EntryID, first.EntryID)
	}
	if (second.AnalysisID == nil) != (first.AnalysisID == nil) {
		t.Fatalf("replay analysis id mismatch: %v vs %v", second.AnalysisID, first.AnalysisID)
	}
	if second.AnalysisID != nil && *second.AnalysisID != *first.AnalysisID {
		t.Fatalf("replay analysis id = %d, want %d", *second.AnalysisID, *first.AnalysisID)
	}
}

func TestIntegration_CreateCapture_Conflict(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	postCapture(t, ctx, srv.URL, captureWithAnalysis, http.StatusCreated)

	// Same capture_id, different content -> 409.
	conflicting := `{
	  "schema_version": "learning_capture_v1",
	  "capture_id": "cap-http-1",
	  "source": "chatgpt-web",
	  "original_input": "A completely different question",
	  "original_context": "different context",
	  "discussion_summary": "different summary"
	}`
	postCapture(t, ctx, srv.URL, conflicting, http.StatusConflict)
}

func TestIntegration_CreateCapture_UnsupportedSchema(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	body := `{"schema_version":"learning_capture_v2","capture_id":"cap-x","source":"manual","original_input":"x","original_context":"y"}`
	postCapture(t, ctx, srv.URL, body, http.StatusUnprocessableEntity)
}

func TestIntegration_CreateCapture_UnknownSource(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	body := `{"schema_version":"learning_capture_v1","capture_id":"cap-x","source":"api","original_input":"x","original_context":"y"}`
	postCapture(t, ctx, srv.URL, body, http.StatusUnprocessableEntity)
}

func TestIntegration_CreateCapture_InvalidContent(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	// Empty original_input fails the reused entry validation -> 422.
	body := `{"schema_version":"learning_capture_v1","capture_id":"cap-x","source":"manual","original_input":"   ","original_context":"y"}`
	postCapture(t, ctx, srv.URL, body, http.StatusUnprocessableEntity)
}

func TestIntegration_CreateCapture_MalformedJSON(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	postCapture(t, ctx, srv.URL, `{not json`, http.StatusBadRequest)
}

func TestIntegration_CreateCapture_UnknownField(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	// Unknown top-level field is rejected by strict decoding -> 400.
	body := `{"schema_version":"learning_capture_v1","capture_id":"cap-x","source":"manual","original_input":"x","original_context":"y","bogus":1}`
	postCapture(t, ctx, srv.URL, body, http.StatusBadRequest)
}

func TestIntegration_CreateCapture_TrailingJSON(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	// A second JSON object after the first is rejected -> 400.
	body := captureNoAnalysis + `{"schema_version":"learning_capture_v1"}`
	postCapture(t, ctx, srv.URL, body, http.StatusBadRequest)
}

func TestIntegration_GetCapture(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	created := postCapture(t, ctx, srv.URL, captureWithAnalysis, http.StatusCreated)

	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/captures/cap-http-1", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get capture: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("get capture status = %d, want 200", resp.StatusCode)
	}
	var look captureLookup
	decodeBody(t, resp, &look)
	if look.CaptureID != "cap-http-1" || look.SchemaVersion != "learning_capture_v1" {
		t.Fatalf("unexpected lookup: %+v", look)
	}
	if look.Source != "chatgpt-web" || look.EntryID != created.EntryID {
		t.Fatalf("lookup metadata wrong: %+v", look)
	}
	if look.AnalysisID == nil || *look.AnalysisID != *created.AnalysisID {
		t.Fatalf("lookup analysis id = %v, want %v", look.AnalysisID, created.AnalysisID)
	}

	// The lookup must not leak a content fingerprint field.
	req, _ = http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/captures/cap-http-1", nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get capture raw: %v", err)
	}
	var raw map[string]any
	decodeBody(t, resp, &raw)
	for k := range raw {
		if k == "content_fingerprint" || k == "fingerprint" {
			t.Fatalf("lookup leaked fingerprint field %q", k)
		}
	}
}

func TestIntegration_GetCapture_NotFound(t *testing.T) {
	srv := setupServer(t)
	req, _ := http.NewRequestWithContext(context.Background(), http.MethodGet, srv.URL+"/captures/never-created", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", resp.StatusCode)
	}
	resp.Body.Close()
}

func TestIntegration_GetCapture_MalformedID(t *testing.T) {
	srv := setupServer(t)
	// A space is not in the portable charset; URL-encoded so it reaches the router
	// as a single path segment that then fails validation -> 400.
	u := srv.URL + "/captures/" + url.PathEscape("bad id!")
	req, _ := http.NewRequestWithContext(context.Background(), http.MethodGet, u, nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", resp.StatusCode)
	}
	resp.Body.Close()
}

// TestIntegration_CaptureInInventory proves an imported capture appears in the
// M7 learning inventory as unreviewed, with imported provenance and effective ==
// original analysis, and no feedback.
func TestIntegration_CaptureInInventory(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	created := postCapture(t, ctx, srv.URL, captureWithAnalysis, http.StatusCreated)

	rec := findRecord(t, ctx, srv.URL, created.EntryID)
	if rec.State != "unreviewed" {
		t.Fatalf("state = %q, want unreviewed", rec.State)
	}
	if rec.Analyzer == nil || *rec.Analyzer != "imported:chatgpt-web:learning_capture_v1" {
		t.Fatalf("analyzer = %v", rec.Analyzer)
	}
	if rec.Effective == nil || rec.Effective.Category != "grammar" {
		t.Fatalf("effective = %+v, want grammar", rec.Effective)
	}
	if rec.Original == nil || rec.Original.Category != "grammar" {
		t.Fatalf("original = %+v, want grammar", rec.Original)
	}
	if rec.FeedbackID != nil {
		t.Fatalf("feedback id should be null, got %d", *rec.FeedbackID)
	}
}

// TestIntegration_CaptureNoAnalysisInInventory proves a capture without analysis
// is unanalyzed with null analysis and effective.
func TestIntegration_CaptureNoAnalysisInInventory(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	created := postCapture(t, ctx, srv.URL, captureNoAnalysis, http.StatusCreated)

	rec := findRecord(t, ctx, srv.URL, created.EntryID)
	if rec.State != "unanalyzed" {
		t.Fatalf("state = %q, want unanalyzed", rec.State)
	}
	if rec.Analyzer != nil {
		t.Fatalf("analyzer should be null, got %q", *rec.Analyzer)
	}
	if rec.Effective != nil {
		t.Fatalf("effective should be null, got %+v", rec.Effective)
	}
}

// TestIntegration_CaptureEffectiveCategoryFilter proves the inventory category
// filter (which filters by effective category) finds an imported capture.
func TestIntegration_CaptureEffectiveCategoryFilter(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	created := postCapture(t, ctx, srv.URL, captureWithAnalysis, http.StatusCreated)

	records := listRecords(t, ctx, srv.URL, "category=grammar")
	if !containsEntry(records, created.EntryID) {
		t.Fatal("imported capture not found by effective category filter")
	}
}

// TestIntegration_CaptureFeedbackChangesInventory proves feedback on an imported
// analysis flows through the existing feedback + inventory path: a correction
// changes the effective category, and a later rejection removes it.
func TestIntegration_CaptureFeedbackChangesInventory(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	created := postCapture(t, ctx, srv.URL, captureWithAnalysis, http.StatusCreated)
	analysisID := *created.AnalysisID

	// Correct the imported analysis category.
	postFeedback(t, ctx, srv.URL, analysisID, `{"status":"corrected","corrected_category":"vocabulary"}`, http.StatusCreated)

	rec := findRecord(t, ctx, srv.URL, created.EntryID)
	if rec.State != "corrected" {
		t.Fatalf("state = %q, want corrected", rec.State)
	}
	if rec.Effective == nil || rec.Effective.Category != "vocabulary" {
		t.Fatalf("effective category = %+v, want vocabulary", rec.Effective)
	}
	// The corrected effective category is now filterable; the original is not.
	if !containsEntry(listRecords(t, ctx, srv.URL, "category=vocabulary"), created.EntryID) {
		t.Fatal("corrected capture not found by new effective category")
	}
	if containsEntry(listRecords(t, ctx, srv.URL, "category=grammar"), created.EntryID) {
		t.Fatal("corrected capture should no longer match its original category")
	}

	// A later rejection removes the effective interpretation entirely.
	postFeedback(t, ctx, srv.URL, analysisID, `{"status":"rejected"}`, http.StatusCreated)
	rec = findRecord(t, ctx, srv.URL, created.EntryID)
	if rec.State != "rejected" {
		t.Fatalf("state = %q, want rejected", rec.State)
	}
	if rec.Effective != nil {
		t.Fatalf("rejected effective should be null, got %+v", rec.Effective)
	}
	if containsEntry(listRecords(t, ctx, srv.URL, "category=vocabulary"), created.EntryID) {
		t.Fatal("rejected capture should not match any effective category")
	}
}

// TestIntegration_ExistingEndpointsUnaffectedByCaptures proves the manual entry +
// analysis + inventory workflow still behaves as before when captures also exist.
func TestIntegration_ExistingEndpointsUnaffectedByCaptures(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	// Import a capture, then use the ordinary entry/analysis endpoints.
	postCapture(t, ctx, srv.URL, captureWithAnalysis, http.StatusCreated)

	entryID := createEntry(t, ctx, srv.URL, `{"original_input":"Bonjour","original_context":"greeting"}`)
	a := postAnalysis(t, ctx, srv.URL, entryID)
	if a.Version != 1 {
		t.Fatalf("manual analysis version = %d, want 1", a.Version)
	}
	if a.Analyzer != wantRuleBasedProvenance {
		t.Fatalf("manual analysis analyzer = %q, want %q", a.Analyzer, wantRuleBasedProvenance)
	}
}

// ---- inventory helpers ----

type inventoryRecord struct {
	EntryID  int64   `json:"entry_id"`
	State    string  `json:"state"`
	Analyzer *string `json:"analyzer"`
	Original *struct {
		Category    string `json:"category"`
		Explanation string `json:"explanation"`
	} `json:"original"`
	Effective *struct {
		Category    string `json:"category"`
		Explanation string `json:"explanation"`
	} `json:"effective"`
	FeedbackID *int64 `json:"feedback_id"`
}

func listRecords(t *testing.T, ctx context.Context, baseURL, query string) []inventoryRecord {
	t.Helper()
	u := baseURL + "/learning-records"
	if query != "" {
		u += "?" + query
	}
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("list records: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		t.Fatalf("list records status = %d, want 200", resp.StatusCode)
	}
	var body struct {
		Records []inventoryRecord `json:"records"`
	}
	decodeBody(t, resp, &body)
	return body.Records
}

func findRecord(t *testing.T, ctx context.Context, baseURL string, entryID int64) inventoryRecord {
	t.Helper()
	for _, rec := range listRecords(t, ctx, baseURL, "") {
		if rec.EntryID == entryID {
			return rec
		}
	}
	t.Fatalf("entry %d not found in inventory", entryID)
	return inventoryRecord{}
}

func containsEntry(records []inventoryRecord, entryID int64) bool {
	for _, rec := range records {
		if rec.EntryID == entryID {
			return true
		}
	}
	return false
}
