package http

import (
	"context"
	"errors"
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// ExamService is the Mock Exam v1 application capability.
type ExamService interface {
	Forms() domain.MockExamForms
	Start(ctx context.Context, formID, operationID string) (*application.ExamView, bool, error)
	StartRetry(ctx context.Context, sessionID int64, position int, operationID string) (*application.ExamView, bool, error)
	Get(ctx context.Context, id int64) (*application.ExamView, error)
	List(ctx context.Context) ([]application.ExamSummary, error)
	SaveAnswer(ctx context.Context, id int64, position int, choice *int) (domain.ExamAnswer, *application.ExamView, error)
	Submit(ctx context.Context, id int64, answers map[int]*int) (*application.ExamView, bool, error)
	Now() time.Time
}

// WithExam enables the private /exam routes. Without it they answer 503. The
// public demo never reaches them: its boundary is an allowlist.
func WithExam(service ExamService) HandlerOption {
	return func(handler *Handler) { handler.exam = service }
}

func (h *Handler) registerExamRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /exam/forms", h.handleListExamForms)
	mux.HandleFunc("GET /exam/sessions", h.handleListExamSessions)
	mux.HandleFunc("POST /exam/sessions", h.handleStartExam)
	mux.HandleFunc("GET /exam/sessions/{id}", h.handleGetExam)
	mux.HandleFunc("PUT /exam/sessions/{id}/answers/{position}", h.handleSaveExamAnswer)
	mux.HandleFunc("POST /exam/sessions/{id}/submit", h.handleSubmitExam)
	mux.HandleFunc("POST /exam/sessions/{id}/retries", h.handleStartExamRetry)
}

func (h *Handler) examUnavailable(w http.ResponseWriter) bool {
	if h.exam == nil {
		writeError(w, http.StatusServiceUnavailable, "the mock exam is not available on this server")
		return true
	}
	return false
}

type examPassageJSON struct {
	ID         string                  `json:"id"`
	Title      string                  `json:"title"`
	Format     string                  `json:"format"`
	StyleLevel string                  `json:"style_level"`
	Segments   []domain.ReadingSegment `json:"segments"`
}

type examQuestionJSON struct {
	Position  int      `json:"position"`
	PassageID string   `json:"passage_id"`
	Kind      string   `json:"kind"`
	Question  string   `json:"question"`
	Choices   []string `json:"choices"`
}

type examResultItemJSON struct {
	Position      int                      `json:"position"`
	Choice        *int                     `json:"choice"`
	Key           int                      `json:"key"`
	Correct       bool                     `json:"correct"`
	ExplanationEN string                   `json:"explanation_en"`
	ExplanationZH string                   `json:"explanation_zh"`
	WhyWrong      *domain.ExamWhyWrong     `json:"why_wrong"` // for the chosen wrong answer
	Evidence      []domain.ReadingEvidence `json:"evidence"`
	Source        map[string]any           `json:"source"`
}

// toExamView never puts a key, an explanation, a reason or evidence in the
// answer while the session is in progress: those exist only in "result".
func toExamView(v *application.ExamView, notice string) map[string]any {
	s := v.Session
	passages := []examPassageJSON{}
	seen := map[string]bool{}
	questions := make([]examQuestionJSON, 0, len(s.Items))
	for i, it := range s.Items {
		if !seen[it.PassageID] {
			seen[it.PassageID] = true
			passages = append(passages, examPassageJSON{ID: it.PassageID, Title: it.PassageTitle, Format: it.PassageFormat, StyleLevel: it.StyleLevel, Segments: it.Segments})
		}
		questions = append(questions, examQuestionJSON{Position: i + 1, PassageID: it.PassageID, Kind: it.Kind, Question: it.Question, Choices: it.Choices})
	}
	answers := []map[string]any{}
	for p := 1; p <= len(s.Items); p++ {
		if a, ok := v.Answers[p]; ok {
			answers = append(answers, map[string]any{"position": p, "choice": a.Choice, "saved_at": ts(a.SavedAt)})
		}
	}
	remaining := 0
	if v.State == domain.ExamInProgress {
		remaining = int(math.Ceil(s.DeadlineAt.Sub(v.Now).Seconds()))
	}
	var retryOf any
	if s.RetryOf != nil {
		retryOf = map[string]any{"session_id": *s.RetryOf, "position": s.RetryOfPosition}
	}
	out := map[string]any{
		"session": map[string]any{
			"id": s.ID, "kind": s.Kind, "form_id": s.FormID, "title": s.FormTitle, "retry_of": retryOf,
			"duration_seconds": s.DurationSeconds, "started_at": ts(s.StartedAt), "deadline_at": ts(s.DeadlineAt),
			"forms_sha256": s.FormsSHA256, "pack_sha256": s.PackSHA256,
		},
		"state": v.State, "server_now": ts(v.Now), "remaining_seconds": remaining, "notice": notice,
		"passages": passages, "questions": questions, "answers": answers, "result": nil,
	}
	if v.Final == nil {
		return out
	}
	items := make([]examResultItemJSON, 0, len(s.Items))
	for i, it := range s.Items {
		p := i + 1
		c := v.Final[p]
		r := examResultItemJSON{Position: p, Choice: c, Key: it.Key, Correct: c != nil && *c == it.Key,
			ExplanationEN: it.ExplanationEN, ExplanationZH: it.ExplanationZH, Evidence: it.Evidence,
			Source: map[string]any{"pack": it.PackID, "passage_id": it.PassageID, "question_id": it.QuestionID, "pack_item": it.PackItem, "content_sha256": s.ItemSHA256[i]}}
		if c != nil && *c != it.Key {
			r.WhyWrong = it.WhyWrong[*c]
		}
		items = append(items, r)
	}
	closedAt := s.DeadlineAt
	if v.Submission != nil {
		closedAt = v.Submission.SubmittedAt
	}
	out["result"] = map[string]any{"closed": v.State, "closed_at": ts(closedAt), "correct": v.Correct, "total": v.Total, "items": items}
	return out
}

func writeExamError(w http.ResponseWriter, err error, action string) {
	switch {
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "exam session not found")
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusUnprocessableEntity, err.Error())
	case errors.Is(err, domain.ErrExamOperationConflict), errors.Is(err, domain.ErrExamNotClosed), errors.Is(err, domain.ErrExamNoRelated):
		writeError(w, http.StatusConflict, err.Error())
	default:
		writeError(w, http.StatusInternalServerError, "could not "+action)
	}
}

// writeExamConflict answers a closed or expired session with its code and the
// current view, so a client can show the result at once.
func (h *Handler) writeExamConflict(w http.ResponseWriter, err error, v *application.ExamView) bool {
	code := ""
	switch {
	case errors.Is(err, domain.ErrExamClosed):
		code = "exam_submitted"
	case errors.Is(err, domain.ErrExamExpired):
		code = "exam_expired"
	case errors.Is(err, domain.ErrExamAlreadySubmitted):
		code = "already_submitted"
	default:
		return false
	}
	body := map[string]any{"error": err.Error(), "code": code}
	if v != nil {
		body["exam"] = toExamView(v, h.exam.Forms().Notice)
	}
	writeJSON(w, http.StatusConflict, body)
	return true
}

func examIdempotencyKey(w http.ResponseWriter, r *http.Request) (string, bool) {
	keys := r.Header.Values("Idempotency-Key")
	if len(keys) != 1 || strings.TrimSpace(keys[0]) == "" {
		writeError(w, http.StatusBadRequest, "exactly one Idempotency-Key header is required")
		return "", false
	}
	return strings.ToLower(strings.TrimSpace(keys[0])), true
}

func (h *Handler) handleListExamForms(w http.ResponseWriter, r *http.Request) {
	if h.examUnavailable(w) {
		return
	}
	f := h.exam.Forms()
	forms := make([]map[string]any, 0, len(f.Forms))
	for _, x := range f.Forms {
		forms = append(forms, map[string]any{"id": x.ID, "title": x.Title, "section": x.Section, "duration_seconds": x.DurationSeconds,
			"description": x.Description, "question_count": len(x.Questions)})
	}
	writeJSON(w, http.StatusOK, map[string]any{"schema_version": f.SchemaVersion, "notice": f.Notice, "pack": f.Pack, "forms": forms})
}

func (h *Handler) handleListExamSessions(w http.ResponseWriter, r *http.Request) {
	if h.examUnavailable(w) {
		return
	}
	list, err := h.exam.List(r.Context())
	if err != nil {
		writeExamError(w, err, "list exam sessions")
		return
	}
	rows := make([]map[string]any, 0, len(list))
	for _, x := range list {
		var result any
		if x.Closed {
			result = map[string]any{"correct": x.Correct, "total": x.Total}
		}
		var retryOf any
		if x.Session.RetryOf != nil {
			retryOf = map[string]any{"session_id": *x.Session.RetryOf, "position": x.Session.RetryOfPosition}
		}
		rows = append(rows, map[string]any{"id": x.Session.ID, "kind": x.Session.Kind, "form_id": x.Session.FormID, "title": x.Session.FormTitle,
			"retry_of": retryOf, "state": x.State, "started_at": ts(x.Session.StartedAt), "deadline_at": ts(x.Session.DeadlineAt),
			"question_count": len(x.Session.Items), "result": result})
	}
	writeJSON(w, http.StatusOK, map[string]any{"server_now": ts(h.exam.Now()), "sessions": rows})
}

type startExamRequest struct {
	FormID string `json:"form_id"`
}

func (h *Handler) handleStartExam(w http.ResponseWriter, r *http.Request) {
	if h.examUnavailable(w) {
		return
	}
	key, ok := examIdempotencyKey(w, r)
	if !ok {
		return
	}
	var req startExamRequest
	if !decodeListening(w, r, &req) {
		return
	}
	v, replay, err := h.exam.Start(r.Context(), req.FormID, key)
	if err != nil {
		writeExamError(w, err, "start the exam")
		return
	}
	status := http.StatusCreated
	if replay {
		status = http.StatusOK
	}
	writeJSON(w, status, toExamView(v, h.exam.Forms().Notice))
}

type startExamRetryRequest struct {
	Position int `json:"position"`
}

func (h *Handler) handleStartExamRetry(w http.ResponseWriter, r *http.Request) {
	if h.examUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	key, ok := examIdempotencyKey(w, r)
	if !ok {
		return
	}
	var req startExamRetryRequest
	if !decodeListening(w, r, &req) {
		return
	}
	v, replay, err := h.exam.StartRetry(r.Context(), id, req.Position, key)
	if err != nil {
		writeExamError(w, err, "start the related question")
		return
	}
	status := http.StatusCreated
	if replay {
		status = http.StatusOK
	}
	writeJSON(w, status, toExamView(v, h.exam.Forms().Notice))
}

func (h *Handler) handleGetExam(w http.ResponseWriter, r *http.Request) {
	if h.examUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	v, err := h.exam.Get(r.Context(), id)
	if err != nil {
		writeExamError(w, err, "read the exam")
		return
	}
	writeJSON(w, http.StatusOK, toExamView(v, h.exam.Forms().Notice))
}

type saveExamAnswerRequest struct {
	Choice *int `json:"choice"`
}

func (h *Handler) handleSaveExamAnswer(w http.ResponseWriter, r *http.Request) {
	if h.examUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	position, err := strconv.Atoi(r.PathValue("position"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "position must be a number")
		return
	}
	var req saveExamAnswerRequest
	if !decodeListening(w, r, &req) {
		return
	}
	a, v, err := h.exam.SaveAnswer(r.Context(), id, position, req.Choice)
	if err != nil {
		if !h.writeExamConflict(w, err, v) {
			writeExamError(w, err, "save the answer")
		}
		return
	}
	remaining := int(math.Ceil(v.Session.DeadlineAt.Sub(v.Now).Seconds()))
	writeJSON(w, http.StatusOK, map[string]any{"position": a.Position, "choice": a.Choice, "saved_at": ts(a.SavedAt),
		"server_now": ts(v.Now), "remaining_seconds": max(remaining, 0)})
}

type submitExamRequest struct {
	Answers map[string]*int `json:"answers"`
}

func (h *Handler) handleSubmitExam(w http.ResponseWriter, r *http.Request) {
	if h.examUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	var req submitExamRequest
	if !decodeListening(w, r, &req) {
		return
	}
	answers := map[int]*int{}
	for k, c := range req.Answers {
		p, err := strconv.Atoi(k)
		if err != nil {
			writeError(w, http.StatusUnprocessableEntity, "answers must be keyed by position")
			return
		}
		answers[p] = c
	}
	v, replay, err := h.exam.Submit(r.Context(), id, answers)
	if err != nil {
		if !h.writeExamConflict(w, err, v) {
			writeExamError(w, err, "submit the exam")
		}
		return
	}
	out := toExamView(v, h.exam.Forms().Notice)
	out["replayed"] = replay
	writeJSON(w, http.StatusOK, out)
}
