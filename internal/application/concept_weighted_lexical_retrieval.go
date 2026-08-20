package application

import (
	"context"
	"encoding/json"
	"math"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"

	"golang.org/x/text/unicode/norm"
)

const (
	WeightedLexicalRetrieverV1Name = "weighted_lexical_retriever_v1"
	ConceptLexicalNormalizationV1  = "concept_lexical_normalization_v1"

	lexicalQueryCanonicalWeight     = 4.0
	lexicalQueryStatementWeight     = 2.0
	lexicalQueryIntentWeight        = 1.0
	lexicalQueryScopeWeight         = 1.0
	lexicalQueryFeatureKeysWeight   = 1.0
	lexicalQueryFeatureValuesWeight = 1.0

	lexicalDocumentTargetWeight        = 4.0
	lexicalDocumentIntentWeight        = 1.0
	lexicalDocumentScopeWeight         = 1.0
	lexicalDocumentFeatureKeysWeight   = 1.0
	lexicalDocumentFeatureValuesWeight = 1.0
)

type lexicalVector map[string]float64

// NormalizeConceptLexicalTokens applies the deterministic v1 lexical policy:
// Unicode lowercase, canonical decomposition, combining-mark removal,
// punctuation/separator boundaries, and removal of empty or one-rune tokens.
// It intentionally applies no stop-word list, stemming, or lemmatization.
func NormalizeConceptLexicalTokens(value string) []string {
	decomposed := norm.NFD.String(strings.ToLower(value))
	tokens := make([]string, 0)
	var token strings.Builder
	flush := func() {
		if token.Len() == 0 {
			return
		}
		value := token.String()
		if utf8.RuneCountInString(value) > 1 {
			tokens = append(tokens, value)
		}
		token.Reset()
	}
	for _, r := range decomposed {
		if unicode.IsMark(r) {
			continue
		}
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			token.WriteRune(r)
			continue
		}
		flush()
	}
	flush()
	return tokens
}

// WeightedLexicalConceptRetriever scores every supplied document with weighted
// cosine similarity. Catalog lifecycle policy remains outside the retriever.
type WeightedLexicalConceptRetriever struct{}

func NewWeightedLexicalConceptRetriever() *WeightedLexicalConceptRetriever {
	return &WeightedLexicalConceptRetriever{}
}

func (*WeightedLexicalConceptRetriever) Name() string {
	return WeightedLexicalRetrieverV1Name
}

func (*WeightedLexicalConceptRetriever) Retrieve(_ context.Context, query ConceptRetrievalQuery, concepts []ConceptRetrievalDocument, limit int) ([]ConceptRetrievalCandidate, error) {
	candidates := make([]ConceptRetrievalCandidate, 0)
	if limit <= 0 {
		return candidates, nil
	}

	queryVector := weightedLexicalQueryVector(query)
	type scoredCandidate struct {
		conceptID int64
		score     float64
		evidence  string
	}
	scored := make([]scoredCandidate, 0, len(concepts))
	for _, concept := range concepts {
		documentVector := weightedLexicalDocumentVector(concept)
		score := lexicalCosineSimilarity(queryVector, documentVector)
		if score <= 0 {
			continue
		}
		scored = append(scored, scoredCandidate{
			conceptID: concept.ConceptID,
			score:     score,
			evidence:  lexicalRetrievalEvidence(matchedLexicalTokens(queryVector, documentVector)),
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
			ConceptID: candidate.conceptID, Rank: index + 1,
			Score: candidate.score, Evidence: candidate.evidence,
		})
	}
	return candidates, nil
}

func weightedLexicalQueryVector(query ConceptRetrievalQuery) lexicalVector {
	vector := make(lexicalVector)
	addWeightedLexicalField(vector, query.Canonical, lexicalQueryCanonicalWeight)
	addWeightedLexicalField(vector, query.Statement, lexicalQueryStatementWeight)
	addWeightedLexicalField(vector, query.CandidateIdentity.PedagogicalIntent, lexicalQueryIntentWeight)
	addWeightedLexicalField(vector, query.CandidateIdentity.Scope, lexicalQueryScopeWeight)
	keys, values := sortedLexicalFeatureFields(query.CandidateIdentity.IdentityFeatures)
	addWeightedLexicalField(vector, keys, lexicalQueryFeatureKeysWeight)
	addWeightedLexicalField(vector, values, lexicalQueryFeatureValuesWeight)
	return vector
}

func weightedLexicalDocumentVector(document ConceptRetrievalDocument) lexicalVector {
	vector := make(lexicalVector)
	addWeightedLexicalField(vector, document.Target, lexicalDocumentTargetWeight)
	addWeightedLexicalField(vector, document.PedagogicalIntent, lexicalDocumentIntentWeight)
	addWeightedLexicalField(vector, document.Scope, lexicalDocumentScopeWeight)
	keys, values := sortedLexicalFeatureFields(document.IdentityFeatures)
	addWeightedLexicalField(vector, keys, lexicalDocumentFeatureKeysWeight)
	addWeightedLexicalField(vector, values, lexicalDocumentFeatureValuesWeight)
	return vector
}

func addWeightedLexicalField(vector lexicalVector, value string, weight float64) {
	seen := make(map[string]struct{})
	for _, token := range NormalizeConceptLexicalTokens(value) {
		if _, duplicate := seen[token]; duplicate {
			continue
		}
		seen[token] = struct{}{}
		vector[token] += weight
	}
}

func sortedLexicalFeatureFields(features map[string]string) (string, string) {
	keys := make([]string, 0, len(features))
	for key := range features {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	values := make([]string, 0, len(keys))
	for _, key := range keys {
		values = append(values, features[key])
	}
	return strings.Join(keys, " "), strings.Join(values, " ")
}

func lexicalCosineSimilarity(query, document lexicalVector) float64 {
	if len(query) == 0 || len(document) == 0 {
		return 0
	}
	queryTokens := sortedLexicalVectorTokens(query)
	documentTokens := sortedLexicalVectorTokens(document)
	var dot, queryNormSquared, documentNormSquared float64
	for _, token := range queryTokens {
		weight := query[token]
		queryNormSquared += weight * weight
		dot += weight * document[token]
	}
	for _, token := range documentTokens {
		weight := document[token]
		documentNormSquared += weight * weight
	}
	if queryNormSquared == 0 || documentNormSquared == 0 {
		return 0
	}
	score := dot / (math.Sqrt(queryNormSquared) * math.Sqrt(documentNormSquared))
	if math.IsNaN(score) || math.IsInf(score, 0) || score <= 0 {
		return 0
	}
	if score > 1 {
		return 1
	}
	return score
}

func sortedLexicalVectorTokens(vector lexicalVector) []string {
	tokens := make([]string, 0, len(vector))
	for token := range vector {
		tokens = append(tokens, token)
	}
	sort.Strings(tokens)
	return tokens
}

func matchedLexicalTokens(query, document lexicalVector) []string {
	matched := make([]string, 0)
	for _, token := range sortedLexicalVectorTokens(query) {
		if document[token] > 0 {
			matched = append(matched, token)
		}
	}
	return matched
}

func lexicalRetrievalEvidence(matched []string) string {
	evidence := struct {
		Reason        string   `json:"reason"`
		Normalization string   `json:"normalization"`
		MatchedTokens []string `json:"matched_tokens"`
	}{
		Reason: "weighted_lexical_cosine", Normalization: ConceptLexicalNormalizationV1,
		MatchedTokens: matched,
	}
	encoded, err := json.Marshal(evidence)
	if err != nil {
		return `{"reason":"weighted_lexical_cosine","normalization":"concept_lexical_normalization_v1","matched_tokens":[]}`
	}
	return string(encoded)
}
