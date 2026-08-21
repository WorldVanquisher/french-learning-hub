package application

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"reflect"
	"strings"
	"testing"

	"french-learning-app/internal/domain"
)

type frozenEmbeddingProvider struct {
	name    string
	vectors map[string][]float64
	output  [][]float64
	err     error
	calls   int
	batches [][]string
}

func (f *frozenEmbeddingProvider) Name() string { return f.name }

func (f *frozenEmbeddingProvider) Embed(_ context.Context, texts []string) ([][]float64, error) {
	f.calls++
	f.batches = append(f.batches, append([]string(nil), texts...))
	if f.err != nil {
		return nil, f.err
	}
	if f.output != nil {
		return f.output, nil
	}
	vectors := make([][]float64, 0, len(texts))
	for _, text := range texts {
		vector, ok := f.vectors[text]
		if !ok {
			return nil, errors.New("frozen vector missing")
		}
		vectors = append(vectors, append([]float64(nil), vector...))
	}
	return vectors, nil
}

func TestConceptEmbeddingTextV1_DeterministicFieldsAndSortedFeatures(t *testing.T) {
	example := "Il faut partir."
	query := ConceptRetrievalQuery{
		UnitID:    999,
		Kind:      domain.KindGrammar,
		Canonical: "obligation impersonnelle",
		Statement: "Employer une tournure sans sujet personnel.",
		Example:   &example,
		CandidateIdentity: domain.ConceptIdentity{
			Target:            "il faut + infinitif",
			PedagogicalIntent: "usage",
			Scope:             "phrase simple",
			IdentityFeatures:  map[string]string{"register": "neutral", "construction": "impersonal"},
		},
	}
	got, err := conceptEmbeddingQueryText(query)
	if err != nil {
		t.Fatalf("query text: %v", err)
	}
	want := `{"representation":"concept_embedding_text_v1","type":"query","canonical":"obligation impersonnelle","statement":"Employer une tournure sans sujet personnel.","example":"Il faut partir.","candidate_target":"il faut + infinitif","pedagogical_intent":"usage","scope":"phrase simple","identity_features":[{"key":"construction","value":"impersonal"},{"key":"register","value":"neutral"}]}`
	if got != want {
		t.Fatalf("query text = %s\nwant = %s", got, want)
	}
	again, err := conceptEmbeddingQueryText(query)
	if err != nil || again != got {
		t.Fatalf("second query text = %q, err = %v", again, err)
	}
	if strings.Contains(got, "999") || strings.Contains(got, `"kind"`) {
		t.Fatalf("query metadata leaked into embedding text: %s", got)
	}

	document := ConceptRetrievalDocument{
		ConceptID: 42, IdentitySchemaVersion: "secret-schema", Target: "il faut + infinitif",
		PedagogicalIntent: "usage", Scope: "phrase simple",
		IdentityFeatures: map[string]string{"register": "neutral", "construction": "impersonal"},
		Signature:        "secret-signature", Lifecycle: domain.LifecycleRetired,
		Support: domain.SupportOrphaned, State: domain.ConceptRetired,
	}
	documentText, err := conceptEmbeddingDocumentText(document)
	if err != nil {
		t.Fatalf("document text: %v", err)
	}
	wantDocument := `{"representation":"concept_embedding_text_v1","type":"concept","target":"il faut + infinitif","pedagogical_intent":"usage","scope":"phrase simple","identity_features":[{"key":"construction","value":"impersonal"},{"key":"register","value":"neutral"}]}`
	if documentText != wantDocument {
		t.Fatalf("document text = %s\nwant = %s", documentText, wantDocument)
	}
	for _, excluded := range []string{"42", "secret-schema", "secret-signature", "retired", "orphaned"} {
		if strings.Contains(documentText, excluded) {
			t.Fatalf("document metadata %q leaked into text: %s", excluded, documentText)
		}
	}

	metadataVariant := document
	metadataVariant.ConceptID = 500
	metadataVariant.IdentitySchemaVersion = "other"
	metadataVariant.Signature = "other"
	metadataVariant.Lifecycle = domain.LifecycleNormal
	metadataVariant.Support = domain.SupportSupported
	metadataVariant.State = domain.ConceptActive
	variantText, err := conceptEmbeddingDocumentText(metadataVariant)
	if err != nil || variantText != documentText {
		t.Fatalf("metadata changed document text: %q, err = %v", variantText, err)
	}
}

func TestEmbeddingCosineSimilarity_VectorSafety(t *testing.T) {
	for _, tc := range []struct {
		name    string
		left    []float64
		right   []float64
		want    float64
		wantErr bool
	}{
		{name: "identical", left: []float64{1, 2}, right: []float64{1, 2}, want: 1},
		{name: "orthogonal", left: []float64{1, 0}, right: []float64{0, 2}, want: 0},
		{name: "opposite", left: []float64{1, 0}, right: []float64{-2, 0}, want: -1},
		{name: "zero norm", left: []float64{0, 0}, right: []float64{1, 0}, want: 0},
		{name: "empty", left: nil, right: []float64{1}, wantErr: true},
		{name: "dimension mismatch", left: []float64{1}, right: []float64{1, 0}, wantErr: true},
		{name: "nan", left: []float64{math.NaN()}, right: []float64{1}, wantErr: true},
		{name: "infinity", left: []float64{1}, right: []float64{math.Inf(1)}, wantErr: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, err := embeddingCosineSimilarity(tc.left, tc.right)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("similarity = %v, want error", got)
				}
				return
			}
			if err != nil || math.Abs(got-tc.want) > 1e-12 || math.IsNaN(got) || math.IsInf(got, 0) {
				t.Fatalf("similarity = %v, err = %v, want %v", got, err, tc.want)
			}
		})
	}
}

func TestEmbeddingConceptRetriever_BatchesRanksLimitsAndEmitsStableEvidence(t *testing.T) {
	query := ConceptRetrievalQuery{Canonical: "semantic query"}
	documents := []ConceptRetrievalDocument{
		{ConceptID: 7, Target: "same seven"},
		{ConceptID: 9, Target: "orthogonal"},
		{ConceptID: 2, Target: "same two"},
		{ConceptID: 5, Target: "partial"},
		{ConceptID: 10, Target: "zero"},
	}
	queryText, _ := conceptEmbeddingQueryText(query)
	vectors := map[string][]float64{queryText: {1, 0}}
	for _, document := range documents {
		text, _ := conceptEmbeddingDocumentText(document)
		switch document.ConceptID {
		case 2, 7:
			vectors[text] = []float64{1, 0}
		case 5:
			vectors[text] = []float64{0.6, 0.8}
		case 9:
			vectors[text] = []float64{0, 1}
		case 10:
			vectors[text] = []float64{0, 0}
		}
	}
	provider := &frozenEmbeddingProvider{name: "frozen:semantic-v1", vectors: vectors}
	retriever := NewEmbeddingConceptRetriever(provider)
	if retriever.Name() != EmbeddingRetrieverV1Name {
		t.Fatalf("Name = %q", retriever.Name())
	}

	got, err := retriever.Retrieve(context.Background(), query, documents, 3)
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	wantIDs := []int64{2, 7, 5}
	if len(got) != len(wantIDs) {
		t.Fatalf("candidates = %+v", got)
	}
	for index, candidate := range got {
		if candidate.ConceptID != wantIDs[index] || candidate.Rank != index+1 || candidate.Score <= 0 || math.IsNaN(candidate.Score) || math.IsInf(candidate.Score, 0) {
			t.Fatalf("candidate[%d] = %+v", index, candidate)
		}
		var evidence embeddingRetrievalEvidenceV1
		if err := json.Unmarshal([]byte(candidate.Evidence), &evidence); err != nil {
			t.Fatalf("evidence[%d]: %v", index, err)
		}
		if evidence.Reason != embeddingEvidenceReasonV1 || evidence.Provider != provider.name || evidence.Representation != ConceptEmbeddingTextV1 || evidence.Similarity != candidate.Score || evidence.Dimensions != 2 {
			t.Fatalf("evidence[%d] = %+v", index, evidence)
		}
		if strings.Contains(candidate.Evidence, "[1") || strings.Contains(candidate.Evidence, "[0") {
			t.Fatalf("evidence leaked raw vector: %s", candidate.Evidence)
		}
	}
	if provider.calls != 1 || len(provider.batches) != 1 || len(provider.batches[0]) != len(documents)+1 || provider.batches[0][0] != queryText {
		t.Fatalf("provider calls/batch = %d, %#v", provider.calls, provider.batches)
	}
	for index, document := range documents {
		wantText, _ := conceptEmbeddingDocumentText(document)
		if provider.batches[0][index+1] != wantText {
			t.Fatalf("batch document[%d] = %q, want %q", index, provider.batches[0][index+1], wantText)
		}
	}

	again, err := retriever.Retrieve(context.Background(), query, documents, 3)
	if err != nil || !reflect.DeepEqual(again, got) {
		t.Fatalf("second retrieval = %+v, err = %v; want %+v", again, err, got)
	}
	limited, err := retriever.Retrieve(context.Background(), query, documents, 1)
	if err != nil || len(limited) != 1 || limited[0].ConceptID != 2 || limited[0].Rank != 1 {
		t.Fatalf("limited candidates = %+v, err = %v", limited, err)
	}
}

func TestEmbeddingConceptRetriever_EmptyInputsAndProviderFailures(t *testing.T) {
	provider := &frozenEmbeddingProvider{name: "frozen:test", vectors: map[string][]float64{}}
	retriever := NewEmbeddingConceptRetriever(provider)
	for _, tc := range []struct {
		name      string
		query     ConceptRetrievalQuery
		documents []ConceptRetrievalDocument
		limit     int
	}{
		{name: "zero limit", query: ConceptRetrievalQuery{Canonical: "query"}, documents: []ConceptRetrievalDocument{{ConceptID: 1, Target: "doc"}}, limit: 0},
		{name: "empty corpus", query: ConceptRetrievalQuery{Canonical: "query"}, limit: 5},
		{name: "empty query", documents: []ConceptRetrievalDocument{{ConceptID: 1, Target: "doc"}}, limit: 5},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, err := retriever.Retrieve(context.Background(), tc.query, tc.documents, tc.limit)
			if err != nil || got == nil || len(got) != 0 {
				t.Fatalf("candidates = %#v, err = %v", got, err)
			}
		})
	}
	if provider.calls != 0 {
		t.Fatalf("provider calls = %d, want 0", provider.calls)
	}

	if _, err := NewEmbeddingConceptRetriever(nil).Retrieve(context.Background(), ConceptRetrievalQuery{Canonical: "query"}, []ConceptRetrievalDocument{{ConceptID: 1, Target: "doc"}}, 5); !errors.Is(err, ErrEmbeddingProviderUnavailable) {
		t.Fatalf("nil provider error = %v", err)
	}

	sentinel := errors.New("frozen provider failed")
	failing := &frozenEmbeddingProvider{name: "frozen:test", err: sentinel}
	if _, err := NewEmbeddingConceptRetriever(failing).Retrieve(context.Background(), ConceptRetrievalQuery{Canonical: "query"}, []ConceptRetrievalDocument{{ConceptID: 1, Target: "doc"}}, 5); !errors.Is(err, sentinel) {
		t.Fatalf("provider error = %v", err)
	}

	for _, tc := range []struct {
		name   string
		output [][]float64
	}{
		{name: "wrong vector count", output: [][]float64{{1, 0}}},
		{name: "empty vector", output: [][]float64{{1, 0}, {}}},
		{name: "dimension mismatch", output: [][]float64{{1, 0}, {1}}},
		{name: "nan", output: [][]float64{{1, 0}, {math.NaN(), 0}}},
		{name: "infinity", output: [][]float64{{1, 0}, {math.Inf(1), 0}}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			invalid := &frozenEmbeddingProvider{name: "frozen:test", output: tc.output}
			_, err := NewEmbeddingConceptRetriever(invalid).Retrieve(context.Background(), ConceptRetrievalQuery{Canonical: "query"}, []ConceptRetrievalDocument{{ConceptID: 1, Target: "doc"}}, 5)
			if !errors.Is(err, ErrEmbeddingProviderUnavailable) {
				t.Fatalf("error = %v", err)
			}
		})
	}
}

func TestEmbeddingConceptRetriever_ControlledFrenchSemanticRegression(t *testing.T) {
	query := ConceptRetrievalQuery{
		Canonical: "tournure impersonnelle pour dire on doit agir",
		Statement: "Je cherche une autre manière sans employer le mot cible.",
		CandidateIdentity: domain.ConceptIdentity{
			Target:            "formulation de l'obligation",
			PedagogicalIntent: "usage",
		},
	}
	documents := []ConceptRetrievalDocument{
		{ConceptID: 11, Target: "il faut + infinitif", PedagogicalIntent: "nécessité générale", Signature: retrievalTestIdentity("il faut + infinitif").Signature()},
		{ConceptID: 12, Target: "tournure impersonnelle avec on", PedagogicalIntent: "emploi du pronom on", Signature: retrievalTestIdentity("tournure avec on").Signature()},
		{ConceptID: 13, Target: "accord du participe passé", PedagogicalIntent: "morphologie", Signature: retrievalTestIdentity("accord du participe").Signature()},
	}
	exact, err := NewExactSignatureConceptRetriever().Retrieve(context.Background(), query, documents, 5)
	if err != nil || len(exact) != 0 {
		t.Fatalf("exact candidates = %+v, err = %v", exact, err)
	}
	weighted, err := NewWeightedLexicalConceptRetriever().Retrieve(context.Background(), query, documents, 5)
	if err != nil || len(weighted) == 0 || weighted[0].ConceptID != 12 {
		t.Fatalf("weighted lexical candidates = %+v, err = %v", weighted, err)
	}
	bm25, err := NewBM25ConceptRetriever().Retrieve(context.Background(), query, documents, 5)
	if err != nil || len(bm25) == 0 || bm25[0].ConceptID != 12 {
		t.Fatalf("BM25 candidates = %+v, err = %v", bm25, err)
	}

	queryText, _ := conceptEmbeddingQueryText(query)
	vectors := map[string][]float64{queryText: {1, 0, 0}}
	for _, document := range documents {
		text, _ := conceptEmbeddingDocumentText(document)
		switch document.ConceptID {
		case 11:
			vectors[text] = []float64{0.99, 0.01, 0}
		case 12:
			vectors[text] = []float64{0.1, 0.99, 0}
		case 13:
			vectors[text] = []float64{0, 0, 1}
		}
	}
	semantic, err := NewEmbeddingConceptRetriever(&frozenEmbeddingProvider{name: "frozen:french-semantic-v1", vectors: vectors}).Retrieve(context.Background(), query, documents, 5)
	if err != nil {
		t.Fatalf("embedding Retrieve: %v", err)
	}
	if len(semantic) == 0 || semantic[0].ConceptID != 11 || semantic[0].Rank != 1 {
		t.Fatalf("embedding candidates = %+v", semantic)
	}
}
