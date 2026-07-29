// Package http adapts HTTP requests to the application use cases. It contains
// no business logic and no direct database access.
package http

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"time"

	"french-learning-app/internal/domain"
)

// EntryService is the subset of application behavior the handlers depend on.
type EntryService interface {
	CreateEntry(ctx context.Context, in domain.NewEntryInput) (*domain.Entry, error)
	GetEntry(ctx context.Context, id int64) (*domain.Entry, error)
	ListEntries(ctx context.Context, limit int) ([]*domain.Entry, error)
}

// AnalysisService is the subset of analysis behavior the handlers depend on.
type AnalysisService interface {
	AnalyzeEntry(ctx context.Context, entryID int64) (*domain.Analysis, error)
	ListAnalyses(ctx context.Context, entryID int64) ([]*domain.Analysis, error)
}

// FeedbackService is the subset of feedback behavior the handlers depend on.
type FeedbackService interface {
	AddFeedback(ctx context.Context, analysisID int64, in domain.NewFeedbackInput) (*domain.Feedback, error)
	ListFeedback(ctx context.Context, analysisID int64) ([]*domain.Feedback, error)
}

// Handler holds dependencies for the HTTP layer.
type Handler struct {
	svc      EntryService
	analysis AnalysisService
	feedback FeedbackService
}

// NewHandler builds a Handler over the given services.
func NewHandler(svc EntryService, analysis AnalysisService, feedback FeedbackService) *Handler {
	return &Handler{svc: svc, analysis: analysis, feedback: feedback}
}

// Routes returns the configured HTTP mux for the API.
func (h *Handler) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", h.handleHealth)
	mux.HandleFunc("POST /entries", h.handleCreateEntry)
	mux.HandleFunc("GET /entries", h.handleListEntries)
	mux.HandleFunc("GET /entries/{id}", h.handleGetEntry)
	mux.HandleFunc("POST /entries/{id}/analysis", h.handleCreateAnalysis)
	mux.HandleFunc("GET /entries/{id}/analyses", h.handleListAnalyses)
	mux.HandleFunc("POST /analyses/{id}/feedback", h.handleCreateFeedback)
	mux.HandleFunc("GET /analyses/{id}/feedback", h.handleListFeedback)
	return mux
}

// ---- request / response DTOs ----

type createEntryRequest struct {
	OriginalInput   string `json:"original_input"`
	OriginalContext string `json:"original_context"`
}

type entryResponse struct {
	ID              int64    `json:"id"`
	OriginalInput   string   `json:"original_input"`
	OriginalContext string   `json:"original_context"`
	CreatedAt       string   `json:"created_at"`
	UpdatedAt       string   `json:"updated_at"`
	Category        *string  `json:"category,omitempty"`
	Explanation     *string  `json:"explanation,omitempty"`
	Confidence      *float64 `json:"confidence,omitempty"`
}

func toResponse(e *domain.Entry) entryResponse {
	return entryResponse{
		ID:              e.ID,
		OriginalInput:   e.OriginalInput,
		OriginalContext: e.OriginalContext,
		CreatedAt:       e.CreatedAt.Format(time.RFC3339Nano),
		UpdatedAt:       e.UpdatedAt.Format(time.RFC3339Nano),
		Category:        e.Category,
		Explanation:     e.Explanation,
		Confidence:      e.Confidence,
	}
}

type analysisResponse struct {
	ID          int64   `json:"id"`
	EntryID     int64   `json:"entry_id"`
	Version     int64   `json:"version"`
	Category    string  `json:"category"`
	Explanation string  `json:"explanation"`
	Confidence  float64 `json:"confidence"`
	Uncertainty string  `json:"uncertainty"`
	Analyzer    string  `json:"analyzer"`
	CreatedAt   string  `json:"created_at"`
}

func toAnalysisResponse(a *domain.Analysis) analysisResponse {
	return analysisResponse{
		ID:          a.ID,
		EntryID:     a.EntryID,
		Version:     a.Version,
		Category:    a.Category,
		Explanation: a.Explanation,
		Confidence:  a.Confidence,
		Uncertainty: a.Uncertainty,
		Analyzer:    a.Analyzer,
		CreatedAt:   a.CreatedAt.Format(time.RFC3339Nano),
	}
}

type createFeedbackRequest struct {
	Status               string  `json:"status"`
	CorrectedCategory    *string `json:"corrected_category"`
	CorrectedExplanation *string `json:"corrected_explanation"`
	UserNote             string  `json:"user_note"`
}

type feedbackResponse struct {
	ID                   int64   `json:"id"`
	AnalysisID           int64   `json:"analysis_id"`
	Status               string  `json:"status"`
	CorrectedCategory    *string `json:"corrected_category,omitempty"`
	CorrectedExplanation *string `json:"corrected_explanation,omitempty"`
	UserNote             string  `json:"user_note"`
	CreatedAt            string  `json:"created_at"`
}

func toFeedbackResponse(f *domain.Feedback) feedbackResponse {
	return feedbackResponse{
		ID:                   f.ID,
		AnalysisID:           f.AnalysisID,
		Status:               string(f.Status),
		CorrectedCategory:    f.CorrectedCategory,
		CorrectedExplanation: f.CorrectedExplanation,
		UserNote:             f.UserNote,
		CreatedAt:            f.CreatedAt.Format(time.RFC3339Nano),
	}
}

// ---- handlers ----

func (h *Handler) handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (h *Handler) handleCreateEntry(w http.ResponseWriter, r *http.Request) {
	var req createEntryRequest
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	entry, err := h.svc.CreateEntry(r.Context(), domain.NewEntryInput{
		OriginalInput:   req.OriginalInput,
		OriginalContext: req.OriginalContext,
	})
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not create entry")
		return
	}
	writeJSON(w, http.StatusCreated, toResponse(entry))
}

func (h *Handler) handleGetEntry(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	entry, err := h.svc.GetEntry(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "entry not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not fetch entry")
		return
	}
	writeJSON(w, http.StatusOK, toResponse(entry))
}

func (h *Handler) handleListEntries(w http.ResponseWriter, r *http.Request) {
	limit := 0
	if v := r.URL.Query().Get("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			limit = n
		}
	}

	entries, err := h.svc.ListEntries(r.Context(), limit)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list entries")
		return
	}

	resp := make([]entryResponse, 0, len(entries))
	for _, e := range entries {
		resp = append(resp, toResponse(e))
	}
	writeJSON(w, http.StatusOK, map[string]any{"entries": resp})
}

func (h *Handler) handleCreateAnalysis(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	analysis, err := h.analysis.AnalyzeEntry(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "entry not found")
		return
	}
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	// Provider failures map to gateway statuses. The message is generic on
	// purpose: the underlying error may reference the provider, but never the
	// API key, Authorization header, full provider response, or original
	// learning content. Detail stays in the wrapped error for server logs.
	if errors.Is(err, domain.ErrProviderTimeout) {
		writeError(w, http.StatusGatewayTimeout, "analysis provider timed out")
		return
	}
	if errors.Is(err, domain.ErrProviderUnavailable) {
		writeError(w, http.StatusBadGateway, "analysis provider unavailable")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not analyze entry")
		return
	}
	writeJSON(w, http.StatusCreated, toAnalysisResponse(analysis))
}

func (h *Handler) handleListAnalyses(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	analyses, err := h.analysis.ListAnalyses(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "entry not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list analyses")
		return
	}

	resp := make([]analysisResponse, 0, len(analyses))
	for _, a := range analyses {
		resp = append(resp, toAnalysisResponse(a))
	}
	writeJSON(w, http.StatusOK, map[string]any{"analyses": resp})
}

func (h *Handler) handleCreateFeedback(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	var req createFeedbackRequest
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	feedback, err := h.feedback.AddFeedback(r.Context(), id, domain.NewFeedbackInput{
		Status:               domain.FeedbackStatus(req.Status),
		CorrectedCategory:    req.CorrectedCategory,
		CorrectedExplanation: req.CorrectedExplanation,
		UserNote:             req.UserNote,
	})
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "analysis not found")
		return
	}
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not create feedback")
		return
	}
	writeJSON(w, http.StatusCreated, toFeedbackResponse(feedback))
}

func (h *Handler) handleListFeedback(w http.ResponseWriter, r *http.Request) {
	id, ok := parseID(w, r)
	if !ok {
		return
	}

	feedback, err := h.feedback.ListFeedback(r.Context(), id)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "analysis not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list feedback")
		return
	}

	resp := make([]feedbackResponse, 0, len(feedback))
	for _, f := range feedback {
		resp = append(resp, toFeedbackResponse(f))
	}
	writeJSON(w, http.StatusOK, map[string]any{"feedback": resp})
}

// ---- helpers ----

// parseID reads and validates the {id} path value, writing a 400 response and
// returning ok=false when it is missing or malformed.
func parseID(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil || id <= 0 {
		writeError(w, http.StatusBadRequest, "invalid id")
		return 0, false
	}
	return id, true
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
