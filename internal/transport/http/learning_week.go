package http

import (
	"context"
	"net/http"
	"time"

	"french-learning-app/internal/application"
)

// LearningWeekService is the learning_week_v1 capability (private workbench).
type LearningWeekService interface {
	Week(ctx context.Context, loc *time.Location) (application.LearningWeek, error)
	Sources() map[string]bool
	Now() time.Time
}

// WithLearningWeek enables GET /learning-week. Without it the route answers
// 503. The public demo never reaches it: its boundary is an allowlist.
func WithLearningWeek(service LearningWeekService) HandlerOption {
	return func(handler *Handler) { handler.week = service }
}

func (h *Handler) registerLearningWeekRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /learning-week", h.handleLearningWeek)
}

// learnerZone reads ?zone= (an IANA name, e.g. Europe/Paris). Empty means
// UTC, and the response says so; an unknown name is a 400, never a guess.
func learnerZone(w http.ResponseWriter, r *http.Request) (*time.Location, bool) {
	name := r.URL.Query().Get("zone")
	if name == "" {
		return time.UTC, true
	}
	loc, err := time.LoadLocation(name)
	if err != nil || name == "Local" {
		writeError(w, http.StatusBadRequest, "zone must be an IANA time zone name such as Europe/Paris")
		return nil, false
	}
	return loc, true
}

// handleLearningWeek is the seven-day summary in the learner's zone. Read-only.
func (h *Handler) handleLearningWeek(w http.ResponseWriter, r *http.Request) {
	if h.week == nil {
		writeError(w, http.StatusServiceUnavailable, "the learning week is not available on this server")
		return
	}
	loc, ok := learnerZone(w, r)
	if !ok {
		return
	}
	week, err := h.week.Week(r.Context(), loc)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not read the learning week")
		return
	}
	days := make([]map[string]any, 0, len(week.Days))
	for _, d := range week.Days {
		days = append(days, map[string]any{"day": d.Day, "production": d.Production, "reviewed": d.Reviewed, "own_corrections": d.OwnCorrections, "provider_feedback": d.ProviderFeedback})
	}
	corrections := make([]map[string]any, 0, len(week.Corrections))
	for _, c := range week.Corrections {
		row := map[string]any{"skill": c.Skill, "title": c.Title, "version": c.Version, "prior_version": c.PriorVersion, "day": c.Day, "at": ts(c.At)}
		if c.Skill == "speaking" {
			row["exercise_id"], row["take_id"], row["take_number"] = c.ExerciseID, c.TakeID, c.TakeNumber
		} else {
			row["task_id"] = c.TaskID
		}
		corrections = append(corrections, row)
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"schema_version": application.LearningWeekVersion, "generated_at": ts(h.week.Now()), "zone": week.Zone, "from": week.From, "to": week.To,
		"days": days,
		"totals": map[string]any{"production": week.Production, "reviewed": week.Reviewed, "own_corrections": week.OwnCorrections,
			"provider_feedback": week.ProviderFeedback, "distinct_exercises": week.DistinctExercises, "active_days": week.ActiveDays, "duplicates_ignored": week.Duplicates},
		"sparse": week.Sparse, "min_for_shares": application.LearningWeekMinForShares, "production_share": week.ProductionShare,
		"corrections": corrections, "sources": h.week.Sources(),
	})
}
