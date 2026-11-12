package application

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// SpeakingService implements Speaking v1: exercises from authored prompts,
// takes recorded and played back in the browser (only their metadata is
// stored), one explicit transcription request for one take's audio (sent once,
// never stored), confirmed transcript versions, and one explicit feedback
// request for one confirmed version, through the attempt-first path used by
// Listening, Reading and Writing. Nothing else calls a provider, nothing runs
// in the background and nothing retries itself.
type SpeakingService struct {
	repo        domain.SpeakingRepository
	transcriber domain.SpeakingTranscriber       // nil when SPEAKING_TRANSCRIPTION_PROVIDER=disabled
	generator   domain.SpeakingFeedbackGenerator // nil when SPEAKING_PROVIDER=disabled
	prompts     domain.SpeakingPromptSet
	now         func() time.Time
	deadline    time.Duration
}

// SpeakingOption configures a SpeakingService.
type SpeakingOption func(*SpeakingService)

// WithSpeakingClock replaces the clock (tests).
func WithSpeakingClock(now func() time.Time) SpeakingOption {
	return func(s *SpeakingService) { s.now = now }
}

// WithSpeakingDeadline sets how long an unfinished request reads as in progress.
func WithSpeakingDeadline(d time.Duration) SpeakingOption {
	return func(s *SpeakingService) { s.deadline = d }
}

// NewSpeakingService builds the service; an invalid prompt set is refused.
func NewSpeakingService(repo domain.SpeakingRepository, transcriber domain.SpeakingTranscriber, generator domain.SpeakingFeedbackGenerator, promptsJSON []byte, opts ...SpeakingOption) (*SpeakingService, error) {
	prompts, err := domain.ParseSpeakingPrompts(promptsJSON)
	if err != nil {
		return nil, fmt.Errorf("speaking prompts: %w", err)
	}
	s := &SpeakingService{repo: repo, transcriber: transcriber, generator: generator, prompts: prompts,
		now: func() time.Time { return time.Now().UTC() }, deadline: DefaultPreparationDeadline}
	for _, o := range opts {
		o(s)
	}
	return s, nil
}

// Now is the service clock.
func (s *SpeakingService) Now() time.Time { return s.now() }

// Providers reports which providers are enabled, with their provenance.
func (s *SpeakingService) Providers() (transcriber, generator string) {
	if s.transcriber != nil {
		transcriber = s.transcriber.Name()
	}
	if s.generator != nil {
		generator = s.generator.Name()
	}
	return transcriber, generator
}

// SpeakingExerciseView is one exercise with every take, transcript and report.
type SpeakingExerciseView struct {
	Exercise              domain.SpeakingExercise
	Takes                 []domain.SpeakingTake                 // by take number
	Transcriptions        []domain.SpeakingTranscription        // newest first
	TranscriptionRequests []domain.SpeakingTranscriptionRequest // newest first
	Transcripts           []domain.SpeakingTranscript           // by take, then version
	Feedback              []domain.SpeakingFeedback             // newest first
	FeedbackRequests      []domain.SpeakingFeedbackRequest      // newest first
	ExampleTranscript     string
	Now                   time.Time
}

// SpeakingExerciseSummary is a list row.
type SpeakingExerciseSummary struct {
	Exercise domain.SpeakingExercise
	Takes    int
}

// SpeakingPromptView is one authored prompt and the exercise started from it, if any.
type SpeakingPromptView struct {
	Prompt            domain.SpeakingPrompt
	StartedExerciseID *int64
}

func (s *SpeakingService) prompt(id string) (domain.SpeakingPrompt, bool) {
	for _, p := range s.prompts.Prompts {
		if p.ID == id {
			return p, true
		}
	}
	return domain.SpeakingPrompt{}, false
}

// ListPrompts lists the authored prompts.
func (s *SpeakingService) ListPrompts(ctx context.Context) ([]SpeakingPromptView, error) {
	es, err := s.repo.ListExercises(ctx)
	if err != nil {
		return nil, err
	}
	started := map[string]int64{}
	for _, e := range es {
		started[e.PromptID] = e.ID
	}
	out := make([]SpeakingPromptView, 0, len(s.prompts.Prompts))
	for _, p := range s.prompts.Prompts {
		v := SpeakingPromptView{Prompt: p}
		if id, ok := started[p.ID]; ok {
			v.StartedExerciseID = &id
		}
		out = append(out, v)
	}
	return out, nil
}

// StartPrompt creates the exercise for an authored prompt. Starting it again
// returns the existing exercise (true).
func (s *SpeakingService) StartPrompt(ctx context.Context, promptID string) (*SpeakingExerciseView, bool, error) {
	p, ok := s.prompt(promptID)
	if !ok {
		return nil, false, fmt.Errorf("%w: no authored prompt %q", domain.ErrNotFound, promptID)
	}
	e, replay, err := s.repo.StartExercise(ctx, domain.SpeakingExercise{PromptID: p.ID, Title: p.Title, Situation: p.Situation, Requirements: p.Requirements,
		SecondsMin: p.SecondsMin, SecondsMax: p.SecondsMax}, s.now())
	if err != nil {
		return nil, false, err
	}
	v, err := s.GetExercise(ctx, e.ID)
	return v, replay, err
}

// GetExercise reads one exercise. It never calls a provider.
func (s *SpeakingService) GetExercise(ctx context.Context, id int64) (*SpeakingExerciseView, error) {
	e, err := s.repo.GetExercise(ctx, id)
	if err != nil {
		return nil, err
	}
	v := &SpeakingExerciseView{Exercise: e, Now: s.now()}
	if p, ok := s.prompt(e.PromptID); ok {
		v.ExampleTranscript = p.ExampleTranscript
	}
	if v.Takes, err = s.repo.ListTakes(ctx, id); err != nil {
		return nil, err
	}
	if v.Transcriptions, err = s.repo.ListTranscriptions(ctx, id); err != nil {
		return nil, err
	}
	if v.TranscriptionRequests, err = s.repo.ListTranscriptionRequests(ctx, id); err != nil {
		return nil, err
	}
	if v.Transcripts, err = s.repo.ListTranscripts(ctx, id); err != nil {
		return nil, err
	}
	if v.Feedback, err = s.repo.ListFeedback(ctx, id); err != nil {
		return nil, err
	}
	if v.FeedbackRequests, err = s.repo.ListFeedbackRequests(ctx, id); err != nil {
		return nil, err
	}
	return v, nil
}

// ListExercises lists every exercise, newest first.
func (s *SpeakingService) ListExercises(ctx context.Context) ([]SpeakingExerciseSummary, error) {
	es, err := s.repo.ListExercises(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]SpeakingExerciseSummary, 0, len(es))
	for _, e := range es {
		takes, err := s.repo.ListTakes(ctx, e.ID)
		if err != nil {
			return nil, err
		}
		out = append(out, SpeakingExerciseSummary{Exercise: e, Takes: len(takes)})
	}
	return out, nil
}

// AddTake stores a new take's metadata (never its audio). No provider call.
func (s *SpeakingService) AddTake(ctx context.Context, exerciseID int64, t domain.SpeakingTake) (*SpeakingExerciseView, error) {
	t, err := domain.NormalizeSpeakingTake(t)
	if err != nil {
		return nil, err
	}
	if _, err := s.repo.AddTake(ctx, exerciseID, t, s.now()); err != nil {
		return nil, err
	}
	return s.GetExercise(ctx, exerciseID)
}

// AddTranscript saves the learner's confirmed transcript as the take's next
// version. transcriptionID names the machine transcript it was checked
// against, if any. No provider call.
func (s *SpeakingService) AddTranscript(ctx context.Context, takeID int64, text string, transcriptionID *int64) (*SpeakingExerciseView, error) {
	t, words, err := domain.NormalizeSpeakingTranscript(text)
	if err != nil {
		return nil, err
	}
	saved, err := s.repo.AddTranscript(ctx, takeID, t, words, transcriptionID, s.now())
	if err != nil {
		return nil, err
	}
	take, err := s.repo.GetTake(ctx, saved.TakeID)
	if err != nil {
		return nil, err
	}
	return s.GetExercise(ctx, take.ExerciseID)
}

func speakingKey(key string) (string, error) {
	if key == "" {
		return newOperationKey()
	}
	op, err := domain.NormalizeAnnotationOperationID(key)
	if err != nil {
		return "", fmt.Errorf("%w: invalid idempotency key", domain.ErrValidation)
	}
	return op, nil
}

// classify makes any unexpected provider error an unknown outcome: it may
// have been sent.
func speakingCallError(err error) error {
	if err != nil && !errors.Is(err, domain.ErrProviderTimeout) && !errors.Is(err, domain.ErrProviderUnavailable) && !errors.Is(err, domain.ErrValidation) {
		return fmt.Errorf("%w: %w: %v", domain.ErrProviderUnavailable, domain.ErrOutcomeUnknown, err)
	}
	return err
}

// SpeakingTranscriptionInput is one explicit "Send audio for transcription" click.
type SpeakingTranscriptionInput struct {
	TakeID              int64
	Audio               []byte
	AudioMIME           string
	OperationID         string // UUID; empty: generated
	ConfirmUnknownRetry bool
}

// SpeakingTranscriptionResult is one request and, once finished, its transcription.
type SpeakingTranscriptionResult struct {
	Request       domain.SpeakingTranscriptionRequest
	Transcription *domain.SpeakingTranscription
}

// SpeakingProviderError carries a stored failure (or unknown outcome) from a provider call.
type SpeakingProviderError struct {
	Err error
}

func (e *SpeakingProviderError) Error() string { return e.Err.Error() }
func (e *SpeakingProviderError) Unwrap() error { return e.Err }

// Transcribe checks one take's audio (type, size, magic bytes, and that it is
// the take's recorded audio), records the request, sends the audio once and
// stores the machine transcript or a failure. The audio is held in memory for
// this call only; it is never stored, and nothing about the take changes.
func (s *SpeakingService) Transcribe(ctx context.Context, in SpeakingTranscriptionInput) (*SpeakingTranscriptionResult, bool, error) {
	if s.transcriber == nil {
		return nil, false, domain.ErrSpeakingTranscriptionDisabled
	}
	op, err := speakingKey(in.OperationID)
	if err != nil {
		return nil, false, err
	}
	format, err := domain.SpeakingAudioType(in.AudioMIME)
	if err != nil {
		return nil, false, err
	}
	if err := domain.CheckSpeakingAudio(format, in.Audio); err != nil {
		return nil, false, err
	}
	sum := sha256.Sum256(in.Audio)
	now := s.now()
	req, take, replay, err := s.repo.StartTranscriptionRequest(ctx, domain.NewSpeakingTranscriptionRequest{
		OperationID: op, TakeID: in.TakeID, AudioMIME: format.MIME, AudioSHA256: hex.EncodeToString(sum[:]), ConfirmUnknownRetry: in.ConfirmUnknownRetry, Now: now, Deadline: now.Add(s.deadline),
	})
	if err != nil {
		if req.ID != 0 {
			return &SpeakingTranscriptionResult{Request: req}, false, err
		}
		return nil, false, err
	}
	if replay {
		out, err := s.withTranscription(ctx, req)
		return out, true, err
	}
	text, callErr := s.transcriber.Transcribe(ctx, domain.SpeakingTranscriptionInput{Audio: in.Audio, Format: format})
	callErr = speakingCallError(callErr)
	row := domain.SpeakingTranscription{TakeID: take.ID, Transcriber: s.transcriber.Name()}
	if callErr != nil {
		row.Status, row.FailureCode = domain.ListeningExerciseFailed, domain.SpeakingFailureCode(callErr)
	} else {
		row.Status, row.Text = domain.ListeningExerciseCompleted, text
	}
	storeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), commitTimeout)
	defer cancel()
	finished, stored, err := s.repo.FinishTranscriptionRequest(storeCtx, req.ID, domain.PreparationOutcome(callErr), row, s.now())
	if err != nil {
		return &SpeakingTranscriptionResult{Request: req}, false, err
	}
	out := &SpeakingTranscriptionResult{Request: finished, Transcription: &stored}
	if callErr != nil {
		return out, false, &SpeakingProviderError{Err: callErr}
	}
	return out, false, nil
}

// GetTranscriptionRequest looks a transcription request up by its key.
func (s *SpeakingService) GetTranscriptionRequest(ctx context.Context, operationID string) (*SpeakingTranscriptionResult, error) {
	op, err := domain.NormalizeAnnotationOperationID(operationID)
	if err != nil {
		return nil, fmt.Errorf("%w: invalid idempotency key", domain.ErrValidation)
	}
	req, err := s.repo.GetTranscriptionRequestByOperation(ctx, op)
	if err != nil {
		return nil, err
	}
	return s.withTranscription(ctx, req)
}

func (s *SpeakingService) withTranscription(ctx context.Context, req domain.SpeakingTranscriptionRequest) (*SpeakingTranscriptionResult, error) {
	out := &SpeakingTranscriptionResult{Request: req}
	if req.TranscriptionID != nil {
		t, err := s.repo.GetTranscription(ctx, *req.TranscriptionID)
		if err != nil {
			return nil, err
		}
		out.Transcription = &t
	}
	return out, nil
}

// SpeakingFeedbackRequestInput is one explicit "Request feedback" click.
type SpeakingFeedbackRequestInput struct {
	TranscriptID        int64
	OperationID         string
	ConfirmUnknownRetry bool
}

// SpeakingFeedbackResult is one request and, once finished, its report.
type SpeakingFeedbackResult struct {
	Request  domain.SpeakingFeedbackRequest
	Feedback *domain.SpeakingFeedback
}

// RequestFeedback records a request for one confirmed transcript version,
// makes one provider call, validates and grounds the output against that exact
// text, and stores the outcome. Transcripts are never touched.
func (s *SpeakingService) RequestFeedback(ctx context.Context, in SpeakingFeedbackRequestInput) (*SpeakingFeedbackResult, bool, error) {
	if s.generator == nil {
		return nil, false, domain.ErrSpeakingFeedbackDisabled
	}
	op, err := speakingKey(in.OperationID)
	if err != nil {
		return nil, false, err
	}
	now := s.now()
	req, transcript, replay, err := s.repo.StartFeedbackRequest(ctx, domain.NewSpeakingFeedbackRequest{
		OperationID: op, TranscriptID: in.TranscriptID, ConfirmUnknownRetry: in.ConfirmUnknownRetry, Now: now, Deadline: now.Add(s.deadline),
	})
	if err != nil {
		if req.ID != 0 {
			return &SpeakingFeedbackResult{Request: req}, false, err
		}
		return nil, false, err
	}
	if replay {
		out, err := s.withFeedback(ctx, req)
		return out, true, err
	}
	take, err := s.repo.GetTake(ctx, transcript.TakeID)
	if err != nil {
		return &SpeakingFeedbackResult{Request: req}, false, err
	}
	ex, err := s.repo.GetExercise(ctx, take.ExerciseID)
	if err != nil {
		return &SpeakingFeedbackResult{Request: req}, false, err
	}
	content, callErr := s.generator.Generate(ctx, domain.SpeakingFeedbackInput{Title: ex.Title, Situation: ex.Situation, Requirements: ex.Requirements,
		SecondsMin: ex.SecondsMin, SecondsMax: ex.SecondsMax, DurationMS: take.DurationMS, Transcript: transcript.Text, WordCount: transcript.WordCount})
	if callErr == nil {
		callErr = domain.ValidateSpeakingFeedback(transcript.Text, &content)
	}
	callErr = speakingCallError(callErr)
	row := domain.SpeakingFeedback{ExerciseID: ex.ID, TranscriptID: transcript.ID, Generator: s.generator.Name()}
	if callErr != nil {
		row.Status, row.FailureCode = domain.ListeningExerciseFailed, domain.SpeakingFailureCode(callErr)
	} else {
		row.Status, row.Content = domain.ListeningExerciseCompleted, &content
	}
	storeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), commitTimeout)
	defer cancel()
	finished, stored, err := s.repo.FinishFeedbackRequest(storeCtx, req.ID, domain.PreparationOutcome(callErr), row, s.now())
	if err != nil {
		return &SpeakingFeedbackResult{Request: req}, false, err
	}
	out := &SpeakingFeedbackResult{Request: finished, Feedback: &stored}
	if callErr != nil {
		return out, false, &SpeakingProviderError{Err: callErr}
	}
	return out, false, nil
}

// GetFeedbackRequest looks a feedback request up by its key.
func (s *SpeakingService) GetFeedbackRequest(ctx context.Context, operationID string) (*SpeakingFeedbackResult, error) {
	op, err := domain.NormalizeAnnotationOperationID(operationID)
	if err != nil {
		return nil, fmt.Errorf("%w: invalid idempotency key", domain.ErrValidation)
	}
	req, err := s.repo.GetFeedbackRequestByOperation(ctx, op)
	if err != nil {
		return nil, err
	}
	return s.withFeedback(ctx, req)
}

func (s *SpeakingService) withFeedback(ctx context.Context, req domain.SpeakingFeedbackRequest) (*SpeakingFeedbackResult, error) {
	out := &SpeakingFeedbackResult{Request: req}
	if req.FeedbackID != nil {
		f, err := s.repo.GetFeedback(ctx, *req.FeedbackID)
		if err != nil {
			return nil, err
		}
		out.Feedback = &f
	}
	return out, nil
}
