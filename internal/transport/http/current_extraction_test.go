package http

import (
	"context"
	"encoding/json"
	"errors"
	"net/http/httptest"
	"strings"
	"testing"

	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
)

func TestCurrentExtractionSelectionHTTPWorkflow(t *testing.T) {
	handler, db, provider := boundaryIntegration(t)
	type selectionResponse struct {
		EntryID             int64  `json:"entry_id"`
		CurrentExtractionID *int64 `json:"current_extraction_id"`
		Mode                string `json:"selection_mode"`
	}
	request := func(method, path, body string, want int) selectionResponse {
		t.Helper()
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.Host = "localhost:8080"
		req.Header.Set("Origin", "http://localhost:8080")
		if body != "" {
			req.Header.Set("Content-Type", "application/json")
		}
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != want {
			t.Fatalf("%s %s: %d %s", method, path, rec.Code, rec.Body.String())
		}
		var result selectionResponse
		if want == 200 {
			if err := json.Unmarshal(rec.Body.Bytes(), &result); err != nil {
				t.Fatal(err)
			}
			var fields map[string]json.RawMessage
			if err := json.Unmarshal(rec.Body.Bytes(), &fields); err != nil {
				t.Fatal(err)
			}
			if len(fields) != 3 || fields["entry_id"] == nil || fields["current_extraction_id"] == nil || fields["selection_mode"] == nil {
				t.Fatalf("wrong contract: %s", rec.Body.String())
			}
			// Legacy decoders retain their existing two fields.
			var legacy struct {
				EntryID      int64  `json:"entry_id"`
				ExtractionID *int64 `json:"current_extraction_id"`
			}
			if err := json.Unmarshal(rec.Body.Bytes(), &legacy); err != nil || legacy.EntryID != result.EntryID {
				t.Fatal("legacy fields changed")
			}
		}
		return result
	}
	check := func(result selectionResponse, mode string, id *int64) {
		t.Helper()
		if result.EntryID != 1 || result.Mode != mode || (result.CurrentExtractionID == nil) != (id == nil) || (id != nil && *result.CurrentExtractionID != *id) {
			t.Fatalf("selection=%+v want mode=%s id=%v", result, mode, id)
		}
	}
	extract := func() int64 {
		t.Helper()
		req := httptest.NewRequest("POST", "/entries/1/extractions", nil)
		req.Host = "localhost:8080"
		req.Header.Set("Origin", "http://localhost:8080")
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != 201 {
			t.Fatalf("extract=%d %s", rec.Code, rec.Body.String())
		}
		var result extractionResponse
		if err := json.Unmarshal(rec.Body.Bytes(), &result); err != nil {
			t.Fatal(err)
		}
		return result.ID
	}
	for _, prefix := range []string{"", "/api"} {
		check(request("GET", prefix+"/entries/1/current-extraction", "", 200), "automatic", nil)
		check(request("DELETE", prefix+"/entries/1/current-extraction", "", 200), "automatic", nil)
	}
	first := extract()
	check(request("GET", "/entries/1/current-extraction", "", 200), "automatic", &first)
	pinBody := func(id int64) string {
		bytes, _ := json.Marshal(map[string]int64{"extraction_id": id})
		return string(bytes)
	}
	check(request("PUT", "/api/entries/1/current-extraction", pinBody(first), 200), "pinned", &first)
	second := extract()
	check(request("GET", "/api/entries/1/current-extraction", "", 200), "pinned", &first)
	before := provider.extractionCalls
	// Cross-origin, null and rebinding-host clears must leave the live pin intact.
	for _, prefix := range []string{"", "/api"} {
		for _, variant := range []string{"cross", "null", "fetch", "host"} {
			req := httptest.NewRequest("DELETE", prefix+"/entries/1/current-extraction", nil)
			req.Host = "localhost:8080"
			switch variant {
			case "cross":
				req.Header.Set("Origin", "https://attacker.example")
			case "null":
				req.Header.Set("Origin", "null")
				req.Header.Set("Sec-Fetch-Site", "same-origin")
			case "fetch":
				req.Header.Set("Sec-Fetch-Site", "cross-site")
			case "host":
				req.Host = "attacker.example"
				req.Header.Set("Origin", "http://attacker.example")
				req.Header.Set("Sec-Fetch-Site", "same-origin")
			}
			changes := totalChanges(t, db)
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			if rec.Code != 403 || totalChanges(t, db) != changes || provider.extractionCalls != before || provider.analysisCalls != 0 {
				t.Fatal("forbidden clear wrote data or called a provider")
			}
			check(request("GET", prefix+"/entries/1/current-extraction", "", 200), "pinned", &first)
		}
	}
	check(request("DELETE", "/api/entries/1/current-extraction", "", 200), "automatic", &second)
	check(request("DELETE", "/entries/1/current-extraction", "", 200), "automatic", &second)
	third := extract()
	check(request("GET", "/entries/1/current-extraction", "", 200), "automatic", &third)
	check(request("PUT", "/entries/1/current-extraction", pinBody(third), 200), "pinned", &third)
	// A foreign extraction must not change even a latest-version pin.
	ctx := context.Background()
	entry, err := sqlite.NewEntryRepository(db).Create(ctx, domain.NewEntryInput{OriginalInput: "other"})
	if err != nil {
		t.Fatal(err)
	}
	analysis, err := sqlite.NewAnalysisRepository(db).Create(ctx, entry.ID, domain.AnalysisResult{Category: "grammar", Explanation: "synthetic", Confidence: .9}, "fake:seed")
	if err != nil {
		t.Fatal(err)
	}
	foreign, err := sqlite.NewKnowledgeRepository(db).Create(ctx, domain.NewExtractionInput{EntryID: entry.ID, SourceAnalysisID: analysis.ID, Extractor: "fake:seed"})
	if err != nil {
		t.Fatal(err)
	}
	for _, bad := range []int64{0, -1, 99999, foreign.Extraction.ID} {
		request("PUT", "/entries/1/current-extraction", pinBody(bad), 422)
		check(request("GET", "/entries/1/current-extraction", "", 200), "pinned", &third)
	}
	for _, method := range []string{"GET", "PUT", "DELETE"} {
		for _, id := range []string{"nope", "0", "-1"} {
			request(method, "/entries/"+id+"/current-extraction", pinBody(first), 400)
		}
		request(method, "/entries/99999/current-extraction", pinBody(first), 404)
	}
	request("PUT", "/entries/1/current-extraction", "not JSON", 400)
	check(request("DELETE", "/entries/1/current-extraction", "", 200), "automatic", &third)
	if provider.extractionCalls != 3 || provider.analysisCalls != 0 {
		t.Fatalf("selection operations invoked providers: %+v", provider)
	}
}

type selectionErrorService struct {
	ConceptService
	err error
}

func (s selectionErrorService) GetCurrentExtractionSelection(context.Context, int64) (domain.CurrentExtractionSelection, error) {
	return domain.CurrentExtractionSelection{}, s.err
}
func (s selectionErrorService) ClearCurrentExtraction(context.Context, int64) (domain.CurrentExtractionSelection, error) {
	return domain.CurrentExtractionSelection{}, s.err
}

func TestCurrentExtractionSelectionHTTPErrorMapping(t *testing.T) {
	for _, method := range []string{"GET", "DELETE"} {
		for _, tc := range []struct {
			err    error
			status int
		}{{domain.ErrNotFound, 404}, {errors.New("synthetic SECRET storage detail"), 500}} {
			handler := NewHandler(nil, nil, nil, nil, nil, nil, nil, selectionErrorService{err: tc.err}, nil, nil).Routes()
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, httptest.NewRequest(method, "/entries/1/current-extraction", nil))
			if rec.Code != tc.status || strings.Contains(rec.Body.String(), "SECRET") {
				t.Fatalf("%s: %d %s", method, rec.Code, rec.Body.String())
			}
		}
	}
}
