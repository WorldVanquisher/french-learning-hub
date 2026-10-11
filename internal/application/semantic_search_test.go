package application_test

import (
	"context"
	"errors"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

func TestSemanticSearch_ReturnsCurrentConceptsBySimilarity(t *testing.T) {
	f := newSemanticFixture(t)
	b := mustRun(t, "build", f.service(10))
	r, err := f.search().Search(context.Background(), application.LibrarySearchQuery{Text: "subjunctive", Limit: 3})
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Results) != 3 || r.Collection != b.Collection || r.Publication.PublishedRunID != b.RunID || r.Publication.LastRunOutcome != "published" {
		t.Fatalf("report = %+v", r)
	}
	for i := 1; i < len(r.Results); i++ {
		if r.Results[i].Similarity > r.Results[i-1].Similarity {
			t.Fatalf("results not ordered by similarity: %+v", r.Results)
		}
	}
	got := map[int64]bool{}
	for _, res := range r.Results {
		got[res.Concept.ID] = true
	}
	for _, id := range []int64{1, 3, 5} {
		if !got[id] {
			t.Fatalf("expected concept %d among %v", id, got)
		}
	}
}

func TestSemanticSearch_StateFilterDoesNotFillShortages(t *testing.T) {
	f := newSemanticFixture(t)
	mustRun(t, "build", f.service(10))
	orphaned := domain.ConceptOrphaned
	r, err := f.search().Search(context.Background(), application.LibrarySearchQuery{Text: "subjunctive", State: &orphaned, Limit: 5})
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Results) != 1 || r.Results[0].Concept.ID != 3 || r.FilteredByState == 0 {
		t.Fatalf("report = %+v", r)
	}
	retired := domain.ConceptRetired
	r, err = f.search().Search(context.Background(), application.LibrarySearchQuery{Text: "subjunctive", State: &retired, Limit: 5})
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Results) != 0 {
		t.Fatalf("unrelated retired concept must not fill the page: %+v", r.Results)
	}
}

func TestSemanticSearch_RevalidatesHitsAgainstSQLite(t *testing.T) {
	f := newSemanticFixture(t)
	b := mustRun(t, "build", f.service(10))
	f.concepts.set(concept(5, "although: bien que takes the subjunctive", domain.ConceptActive))
	f.concepts.remove(1)
	foreign := f.space
	foreign.ModelID = "someone-else/model"
	vec, _ := application.ValidateEmbedding(bagOfWords("subjunctive", testDims), testDims)
	f.index.injectPoint(b.Collection, 99, "hash", foreign, vec)

	r, err := f.search().Search(context.Background(), application.LibrarySearchQuery{Text: "subjunctive", Limit: 5})
	if err != nil {
		t.Fatal(err)
	}
	if r.SkippedStale != 1 || r.SkippedMissing != 1 || r.SkippedIncompatible != 1 {
		t.Fatalf("skips = %+v", r)
	}
	if len(r.Results) != 1 || r.Results[0].Concept.ID != 3 {
		t.Fatalf("results = %+v", r.Results)
	}
	// The run record still says "published": search reports it as history,
	// while status reports the live inventory as unhealthy.
	if r.Publication.LastRunOutcome != "published" || f.status().VerifiedHealthy {
		t.Fatal("run history and verified health must differ here")
	}
}

func TestSemanticSearch_RetriesOnceWhenThePublicationIsReplaced(t *testing.T) {
	f := newSemanticFixture(t)
	first := mustRun(t, "build", f.service(10)).Collection
	var second string
	f.index.onQuery = func(collection string) {
		if collection == first {
			// A rebuild publishes a new collection and deletes the old one
			// between search's pointer read and its query.
			second = mustRun(t, "rebuild", f.service(10)).Collection
		}
	}
	r, err := f.search().Search(context.Background(), application.LibrarySearchQuery{Text: "subjunctive", Limit: 5})
	if err != nil {
		t.Fatal(err)
	}
	if second == "" || r.Collection != second || len(r.Results) != 3 {
		t.Fatalf("report = %+v (second %q)", r, second)
	}
}

func TestSemanticSearch_ExplicitFailures(t *testing.T) {
	f := newSemanticFixture(t)
	q := application.LibrarySearchQuery{Text: "subjunctive", Limit: 5}
	if _, err := f.search().Search(context.Background(), q); !errors.Is(err, application.ErrSemanticIndexNotBuilt) {
		t.Fatalf("unbuilt: %v", err)
	}
	mustRun(t, "build", f.service(2))
	f.index.unavailable = true
	if _, err := f.search().Search(context.Background(), q); !errors.Is(err, application.ErrVectorIndexUnavailable) {
		t.Fatalf("vector store down: %v", err)
	}
	f.index.unavailable = false
	f.provider.failCall = f.provider.calls + 1
	f.provider.failError = application.ErrEmbeddingProviderTimeout
	if _, err := f.search().Search(context.Background(), q); !errors.Is(err, application.ErrEmbeddingProviderTimeout) {
		t.Fatalf("provider timeout: %v", err)
	}
	if _, err := f.search().Search(context.Background(), application.LibrarySearchQuery{Text: "", Limit: 5}); !errors.Is(err, application.ErrKnowledgeLibraryQuery) {
		t.Fatalf("empty query: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := f.search().Search(ctx, q); err == nil {
		t.Fatal("canceled search must fail")
	}
}
