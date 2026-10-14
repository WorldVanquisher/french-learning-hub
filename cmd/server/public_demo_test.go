package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"french-learning-app/internal/config"
	"french-learning-app/internal/publicdemo"
)

func demoConfig() config.Config {
	return config.Config{
		AI:           config.AIConfig{Provider: config.ProviderRuleBased},
		Extractor:    config.ExtractorConfig{Provider: config.ExtractorDisabled},
		Embedding:    config.EmbeddingConfig{Provider: config.EmbeddingDisabled},
		Semantic:     config.SemanticConfig{Mode: config.SemanticDisabled},
		HTTPBoundary: config.HTTPBoundaryConfig{AllowedHosts: []string{"127.0.0.1"}},
	}
}

func demoArtifact(t *testing.T) string {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "artifact")
	if _, err := publicdemo.Build(context.Background(), "../../scripts/demo/flh073/fixtures/catalog.json", dir); err != nil {
		t.Fatal(err)
	}
	return dir
}

func demoWebDir(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "assets"), 0o755); err != nil {
		t.Fatal(err)
	}
	os.WriteFile(filepath.Join(dir, "index.html"), []byte("<!doctype html><title>demo</title>"), 0o644)
	os.WriteFile(filepath.Join(dir, "assets", "app.js"), []byte("console.log(1)"), 0o644)
	return dir
}

type demoFixture struct {
	srv      *httptest.Server
	artifact string
	d        *demoServer
}

func startDemo(t *testing.T) *demoFixture {
	t.Helper()
	art := demoArtifact(t)
	d, err := buildPublicDemo(demoConfig(), art, true, demoWebDir(t))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { d.close() })
	srv := httptest.NewServer(d.routes)
	t.Cleanup(srv.Close)
	return &demoFixture{srv: srv, artifact: art, d: d}
}

func (f *demoFixture) do(t *testing.T, method, path string) (int, []byte, http.Header) {
	t.Helper()
	req, err := http.NewRequest(method, f.srv.URL+path, strings.NewReader(`{"original_input":"x"}`))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, body, resp.Header
}

func (f *demoFixture) json(t *testing.T, path string) map[string]any {
	t.Helper()
	status, body, _ := f.do(t, http.MethodGet, path)
	if status != 200 {
		t.Fatalf("GET %s: %d %s", path, status, body)
	}
	var out map[string]any
	if err := json.Unmarshal(body, &out); err != nil {
		t.Fatalf("GET %s: %v", path, err)
	}
	return out
}

// state is everything a denied request must leave unchanged.
type demoState struct {
	dbSHA, fingerprint string
	lookups, refused   int64
}

func (f *demoFixture) state(t *testing.T) demoState {
	t.Helper()
	sum, err := publicdemo.SHA256File(filepath.Join(f.artifact, publicdemo.DatabaseFile))
	if err != nil {
		t.Fatal(err)
	}
	db, err := publicdemo.OpenReadOnly(filepath.Join(f.artifact, publicdemo.DatabaseFile))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	fp, err := publicdemo.ComputeFingerprint(context.Background(), db)
	if err != nil {
		t.Fatal(err)
	}
	info := f.json(t, "/knowledge-library/demo")["counters"].(map[string]any)
	return demoState{dbSHA: sum, fingerprint: fp.SHA256, lookups: int64(info["preset_vector_lookups"].(float64)), refused: int64(info["refused_vector_lookups"].(float64))}
}

func TestPublicDemo_RefusesLiveProvidersAndMechanicalReleaseArtifacts(t *testing.T) {
	art := demoArtifact(t)
	cases := map[string]func(*config.Config){
		"openai analyzer":   func(c *config.Config) { c.AI.Provider = config.ProviderOpenAI },
		"openai extractor":  func(c *config.Config) { c.Extractor.Provider = config.ExtractorOpenAI },
		"http embedding":    func(c *config.Config) { c.Embedding.Provider = config.EmbeddingHTTP },
		"qdrant semantic":   func(c *config.Config) { c.Semantic.Mode = config.SemanticQdrant },
		"unknown analyzer?": func(c *config.Config) { c.AI.Provider = "something-else" },
	}
	for name, mutate := range cases {
		cfg := demoConfig()
		mutate(&cfg)
		if _, err := buildPublicDemo(cfg, art, true, ""); err == nil || !strings.Contains(err.Error(), "refuses live providers") {
			t.Fatalf("%s: %v", name, err)
		}
	}
	if _, err := buildPublicDemo(demoConfig(), art, false, ""); err == nil || !strings.Contains(err.Error(), "mechanical test fixtures") {
		t.Fatalf("a mechanical artifact must need the explicit local flag: %v", err)
	}
	if _, err := buildPublicDemo(demoConfig(), filepath.Join(t.TempDir(), "missing"), true, ""); err == nil {
		t.Fatal("a missing artifact must refuse startup")
	}
}

func TestPublicDemo_AllowedRoutesAtRootAndAPI(t *testing.T) {
	f := startDemo(t)
	info := f.json(t, "/knowledge-library/demo")
	art := info["artifact"].(map[string]any)
	if info["schema_version"] != "knowledge_library_public_demo_v1" || info["read_only"] != true || info["data"] != "synthetic" ||
		art["vector_source"] != "mechanical-test" || art["real_model"] != false || art["release_status"] != "blocked_mechanical_vectors" ||
		!strings.Contains(art["notice"].(string), "say nothing about semantic relevance") || len(info["presets"].([]any)) != 8 {
		t.Fatalf("info = %v", info)
	}
	concepts := f.json(t, "/knowledge-library/concepts")
	first := concepts["results"].([]any)[0].(map[string]any)["concept"].(map[string]any)
	id := int(first["id"].(float64))
	detail := f.json(t, "/knowledge-library/concepts/"+itoa(id))
	var unitID int
	for _, key := range []string{"supporting_units", "non_supporting_members"} {
		if units := detail[key].([]any); len(units) > 0 && unitID == 0 {
			unitID = int(units[0].(map[string]any)["unit_id"].(float64))
		}
	}
	if unitID == 0 {
		t.Fatalf("concept %d has no member to trace: %v", id, detail)
	}
	src := f.json(t, "/knowledge-library/units/"+itoa(unitID)+"/source")
	if !strings.Contains(src["entry"].(map[string]any)["original_input"].(string), "?") ||
		src["extraction"].(map[string]any)["extractor"] != publicdemo.FixtureExtractor {
		t.Fatalf("provenance = %v", src)
	}
	sem := f.json(t, "/knowledge-library/demo/semantic-search?preset=miss-someone&limit=5")
	if sem["schema_version"] != "knowledge_library_semantic_search_v2" || sem["query"] != "how to tell a friend I miss them" ||
		sem["index"].(map[string]any)["last_run_operation"] != "artifact" || len(sem["results"].([]any)) == 0 {
		t.Fatalf("semantic = %v", sem)
	}
	hyb := f.json(t, "/knowledge-library/demo/hybrid-search?preset=subjunctive&limit=5&depth=20&state=active")
	if hyb["schema_version"] != "knowledge_library_hybrid_search_v1" || hyb["query"] != "subjunctive" ||
		hyb["policy"].(map[string]any)["version"] != "concept_hybrid_rrf_v1" || hyb["state"] != "active" || hyb["depth"] != float64(20) {
		t.Fatalf("hybrid = %v", hyb)
	}
	for _, p := range []string{"/healthz", "/readyz", "/knowledge-library/concepts?q=subj", "/knowledge-library/concepts/" + itoa(id),
		"/knowledge-library/units/" + itoa(unitID) + "/source", "/knowledge-library/demo/semantic-search?preset=no-longer",
		"/knowledge-library/demo/hybrid-search?preset=no-longer"} {
		sRoot, bRoot, _ := f.do(t, http.MethodGet, p)
		sAPI, bAPI, _ := f.do(t, http.MethodGet, "/api"+p)
		if sRoot != 200 || sAPI != 200 || string(bRoot) != string(bAPI) {
			t.Fatalf("%s: root %d api %d (equal bodies: %v)", p, sRoot, sAPI, string(bRoot) == string(bAPI))
		}
	}
	for _, p := range []string{"/", "/assets/app.js"} {
		if status, _, _ := f.do(t, http.MethodGet, p); status != 200 {
			t.Fatalf("static %s: %d", p, status)
		}
	}
	if status, _, _ := f.do(t, http.MethodHead, "/knowledge-library/demo"); status != 200 {
		t.Fatal("HEAD must be allowed")
	}
}

func TestPublicDemo_DeniedRequestsChangeNothing(t *testing.T) {
	f := startDemo(t)
	before := f.state(t)
	writes := []string{"/entries", "/captures", "/entries/1/analyses", "/entries/1/extractions", "/concepts",
		"/knowledge-units/1/concept-links/same", "/knowledge-library/concepts", "/knowledge-library/demo/hybrid-search?preset=subjunctive"}
	for _, m := range []string{http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete} {
		for _, p := range writes {
			for _, prefix := range []string{"", "/api"} {
				status, _, h := f.do(t, m, prefix+p)
				if status != http.StatusMethodNotAllowed || h.Get("Allow") != "GET, HEAD" {
					t.Fatalf("%s %s%s: %d", m, prefix, p, status)
				}
			}
		}
	}
	deniedGets := []string{
		// free-text semantic/hybrid would embed visitor input: denied outright
		"/knowledge-library/semantic-search?q=anything+at+all", "/knowledge-library/hybrid-search?q=anything+at+all",
		// provider-triggering or full-surface reads
		"/retrieval-evaluation/v1?retriever=embedding_retriever_v1", "/retrieval-comparison/v1", "/annotation-dataset/v1/export",
		"/annotation-dataset/v1/quality", "/entries", "/entries/1", "/entries/1/analyses", "/inventory", "/concepts",
		"/reviewable-units", "/knowledge-units/1/concept-resolution", "/annotation-operations/x", "/unknown",
	}
	for _, p := range deniedGets {
		for _, prefix := range []string{"", "/api"} {
			if status, _, _ := f.do(t, http.MethodGet, prefix+p); status != http.StatusNotFound {
				t.Fatalf("GET %s%s: %d", prefix, p, status)
			}
		}
	}
	// Preset routes accept only preset ids: no free text reaches the provider.
	badPreset := map[string]int{
		"?q=how+to+say+hello": 400, "?preset=miss-someone&q=free+text": 400, "?preset=": 400, "?preset=nope": 404,
		"?preset=miss-someone&preset=no-longer": 400, "?preset=miss-someone&text=x": 400, "?preset=miss-someone&limit=0": 400,
	}
	for qs, want := range badPreset {
		for _, route := range []string{"semantic-search", "hybrid-search"} {
			if status, body, _ := f.do(t, http.MethodGet, "/api/knowledge-library/demo/"+route+qs); status != want {
				t.Fatalf("%s%s: %d %s", route, qs, status, body)
			}
		}
	}
	// Host protection is preserved in front of the allowlist.
	req, _ := http.NewRequest(http.MethodGet, f.srv.URL+"/knowledge-library/demo", nil)
	req.Host = "evil.example"
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("foreign Host: %d", resp.StatusCode)
	}
	after := f.state(t)
	if after != before {
		t.Fatalf("denied requests changed state:\nbefore %+v\nafter  %+v", before, after)
	}
	if before.lookups != 0 || before.refused != 0 {
		t.Fatalf("no preset vector may be used before a valid preset search: %+v", before)
	}
	// A valid preset search performs exactly one cached lookup, and still writes nothing.
	f.json(t, "/knowledge-library/demo/hybrid-search?preset=no-longer")
	final := f.state(t)
	if final.lookups != 1 || final.refused != 0 || final.dbSHA != before.dbSHA || final.fingerprint != before.fingerprint {
		t.Fatalf("after one hybrid preset search: %+v", final)
	}
}

func itoa(n int) string {
	b, _ := json.Marshal(n)
	return string(b)
}
