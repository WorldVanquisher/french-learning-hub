package application

import (
	"errors"
	"testing"
)

func TestConceptRetrieverRegistry_DefaultExplicitAndUnknown(t *testing.T) {
	exact := NewExactSignatureConceptRetriever()
	weighted := NewWeightedLexicalConceptRetriever()
	bm25 := NewBM25ConceptRetriever()
	registry := NewConceptRetrieverRegistry(exact, weighted, bm25)

	for _, tc := range []struct {
		name string
		want ConceptRetriever
	}{
		{name: "", want: exact},
		{name: ExactSignatureRetrieverV1Name, want: exact},
		{name: WeightedLexicalRetrieverV1Name, want: weighted},
		{name: BM25RetrieverV1Name, want: bm25},
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
