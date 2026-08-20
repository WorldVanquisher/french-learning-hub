package application

import (
	"errors"
	"testing"
)

func TestConceptRetrieverRegistry_DefaultExplicitAndUnknown(t *testing.T) {
	exact := NewExactSignatureConceptRetriever()
	weighted := NewWeightedLexicalConceptRetriever()
	registry := NewConceptRetrieverRegistry(exact, weighted)

	for _, tc := range []struct {
		name string
		want ConceptRetriever
	}{
		{name: "", want: exact},
		{name: ExactSignatureRetrieverV1Name, want: exact},
		{name: WeightedLexicalRetrieverV1Name, want: weighted},
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
