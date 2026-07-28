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

// Handler holds dependencies for the HTTP layer.
type Handler struct {
	svc EntryService
}

// NewHandler builds a Handler over the given service.
func NewHandler(svc EntryService) *Handler {
	return &Handler{svc: svc}
}

// Routes returns the configured HTTP mux for the API.
func (h *Handler) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", h.handleHealth)
	mux.HandleFunc("POST /entries", h.handleCreateEntry)
	mux.HandleFunc("GET /entries", h.handleListEntries)
	mux.HandleFunc("GET /entries/{id}", h.handleGetEntry)
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
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil || id <= 0 {
		writeError(w, http.StatusBadRequest, "invalid id")
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

// ---- helpers ----

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
