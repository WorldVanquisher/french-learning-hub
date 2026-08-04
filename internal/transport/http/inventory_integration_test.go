package http_test

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"
)

// learningRecordJSON mirrors the list/export record wire shape for assertions.
type learningRecordJSON struct {
	EntryID         int64   `json:"entry_id"`
	OriginalInput   string  `json:"original_input"`
	OriginalContext string  `json:"original_context"`
	State           string  `json:"state"`
	AnalysisID      *int64  `json:"analysis_id"`
	Analyzer        *string `json:"analyzer"`
	Original        *struct {
		Category    string `json:"category"`
		Explanation string `json:"explanation"`
	} `json:"original"`
	Effective *struct {
		Category    string `json:"category"`
		Explanation string `json:"explanation"`
	} `json:"effective"`
	FeedbackID *int64 `json:"feedback_id"`
}

type listRecordsResponse struct {
	Records         []learningRecordJSON `json:"records"`
	NextBeforeEntry *int64               `json:"next_before_entry_id"`
}

// getJSON performs a GET and decodes a 200 JSON response.
func getJSON(t *testing.T, ctx context.Context, url string, v any) {
	t.Helper()
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("GET %s: %v", url, err)
	}
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		t.Fatalf("GET %s status = %d, want 200", url, resp.StatusCode)
	}
	decodeBody(t, resp, v)
}

// seedInventory builds a small mixed inventory over the real stack and returns
// the created entry ids by role.
type seededInventory struct {
	unanalyzed int64
	unreviewed int64
	accepted   int64
	corrected  int64
	rejected   int64
}

func seedInventory(t *testing.T, ctx context.Context, baseURL string) seededInventory {
	t.Helper()
	var s seededInventory

	// Unanalyzed.
	s.unanalyzed = createEntry(t, ctx, baseURL, `{"original_input":"unanalyzed entry","original_context":""}`)

	// Unreviewed: analyze, no feedback.
	s.unreviewed = createEntry(t, ctx, baseURL, `{"original_input":"unreviewed entry","original_context":""}`)
	postAnalysis(t, ctx, baseURL, s.unreviewed)

	// Accepted.
	s.accepted = createEntry(t, ctx, baseURL, `{"original_input":"accepted entry","original_context":""}`)
	aAcc := postAnalysisFull(t, ctx, baseURL, s.accepted)
	postFeedback(t, ctx, baseURL, aAcc.ID, `{"status":"accepted"}`, http.StatusCreated)

	// Corrected to morphology.
	s.corrected = createEntry(t, ctx, baseURL, `{"original_input":"corrected entry","original_context":""}`)
	aCorr := postAnalysisFull(t, ctx, baseURL, s.corrected)
	postFeedback(t, ctx, baseURL, aCorr.ID, `{"status":"corrected","corrected_category":"morphology"}`, http.StatusCreated)

	// Rejected.
	s.rejected = createEntry(t, ctx, baseURL, `{"original_input":"rejected entry","original_context":""}`)
	aRej := postAnalysisFull(t, ctx, baseURL, s.rejected)
	postFeedback(t, ctx, baseURL, aRej.ID, `{"status":"rejected"}`, http.StatusCreated)

	return s
}

func TestIntegration_Inventory_ListAll(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	seedInventory(t, ctx, srv.URL)

	var body listRecordsResponse
	getJSON(t, ctx, srv.URL+"/learning-records", &body)
	if len(body.Records) != 5 {
		t.Fatalf("expected 5 records, got %d", len(body.Records))
	}
	// Descending entry id order.
	for i := 1; i < len(body.Records); i++ {
		if body.Records[i-1].EntryID <= body.Records[i].EntryID {
			t.Fatalf("records not in descending id order: %+v", body.Records)
		}
	}
	// Small result set: no further page.
	if body.NextBeforeEntry != nil {
		t.Fatalf("expected null next cursor for a full unpaginated list, got %d", *body.NextBeforeEntry)
	}
}

func TestIntegration_Inventory_FilterByState(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	s := seedInventory(t, ctx, srv.URL)

	cases := []struct {
		state  string
		wantID int64
	}{
		{"unanalyzed", s.unanalyzed},
		{"unreviewed", s.unreviewed},
		{"accepted", s.accepted},
		{"corrected", s.corrected},
		{"rejected", s.rejected},
	}
	for _, tc := range cases {
		t.Run(tc.state, func(t *testing.T) {
			var body listRecordsResponse
			getJSON(t, ctx, srv.URL+"/learning-records?state="+tc.state, &body)
			if len(body.Records) != 1 {
				t.Fatalf("state=%s expected 1 record, got %d", tc.state, len(body.Records))
			}
			if body.Records[0].EntryID != tc.wantID {
				t.Fatalf("state=%s returned entry %d, want %d", tc.state, body.Records[0].EntryID, tc.wantID)
			}
			if body.Records[0].State != tc.state {
				t.Fatalf("record state = %q, want %q", body.Records[0].State, tc.state)
			}
		})
	}
}

func TestIntegration_Inventory_FilterByEffectiveCategory(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	s := seedInventory(t, ctx, srv.URL)

	// The corrected entry's effective category is morphology.
	var body listRecordsResponse
	getJSON(t, ctx, srv.URL+"/learning-records?category=morphology", &body)
	if len(body.Records) != 1 || body.Records[0].EntryID != s.corrected {
		t.Fatalf("morphology filter should return the corrected entry, got %+v", body.Records)
	}
	if body.Records[0].Effective == nil || body.Records[0].Effective.Category != "morphology" {
		t.Fatalf("effective category should be morphology, got %+v", body.Records[0].Effective)
	}
}

func TestIntegration_Inventory_FilterByAnalyzer(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	seedInventory(t, ctx, srv.URL)

	// All analyzed entries use the default rule-based provenance.
	var body listRecordsResponse
	getJSON(t, ctx, srv.URL+"/learning-records?analyzer="+wantRuleBasedProvenance, &body)
	if len(body.Records) != 4 {
		t.Fatalf("expected 4 analyzed records for rule-based analyzer, got %d", len(body.Records))
	}
	for _, rec := range body.Records {
		if rec.Analyzer == nil || *rec.Analyzer != wantRuleBasedProvenance {
			t.Fatalf("record analyzer = %v, want %q", rec.Analyzer, wantRuleBasedProvenance)
		}
	}

	// Substring must not match (exact filter).
	getJSON(t, ctx, srv.URL+"/learning-records?analyzer=rule-based", &body)
	if len(body.Records) != 0 {
		t.Fatalf("substring analyzer filter should match nothing, got %d", len(body.Records))
	}
}

func TestIntegration_Inventory_Pagination(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	// Create 5 plain entries.
	var ids []int64
	for i := 0; i < 5; i++ {
		ids = append(ids, createEntry(t, ctx, srv.URL, `{"original_input":"page entry","original_context":""}`))
	}

	// Page 1: limit 2.
	var page1 listRecordsResponse
	getJSON(t, ctx, srv.URL+"/learning-records?limit=2", &page1)
	if len(page1.Records) != 2 {
		t.Fatalf("page1 len = %d, want 2", len(page1.Records))
	}
	if page1.NextBeforeEntry == nil {
		t.Fatal("page1 should carry a next cursor")
	}
	if page1.Records[0].EntryID != ids[4] || page1.Records[1].EntryID != ids[3] {
		t.Fatalf("page1 not descending: %d, %d", page1.Records[0].EntryID, page1.Records[1].EntryID)
	}

	// Page 2 via cursor.
	var page2 listRecordsResponse
	getJSON(t, ctx, srv.URL+"/learning-records?limit=2&before_entry_id="+itoa(*page1.NextBeforeEntry), &page2)
	if len(page2.Records) != 2 {
		t.Fatalf("page2 len = %d, want 2", len(page2.Records))
	}
	if page2.Records[0].EntryID != ids[2] || page2.Records[1].EntryID != ids[1] {
		t.Fatalf("page2 wrong: %d, %d", page2.Records[0].EntryID, page2.Records[1].EntryID)
	}

	// Page 3: final record, no further cursor.
	var page3 listRecordsResponse
	getJSON(t, ctx, srv.URL+"/learning-records?limit=2&before_entry_id="+itoa(*page2.NextBeforeEntry), &page3)
	if len(page3.Records) != 1 || page3.Records[0].EntryID != ids[0] {
		t.Fatalf("page3 wrong: %+v", page3.Records)
	}
	if page3.NextBeforeEntry != nil {
		t.Fatalf("page3 should have no further cursor, got %d", *page3.NextBeforeEntry)
	}
}

func TestIntegration_Inventory_Summary(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	seedInventory(t, ctx, srv.URL)

	var summary struct {
		TotalEntries        int64            `json:"total_entries"`
		AnalyzedEntries     int64            `json:"analyzed_entries"`
		UnanalyzedEntries   int64            `json:"unanalyzed_entries"`
		ByState             map[string]int64 `json:"by_state"`
		ByEffectiveCategory map[string]int64 `json:"by_effective_category"`
		ByAnalyzer          map[string]int64 `json:"by_analyzer"`
	}
	getJSON(t, ctx, srv.URL+"/learning-records/summary", &summary)

	if summary.TotalEntries != 5 {
		t.Fatalf("total = %d, want 5", summary.TotalEntries)
	}
	if summary.AnalyzedEntries != 4 || summary.UnanalyzedEntries != 1 {
		t.Fatalf("analyzed=%d unanalyzed=%d, want 4 and 1", summary.AnalyzedEntries, summary.UnanalyzedEntries)
	}
	if summary.AnalyzedEntries+summary.UnanalyzedEntries != summary.TotalEntries {
		t.Fatal("analyzed+unanalyzed must equal total")
	}
	// State counts sum to total; all five keys present.
	var sum int64
	for _, st := range []string{"unanalyzed", "unreviewed", "accepted", "corrected", "rejected"} {
		v, ok := summary.ByState[st]
		if !ok {
			t.Fatalf("by_state missing key %q", st)
		}
		sum += v
	}
	if sum != summary.TotalEntries {
		t.Fatalf("by_state sum = %d, want %d", sum, summary.TotalEntries)
	}
	// Rejected + unanalyzed do not contribute to by_effective_category.
	// Effective categories: unreviewed(comprehension/other...), accepted(...),
	// corrected(morphology). Exactly 3 analyzed non-rejected entries contribute.
	var catTotal int64
	for _, v := range summary.ByEffectiveCategory {
		catTotal += v
	}
	if catTotal != 3 {
		t.Fatalf("by_effective_category total = %d, want 3 (accepted+corrected+unreviewed)", catTotal)
	}
	if _, ok := summary.ByEffectiveCategory["morphology"]; !ok {
		t.Fatalf("corrected entry's morphology category missing: %+v", summary.ByEffectiveCategory)
	}
	// by_analyzer counts the 4 analyzed entries, all rule-based.
	if summary.ByAnalyzer[wantRuleBasedProvenance] != 4 {
		t.Fatalf("by_analyzer[%q] = %d, want 4", wantRuleBasedProvenance, summary.ByAnalyzer[wantRuleBasedProvenance])
	}
}

// decodeJSONL reads an NDJSON body into a slice of records, asserting each line
// is a standalone JSON object (no enclosing array).
func decodeJSONL(t *testing.T, body string) []learningRecordJSON {
	t.Helper()
	var out []learningRecordJSON
	sc := bufio.NewScanner(strings.NewReader(body))
	sc.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		if !strings.HasPrefix(line, "{") || !strings.HasSuffix(line, "}") {
			t.Fatalf("JSONL line is not a standalone object: %q", line)
		}
		var rec learningRecordJSON
		if err := json.Unmarshal([]byte(line), &rec); err != nil {
			t.Fatalf("decode JSONL line %q: %v", line, err)
		}
		out = append(out, rec)
	}
	if err := sc.Err(); err != nil {
		t.Fatalf("scan JSONL: %v", err)
	}
	return out
}

func TestIntegration_Inventory_ExportJSONL(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	seedInventory(t, ctx, srv.URL)

	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/learning-records/export", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("export: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("export status = %d, want 200", resp.StatusCode)
	}
	if ct := resp.Header.Get("Content-Type"); ct != "application/x-ndjson; charset=utf-8" {
		t.Fatalf("content-type = %q, want application/x-ndjson; charset=utf-8", ct)
	}
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	body := string(raw)

	// Body must not be a JSON array.
	if strings.HasPrefix(strings.TrimSpace(body), "[") {
		t.Fatal("JSONL export must not be a JSON array")
	}
	// One object per line: 5 records -> 5 non-empty lines.
	recs := decodeJSONL(t, body)
	if len(recs) != 5 {
		t.Fatalf("expected 5 JSONL records, got %d", len(recs))
	}
	// Descending entry id order preserved in the export.
	for i := 1; i < len(recs); i++ {
		if recs[i-1].EntryID <= recs[i].EntryID {
			t.Fatalf("export not in descending id order: %+v", recs)
		}
	}
}

func TestIntegration_Inventory_ExportFiltering(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()
	s := seedInventory(t, ctx, srv.URL)

	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+"/learning-records/export?state=rejected", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("export: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("export status = %d, want 200", resp.StatusCode)
	}
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	recs := decodeJSONL(t, string(raw))
	if len(recs) != 1 || recs[0].EntryID != s.rejected {
		t.Fatalf("filtered export should contain only the rejected entry, got %+v", recs)
	}
	if recs[0].Effective != nil {
		t.Fatalf("rejected record effective must be null in export, got %+v", recs[0].Effective)
	}
}

func TestIntegration_Inventory_InvalidFilters(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	cases := []string{
		"/learning-records?state=bogus",
		"/learning-records?category=not-a-category",
		"/learning-records?before_entry_id=0",
		"/learning-records?before_entry_id=-3",
		"/learning-records?before_entry_id=abc",
		"/learning-records?limit=abc",
		"/learning-records/export?state=bogus",
	}
	for _, path := range cases {
		t.Run(path, func(t *testing.T) {
			req, _ := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL+path, nil)
			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatalf("request: %v", err)
			}
			resp.Body.Close()
			if resp.StatusCode != http.StatusBadRequest {
				t.Fatalf("%s status = %d, want 400", path, resp.StatusCode)
			}
		})
	}
}

func TestIntegration_Inventory_EmptySummary(t *testing.T) {
	srv := setupServer(t)
	ctx := context.Background()

	var summary struct {
		TotalEntries int64            `json:"total_entries"`
		ByState      map[string]int64 `json:"by_state"`
	}
	getJSON(t, ctx, srv.URL+"/learning-records/summary", &summary)
	if summary.TotalEntries != 0 {
		t.Fatalf("empty total = %d, want 0", summary.TotalEntries)
	}
	// All five state keys present even when empty.
	for _, st := range []string{"unanalyzed", "unreviewed", "accepted", "corrected", "rejected"} {
		if _, ok := summary.ByState[st]; !ok {
			t.Fatalf("empty summary missing state key %q", st)
		}
	}
}
