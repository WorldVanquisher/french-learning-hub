package application

import (
	"context"
	"sort"

	"french-learning-app/internal/domain"
)

// ExactSignatureRetrieverV1Name identifies the retrieval-only exact identity
// baseline. It is deliberately versioned separately from Concept resolution.
const ExactSignatureRetrieverV1Name = "exact_signature_retriever_v1"

// ConceptRetrievalQuery contains immutable Unit evidence and its deterministic
// candidate identity. Future retrievers can use the representation fields
// without changing this provider-independent contract.
type ConceptRetrievalQuery struct {
	UnitID            int64
	Kind              domain.KnowledgeKind
	Canonical         string
	Statement         string
	Example           *string
	CandidateIdentity domain.ConceptIdentity
}

// ConceptRetrievalDocument is one durable Concept representation available to
// a retriever. Lifecycle/support/state are metadata; catalog policy remains the
// evaluation service's responsibility.
type ConceptRetrievalDocument struct {
	ConceptID             int64
	IdentitySchemaVersion string
	Target                string
	PedagogicalIntent     string
	Scope                 string
	IdentityFeatures      map[string]string
	Signature             string
	Lifecycle             domain.ConceptLifecycleState
	Support               domain.ConceptSupportState
	State                 domain.ConceptState
}

// ConceptRetrievalCandidate is one ranked retrieval result. Score is a
// retriever-specific value, not a calibrated probability.
type ConceptRetrievalCandidate struct {
	ConceptID int64
	Rank      int
	Score     float64
	Evidence  string
}

// ConceptRetriever ranks existing Concept documents for one Unit query. It has
// no mutation, persistence, resolver, or annotation capability.
type ConceptRetriever interface {
	Name() string
	Retrieve(ctx context.Context, query ConceptRetrievalQuery, concepts []ConceptRetrievalDocument, limit int) ([]ConceptRetrievalCandidate, error)
}

// ExactSignatureConceptRetriever is a deterministic lower-bound baseline. It
// returns only complete candidate-identity signature matches.
type ExactSignatureConceptRetriever struct{}

func NewExactSignatureConceptRetriever() *ExactSignatureConceptRetriever {
	return &ExactSignatureConceptRetriever{}
}

func (*ExactSignatureConceptRetriever) Name() string {
	return ExactSignatureRetrieverV1Name
}

func (*ExactSignatureConceptRetriever) Retrieve(_ context.Context, query ConceptRetrievalQuery, concepts []ConceptRetrievalDocument, limit int) ([]ConceptRetrievalCandidate, error) {
	candidates := make([]ConceptRetrievalCandidate, 0)
	if limit <= 0 {
		return candidates, nil
	}

	signature := query.CandidateIdentity.Signature()
	matches := make([]ConceptRetrievalDocument, 0)
	for _, concept := range concepts {
		if concept.Signature == signature {
			matches = append(matches, concept)
		}
	}
	sort.Slice(matches, func(i, j int) bool { return matches[i].ConceptID < matches[j].ConceptID })
	if len(matches) > limit {
		matches = matches[:limit]
	}
	for i, concept := range matches {
		candidates = append(candidates, ConceptRetrievalCandidate{
			ConceptID: concept.ConceptID,
			Rank:      i + 1,
			Score:     1.0,
			Evidence:  "exact_identity_signature",
		})
	}
	return candidates, nil
}
