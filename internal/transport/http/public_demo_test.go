package http_test

import (
	"net/http"
	"net/http/httptest"
	"testing"

	transporthttp "french-learning-app/internal/transport/http"
)

// The allowlist decides before any inner handler runs: a recording inner
// handler must see exactly the allowed requests.
func TestPublicDemoBoundary_DecidesBeforeAnyHandler(t *testing.T) {
	var reached []string
	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		reached = append(reached, r.Method+" "+r.URL.Path)
		w.WriteHeader(299)
	})
	h := transporthttp.NewPublicDemoBoundary(inner, true)
	do := func(method, target string) *httptest.ResponseRecorder {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(method, target, nil))
		return rec
	}
	allowed := []string{
		"/healthz", "/readyz", "/knowledge-library/concepts", "/knowledge-library/concepts?q=subj&state=active&limit=5",
		"/knowledge-library/concepts/12", "/knowledge-library/units/3/source", "/knowledge-library/demo",
		"/knowledge-library/demo/semantic-search?preset=x", "/knowledge-library/demo/hybrid-search?preset=x",
		"/", "/assets/index-abc.js",
	}
	for _, p := range allowed {
		for _, prefix := range []string{"", "/api"} {
			if prefix != "" && (p == "/" || p[:7] == "/assets") {
				continue
			}
			for _, m := range []string{http.MethodGet, http.MethodHead} {
				if rec := do(m, prefix+p); rec.Code != 299 {
					t.Fatalf("%s %s%s: %d", m, prefix, p, rec.Code)
				}
			}
		}
	}
	n := len(reached)
	denied := []string{
		"/entries", "/entries/1", "/entries/1/analyses", "/entries/1/extractions", "/entries/1/current-extraction",
		"/inventory", "/inventory/export", "/captures/x", "/concepts", "/concepts/1", "/reviewable-units",
		"/knowledge-units/1/concept-resolution", "/annotation-dataset/v1/export", "/annotation-dataset/v1/quality",
		"/retrieval-evaluation/v1", "/retrieval-comparison/v1", "/annotation-operations/x",
		"/knowledge-library/semantic-search", "/knowledge-library/hybrid-search",
		"/knowledge-library/concepts/", "/knowledge-library/concepts/x", "/knowledge-library/concepts/1/../2",
		"/knowledge-library/concepts//1", "/knowledge-library/units/1/source/extra", "/knowledge-library/demo/",
		"/knowledge-library/demo/other", "/unknown", "/api", "/api/", "/api/unknown", "/api/assets/app.js", "/assets/",
		"/knowledge-library%2Fconcepts", "/KNOWLEDGE-LIBRARY/concepts",
	}
	for _, p := range denied {
		for _, prefix := range []string{"", "/api"} {
			rec := do(http.MethodGet, prefix+p)
			if rec.Code != http.StatusNotFound {
				t.Fatalf("GET %s%s: %d", prefix, p, rec.Code)
			}
		}
	}
	for _, m := range []string{http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete, http.MethodOptions, "TRACE"} {
		for _, p := range []string{"/entries", "/api/captures", "/knowledge-library/concepts", "/api/knowledge-library/concepts/1",
			"/concepts", "/knowledge-units/1/concept-membership", "/", "/knowledge-library/demo/hybrid-search?preset=x"} {
			rec := do(m, p)
			if rec.Code != http.StatusMethodNotAllowed || rec.Header().Get("Allow") != "GET, HEAD" {
				t.Fatalf("%s %s: %d %q", m, p, rec.Code, rec.Header().Get("Allow"))
			}
		}
	}
	if len(reached) != n {
		t.Fatalf("denied requests reached the handler: %v", reached[n:])
	}
	// Without the demo web build, / and /assets are not served either.
	api := transporthttp.NewPublicDemoBoundary(inner, false)
	for _, p := range []string{"/", "/assets/app.js"} {
		rec := httptest.NewRecorder()
		api.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, p, nil))
		if rec.Code != http.StatusNotFound {
			t.Fatalf("API-only demo %s: %d", p, rec.Code)
		}
	}
}

func TestPublicDemoRoutes_AbsentInNormalMode(t *testing.T) {
	root, api := hybridServers(t, transporthttp.WithHybridSearch(&fakeHybrid{}))
	for _, base := range []string{root.URL, api.URL + "/api"} {
		for _, p := range []string{"/knowledge-library/demo", "/knowledge-library/demo/semantic-search?preset=x", "/knowledge-library/demo/hybrid-search?preset=x"} {
			resp, err := http.Get(base + p)
			if err != nil {
				t.Fatal(err)
			}
			resp.Body.Close()
			if resp.StatusCode != http.StatusNotFound {
				t.Fatalf("normal mode %s%s: %d", base, p, resp.StatusCode)
			}
		}
	}
	// The normal free-text hybrid route is unaffected by the demo code.
	if status, _ := semanticGet(t, root.URL+"/knowledge-library/hybrid-search?q=x"); status != 200 {
		t.Fatalf("normal hybrid: %d", status)
	}
}
