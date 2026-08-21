package application

import (
	"errors"
	"testing"
)

func TestConceptRetrieverRegistry_DefaultExplicitAndUnknown(t *testing.T) {
	exact := NewExactSignatureConceptRetriever()
	weighted := NewWeightedLexicalConceptRetriever()
	bm25 := NewBM25ConceptRetriever()
	embedding := NewEmbeddingConceptRetriever(&frozenEmbeddingProvider{name: "frozen:test"})
	registry := NewConceptRetrieverRegistry(exact, weighted, bm25, embedding)

	for _, tc := range []struct {
		name string
		want ConceptRetriever
	}{
		{name: "", want: exact},
		{name: ExactSignatureRetrieverV1Name, want: exact},
		{name: WeightedLexicalRetrieverV1Name, want: weighted},
		{name: BM25RetrieverV1Name, want: bm25},
		{name: EmbeddingRetrieverV1Name, want: embedding},
	} {
		got, err := registry.Select(tc.name)
		if err != nil || got != tc.want {
			t.Fatalf("Select(%q) = %v, %v; want %v", tc.name, got, err, tc.want)
		}
	}
	if _, err := registry.Select("unknown"); !errors.Is(err, ErrUnknownConceptRetriever) {
		t.Fatalf("unknown error = %v", err)
	}
}

func TestConceptRetrieverRegistry_EmbeddingUnavailableWhenNotRegistered(t *testing.T) {
	registry := NewConceptRetrieverRegistry(
		NewExactSignatureConceptRetriever(),
		NewWeightedLexicalConceptRetriever(),
		NewBM25ConceptRetriever(),
	)
	if _, err := registry.Select(EmbeddingRetrieverV1Name); !errors.Is(err, ErrUnknownConceptRetriever) {
		t.Fatalf("embedding selection error = %v", err)
	}
	defaultRetriever, err := registry.Select("")
	if err != nil || defaultRetriever.Name() != ExactSignatureRetrieverV1Name {
		t.Fatalf("default retriever = %v, err = %v", defaultRetriever, err)
	}
}
