package http

import (
	"context"
	"net/http"
	"strconv"

	"french-learning-app/internal/application"
)

// KnowledgeLibraryHybridSearchSchemaVersion names the FLH-071 hybrid response.
const KnowledgeLibraryHybridSearchSchemaVersion = "knowledge_library_hybrid_search_v1"

// HybridSearchService fuses the existing keyword and semantic searches. It is
// read-only and needs semantic search: without it the route answers 503.
type HybridSearchService interface {
	Search(ctx context.Context, q application.HybridSearchQuery) (*application.HybridSearchReport, error)
}

// WithHybridSearch wires GET /knowledge-library/hybrid-search. It is wired only
// when semantic search is configured; hybrid never runs keyword search alone.
func WithHybridSearch(service HybridSearchService) HandlerOption {
	return func(handler *Handler) { handler.hybrid = service }
}

const hybridKeywordMatching = "keyword component: concept_lexical_normalization_v1 tokens; every query token must be the " +
	"prefix of a token in the Concept identity (tier identity) or in identity plus CURRENT SAME member wording (tier " +
	"unit_evidence). Its rank is the keyword order (tier, then active/orphaned/retired, then target, then id), not a " +
	"relevance score, and it has no numeric score"

type hybridPolicyResponse struct {
	Version  string             `json:"version"`
	RRFK     int                `json:"rrf_k"`
	Weights  map[string]float64 `json:"weights"`
	TieBreak string             `json:"tie_break"`
}

type hybridKeywordComponentResponse struct {
	Returned         int    `json:"returned"`
	TotalMatches     int    `json:"total_matches"`
	TruncatedAtDepth bool   `json:"truncated_at_depth"`
	Matching         string `json:"matching"`
}

type hybridSemanticComponentResponse struct {
	Returned            int                     `json:"returned"`
	Considered          int                     `json:"considered"`
	Skipped             semanticSkippedResponse `json:"skipped"`
	FilteredByState     int                     `json:"filtered_by_state"`
	QueryRepresentation string                  `json:"query_representation"`
	Index               semanticIndexResponse   `json:"index"`
	ScoreNote           string                  `json:"score_note"`
}

type hybridComponentsResponse struct {
	Keyword  hybridKeywordComponentResponse  `json:"keyword"`
	Semantic hybridSemanticComponentResponse `json:"semantic"`
}

type hybridDroppedResponse struct {
	Missing               int `json:"missing"`
	FilteredByState       int `json:"filtered_by_state"`
	ChangedDuringSearch   int `json:"changed_during_search"`
	DuplicateComponentIDs int `json:"duplicate_component_ids"`
}

type hybridKeywordEvidenceResponse struct {
	Rank          int      `json:"rank"`
	MatchTier     string   `json:"match_tier"`
	MatchedFields []string `json:"matched_fields"`
}

type hybridSemanticEvidenceResponse struct {
	Rank       int     `json:"rank"`
	Similarity float64 `json:"similarity"`
}

type hybridSearchResultResponse struct {
	Concept             conceptResponse                 `json:"concept"`
	FusedScore          float64                         `json:"fused_score"`
	Sources             []string                        `json:"sources"`
	Keyword             *hybridKeywordEvidenceResponse  `json:"keyword"`
	Semantic            *hybridSemanticEvidenceResponse `json:"semantic"`
	CurrentMemberCount  int                             `json:"current_member_count"`
	SupportingUnitCount int                             `json:"supporting_unit_count"`
}

type hybridSearchResponse struct {
	SchemaVersion   string                       `json:"schema_version"`
	Query           string                       `json:"query"`
	State           string                       `json:"state"`
	Limit           int                          `json:"limit"`
	Depth           int                          `json:"depth"`
	Policy          hybridPolicyResponse         `json:"policy"`
	ScoreNote       string                       `json:"score_note"`
	Components      hybridComponentsResponse     `json:"components"`
	TotalCandidates int                          `json:"total_candidates"`
	Truncated       bool                         `json:"truncated"`
	Dropped         hybridDroppedResponse        `json:"dropped_after_fusion"`
	Results         []hybridSearchResultResponse `json:"results"`
}

func optionalInt(raw, name string) (*int, string) {
	if raw == "" {
		return nil, ""
	}
	n, err := strconv.Atoi(raw)
	if err != nil {
		return nil, name + " must be an integer"
	}
	return &n, ""
}

// handleHybridSearch: 200; 400 invalid query; 503 semantic search not
// configured; otherwise the semantic search status codes. No keyword fallback.
func (h *Handler) handleHybridSearch(w http.ResponseWriter, r *http.Request) {
	if h.hybrid == nil {
		writeError(w, http.StatusServiceUnavailable, "hybrid search needs semantic search, which is not configured")
		return
	}
	values := r.URL.Query()
	limit, msg := optionalInt(values.Get("limit"), "limit")
	if msg != "" {
		writeError(w, http.StatusBadRequest, msg)
		return
	}
	depth, msg := optionalInt(values.Get("depth"), "depth")
	if msg != "" {
		writeError(w, http.StatusBadRequest, msg)
		return
	}
	state := values.Get("state")
	q, err := application.ParseHybridSearchQuery(values.Get("q"), state, limit, depth)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	report, err := h.hybrid.Search(r.Context(), q)
	if err != nil {
		writeSemanticError(w, err)
		return
	}
	if report.Semantic == nil || report.Keyword == nil || report.Semantic.QueryRepresentation == "" {
		// Both components must have run; never present a one-sided result as hybrid.
		writeError(w, http.StatusInternalServerError, "could not run hybrid search")
		return
	}
	if state == "" {
		state = "all"
	}
	sem, kw := report.Semantic, report.Keyword
	resp := hybridSearchResponse{
		SchemaVersion: KnowledgeLibraryHybridSearchSchemaVersion,
		Query:         report.Query, State: state, Limit: report.Limit, Depth: report.Depth,
		Policy: hybridPolicyResponse{Version: application.HybridSearchPolicyVersion, RRFK: application.HybridRRFK,
			Weights:  map[string]float64{"keyword": application.HybridKeywordWeight, "semantic": application.HybridSemanticWeight},
			TieBreak: "concept_id_ascending"},
		ScoreNote: "fused_score is a reciprocal-rank-fusion sum of 1/(rrf_k + rank) over the components that ranked the " +
			"concept; it is not a probability or a relevance estimate and is comparable only within this response",
		Components: hybridComponentsResponse{
			Keyword: hybridKeywordComponentResponse{Returned: len(kw.Results), TotalMatches: kw.TotalMatches,
				TruncatedAtDepth: kw.Truncated, Matching: hybridKeywordMatching},
			Semantic: hybridSemanticComponentResponse{Returned: len(sem.Results), Considered: sem.Considered,
				Skipped: toSemanticSkipped(sem), FilteredByState: sem.FilteredByState,
				QueryRepresentation: sem.QueryRepresentation, Index: toSemanticIndexResponse(sem),
				ScoreNote: "similarity is cosine similarity between query and concept-document embeddings; not a probability and not a SAME judgment"},
		},
		TotalCandidates: report.TotalCandidates, Truncated: report.Truncated,
		Dropped: hybridDroppedResponse{Missing: report.Dropped.Missing, FilteredByState: report.Dropped.FilteredByState,
			ChangedDuringSearch: report.Dropped.ChangedDuringSearch, DuplicateComponentIDs: report.Dropped.DuplicateComponentIDs},
		Results: make([]hybridSearchResultResponse, 0, len(report.Results)),
	}
	for _, res := range report.Results {
		out := hybridSearchResultResponse{Concept: toConceptResponse(res.Concept), FusedScore: res.FusedScore, Sources: res.Sources(),
			CurrentMemberCount: res.CurrentMemberCount, SupportingUnitCount: res.SupportingUnitCount}
		if res.Keyword != nil {
			fields := res.Keyword.MatchedFields
			if fields == nil {
				fields = []string{}
			}
			out.Keyword = &hybridKeywordEvidenceResponse{Rank: res.Keyword.Rank, MatchTier: res.Keyword.MatchTier, MatchedFields: fields}
		}
		if res.Semantic != nil {
			out.Semantic = &hybridSemanticEvidenceResponse{Rank: res.Semantic.Rank, Similarity: res.Semantic.Similarity}
		}
		resp.Results = append(resp.Results, out)
	}
	writeJSON(w, http.StatusOK, resp)
}
