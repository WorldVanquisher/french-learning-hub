package http

import (
	"context"
	"errors"
	"net/http"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// ReadingService is the Exam Reading v1 application capability.
type ReadingService interface {
	GeneratorEnabled() (bool, string)
	CreateLesson(ctx context.Context, title, text, sourceURL string) (*application.ReadingLessonView, error)
	AddPassage(ctx context.Context, lessonID int64, text string) (*application.ReadingLessonView, error)
	GetLesson(ctx context.Context, id int64) (*application.ReadingLessonView, error)
	ListLessons(ctx context.Context) ([]application.ReadingLessonSummary, error)
	ListExamples(ctx context.Context) ([]application.ReadingExample, error)
	ImportExample(ctx context.Context, passageID string) (*application.ReadingLessonView, bool, error)
	PrepareExercise(ctx context.Context, req application.ReadingPrepareRequest) (*application.ReadingPreparationResult, bool, error)
	GetPreparation(ctx context.Context, operationID string) (*application.ReadingPreparationResult, error)
	Now() time.Time
}

// WithReading enables the private /reading routes. Without it they answer 503.
// The public demo never reaches them: its boundary is an allowlist.
func WithReading(service ReadingService) HandlerOption {
	return func(handler *Handler) { handler.reading = service }
}

func (h *Handler) registerReadingRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /reading/lessons", h.handleListReading)
	mux.HandleFunc("POST /reading/lessons", h.handleCreateReading)
	mux.HandleFunc("GET /reading/lessons/{id}", h.handleGetReading)
	mux.HandleFunc("POST /reading/lessons/{id}/passages", h.handleAddReadingPassage)
	mux.HandleFunc("POST /reading/lessons/{id}/exercises", h.handlePrepareReading)
	mux.HandleFunc("GET /reading/preparations/{operation_id}", h.handleGetReadingPreparation)
	mux.HandleFunc("GET /reading/examples", h.handleListReadingExamples)
	mux.HandleFunc("POST /reading/examples/{passage_id}", h.handleImportReadingExample)
}

type readingLessonJSON struct {
	ID            int64   `json:"id"`
	Title         string  `json:"title"`
	SourceURL     *string `json:"source_url"`
	Origin        string  `json:"origin"`
	PackPassageID *string `json:"pack_passage_id"`
	CreatedAt     string  `json:"created_at"`
}

type readingPassageJSON struct {
	ID        int64                   `json:"id"`
	Version   int                     `json:"version"`
	Segments  []domain.ReadingSegment `json:"segments"`
	CreatedAt string                  `json:"created_at"`
}

type readingExerciseJSON struct {
	ID          int64                          `json:"id"`
	PassageID   int64                          `json:"passage_id"`
	Status      string                         `json:"status"`
	FailureCode *string                        `json:"failure_code"`
	Generator   string                         `json:"generator"`
	CreatedAt   string                         `json:"created_at"`
	Content     *domain.ReadingExerciseContent `json:"content"`
}

type readingPreparationJSON struct {
	ID           int64   `json:"id"`
	OperationID  string  `json:"operation_id"`
	PassageID    int64   `json:"passage_id"`
	AfterUnknown bool    `json:"after_unknown"`
	StartedAt    string  `json:"started_at"`
	DeadlineAt   string  `json:"deadline_at"`
	FinishedAt   *string `json:"finished_at"`
	State        string  `json:"state"`
	ExerciseID   *int64  `json:"exercise_id"`
}

func toReadingLesson(l domain.ReadingLesson) readingLessonJSON {
	return readingLessonJSON{ID: l.ID, Title: l.Title, SourceURL: optString(l.SourceURL), Origin: l.Origin, PackPassageID: optString(l.PackPassageID), CreatedAt: ts(l.CreatedAt)}
}

func toReadingExercise(e domain.ReadingExercise, withContent bool) readingExerciseJSON {
	out := readingExerciseJSON{ID: e.ID, PassageID: e.PassageID, Status: e.Status, FailureCode: optString(e.FailureCode), Generator: e.Generator, CreatedAt: ts(e.CreatedAt)}
	if withContent {
		out.Content = e.Content
	}
	return out
}

func toReadingPreparation(p domain.ReadingPreparation, now time.Time) readingPreparationJSON {
	return readingPreparationJSON{ID: p.ID, OperationID: p.OperationID, PassageID: p.PassageID, AfterUnknown: p.AfterUnknown,
		StartedAt: ts(p.StartedAt), DeadlineAt: ts(p.DeadlineAt), FinishedAt: listeningOptTime(p.FinishedAt), State: p.State(now), ExerciseID: p.ExerciseID}
}

func (h *Handler) readingGeneration() listeningGenerationResponse {
	enabled, name := h.reading.GeneratorEnabled()
	out := listeningGenerationResponse{Enabled: enabled}
	if enabled {
		out.Generator = &name
	}
	return out
}

func (h *Handler) toReadingView(v *application.ReadingLessonView) map[string]any {
	ex := make([]readingExerciseJSON, 0, len(v.Exercises))
	for _, e := range v.Exercises {
		ex = append(ex, toReadingExercise(e, true))
	}
	preps := make([]readingPreparationJSON, 0, len(v.Preparations))
	for _, p := range v.Preparations {
		preps = append(preps, toReadingPreparation(p, v.Now))
	}
	return map[string]any{
		"lesson":       toReadingLesson(v.Lesson),
		"passage":      readingPassageJSON{ID: v.Passage.ID, Version: v.Passage.Version, Segments: v.Passage.Segments, CreatedAt: ts(v.Passage.CreatedAt)},
		"versions":     v.Versions,
		"exercises":    ex,
		"preparations": preps,
		"state":        v.State,
		"generation":   h.readingGeneration(),
	}
}

func (h *Handler) readingUnavailable(w http.ResponseWriter) bool {
	if h.reading == nil {
		writeError(w, http.StatusServiceUnavailable, "reading lessons are not available on this server")
		return true
	}
	return false
}

func writeReadingError(w http.ResponseWriter, err error, action string) {
	switch {
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "reading lesson or example not found")
	case errors.Is(err, domain.ErrReadingPackConflict):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "pack_conflict"})
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusUnprocessableEntity, err.Error())
	default:
		writeError(w, http.StatusInternalServerError, "could not "+action)
	}
}

// handleListReading lists lessons with their derived state. No provider call.
func (h *Handler) handleListReading(w http.ResponseWriter, r *http.Request) {
	if h.readingUnavailable(w) {
		return
	}
	rows, err := h.reading.ListLessons(r.Context())
	if err != nil {
		writeReadingError(w, err, "list reading lessons")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		out = append(out, map[string]any{"lesson": toReadingLesson(row.Lesson), "passage_version": row.PassageVersion, "paragraphs": row.Paragraphs, "state": row.State})
	}
	writeJSON(w, http.StatusOK, map[string]any{"lessons": out, "generation": h.readingGeneration()})
}

type createReadingRequest struct {
	Title     string `json:"title"`
	Text      string `json:"text"`
	SourceURL string `json:"source_url"`
}

// handleCreateReading saves a title, a French passage and an optional https
// source link (stored, never fetched). 201, 400, 413, 422.
func (h *Handler) handleCreateReading(w http.ResponseWriter, r *http.Request) {
	if h.readingUnavailable(w) {
		return
	}
	var req createReadingRequest
	if !decodeListening(w, r, &req) {
		return
	}
	v, err := h.reading.CreateLesson(r.Context(), req.Title, req.Text, req.SourceURL)
	if err != nil {
		writeReadingError(w, err, "save the reading lesson")
		return
	}
	writeJSON(w, http.StatusCreated, h.toReadingView(v))
}

// handleGetReading returns one lesson. It never calls a provider.
func (h *Handler) handleGetReading(w http.ResponseWriter, r *http.Request) {
	if h.readingUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	v, err := h.reading.GetLesson(r.Context(), id)
	if err != nil {
		writeReadingError(w, err, "read the reading lesson")
		return
	}
	writeJSON(w, http.StatusOK, h.toReadingView(v))
}

type addReadingPassageRequest struct {
	Text string `json:"text"`
}

// handleAddReadingPassage stores the next passage version of a learner lesson.
func (h *Handler) handleAddReadingPassage(w http.ResponseWriter, r *http.Request) {
	if h.readingUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	var req addReadingPassageRequest
	if !decodeListening(w, r, &req) {
		return
	}
	v, err := h.reading.AddPassage(r.Context(), id, req.Text)
	if err != nil {
		writeReadingError(w, err, "save the passage")
		return
	}
	writeJSON(w, http.StatusCreated, h.toReadingView(v))
}

// handleListReadingExamples lists the embedded authored pack (no text).
func (h *Handler) handleListReadingExamples(w http.ResponseWriter, r *http.Request) {
	if h.readingUnavailable(w) {
		return
	}
	ex, err := h.reading.ListExamples(r.Context())
	if err != nil {
		writeReadingError(w, err, "list reading examples")
		return
	}
	out := make([]map[string]any, 0, len(ex))
	for _, e := range ex {
		out = append(out, map[string]any{"id": e.ID, "title": e.Title, "format": e.Format, "style_level": e.StyleLevel,
			"paragraphs": e.Paragraphs, "questions": e.Questions, "has_inference": e.HasInference, "imported_lesson_id": e.ImportedLessonID})
	}
	writeJSON(w, http.StatusOK, map[string]any{"pack": domain.ReadingPackID,
		"notice": "Authored practice material: not an official exam item, no certified CEFR level.", "examples": out})
}

// handleImportReadingExample imports one authored passage with its reviewed
// exercise. No provider call. 201 new; 200 already imported (replay); 404; 409.
func (h *Handler) handleImportReadingExample(w http.ResponseWriter, r *http.Request) {
	if h.readingUnavailable(w) {
		return
	}
	v, replay, err := h.reading.ImportExample(r.Context(), r.PathValue("passage_id"))
	if err != nil {
		writeReadingError(w, err, "import the example")
		return
	}
	status := http.StatusCreated
	if replay {
		status = http.StatusOK
		w.Header().Set("Idempotency-Replayed", "true")
	}
	writeJSON(w, status, h.toReadingView(v))
}

func toReadingPreparationResult(res *application.ReadingPreparationResult, now time.Time) map[string]any {
	out := map[string]any{"preparation": nil, "exercise": nil}
	if res == nil {
		return out
	}
	out["preparation"] = toReadingPreparation(res.Preparation, now)
	if res.Exercise != nil {
		out["exercise"] = toReadingExercise(*res.Exercise, false)
	}
	return out
}

// handlePrepareReading is the one explicit provider call (the Listening
// contract): optional UUID Idempotency-Key, optional {"confirm_unknown_retry":
// true}; the call is not canceled when the client goes away. 201 {preparation,
// exercise}; 200 same-key replay; 502/504 stored failure or unknown outcome;
// 409 {code}: preparation_in_progress, outcome_unknown, key_conflict; 503
// disabled (nothing stored); 404; 400.
func (h *Handler) handlePrepareReading(w http.ResponseWriter, r *http.Request) {
	if h.readingUnavailable(w) {
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
	var req prepareListeningRequest
	if !decodeOptionalListening(w, r, &req) {
		return
	}
	res, replay, err := h.reading.PrepareExercise(context.WithoutCancel(r.Context()), application.ReadingPrepareRequest{
		LessonID: id, OperationID: key, ConfirmUnknownRetry: req.ConfirmUnknownRetry,
	})
	now := h.reading.Now()
	if res != nil {
		w.Header().Set("Idempotency-Key", res.Preparation.OperationID)
	}
	var genErr *application.ReadingGenerationError
	switch {
	case errors.As(err, &genErr):
		status, msg := http.StatusBadGateway, "the exercise provider is unavailable; the passage is kept"
		switch {
		case errors.Is(err, domain.ErrProviderTimeout):
			status, msg = http.StatusGatewayTimeout, "the exercise provider timed out, so the outcome is unknown; the passage is kept"
		case errors.Is(err, domain.ErrOutcomeUnknown):
			msg = "the request reached the exercise provider but no usable answer came back, so the outcome is unknown; the passage is kept"
		case errors.Is(err, domain.ErrValidation):
			msg = "the exercise provider returned output that does not fit the passage (for example a citation that is not in it); the passage is kept"
		}
		body := toReadingPreparationResult(res, now)
		body["error"] = msg
		writeJSON(w, status, body)
	case errors.Is(err, domain.ErrReadingDisabled):
		writeError(w, http.StatusServiceUnavailable, "reading exercise generation is not enabled (READING_PROVIDER)")
	case errors.Is(err, domain.ErrReadingPreparationInProgress):
		body := toReadingPreparationResult(res, now)
		body["error"], body["code"] = err.Error(), "preparation_in_progress"
		writeJSON(w, http.StatusConflict, body)
	case errors.Is(err, domain.ErrReadingOutcomeUnknown):
		body := toReadingPreparationResult(res, now)
		body["error"], body["code"] = err.Error(), "outcome_unknown"
		writeJSON(w, http.StatusConflict, body)
	case errors.Is(err, domain.ErrReadingOperationConflict):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "key_conflict"})
	case err != nil:
		writeReadingError(w, err, "prepare the exercise")
	case replay:
		w.Header().Set("Idempotency-Replayed", "true")
		writeJSON(w, http.StatusOK, toReadingPreparationResult(res, now))
	default:
		writeJSON(w, http.StatusCreated, toReadingPreparationResult(res, now))
	}
}

// handleGetReadingPreparation looks an attempt up by its key. 404 means nothing
// is recorded under the key; it never proves the request was not received.
func (h *Handler) handleGetReadingPreparation(w http.ResponseWriter, r *http.Request) {
	if h.readingUnavailable(w) {
		return
	}
	res, err := h.reading.GetPreparation(r.Context(), r.PathValue("operation_id"))
	switch {
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusBadRequest, "invalid idempotency key")
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "no preparation is recorded under this key")
	case err != nil:
		writeReadingError(w, err, "read the preparation")
	default:
		writeJSON(w, http.StatusOK, toReadingPreparationResult(res, h.reading.Now()))
	}
}
