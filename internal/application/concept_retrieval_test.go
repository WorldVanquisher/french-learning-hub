package application

import (
	"context"
	"reflect"
	"testing"

	"french-learning-app/internal/domain"
)

func retrievalTestIdentity(target string) domain.ConceptIdentity {
	return domain.ConceptIdentity{Target: target, PedagogicalIntent: "grammar", IdentityFeatures: map[string]string{}}
}

func TestExactSignatureConceptRetriever_ExactOnlyScoreRankAndDeterminism(t *testing.T) {
	identity := retrievalTestIdentity("vouloir + infinitif")
	retriever := NewExactSignatureConceptRetriever()
	documents := []ConceptRetrievalDocument{
		{ConceptID: 9, Signature: retrievalTestIdentity("different").Signature()},
		{ConceptID: 3, Signature: identity.Signature(), Lifecycle: domain.LifecycleNormal},
		// The retriever intentionally does not hide lifecycle policy. Evaluation
		// catalog composition must remove retired documents before this call.
		{ConceptID: 2, Signature: identity.Signature(), Lifecycle: domain.LifecycleRetired},
		{ConceptID: 1, Signature: identity.Signature(), Lifecycle: domain.LifecycleNormal},
	}
	got, err := retriever.Retrieve(context.Background(), ConceptRetrievalQuery{CandidateIdentity: identity}, documents, 5)
	if err != nil {
		t.Fatalf("Retrieve: %v", err)
	}
	want := []ConceptRetrievalCandidate{
		{ConceptID: 1, Rank: 1, Score: 1, Evidence: "exact_identity_signature"},
		{ConceptID: 2, Rank: 2, Score: 1, Evidence: "exact_identity_signature"},
		{ConceptID: 3, Rank: 3, Score: 1, Evidence: "exact_identity_signature"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("candidates = %+v, want %+v", got, want)
	}
	if retriever.Name() != ExactSignatureRetrieverV1Name {
		t.Fatalf("Name = %q", retriever.Name())
	}
}

func TestExactSignatureConceptRetriever_NonExactAndLimit(t *testing.T) {
	retriever := NewExactSignatureConceptRetriever()
	query := ConceptRetrievalQuery{CandidateIdentity: retrievalTestIdentity("query")}
	nonmatch, err := retriever.Retrieve(context.Background(), query, []ConceptRetrievalDocument{{ConceptID: 1, Signature: retrievalTestIdentity("other").Signature()}}, 5)
	if err != nil || len(nonmatch) != 0 || nonmatch == nil {
		t.Fatalf("nonmatch = %+v, err = %v", nonmatch, err)
	}
	matches, err := retriever.Retrieve(context.Background(), query, []ConceptRetrievalDocument{
		{ConceptID: 2, Signature: query.CandidateIdentity.Signature()},
		{ConceptID: 1, Signature: query.CandidateIdentity.Signature()},
	}, 1)
	if err != nil || len(matches) != 1 || matches[0].ConceptID != 1 || matches[0].Rank != 1 {
		t.Fatalf("limited matches = %+v, err = %v", matches, err)
	}
}
