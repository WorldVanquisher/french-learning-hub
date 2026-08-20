package application

import (
	"context"
	"encoding/json"
	"math"
	"reflect"
	"testing"

	"french-learning-app/internal/domain"
)

func TestBM25ConceptRetriever_NameParametersNormalizationAndEmptyInputs(t *testing.T) {
	retriever := NewBM25ConceptRetriever()
	if retriever.Name() != BM25RetrieverV1Name {
		t.Fatalf("Name = %q", retriever.Name())
	}
	if BM25K1V1 != 1.2 || BM25BV1 != 0.75 {
		t.Fatalf("parameters = k1:%v b:%v", BM25K1V1, BM25BV1)
	}

	accented, err := retriever.Retrieve(
		context.Background(),
		ConceptRetrievalQuery{Canonical: "FRANÇAIS"},
		[]ConceptRetrievalDocument{{ConceptID: 1, Target: "francais"}},
		5,
	)
	if err != nil || len(accented) != 1 || accented[0].ConceptID != 1 {
		t.Fatalf("accent-normalized candidates = %+v, err = %v", accented, err)
	}

	for _, tc := range []struct {
		name     string
		query    ConceptRetrievalQuery
		concepts []ConceptRetrievalDocument
		limit    int
	}{
		{name: "zero limit", query: ConceptRetrievalQuery{Canonical: "article"}, concepts: []ConceptRetrievalDocument{{ConceptID: 1, Target: "article"}}, limit: 0},
		{name: "empty query", concepts: []ConceptRetrievalDocument{{ConceptID: 1, Target: "article"}}, limit: 5},
		{name: "one-rune query", query: ConceptRetrievalQuery{Canonical: "à y"}, concepts: []ConceptRetrievalDocument{{ConceptID: 1, Target: "article"}}, limit: 5},
		{name: "empty corpus", query: ConceptRetrievalQuery{Canonical: "article"}, limit: 5},
		{name: "empty document corpus", query: ConceptRetrievalQuery{Canonical: "article"}, concepts: []ConceptRetrievalDocument{{ConceptID: 1, Target: "à y"}}, limit: 5},
		{name: "no overlap", query: ConceptRetrievalQuery{Canonical: "article"}, concepts: []ConceptRetrievalDocument{{ConceptID: 1, Target: "verbe"}}, limit: 5},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, err := retriever.Retrieve(context.Background(), tc.query, tc.concepts, tc.limit)
			if err != nil || got == nil || len(got) != 0 {
				t.Fatalf("candidates = %#v, err = %v", got, err)
			}
		})
	}
}

func TestBM25CorpusStatistics_PreserveTermFrequencyDocumentFrequencyAndAverageLength(t *testing.T) {
	statistics := buildBM25CorpusStatistics([]ConceptRetrievalDocument{
		{ConceptID: 1, Target: "article article rare"},
		{ConceptID: 2, Target: "article usage", PedagogicalIntent: "usage"},
		{ConceptID: 3, Target: "à y"},
	})
	if len(statistics.documents) != 3 {
		t.Fatalf("document count = %d", len(statistics.documents))
	}
	if got := statistics.documents[0].terms["article"]; got != 8 {
		t.Fatalf("repeated target term frequency = %v, want 8", got)
	}
	if got := statistics.documents[0].terms["rare"]; got != 4 {
		t.Fatalf("rare target term frequency = %v, want 4", got)
	}
	if got := statistics.documents[0].length; got != 12 {
		t.Fatalf("first document length = %v, want 12", got)
	}
	if got := statistics.documents[1].terms["usage"]; got != 5 {
		t.Fatalf("cross-field usage term frequency = %v, want 5", got)
	}
	if got := statistics.documents[1].length; got != 9 {
		t.Fatalf("second document length = %v, want 9", got)
	}
	if got := statistics.documents[2].length; got != 0 {
		t.Fatalf("empty normalized document length = %v", got)
	}
	wantFrequency := map[string]int{"article": 2, "rare": 1, "usage": 1}
	if !reflect.DeepEqual(statistics.documentFrequency, wantFrequency) {
		t.Fatalf("document frequency = %#v, want %#v", statistics.documentFrequency, wantFrequency)
	}
	if got, want := statistics.averageDocumentLength, 7.0; got != want {
		t.Fatalf("average document length = %v, want %v", got, want)
	}
}

func TestBM25InverseDocumentFrequency_RareTokenHasGreaterWeight(t *testing.T) {
	rare := bm25InverseDocumentFrequency(5, 1)
	common := bm25InverseDocumentFrequency(5, 5)
	if rare <= common || common <= 0 {
		t.Fatalf("rare idf = %v, common idf = %v", rare, common)
	}
	wantRare := math.Log(1 + (4.0+0.5)/(1.0+0.5))
	if math.Abs(rare-wantRare) > 1e-12 {
		t.Fatalf("rare idf = %v, want %v", rare, wantRare)
	}
	for _, invalid := range [][2]int{{0, 0}, {5, 0}, {5, 6}} {
		if got := bm25InverseDocumentFrequency(invalid[0], invalid[1]); got != 0 {
			t.Fatalf("idf(%d, %d) = %v", invalid[0], invalid[1], got)
		}
	}
}

func TestBM25ConceptRetriever_TermFrequencySaturates(t *testing.T) {
	retriever := NewBM25ConceptRetriever()
	query := ConceptRetrievalQuery{Canonical: "pivot"}
	documents := []ConceptRetrievalDocument{
		{ConceptID: 1, Target: "pivot filler filler filler"},
		{ConceptID: 2, Target: "pivot pivot filler filler"},
		{ConceptID: 3, Target: "filler filler filler filler"},
	}
	got, err := retriever.Retrieve(context.Background(), query, documents, 5)
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	if len(got) != 2 || got[0].ConceptID != 2 || got[1].ConceptID != 1 {
		t.Fatalf("candidates = %+v", got)
	}
	if got[0].Score <= got[1].Score || got[0].Score >= 2*got[1].Score {
		t.Fatalf("repeated score = %v, single score = %v; want a saturated increase", got[0].Score, got[1].Score)
	}
}

func TestBM25DocumentLengthNormalization_PenalizesLongerEqualTFDocument(t *testing.T) {
	retriever := NewBM25ConceptRetriever()
	query := ConceptRetrievalQuery{Canonical: "pivot"}
	documents := []ConceptRetrievalDocument{
		{ConceptID: 1, Target: "pivot"},
		{ConceptID: 2, Target: "pivot extra extra extra extra extra"},
	}
	got, err := retriever.Retrieve(context.Background(), query, documents, 5)
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	if len(got) != 2 || got[0].ConceptID != 1 || got[0].Score <= got[1].Score {
		t.Fatalf("length-normalized candidates = %+v", got)
	}

	idf := bm25InverseDocumentFrequency(2, 2)
	shortWithoutNormalization := bm25TermContribution(4, idf, 4, 4, 14, BM25K1V1, 0)
	longWithoutNormalization := bm25TermContribution(4, idf, 4, 24, 14, BM25K1V1, 0)
	if shortWithoutNormalization != longWithoutNormalization {
		t.Fatalf("b=0 scores differ: short=%v long=%v", shortWithoutNormalization, longWithoutNormalization)
	}
	shortWithNormalization := bm25TermContribution(4, idf, 4, 4, 14, BM25K1V1, BM25BV1)
	longWithNormalization := bm25TermContribution(4, idf, 4, 24, 14, BM25K1V1, BM25BV1)
	if shortWithNormalization <= longWithNormalization {
		t.Fatalf("b=%v scores: short=%v long=%v", BM25BV1, shortWithNormalization, longWithNormalization)
	}
}

func TestBM25Representations_ApplyExplicitFieldWeightsWithoutTargetLeakage(t *testing.T) {
	query := ConceptRetrievalQuery{
		Canonical: "pivot pivot",
		Statement: "pivot",
		CandidateIdentity: domain.ConceptIdentity{
			Target:            "secret target",
			PedagogicalIntent: "pivot",
			Scope:             "pivot",
			IdentityFeatures:  map[string]string{"pivot key": "pivot value"},
		},
	}
	queryTerms := bm25QueryTerms(query)
	if got := queryTerms["pivot"]; got != 14 {
		t.Fatalf("query pivot weight = %v, want 14", got)
	}
	if queryTerms["secret"] != 0 || queryTerms["target"] != 0 {
		t.Fatalf("candidate identity target leaked into query terms: %#v", queryTerms)
	}

	documentTerms, _ := bm25DocumentTerms(ConceptRetrievalDocument{
		Target:            "pivot pivot",
		PedagogicalIntent: "pivot",
		Scope:             "pivot",
		IdentityFeatures:  map[string]string{"pivot key": "pivot value"},
	})
	if got := documentTerms["pivot"]; got != 12 {
		t.Fatalf("document pivot weight = %v, want 12", got)
	}

	got, err := NewBM25ConceptRetriever().Retrieve(context.Background(), ConceptRetrievalQuery{Canonical: "pivot"}, []ConceptRetrievalDocument{
		{ConceptID: 2, PedagogicalIntent: "pivot"},
		{ConceptID: 1, Target: "pivot"},
		{ConceptID: 3, Target: "unrelated"},
	}, 5)
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	if len(got) != 2 || got[0].ConceptID != 1 || got[0].Score <= got[1].Score {
		t.Fatalf("field-weighted candidates = %+v", got)
	}
}

func TestBM25ConceptRetriever_DeterministicRankingLimitAndStableEvidence(t *testing.T) {
	retriever := NewBM25ConceptRetriever()
	query := ConceptRetrievalQuery{Canonical: "zèbre article"}
	documents := []ConceptRetrievalDocument{
		{ConceptID: 7, Target: "article zebre"},
		{ConceptID: 9, Target: "unrelated"},
		{ConceptID: 2, Target: "article zèbre"},
	}
	got, err := retriever.Retrieve(context.Background(), query, documents, 2)
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	if len(got) != 2 || got[0].ConceptID != 2 || got[1].ConceptID != 7 {
		t.Fatalf("tie-broken candidates = %+v", got)
	}
	for index, candidate := range got {
		if candidate.Rank != index+1 || candidate.Score <= 0 || math.IsNaN(candidate.Score) || math.IsInf(candidate.Score, 0) {
			t.Fatalf("candidate[%d] = %+v", index, candidate)
		}
		var evidence bm25RetrievalEvidenceV1
		if err := json.Unmarshal([]byte(candidate.Evidence), &evidence); err != nil {
			t.Fatalf("evidence[%d] is not JSON: %v", index, err)
		}
		if evidence.Reason != "bm25" || evidence.Normalization != ConceptLexicalNormalizationV1 || evidence.Parameters.K1 != BM25K1V1 || evidence.Parameters.B != BM25BV1 || evidence.CorpusDocuments != 3 {
			t.Fatalf("evidence[%d] = %+v", index, evidence)
		}
		if !reflect.DeepEqual(evidence.MatchedTokens, []string{"article", "zebre"}) || len(evidence.TermContributions) != 2 {
			t.Fatalf("matched evidence[%d] = %+v", index, evidence)
		}
		for contributionIndex, contribution := range evidence.TermContributions {
			if contribution.Token != evidence.MatchedTokens[contributionIndex] || contribution.Contribution <= 0 || math.IsNaN(contribution.Contribution) || math.IsInf(contribution.Contribution, 0) {
				t.Fatalf("contribution[%d][%d] = %+v", index, contributionIndex, contribution)
			}
		}
	}
	again, err := retriever.Retrieve(context.Background(), query, documents, 2)
	if err != nil || !reflect.DeepEqual(again, got) {
		t.Fatalf("second retrieval = %+v, err = %v; want %+v", again, err, got)
	}
	limited, err := retriever.Retrieve(context.Background(), query, documents, 1)
	if err != nil || len(limited) != 1 || limited[0].ConceptID != 2 || limited[0].Rank != 1 {
		t.Fatalf("limited candidates = %+v, err = %v", limited, err)
	}
}

func TestBM25ConceptRetriever_ControlledFrenchCorpusRegression(t *testing.T) {
	query := ConceptRetrievalQuery{
		Canonical: "article parler",
		CandidateIdentity: domain.ConceptIdentity{
			Target:            "omission devant un nom de langue",
			PedagogicalIntent: "usage",
		},
	}
	documents := []ConceptRetrievalDocument{
		{ConceptID: 11, Target: "article parler", Signature: retrievalTestIdentity("parler sans article devant un nom de langue").Signature()},
		{ConceptID: 12, Target: "article article article article", Signature: retrievalTestIdentity("article défini").Signature()},
		{ConceptID: 13, Target: "article langue", Signature: retrievalTestIdentity("nom de langue").Signature()},
		{ConceptID: 14, Target: "article verbe", Signature: retrievalTestIdentity("temps du verbe").Signature()},
		{ConceptID: 15, Target: "article grammaire", Signature: retrievalTestIdentity("règle de grammaire").Signature()},
	}
	exact, err := NewExactSignatureConceptRetriever().Retrieve(context.Background(), query, documents, 5)
	if err != nil || len(exact) != 0 {
		t.Fatalf("exact candidates = %+v, err = %v", exact, err)
	}
	weighted, err := NewWeightedLexicalConceptRetriever().Retrieve(context.Background(), query, documents, 5)
	if err != nil || len(weighted) == 0 {
		t.Fatalf("ordinary lexical candidates = %+v, err = %v", weighted, err)
	}

	bm25, err := NewBM25ConceptRetriever().Retrieve(context.Background(), query, documents, 5)
	if err != nil {
		t.Fatalf("BM25 Retrieve: %v", err)
	}
	if len(bm25) == 0 || bm25[0].ConceptID != 11 || bm25[0].Rank != 1 {
		t.Fatalf("BM25 candidates = %+v", bm25)
	}
	var evidence bm25RetrievalEvidenceV1
	if err := json.Unmarshal([]byte(bm25[0].Evidence), &evidence); err != nil {
		t.Fatalf("decode BM25 evidence: %v", err)
	}
	contributions := make(map[string]float64, len(evidence.TermContributions))
	for _, contribution := range evidence.TermContributions {
		contributions[contribution.Token] = contribution.Contribution
	}
	if contributions["parler"] <= contributions["article"] {
		t.Fatalf("rare parler contribution = %v, common article contribution = %v", contributions["parler"], contributions["article"])
	}
}
