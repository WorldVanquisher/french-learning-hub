package http

import (
	"context"
	"errors"
	"net/http"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// WritingService is the Exam Writing v1 application capability.
type WritingService interface {
	GeneratorEnabled() (bool, string)
	ListPrompts(ctx context.Context) ([]application.WritingPromptView, error)
	StartPrompt(ctx context.Context, promptID string) (*application.WritingTaskView, bool, error)
	CreateTask(ctx context.Context, t domain.WritingTask) (*application.WritingTaskView, error)
	GetTask(ctx context.Context, id int64) (*application.WritingTaskView, error)
	ListTasks(ctx context.Context) ([]application.WritingTaskSummary, error)
	AddDraft(ctx context.Context, taskID int64, text string) (*application.WritingTaskView, error)
	RequestFeedback(ctx context.Context, in application.WritingFeedbackRequestInput) (*application.WritingFeedbackResult, bool, error)
	GetFeedbackRequest(ctx context.Context, operationID string) (*application.WritingFeedbackResult, error)
	Now() time.Time
}

// WithWriting enables the private /writing routes. Without it they answer 503.
// The public demo never reaches them: its boundary is an allowlist.
func WithWriting(service WritingService) HandlerOption {
	return func(handler *Handler) { handler.writing = service }
}

// WritingWordConvention is shown with every task so the count is never a surprise.
const WritingWordConvention = "Words are runs of letters or digits; an apostrophe or a hyphen inside a word keeps it one word (« l'invitation », « peut-être »); numbers count; punctuation alone does not."

func (h *Handler) registerWritingRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /writing/prompts", h.handleListWritingPrompts)
	mux.HandleFunc("POST /writing/prompts/{prompt_id}", h.handleStartWritingPrompt)
	mux.HandleFunc("GET /writing/tasks", h.handleListWritingTasks)
	mux.HandleFunc("POST /writing/tasks", h.handleCreateWritingTask)
	mux.HandleFunc("GET /writing/tasks/{id}", h.handleGetWritingTask)
	mux.HandleFunc("POST /writing/tasks/{id}/drafts", h.handleAddWritingDraft)
	mux.HandleFunc("POST /writing/drafts/{id}/feedback", h.handleRequestWritingFeedback)
	mux.HandleFunc("GET /writing/feedback-requests/{operation_id}", h.handleGetWritingFeedbackRequest)
}

type writingTaskJSON struct {
	ID           int64    `json:"id"`
	Title        string   `json:"title"`
	Prompt       string   `json:"prompt"`
	Requirements []string `json:"requirements"`
	WordMin      int      `json:"word_min"`
	WordMax      int      `json:"word_max"`
	Origin       string   `json:"origin"`
	PromptID     *string  `json:"prompt_id"`
	CreatedAt    string   `json:"created_at"`
}

type writingDraftJSON struct {
	ID        int64  `json:"id"`
	Version   int    `json:"version"`
	Text      string `json:"text"`
	WordCount int    `json:"word_count"`
	CreatedAt string `json:"created_at"`
}

type writingFeedbackJSON struct {
	ID          int64                          `json:"id"`
	DraftID     int64                          `json:"draft_id"`
	Status      string                         `json:"status"`
	FailureCode *string                        `json:"failure_code"`
	Generator   string                         `json:"generator"`
	CreatedAt   string                         `json:"created_at"`
	Content     *domain.WritingFeedbackContent `json:"content"`
}

type writingRequestJSON struct {
	ID           int64   `json:"id"`
	OperationID  string  `json:"operation_id"`
	DraftID      int64   `json:"draft_id"`
	AfterUnknown bool    `json:"after_unknown"`
	StartedAt    string  `json:"started_at"`
	DeadlineAt   string  `json:"deadline_at"`
	FinishedAt   *string `json:"finished_at"`
	State        string  `json:"state"`
	FeedbackID   *int64  `json:"feedback_id"`
}

func toWritingTask(t domain.WritingTask) writingTaskJSON {
	reqs := t.Requirements
	if reqs == nil {
		reqs = []string{}
	}
	return writingTaskJSON{ID: t.ID, Title: t.Title, Prompt: t.Prompt, Requirements: reqs, WordMin: t.WordMin, WordMax: t.WordMax,
		Origin: t.Origin, PromptID: optString(t.PromptID), CreatedAt: ts(t.CreatedAt)}
}

func toWritingFeedback(f domain.WritingFeedback, withContent bool) writingFeedbackJSON {
	out := writingFeedbackJSON{ID: f.ID, DraftID: f.DraftID, Status: f.Status, FailureCode: optString(f.FailureCode), Generator: f.Generator, CreatedAt: ts(f.CreatedAt)}
	if withContent {
		out.Content = f.Content
	}
	return out
}

func toWritingRequest(r domain.WritingFeedbackRequest, now time.Time) writingRequestJSON {
	return writingRequestJSON{ID: r.ID, OperationID: r.OperationID, DraftID: r.DraftID, AfterUnknown: r.AfterUnknown, StartedAt: ts(r.StartedAt),
		DeadlineAt: ts(r.DeadlineAt), FinishedAt: listeningOptTime(r.FinishedAt), State: r.State(now), FeedbackID: r.FeedbackID}
}

func (h *Handler) writingGeneration() listeningGenerationResponse {
	enabled, name := h.writing.GeneratorEnabled()
	out := listeningGenerationResponse{Enabled: enabled}
	if enabled {
		out.Generator = &name
	}
	return out
}

func (h *Handler) toWritingView(v *application.WritingTaskView) map[string]any {
	drafts := make([]writingDraftJSON, 0, len(v.Drafts))
	for _, d := range v.Drafts {
		drafts = append(drafts, writingDraftJSON{ID: d.ID, Version: d.Version, Text: d.Text, WordCount: d.WordCount, CreatedAt: ts(d.CreatedAt)})
	}
	fb := make([]writingFeedbackJSON, 0, len(v.Feedback))
	for _, f := range v.Feedback {
		fb = append(fb, toWritingFeedback(f, true))
	}
	reqs := make([]writingRequestJSON, 0, len(v.Requests))
	for _, r := range v.Requests {
		reqs = append(reqs, toWritingRequest(r, v.Now))
	}
	return map[string]any{"task": toWritingTask(v.Task), "drafts": drafts, "feedback": fb, "requests": reqs,
		"generation": h.writingGeneration(), "word_convention": WritingWordConvention}
}

func (h *Handler) writingUnavailable(w http.ResponseWriter) bool {
	if h.writing == nil {
		writeError(w, http.StatusServiceUnavailable, "writing tasks are not available on this server")
		return true
	}
	return false
}

func writeWritingError(w http.ResponseWriter, err error, action string) {
	switch {
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "writing task, draft or prompt not found")
	case errors.Is(err, domain.ErrWritingDraftUnchanged):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "unchanged"})
	case errors.Is(err, domain.ErrWritingTooManyVersions):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "too_many_versions"})
	case errors.Is(err, domain.ErrWritingPromptConflict):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "prompt_conflict"})
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusUnprocessableEntity, err.Error())
	default:
		writeError(w, http.StatusInternalServerError, "could not "+action)
	}
}

func (h *Handler) handleListWritingPrompts(w http.ResponseWriter, r *http.Request) {
	if h.writingUnavailable(w) {
		return
	}
	ps, err := h.writing.ListPrompts(r.Context())
	if err != nil {
		writeWritingError(w, err, "list writing prompts")
		return
	}
	out := make([]map[string]any, 0, len(ps))
	for _, p := range ps {
		out = append(out, map[string]any{"id": p.Prompt.ID, "format": p.Prompt.Format, "style_level": p.Prompt.StyleLevel, "title": p.Prompt.Title,
			"prompt": p.Prompt.Prompt, "requirements": p.Prompt.Requirements, "word_min": p.Prompt.WordMin, "word_max": p.Prompt.WordMax,
			"example_draft": p.Prompt.ExampleDraft, "started_task_id": p.StartedTaskID})
	}
	writeJSON(w, http.StatusOK, map[string]any{"set": domain.WritingPromptsID,
		"notice": "Authored practice tasks: not official exam items; no score and no certified CEFR level.", "prompts": out})
}

// handleStartWritingPrompt starts the task for an authored prompt. 201 new; 200 existing.
func (h *Handler) handleStartWritingPrompt(w http.ResponseWriter, r *http.Request) {
	if h.writingUnavailable(w) {
		return
	}
	v, replay, err := h.writing.StartPrompt(r.Context(), r.PathValue("prompt_id"))
	if err != nil {
		writeWritingError(w, err, "start the task")
		return
	}
	status := http.StatusCreated
	if replay {
		status = http.StatusOK
		w.Header().Set("Idempotency-Replayed", "true")
	}
	writeJSON(w, status, h.toWritingView(v))
}

func (h *Handler) handleListWritingTasks(w http.ResponseWriter, r *http.Request) {
	if h.writingUnavailable(w) {
		return
	}
	rows, err := h.writing.ListTasks(r.Context())
	if err != nil {
		writeWritingError(w, err, "list writing tasks")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		out = append(out, map[string]any{"task": toWritingTask(row.Task), "versions": row.Versions, "feedback": row.Feedback})
	}
	writeJSON(w, http.StatusOK, map[string]any{"tasks": out, "generation": h.writingGeneration()})
}

type createWritingTaskRequest struct {
	Title        string   `json:"title"`
	Prompt       string   `json:"prompt"`
	Requirements []string `json:"requirements"`
	WordMin      int      `json:"word_min"`
	WordMax      int      `json:"word_max"`
}

func (h *Handler) handleCreateWritingTask(w http.ResponseWriter, r *http.Request) {
	if h.writingUnavailable(w) {
		return
	}
	var req createWritingTaskRequest
	if !decodeListening(w, r, &req) {
		return
	}
	v, err := h.writing.CreateTask(r.Context(), domain.WritingTask{Title: req.Title, Prompt: req.Prompt, Requirements: req.Requirements, WordMin: req.WordMin, WordMax: req.WordMax})
	if err != nil {
		writeWritingError(w, err, "save the task")
		return
	}
	writeJSON(w, http.StatusCreated, h.toWritingView(v))
}

func (h *Handler) handleGetWritingTask(w http.ResponseWriter, r *http.Request) {
	if h.writingUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	v, err := h.writing.GetTask(r.Context(), id)
	if err != nil {
		writeWritingError(w, err, "read the task")
		return
	}
	writeJSON(w, http.StatusOK, h.toWritingView(v))
}

type addWritingDraftRequest struct {
	Text string `json:"text"`
}

// handleAddWritingDraft saves the next immutable version (201); 409 unchanged
// or too many versions; 422 invalid text. No provider call.
func (h *Handler) handleAddWritingDraft(w http.ResponseWriter, r *http.Request) {
	if h.writingUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	var req addWritingDraftRequest
	if !decodeListening(w, r, &req) {
		return
	}
	v, err := h.writing.AddDraft(r.Context(), id, req.Text)
	if err != nil {
		writeWritingError(w, err, "save the draft")
		return
	}
	writeJSON(w, http.StatusCreated, h.toWritingView(v))
}

func toWritingResult(res *application.WritingFeedbackResult, now time.Time) map[string]any {
	out := map[string]any{"request": nil, "feedback": nil}
	if res == nil {
		return out
	}
	out["request"] = toWritingRequest(res.Request, now)
	if res.Feedback != nil {
		out["feedback"] = toWritingFeedback(*res.Feedback, true)
	}
	return out
}

// handleRequestWritingFeedback is the one explicit provider call, for one
// draft version (the Listening/Reading contract): optional UUID
// Idempotency-Key, optional {"confirm_unknown_retry": true}; not canceled when
// the client goes away. 201 {request, feedback}; 200 same-key replay; 502/504
// stored failure or unknown outcome (the draft is kept); 409 {code}:
// request_in_progress, outcome_unknown, key_conflict; 503 disabled; 404.
func (h *Handler) handleRequestWritingFeedback(w http.ResponseWriter, r *http.Request) {
	if h.writingUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	key, ok := optionalKey(w, r)
	if !ok {
		return
	}
	var body prepareListeningRequest
	if !decodeOptionalListening(w, r, &body) {
		return
	}
	res, replay, err := h.writing.RequestFeedback(context.WithoutCancel(r.Context()), application.WritingFeedbackRequestInput{
		DraftID: id, OperationID: key, ConfirmUnknownRetry: body.ConfirmUnknownRetry,
	})
	now := h.writing.Now()
	if res != nil {
		w.Header().Set("Idempotency-Key", res.Request.OperationID)
	}
	var genErr *application.WritingGenerationError
	switch {
	case errors.As(err, &genErr):
		status, msg := http.StatusBadGateway, "the feedback provider is unavailable; your draft is kept"
		switch {
		case errors.Is(err, domain.ErrProviderTimeout):
			status, msg = http.StatusGatewayTimeout, "the feedback provider timed out, so the outcome is unknown; your draft is kept"
		case errors.Is(err, domain.ErrOutcomeUnknown):
			msg = "the request reached the feedback provider but no usable answer came back, so the outcome is unknown; your draft is kept"
		case errors.Is(err, domain.ErrValidation):
			msg = "the feedback provider returned output that is not usable; your draft is kept"
		}
		b := toWritingResult(res, now)
		b["error"] = msg
		writeJSON(w, status, b)
	case errors.Is(err, domain.ErrWritingDisabled):
		writeError(w, http.StatusServiceUnavailable, "writing feedback is not enabled (WRITING_PROVIDER); drafting and revising still work")
	case errors.Is(err, domain.ErrWritingRequestInProgress):
		b := toWritingResult(res, now)
		b["error"], b["code"] = err.Error(), "request_in_progress"
		writeJSON(w, http.StatusConflict, b)
	case errors.Is(err, domain.ErrWritingOutcomeUnknown):
		b := toWritingResult(res, now)
		b["error"], b["code"] = err.Error(), "outcome_unknown"
		writeJSON(w, http.StatusConflict, b)
	case errors.Is(err, domain.ErrWritingOperationConflict):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "key_conflict"})
	case err != nil:
		writeWritingError(w, err, "request feedback")
	case replay:
		w.Header().Set("Idempotency-Replayed", "true")
		writeJSON(w, http.StatusOK, toWritingResult(res, now))
	default:
		writeJSON(w, http.StatusCreated, toWritingResult(res, now))
	}
}

func (h *Handler) handleGetWritingFeedbackRequest(w http.ResponseWriter, r *http.Request) {
	if h.writingUnavailable(w) {
		return
	}
	res, err := h.writing.GetFeedbackRequest(r.Context(), r.PathValue("operation_id"))
	switch {
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusBadRequest, "invalid idempotency key")
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "no feedback request is recorded under this key")
	case err != nil:
		writeWritingError(w, err, "read the request")
	default:
		writeJSON(w, http.StatusOK, toWritingResult(res, h.writing.Now()))
	}
}
