package application

import (
	"context"
	"fmt"
	"sort"

	"french-learning-app/internal/domain"
)

// Hybrid Knowledge Library search (FLH-071) fuses the ranked candidates of the
// existing keyword search and the existing semantic search by Concept ID with
// reciprocal rank fusion. It is an explicit third mode: keyword and semantic
// search keep their own routes, behaviour and defaults. It is not a resolver,
// reranker or learned model, and it never falls back to one component.
const (
	HybridSearchPolicyVersion = "concept_hybrid_rrf_v1"
	// HybridRRFK is the fixed reciprocal-rank-fusion constant (not tuned).
	HybridRRFK = 60
	// HybridKeywordWeight and HybridSemanticWeight are fixed and equal.
	HybridKeywordWeight  = 1.0
	HybridSemanticWeight = 1.0

	// HybridDefaultDepth is how many ranked candidates each component
	// contributes before fusion; HybridMaxDepth is the strict cap. The
	// displayed limit is separate and never exceeds the depth.
	HybridDefaultDepth = 50
	HybridMaxDepth     = KnowledgeLibraryMaxLimit
)

// HybridSearchQuery is one validated hybrid request.
type HybridSearchQuery struct {
	Text  string
	State *domain.ConceptState
	Limit int
	Depth int
}

// ParseHybridSearchQuery validates raw request values. q, state and limit
// follow the keyword rules; q is required and depth is limit..HybridMaxDepth.
func ParseHybridSearchQuery(text, state string, limit, depth *int) (HybridSearchQuery, error) {
	base, err := ParseLibrarySearchQuery(text, state, limit)
	if err != nil {
		return HybridSearchQuery{}, err
	}
	q := HybridSearchQuery{Text: base.Text, State: base.State, Limit: base.Limit, Depth: HybridDefaultDepth}
	if q.Text == "" {
		return q, fmt.Errorf("%w: hybrid search needs a non-empty q", ErrKnowledgeLibraryQuery)
	}
	if depth != nil {
		q.Depth = *depth
	}
	if q.Depth < 1 || q.Depth > HybridMaxDepth {
		return q, fmt.Errorf("%w: depth must be between 1 and %d", ErrKnowledgeLibraryQuery, HybridMaxDepth)
	}
	if q.Depth < q.Limit {
		return q, fmt.Errorf("%w: depth (%d) must be at least limit (%d)", ErrKnowledgeLibraryQuery, q.Depth, q.Limit)
	}
	return q, nil
}

// KeywordConceptSearcher is the existing keyword search (read-only).
type KeywordConceptSearcher interface {
	Search(ctx context.Context, q LibrarySearchQuery) (*LibrarySearchReport, error)
}

// SemanticConceptSearcher is the existing semantic search (read-only).
type SemanticConceptSearcher interface {
	Search(ctx context.Context, q LibrarySearchQuery) (*SemanticSearchReport, error)
}

// HybridConceptLister re-reads current Concept authority after both components.
type HybridConceptLister interface {
	ListConcepts(ctx context.Context, state *domain.ConceptState) ([]domain.KnowledgeConcept, error)
}

// HybridKeywordEvidence is a Concept's place in the keyword candidates. The
// keyword path has no numeric score: its rank is tier, state, target, id order.
type HybridKeywordEvidence struct {
	Rank          int
	MatchTier     string
	MatchedFields []string
}

// HybridSemanticEvidence is a Concept's place in the semantic candidates.
type HybridSemanticEvidence struct {
	Rank       int
	Similarity float64
}

// HybridSearchResult is one fused Concept with the evidence it was ranked on.
// FusedScore is a reciprocal-rank-fusion sum: not a probability, not a
// relevance estimate, and only comparable within one response.
type HybridSearchResult struct {
	Concept             domain.KnowledgeConcept
	FusedScore          float64
	Keyword             *HybridKeywordEvidence
	Semantic            *HybridSemanticEvidence
	CurrentMemberCount  int
	SupportingUnitCount int
}

// Sources lists the components that ranked this Concept, keyword first.
func (r HybridSearchResult) Sources() []string {
	out := []string{}
	if r.Keyword != nil {
		out = append(out, "keyword")
	}
	if r.Semantic != nil {
		out = append(out, "semantic")
	}
	return out
}

// HybridDropped counts fused candidates removed by the final authority re-check
// (never replaced by other candidates) and ignored duplicate component ids.
type HybridDropped struct {
	Missing               int
	FilteredByState       int
	ChangedDuringSearch   int
	DuplicateComponentIDs int
}

// HybridSearchReport is one bounded hybrid page with both component reports.
type HybridSearchReport struct {
	Query           string
	State           *domain.ConceptState
	Limit           int
	Depth           int
	Keyword         *LibrarySearchReport
	Semantic        *SemanticSearchReport
	TotalCandidates int
	Truncated       bool
	Dropped         HybridDropped
	Results         []HybridSearchResult
}

// HybridSearchService composes the two existing searches. Every dependency is
// read-only; nothing is recorded, embedded for documents or indexed.
type HybridSearchService struct {
	keyword    KeywordConceptSearcher
	semantic   SemanticConceptSearcher
	concepts   HybridConceptLister
	summarizer ConceptSummarizer
}

func NewHybridSearchService(keyword KeywordConceptSearcher, semantic SemanticConceptSearcher, concepts HybridConceptLister, summarizer ConceptSummarizer) *HybridSearchService {
	return &HybridSearchService{keyword: keyword, semantic: semantic, concepts: concepts, summarizer: summarizer}
}

type hybridCandidate struct {
	keyword  *HybridKeywordEvidence
	semantic *HybridSemanticEvidence
	// snapshots are the Concept versions the components ranked.
	snapshots []domain.KnowledgeConcept
}

// FuseReciprocalRank returns Σ w_i/(k + rank_i) over the given 1-based ranks
// (0 means "absent from that component").
func FuseReciprocalRank(keywordRank, semanticRank int) float64 {
	score := 0.0
	if keywordRank > 0 {
		score += HybridKeywordWeight / float64(HybridRRFK+keywordRank)
	}
	if semanticRank > 0 {
		score += HybridSemanticWeight / float64(HybridRRFK+semanticRank)
	}
	return score
}

// Search runs keyword first (local; an invalid query costs no provider call),
// then semantic once, fuses by Concept ID, and re-checks the fused Concepts
// against current authority. Any component error fails the whole search.
func (s *HybridSearchService) Search(ctx context.Context, q HybridSearchQuery) (*HybridSearchReport, error) {
	if q.Text == "" {
		return nil, fmt.Errorf("%w: hybrid search needs a non-empty q", ErrKnowledgeLibraryQuery)
	}
	if q.Depth < q.Limit || q.Depth < 1 || q.Depth > HybridMaxDepth || q.Limit < 1 {
		return nil, fmt.Errorf("%w: need 1 <= limit <= depth <= %d", ErrKnowledgeLibraryQuery, HybridMaxDepth)
	}
	component := LibrarySearchQuery{Text: q.Text, State: q.State, Limit: q.Depth}
	kw, err := s.keyword.Search(ctx, component)
	if err != nil {
		return nil, err
	}
	sem, err := s.semantic.Search(ctx, component)
	if err != nil {
		return nil, err
	}

	report := &HybridSearchReport{Query: q.Text, State: q.State, Limit: q.Limit, Depth: q.Depth, Keyword: kw, Semantic: sem,
		Results: []HybridSearchResult{}}
	byID := map[int64]*hybridCandidate{}
	var order []int64
	get := func(id int64) *hybridCandidate {
		c, ok := byID[id]
		if !ok {
			c = &hybridCandidate{}
			byID[id] = c
			order = append(order, id)
		}
		return c
	}
	for i, r := range kw.Results {
		if i >= q.Depth {
			break
		}
		c := get(r.Concept.ID)
		if c.keyword != nil {
			report.Dropped.DuplicateComponentIDs++
			continue
		}
		fields := append([]string{}, r.MatchedFields...)
		c.keyword = &HybridKeywordEvidence{Rank: i + 1, MatchTier: r.MatchTier, MatchedFields: fields}
		c.snapshots = append(c.snapshots, r.Concept)
	}
	for i, r := range sem.Results {
		if i >= q.Depth {
			break
		}
		c := get(r.Concept.ID)
		if c.semantic != nil {
			report.Dropped.DuplicateComponentIDs++
			continue
		}
		c.semantic = &HybridSemanticEvidence{Rank: i + 1, Similarity: r.Similarity}
		c.snapshots = append(c.snapshots, r.Concept)
	}

	// One authoritative re-read after both components.
	current, err := s.concepts.ListConcepts(ctx, nil)
	if err != nil {
		return nil, err
	}
	now := make(map[int64]domain.KnowledgeConcept, len(current))
	for _, c := range current {
		now[c.ID] = c
	}
	for _, id := range order {
		cand := byID[id]
		c, ok := now[id]
		if !ok {
			report.Dropped.Missing++
			continue
		}
		if q.State != nil && c.State != *q.State {
			report.Dropped.FilteredByState++
			continue
		}
		changed, err := changedSince(c, cand.snapshots)
		if err != nil {
			return nil, err
		}
		if changed {
			report.Dropped.ChangedDuringSearch++
			continue
		}
		kr, sr := 0, 0
		if cand.keyword != nil {
			kr = cand.keyword.Rank
		}
		if cand.semantic != nil {
			sr = cand.semantic.Rank
		}
		report.Results = append(report.Results, HybridSearchResult{Concept: c, FusedScore: FuseReciprocalRank(kr, sr),
			Keyword: cand.keyword, Semantic: cand.semantic})
	}
	sort.SliceStable(report.Results, func(i, j int) bool {
		a, b := report.Results[i], report.Results[j]
		if a.FusedScore != b.FusedScore {
			return a.FusedScore > b.FusedScore
		}
		return a.Concept.ID < b.Concept.ID
	})
	report.TotalCandidates = len(report.Results)
	if len(report.Results) > q.Limit {
		report.Results = report.Results[:q.Limit]
		report.Truncated = true
	}
	for i := range report.Results {
		members, supporting, err := s.summarizer.ConceptCounts(ctx, report.Results[i].Concept.ID)
		if err != nil {
			return nil, err
		}
		report.Results[i].CurrentMemberCount, report.Results[i].SupportingUnitCount = members, supporting
	}
	return report, nil
}

// changedSince reports whether the current Concept's identity fields or state
// differ from any version a component ranked.
func changedSince(current domain.KnowledgeConcept, snapshots []domain.KnowledgeConcept) (bool, error) {
	doc, err := BuildSemanticIndexDocument(current)
	if err != nil {
		return false, err
	}
	for _, s := range snapshots {
		d, err := BuildSemanticIndexDocument(s)
		if err != nil {
			return false, err
		}
		if d.ContentHash != doc.ContentHash || s.State != current.State {
			return true, nil
		}
	}
	return false, nil
}
