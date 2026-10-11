package http

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"time"

	"french-learning-app/internal/application"
)

// KnowledgeLibrarySemanticSearchSchemaVersion names the FLH-040 response.
const KnowledgeLibrarySemanticSearchSchemaVersion = "knowledge_library_semantic_search_v1"

// SemanticSearchService answers semantic Knowledge Library queries. It is
// read-only: it embeds the query, reads stored vectors and re-reads SQLite.
type SemanticSearchService interface {
	Search(ctx context.Context, q application.LibrarySearchQuery) (*application.SemanticSearchReport, error)
}

// WithSemanticSearch wires GET /knowledge-library/semantic-search. Without it
// the route answers 503: semantic search is optional and never falls back to
// keyword search.
func WithSemanticSearch(service SemanticSearchService) HandlerOption {
	return func(handler *Handler) { handler.semantic = service }
}

type semanticIndexResponse struct {
	Collection     string  `json:"collection"`
	Representation string  `json:"representation"`
	ModelID        string  `json:"model_id"`
	Dimensions     int     `json:"dimensions"`
	State          string  `json:"state"`
	Complete       bool    `json:"complete"`
	UpdatedAt      string  `json:"updated_at"`
	CompletedAt    *string `json:"completed_at"`
	LastError      string  `json:"last_error"`
}

type semanticSearchResultResponse struct {
	Concept             conceptResponse `json:"concept"`
	Similarity          float64         `json:"similarity"`
	CurrentMemberCount  int             `json:"current_member_count"`
	SupportingUnitCount int             `json:"supporting_unit_count"`
}

type semanticSkippedResponse struct {
	Missing      int `json:"missing"`
	Stale        int `json:"stale"`
	Incompatible int `json:"incompatible"`
	NonPositive  int `json:"non_positive"`
}

type semanticSearchResponse struct {
	SchemaVersion   string                         `json:"schema_version"`
	Query           string                         `json:"query"`
	QueryForm       string                         `json:"query_representation"`
	State           string                         `json:"state"`
	Limit           int                            `json:"limit"`
	Index           semanticIndexResponse          `json:"index"`
	Considered      int                            `json:"considered"`
	Skipped         semanticSkippedResponse        `json:"skipped"`
	FilteredByState int                            `json:"filtered_by_state"`
	ScoreNote       string                         `json:"score_note"`
	Results         []semanticSearchResultResponse `json:"results"`
}

func (h *Handler) handleSemanticSearch(w http.ResponseWriter, r *http.Request) {
	if h.semantic == nil {
		writeError(w, http.StatusServiceUnavailable, "semantic search is not configured")
		return
	}
	values := r.URL.Query()
	var limit *int
	if raw := values.Get("limit"); raw != "" {
		n, err := strconv.Atoi(raw)
		if err != nil {
			writeError(w, http.StatusBadRequest, "limit must be an integer")
			return
		}
		limit = &n
	}
	state := values.Get("state")
	q, err := application.ParseLibrarySearchQuery(values.Get("q"), state, limit)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	report, err := h.semantic.Search(r.Context(), q)
	if err != nil {
		writeSemanticError(w, err)
		return
	}
	if state == "" {
		state = "all"
	}
	idx := report.Index
	resp := semanticSearchResponse{
		SchemaVersion: KnowledgeLibrarySemanticSearchSchemaVersion,
		Query:         report.Query,
		QueryForm:     application.ConceptSearchQueryRepresentationV1,
		State:         state,
		Limit:         report.Limit,
		Index: semanticIndexResponse{
			Collection: idx.Collection, Representation: idx.Representation, ModelID: idx.ModelID, Dimensions: idx.Dimensions,
			State: idx.State, Complete: report.IndexComplete, UpdatedAt: idx.UpdatedAt.Format(time.RFC3339Nano), LastError: idx.LastError,
		},
		Considered: report.Considered,
		Skipped: semanticSkippedResponse{
			Missing: report.SkippedMissing, Stale: report.SkippedStale, Incompatible: report.SkippedIncompatible, NonPositive: report.SkippedNonPositive,
		},
		FilteredByState: report.FilteredByState,
		ScoreNote:       "cosine similarity between query and concept-document embeddings; not a probability and not a SAME judgment",
		Results:         make([]semanticSearchResultResponse, 0, len(report.Results)),
	}
	if idx.CompletedAt != nil {
		ts := idx.CompletedAt.Format(time.RFC3339Nano)
		resp.Index.CompletedAt = &ts
	}
	for _, res := range report.Results {
		resp.Results = append(resp.Results, semanticSearchResultResponse{
			Concept: toConceptResponse(res.Concept), Similarity: res.Similarity,
			CurrentMemberCount: res.CurrentMemberCount, SupportingUnitCount: res.SupportingUnitCount,
		})
	}
	writeJSON(w, http.StatusOK, resp)
}

// writeSemanticError maps categories only; provider and vector-store details,
// keys and learning content never reach the response.
func writeSemanticError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, application.ErrKnowledgeLibraryQuery):
		writeError(w, http.StatusBadRequest, err.Error())
	case errors.Is(err, application.ErrSemanticSearchDisabled):
		writeError(w, http.StatusServiceUnavailable, "semantic search is not configured")
	case errors.Is(err, application.ErrSemanticIndexNotBuilt):
		writeError(w, http.StatusConflict, "semantic index has not been built for the configured model; run semantic-index build or rebuild")
	case errors.Is(err, application.ErrSemanticIndexIncompatible):
		writeError(w, http.StatusConflict, "semantic index is incompatible with the configured model; run semantic-index rebuild")
	case errors.Is(err, application.ErrEmbeddingProviderTimeout):
		writeError(w, http.StatusGatewayTimeout, "embedding provider timeout")
	case errors.Is(err, application.ErrEmbeddingProviderUnavailable):
		writeError(w, http.StatusBadGateway, "embedding provider unavailable")
	case errors.Is(err, application.ErrVectorIndexTimeout):
		writeError(w, http.StatusGatewayTimeout, "vector index timeout")
	case errors.Is(err, application.ErrVectorIndexUnavailable):
		writeError(w, http.StatusBadGateway, "vector index unavailable")
	default:
		writeError(w, http.StatusInternalServerError, "could not run semantic search")
	}
}
