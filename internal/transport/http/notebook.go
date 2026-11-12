package http

import (
	"context"
	"errors"
	"net/http"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// MistakeNotebookService is the Mistake Notebook v1 capability.
type MistakeNotebookService interface {
	ListItems(ctx context.Context, skill string, markedOnly bool) ([]application.NotebookItem, error)
	EntrySource(ctx context.Context, entryID int64) (*application.NotebookItem, error)
	SetRetry(ctx context.Context, entryID int64, marked bool) (*application.NotebookItem, bool, error)
	ConceptsByKind(ctx context.Context, kind, text string) (*application.ConceptKindView, error)
}

// WithMistakeNotebook enables the private /mistake-notebook routes and
// GET /entries/{id}/source. Without it they answer 503. The public demo never
// reaches them: its boundary is an allowlist.
func WithMistakeNotebook(service MistakeNotebookService) HandlerOption {
	return func(handler *Handler) { handler.notebook = service }
}

func (h *Handler) registerNotebookRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /mistake-notebook/items", h.handleListNotebookItems)
	mux.HandleFunc("PUT /mistake-notebook/items/{id}/retry", h.handleSetNotebookRetry)
	mux.HandleFunc("GET /mistake-notebook/concepts", h.handleNotebookConcepts)
	mux.HandleFunc("GET /entries/{id}/source", h.handleEntrySource)
}

// captureSourceRefRequest is the optional source_ref of a learning_capture_v1
// capture (Mistake Notebook v1).
type captureSourceRefRequest struct {
	Type     string `json:"type"`
	RecordID int64  `json:"record_id"`
	Item     int    `json:"item"`
	Attempt  string `json:"attempt"`
}

type notebookItemJSON struct {
	EntryID   int64          `json:"entry_id"`
	CaptureID string         `json:"capture_id"`
	SavedAt   string         `json:"saved_at"`
	Skill     string         `json:"skill"`
	Source    map[string]any `json:"source"`
	Title     string         `json:"title"`
	Prompt    string         `json:"prompt"`
	Category  string         `json:"category"`
	Quote     *string        `json:"quote"`
	Reference string         `json:"reference"`
	// FLH sections v1: the item's source state, who wrote the reference, and
	// a newer source version when one exists.
	SourceStatus    string            `json:"source_status"`
	ReferenceOrigin string            `json:"reference_origin"`
	Generator       string            `json:"generator"`
	LatestVersion   *int              `json:"latest_version"`
	ExplanationEN   string            `json:"explanation_en"`
	ExplanationZH   string            `json:"explanation_zh"`
	HintEN          *string           `json:"hint_en"`
	HintZH          *string           `json:"hint_zh"`
	Link            domain.SourceLink `json:"link"`
	Record          map[string]string `json:"record"`
	Retry           map[string]any    `json:"retry"`
}

func toNotebookItem(it application.NotebookItem) notebookItemJSON {
	ref := it.Source.Ref
	retry := map[string]any{"marked": false, "since": nil}
	if it.Mark != nil {
		retry["marked"] = it.Mark.Marked
		retry["since"] = ts(it.Mark.At)
	}
	r := it.Resolved
	return notebookItemJSON{
		EntryID: it.Source.EntryID, CaptureID: it.Source.CaptureID, SavedAt: ts(it.Source.CreatedAt), Skill: r.Skill,
		Source: map[string]any{"type": ref.Type, "record_id": ref.RecordID, "item": ref.Item, "attempt": optString(ref.Attempt)},
		Title:  r.Title, Prompt: r.Prompt, Category: r.Category, Quote: optString(r.Quote), Reference: r.Reference,
		ExplanationEN: r.ExplanationEN, ExplanationZH: r.ExplanationZH, HintEN: optString(r.HintEN), HintZH: optString(r.HintZH),
		Link:         r.Link,
		Record:       map[string]string{"original_input": it.Entry.OriginalInput, "original_context": it.Entry.OriginalContext},
		Retry:        retry,
		SourceStatus: it.SourceState, ReferenceOrigin: r.Origin, Generator: r.Generator, LatestVersion: optInt(r.LatestVersion),
	}
}

func optInt(n int) *int {
	if n == 0 {
		return nil
	}
	return &n
}

func (h *Handler) notebookUnavailable(w http.ResponseWriter) bool {
	if h.notebook == nil {
		writeError(w, http.StatusServiceUnavailable, "the mistake notebook is not available on this server")
		return true
	}
	return false
}

func writeNotebookError(w http.ResponseWriter, err error, action string) {
	switch {
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "notebook record not found")
	case errors.Is(err, domain.ErrValidation), errors.Is(err, application.ErrKnowledgeLibraryQuery):
		writeError(w, http.StatusBadRequest, err.Error())
	case errors.Is(err, application.ErrNotebookKindViewsUnavailable):
		writeError(w, http.StatusServiceUnavailable, err.Error())
	default:
		writeError(w, http.StatusInternalServerError, "could not "+action)
	}
}

// handleListNotebookItems lists notebook records (newest first), filtered by
// skill and/or marked=true. Read-only.
func (h *Handler) handleListNotebookItems(w http.ResponseWriter, r *http.Request) {
	if h.notebookUnavailable(w) {
		return
	}
	q := r.URL.Query()
	marked := false
	switch q.Get("marked") {
	case "", "false":
	case "true":
		marked = true
	default:
		writeError(w, http.StatusBadRequest, "marked must be true or false")
		return
	}
	items, err := h.notebook.ListItems(r.Context(), q.Get("skill"), marked)
	if err != nil {
		writeNotebookError(w, err, "list the notebook")
		return
	}
	out := make([]notebookItemJSON, 0, len(items))
	for _, it := range items {
		out = append(out, toNotebookItem(it))
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": out, "unlinked_notice": "Only records saved from an exercise with a source link appear here. Records saved without one (for example before source links existed) stay in Learning Records and are never linked by guessing."})
}

type setRetryRequest struct {
	Marked *bool `json:"marked"`
}

// handleSetNotebookRetry records one explicit retry decision. 200 with the
// item and "changed"; 404 when the record is not a notebook record.
func (h *Handler) handleSetNotebookRetry(w http.ResponseWriter, r *http.Request) {
	if h.notebookUnavailable(w) {
		return
	}
	id, ok := parseID(w, r) // the record (entry) id
	if !ok {
		return
	}
	var req setRetryRequest
	if !decodeListening(w, r, &req) {
		return
	}
	if req.Marked == nil {
		writeError(w, http.StatusUnprocessableEntity, "marked is required")
		return
	}
	it, changed, err := h.notebook.SetRetry(r.Context(), id, *req.Marked)
	if err != nil {
		writeNotebookError(w, err, "record the retry decision")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"item": toNotebookItem(*it), "changed": changed})
}

// handleNotebookConcepts is one Grammar / Vocabulary / Unclassified view over
// active Concepts (Knowledge Library search, concept_kind_view_v1). Read-only.
func (h *Handler) handleNotebookConcepts(w http.ResponseWriter, r *http.Request) {
	if h.notebookUnavailable(w) {
		return
	}
	view, err := h.notebook.ConceptsByKind(r.Context(), r.URL.Query().Get("kind"), r.URL.Query().Get("q"))
	if err != nil {
		writeNotebookError(w, err, "read the view")
		return
	}
	rows := make([]map[string]any, 0, len(view.Rows))
	for _, row := range view.Rows {
		kinds := make([]string, 0, len(row.Kinds))
		for _, k := range row.Kinds {
			kinds = append(kinds, string(k))
		}
		var reason any
		if row.Reason != "" {
			reason = row.Reason
		}
		rows = append(rows, map[string]any{"concept_id": row.Concept.ID, "target": row.Concept.Target, "pedagogical_intent": row.Concept.PedagogicalIntent,
			"scope": row.Concept.Scope, "state": row.Concept.State, "class": row.Class, "reason": reason, "kinds": kinds,
			"supporting_unit_count": row.SupportingUnitCount, "match_tier": row.MatchTier})
	}
	writeJSON(w, http.StatusOK, map[string]any{"rule": domain.ConceptKindViewVersion, "kind": view.Kind, "query": view.Query, "tokens": view.Tokens,
		"classified": view.Classified, "truncated": view.Truncated, "concepts": rows})
}

// handleEntrySource returns a record's structured source, or linked:false for
// a record saved without one. 404 for an unknown record.
func (h *Handler) handleEntrySource(w http.ResponseWriter, r *http.Request) {
	if h.notebookUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	it, err := h.notebook.EntrySource(r.Context(), id)
	switch {
	case errors.Is(err, domain.ErrNotFound):
		if _, getErr := h.svc.GetEntry(r.Context(), id); getErr != nil {
			if errors.Is(getErr, domain.ErrNotFound) {
				writeError(w, http.StatusNotFound, "record not found")
			} else {
				writeError(w, http.StatusInternalServerError, "could not read the record")
			}
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"entry_id": id, "linked": false,
			"notice": "This record has no structured source link: it was saved without one (for example before source links existed, or from another tool). It is not linked by guessing."})
	case err != nil:
		writeNotebookError(w, err, "read the record's source")
	default:
		writeJSON(w, http.StatusOK, map[string]any{"entry_id": id, "linked": true, "item": toNotebookItem(*it)})
	}
}
