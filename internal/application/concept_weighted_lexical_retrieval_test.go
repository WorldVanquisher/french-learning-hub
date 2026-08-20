package application

import (
	"context"
	"encoding/json"
	"math"
	"reflect"
	"testing"

	"french-learning-app/internal/domain"
)

func TestNormalizeConceptLexicalTokens_V1Policy(t *testing.T) {
	want := []string{"francais", "article", "apres", "parler", "42"}
	got := NormalizeConceptLexicalTokens("FRANÇAIS, d'article—après/parler! à y 42")
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("tokens = %v, want %v", got, want)
	}
	decomposed := "franc\u0327ais"
	if got := NormalizeConceptLexicalTokens(decomposed); !reflect.DeepEqual(got, []string{"francais"}) {
		t.Fatalf("decomposed tokens = %v", got)
	}
	if got := NormalizeConceptLexicalTokens("' — ! a à y"); len(got) != 0 || got == nil {
		t.Fatalf("empty/one-rune tokens = %#v", got)
	}
	if got := NormalizeConceptLexicalTokens(""); len(got) != 0 || got == nil {
		t.Fatalf("empty input tokens = %#v", got)
	}
	if again := NormalizeConceptLexicalTokens("FRANÇAIS, d'article—après/parler! à y 42"); !reflect.DeepEqual(again, want) {
		t.Fatalf("second normalization = %v, want %v", again, want)
	}
}

func TestWeightedLexicalVectors_DeduplicateWithinFieldsAndAccumulateAcrossFields(t *testing.T) {
	query := ConceptRetrievalQuery{
		Canonical: "Article article",
		Statement: "ARTICLE défini défini",
		CandidateIdentity: domain.ConceptIdentity{
			PedagogicalIntent: "Usage usage",
			Scope:             "Langue langue",
			IdentityFeatures:  map[string]string{"context type": "Après parler", "register": "Usage"},
		},
	}
	got := weightedLexicalQueryVector(query)
	want := lexicalVector{
		"article": 6, "defini": 2, "usage": 2, "langue": 1,
		"context": 1, "type": 1, "register": 1, "apres": 1, "parler": 1,
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("query vector = %#v, want %#v", got, want)
	}

	documentA := ConceptRetrievalDocument{Target: "Article article", PedagogicalIntent: "usage", IdentityFeatures: map[string]string{"z key": "last value", "a key": "first value"}}
	documentB := ConceptRetrievalDocument{Target: "Article article", PedagogicalIntent: "usage", IdentityFeatures: map[string]string{"a key": "first value", "z key": "last value"}}
	if a, b := weightedLexicalDocumentVector(documentA), weightedLexicalDocumentVector(documentB); !reflect.DeepEqual(a, b) {
		t.Fatalf("feature map order changed vector: %#v != %#v", a, b)
	}
	if got := weightedLexicalDocumentVector(documentA)["article"]; got != lexicalDocumentTargetWeight {
		t.Fatalf("repeated document target token weight = %v", got)
	}
}

func TestLexicalCosineSimilarity_BoundsEmptyPartialAndIdentity(t *testing.T) {
	if got := lexicalCosineSimilarity(nil, lexicalVector{"x": 1}); got != 0 {
		t.Fatalf("empty score = %v", got)
	}
	if got := lexicalCosineSimilarity(lexicalVector{"x": 1}, nil); got != 0 {
		t.Fatalf("empty document score = %v", got)
	}
	if got := lexicalCosineSimilarity(lexicalVector{"x": 1}, lexicalVector{"y": 1}); got != 0 {
		t.Fatalf("disjoint score = %v", got)
	}
	if got := lexicalCosineSimilarity(lexicalVector{"x": 2, "y": 1}, lexicalVector{"x": 2, "y": 1}); math.Abs(got-1) > 1e-12 {
		t.Fatalf("identity score = %v", got)
	}
	partial := lexicalCosineSimilarity(lexicalVector{"x": 1, "y": 1}, lexicalVector{"x": 1, "z": 1})
	if partial <= 0 || partial >= 1 || math.IsNaN(partial) || math.IsInf(partial, 0) {
		t.Fatalf("partial score = %v", partial)
	}
	if again := lexicalCosineSimilarity(lexicalVector{"y": 1, "x": 1}, lexicalVector{"z": 1, "x": 1}); again != partial {
		t.Fatalf("second score = %v, want %v", again, partial)
	}
}

func TestWeightedLexicalConceptRetriever_PositiveOnlyRankingLimitTieBreakAndEvidence(t *testing.T) {
	retriever := NewWeightedLexicalConceptRetriever()
	query := ConceptRetrievalQuery{Canonical: "article langue", CandidateIdentity: domain.ConceptIdentity{}}
	documents := []ConceptRetrievalDocument{
		{ConceptID: 7, Target: "langue"},
		{ConceptID: 4, Target: "unrelated"},
		{ConceptID: 3, Target: "article"},
		{ConceptID: 9, Target: "article langue"},
		{ConceptID: 2, Target: "article"},
	}
	got, err := retriever.Retrieve(context.Background(), query, documents, 4)
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	if retriever.Name() != WeightedLexicalRetrieverV1Name {
		t.Fatalf("Name = %q", retriever.Name())
	}
	wantIDs := []int64{9, 2, 3, 7}
	if len(got) != len(wantIDs) {
		t.Fatalf("candidates = %+v", got)
	}
	for index, candidate := range got {
		if candidate.ConceptID != wantIDs[index] || candidate.Rank != index+1 || candidate.Score <= 0 || candidate.Score > 1 || math.IsNaN(candidate.Score) || math.IsInf(candidate.Score, 0) {
			t.Fatalf("candidate[%d] = %+v", index, candidate)
		}
		var evidence struct {
			Reason        string   `json:"reason"`
			Normalization string   `json:"normalization"`
			MatchedTokens []string `json:"matched_tokens"`
		}
		if err := json.Unmarshal([]byte(candidate.Evidence), &evidence); err != nil {
			t.Fatalf("evidence[%d] is not JSON: %v", index, err)
		}
		if evidence.Reason != "weighted_lexical_cosine" || evidence.Normalization != ConceptLexicalNormalizationV1 {
			t.Fatalf("evidence[%d] = %+v", index, evidence)
		}
		for i := 1; i < len(evidence.MatchedTokens); i++ {
			if evidence.MatchedTokens[i-1] >= evidence.MatchedTokens[i] {
				t.Fatalf("matched tokens are not unique and sorted: %v", evidence.MatchedTokens)
			}
		}
	}
	limited, err := retriever.Retrieve(context.Background(), query, documents, 1)
	if err != nil || len(limited) != 1 || limited[0].ConceptID != 9 {
		t.Fatalf("limited candidates = %+v, err = %v", limited, err)
	}
	empty, err := retriever.Retrieve(context.Background(), query, documents, 0)
	if err != nil || len(empty) != 0 || empty == nil {
		t.Fatalf("zero-limit candidates = %#v, err = %v", empty, err)
	}
	again, err := retriever.Retrieve(context.Background(), query, documents, 4)
	if err != nil || !reflect.DeepEqual(again, got) {
		t.Fatalf("second retrieval = %+v, err = %v; want %+v", again, err, got)
	}
}

func TestWeightedLexicalConceptRetriever_DoesNotBoostExactSignature(t *testing.T) {
	identity := retrievalTestIdentity("signature-only target")
	query := ConceptRetrievalQuery{Canonical: "article langue", CandidateIdentity: identity}
	documents := []ConceptRetrievalDocument{
		{ConceptID: 1, Target: "unrelated words", Signature: identity.Signature()},
		{ConceptID: 2, Target: "article", Signature: retrievalTestIdentity("different").Signature()},
	}
	got, err := NewWeightedLexicalConceptRetriever().Retrieve(context.Background(), query, documents, 5)
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	if len(got) != 1 || got[0].ConceptID != 2 {
		t.Fatalf("candidates = %+v", got)
	}
}

func TestWeightedLexicalConceptRetriever_ControlledFrenchRegression(t *testing.T) {
	query := ConceptRetrievalQuery{
		Canonical:         "nom de langue — omission d'article après parler",
		Statement:         "On n'emploie pas d'article défini devant un nom de langue après un verbe comme parler.",
		CandidateIdentity: domain.ConceptIdentity{Target: "nom de langue — omission d'article après parler", PedagogicalIntent: "grammar"},
	}
	targetIdentity := domain.ConceptIdentity{Target: "parler + nom de langue — pas d'article", PedagogicalIntent: "usage"}
	documents := []ConceptRetrievalDocument{
		{ConceptID: 11, Target: targetIdentity.Target, PedagogicalIntent: targetIdentity.PedagogicalIntent, Signature: targetIdentity.Signature()},
		{ConceptID: 12, Target: "article défini devant les noms de langue", PedagogicalIntent: "grammar"},
		{ConceptID: 13, Target: "parler suivi d'un infinitif", PedagogicalIntent: "grammar"},
		{ConceptID: 14, Target: "accord de l'adjectif qualificatif", PedagogicalIntent: "grammar"},
		{ConceptID: 15, Target: "formation du futur simple", PedagogicalIntent: "grammar"},
	}
	exact, err := NewExactSignatureConceptRetriever().Retrieve(context.Background(), query, documents, 5)
	if err != nil || len(exact) != 0 {
		t.Fatalf("exact candidates = %+v, err = %v", exact, err)
	}
	weighted, err := NewWeightedLexicalConceptRetriever().Retrieve(context.Background(), query, documents, 5)
	if err != nil {
		t.Fatalf("weighted Retrieve: %v", err)
	}
	if len(weighted) == 0 || weighted[0].ConceptID != 11 || weighted[0].Rank != 1 {
		t.Fatalf("weighted candidates = %+v", weighted)
	}
}
