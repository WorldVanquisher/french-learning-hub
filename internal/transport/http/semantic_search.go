package http

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"time"

	"french-learning-app/internal/application"
)

// KnowledgeLibrarySemanticSearchSchemaVersion names the response. v2 (FLH-042)
// replaced v1's index.complete flag, which repeated stored run state as if it
// were verified completeness, with explicit publication and last-run history.
const KnowledgeLibrarySemanticSearchSchemaVersion = "knowledge_library_semantic_search_v2"

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

// semanticIndexResponse reports recorded history only. health_verified is
// always false: search does not verify the index (semantic-index status does).
type semanticIndexResponse struct {
	Space             string  `json:"space"`
	Collection        string  `json:"collection"` // physical collection queried
	Representation    string  `json:"representation"`
	ModelID           string  `json:"model_id"`
	Dimensions        int     `json:"dimensions"`
	PublishedRunID    string  `json:"published_run_id"`
	PublishedAt       *string `json:"published_at"`
	LastRunOperation  string  `json:"last_run_operation"`
	LastRunOutcome    string  `json:"last_run_outcome"`
	LastRunFinishedAt *string `json:"last_run_finished_at"`
	LastError         string  `json:"last_error"`
	HealthVerified    bool    `json:"health_verified"`
	Note              string  `json:"note"`
}

func optTime(t *time.Time) *string {
	if t == nil {
		return nil
	}
	s := t.Format(time.RFC3339Nano)
	return &s
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
	pub := report.Publication
	resp := semanticSearchResponse{
		SchemaVersion: KnowledgeLibrarySemanticSearchSchemaVersion,
		Query:         report.Query,
		QueryForm:     application.ConceptSearchQueryRepresentationV1,
		State:         state,
		Limit:         report.Limit,
		Index: semanticIndexResponse{
			Space: report.Space.Collection, Collection: report.Collection, Representation: report.Space.Representation,
			ModelID: report.Space.ModelID, Dimensions: report.Space.Dimensions,
			PublishedRunID: pub.PublishedRunID, PublishedAt: optTime(pub.PublishedAt),
			LastRunOperation: pub.LastRunOperation, LastRunOutcome: pub.LastRunOutcome,
			LastRunFinishedAt: optTime(pub.LastRunFinishedAt), LastError: pub.LastError,
			HealthVerified: false,
			Note:           "publication and last-run fields are recorded history, not verified for this request; every returned hit was re-checked against the database",
		},
		Considered: report.Considered,
		Skipped: semanticSkippedResponse{
			Missing: report.SkippedMissing, Stale: report.SkippedStale, Incompatible: report.SkippedIncompatible, NonPositive: report.SkippedNonPositive,
		},
		FilteredByState: report.FilteredByState,
		ScoreNote:       "cosine similarity between query and concept-document embeddings; not a probability and not a SAME judgment",
		Results:         make([]semanticSearchResultResponse, 0, len(report.Results)),
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
