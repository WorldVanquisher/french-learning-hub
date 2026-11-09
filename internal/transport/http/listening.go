package http

import (
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
	GenerateExercise(ctx context.Context, materialID int64) (*domain.ListeningExercise, error)
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
}

type listeningMaterialResponse struct {
	ID        int64  `json:"id"`
	VideoID   string `json:"video_id"`
	SourceURL string `json:"source_url"`
	Title     string `json:"title"`
	CreatedAt string `json:"created_at"`
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
	Generation listeningGenerationResponse  `json:"generation"`
}

type listeningSummaryResponse struct {
	Material          listeningMaterialResponse  `json:"material"`
	TranscriptVersion *int                       `json:"transcript_version"`
	SegmentCount      int                        `json:"segment_count"`
	LatestExercise    *listeningExerciseResponse `json:"latest_exercise"`
}

func ts(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

func toListeningMaterial(m domain.ListeningMaterial) listeningMaterialResponse {
	return listeningMaterialResponse{ID: m.ID, VideoID: m.VideoID, SourceURL: m.SourceURL, Title: m.Title, CreatedAt: ts(m.CreatedAt)}
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
	out := listeningLessonResponse{Material: toListeningMaterial(l.Material), Exercises: []listeningExerciseResponse{}, Generation: h.listeningGeneration()}
	if l.Transcript != nil {
		t := l.Transcript
		out.Transcript = &listeningTranscriptResponse{ID: t.ID, Version: t.Version, HasTimestamps: t.HasTimestamps, Segments: t.Segments, CreatedAt: ts(t.CreatedAt)}
	}
	for _, e := range l.Exercises {
		out.Exercises = append(out.Exercises, toListeningExercise(e, true))
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
	default:
		writeError(w, http.StatusInternalServerError, "could not "+action)
	}
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
		s := listeningSummaryResponse{Material: toListeningMaterial(row.Material), SegmentCount: row.SegmentCount}
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
// versions and their exercises are kept. 201, 400, 404, 413, 422, 500.
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

// handleGenerateListeningExercise is the one explicit provider call. Status:
// 201 completed exercise; 503 generation not enabled (nothing stored); 404
// unknown material; 409 no transcript (no call, nothing stored); 502/504 with
// the stored failed exercise for provider failure, timeout or invalid output.
// The request body must be empty.
func (h *Handler) handleGenerateListeningExercise(w http.ResponseWriter, r *http.Request) {
	if h.listeningUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	if body, _ := io.ReadAll(io.LimitReader(r.Body, 1)); len(body) > 0 {
		writeError(w, http.StatusBadRequest, "this request takes no body")
		return
	}
	exercise, err := h.listening.GenerateExercise(r.Context(), id)
	var genErr *application.ListeningGenerationError
	switch {
	case errors.As(err, &genErr):
		status, msg := http.StatusBadGateway, "the exercise provider is unavailable; the material and transcript are kept"
		if errors.Is(err, domain.ErrProviderTimeout) {
			status, msg = http.StatusGatewayTimeout, "the exercise provider timed out; the material and transcript are kept"
		} else if errors.Is(err, domain.ErrValidation) {
			msg = "the exercise provider returned output that does not fit the transcript; the material and transcript are kept"
		}
		writeJSON(w, status, map[string]any{"error": msg, "exercise": toListeningExercise(genErr.Exercise, false)})
	case errors.Is(err, domain.ErrListeningDisabled):
		writeError(w, http.StatusServiceUnavailable, "listening exercise generation is not enabled (LISTENING_PROVIDER)")
	case errors.Is(err, domain.ErrListeningNoTranscript):
		writeError(w, http.StatusConflict, domain.ErrListeningNoTranscript.Error())
	case err != nil:
		writeListeningError(w, err, "prepare the exercise")
	default:
		writeJSON(w, http.StatusCreated, toListeningExercise(*exercise, true))
	}
}
