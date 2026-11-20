package http

import (
	"net/http"
	"time"

	"french-learning-app/internal/application"
)

// GET /review-today (private workbench; not on the public demo allowlist):
// review_today_v1, the Speaking steps of started, incomplete exercises and
// the Mistake Notebook items marked for retry, in one stable order. Read-only,
// no provider call. Each item reuses its source's JSON (a speaking_practice_v1
// queue item, a Mistake Notebook item) so the workbench opens it the way that
// section does.
func (h *Handler) registerReviewTodayRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /review-today", h.handleReviewToday)
}

func (h *Handler) handleReviewToday(w http.ResponseWriter, r *http.Request) {
	if h.speaking == nil && h.notebook == nil {
		writeError(w, http.StatusServiceUnavailable, "review today is not available on this server")
		return
	}
	// The learner's zone names each item's local day, the same way the
	// learning week groups its days (learnerZone; empty = UTC).
	loc, ok := learnerZone(w, r)
	if !ok {
		return
	}
	var practice *application.SpeakingPractice
	if h.speaking != nil {
		p, err := h.speaking.Practice(r.Context())
		if err != nil {
			writeSpeakingError(w, err, "read the practice overview")
			return
		}
		practice = p
	}
	var notebook []application.NotebookItem
	if h.notebook != nil {
		items, err := h.notebook.ListItems(r.Context(), "", false)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "could not read the Mistake Notebook")
			return
		}
		notebook = items
	}
	now := time.Now().UTC()
	if practice != nil {
		now = practice.Now
	}
	rt := application.BuildReviewToday(practice, notebook, now)
	items := make([]map[string]any, 0, len(rt.Items))
	for _, it := range rt.Items {
		var sinceDay any
		if !it.Since.IsZero() {
			sinceDay = application.LocalDay(it.Since, loc)
		}
		row := map[string]any{"key": it.Key, "source": it.Source, "reason": it.Reason, "priority": it.Priority, "since": ts(it.Since),
			"since_day": sinceDay, "speaking": nil, "notebook": nil}
		if it.Speaking != nil {
			row["speaking"] = toSpeakingQueueItem(*it.Speaking)
		}
		if it.Notebook != nil {
			row["notebook"] = toNotebookItem(*it.Notebook)
		}
		items = append(items, row)
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"schema_version": application.ReviewTodayVersion,
		"generated_at":   ts(rt.Now),
		"zone":           loc.String(),
		"today":          application.LocalDay(rt.Now, loc),
		"items":          items,
		"history": map[string]any{"notebook_items": rt.History.NotebookItems, "speaking_exercises": rt.History.SpeakingExercises,
			"speaking_takes": rt.History.SpeakingTakes},
		"sources": map[string]any{"speaking": h.speaking != nil, "notebook": h.notebook != nil},
	})
}
