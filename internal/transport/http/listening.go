package http

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// ListeningService is the Exam Listening Lesson v1 application capability.
type ListeningService interface {
	GeneratorEnabled() (bool, string)
	CreateMaterial(ctx context.Context, sourceURL, title, transcript string) (*application.ListeningLesson, error)
	AddTranscript(ctx context.Context, materialID int64, transcript string) (*application.ListeningLesson, error)
	GetLesson(ctx context.Context, materialID int64) (*application.ListeningLesson, error)
	ListMaterials(ctx context.Context) ([]application.ListeningMaterialSummary, error)
	PrepareExercise(ctx context.Context, req application.ListeningPrepareRequest) (*application.ListeningPreparationResult, bool, error)
	GetPreparation(ctx context.Context, operationID string) (*application.ListeningPreparationResult, error)
	ListScripts(ctx context.Context) ([]application.ListeningScriptSummary, error)
	ImportScript(ctx context.Context, scriptID string) (*application.ListeningLesson, bool, error)
	ScriptUpdatePreview(ctx context.Context, materialID int64) (*application.ListeningScriptUpdatePreview, error)
	UpdateScript(ctx context.Context, materialID int64, fromRevision int, packFingerprint string) (*application.ListeningScriptUpdateResult, bool, error)
	GetScriptRevision(ctx context.Context, materialID int64, revision int) (*domain.ListeningScriptRevision, int, error)
	Now() time.Time
}

// WithListening enables the private /listening routes. Without it they answer
// 503. The public demo never reaches them: its boundary is an allowlist.
func WithListening(service ListeningService) HandlerOption {
	return func(handler *Handler) { handler.listening = service }
}

// Request bodies are bounded above the transcript limit so the domain reports
// an oversized transcript with its own message.
const maxListeningBody = 32 << 10

func (h *Handler) registerListeningRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /listening/materials", h.handleListListening)
	mux.HandleFunc("POST /listening/materials", h.handleCreateListening)
	mux.HandleFunc("GET /listening/materials/{id}", h.handleGetListening)
	mux.HandleFunc("POST /listening/materials/{id}/transcripts", h.handleAddListeningTranscript)
	mux.HandleFunc("POST /listening/materials/{id}/exercises", h.handleGenerateListeningExercise)
	mux.HandleFunc("GET /listening/preparations/{operation_id}", h.handleGetListeningPreparation)
	mux.HandleFunc("GET /listening/scripts", h.handleListListeningScripts)
	mux.HandleFunc("POST /listening/scripts/{script_id}", h.handleImportListeningScript)
	mux.HandleFunc("GET /listening/materials/{id}/script-update", h.handleListeningScriptUpdatePreview)
	mux.HandleFunc("POST /listening/materials/{id}/script-update", h.handleListeningScriptUpdate)
	mux.HandleFunc("GET /listening/materials/{id}/revisions/{revision}", h.handleGetListeningScriptRevision)
	h.registerListeningDailyRoutes(mux)
}

// listeningMaterialResponse: video_id and source_url are null for an authored
// script (source_kind "authored_script"), which has no link, video or
// timestamp; pack_script_id is null for YouTube material.
type listeningMaterialResponse struct {
	ID           int64   `json:"id"`
	SourceKind   string  `json:"source_kind"`
	VideoID      *string `json:"video_id"`
	SourceURL    *string `json:"source_url"`
	PackScriptID *string `json:"pack_script_id"`
	Title        string  `json:"title"`
	CreatedAt    string  `json:"created_at"`
}

type listeningTranscriptResponse struct {
	ID            int64                      `json:"id"`
	Version       int                        `json:"version"`
	HasTimestamps bool                       `json:"has_timestamps"`
	Segments      []domain.TranscriptSegment `json:"segments"`
	CreatedAt     string                     `json:"created_at"`
}

type listeningExerciseResponse struct {
	ID           int64                            `json:"id"`
	TranscriptID int64                            `json:"transcript_id"`
	Status       string                           `json:"status"`
	FailureCode  *string                          `json:"failure_code"`
	Generator    string                           `json:"generator"`
	CreatedAt    string                           `json:"created_at"`
	Content      *domain.ListeningExerciseContent `json:"content"`
}

type listeningGenerationResponse struct {
	Enabled   bool    `json:"enabled"`
	Generator *string `json:"generator"`
}

type listeningLessonResponse struct {
	Material   listeningMaterialResponse    `json:"material"`
	Transcript *listeningTranscriptResponse `json:"transcript"`
	Exercises  []listeningExerciseResponse  `json:"exercises"`
	// CurrentExerciseID is the exercise the lesson shows (null when none): the
	// newest completed one on the latest transcript, or for an authored script
	// its authored exercise, never a generated one.
	CurrentExerciseID *int64 `json:"current_exercise_id"`
	// ScriptRevision is an authored script's current revision against the
	// server's pack (null for YouTube material).
	ScriptRevision *listeningScriptStateResponse `json:"script_revision"`
	Generation     listeningGenerationResponse   `json:"generation"`
	// Daily Listening: derived state, playlist membership and every attempt.
	State         string                          `json:"state"`
	InPlaylist    bool                            `json:"in_playlist"`
	Preparations  []listeningPreparationResponse  `json:"preparations"`
	Notifications []listeningNotificationResponse `json:"notifications"`
	Notification  listeningNotifySettings         `json:"notification"`
}

type listeningSummaryResponse struct {
	Material          listeningMaterialResponse  `json:"material"`
	TranscriptVersion *int                       `json:"transcript_version"`
	SegmentCount      int                        `json:"segment_count"`
	LatestExercise    *listeningExerciseResponse `json:"latest_exercise"`
	State             string                     `json:"state"`
	InPlaylist        bool                       `json:"in_playlist"`
}

func ts(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

func toListeningMaterial(m domain.ListeningMaterial) listeningMaterialResponse {
	return listeningMaterialResponse{ID: m.ID, SourceKind: m.SourceKind, VideoID: optionalString(m.VideoID), SourceURL: optionalString(m.SourceURL),
		PackScriptID: optionalString(m.PackScriptID), Title: m.Title, CreatedAt: ts(m.CreatedAt)}
}

func optionalString(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// toListeningExercise includes the content only when asked: list rows carry
// the status, never the answers.
func toListeningExercise(e domain.ListeningExercise, withContent bool) listeningExerciseResponse {
	out := listeningExerciseResponse{ID: e.ID, TranscriptID: e.TranscriptID, Status: e.Status, Generator: e.Generator, CreatedAt: ts(e.CreatedAt)}
	if e.FailureCode != "" {
		code := e.FailureCode
		out.FailureCode = &code
	}
	if withContent {
		out.Content = e.Content
	}
	return out
}

func (h *Handler) listeningGeneration() listeningGenerationResponse {
	enabled, name := h.listening.GeneratorEnabled()
	out := listeningGenerationResponse{Enabled: enabled}
	if enabled {
		out.Generator = &name
	}
	return out
}

func (h *Handler) toListeningLesson(l *application.ListeningLesson) listeningLessonResponse {
	out := listeningLessonResponse{
		Material: toListeningMaterial(l.Material), Exercises: []listeningExerciseResponse{}, Generation: h.listeningGeneration(),
		State: l.Status.State, InPlaylist: l.Status.InPlaylist, Notification: h.listeningNotifySettings(),
		Preparations: []listeningPreparationResponse{}, Notifications: []listeningNotificationResponse{},
	}
	for _, p := range l.Status.Preparations {
		out.Preparations = append(out.Preparations, toListeningPreparation(p, l.Now))
	}
	for _, n := range l.Status.Notifications {
		out.Notifications = append(out.Notifications, toListeningNotification(n, l.Now))
	}
	if l.Transcript != nil {
		t := l.Transcript
		out.Transcript = &listeningTranscriptResponse{ID: t.ID, Version: t.Version, HasTimestamps: t.HasTimestamps, Segments: t.Segments, CreatedAt: ts(t.CreatedAt)}
	}
	for _, e := range l.Exercises {
		out.Exercises = append(out.Exercises, toListeningExercise(e, true))
	}
	if l.Current != nil {
		id := l.Current.ID
		out.CurrentExerciseID = &id
	}
	if l.Script != nil {
		st := toListeningScriptState(*l.Script)
		out.ScriptRevision = &st
	}
	return out
}

func (h *Handler) listeningUnavailable(w http.ResponseWriter) bool {
	if h.listening == nil {
		writeError(w, http.StatusServiceUnavailable, "listening lessons are not available on this server")
		return true
	}
	return false
}

// decodeListening decodes one bounded JSON object with no unknown fields and no
// trailing content.
func decodeListening(w http.ResponseWriter, r *http.Request, into any) bool {
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxListeningBody))
	dec.DisallowUnknownFields()
	if err := dec.Decode(into); err != nil {
		var tooBig *http.MaxBytesError
		if errors.As(err, &tooBig) {
			writeError(w, http.StatusRequestEntityTooLarge, "request body is too large")
		} else {
			writeError(w, http.StatusBadRequest, "invalid JSON body")
		}
		return false
	}
	var extra any
	if err := dec.Decode(&extra); err != io.EOF {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return false
	}
	return true
}

// writeListeningError maps service errors. Validation messages name the field
// or segment number, never the submitted text.
func writeListeningError(w http.ResponseWriter, err error, action string) {
	switch {
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "listening material not found")
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusUnprocessableEntity, err.Error())
	case errors.Is(err, domain.ErrListeningScriptConflict):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "script_conflict"})
	case errors.Is(err, domain.ErrListeningScriptFixed), errors.Is(err, domain.ErrListeningScriptExerciseFixed):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "authored_script"})
	case errors.Is(err, domain.ErrListeningNotAuthoredScript):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "not_authored_script"})
	case errors.Is(err, domain.ErrListeningScriptNotInPack):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "script_not_in_pack"})
	case errors.Is(err, domain.ErrListeningScriptTitleChanged):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "script_title_changed"})
	default:
		writeError(w, http.StatusInternalServerError, "could not "+action)
	}
}

// handleListListeningScripts lists the embedded authored scripts (no line and
// no key) and whether each is imported. It never calls a provider.
func (h *Handler) handleListListeningScripts(w http.ResponseWriter, r *http.Request) {
	if h.listeningUnavailable(w) {
		return
	}
	rows, err := h.listening.ListScripts(r.Context())
	if err != nil {
		writeListeningError(w, err, "list listening scripts")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, s := range rows {
		out = append(out, map[string]any{"id": s.ID, "title": s.Title, "genre": s.Genre, "style_level": s.StyleLevel,
			"source_pack": s.SourcePack, "notice": s.Notice, "lines": s.Lines, "questions": s.Questions,
			"imported_material_id": s.ImportedMaterialID, "imported_revision": positiveInt(s.ImportedRevision), "pack_status": optionalString(s.PackStatus)})
	}
	writeJSON(w, http.StatusOK, map[string]any{"pack": domain.ListeningScriptPackID, "scripts": out})
}

// handleImportListeningScript imports one authored script (material with no
// link, its lines as an untimed transcript, its authored exercise) in one
// transaction. No provider call. 201 new; 200 already imported with the
// pack's content (replay); 404 unknown script; 409 script_conflict (the
// lesson's current revision differs from the pack: nothing is written, and the
// body names the lesson, its revision and pack_status; an update is the
// explicit script-update route).
func (h *Handler) handleImportListeningScript(w http.ResponseWriter, r *http.Request) {
	if h.listeningUnavailable(w) {
		return
	}
	lesson, replay, err := h.listening.ImportScript(r.Context(), r.PathValue("script_id"))
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "listening script not found")
		return
	}
	var conflict *application.ListeningScriptConflictError
	if errors.As(err, &conflict) {
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "script_conflict",
			"material_id": conflict.MaterialID, "current_revision": conflict.Revision, "pack_status": conflict.PackStatus})
		return
	}
	if err != nil {
		writeListeningError(w, err, "import the listening script")
		return
	}
	status := http.StatusCreated
	if replay {
		status = http.StatusOK
		w.Header().Set("Idempotency-Replayed", "true")
	}
	writeJSON(w, status, h.toListeningLesson(lesson))
}

// handleListListening lists materials with their transcript and latest
// exercise status (no answers). It never calls a provider.
func (h *Handler) handleListListening(w http.ResponseWriter, r *http.Request) {
	if h.listeningUnavailable(w) {
		return
	}
	rows, err := h.listening.ListMaterials(r.Context())
	if err != nil {
		writeListeningError(w, err, "list listening materials")
		return
	}
	out := make([]listeningSummaryResponse, 0, len(rows))
	for _, row := range rows {
		s := listeningSummaryResponse{Material: toListeningMaterial(row.Material), SegmentCount: row.SegmentCount, State: row.State, InPlaylist: row.InPlaylist}
		if row.TranscriptVersion > 0 {
			v := row.TranscriptVersion
			s.TranscriptVersion = &v
		}
		if row.LatestExercise != nil {
			e := toListeningExercise(*row.LatestExercise, false)
			s.LatestExercise = &e
		}
		out = append(out, s)
	}
	writeJSON(w, http.StatusOK, map[string]any{"materials": out, "generation": h.listeningGeneration()})
}

type createListeningRequest struct {
	SourceURL  string `json:"source_url"`
	Title      string `json:"title"`
	Transcript string `json:"transcript"`
}

// handleCreateListening saves a link, a title and an optional transcript. The
// link is validated as text and never fetched. 201, 400, 413, 422, 500.
func (h *Handler) handleCreateListening(w http.ResponseWriter, r *http.Request) {
	if h.listeningUnavailable(w) {
		return
	}
	var req createListeningRequest
	if !decodeListening(w, r, &req) {
		return
	}
	lesson, err := h.listening.CreateMaterial(r.Context(), req.SourceURL, req.Title, req.Transcript)
	if err != nil {
		writeListeningError(w, err, "save listening material")
		return
	}
	writeJSON(w, http.StatusCreated, h.toListeningLesson(lesson))
}

// handleGetListening returns one lesson. It never calls a provider.
func (h *Handler) handleGetListening(w http.ResponseWriter, r *http.Request) {
	if h.listeningUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	lesson, err := h.listening.GetLesson(r.Context(), id)
	if err != nil {
		writeListeningError(w, err, "read listening material")
		return
	}
	writeJSON(w, http.StatusOK, h.toListeningLesson(lesson))
}

type addListeningTranscriptRequest struct {
	Transcript string `json:"transcript"`
}

// handleAddListeningTranscript stores the next transcript version. Earlier
// versions and their exercises are kept. 201, 400, 404, 409 authored_script
// (an authored script is fixed text), 413, 422, 500.
func (h *Handler) handleAddListeningTranscript(w http.ResponseWriter, r *http.Request) {
	if h.listeningUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	var req addListeningTranscriptRequest
	if !decodeListening(w, r, &req) {
		return
	}
	lesson, err := h.listening.AddTranscript(r.Context(), id, req.Transcript)
	if err != nil {
		writeListeningError(w, err, "save transcript")
		return
	}
	writeJSON(w, http.StatusCreated, h.toListeningLesson(lesson))
}

type prepareListeningRequest struct {
	ConfirmUnknownRetry bool `json:"confirm_unknown_retry"`
}

// decodeOptionalListening accepts an empty body or one bounded JSON object.
func decodeOptionalListening(w http.ResponseWriter, r *http.Request, into any) bool {
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 4<<10))
	if err != nil {
		writeError(w, http.StatusRequestEntityTooLarge, "request body is too large")
		return false
	}
	if len(raw) == 0 {
		return true
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	var extra any
	if dec.Decode(into) != nil || dec.Decode(&extra) != io.EOF {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return false
	}
	return true
}

// optionalKey reads at most one Idempotency-Key header.
func optionalKey(w http.ResponseWriter, r *http.Request) (string, bool) {
	keys := r.Header.Values("Idempotency-Key")
	switch {
	case len(keys) == 0:
		return "", true
	case len(keys) > 1:
		writeError(w, http.StatusBadRequest, "at most one Idempotency-Key header is allowed")
		return "", false
	}
	if _, err := domain.NormalizeAnnotationOperationID(keys[0]); err != nil {
		writeError(w, http.StatusBadRequest, "invalid idempotency key")
		return "", false
	}
	return keys[0], true
}

func (h *Handler) toPreparationResult(res *application.ListeningPreparationResult, now time.Time) map[string]any {
	out := map[string]any{"preparation": nil, "exercise": nil}
	if res == nil {
		return out
	}
	out["preparation"] = toListeningPreparation(res.Preparation, now)
	if res.Exercise != nil {
		out["exercise"] = toListeningExercise(*res.Exercise, false)
	}
	return out
}

// handleGenerateListeningExercise is the explicit Prepare button: one provider
// call through the shared preparation path. An optional UUID Idempotency-Key
// makes it safe to resend after a lost response; the attempt is recorded before
// the call and can be looked up at GET /listening/preparations/{key}. The
// optional body {"confirm_unknown_retry": true} acknowledges that the previous
// attempt's outcome is unknown. The call is not canceled when the client goes
// away, so its result is stored either way.
//
// Status: 201 completed ({preparation, exercise}); 200 same-key replay (header
// Idempotency-Replayed: true) in any state; 502/504 with the stored failed
// exercise and attempt (provider failure, unknown outcome, invalid output);
// 409 {code}: no_transcript (no call), preparation_in_progress or
// outcome_unknown (no call; the blocking attempt is returned), key_conflict;
// 503 generation not enabled (nothing stored); 404 unknown material; 400.
func (h *Handler) handleGenerateListeningExercise(w http.ResponseWriter, r *http.Request) {
	if h.listeningUnavailable(w) {
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
	res, replay, err := h.listening.PrepareExercise(context.WithoutCancel(r.Context()), application.ListeningPrepareRequest{
		MaterialID: id, OperationID: key, ConfirmUnknownRetry: req.ConfirmUnknownRetry,
	})
	now := h.listening.Now()
	if res != nil {
		w.Header().Set("Idempotency-Key", res.Preparation.OperationID)
	}
	var genErr *application.ListeningGenerationError
	switch {
	case errors.As(err, &genErr):
		status, msg := http.StatusBadGateway, "the exercise provider is unavailable; the material and transcript are kept"
		switch {
		case errors.Is(err, domain.ErrProviderTimeout):
			status, msg = http.StatusGatewayTimeout, "the exercise provider timed out, so the outcome is unknown; the material and transcript are kept"
		case errors.Is(err, domain.ErrOutcomeUnknown):
			msg = "the request reached the exercise provider but no usable answer came back, so the outcome is unknown; the material and transcript are kept"
		case errors.Is(err, domain.ErrValidation):
			msg = "the exercise provider returned output that does not fit the transcript; the material and transcript are kept"
		}
		body := h.toPreparationResult(res, now)
		body["error"] = msg
		writeJSON(w, status, body)
	case errors.Is(err, domain.ErrListeningDisabled):
		writeError(w, http.StatusServiceUnavailable, "listening exercise generation is not enabled (LISTENING_PROVIDER)")
	case errors.Is(err, domain.ErrListeningNoTranscript):
		writeJSON(w, http.StatusConflict, map[string]any{"error": domain.ErrListeningNoTranscript.Error(), "code": "no_transcript"})
	case errors.Is(err, domain.ErrListeningPreparationInProgress):
		body := h.toPreparationResult(res, now)
		body["error"], body["code"] = err.Error(), "preparation_in_progress"
		writeJSON(w, http.StatusConflict, body)
	case errors.Is(err, domain.ErrListeningOutcomeUnknown):
		body := h.toPreparationResult(res, now)
		body["error"], body["code"] = err.Error(), "outcome_unknown"
		writeJSON(w, http.StatusConflict, body)
	case errors.Is(err, domain.ErrListeningOperationConflict):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "key_conflict"})
	case err != nil:
		writeListeningError(w, err, "prepare the exercise")
	case replay:
		w.Header().Set("Idempotency-Replayed", "true")
		writeJSON(w, http.StatusOK, h.toPreparationResult(res, now))
	default:
		writeJSON(w, http.StatusCreated, h.toPreparationResult(res, now))
	}
}

// handleGetListeningPreparation looks an attempt up by its key: its state and,
// once finished, its exercise (without content; the lesson read has it). 404
// means nothing is recorded under the key, which never proves it was not sent.
func (h *Handler) handleGetListeningPreparation(w http.ResponseWriter, r *http.Request) {
	if h.listeningUnavailable(w) {
		return
	}
	res, err := h.listening.GetPreparation(r.Context(), r.PathValue("operation_id"))
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "no preparation is recorded under this key")
		return
	}
	if err != nil {
		writeListeningError(w, err, "read the preparation")
		return
	}
	writeJSON(w, http.StatusOK, h.toPreparationResult(res, h.listening.Now()))
}
