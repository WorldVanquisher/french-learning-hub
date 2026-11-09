package http

import (
	"context"
	"errors"
	"io"
	"net/http"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// ListeningDailyService is Daily Listening: the one pull operation (shared with
// the operator command), its status, and explicit notification retries.
type ListeningDailyService interface {
	Status(ctx context.Context) (application.ListeningDailyStatus, error)
	Pull(ctx context.Context, operationID, trigger string) (domain.ListeningPullRun, bool, error)
	GetPullRun(ctx context.Context, operationID string) (domain.ListeningPullRun, error)
	RetryNotification(ctx context.Context, exerciseID int64, operationID string, confirmUnknown bool) (domain.ListeningNotification, bool, error)
	GetNotification(ctx context.Context, operationID string) (domain.ListeningNotification, error)
	NotifyChannel() (bool, string)
	Now() time.Time
}

// WithListeningDaily enables the Daily Listening routes under /listening.
// Without it they answer 503. The public demo never reaches them.
func WithListeningDaily(service ListeningDailyService) HandlerOption {
	return func(handler *Handler) { handler.listeningDaily = service }
}

func (h *Handler) registerListeningDailyRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /listening/daily", h.handleListeningDailyStatus)
	mux.HandleFunc("POST /listening/pull", h.handleListeningPull)
	mux.HandleFunc("GET /listening/pull-runs/{operation_id}", h.handleGetListeningPullRun)
	mux.HandleFunc("POST /listening/exercises/{id}/notifications", h.handleRetryListeningNotification)
	mux.HandleFunc("GET /listening/notifications/{operation_id}", h.handleGetListeningNotification)
}

type listeningPreparationResponse struct {
	ID           int64   `json:"id"`
	OperationID  string  `json:"operation_id"`
	MaterialID   int64   `json:"material_id"`
	TranscriptID int64   `json:"transcript_id"`
	Trigger      string  `json:"trigger"`
	PullRunID    *int64  `json:"pull_run_id"`
	AfterUnknown bool    `json:"after_unknown"`
	StartedAt    string  `json:"started_at"`
	DeadlineAt   string  `json:"deadline_at"`
	FinishedAt   *string `json:"finished_at"`
	// State: in_progress, completed, failed or unknown (also an attempt left
	// unfinished past its deadline).
	State      string `json:"state"`
	ExerciseID *int64 `json:"exercise_id"`
}

type listeningNotificationResponse struct {
	ID           int64   `json:"id"`
	OperationID  string  `json:"operation_id"`
	ExerciseID   int64   `json:"exercise_id"`
	Channel      string  `json:"channel"`
	Trigger      string  `json:"trigger"`
	PullRunID    *int64  `json:"pull_run_id"`
	AfterUnknown bool    `json:"after_unknown"`
	StartedAt    string  `json:"started_at"`
	DeadlineAt   string  `json:"deadline_at"`
	FinishedAt   *string `json:"finished_at"`
	// State: in_progress, sent, failed or unknown.
	State       string  `json:"state"`
	FailureCode *string `json:"failure_code"`
}

type listeningNotifySettings struct {
	Enabled bool    `json:"enabled"`
	Channel *string `json:"channel"`
}

type listeningStepResponse struct {
	Outcome *string `json:"outcome"`
}

type listeningPullRunResponse struct {
	ID             int64   `json:"id"`
	OperationID    string  `json:"operation_id"`
	Trigger        string  `json:"trigger"`
	Status         string  `json:"status"` // running, finished, interrupted (also a running run past its lease)
	StartedAt      string  `json:"started_at"`
	LeaseExpiresAt string  `json:"lease_expires_at"`
	FinishedAt     *string `json:"finished_at"`
	Source         struct {
		Outcome *string `json:"outcome"`
		Failure *string `json:"failure"`
	} `json:"source"`
	Items struct {
		Seen    int `json:"seen"`
		Created int `json:"created"`
		Known   int `json:"known"`
		Skipped int `json:"skipped"`
	} `json:"items"`
	Preparation struct {
		Outcome *string                       `json:"outcome"`
		Attempt *listeningPreparationResponse `json:"attempt"`
	} `json:"preparation"`
	Notification struct {
		Outcome *string                        `json:"outcome"`
		Attempt *listeningNotificationResponse `json:"attempt"`
	} `json:"notification"`
}

func optString(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func listeningOptTime(t *time.Time) *string {
	if t == nil {
		return nil
	}
	s := ts(*t)
	return &s
}

func toListeningPreparation(p domain.ListeningPreparation, now time.Time) listeningPreparationResponse {
	return listeningPreparationResponse{
		ID: p.ID, OperationID: p.OperationID, MaterialID: p.MaterialID, TranscriptID: p.TranscriptID, Trigger: p.Trigger,
		PullRunID: p.PullRunID, AfterUnknown: p.AfterUnknown, StartedAt: ts(p.StartedAt), DeadlineAt: ts(p.DeadlineAt),
		FinishedAt: listeningOptTime(p.FinishedAt), State: p.State(now), ExerciseID: p.ExerciseID,
	}
}

func toListeningNotification(n domain.ListeningNotification, now time.Time) listeningNotificationResponse {
	return listeningNotificationResponse{
		ID: n.ID, OperationID: n.OperationID, ExerciseID: n.ExerciseID, Channel: n.Channel, Trigger: n.Trigger,
		PullRunID: n.PullRunID, AfterUnknown: n.AfterUnknown, StartedAt: ts(n.StartedAt), DeadlineAt: ts(n.DeadlineAt),
		FinishedAt: listeningOptTime(n.FinishedAt), State: n.State(now), FailureCode: optString(n.FailureCode),
	}
}

func toListeningPullRun(r domain.ListeningPullRun, now time.Time) listeningPullRunResponse {
	out := listeningPullRunResponse{
		ID: r.ID, OperationID: r.OperationID, Trigger: r.Trigger, Status: r.EffectiveStatus(now),
		StartedAt: ts(r.StartedAt), LeaseExpiresAt: ts(r.LeaseExpiresAt), FinishedAt: listeningOptTime(r.FinishedAt),
	}
	out.Source.Outcome, out.Source.Failure = optString(r.SourceOutcome), optString(r.SourceFailure)
	out.Items.Seen, out.Items.Created, out.Items.Known, out.Items.Skipped = r.ItemsSeen, r.MaterialsCreated, r.ItemsKnown, r.ItemsSkipped
	out.Preparation.Outcome, out.Notification.Outcome = optString(r.PrepareOutcome), optString(r.NotifyOutcome)
	if r.Preparation != nil {
		p := toListeningPreparation(*r.Preparation, now)
		out.Preparation.Attempt = &p
	}
	if r.Notification != nil {
		n := toListeningNotification(*r.Notification, now)
		out.Notification.Attempt = &n
	}
	return out
}

func (h *Handler) listeningNotifySettings() listeningNotifySettings {
	if h.listeningDaily == nil {
		return listeningNotifySettings{}
	}
	enabled, channel := h.listeningDaily.NotifyChannel()
	return listeningNotifySettings{Enabled: enabled, Channel: optString(channel)}
}

func (h *Handler) listeningDailyUnavailable(w http.ResponseWriter) bool {
	if h.listening == nil || h.listeningDaily == nil {
		writeError(w, http.StatusServiceUnavailable, "daily listening is not available on this server")
		return true
	}
	return false
}

// requiredKey reads exactly one UUID Idempotency-Key header.
func requiredKey(w http.ResponseWriter, r *http.Request) (string, bool) {
	keys := r.Header.Values("Idempotency-Key")
	if len(keys) != 1 {
		writeError(w, http.StatusBadRequest, "exactly one Idempotency-Key header is required")
		return "", false
	}
	if _, err := domain.NormalizeAnnotationOperationID(keys[0]); err != nil {
		writeError(w, http.StatusBadRequest, "invalid idempotency key")
		return "", false
	}
	return keys[0], true
}

// handleListeningDailyStatus reads the settings, today's use of the daily cap
// and the last pull. It calls no outside service.
func (h *Handler) handleListeningDailyStatus(w http.ResponseWriter, r *http.Request) {
	if h.listeningDailyUnavailable(w) {
		return
	}
	st, err := h.listeningDaily.Status(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not read daily listening status")
		return
	}
	var last *listeningPullRunResponse
	if st.LastRun != nil {
		run := toListeningPullRun(*st.LastRun, st.Now)
		last = &run
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"pull_enabled": st.PullEnabled,
		"source":       map[string]any{"enabled": st.SourceEnabled, "name": optString(st.SourceName)},
		"preparation": map[string]any{
			"enabled": st.PrepareEnabled, "generator": optString(st.Generator), "daily_cap": st.DailyCap,
			"timezone": st.Timezone, "today": st.Today, "used_today": st.UsedToday,
		},
		"notification": map[string]any{"enabled": st.NotifyEnabled, "channel": optString(st.Channel)},
		"last_run":     last,
	})
}

// handleListeningPull is the workbench's "Pull now": the same operation the
// operator command runs. It requires a UUID Idempotency-Key and no body. The
// run is not canceled when the client goes away; after a lost response, look
// it up at GET /listening/pull-runs/{key} or resend with the same key.
//
// Status: 201 the finished run; 200 same-key replay (Idempotency-Replayed:
// true), running or finished; 409 {code: busy, run} while another run holds
// its lease (nothing started); 503 not configured; 400; 500 (the run, if it
// started, is reported interrupted once its lease expires).
func (h *Handler) handleListeningPull(w http.ResponseWriter, r *http.Request) {
	if h.listeningDailyUnavailable(w) {
		return
	}
	key, ok := requiredKey(w, r)
	if !ok {
		return
	}
	if body, _ := io.ReadAll(io.LimitReader(r.Body, 1)); len(body) > 0 {
		writeError(w, http.StatusBadRequest, "this request takes no body")
		return
	}
	run, replay, err := h.listeningDaily.Pull(context.WithoutCancel(r.Context()), key, domain.ListeningPullManual)
	now := h.listeningDaily.Now()
	switch {
	case errors.Is(err, domain.ErrListeningPullNotConfigured):
		writeError(w, http.StatusServiceUnavailable, err.Error())
	case errors.Is(err, domain.ErrListeningPullBusy):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "busy", "run": toListeningPullRun(run, now)})
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusBadRequest, err.Error())
	case err != nil:
		writeError(w, http.StatusInternalServerError, "the pull could not be completed; check its status with the same key")
	case replay:
		w.Header().Set("Idempotency-Replayed", "true")
		writeJSON(w, http.StatusOK, toListeningPullRun(run, now))
	default:
		writeJSON(w, http.StatusCreated, toListeningPullRun(run, now))
	}
}

// handleGetListeningPullRun looks a run up by its key. 404 means nothing is
// recorded under it yet; it never proves the request was not received.
func (h *Handler) handleGetListeningPullRun(w http.ResponseWriter, r *http.Request) {
	if h.listeningDailyUnavailable(w) {
		return
	}
	run, err := h.listeningDaily.GetPullRun(r.Context(), r.PathValue("operation_id"))
	switch {
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusBadRequest, "invalid idempotency key")
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "no pull is recorded under this key")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "could not read the pull")
	default:
		writeJSON(w, http.StatusOK, toListeningPullRun(run, h.listeningDaily.Now()))
	}
}

type retryNotificationRequest struct {
	ConfirmUnknownRetry bool `json:"confirm_unknown_retry"`
}

// handleRetryListeningNotification is the explicit "send again" for one
// exercise whose last notification failed or has an unknown outcome. It
// requires a UUID Idempotency-Key; {"confirm_unknown_retry": true} is required
// after an unknown outcome (the message may already have arrived).
//
// Status: 201 the recorded attempt with its outcome (sent, failed or unknown);
// 200 same-key replay; 409 {code}: outcome_unknown, in_progress, not_retryable,
// not_completed, key_conflict; 503 notifications off; 404; 400.
func (h *Handler) handleRetryListeningNotification(w http.ResponseWriter, r *http.Request) {
	if h.listeningDailyUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	key, ok := requiredKey(w, r)
	if !ok {
		return
	}
	var req retryNotificationRequest
	if !decodeOptionalListening(w, r, &req) {
		return
	}
	n, replay, err := h.listeningDaily.RetryNotification(context.WithoutCancel(r.Context()), id, key, req.ConfirmUnknownRetry)
	now := h.listeningDaily.Now()
	conflict := func(code string) {
		body := map[string]any{"error": err.Error(), "code": code, "notification": nil}
		if n.ID != 0 {
			body["notification"] = toListeningNotification(n, now)
		}
		writeJSON(w, http.StatusConflict, body)
	}
	switch {
	case errors.Is(err, domain.ErrListeningNotifyDisabled):
		writeError(w, http.StatusServiceUnavailable, err.Error())
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "listening exercise not found")
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusBadRequest, err.Error())
	case errors.Is(err, domain.ErrListeningOutcomeUnknown):
		conflict("outcome_unknown")
	case errors.Is(err, domain.ErrListeningNotificationInProgress):
		conflict("in_progress")
	case errors.Is(err, domain.ErrListeningNotRetryable):
		conflict("not_retryable")
	case errors.Is(err, domain.ErrListeningExerciseNotCompleted):
		conflict("not_completed")
	case errors.Is(err, domain.ErrListeningOperationConflict):
		conflict("key_conflict")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "could not send the notification; check it with the same key")
	case replay:
		w.Header().Set("Idempotency-Replayed", "true")
		writeJSON(w, http.StatusOK, toListeningNotification(n, now))
	default:
		writeJSON(w, http.StatusCreated, toListeningNotification(n, now))
	}
}

// handleGetListeningNotification looks a send attempt up by its key.
func (h *Handler) handleGetListeningNotification(w http.ResponseWriter, r *http.Request) {
	if h.listeningDailyUnavailable(w) {
		return
	}
	n, err := h.listeningDaily.GetNotification(r.Context(), r.PathValue("operation_id"))
	switch {
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "no notification is recorded under this key")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "could not read the notification")
	default:
		writeJSON(w, http.StatusOK, toListeningNotification(n, h.listeningDaily.Now()))
	}
}
