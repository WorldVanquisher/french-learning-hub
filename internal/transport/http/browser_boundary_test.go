package http

import (
	"context"
	"crypto/tls"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/captureclient"
	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
)

func boundaryPolicy() config.HTTPBoundaryConfig {
	return config.HTTPBoundaryConfig{
		AllowedHosts:   []string{"localhost", "127.0.0.1", "::1", "nas.home", "192.168.1.20", "fd00::20"},
		TrustedOrigins: []string{"http://localhost:5173", "http://127.0.0.1:5173", "http://[::1]:5173", "https://nas.home"},
	}
}

func TestBrowserBoundaryRequestMatrix(t *testing.T) {
	for _, tc := range []struct {
		name, method, host, origin, fetch, contentType string
		body, tls                                      bool
		want                                           int
	}{
		{"release", "POST", "127.0.0.1:8080", "http://127.0.0.1:8080", "same-origin", "application/json", true, false, 204},
		{"legacy release", "POST", "localhost:8080", "http://localhost:8080", "", "application/json", true, false, 204},
		{"bodyless release", "POST", "localhost:8080", "http://localhost:8080", "same-origin", "", false, false, 204},
		{"CLI JSON", "POST", "localhost:8080", "", "", "application/json", true, false, 204},
		{"CLI legacy no type", "POST", "localhost:8080", "", "", "", true, false, 204},
		{"CLI legacy plain", "POST", "localhost:8080", "", "", "text/plain", true, false, 204},
		{"Vite rewritten Host", "POST", "localhost:8080", "http://localhost:5173", "same-origin", "application/json", true, false, 204},
		{"Vite legacy browser", "POST", "127.0.0.1:8080", "http://127.0.0.1:5173", "", "application/json", true, false, 204},
		{"Vite IPv6", "PUT", "[::1]:8080", "http://[::1]:5173", "same-origin", "application/json", true, false, 204},
		{"NAS name", "POST", "NAS.home:8080", "http://nas.home:8080", "same-origin", "application/json", true, false, 204},
		{"NAS IP", "PUT", "192.168.1.20:8080", "http://192.168.1.20:8080", "", "application/json; charset=utf-8", true, false, 204},
		{"NAS IPv6", "POST", "[fd00::20]:8080", "http://[fd00::20]:8080", "", "application/json", true, false, 204},
		{"TLS", "POST", "localhost", "https://localhost:443", "", "application/json", true, true, 204},
		{"HTTP default port", "POST", "localhost:80", "http://localhost", "", "application/json", true, false, 204},
		{"explicit trusted TLS proxy", "POST", "localhost:8080", "https://nas.home", "same-origin", "application/json", true, false, 204},
		{"cross plain", "POST", "localhost:8080", "https://attacker.example", "cross-site", "text/plain", true, false, 403},
		{"cross JSON", "POST", "localhost:8080", "https://attacker.example", "", "application/json", true, false, 403},
		{"cross bodyless provider", "POST", "localhost:8080", "https://attacker.example", "", "", false, false, 403},
		{"misleading metadata", "POST", "localhost:8080", "http://attacker.example", "same-origin", "application/json", true, false, 403},
		{"null", "POST", "localhost:8080", "null", "", "application/json", true, false, 403},
		{"null with same origin metadata", "POST", "localhost:8080", "null", "same-origin", "application/json", true, false, 403},
		{"wrong scheme", "POST", "localhost:8080", "https://localhost:8080", "", "application/json", true, false, 403},
		{"wrong port", "POST", "localhost:8080", "http://localhost:9000", "same-origin", "application/json", true, false, 403},
		{"origin path", "POST", "localhost:8080", "http://localhost:8080/", "", "application/json", true, false, 403},
		{"origin userinfo", "POST", "localhost:8080", "http://user:SECRET@localhost:8080", "", "application/json", true, false, 403},
		{"origin multiple in value", "POST", "localhost:8080", "http://localhost:8080 https://attacker.example", "", "application/json", true, false, 403},
		{"cross metadata without origin", "POST", "localhost:8080", "", "cross-site", "application/json", true, false, 403},
		{"same-site is insufficient", "POST", "localhost:8080", "", "same-site", "application/json", true, false, 403},
		{"form", "POST", "localhost:8080", "http://localhost:8080", "", "application/x-www-form-urlencoded", true, false, 415},
		{"multipart", "POST", "localhost:8080", "http://localhost:8080", "", "multipart/form-data; boundary=x", true, false, 415},
		{"plain same origin", "POST", "localhost:8080", "http://localhost:8080", "", "text/plain", true, false, 415},
		{"missing type with body", "POST", "localhost:8080", "http://localhost:8080", "", "", true, false, 415},
		{"invalid JSON type", "POST", "localhost:8080", "http://localhost:8080", "", "application/json; charset", true, false, 415},
		{"JSON suffix", "POST", "localhost:8080", "http://localhost:8080", "", "application/problem+json", true, false, 415},
		{"rebind read", "GET", "attacker.example:8080", "", "same-origin", "", false, false, 403},
		{"rebind write", "POST", "attacker.example:8080", "http://attacker.example:8080", "same-origin", "application/json", true, false, 403},
		{"unknown IP", "GET", "192.168.1.21:8080", "", "", "", false, false, 403},
		{"Host suffix", "GET", "localhost.attacker.example:8080", "", "", "", false, false, 403},
		{"bad Host", "GET", "localhost:65536", "", "", "", false, false, 403},
		{"safe read", "GET", "localhost:8080", "https://attacker.example", "cross-site", "", false, false, 204},
		{"HEAD", "HEAD", "localhost:8080", "", "", "", false, false, 204},
		{"OPTIONS", "OPTIONS", "localhost:8080", "https://attacker.example", "cross-site", "", false, false, 204},
		{"DELETE", "DELETE", "localhost:8080", "null", "", "", false, false, 403},
	} {
		t.Run(tc.name, func(t *testing.T) {
			calls := 0
			handler, err := NewBrowserBoundary(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				w.WriteHeader(http.StatusNoContent)
			}), boundaryPolicy())
			if err != nil {
				t.Fatal(err)
			}
			var body *strings.Reader
			body = strings.NewReader("")
			if tc.body {
				body = strings.NewReader(`{"original_input":"synthetic"}`)
			}
			req := httptest.NewRequest(tc.method, "/api/entries", body)
			req.Host = tc.host
			for key, value := range map[string]string{"Origin": tc.origin, "Sec-Fetch-Site": tc.fetch, "Content-Type": tc.contentType} {
				if value != "" {
					req.Header.Set(key, value)
				}
			}
			if tc.tls {
				req.TLS = &tls.ConnectionState{}
			}
			// These spoofed headers must not change destination or origin policy.
			req.Header.Set("X-Forwarded-Host", "localhost:8080")
			req.Header.Set("X-Forwarded-Proto", "https")
			req.Header.Set("Forwarded", "host=localhost:8080;proto=https")
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			if rec.Code != tc.want {
				t.Fatalf("status=%d want=%d body=%s", rec.Code, tc.want, rec.Body.String())
			}
			if (calls == 1) != (tc.want == 204) {
				t.Fatalf("downstream calls=%d", calls)
			}
			if strings.Contains(rec.Body.String(), "SECRET") || rec.Header().Get("Access-Control-Allow-Origin") != "" {
				t.Fatal("unsafe response")
			}
		})
	}
}

type boundaryProvider struct{ analysisCalls, extractionCalls int }

func (p *boundaryProvider) Name() string { return "fake:browser-boundary" }
func (p *boundaryProvider) Analyze(context.Context, *domain.Entry) (domain.AnalysisResult, error) {
	p.analysisCalls++
	return domain.AnalysisResult{Category: "grammar", Explanation: "synthetic", Confidence: .9}, nil
}
func (p *boundaryProvider) Extract(context.Context, domain.ExtractionSource) (domain.ExtractionResult, error) {
	p.extractionCalls++
	return domain.ExtractionResult{}, nil
}

func boundaryIntegration(t *testing.T) (http.Handler, *sql.DB, *boundaryProvider) {
	t.Helper()
	db, err := sqlite.Open(filepath.Join(t.TempDir(), "boundary.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	entries := sqlite.NewEntryRepository(db)
	analyses := sqlite.NewAnalysisRepository(db)
	feedback := sqlite.NewFeedbackRepository(db)
	knowledge := sqlite.NewKnowledgeRepository(db)
	admission := sqlite.NewAdmissionRepository(db)
	concepts := sqlite.NewConceptRepository(db)
	provider := &boundaryProvider{}
	entry, err := entries.Create(context.Background(), domain.NewEntryInput{OriginalInput: "synthetic seed"})
	if err != nil {
		t.Fatal(err)
	}
	_, err = analyses.Create(context.Background(), entry.ID, domain.AnalysisResult{Category: "grammar", Explanation: "synthetic seed", Confidence: .9}, "fake:seed")
	if err != nil {
		t.Fatal(err)
	}
	handler := NewHandler(application.NewEntryService(entries), application.NewAnalysisService(entries, analyses, provider), application.NewFeedbackService(feedback), application.NewEffectiveAnalysisService(analyses, feedback), application.NewInventoryService(sqlite.NewInventoryRepository(db)), application.NewCaptureService(sqlite.NewCaptureRepository(db)), application.NewKnowledgeService(entries, analyses, feedback, knowledge, admission, provider), application.NewConceptService(knowledge, concepts, concepts), nil, nil)
	web := t.TempDir()
	if err := os.WriteFile(filepath.Join(web, "index.html"), []byte("synthetic workbench"), 0600); err != nil {
		t.Fatal(err)
	}
	routes, err := NewWorkbenchHandler(handler.Routes(), web)
	if err != nil {
		t.Fatal(err)
	}
	routes, err = NewBrowserBoundary(routes, boundaryPolicy())
	if err != nil {
		t.Fatal(err)
	}
	return routes, db, provider
}

func totalChanges(t *testing.T, db *sql.DB) int64 {
	t.Helper()
	var changes int64
	if err := db.QueryRow("SELECT total_changes()").Scan(&changes); err != nil {
		t.Fatal(err)
	}
	return changes
}

func TestBrowserBoundaryBlockedRequestsHaveNoSideEffects(t *testing.T) {
	handler, db, provider := boundaryIntegration(t)
	before := totalChanges(t, db)
	paths := []struct{ method, path string }{
		{"POST", "/entries"}, {"POST", "/captures"}, {"POST", "/entries/1/analysis"}, {"POST", "/entries/1/extractions"},
		{"POST", "/analyses/1/feedback"}, {"POST", "/knowledge-units/1/admission-overrides"}, {"POST", "/concepts"},
		{"POST", "/concepts/1/preferred-unit"}, {"POST", "/knowledge-units/1/concept-links/same"}, {"PUT", "/knowledge-units/1/concept-membership"},
		{"POST", "/knowledge-units/1/concept-membership/reject"}, {"POST", "/knowledge-units/1/invalid"}, {"POST", "/knowledge-units/1/invalid/restore"},
		{"POST", "/knowledge-units/1/concept-distinctions"}, {"POST", "/knowledge-units/1/concept-links/relation"}, {"PUT", "/entries/1/current-extraction"},
	}
	for _, prefix := range []string{"", "/api"} {
		for _, route := range paths {
			for _, variant := range []string{"cross plain", "cross JSON", "null", "rebind", "form", "fetch only"} {
				t.Run(prefix+route.path+"/"+variant, func(t *testing.T) {
					req := httptest.NewRequest(route.method, prefix+route.path, strings.NewReader(`{"original_input":"must not write"}`))
					req.Host = "localhost:8080"
					req.Header.Set("Origin", "https://attacker.example")
					req.Header.Set("Content-Type", "application/json")
					want := 403
					switch variant {
					case "cross plain":
						req.Header.Set("Content-Type", "text/plain")
					case "null":
						req.Header.Set("Origin", "null")
						req.Header.Set("Sec-Fetch-Site", "same-origin")
					case "rebind":
						req.Host = "attacker.example:8080"
						req.Header.Set("Origin", "http://attacker.example:8080")
						req.Header.Set("Sec-Fetch-Site", "same-origin")
					case "form":
						req.Header.Set("Origin", "http://localhost:8080")
						req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
						want = 415
					case "fetch only":
						req.Header.Del("Origin")
						req.Header.Set("Sec-Fetch-Site", "cross-site")
					}
					rec := httptest.NewRecorder()
					handler.ServeHTTP(rec, req)
					if rec.Code != want {
						t.Fatalf("status=%d want=%d body=%s", rec.Code, want, rec.Body.String())
					}
					if totalChanges(t, db) != before || provider.analysisCalls != 0 || provider.extractionCalls != 0 {
						t.Fatal("blocked request wrote data or called provider")
					}
				})
			}
		}
	}
}

func TestBrowserBoundaryAllowedWorkflowsAndCaptureClient(t *testing.T) {
	handler, db, provider := boundaryIntegration(t)
	for _, prefix := range []string{"", "/api"} {
		for _, origin := range []string{"", "http://localhost:8080", "http://localhost:5173"} {
			req := httptest.NewRequest("POST", prefix+"/entries", strings.NewReader(`{"original_input":"allowed"}`))
			req.Host = "localhost:8080"
			req.Header.Set("Content-Type", "application/json")
			if origin != "" {
				req.Header.Set("Origin", origin)
				req.Header.Set("Sec-Fetch-Site", "same-origin")
			}
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			if rec.Code != 201 {
				t.Fatalf("entry: %d %s", rec.Code, rec.Body.String())
			}
		}
		for _, operation := range []string{"analysis", "extractions"} {
			req := httptest.NewRequest("POST", prefix+"/entries/1/"+operation, nil)
			req.Host = "localhost:8080"
			req.Header.Set("Origin", "http://localhost:8080")
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)
			if rec.Code != 201 {
				t.Fatalf("bodyless %s: %d %s", operation, rec.Code, rec.Body.String())
			}
		}
	}
	if provider.analysisCalls != 2 || provider.extractionCalls != 2 {
		t.Fatalf("provider counters %+v", provider)
	}
	srv := httptest.NewServer(handler)
	defer srv.Close()
	for i, prefix := range []string{"", "/api"} {
		client, err := captureclient.New(srv.URL + prefix)
		if err != nil {
			t.Fatal(err)
		}
		payload := fmt.Sprintf(`{"schema_version":"learning_capture_v1","capture_id":"boundary-%d","source":"manual","original_input":"CLI capture","original_context":"synthetic"}`, i)
		result, err := client.Import(context.Background(), []byte(payload))
		if err != nil || !result.Created {
			t.Fatalf("capture result=%+v err=%v", result, err)
		}
	}
	var count int
	if err := db.QueryRow("SELECT COUNT(*) FROM learning_entries").Scan(&count); err != nil || count != 9 {
		t.Fatalf("entry count=%d err=%v", count, err)
	}
}

func TestBrowserBoundaryDuplicateHeadersAndNoCORSPreflight(t *testing.T) {
	for _, header := range []string{"Origin", "Sec-Fetch-Site", "Content-Type"} {
		called := false
		handler, err := NewBrowserBoundary(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { called = true }), boundaryPolicy())
		if err != nil {
			t.Fatal(err)
		}
		req := httptest.NewRequest("POST", "/entries", strings.NewReader(`{}`))
		req.Host = "localhost:8080"
		req.Header.Set("Origin", "http://localhost:8080")
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Sec-Fetch-Site", "same-origin")
		req.Header.Add(header, req.Header.Get(header))
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if called || rec.Code < 400 {
			t.Fatalf("duplicate %s allowed", header)
		}
		var errorBody map[string]string
		if err := json.Unmarshal(rec.Body.Bytes(), &errorBody); err != nil || errorBody["error"] == "" {
			t.Fatal("missing clear JSON error")
		}
	}
	handler, _, _ := boundaryIntegration(t)
	req := httptest.NewRequest("OPTIONS", "/api/entries", nil)
	req.Host = "localhost:8080"
	req.Header.Set("Origin", "https://attacker.example")
	req.Header.Set("Access-Control-Request-Method", "POST")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != 405 || rec.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Fatalf("unexpected CORS preflight: %d %v", rec.Code, rec.Header())
	}
}

func TestBrowserBoundaryInvalidPolicy(t *testing.T) {
	for _, policy := range []config.HTTPBoundaryConfig{{}, {AllowedHosts: []string{"*"}}, {AllowedHosts: []string{"localhost"}, TrustedOrigins: []string{"http://user:SECRET@localhost"}}} {
		_, err := NewBrowserBoundary(http.NotFoundHandler(), policy)
		if err == nil || strings.Contains(err.Error(), "SECRET") {
			t.Fatalf("invalid policy error=%v", err)
		}
	}
}

// Rejections must happen before even reading the supplied learning content.
type boundaryUnreadBody struct{ reads int }

func (b *boundaryUnreadBody) Read([]byte) (int, error) {
	b.reads++
	return 0, fmt.Errorf("body should not be read")
}
func (b *boundaryUnreadBody) Close() error { return nil }

func TestBrowserBoundaryRejectsBeforeReadingChunkedBody(t *testing.T) {
	for _, origin := range []string{"null", "http://localhost:8080"} {
		body := &boundaryUnreadBody{}
		handler, err := NewBrowserBoundary(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { t.Fatal("downstream called") }), boundaryPolicy())
		if err != nil {
			t.Fatal(err)
		}
		req := httptest.NewRequest("POST", "/api/entries", nil)
		req.Host = "localhost:8080"
		req.Header.Set("Origin", origin)
		req.Body = body
		req.ContentLength = -1
		req.TransferEncoding = []string{"chunked"}
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code < 400 || body.reads != 0 {
			t.Fatalf("status=%d body reads=%d", rec.Code, body.reads)
		}
	}
}
