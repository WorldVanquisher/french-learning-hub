package http_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	transporthttp "french-learning-app/internal/transport/http"
)

type fakeSemantic struct {
	err   error
	query application.LibrarySearchQuery
}

func (f *fakeSemantic) Search(_ context.Context, q application.LibrarySearchQuery) (*application.SemanticSearchReport, error) {
	f.query = q
	if f.err != nil {
		return nil, f.err
	}
	return &application.SemanticSearchReport{
		Query: q.Text, State: q.State, Limit: q.Limit, IndexComplete: false, Considered: 4, SkippedStale: 1,
		Index: application.SemanticIndexCollection{Collection: "c", Representation: "concept_embedding_text_v1", ModelID: "m",
			Dimensions: 8, State: "partial", UpdatedAt: time.Date(2026, 10, 10, 0, 0, 0, 0, time.UTC), LastError: "embedding provider unavailable"},
		Results: []application.SemanticSearchResult{{
			Concept:    domain.KnowledgeConcept{ID: 3, Target: "subjunctive", PedagogicalIntent: "grammar", IdentityFeatures: map[string]string{}, State: domain.ConceptActive},
			Similarity: 0.42, CurrentMemberCount: 2, SupportingUnitCount: 1,
		}},
	}, nil
}

func semanticServer(t *testing.T, svc transporthttp.SemanticSearchService) (*httptest.Server, *httptest.Server) {
	t.Helper()
	var opts []transporthttp.HandlerOption
	if svc != nil {
		opts = append(opts, transporthttp.WithSemanticSearch(svc))
	}
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

func semanticGet(t *testing.T, url string) (int, map[string]any) {
	t.Helper()
	resp, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var body map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	return resp.StatusCode, body
}

func TestSemanticSearchHTTP_ResponseShapeAndAPIPrefix(t *testing.T) {
	svc := &fakeSemantic{}
	root, api := semanticServer(t, svc)
	for _, base := range []string{root.URL, api.URL + "/api"} {
		status, body := semanticGet(t, base+"/knowledge-library/semantic-search?q=subjonctif&state=active&limit=5")
		if status != 200 || body["schema_version"] != "knowledge_library_semantic_search_v1" {
			t.Fatalf("%s: %d %v", base, status, body)
		}
		idx := body["index"].(map[string]any)
		if idx["complete"] != false || idx["state"] != "partial" || idx["model_id"] != "m" || idx["last_error"] != "embedding provider unavailable" {
			t.Fatalf("index = %v", idx)
		}
		res := body["results"].([]any)[0].(map[string]any)
		if res["similarity"] != 0.42 || res["concept"].(map[string]any)["id"] != float64(3) {
			t.Fatalf("result = %v", res)
		}
		if !strings.Contains(body["score_note"].(string), "not a probability") || body["state"] != "active" {
			t.Fatalf("body = %v", body)
		}
	}
	if svc.query.Text != "subjonctif" || svc.query.Limit != 5 || *svc.query.State != domain.ConceptActive {
		t.Fatalf("query = %+v", svc.query)
	}
	for _, bad := range []string{"?q=x&limit=0", "?q=x&limit=nope", "?q=x&state=gone"} {
		if status, _ := semanticGet(t, root.URL+"/knowledge-library/semantic-search"+bad); status != 400 {
			t.Fatalf("%s: status %d", bad, status)
		}
	}
	resp, err := http.Post(root.URL+"/knowledge-library/semantic-search?q=x", "application/json", nil)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusMethodNotAllowed {
		t.Fatalf("POST status %d", resp.StatusCode)
	}
}

func TestSemanticSearchHTTP_ExplicitFailuresWithoutKeywordFallback(t *testing.T) {
	root, _ := semanticServer(t, nil)
	if status, body := semanticGet(t, root.URL+"/knowledge-library/semantic-search?q=x"); status != 503 || body["error"] != "semantic search is not configured" {
		t.Fatalf("disabled: %d %v", status, body)
	}
	cases := map[error]int{
		application.ErrSemanticIndexNotBuilt:                                       409,
		application.ErrSemanticIndexIncompatible:                                   409,
		fmt.Errorf("%w: x", application.ErrEmbeddingProviderTimeout):               504,
		fmt.Errorf("%w: secret body", application.ErrEmbeddingProviderUnavailable): 502,
		application.ErrVectorIndexTimeout:                                          504,
		fmt.Errorf("%w: secret", application.ErrVectorIndexUnavailable):            502,
		fmt.Errorf("%w: empty", application.ErrKnowledgeLibraryQuery):              400,
		errors.New("boom"): 500,
	}
	for err, want := range cases {
		root, _ := semanticServer(t, &fakeSemantic{err: err})
		status, body := semanticGet(t, root.URL+"/knowledge-library/semantic-search?q=x")
		if status != want || strings.Contains(fmt.Sprint(body), "secret") || body["results"] != nil {
			t.Fatalf("%v: %d %v", err, status, body)
		}
	}
}
