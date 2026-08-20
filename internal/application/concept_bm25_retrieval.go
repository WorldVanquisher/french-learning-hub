package application

import (
	"context"
	"encoding/json"
	"math"
	"sort"
)

const (
	// BM25RetrieverV1Name identifies the deterministic corpus-aware lexical
	// baseline. The algorithm and its fixed parameters are versioned together.
	BM25RetrieverV1Name = "bm25_retriever_v1"
	BM25K1V1            = 1.2
	BM25BV1             = 0.75

	bm25QueryCanonicalWeightV1     = 4.0
	bm25QueryStatementWeightV1     = 2.0
	bm25QueryIntentWeightV1        = 1.0
	bm25QueryScopeWeightV1         = 1.0
	bm25QueryFeatureKeysWeightV1   = 1.0
	bm25QueryFeatureValuesWeightV1 = 1.0

	bm25DocumentTargetWeightV1        = 4.0
	bm25DocumentIntentWeightV1        = 1.0
	bm25DocumentScopeWeightV1         = 1.0
	bm25DocumentFeatureKeysWeightV1   = 1.0
	bm25DocumentFeatureValuesWeightV1 = 1.0
)

type bm25WeightedTerms map[string]float64

type bm25DocumentRepresentation struct {
	document ConceptRetrievalDocument
	terms    bm25WeightedTerms
	length   float64
}

type bm25CorpusStatistics struct {
	documents             []bm25DocumentRepresentation
	documentFrequency     map[string]int
	averageDocumentLength float64
}

type bm25TokenContribution struct {
	Token             string  `json:"token"`
	QueryWeight       float64 `json:"query_weight"`
	DocumentFrequency int     `json:"document_frequency"`
	IDF               float64 `json:"idf"`
	DocumentTF        float64 `json:"document_tf"`
	Contribution      float64 `json:"contribution"`
}

type bm25RetrievalEvidenceV1 struct {
	Reason        string `json:"reason"`
	Normalization string `json:"normalization"`
	Parameters    struct {
		K1 float64 `json:"k1"`
		B  float64 `json:"b"`
	} `json:"parameters"`
	CorpusDocuments       int                     `json:"corpus_documents"`
	DocumentLength        float64                 `json:"document_length"`
	AverageDocumentLength float64                 `json:"average_document_length"`
	MatchedTokens         []string                `json:"matched_tokens"`
	TermContributions     []bm25TokenContribution `json:"term_contributions"`
}

// BM25ConceptRetriever computes corpus statistics from the caller-supplied
// documents for each retrieval call. It has no repository, persistence,
// annotation, resolution, or provider capability.
type BM25ConceptRetriever struct{}

func NewBM25ConceptRetriever() *BM25ConceptRetriever {
	return &BM25ConceptRetriever{}
}

func (*BM25ConceptRetriever) Name() string {
	return BM25RetrieverV1Name
}

// Retrieve applies a field-weighted BM25 variant. Raw normalized term counts
// are multiplied by explicit field weights, not produced by token duplication.
// Weighted document term frequency is saturated by BM25, while weighted
// document length participates in the standard b normalization term.
func (*BM25ConceptRetriever) Retrieve(_ context.Context, query ConceptRetrievalQuery, concepts []ConceptRetrievalDocument, limit int) ([]ConceptRetrievalCandidate, error) {
	candidates := make([]ConceptRetrievalCandidate, 0)
	if limit <= 0 || len(concepts) == 0 {
		return candidates, nil
	}

	queryTerms := bm25QueryTerms(query)
	if len(queryTerms) == 0 {
		return candidates, nil
	}
	queryTokens := sortedBM25Tokens(queryTerms)
	corpus := buildBM25CorpusStatistics(concepts)
	if corpus.averageDocumentLength <= 0 {
		return candidates, nil
	}

	type scoredCandidate struct {
		conceptID int64
		score     float64
		evidence  string
	}
	scored := make([]scoredCandidate, 0, len(corpus.documents))
	for _, document := range corpus.documents {
		contributions := make([]bm25TokenContribution, 0)
		var score float64
		for _, token := range queryTokens {
			documentTF := document.terms[token]
			if documentTF <= 0 {
				continue
			}
			documentFrequency := corpus.documentFrequency[token]
			idf := bm25InverseDocumentFrequency(len(corpus.documents), documentFrequency)
			contribution := bm25TermContribution(
				queryTerms[token], idf, documentTF, document.length,
				corpus.averageDocumentLength, BM25K1V1, BM25BV1,
			)
			if contribution <= 0 || math.IsNaN(contribution) || math.IsInf(contribution, 0) {
				continue
			}
			score += contribution
			contributions = append(contributions, bm25TokenContribution{
				Token: token, QueryWeight: queryTerms[token],
				DocumentFrequency: documentFrequency, IDF: idf,
				DocumentTF: documentTF, Contribution: contribution,
			})
		}
		if score <= 0 || math.IsNaN(score) || math.IsInf(score, 0) {
			continue
		}
		scored = append(scored, scoredCandidate{
			conceptID: document.document.ConceptID,
			score:     score,
			evidence: bm25RetrievalEvidence(
				len(corpus.documents), document.length,
				corpus.averageDocumentLength, contributions,
			),
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

func bm25QueryTerms(query ConceptRetrievalQuery) bm25WeightedTerms {
	terms := make(bm25WeightedTerms)
	addBM25Field(terms, query.Canonical, bm25QueryCanonicalWeightV1)
	addBM25Field(terms, query.Statement, bm25QueryStatementWeightV1)
	addBM25Field(terms, query.CandidateIdentity.PedagogicalIntent, bm25QueryIntentWeightV1)
	addBM25Field(terms, query.CandidateIdentity.Scope, bm25QueryScopeWeightV1)
	keys, values := sortedLexicalFeatureFields(query.CandidateIdentity.IdentityFeatures)
	addBM25Field(terms, keys, bm25QueryFeatureKeysWeightV1)
	addBM25Field(terms, values, bm25QueryFeatureValuesWeightV1)
	return terms
}

func bm25DocumentTerms(document ConceptRetrievalDocument) (bm25WeightedTerms, float64) {
	terms := make(bm25WeightedTerms)
	var length float64
	length += addBM25Field(terms, document.Target, bm25DocumentTargetWeightV1)
	length += addBM25Field(terms, document.PedagogicalIntent, bm25DocumentIntentWeightV1)
	length += addBM25Field(terms, document.Scope, bm25DocumentScopeWeightV1)
	keys, values := sortedLexicalFeatureFields(document.IdentityFeatures)
	length += addBM25Field(terms, keys, bm25DocumentFeatureKeysWeightV1)
	length += addBM25Field(terms, values, bm25DocumentFeatureValuesWeightV1)
	return terms, length
}

func addBM25Field(terms bm25WeightedTerms, value string, weight float64) float64 {
	var length float64
	for _, token := range NormalizeConceptLexicalTokens(value) {
		terms[token] += weight
		length += weight
	}
	return length
}

func buildBM25CorpusStatistics(concepts []ConceptRetrievalDocument) bm25CorpusStatistics {
	statistics := bm25CorpusStatistics{
		documents:         make([]bm25DocumentRepresentation, 0, len(concepts)),
		documentFrequency: make(map[string]int),
	}
	var totalLength float64
	for _, concept := range concepts {
		terms, length := bm25DocumentTerms(concept)
		document := bm25DocumentRepresentation{document: concept, terms: terms, length: length}
		statistics.documents = append(statistics.documents, document)
		totalLength += length
		for _, token := range sortedBM25Tokens(terms) {
			statistics.documentFrequency[token]++
		}
	}
	if len(statistics.documents) > 0 {
		statistics.averageDocumentLength = totalLength / float64(len(statistics.documents))
	}
	return statistics
}

// bm25InverseDocumentFrequency is the positive Robertson/Sparck Jones form:
// ln(1 + (N - df + 0.5) / (df + 0.5)).
func bm25InverseDocumentFrequency(documentCount, documentFrequency int) float64 {
	if documentCount <= 0 || documentFrequency <= 0 || documentFrequency > documentCount {
		return 0
	}
	return math.Log(1 + (float64(documentCount-documentFrequency)+0.5)/(float64(documentFrequency)+0.5))
}

func bm25TermContribution(queryWeight, idf, documentTF, documentLength, averageDocumentLength, k1, b float64) float64 {
	if queryWeight <= 0 || idf <= 0 || documentTF <= 0 || documentLength < 0 || averageDocumentLength <= 0 || k1 < 0 || b < 0 || b > 1 {
		return 0
	}
	lengthNormalization := 1 - b + b*documentLength/averageDocumentLength
	denominator := documentTF + k1*lengthNormalization
	if denominator <= 0 {
		return 0
	}
	contribution := queryWeight * idf * (documentTF * (k1 + 1) / denominator)
	if math.IsNaN(contribution) || math.IsInf(contribution, 0) || contribution <= 0 {
		return 0
	}
	return contribution
}

func sortedBM25Tokens(terms bm25WeightedTerms) []string {
	tokens := make([]string, 0, len(terms))
	for token := range terms {
		tokens = append(tokens, token)
	}
	sort.Strings(tokens)
	return tokens
}

func bm25RetrievalEvidence(corpusDocuments int, documentLength, averageDocumentLength float64, contributions []bm25TokenContribution) string {
	matchedTokens := make([]string, 0, len(contributions))
	for _, contribution := range contributions {
		matchedTokens = append(matchedTokens, contribution.Token)
	}
	evidence := bm25RetrievalEvidenceV1{
		Reason:                "bm25",
		Normalization:         ConceptLexicalNormalizationV1,
		CorpusDocuments:       corpusDocuments,
		DocumentLength:        documentLength,
		AverageDocumentLength: averageDocumentLength,
		MatchedTokens:         matchedTokens,
		TermContributions:     contributions,
	}
	evidence.Parameters.K1 = BM25K1V1
	evidence.Parameters.B = BM25BV1
	encoded, err := json.Marshal(evidence)
	if err != nil {
		return `{"reason":"bm25","normalization":"concept_lexical_normalization_v1","parameters":{"k1":1.2,"b":0.75},"corpus_documents":0,"document_length":0,"average_document_length":0,"matched_tokens":[],"term_contributions":[]}`
	}
	return string(encoded)
}
