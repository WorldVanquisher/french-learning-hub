package application

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"strings"
)

const (
	EmbeddingRetrieverV1Name  = "embedding_retriever_v1"
	ConceptEmbeddingTextV1    = "concept_embedding_text_v1"
	embeddingEvidenceReasonV1 = "embedding_cosine"
)

var (
	// ErrEmbeddingProviderUnavailable identifies configured provider failures
	// and invalid provider output. Transport may safely expose only the category.
	ErrEmbeddingProviderUnavailable = errors.New("embedding provider unavailable")
	// ErrEmbeddingProviderTimeout identifies a provider request deadline.
	ErrEmbeddingProviderTimeout = errors.New("embedding provider timeout")
)

// EmbeddingProvider is the application-facing, batch-oriented text-to-vector
// boundary. It knows nothing about repositories, Concepts, annotations,
// lifecycle policy, retrieval metrics, or HTTP transport.
type EmbeddingProvider interface {
	Name() string
	Embed(ctx context.Context, texts []string) ([][]float64, error)
}

type conceptEmbeddingFeatureV1 struct {
	Key   string `json:"key"`
	Value string `json:"value"`
}

type conceptEmbeddingQueryTextV1 struct {
	Representation    string                      `json:"representation"`
	Type              string                      `json:"type"`
	Canonical         string                      `json:"canonical"`
	Statement         string                      `json:"statement"`
	Example           *string                     `json:"example"`
	CandidateTarget   string                      `json:"candidate_target"`
	PedagogicalIntent string                      `json:"pedagogical_intent"`
	Scope             string                      `json:"scope"`
	IdentityFeatures  []conceptEmbeddingFeatureV1 `json:"identity_features"`
}

type conceptEmbeddingDocumentTextV1 struct {
	Representation    string                      `json:"representation"`
	Type              string                      `json:"type"`
	Target            string                      `json:"target"`
	PedagogicalIntent string                      `json:"pedagogical_intent"`
	Scope             string                      `json:"scope"`
	IdentityFeatures  []conceptEmbeddingFeatureV1 `json:"identity_features"`
}

type embeddingRetrievalEvidenceV1 struct {
	Reason         string  `json:"reason"`
	Provider       string  `json:"provider"`
	Representation string  `json:"representation"`
	Similarity     float64 `json:"similarity"`
	Dimensions     int     `json:"dimensions"`
}

// EmbeddingConceptRetriever ranks caller-supplied Concept documents using
// cosine similarity over one provider batch. It has no persistence, resolver,
// annotation, lifecycle-policy, or metric capability.
type EmbeddingConceptRetriever struct {
	provider EmbeddingProvider
}

var _ ConceptRetriever = (*EmbeddingConceptRetriever)(nil)

func NewEmbeddingConceptRetriever(provider EmbeddingProvider) *EmbeddingConceptRetriever {
	return &EmbeddingConceptRetriever{provider: provider}
}

func (*EmbeddingConceptRetriever) Name() string {
	return EmbeddingRetrieverV1Name
}

func (r *EmbeddingConceptRetriever) Retrieve(ctx context.Context, query ConceptRetrievalQuery, concepts []ConceptRetrievalDocument, limit int) ([]ConceptRetrievalCandidate, error) {
	candidates := make([]ConceptRetrievalCandidate, 0)
	if limit <= 0 || len(concepts) == 0 || !conceptEmbeddingQueryHasContent(query) {
		return candidates, nil
	}
	if r.provider == nil {
		return nil, fmt.Errorf("%w: semantic retrieval is not configured", ErrEmbeddingProviderUnavailable)
	}
	providerName := r.provider.Name()
	if strings.TrimSpace(providerName) == "" {
		return nil, fmt.Errorf("%w: semantic retrieval is not configured", ErrEmbeddingProviderUnavailable)
	}

	queryText, err := conceptEmbeddingQueryText(query)
	if err != nil {
		return nil, fmt.Errorf("build %s query text: %w", ConceptEmbeddingTextV1, err)
	}
	texts := make([]string, 0, len(concepts)+1)
	texts = append(texts, queryText)
	for _, concept := range concepts {
		documentText, err := conceptEmbeddingDocumentText(concept)
		if err != nil {
			return nil, fmt.Errorf("build %s document text: %w", ConceptEmbeddingTextV1, err)
		}
		texts = append(texts, documentText)
	}

	vectors, err := r.provider.Embed(ctx, texts)
	if err != nil {
		return nil, fmt.Errorf("embed concept retrieval batch: %w", err)
	}
	if len(vectors) != len(texts) {
		return nil, fmt.Errorf("%w: returned %d vectors for %d texts", ErrEmbeddingProviderUnavailable, len(vectors), len(texts))
	}

	type scoredCandidate struct {
		conceptID int64
		score     float64
		evidence  string
	}
	queryVector := vectors[0]
	scored := make([]scoredCandidate, 0, len(concepts))
	for index, concept := range concepts {
		documentVector := vectors[index+1]
		score, err := embeddingCosineSimilarity(queryVector, documentVector)
		if err != nil {
			return nil, fmt.Errorf("%w: invalid vector for concept %d: %v", ErrEmbeddingProviderUnavailable, concept.ConceptID, err)
		}
		if score <= 0 {
			continue
		}
		evidence, err := embeddingRetrievalEvidence(providerName, score, len(queryVector))
		if err != nil {
			return nil, fmt.Errorf("encode embedding retrieval evidence: %w", err)
		}
		scored = append(scored, scoredCandidate{
			conceptID: concept.ConceptID,
			score:     score,
			evidence:  evidence,
		})
	}

	sort.Slice(scored, func(i, j int) bool {
		if scored[i].score != scored[j].score {
			return scored[i].score > scored[j].score
		}
		return scored[i].conceptID < scored[j].conceptID
	})
	if len(scored) > limit {
		scored = scored[:limit]
	}
	for index, candidate := range scored {
		candidates = append(candidates, ConceptRetrievalCandidate{
			ConceptID: candidate.conceptID,
			Rank:      index + 1,
			Score:     candidate.score,
			Evidence:  candidate.evidence,
		})
	}
	return candidates, nil
}

func conceptEmbeddingQueryText(query ConceptRetrievalQuery) (string, error) {
	value := conceptEmbeddingQueryTextV1{
		Representation:    ConceptEmbeddingTextV1,
		Type:              "query",
		Canonical:         query.Canonical,
		Statement:         query.Statement,
		Example:           query.Example,
		CandidateTarget:   query.CandidateIdentity.Target,
		PedagogicalIntent: query.CandidateIdentity.PedagogicalIntent,
		Scope:             query.CandidateIdentity.Scope,
		IdentityFeatures:  conceptEmbeddingFeatures(query.CandidateIdentity.IdentityFeatures),
	}
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	return string(encoded), nil
}

func conceptEmbeddingDocumentText(document ConceptRetrievalDocument) (string, error) {
	value := conceptEmbeddingDocumentTextV1{
		Representation:    ConceptEmbeddingTextV1,
		Type:              "concept",
		Target:            document.Target,
		PedagogicalIntent: document.PedagogicalIntent,
		Scope:             document.Scope,
		IdentityFeatures:  conceptEmbeddingFeatures(document.IdentityFeatures),
	}
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	return string(encoded), nil
}

func conceptEmbeddingFeatures(features map[string]string) []conceptEmbeddingFeatureV1 {
	keys := make([]string, 0, len(features))
	for key := range features {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	values := make([]conceptEmbeddingFeatureV1, 0, len(keys))
	for _, key := range keys {
		values = append(values, conceptEmbeddingFeatureV1{Key: key, Value: features[key]})
	}
	return values
}

func conceptEmbeddingQueryHasContent(query ConceptRetrievalQuery) bool {
	values := []string{
		query.Canonical,
		query.Statement,
		query.CandidateIdentity.Target,
		query.CandidateIdentity.PedagogicalIntent,
		query.CandidateIdentity.Scope,
	}
	if query.Example != nil {
		values = append(values, *query.Example)
	}
	for key, value := range query.CandidateIdentity.IdentityFeatures {
		values = append(values, key, value)
	}
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return true
		}
	}
	return false
}

func embeddingCosineSimilarity(left, right []float64) (float64, error) {
	if len(left) == 0 || len(right) == 0 {
		return 0, errors.New("embedding vector is empty")
	}
	if len(left) != len(right) {
		return 0, fmt.Errorf("embedding dimensions differ: %d and %d", len(left), len(right))
	}
	var dot, leftNormSquared, rightNormSquared float64
	for index := range left {
		if math.IsNaN(left[index]) || math.IsInf(left[index], 0) || math.IsNaN(right[index]) || math.IsInf(right[index], 0) {
			return 0, errors.New("embedding vector contains a non-finite value")
		}
		dot += left[index] * right[index]
		leftNormSquared += left[index] * left[index]
		rightNormSquared += right[index] * right[index]
	}
	if leftNormSquared == 0 || rightNormSquared == 0 {
		return 0, nil
	}
	similarity := dot / (math.Sqrt(leftNormSquared) * math.Sqrt(rightNormSquared))
	if math.IsNaN(similarity) || math.IsInf(similarity, 0) {
		return 0, errors.New("embedding cosine is non-finite")
	}
	if similarity > 1 {
		return 1, nil
	}
	if similarity < -1 {
		return -1, nil
	}
	return similarity, nil
}

func embeddingRetrievalEvidence(provider string, similarity float64, dimensions int) (string, error) {
	encoded, err := json.Marshal(embeddingRetrievalEvidenceV1{
		Reason:         embeddingEvidenceReasonV1,
		Provider:       provider,
		Representation: ConceptEmbeddingTextV1,
		Similarity:     similarity,
		Dimensions:     dimensions,
	})
	if err != nil {
		return "", err
	}
	return string(encoded), nil
}
