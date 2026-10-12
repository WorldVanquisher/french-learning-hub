package application_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// FLH-054: free-text semantic queries are sent as a versioned envelope; Unit
// queries and Concept documents keep concept_embedding_text_v1. The golden
// file is shared with the local E5 service's contract tests
// (tools/embedding/e5), so a rendering change on either side fails a test.

type goldenInputs struct {
	Convention string `json:"convention"`
	Accepted   []struct {
		Name        string `json:"name"`
		GoQueryText string `json:"go_query_text"`
		GoConcept   *struct {
			ID                int64             `json:"id"`
			Target            string            `json:"target"`
			PedagogicalIntent string            `json:"pedagogical_intent"`
			Scope             string            `json:"scope"`
			IdentityFeatures  map[string]string `json:"identity_features"`
		} `json:"go_concept"`
		GoUnit *struct {
			Kind              string `json:"kind"`
			Canonical         string `json:"canonical"`
			Statement         string `json:"statement"`
			Example           string `json:"example"`
			CandidateTarget   string `json:"candidate_target"`
			PedagogicalIntent string `json:"pedagogical_intent"`
		} `json:"go_unit"`
		Input string `json:"input"`
		Role  string `json:"role"`
	} `json:"accepted"`
}

func loadGolden(t *testing.T) goldenInputs {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "..", "tools", "embedding", "e5", "tests", "golden_inputs.json"))
	if err != nil {
		t.Fatal(err)
	}
	var g goldenInputs
	if err := json.Unmarshal(raw, &g); err != nil {
		t.Fatal(err)
	}
	if g.Convention != "flh_e5_role_prefix_v1" || len(g.Accepted) == 0 {
		t.Fatalf("golden file: %+v", g)
	}
	return g
}

// recordingProvider records every batch and delegates to the fake provider.
type recordingProvider struct {
	mu      sync.Mutex
	inner   application.EmbeddingProvider
	batches [][]string
}

func (r *recordingProvider) Name() string { return r.inner.Name() }
func (r *recordingProvider) Embed(ctx context.Context, texts []string) ([][]float64, error) {
	r.mu.Lock()
	r.batches = append(r.batches, append([]string(nil), texts...))
	r.mu.Unlock()
	return r.inner.Embed(ctx, texts)
}

func TestConceptSearchQueryEnvelope_MatchesGoldenWireBytes(t *testing.T) {
	g := loadGolden(t)
	seen := 0
	for _, c := range g.Accepted {
		if c.GoQueryText == "" {
			continue
		}
		seen++
		got, err := application.ConceptSearchQueryEmbeddingText(c.GoQueryText)
		if err != nil || got != c.Input {
			t.Fatalf("%s: got %q (%v), golden %q", c.Name, got, err, c.Input)
		}
		// The envelope holds exactly three keys and the original text.
		dec := json.NewDecoder(strings.NewReader(got))
		dec.DisallowUnknownFields()
		var env struct{ Representation, Type, Text string }
		if err := dec.Decode(&env); err != nil {
			t.Fatal(err)
		}
		var keys map[string]json.RawMessage
		_ = json.Unmarshal([]byte(got), &keys)
		if len(keys) != 3 || env.Representation != application.ConceptSearchQueryRepresentationV2 || env.Type != "query" || env.Text != c.GoQueryText {
			t.Fatalf("%s: envelope %+v keys %d", c.Name, env, len(keys))
		}
	}
	if seen != 3 {
		t.Fatalf("expected 3 search golden cases, saw %d", seen)
	}
	if _, err := application.ConceptSearchQueryEmbeddingText(""); !errors.Is(err, application.ErrKnowledgeLibraryQuery) {
		t.Fatalf("empty query: %v", err)
	}
}

// Unit-query and Concept-document representations are unchanged.
func TestConceptEmbeddingRepresentations_UnchangedAgainstGolden(t *testing.T) {
	g := loadGolden(t)
	var docGolden, unitGolden string
	var concept domain.KnowledgeConcept
	var query application.ConceptRetrievalQuery
	for _, c := range g.Accepted {
		switch {
		case c.GoConcept != nil:
			docGolden = c.Input
			concept = domain.KnowledgeConcept{ID: c.GoConcept.ID, IdentitySchemaVersion: "fr_l2_concept_identity_v1", Target: c.GoConcept.Target,
				PedagogicalIntent: c.GoConcept.PedagogicalIntent, Scope: c.GoConcept.Scope, IdentityFeatures: c.GoConcept.IdentityFeatures}
		case c.GoUnit != nil:
			unitGolden = c.Input
			ex := c.GoUnit.Example
			query = application.ConceptRetrievalQuery{UnitID: 1, Kind: domain.KnowledgeKind(c.GoUnit.Kind), Canonical: c.GoUnit.Canonical,
				Statement: c.GoUnit.Statement, Example: &ex,
				CandidateIdentity: domain.ConceptIdentity{Target: c.GoUnit.CandidateTarget, PedagogicalIntent: c.GoUnit.PedagogicalIntent}}
		}
	}
	doc, err := application.BuildSemanticIndexDocument(concept)
	if err != nil || doc.Text != docGolden {
		t.Fatalf("index document %q (%v), golden %q", doc.Text, err, docGolden)
	}
	rec := &recordingProvider{inner: newFakeProvider(testDims)}
	_, err = application.NewEmbeddingConceptRetriever(rec).Retrieve(context.Background(), query, []application.ConceptRetrievalDocument{{
		ConceptID: concept.ID, Target: concept.Target, PedagogicalIntent: concept.PedagogicalIntent, Scope: concept.Scope, IdentityFeatures: concept.IdentityFeatures,
	}}, 5)
	if err != nil {
		t.Fatal(err)
	}
	if len(rec.batches) != 1 || len(rec.batches[0]) != 2 || rec.batches[0][0] != unitGolden || rec.batches[0][1] != docGolden {
		t.Fatalf("retriever batch %q", rec.batches)
	}
}

// Search sends exactly one enveloped input; a query that is itself a Concept
// document's JSON is still sent as a query, never as the document text.
func TestSemanticSearch_SendsVersionedQueryEnvelope(t *testing.T) {
	f := newSemanticFixture(t)
	index := &recordingProvider{inner: f.provider}
	mustRun(t, "build", application.NewSemanticIndexService(f.concepts, f.store, f.index, index, f.space, 1))
	// Indexing: singleton batches, every input a Concept document.
	if len(index.batches) != 5 {
		t.Fatalf("index batches %d, want 5 singletons", len(index.batches))
	}
	docs := map[string]bool{}
	for _, b := range index.batches {
		if len(b) != 1 || !strings.HasPrefix(b[0], `{"representation":"concept_embedding_text_v1","type":"concept",`) {
			t.Fatalf("index batch %q", b)
		}
		docs[b[0]] = true
	}

	c, _ := f.concepts.ListConcepts(context.Background(), nil)
	d, err := application.BuildSemanticIndexDocument(c[0])
	if err != nil {
		t.Fatal(err)
	}
	for _, text := range []string{"subjunctive", d.Text} {
		rec := &recordingProvider{inner: f.provider}
		search := application.NewSemanticSearchService(f.concepts, fixedSummarizer{}, f.store, f.index, rec, f.space)
		r, err := search.Search(context.Background(), application.LibrarySearchQuery{Text: text, Limit: 3})
		if err != nil {
			t.Fatal(err)
		}
		want, _ := application.ConceptSearchQueryEmbeddingText(text)
		if len(rec.batches) != 1 || len(rec.batches[0]) != 1 || rec.batches[0][0] != want {
			t.Fatalf("query %q: provider got %q, want [%q]", text, rec.batches, want)
		}
		if docs[rec.batches[0][0]] || r.Query != text || r.QueryRepresentation != application.ConceptSearchQueryRepresentationV2 {
			t.Fatalf("query %q: report %q/%q", text, r.Query, r.QueryRepresentation)
		}
		var env map[string]string
		dec := json.NewDecoder(bytes.NewReader([]byte(rec.batches[0][0])))
		if err := dec.Decode(&env); err != nil || env["type"] != "query" || env["text"] != text {
			t.Fatalf("query %q: envelope %v %v", text, env, err)
		}
	}
}
