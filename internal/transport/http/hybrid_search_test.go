package http_test

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

type fakeHybrid struct {
	err   error
	query application.HybridSearchQuery
	calls int
}

func (f *fakeHybrid) Search(_ context.Context, q application.HybridSearchQuery) (*application.HybridSearchReport, error) {
	f.calls++
	f.query = q
	if f.err != nil {
		return nil, f.err
	}
	published := time.Date(2026, 10, 10, 0, 0, 0, 0, time.UTC)
	c := func(id int64, target string) domain.KnowledgeConcept {
		return domain.KnowledgeConcept{ID: id, Target: target, PedagogicalIntent: "grammar", IdentityFeatures: map[string]string{}, State: domain.ConceptActive}
	}
	return &application.HybridSearchReport{
		Query: q.Text, State: q.State, Limit: q.Limit, Depth: q.Depth,
		Keyword: &application.LibrarySearchReport{TotalMatches: 7, Truncated: true, Results: make([]application.LibrarySearchResult, 2)},
		Semantic: &application.SemanticSearchReport{QueryRepresentation: application.ConceptSearchQueryRepresentationV2, Considered: 8, SkippedStale: 1,
			FilteredByState: 2, Results: make([]application.SemanticSearchResult, 2),
			Space:       application.SemanticIndexSpace{Collection: "space", Representation: "concept_embedding_text_v1", ModelID: "m", Dimensions: 8},
			Collection:  "space_rabc",
			Publication: application.SemanticIndexSpaceState{PublishedRunID: "abc", PublishedAt: &published, LastRunOutcome: "published"}},
		TotalCandidates: 3, Truncated: true,
		Dropped: application.HybridDropped{Missing: 1, ChangedDuringSearch: 1},
		Results: []application.HybridSearchResult{
			{Concept: c(20, "both"), FusedScore: application.FuseReciprocalRank(2, 1),
				Keyword:  &application.HybridKeywordEvidence{Rank: 2, MatchTier: "identity", MatchedFields: []string{"target"}},
				Semantic: &application.HybridSemanticEvidence{Rank: 1, Similarity: 0.61}, CurrentMemberCount: 2, SupportingUnitCount: 1},
			{Concept: c(40, "semantic only"), FusedScore: application.FuseReciprocalRank(0, 2),
				Semantic: &application.HybridSemanticEvidence{Rank: 2, Similarity: 0.33}},
		},
	}, nil
}

func hybridServers(t *testing.T, opts ...transporthttp.HandlerOption) (*httptest.Server, *httptest.Server) {
	t.Helper()
	h := transporthttp.NewHandler(nil, nil, nil, nil, nil, nil, nil, nil, nil, nil, opts...)
	root := httptest.NewServer(h.Routes())
	t.Cleanup(root.Close)
	webDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(webDir, "index.html"), []byte("<!doctype html>"), 0o600); err != nil {
		t.Fatal(err)
	}
	wb, err := transporthttp.NewWorkbenchHandler(h.Routes(), webDir)
	if err != nil {
		t.Fatal(err)
	}
	api := httptest.NewServer(wb)
	t.Cleanup(api.Close)
	return root, api
}

func TestHybridSearchHTTP_ExactResponseAtRootAndAPI(t *testing.T) {
	svc := &fakeHybrid{}
	root, api := hybridServers(t, transporthttp.WithHybridSearch(svc))
	var bodies [][]byte
	for _, base := range []string{root.URL, api.URL + "/api"} {
		resp, err := http.Get(base + "/knowledge-library/hybrid-search?q=subjonctif&state=active&limit=2&depth=10")
		if err != nil {
			t.Fatal(err)
		}
		var raw json.RawMessage
		if err := json.NewDecoder(resp.Body).Decode(&raw); err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		if resp.StatusCode != 200 || !strings.HasPrefix(resp.Header.Get("Content-Type"), "application/json") {
			t.Fatalf("%s: %d %s", base, resp.StatusCode, raw)
		}
		bodies = append(bodies, raw)
	}
	if string(bodies[0]) != string(bodies[1]) {
		t.Fatal("root and /api responses differ")
	}
	if svc.query.Text != "subjonctif" || svc.query.Limit != 2 || svc.query.Depth != 10 || *svc.query.State != domain.ConceptActive {
		t.Fatalf("query = %+v", svc.query)
	}
	var body map[string]any
	if err := json.Unmarshal(bodies[0], &body); err != nil {
		t.Fatal(err)
	}
	wantPolicy := map[string]any{"version": "concept_hybrid_rrf_v1", "rrf_k": float64(60),
		"weights": map[string]any{"keyword": float64(1), "semantic": float64(1)}, "tie_break": "concept_id_ascending"}
	if body["schema_version"] != "knowledge_library_hybrid_search_v1" || !reflect.DeepEqual(body["policy"], wantPolicy) ||
		body["state"] != "active" || body["limit"] != float64(2) || body["depth"] != float64(10) ||
		body["total_candidates"] != float64(3) || body["truncated"] != true {
		t.Fatalf("body = %s", bodies[0])
	}
	if !strings.Contains(body["score_note"].(string), "not a probability or a relevance estimate") {
		t.Fatalf("score_note = %v", body["score_note"])
	}
	wantDropped := map[string]any{"missing": float64(1), "filtered_by_state": float64(0), "changed_during_search": float64(1), "duplicate_component_ids": float64(0)}
	if !reflect.DeepEqual(body["dropped_after_fusion"], wantDropped) {
		t.Fatalf("dropped = %v", body["dropped_after_fusion"])
	}
	comp := body["components"].(map[string]any)
	kw, sem := comp["keyword"].(map[string]any), comp["semantic"].(map[string]any)
	if kw["returned"] != float64(2) || kw["total_matches"] != float64(7) || kw["truncated_at_depth"] != true ||
		!strings.Contains(kw["matching"].(string), "not a relevance score") {
		t.Fatalf("keyword component = %v", kw)
	}
	idx := sem["index"].(map[string]any)
	if sem["returned"] != float64(2) || sem["considered"] != float64(8) || sem["filtered_by_state"] != float64(2) ||
		sem["query_representation"] != application.ConceptSearchQueryRepresentationV2 ||
		sem["skipped"].(map[string]any)["stale"] != float64(1) ||
		idx["collection"] != "space_rabc" || idx["health_verified"] != false || idx["published_run_id"] != "abc" {
		t.Fatalf("semantic component = %v", sem)
	}
	results := body["results"].([]any)
	first, second := results[0].(map[string]any), results[1].(map[string]any)
	if first["concept"].(map[string]any)["id"] != float64(20) || !reflect.DeepEqual(first["sources"], []any{"keyword", "semantic"}) ||
		math.Abs(first["fused_score"].(float64)-(1.0/62+1.0/61)) > 1e-15 ||
		!reflect.DeepEqual(first["keyword"], map[string]any{"rank": float64(2), "match_tier": "identity", "matched_fields": []any{"target"}}) ||
		!reflect.DeepEqual(first["semantic"], map[string]any{"rank": float64(1), "similarity": 0.61}) ||
		first["current_member_count"] != float64(2) || first["supporting_unit_count"] != float64(1) {
		t.Fatalf("first = %v", first)
	}
	if second["keyword"] != nil || !reflect.DeepEqual(second["sources"], []any{"semantic"}) {
		t.Fatalf("a missing component is null, not zero: %v", second)
	}
}

func TestHybridSearchHTTP_ValidationAndMethods(t *testing.T) {
	svc := &fakeHybrid{}
	root, _ := hybridServers(t, transporthttp.WithHybridSearch(svc))
	for _, bad := range []string{"", "?q=", "?q=%20%20", "?q=x&limit=0", "?q=x&limit=51", "?q=x&limit=nope", "?q=x&depth=0",
		"?q=x&depth=51", "?q=x&depth=nope", "?q=x&limit=30&depth=20", "?q=x&state=gone", "?q=" + strings.Repeat("a", 201)} {
		if status, _ := semanticGet(t, root.URL+"/knowledge-library/hybrid-search"+bad); status != 400 {
			t.Fatalf("%q: status %d", bad, status)
		}
	}
	if svc.calls != 0 {
		t.Fatalf("invalid requests must not reach the service: %d", svc.calls)
	}
	if status, _ := semanticGet(t, root.URL+"/knowledge-library/hybrid-search?q=x"); status != 200 || svc.query.Limit != 20 || svc.query.Depth != 50 {
		t.Fatalf("defaults: %d %+v", status, svc.query)
	}
	resp, err := http.Post(root.URL+"/knowledge-library/hybrid-search?q=x", "application/json", nil)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusMethodNotAllowed {
		t.Fatalf("POST status %d", resp.StatusCode)
	}
}

func TestHybridSearchHTTP_ExplicitFailuresWithoutKeywordFallback(t *testing.T) {
	// Keyword library configured, hybrid not: 503, never a keyword-only answer.
	root, api := hybridServers(t, transporthttp.WithKnowledgeLibrary(nil))
	for _, base := range []string{root.URL, api.URL + "/api"} {
		status, body := semanticGet(t, base+"/knowledge-library/hybrid-search?q=x")
		if status != 503 || !strings.Contains(fmt.Sprint(body["error"]), "needs semantic search") {
			t.Fatalf("%s: %d %v", base, status, body)
		}
	}
	cases := map[error]int{
		application.ErrSemanticIndexNotBuilt:        409,
		application.ErrSemanticIndexIncompatible:    409,
		application.ErrEmbeddingProviderTimeout:     504,
		application.ErrEmbeddingProviderUnavailable: 502,
		application.ErrVectorIndexTimeout:           504,
		application.ErrVectorIndexUnavailable:       502,
		application.ErrSemanticPublicationChanged:   500,
		application.ErrKnowledgeLibraryQuery:        400,
		fmt.Errorf("secret provider body sk-123"):   500,
	}
	for e, want := range cases {
		svc := &fakeHybrid{err: e}
		root, _ := hybridServers(t, transporthttp.WithHybridSearch(svc))
		status, body := semanticGet(t, root.URL+"/knowledge-library/hybrid-search?q=x")
		if status != want || body["results"] != nil {
			t.Fatalf("%v: %d %v", e, status, body)
		}
		if strings.Contains(fmt.Sprint(body), "sk-123") {
			t.Fatal("provider details must not reach the response")
		}
	}
}

// stubSemanticSearcher returns fixed semantic ranks over real Concepts.
type stubSemanticSearcher struct {
	ids  []int64
	err  error
	list func() []domain.KnowledgeConcept
}

func (s *stubSemanticSearcher) Search(_ context.Context, q application.LibrarySearchQuery) (*application.SemanticSearchReport, error) {
	if s.err != nil {
		return nil, s.err
	}
	byID := map[int64]domain.KnowledgeConcept{}
	for _, c := range s.list() {
		byID[c.ID] = c
	}
	r := &application.SemanticSearchReport{Query: q.Text, QueryRepresentation: application.ConceptSearchQueryRepresentationV2,
		Limit: q.Limit, Collection: "space_rstub", Results: []application.SemanticSearchResult{}}
	for i, id := range s.ids {
		c, ok := byID[id]
		if !ok || (q.State != nil && c.State != *q.State) || len(r.Results) == q.Limit {
			continue
		}
		r.Results = append(r.Results, application.SemanticSearchResult{Concept: c, Similarity: 0.5 - 0.1*float64(i)})
	}
	return r, nil
}

func TestHybridSearchHTTP_RealKeywordStackAndFusion(t *testing.T) {
	f := setupLibrary(t)
	ctx := context.Background()
	list := func() []domain.KnowledgeConcept {
		cs, err := f.concepts.ListConcepts(ctx, nil)
		if err != nil {
			t.Fatal(err)
		}
		return cs
	}
	before := list()
	// Semantic ranks: C2 first, C3 second (C3 has no keyword match for "subjonctif").
	sem := &stubSemanticSearcher{ids: []int64{f.ids["C2"], f.ids["C3"]}, list: list}
	conceptRepo := sqlite.NewConceptRepository(f.db)
	library := application.NewKnowledgeLibraryService(conceptRepo, sqlite.NewKnowledgeRepository(f.db), sqlite.NewEntryRepository(f.db),
		sqlite.NewAnalysisRepository(f.db), sqlite.NewFeedbackRepository(f.db), application.NewEffectiveAnnotationService(conceptRepo, conceptRepo))
	hybrid := application.NewHybridSearchService(library, sem, f.concepts, library)
	root, api := hybridServers(t, transporthttp.WithHybridSearch(hybrid))

	var body struct {
		Results []struct {
			Concept struct {
				ID int64 `json:"id"`
			} `json:"concept"`
			FusedScore float64  `json:"fused_score"`
			Sources    []string `json:"sources"`
			Keyword    *struct {
				Rank int `json:"rank"`
			} `json:"keyword"`
			Semantic *struct {
				Rank int `json:"rank"`
			} `json:"semantic"`
		} `json:"results"`
		Components struct {
			Keyword struct {
				TotalMatches int `json:"total_matches"`
			} `json:"keyword"`
		} `json:"components"`
	}
	libraryGet(t, root.URL+"/knowledge-library/hybrid-search?q=subjonctif&limit=5&depth=5", 200, &body)
	// Keyword "subjonctif": both C1 and C2 match on identity; C1 is active, C2 orphaned,
	// so keyword ranks C1 (1), C2 (2). Semantic ranks C2 (1), C3 (2).
	//   C2 = 1/62 + 1/61, C1 = 1/61, C3 = 1/62.
	if body.Components.Keyword.TotalMatches != 2 || len(body.Results) != 3 {
		t.Fatalf("body = %+v", body)
	}
	want := []struct {
		id         int64
		score      float64
		kRank, sRk int
	}{{f.ids["C2"], 1.0/62 + 1.0/61, 2, 1}, {f.ids["C1"], 1.0 / 61, 1, 0}, {f.ids["C3"], 1.0 / 62, 0, 2}}
	for i, w := range want {
		got := body.Results[i]
		kr, sr := 0, 0
		if got.Keyword != nil {
			kr = got.Keyword.Rank
		}
		if got.Semantic != nil {
			sr = got.Semantic.Rank
		}
		if got.Concept.ID != w.id || math.Abs(got.FusedScore-w.score) > 1e-15 || kr != w.kRank || sr != w.sRk {
			t.Fatalf("result %d = %+v, want %+v", i, got, w)
		}
	}
	var prefixed json.RawMessage
	libraryGet(t, api.URL+"/api/knowledge-library/hybrid-search?q=subjonctif&limit=5&depth=5", 200, &prefixed)
	var again json.RawMessage
	libraryGet(t, root.URL+"/knowledge-library/hybrid-search?q=subjonctif&limit=5&depth=5", 200, &again)
	if string(prefixed) != string(again) {
		t.Fatal("/api and root differ")
	}
	// Orphaned filter: applied to both components; C1 (active) is excluded everywhere.
	libraryGet(t, root.URL+"/knowledge-library/hybrid-search?q=subjonctif&state=orphaned&limit=5&depth=5", 200, &body)
	for _, r := range body.Results {
		if r.Concept.ID == f.ids["C1"] {
			t.Fatal("active C1 leaked through the orphaned filter")
		}
	}
	// Semantic failure: no keyword-only page.
	sem.err = application.ErrEmbeddingProviderUnavailable
	libraryGet(t, root.URL+"/knowledge-library/hybrid-search?q=subjonctif", 502, nil)
	// Read-only: Concepts are unchanged by every search above.
	if !reflect.DeepEqual(before, list()) {
		t.Fatal("hybrid search changed concept state")
	}
}
