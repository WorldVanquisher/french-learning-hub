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

// SpeakingService is the Speaking v1 application capability.
type SpeakingService interface {
	Providers() (transcriber, generator string)
	ListPrompts(ctx context.Context) ([]application.SpeakingPromptView, error)
	StartPrompt(ctx context.Context, promptID string) (*application.SpeakingExerciseView, bool, error)
	GetExercise(ctx context.Context, id int64) (*application.SpeakingExerciseView, error)
	ListExercises(ctx context.Context) ([]application.SpeakingExerciseSummary, error)
	AddTake(ctx context.Context, exerciseID int64, t domain.SpeakingTake) (*application.SpeakingExerciseView, error)
	AddTranscript(ctx context.Context, takeID int64, text string, transcriptionID *int64) (*application.SpeakingExerciseView, error)
	Transcribe(ctx context.Context, in application.SpeakingTranscriptionInput) (*application.SpeakingTranscriptionResult, bool, error)
	GetTranscriptionRequest(ctx context.Context, operationID string) (*application.SpeakingTranscriptionResult, error)
	RequestFeedback(ctx context.Context, in application.SpeakingFeedbackRequestInput) (*application.SpeakingFeedbackResult, bool, error)
	GetFeedbackRequest(ctx context.Context, operationID string) (*application.SpeakingFeedbackResult, error)
	Now() time.Time
}

// WithSpeaking enables the private /speaking routes. Without it they answer 503.
// The public demo never reaches them: its boundary is an allowlist.
func WithSpeaking(service SpeakingService) HandlerOption {
	return func(handler *Handler) { handler.speaking = service }
}

// maxSpeakingAudioBody bounds a transcription request: base64 audio of at
// most domain.MaxSpeakingAudioBytes plus a small JSON envelope.
const maxSpeakingAudioBody = (domain.MaxSpeakingAudioBytes/3+1)*4 + 4<<10

// SpeakingAcceptedTypes are the audio types a take may have (see
// domain.SpeakingAudioType); shown to the learner before anything is sent.
var SpeakingAcceptedTypes = []string{"audio/webm", "audio/mp4", "audio/mpeg", "audio/wav"}

func (h *Handler) registerSpeakingRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /speaking/prompts", h.handleListSpeakingPrompts)
	mux.HandleFunc("POST /speaking/prompts/{prompt_id}", h.handleStartSpeakingPrompt)
	mux.HandleFunc("GET /speaking/exercises", h.handleListSpeakingExercises)
	mux.HandleFunc("GET /speaking/exercises/{id}", h.handleGetSpeakingExercise)
	mux.HandleFunc("POST /speaking/exercises/{id}/takes", h.handleAddSpeakingTake)
	mux.HandleFunc("POST /speaking/takes/{id}/transcriptions", h.handleTranscribeSpeakingTake)
	mux.HandleFunc("GET /speaking/transcription-requests/{operation_id}", h.handleGetSpeakingTranscriptionRequest)
	mux.HandleFunc("POST /speaking/takes/{id}/transcripts", h.handleAddSpeakingTranscript)
	mux.HandleFunc("POST /speaking/transcripts/{id}/feedback", h.handleRequestSpeakingFeedback)
	mux.HandleFunc("GET /speaking/feedback-requests/{operation_id}", h.handleGetSpeakingFeedbackRequest)
}

type speakingExerciseJSON struct {
	ID           int64    `json:"id"`
	PromptID     string   `json:"prompt_id"`
	Title        string   `json:"title"`
	Situation    string   `json:"situation"`
	Requirements []string `json:"requirements"`
	SecondsMin   int      `json:"seconds_min"`
	SecondsMax   int      `json:"seconds_max"`
	CreatedAt    string   `json:"created_at"`
}

type speakingTakeJSON struct {
	ID          int64   `json:"id"`
	Number      int     `json:"number"`
	AudioSource string  `json:"audio_source"`
	AudioMIME   *string `json:"audio_mime"`
	AudioBytes  *int64  `json:"audio_bytes"`
	AudioSHA256 *string `json:"audio_sha256"`
	DurationMS  *int    `json:"duration_ms"`
	CreatedAt   string  `json:"created_at"`
}

type speakingTranscriptionJSON struct {
	ID          int64   `json:"id"`
	TakeID      int64   `json:"take_id"`
	Status      string  `json:"status"`
	FailureCode *string `json:"failure_code"`
	Transcriber string  `json:"transcriber"`
	Text        *string `json:"text"`
	CreatedAt   string  `json:"created_at"`
}

type speakingTranscriptJSON struct {
	ID              int64  `json:"id"`
	TakeID          int64  `json:"take_id"`
	Version         int    `json:"version"`
	Text            string `json:"text"`
	WordCount       int    `json:"word_count"`
	Origin          string `json:"origin"`
	TranscriptionID *int64 `json:"transcription_id"`
	CreatedAt       string `json:"created_at"`
}

type speakingFeedbackJSON struct {
	ID           int64                           `json:"id"`
	TranscriptID int64                           `json:"transcript_id"`
	Status       string                          `json:"status"`
	FailureCode  *string                         `json:"failure_code"`
	Generator    string                          `json:"generator"`
	CreatedAt    string                          `json:"created_at"`
	Content      *domain.SpeakingFeedbackContent `json:"content"`
}

type speakingRequestJSON struct {
	ID           int64   `json:"id"`
	OperationID  string  `json:"operation_id"`
	TakeID       *int64  `json:"take_id,omitempty"`
	TranscriptID *int64  `json:"transcript_id,omitempty"`
	AfterUnknown bool    `json:"after_unknown"`
	StartedAt    string  `json:"started_at"`
	DeadlineAt   string  `json:"deadline_at"`
	FinishedAt   *string `json:"finished_at"`
	State        string  `json:"state"`
	ResultID     *int64  `json:"result_id"`
}

func toSpeakingExercise(e domain.SpeakingExercise) speakingExerciseJSON {
	reqs := e.Requirements
	if reqs == nil {
		reqs = []string{}
	}
	return speakingExerciseJSON{ID: e.ID, PromptID: e.PromptID, Title: e.Title, Situation: e.Situation, Requirements: reqs,
		SecondsMin: e.SecondsMin, SecondsMax: e.SecondsMax, CreatedAt: ts(e.CreatedAt)}
}

func toSpeakingTake(t domain.SpeakingTake) speakingTakeJSON {
	out := speakingTakeJSON{ID: t.ID, Number: t.Number, AudioSource: t.AudioSource, CreatedAt: ts(t.CreatedAt)}
	if t.AudioSource != domain.SpeakingAudioNone {
		size, dur := t.AudioBytes, t.DurationMS
		out.AudioMIME, out.AudioBytes, out.AudioSHA256, out.DurationMS = optString(t.AudioMIME), &size, optString(t.AudioSHA256), &dur
	}
	return out
}

func toSpeakingTranscription(t domain.SpeakingTranscription) speakingTranscriptionJSON {
	out := speakingTranscriptionJSON{ID: t.ID, TakeID: t.TakeID, Status: t.Status, FailureCode: optString(t.FailureCode), Transcriber: t.Transcriber, CreatedAt: ts(t.CreatedAt)}
	if t.Status == domain.ListeningExerciseCompleted {
		text := t.Text
		out.Text = &text
	}
	return out
}

func toSpeakingTranscript(t domain.SpeakingTranscript) speakingTranscriptJSON {
	return speakingTranscriptJSON{ID: t.ID, TakeID: t.TakeID, Version: t.Version, Text: t.Text, WordCount: t.WordCount, Origin: t.Origin,
		TranscriptionID: t.TranscriptionID, CreatedAt: ts(t.CreatedAt)}
}

func toSpeakingFeedback(f domain.SpeakingFeedback) speakingFeedbackJSON {
	return speakingFeedbackJSON{ID: f.ID, TranscriptID: f.TranscriptID, Status: f.Status, FailureCode: optString(f.FailureCode), Generator: f.Generator,
		CreatedAt: ts(f.CreatedAt), Content: f.Content}
}

func toSpeakingTranscriptionRequest(r domain.SpeakingTranscriptionRequest, now time.Time) speakingRequestJSON {
	take := r.TakeID
	return speakingRequestJSON{ID: r.ID, OperationID: r.OperationID, TakeID: &take, AfterUnknown: r.AfterUnknown, StartedAt: ts(r.StartedAt),
		DeadlineAt: ts(r.DeadlineAt), FinishedAt: listeningOptTime(r.FinishedAt), State: r.State(now), ResultID: r.TranscriptionID}
}

func toSpeakingFeedbackRequest(r domain.SpeakingFeedbackRequest, now time.Time) speakingRequestJSON {
	transcript := r.TranscriptID
	return speakingRequestJSON{ID: r.ID, OperationID: r.OperationID, TranscriptID: &transcript, AfterUnknown: r.AfterUnknown, StartedAt: ts(r.StartedAt),
		DeadlineAt: ts(r.DeadlineAt), FinishedAt: listeningOptTime(r.FinishedAt), State: r.State(now), ResultID: r.FeedbackID}
}

func (h *Handler) speakingProviders() map[string]any {
	tr, gen := h.speaking.Providers()
	provider := func(name string) map[string]any {
		out := map[string]any{"enabled": name != "", "name": nil}
		if name != "" {
			out["name"] = name
		}
		return out
	}
	return map[string]any{"transcription": provider(tr), "feedback": provider(gen)}
}

func speakingLimits() map[string]any {
	return map[string]any{"max_audio_bytes": domain.MaxSpeakingAudioBytes, "max_duration_ms": domain.MaxSpeakingDurationMS,
		"accepted_types": SpeakingAcceptedTypes, "max_transcript_chars": domain.MaxSpeakingTranscriptRunes,
		"max_takes": domain.MaxSpeakingTakes, "max_transcript_versions": domain.MaxSpeakingTranscriptVersions}
}

func (h *Handler) toSpeakingView(v *application.SpeakingExerciseView) map[string]any {
	takes := make([]speakingTakeJSON, 0, len(v.Takes))
	for _, t := range v.Takes {
		takes = append(takes, toSpeakingTake(t))
	}
	trs := make([]speakingTranscriptionJSON, 0, len(v.Transcriptions))
	for _, t := range v.Transcriptions {
		trs = append(trs, toSpeakingTranscription(t))
	}
	trReqs := make([]speakingRequestJSON, 0, len(v.TranscriptionRequests))
	for _, r := range v.TranscriptionRequests {
		trReqs = append(trReqs, toSpeakingTranscriptionRequest(r, v.Now))
	}
	scripts := make([]speakingTranscriptJSON, 0, len(v.Transcripts))
	for _, t := range v.Transcripts {
		scripts = append(scripts, toSpeakingTranscript(t))
	}
	fb := make([]speakingFeedbackJSON, 0, len(v.Feedback))
	for _, f := range v.Feedback {
		fb = append(fb, toSpeakingFeedback(f))
	}
	fbReqs := make([]speakingRequestJSON, 0, len(v.FeedbackRequests))
	for _, r := range v.FeedbackRequests {
		fbReqs = append(fbReqs, toSpeakingFeedbackRequest(r, v.Now))
	}
	return map[string]any{"exercise": toSpeakingExercise(v.Exercise), "takes": takes, "transcriptions": trs, "transcription_requests": trReqs,
		"transcripts": scripts, "feedback": fb, "feedback_requests": fbReqs, "example_transcript": v.ExampleTranscript,
		"providers": h.speakingProviders(), "limits": speakingLimits(), "word_convention": WritingWordConvention}
}

func (h *Handler) speakingUnavailable(w http.ResponseWriter) bool {
	if h.speaking == nil {
		writeError(w, http.StatusServiceUnavailable, "speaking practice is not available on this server")
		return true
	}
	return false
}

func writeSpeakingError(w http.ResponseWriter, err error, action string) {
	conflict := func(code string) {
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": code})
	}
	switch {
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "speaking exercise, take, transcript or prompt not found")
	case errors.Is(err, domain.ErrSpeakingTranscriptUnchanged):
		conflict("unchanged")
	case errors.Is(err, domain.ErrSpeakingTooManyTakes):
		conflict("too_many_takes")
	case errors.Is(err, domain.ErrSpeakingTooManyVersions):
		conflict("too_many_versions")
	case errors.Is(err, domain.ErrSpeakingPromptConflict):
		conflict("prompt_conflict")
	case errors.Is(err, domain.ErrSpeakingNoAudio):
		conflict("no_audio")
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusUnprocessableEntity, err.Error())
	default:
		writeError(w, http.StatusInternalServerError, "could not "+action)
	}
}

func (h *Handler) handleListSpeakingPrompts(w http.ResponseWriter, r *http.Request) {
	if h.speakingUnavailable(w) {
		return
	}
	ps, err := h.speaking.ListPrompts(r.Context())
	if err != nil {
		writeSpeakingError(w, err, "list speaking prompts")
		return
	}
	out := make([]map[string]any, 0, len(ps))
	for _, p := range ps {
		out = append(out, map[string]any{"id": p.Prompt.ID, "format": p.Prompt.Format, "style_level": p.Prompt.StyleLevel, "title": p.Prompt.Title,
			"situation": p.Prompt.Situation, "requirements": p.Prompt.Requirements, "seconds_min": p.Prompt.SecondsMin, "seconds_max": p.Prompt.SecondsMax,
			"started_exercise_id": p.StartedExerciseID})
	}
	writeJSON(w, http.StatusOK, map[string]any{"set": domain.SpeakingPromptsID,
		"notice":  "Authored practice prompts: not official exam items; no score and no certified CEFR level. Feedback reads the confirmed transcript only and cannot judge pronunciation.",
		"prompts": out, "providers": h.speakingProviders(), "limits": speakingLimits()})
}

// handleStartSpeakingPrompt starts the exercise for an authored prompt. 201 new; 200 existing.
func (h *Handler) handleStartSpeakingPrompt(w http.ResponseWriter, r *http.Request) {
	if h.speakingUnavailable(w) {
		return
	}
	v, replay, err := h.speaking.StartPrompt(r.Context(), r.PathValue("prompt_id"))
	if err != nil {
		writeSpeakingError(w, err, "start the exercise")
		return
	}
	status := http.StatusCreated
	if replay {
		status = http.StatusOK
		w.Header().Set("Idempotency-Replayed", "true")
	}
	writeJSON(w, status, h.toSpeakingView(v))
}

func (h *Handler) handleListSpeakingExercises(w http.ResponseWriter, r *http.Request) {
	if h.speakingUnavailable(w) {
		return
	}
	rows, err := h.speaking.ListExercises(r.Context())
	if err != nil {
		writeSpeakingError(w, err, "list speaking exercises")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		out = append(out, map[string]any{"exercise": toSpeakingExercise(row.Exercise), "takes": row.Takes})
	}
	writeJSON(w, http.StatusOK, map[string]any{"exercises": out, "providers": h.speakingProviders()})
}

func (h *Handler) handleGetSpeakingExercise(w http.ResponseWriter, r *http.Request) {
	if h.speakingUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	v, err := h.speaking.GetExercise(r.Context(), id)
	if err != nil {
		writeSpeakingError(w, err, "read the exercise")
		return
	}
	writeJSON(w, http.StatusOK, h.toSpeakingView(v))
}

type addSpeakingTakeRequest struct {
	AudioSource string `json:"audio_source"`
	AudioMIME   string `json:"audio_mime"`
	AudioBytes  int64  `json:"audio_bytes"`
	AudioSHA256 string `json:"audio_sha256"`
	DurationMS  int    `json:"duration_ms"`
}

// handleAddSpeakingTake stores a take's metadata (201). No audio, no provider call.
func (h *Handler) handleAddSpeakingTake(w http.ResponseWriter, r *http.Request) {
	if h.speakingUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	var req addSpeakingTakeRequest
	if !decodeListening(w, r, &req) {
		return
	}
	v, err := h.speaking.AddTake(r.Context(), id, domain.SpeakingTake{AudioSource: req.AudioSource, AudioMIME: req.AudioMIME, AudioBytes: req.AudioBytes,
		AudioSHA256: req.AudioSHA256, DurationMS: req.DurationMS})
	if err != nil {
		writeSpeakingError(w, err, "save the take")
		return
	}
	writeJSON(w, http.StatusCreated, h.toSpeakingView(v))
}

type addSpeakingTranscriptRequest struct {
	Text            string `json:"text"`
	TranscriptionID *int64 `json:"transcription_id"`
}

// handleAddSpeakingTranscript saves the learner's confirmed transcript as the
// take's next version (201); 409 unchanged or too many versions; 422. No call.
func (h *Handler) handleAddSpeakingTranscript(w http.ResponseWriter, r *http.Request) {
	if h.speakingUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	var req addSpeakingTranscriptRequest
	if !decodeListening(w, r, &req) {
		return
	}
	v, err := h.speaking.AddTranscript(r.Context(), id, req.Text, req.TranscriptionID)
	if err != nil {
		writeSpeakingError(w, err, "save the transcript")
		return
	}
	writeJSON(w, http.StatusCreated, h.toSpeakingView(v))
}

type transcribeSpeakingRequest struct {
	AudioBase64         []byte `json:"audio_base64"` // standard base64
	AudioMIME           string `json:"audio_mime"`
	ConfirmUnknownRetry bool   `json:"confirm_unknown_retry"`
}

func writeSpeakingProviderOutcome(w http.ResponseWriter, err error, body map[string]any, kind, kept string) bool {
	var perr *application.SpeakingProviderError
	switch {
	case errors.As(err, &perr):
		status, msg := http.StatusBadGateway, "the "+kind+" provider is unavailable; "+kept
		switch {
		case errors.Is(err, domain.ErrProviderTimeout):
			status, msg = http.StatusGatewayTimeout, "the "+kind+" provider timed out, so the outcome is unknown; "+kept
		case errors.Is(err, domain.ErrOutcomeUnknown):
			msg = "the request reached the " + kind + " provider but no usable answer came back, so the outcome is unknown; " + kept
		case errors.Is(err, domain.ErrValidation):
			msg = "the " + kind + " provider returned output that is not usable; " + kept
		}
		body["error"] = msg
		writeJSON(w, status, body)
	case errors.Is(err, domain.ErrSpeakingRequestInProgress):
		body["error"], body["code"] = err.Error(), "request_in_progress"
		writeJSON(w, http.StatusConflict, body)
	case errors.Is(err, domain.ErrSpeakingOutcomeUnknown):
		body["error"], body["code"] = err.Error(), "outcome_unknown"
		writeJSON(w, http.StatusConflict, body)
	case errors.Is(err, domain.ErrSpeakingOperationConflict):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "key_conflict"})
	default:
		return false
	}
	return true
}

func toSpeakingTranscriptionResult(res *application.SpeakingTranscriptionResult, now time.Time) map[string]any {
	out := map[string]any{"request": nil, "transcription": nil}
	if res == nil {
		return out
	}
	out["request"] = toSpeakingTranscriptionRequest(res.Request, now)
	if res.Transcription != nil {
		out["transcription"] = toSpeakingTranscription(*res.Transcription)
	}
	return out
}

// handleTranscribeSpeakingTake is the one explicit transcription call, for one
// take: JSON {"audio_base64", "audio_mime", "confirm_unknown_retry"?} (the
// browser boundary accepts JSON bodies only), optional UUID Idempotency-Key;
// not canceled when the client goes away. The audio must be the take's (same
// type and SHA-256); it is used for this call only and never stored.
// 201 {request, transcription}; 200 same-key replay; 502/504 stored failure or
// unknown outcome; 409 {code}: request_in_progress, outcome_unknown,
// key_conflict, no_audio; 413; 422 audio refused before any call; 503 disabled.
func (h *Handler) handleTranscribeSpeakingTake(w http.ResponseWriter, r *http.Request) {
	if h.speakingUnavailable(w) {
		return
	}
	if tr, _ := h.speaking.Providers(); tr == "" {
		writeError(w, http.StatusServiceUnavailable, "speaking transcription is not enabled (SPEAKING_TRANSCRIPTION_PROVIDER); type the transcript instead")
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
	var req transcribeSpeakingRequest
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxSpeakingAudioBody))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		var tooBig *http.MaxBytesError
		if errors.As(err, &tooBig) {
			writeError(w, http.StatusRequestEntityTooLarge, "the audio is larger than this server accepts")
		} else {
			writeError(w, http.StatusBadRequest, "invalid JSON body (audio_base64 must be standard base64)")
		}
		return
	}
	if extra := dec.Decode(&struct{}{}); extra != io.EOF {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	res, replay, err := h.speaking.Transcribe(context.WithoutCancel(r.Context()), application.SpeakingTranscriptionInput{
		TakeID: id, Audio: req.AudioBase64, AudioMIME: req.AudioMIME, OperationID: key, ConfirmUnknownRetry: req.ConfirmUnknownRetry,
	})
	req.AudioBase64 = nil
	now := h.speaking.Now()
	if res != nil {
		w.Header().Set("Idempotency-Key", res.Request.OperationID)
	}
	if err != nil && writeSpeakingProviderOutcome(w, err, toSpeakingTranscriptionResult(res, now), "transcription", "your take and transcripts are kept") {
		return
	}
	switch {
	case errors.Is(err, domain.ErrSpeakingTranscriptionDisabled):
		writeError(w, http.StatusServiceUnavailable, "speaking transcription is not enabled (SPEAKING_TRANSCRIPTION_PROVIDER); type the transcript instead")
	case err != nil:
		writeSpeakingError(w, err, "transcribe the take")
	case replay:
		w.Header().Set("Idempotency-Replayed", "true")
		writeJSON(w, http.StatusOK, toSpeakingTranscriptionResult(res, now))
	default:
		writeJSON(w, http.StatusCreated, toSpeakingTranscriptionResult(res, now))
	}
}

func (h *Handler) handleGetSpeakingTranscriptionRequest(w http.ResponseWriter, r *http.Request) {
	if h.speakingUnavailable(w) {
		return
	}
	res, err := h.speaking.GetTranscriptionRequest(r.Context(), r.PathValue("operation_id"))
	switch {
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusBadRequest, "invalid idempotency key")
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "no transcription request is recorded under this key")
	case err != nil:
		writeSpeakingError(w, err, "read the request")
	default:
		writeJSON(w, http.StatusOK, toSpeakingTranscriptionResult(res, h.speaking.Now()))
	}
}

func toSpeakingFeedbackResult(res *application.SpeakingFeedbackResult, now time.Time) map[string]any {
	out := map[string]any{"request": nil, "feedback": nil}
	if res == nil {
		return out
	}
	out["request"] = toSpeakingFeedbackRequest(res.Request, now)
	if res.Feedback != nil {
		out["feedback"] = toSpeakingFeedback(*res.Feedback)
	}
	return out
}

// handleRequestSpeakingFeedback is the one explicit feedback call, for one
// confirmed transcript version (the Writing contract). 201 {request,
// feedback}; 200 same-key replay; 502/504; 409 {code}; 503 disabled; 404.
func (h *Handler) handleRequestSpeakingFeedback(w http.ResponseWriter, r *http.Request) {
	if h.speakingUnavailable(w) {
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
	res, replay, err := h.speaking.RequestFeedback(context.WithoutCancel(r.Context()), application.SpeakingFeedbackRequestInput{
		TranscriptID: id, OperationID: key, ConfirmUnknownRetry: body.ConfirmUnknownRetry,
	})
	now := h.speaking.Now()
	if res != nil {
		w.Header().Set("Idempotency-Key", res.Request.OperationID)
	}
	if err != nil && writeSpeakingProviderOutcome(w, err, toSpeakingFeedbackResult(res, now), "feedback", "your transcripts are kept") {
		return
	}
	switch {
	case errors.Is(err, domain.ErrSpeakingFeedbackDisabled):
		writeError(w, http.StatusServiceUnavailable, "speaking feedback is not enabled (SPEAKING_PROVIDER); recording, transcripts and comparison still work")
	case err != nil:
		writeSpeakingError(w, err, "request feedback")
	case replay:
		w.Header().Set("Idempotency-Replayed", "true")
		writeJSON(w, http.StatusOK, toSpeakingFeedbackResult(res, now))
	default:
		writeJSON(w, http.StatusCreated, toSpeakingFeedbackResult(res, now))
	}
}

func (h *Handler) handleGetSpeakingFeedbackRequest(w http.ResponseWriter, r *http.Request) {
	if h.speakingUnavailable(w) {
		return
	}
	res, err := h.speaking.GetFeedbackRequest(r.Context(), r.PathValue("operation_id"))
	switch {
	case errors.Is(err, domain.ErrValidation):
		writeError(w, http.StatusBadRequest, "invalid idempotency key")
	case errors.Is(err, domain.ErrNotFound):
		writeError(w, http.StatusNotFound, "no feedback request is recorded under this key")
	case err != nil:
		writeSpeakingError(w, err, "read the request")
	default:
		writeJSON(w, http.StatusOK, toSpeakingFeedbackResult(res, h.speaking.Now()))
	}
}
