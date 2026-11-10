package application

import (
	"context"
	"errors"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// WritingService implements Exam Writing v1: tasks from an authored prompt or
// the learner's own, immutable draft versions, and one explicit, opt-in
// feedback request for one selected version, through the attempt-first path
// used by Listening and Reading. Drafting, revising and comparing never call a
// provider; nothing runs in the background and nothing retries itself.
type WritingService struct {
	repo      domain.WritingRepository
	generator domain.WritingFeedbackGenerator // nil when WRITING_PROVIDER=disabled
	prompts   domain.WritingPromptSet
	now       func() time.Time
	deadline  time.Duration
}

// WritingOption configures a WritingService.
type WritingOption func(*WritingService)

// WithWritingClock replaces the clock (tests).
func WithWritingClock(now func() time.Time) WritingOption {
	return func(s *WritingService) { s.now = now }
}

// WithWritingDeadline sets how long an unfinished request reads as in progress.
func WithWritingDeadline(d time.Duration) WritingOption {
	return func(s *WritingService) { s.deadline = d }
}

// NewWritingService builds the service; an invalid prompt set is refused.
func NewWritingService(repo domain.WritingRepository, generator domain.WritingFeedbackGenerator, promptsJSON []byte, opts ...WritingOption) (*WritingService, error) {
	prompts, err := domain.ParseWritingPrompts(promptsJSON)
	if err != nil {
		return nil, fmt.Errorf("writing prompts: %w", err)
	}
	s := &WritingService{repo: repo, generator: generator, prompts: prompts, now: func() time.Time { return time.Now().UTC() }, deadline: DefaultPreparationDeadline}
	for _, o := range opts {
		o(s)
	}
	return s, nil
}

// Now is the service clock.
func (s *WritingService) Now() time.Time { return s.now() }

// GeneratorEnabled reports whether feedback can be requested, and its provenance.
func (s *WritingService) GeneratorEnabled() (bool, string) {
	if s.generator == nil {
		return false, ""
	}
	return true, s.generator.Name()
}

// WritingTaskView is one task with every version, report and request.
type WritingTaskView struct {
	Task     domain.WritingTask
	Drafts   []domain.WritingDraft           // oldest first
	Feedback []domain.WritingFeedback        // newest first
	Requests []domain.WritingFeedbackRequest // newest first
	Now      time.Time
}

// WritingTaskSummary is a list row.
type WritingTaskSummary struct {
	Task     domain.WritingTask
	Versions int
	Feedback int
}

// WritingPromptView is one authored prompt and the task started from it, if any.
type WritingPromptView struct {
	Prompt        domain.WritingPrompt
	StartedTaskID *int64
}

// ListPrompts lists the authored prompts.
func (s *WritingService) ListPrompts(ctx context.Context) ([]WritingPromptView, error) {
	tasks, err := s.repo.ListTasks(ctx)
	if err != nil {
		return nil, err
	}
	started := map[string]int64{}
	for _, t := range tasks {
		if t.PromptID != "" {
			started[t.PromptID] = t.ID
		}
	}
	out := make([]WritingPromptView, 0, len(s.prompts.Prompts))
	for _, p := range s.prompts.Prompts {
		v := WritingPromptView{Prompt: p}
		if id, ok := started[p.ID]; ok {
			v.StartedTaskID = &id
		}
		out = append(out, v)
	}
	return out, nil
}

// StartPrompt creates the task for an authored prompt (no draft: the learner
// writes version 1). Starting it again returns the existing task (true).
func (s *WritingService) StartPrompt(ctx context.Context, promptID string) (*WritingTaskView, bool, error) {
	for _, p := range s.prompts.Prompts {
		if p.ID != promptID {
			continue
		}
		t, replay, err := s.repo.StartAuthoredTask(ctx, domain.WritingTask{Title: p.Title, Prompt: p.Prompt, Requirements: p.Requirements,
			WordMin: p.WordMin, WordMax: p.WordMax, Origin: domain.ReadingOriginAuthored, PromptID: p.ID}, s.now())
		if err != nil {
			return nil, false, err
		}
		v, err := s.GetTask(ctx, t.ID)
		return v, replay, err
	}
	return nil, false, fmt.Errorf("%w: no authored prompt %q", domain.ErrNotFound, promptID)
}

// CreateTask stores the learner's own task.
func (s *WritingService) CreateTask(ctx context.Context, t domain.WritingTask) (*WritingTaskView, error) {
	t.Origin, t.PromptID = domain.ReadingOriginLearner, ""
	t, err := domain.NormalizeWritingTask(t)
	if err != nil {
		return nil, err
	}
	saved, err := s.repo.CreateTask(ctx, t, s.now())
	if err != nil {
		return nil, err
	}
	return s.GetTask(ctx, saved.ID)
}

// GetTask reads one task. It never calls the generator.
func (s *WritingService) GetTask(ctx context.Context, id int64) (*WritingTaskView, error) {
	t, err := s.repo.GetTask(ctx, id)
	if err != nil {
		return nil, err
	}
	drafts, err := s.repo.ListDrafts(ctx, id)
	if err != nil {
		return nil, err
	}
	fb, err := s.repo.ListFeedback(ctx, id)
	if err != nil {
		return nil, err
	}
	reqs, err := s.repo.ListFeedbackRequests(ctx, id)
	if err != nil {
		return nil, err
	}
	return &WritingTaskView{Task: t, Drafts: drafts, Feedback: fb, Requests: reqs, Now: s.now()}, nil
}

// ListTasks lists every task, newest first.
func (s *WritingService) ListTasks(ctx context.Context) ([]WritingTaskSummary, error) {
	ts, err := s.repo.ListTasks(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]WritingTaskSummary, 0, len(ts))
	for _, t := range ts {
		v, err := s.GetTask(ctx, t.ID)
		if err != nil {
			return nil, err
		}
		out = append(out, WritingTaskSummary{Task: t, Versions: len(v.Drafts), Feedback: len(v.Feedback)})
	}
	return out, nil
}

// AddDraft saves the next immutable version. Earlier versions and their
// feedback are never changed.
func (s *WritingService) AddDraft(ctx context.Context, taskID int64, text string) (*WritingTaskView, error) {
	t, words, err := domain.NormalizeWritingDraft(text)
	if err != nil {
		return nil, err
	}
	if _, err := s.repo.AddDraft(ctx, taskID, t, words, s.now()); err != nil {
		return nil, err
	}
	return s.GetTask(ctx, taskID)
}

// WritingFeedbackRequestInput is one explicit "Request feedback" click.
type WritingFeedbackRequestInput struct {
	DraftID             int64
	OperationID         string // UUID; empty: generated
	ConfirmUnknownRetry bool
}

// WritingFeedbackResult is one request and, once finished, its report.
type WritingFeedbackResult struct {
	Request  domain.WritingFeedbackRequest
	Feedback *domain.WritingFeedback
}

// WritingGenerationError carries the stored request and failed report.
type WritingGenerationError struct {
	Feedback domain.WritingFeedback
	Request  domain.WritingFeedbackRequest
	Err      error
}

func (e *WritingGenerationError) Error() string { return e.Err.Error() }
func (e *WritingGenerationError) Unwrap() error { return e.Err }

// RequestFeedback records a request for one draft version, makes one provider
// call, validates and grounds the output against that exact text, and stores
// the outcome. The draft versions are never touched, whatever happens.
func (s *WritingService) RequestFeedback(ctx context.Context, in WritingFeedbackRequestInput) (*WritingFeedbackResult, bool, error) {
	if s.generator == nil {
		return nil, false, domain.ErrWritingDisabled
	}
	op := in.OperationID
	if op == "" {
		var err error
		if op, err = newOperationKey(); err != nil {
			return nil, false, err
		}
	} else {
		normalized, err := domain.NormalizeAnnotationOperationID(op)
		if err != nil {
			return nil, false, fmt.Errorf("%w: invalid idempotency key", domain.ErrValidation)
		}
		op = normalized
	}
	now := s.now()
	req, draft, replay, err := s.repo.StartFeedbackRequest(ctx, domain.NewWritingFeedbackRequest{
		OperationID: op, DraftID: in.DraftID, ConfirmUnknownRetry: in.ConfirmUnknownRetry, Now: now, Deadline: now.Add(s.deadline),
	})
	if err != nil {
		if req.ID != 0 {
			return &WritingFeedbackResult{Request: req}, false, err
		}
		return nil, false, err
	}
	if replay {
		out, err := s.withFeedback(ctx, req)
		return out, true, err
	}
	task, err := s.repo.GetTask(ctx, draft.TaskID)
	if err != nil {
		return &WritingFeedbackResult{Request: req}, false, err
	}
	content, genErr := s.generator.Generate(ctx, domain.WritingFeedbackInput{Title: task.Title, Prompt: task.Prompt, Requirements: task.Requirements,
		WordMin: task.WordMin, WordMax: task.WordMax, Draft: draft.Text, WordCount: draft.WordCount})
	if genErr == nil {
		genErr = domain.ValidateWritingFeedback(draft.Text, &content)
	}
	row := domain.WritingFeedback{TaskID: task.ID, DraftID: draft.ID, Generator: s.generator.Name()}
	if genErr != nil {
		if !errors.Is(genErr, domain.ErrProviderTimeout) && !errors.Is(genErr, domain.ErrProviderUnavailable) && !errors.Is(genErr, domain.ErrValidation) {
			genErr = fmt.Errorf("%w: %w: %v", domain.ErrProviderUnavailable, domain.ErrOutcomeUnknown, genErr)
		}
		row.Status, row.FailureCode = domain.ListeningExerciseFailed, domain.WritingFailureCode(genErr)
	} else {
		row.Status, row.Content = domain.ListeningExerciseCompleted, &content
	}
	storeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), commitTimeout)
	defer cancel()
	finished, stored, err := s.repo.FinishFeedbackRequest(storeCtx, req.ID, domain.PreparationOutcome(genErr), row, s.now())
	if err != nil {
		return &WritingFeedbackResult{Request: req}, false, err
	}
	out := &WritingFeedbackResult{Request: finished, Feedback: &stored}
	if genErr != nil {
		return out, false, &WritingGenerationError{Feedback: stored, Request: finished, Err: genErr}
	}
	return out, false, nil
}

// GetFeedbackRequest looks a request up by its key.
func (s *WritingService) GetFeedbackRequest(ctx context.Context, operationID string) (*WritingFeedbackResult, error) {
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

func (s *WritingService) withFeedback(ctx context.Context, req domain.WritingFeedbackRequest) (*WritingFeedbackResult, error) {
	out := &WritingFeedbackResult{Request: req}
	if req.FeedbackID != nil {
		f, err := s.repo.GetFeedback(ctx, *req.FeedbackID)
		if err != nil {
			return nil, err
		}
		out.Feedback = &f
	}
	return out, nil
}
