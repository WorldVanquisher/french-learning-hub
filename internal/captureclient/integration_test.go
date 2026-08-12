package captureclient_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"french-learning-app/internal/analyzer"
	"french-learning-app/internal/application"
	"french-learning-app/internal/captureclient"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

// setupHub wires the real HTTP handler over a real temporary SQLite database and
// returns a running test server. This exercises the full path the CLI uses in
// production: capture client -> HTTP -> CaptureService -> SQLite -> inventory.
func setupHub(t *testing.T) *httptest.Server {
	t.Helper()
	db, err := sqlite.Open(filepath.Join(t.TempDir(), "hub.db"))
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	t.Cleanup(func() { db.Close() })

	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	inventoryRepo := sqlite.NewInventoryRepository(db)
	captureRepo := sqlite.NewCaptureRepository(db)

	handler := transporthttp.NewHandler(
		application.NewEntryService(entryRepo),
		application.NewAnalysisService(entryRepo, analysisRepo, analyzer.NewRuleBased()),
		application.NewFeedbackService(feedbackRepo),
		application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo),
		application.NewInventoryService(inventoryRepo),
		application.NewCaptureService(captureRepo),
		nil,
	)
	srv := httptest.NewServer(handler.Routes())
	t.Cleanup(srv.Close)
	return srv
}

// inventoryRecord is the subset of the /learning-records shape this test checks.
type inventoryRecord struct {
	EntryID         int64   `json:"entry_id"`
	OriginalInput   string  `json:"original_input"`
	OriginalContext string  `json:"original_context"`
	State           string  `json:"state"`
	Analyzer        *string `json:"analyzer"`
	Original        *struct {
		Category string `json:"category"`
	} `json:"original"`
	Effective *struct {
		Category string `json:"category"`
	} `json:"effective"`
}

func listInventory(t *testing.T, baseURL string) []inventoryRecord {
	t.Helper()
	resp, err := http.Get(baseURL + "/learning-records?limit=200")
	if err != nil {
		t.Fatalf("list inventory: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("inventory status = %d, want 200", resp.StatusCode)
	}
	var body struct {
		Records []inventoryRecord `json:"records"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode inventory: %v", err)
	}
	return body.Records
}

func findByEntryID(records []inventoryRecord, entryID int64) *inventoryRecord {
	for i := range records {
		if records[i].EntryID == entryID {
			return &records[i]
		}
	}
	return nil
}

const captureNoAnalysis = `{
  "schema_version": "learning_capture_v1",
  "capture_id": "manual-e2e-001",
  "source": "manual",
  "original_input": "vouloir",
  "original_context": "asking about the conjugation of vouloir",
  "discussion_summary": "learning the common conjugations of vouloir"
}`

// TestE2E_CaptureWithoutAnalysis proves the full real path end to end: a valid
// capture posted through the client is persisted and then visible in the
// inventory as an unanalyzed entry with its original content intact.
func TestE2E_CaptureWithoutAnalysis(t *testing.T) {
	srv := setupHub(t)
	client, err := captureclient.New(srv.URL)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	ctx := context.Background()

	res, err := client.Import(ctx, []byte(captureNoAnalysis))
	if err != nil {
		t.Fatalf("import: %v", err)
	}
	if !res.Created {
		t.Fatal("expected created=true for a new capture")
	}
	if res.EntryID == 0 {
		t.Fatal("expected a valid entry id")
	}
	if res.AnalysisID != nil {
		t.Fatalf("expected null analysis_id, got %d", *res.AnalysisID)
	}

	rec := findByEntryID(listInventory(t, srv.URL), res.EntryID)
	if rec == nil {
		t.Fatal("captured entry not found in inventory")
	}
	if rec.State != "unanalyzed" {
		t.Fatalf("state = %q, want unanalyzed", rec.State)
	}
	if rec.Analyzer != nil || rec.Effective != nil {
		t.Fatalf("unanalyzed record should have null analyzer/effective: %+v", rec)
	}
	if rec.OriginalInput != "vouloir" || rec.OriginalContext != "asking about the conjugation of vouloir" {
		t.Fatalf("original content changed: %+v", rec)
	}
}

// TestE2E_IdempotentReplay proves resubmitting the identical payload through the
// client is a successful replay that creates no second entry.
func TestE2E_IdempotentReplay(t *testing.T) {
	srv := setupHub(t)
	client, err := captureclient.New(srv.URL)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	ctx := context.Background()

	first, err := client.Import(ctx, []byte(captureNoAnalysis))
	if err != nil {
		t.Fatalf("first import: %v", err)
	}
	second, err := client.Import(ctx, []byte(captureNoAnalysis))
	if err != nil {
		t.Fatalf("replay import should succeed: %v", err)
	}
	if second.Created {
		t.Fatal("replay should have created=false")
	}
	if second.EntryID != first.EntryID {
		t.Fatalf("replay entry id = %d, want %d", second.EntryID, first.EntryID)
	}

	// Exactly one matching record exists.
	count := 0
	for _, rec := range listInventory(t, srv.URL) {
		if rec.EntryID == first.EntryID {
			count++
		}
	}
	if count != 1 {
		t.Fatalf("expected exactly 1 inventory record for the capture, got %d", count)
	}
}

const captureWithAnalysis = `{
  "schema_version": "learning_capture_v1",
  "capture_id": "chatgpt-e2e-001",
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

// TestE2E_CaptureWithAnalysis proves an imported analysis flows through to the
// inventory with the existing imported-provenance rule and shared taxonomy.
func TestE2E_CaptureWithAnalysis(t *testing.T) {
	srv := setupHub(t)
	client, err := captureclient.New(srv.URL)
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	res, err := client.Import(context.Background(), []byte(captureWithAnalysis))
	if err != nil {
		t.Fatalf("import: %v", err)
	}
	if res.AnalysisID == nil {
		t.Fatal("expected an analysis id")
	}

	rec := findByEntryID(listInventory(t, srv.URL), res.EntryID)
	if rec == nil {
		t.Fatal("captured entry not found in inventory")
	}
	if rec.State != "unreviewed" {
		t.Fatalf("state = %q, want unreviewed", rec.State)
	}
	if rec.Analyzer == nil || *rec.Analyzer != "imported:chatgpt-web:learning_capture_v1" {
		t.Fatalf("analyzer provenance = %v", rec.Analyzer)
	}
	if rec.Effective == nil || rec.Effective.Category != "grammar" {
		t.Fatalf("effective category = %+v, want grammar (fr_l2_taxonomy_v1)", rec.Effective)
	}
}

// TestE2E_Conflict proves a same-id/different-content submission through the
// client surfaces as a conflict error and does not overwrite the stored capture.
func TestE2E_Conflict(t *testing.T) {
	srv := setupHub(t)
	client, err := captureclient.New(srv.URL)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	ctx := context.Background()

	if _, err := client.Import(ctx, []byte(captureNoAnalysis)); err != nil {
		t.Fatalf("first import: %v", err)
	}

	conflicting := `{
	  "schema_version": "learning_capture_v1",
	  "capture_id": "manual-e2e-001",
	  "source": "manual",
	  "original_input": "different question entirely",
	  "original_context": "different context",
	  "discussion_summary": "different"
	}`
	_, err = client.Import(ctx, []byte(conflicting))
	var apiErr *captureclient.APIError
	if err == nil || !apiErrIsConflict(err, &apiErr) {
		t.Fatalf("expected a 409 conflict, got %v", err)
	}

	// The original capture is unchanged: its entry still has the original input.
	recs := listInventory(t, srv.URL)
	var found bool
	for _, rec := range recs {
		if rec.OriginalInput == "vouloir" {
			found = true
		}
		if rec.OriginalInput == "different question entirely" {
			t.Fatal("conflicting submission should not have been stored")
		}
	}
	if !found {
		t.Fatal("original capture was lost")
	}
}

func apiErrIsConflict(err error, target **captureclient.APIError) bool {
	if e, ok := err.(*captureclient.APIError); ok {
		*target = e
		return e.IsConflict()
	}
	return false
}
