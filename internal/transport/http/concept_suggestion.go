package http

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// ConceptSuggestionService is the FLH-097 advisory suggestion workflow.
type ConceptSuggestionService interface {
	Enabled() bool
	Generator() string
	Generate(ctx context.Context, operationID string, unitIDs []int64) (*domain.ConceptSuggestionRun, bool, error)
	Confirm(ctx context.Context, itemID, conceptID int64) (*domain.ConceptSuggestionItem, *domain.UnitConceptLink, bool, error)
	GetRun(ctx context.Context, id int64) (*domain.ConceptSuggestionRun, error)
	GetRunByOperation(ctx context.Context, operationID string) (*domain.ConceptSuggestionRun, error)
	ListRuns(ctx context.Context, limit int) ([]domain.ConceptSuggestionRun, error)
}

// WithConceptSuggestions wires the suggestion endpoints. Without it they
// report 503 like a disabled suggester.
func WithConceptSuggestions(service ConceptSuggestionService) HandlerOption {
	return func(handler *Handler) { handler.suggestions = service }
}

func (h *Handler) registerConceptSuggestionRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /concept-suggestion-runs", h.handleListSuggestionRuns)
	mux.HandleFunc("POST /concept-suggestion-runs", h.handleCreateSuggestionRun)
	mux.HandleFunc("GET /concept-suggestion-runs/{id}", h.handleGetSuggestionRun)
	mux.HandleFunc("GET /concept-suggestion-runs/operations/{operation_id}", h.handleGetSuggestionRunByOperation)
	mux.HandleFunc("POST /concept-suggestion-items/{id}/confirm", h.handleConfirmSuggestion)
}

// ---- DTOs ----

type suggestionCandidateResponse struct {
	ConceptID int64  `json:"concept_id"`
	Rank      int    `json:"rank"`
	Source    string `json:"source"`
	Signature string `json:"signature"`
	Target    string `json:"target"`
}

// suggestionConfirmationResponse is historical attribution. still_current
// says whether link_id is the unit's CURRENT SAME now.
type suggestionConfirmationResponse struct {
	ID           int64  `json:"id"`
	LinkID       int64  `json:"link_id"`
	CreatedAt    string `json:"created_at"`
	StillCurrent bool   `json:"still_current"`
}

type suggestionItemResponse struct {
	ID                 int64                           `json:"id"`
	RunID              int64                           `json:"run_id"`
	Ordinal            int                             `json:"ordinal"`
	UnitID             int64                           `json:"unit_id"`
	EntryID            int64                           `json:"entry_id"`
	SourceExtractionID int64                           `json:"source_extraction_id"`
	Outcome            string                          `json:"outcome"`
	SuggestedConceptID *int64                          `json:"suggested_concept_id"`
	Reason             string                          `json:"reason"`
	Candidates         []suggestionCandidateResponse   `json:"candidates"`
	State              string                          `json:"state"`
	StaleReasons       []string                        `json:"stale_reasons"`
	CurrentConceptID   *int64                          `json:"current_concept_id"`
	Confirmation       *suggestionConfirmationResponse `json:"confirmation"`
	Unit               *reviewableUnitResponse         `json:"unit"`
	CreatedAt          string                          `json:"created_at"`
}

type suggestionRunResponse struct {
	ID              int64                    `json:"id"`
	OperationID     string                   `json:"operation_id"`
	Status          string                   `json:"status"`
	FailureCode     *string                  `json:"failure_code"`
	Generator       string                   `json:"generator"`
	CandidatePolicy string                   `json:"candidate_policy"`
	CandidateLimit  int                      `json:"candidate_limit"`
	ProviderCalled  bool                     `json:"provider_called"`
	UnitIDs         []int64                  `json:"unit_ids"`
	ItemCount       int                      `json:"item_count"`
	SuggestedCount  int                      `json:"suggested_count"`
	CreatedAt       string                   `json:"created_at"`
	Items           []suggestionItemResponse `json:"items,omitempty"`
}

func toSuggestionItemResponse(it domain.ConceptSuggestionItem) suggestionItemResponse {
	out := suggestionItemResponse{
		ID: it.ID, RunID: it.RunID, Ordinal: it.Ordinal, UnitID: it.UnitID, EntryID: it.EntryID,
		SourceExtractionID: it.SourceExtractionID, Outcome: string(it.Outcome), SuggestedConceptID: it.SuggestedConceptID,
		Reason: it.Reason, State: string(it.State), CurrentConceptID: it.CurrentConceptID,
		Candidates: []suggestionCandidateResponse{}, StaleReasons: []string{},
		CreatedAt: it.CreatedAt.Format(time.RFC3339Nano),
	}
	for _, c := range it.Candidates {
		out.Candidates = append(out.Candidates, suggestionCandidateResponse(c))
	}
	for _, r := range it.StaleReasons {
		out.StaleReasons = append(out.StaleReasons, string(r))
	}
	if it.Confirmation != nil {
		out.Confirmation = &suggestionConfirmationResponse{
			ID: it.Confirmation.ID, LinkID: it.Confirmation.LinkID, CreatedAt: it.Confirmation.CreatedAt.Format(time.RFC3339Nano),
			StillCurrent: it.Confirmation.StillCurrent,
		}
	}
	if it.Unit != nil {
		u := toReviewableUnitResponse(domain.ReviewableUnit{Unit: *it.Unit, Candidate: domain.DeriveCandidateIdentity(*it.Unit), EntryID: it.EntryID})
		out.Unit = &u
	}
	return out
}

func toSuggestionRunResponse(run *domain.ConceptSuggestionRun, withItems bool) suggestionRunResponse {
	out := suggestionRunResponse{
		ID: run.ID, OperationID: run.OperationID, Status: string(run.Status), Generator: run.Generator,
		CandidatePolicy: run.CandidatePolicy, CandidateLimit: run.CandidateLimit, ProviderCalled: run.ProviderCalled,
		UnitIDs: run.RequestUnitIDs, ItemCount: run.ItemCount, SuggestedCount: run.SuggestedCount,
		CreatedAt: run.CreatedAt.Format(time.RFC3339Nano),
	}
	if run.FailureCode != nil {
		code := string(*run.FailureCode)
		out.FailureCode = &code
	}
	if withItems {
		out.Items = []suggestionItemResponse{}
		for _, it := range run.Items {
			out.Items = append(out.Items, toSuggestionItemResponse(it))
		}
	}
	return out
}

func suggestionLimits() map[string]int {
	return map[string]int{
		"max_units":              domain.MaxSuggestionUnits,
		"candidates_per_unit":    domain.SuggestionCandidatesPerUnit,
		"member_examples":        domain.SuggestionMemberExamples,
		"max_unit_text_chars":    domain.MaxSuggestionUnitTextChars,
		"max_concept_text_chars": domain.MaxSuggestionConceptTextChars,
		"max_reason_chars":       domain.MaxSuggestionReasonChars,
	}
}

// ---- handlers ----

// handleListSuggestionRuns reports whether suggestions are enabled, the fixed
// limits and the recent runs (newest first, no items). Read-only.
func (h *Handler) handleListSuggestionRuns(w http.ResponseWriter, r *http.Request) {
	if h.suggestions == nil {
		writeError(w, http.StatusServiceUnavailable, "concept suggestions are not enabled")
		return
	}
	limit := 0
	if v := r.URL.Query().Get("limit"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n <= 0 {
			writeError(w, http.StatusBadRequest, "limit must be a positive integer")
			return
		}
		limit = n
	}
	runs, err := h.suggestions.ListRuns(r.Context(), limit)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list suggestion runs")
		return
	}
	out := make([]suggestionRunResponse, 0, len(runs))
	for i := range runs {
		out = append(out, toSuggestionRunResponse(&runs[i], false))
	}
	var generator *string
	if g := h.suggestions.Generator(); g != "" {
		generator = &g
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"enabled":          h.suggestions.Enabled(),
		"generator":        generator,
		"candidate_policy": domain.ConceptSuggestionCandidatePolicy,
		"limits":           suggestionLimits(),
		"runs":             out,
	})
}

type createSuggestionRunRequest struct {
	UnitIDs []int64 `json:"unit_ids"`
}

// handleCreateSuggestionRun is the only call that contacts the provider. It
// requires a UUID Idempotency-Key. Status: 201 (new, or replay with header
// Idempotency-Replayed: true), 400 missing/invalid key or JSON, 409 key used for
// different unit_ids or still in progress, 422 invalid or oversized input or a
// unit that is not reviewable, 503 disabled, 502/504 provider or output
// failure (the failed run is stored and returned), 500 storage failure.
func (h *Handler) handleCreateSuggestionRun(w http.ResponseWriter, r *http.Request) {
	if h.suggestions == nil {
		writeError(w, http.StatusServiceUnavailable, "concept suggestions are not enabled")
		return
	}
	keys := r.Header.Values("Idempotency-Key")
	if len(keys) != 1 {
		writeError(w, http.StatusBadRequest, "exactly one Idempotency-Key header is required")
		return
	}
	if _, err := domain.NormalizeAnnotationOperationID(keys[0]); err != nil {
		writeError(w, http.StatusBadRequest, "invalid idempotency key")
		return
	}
	var req createSuggestionRunRequest
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	var extra any
	if err := dec.Decode(&extra); err != io.EOF {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	run, replay, err := h.suggestions.Generate(r.Context(), keys[0], req.UnitIDs)
	var genErr *application.GenerationError
	switch {
	case errors.As(err, &genErr):
		status, msg := http.StatusBadGateway, "suggestion provider unavailable"
		if errors.Is(err, domain.ErrProviderTimeout) {
			status, msg = http.StatusGatewayTimeout, "suggestion provider timed out"
		} else if errors.Is(err, domain.ErrValidation) {
			msg = "suggestion provider returned invalid output"
		}
		writeJSON(w, status, map[string]any{"error": msg, "run": toSuggestionRunResponse(genErr.Run, true)})
		return
	case errors.Is(err, domain.ErrSuggesterDisabled):
		writeError(w, http.StatusServiceUnavailable, "concept suggestions are not enabled")
		return
	case errors.Is(err, domain.ErrSuggestionKeyConflict), errors.Is(err, domain.ErrSuggestionInProgress):
		writeError(w, http.StatusConflict, err.Error())
		return
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	case err != nil:
		writeError(w, http.StatusInternalServerError, "could not generate suggestions")
		return
	}
	w.Header().Set("Idempotency-Key", run.OperationID)
	if replay {
		w.Header().Set("Idempotency-Replayed", "true")
	}
	writeJSON(w, http.StatusCreated, toSuggestionRunResponse(run, true))
}

// handleGetSuggestionRun returns one run with items and derived states.
func (h *Handler) handleGetSuggestionRun(w http.ResponseWriter, r *http.Request) {
	if h.suggestions == nil {
		writeError(w, http.StatusServiceUnavailable, "concept suggestions are not enabled")
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	run, err := h.suggestions.GetRun(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "suggestion run not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not read suggestion run")
		return
	}
	writeJSON(w, http.StatusOK, toSuggestionRunResponse(run, true))
}

// handleGetSuggestionRunByOperation looks a run up by its Idempotency-Key. 404
// means nothing is committed under the key; it never means canceled.
func (h *Handler) handleGetSuggestionRunByOperation(w http.ResponseWriter, r *http.Request) {
	if h.suggestions == nil {
		writeError(w, http.StatusServiceUnavailable, "concept suggestions are not enabled")
		return
	}
	run, err := h.suggestions.GetRunByOperation(r.Context(), r.PathValue("operation_id"))
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusBadRequest, "invalid idempotency key")
		return
	}
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "no suggestion run is committed under this key")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not read suggestion run")
		return
	}
	writeJSON(w, http.StatusOK, toSuggestionRunResponse(run, true))
}

type confirmSuggestionRequest struct {
	ConceptID int64 `json:"concept_id"`
}

// handleConfirmSuggestion records the explicit human SAME for one suggested
// item. concept_id must equal the suggested Concept. Status: 201 (new, or
// replay of the item's earlier confirmation with Idempotency-Replayed: true),
// 400 invalid JSON/id, 404 unknown item, 409 stale (stale_reasons) or another
// membership conflict, 422 item has no suggestion or concept_id differs, 500.
func (h *Handler) handleConfirmSuggestion(w http.ResponseWriter, r *http.Request) {
	if h.suggestions == nil {
		writeError(w, http.StatusServiceUnavailable, "concept suggestions are not enabled")
		return
	}
	itemID, ok := parseID(w, r)
	if !ok {
		return
	}
	var req confirmSuggestionRequest
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	item, link, replay, err := h.suggestions.Confirm(r.Context(), itemID, req.ConceptID)
	var stale *domain.SuggestionStaleError
	switch {
	case errors.As(err, &stale):
		reasons := make([]string, len(stale.Reasons))
		for i, s := range stale.Reasons {
			reasons[i] = string(s)
		}
		writeJSON(w, http.StatusConflict, map[string]any{"error": stale.Error(), "stale_reasons": reasons})
		return
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "suggestion item not found")
		return
	case errors.Is(err, domain.ErrConceptConflict):
		writeError(w, http.StatusConflict, err.Error())
		return
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	case err != nil:
		writeError(w, http.StatusInternalServerError, "could not confirm suggestion")
		return
	}
	if replay {
		w.Header().Set("Idempotency-Replayed", "true")
	}
	writeJSON(w, http.StatusCreated, map[string]any{
		"item": toSuggestionItemResponse(*item), "link": toLinkResponse(*link), "replayed": replay,
	})
}
