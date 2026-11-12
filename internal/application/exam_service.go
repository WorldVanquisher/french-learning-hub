package application

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// ExamService runs Mock Exam v1: authored forms over the reading pack,
// server-owned deadlines, append-only answers and one replay-safe submission
// per session. It calls no provider and writes nothing on a read.
type ExamService struct {
	repo     domain.ExamRepository
	forms    domain.MockExamForms
	pack     domain.ReadingPack
	formsSHA string
	packSHA  string
	now      func() time.Time
}

// ExamOption configures an ExamService.
type ExamOption func(*ExamService)

// WithExamClock replaces the clock (tests).
func WithExamClock(now func() time.Time) ExamOption {
	return func(s *ExamService) { s.now = now }
}

func sha(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

// NewExamService validates the forms against the pack (startup refuses an
// invalid pair) and builds the service.
func NewExamService(repo domain.ExamRepository, formsRaw, packRaw []byte, opts ...ExamOption) (*ExamService, error) {
	pack, err := domain.ParseReadingPack(packRaw)
	if err != nil {
		return nil, fmt.Errorf("mock exam: %w", err)
	}
	forms, err := domain.ParseMockExamForms(formsRaw, pack)
	if err != nil {
		return nil, fmt.Errorf("mock exam: %w", err)
	}
	s := &ExamService{repo: repo, forms: forms, pack: pack, formsSHA: sha(formsRaw), packSHA: sha(packRaw),
		now: func() time.Time { return time.Now().UTC() }}
	for _, o := range opts {
		o(s)
	}
	return s, nil
}

// Now is the server's clock.
func (s *ExamService) Now() time.Time { return s.now().UTC() }

// Forms returns the authored forms and their notice.
func (s *ExamService) Forms() domain.MockExamForms { return s.forms }

// ExamView is one session as seen at Now.
type ExamView struct {
	Session    domain.ExamSession
	Answers    map[int]domain.ExamAnswer
	Submission *domain.ExamSubmission
	State      string
	Now        time.Time
	// Final answers once closed: the submission's, or (expired) the answers
	// saved before the deadline.
	Final   map[int]*int
	Correct int
	Total   int
}

func (s *ExamService) view(ctx context.Context, sess domain.ExamSession) (*ExamView, error) {
	answers, err := s.repo.CurrentAnswers(ctx, sess.ID)
	if err != nil {
		return nil, err
	}
	sub, err := s.repo.GetSubmission(ctx, sess.ID)
	if err != nil {
		return nil, err
	}
	now := s.Now()
	v := &ExamView{Session: sess, Answers: answers, Submission: sub, State: domain.ExamState(sess, sub, now), Now: now}
	switch v.State {
	case domain.ExamSubmitted:
		v.Final = sub.Answers
	case domain.ExamExpired:
		// Answers are accepted only up to the deadline, so the current ones are
		// exactly those saved in time.
		v.Final = map[int]*int{}
		for p, a := range answers {
			v.Final[p] = a.Choice
		}
	}
	if v.Final != nil {
		v.Correct, v.Total = domain.ScoreExam(sess.Items, v.Final)
	}
	return v, nil
}

func validOperationID(id string) error {
	if _, err := domain.NormalizeAnnotationOperationID(id); err != nil {
		return fmt.Errorf("%w: Idempotency-Key must be a UUID", domain.ErrValidation)
	}
	return nil
}

// Start begins an exam on one form under an idempotency key. A repeated key
// replays the same session (true).
func (s *ExamService) Start(ctx context.Context, formID, operationID string) (*ExamView, bool, error) {
	if err := validOperationID(operationID); err != nil {
		return nil, false, err
	}
	form, ok := s.forms.Form(formID)
	if !ok {
		return nil, false, fmt.Errorf("%w: unknown form %q", domain.ErrValidation, formID)
	}
	items := make([]domain.ExamItem, 0, len(form.Questions))
	for _, ref := range form.Questions {
		it, err := domain.FreezeExamItem(s.pack, ref)
		if err != nil {
			return nil, false, err
		}
		items = append(items, it)
	}
	now := s.Now()
	sess, replay, err := s.repo.CreateSession(ctx, domain.ExamSession{
		OperationID: operationID, Kind: domain.ExamKindExam, FormID: form.ID, FormTitle: form.Title,
		FormsSHA256: s.formsSHA, PackSHA256: s.packSHA, DurationSeconds: form.DurationSeconds,
		StartedAt: now, DeadlineAt: now.Add(time.Duration(form.DurationSeconds) * time.Second), Items: items,
	})
	if err != nil {
		return nil, false, err
	}
	v, err := s.view(ctx, sess)
	return v, replay, err
}

// StartRetry begins a one-question practice of an authored question related
// to one position of a closed session (same kind, another passage first).
func (s *ExamService) StartRetry(ctx context.Context, sessionID int64, position int, operationID string) (*ExamView, bool, error) {
	if err := validOperationID(operationID); err != nil {
		return nil, false, err
	}
	orig, err := s.repo.GetSession(ctx, sessionID)
	if err != nil {
		return nil, false, err
	}
	if position < 1 || position > len(orig.Items) {
		return nil, false, fmt.Errorf("%w: position must be between 1 and %d", domain.ErrValidation, len(orig.Items))
	}
	v, err := s.view(ctx, orig)
	if err != nil {
		return nil, false, err
	}
	if v.State == domain.ExamInProgress {
		return nil, false, domain.ErrExamNotClosed
	}
	exclude := map[string]bool{}
	for _, it := range orig.Items {
		exclude[it.QuestionID] = true
	}
	used, err := s.repo.RetryQuestionIDs(ctx, sessionID)
	if err != nil {
		return nil, false, err
	}
	for _, q := range used {
		exclude[q] = true
	}
	ref, err := domain.RelatedExamRef(s.pack, orig.Items[position-1], exclude)
	if err != nil {
		// A replay of an earlier retry start must still find its session even
		// when no further question is left.
		if sess, replay, rerr := s.replayOnly(ctx, operationID, orig, position); rerr == nil {
			return sess, replay, nil
		}
		return nil, false, err
	}
	it, err := domain.FreezeExamItem(s.pack, ref)
	if err != nil {
		return nil, false, err
	}
	now := s.Now()
	id := orig.ID
	sess, replay, err := s.repo.CreateSession(ctx, domain.ExamSession{
		OperationID: operationID, Kind: domain.ExamKindRetry, FormID: orig.FormID, FormTitle: orig.FormTitle,
		RetryOf: &id, RetryOfPosition: position, FormsSHA256: s.formsSHA, PackSHA256: s.packSHA,
		DurationSeconds: s.forms.RetrySeconds, StartedAt: now, DeadlineAt: now.Add(time.Duration(s.forms.RetrySeconds) * time.Second),
		Items: []domain.ExamItem{it},
	})
	if err != nil {
		return nil, false, err
	}
	out, err := s.view(ctx, sess)
	return out, replay, err
}

func (s *ExamService) replayOnly(ctx context.Context, operationID string, orig domain.ExamSession, position int) (*ExamView, bool, error) {
	id := orig.ID
	sessions, err := s.repo.ListSessions(ctx)
	if err != nil {
		return nil, false, err
	}
	for _, x := range sessions {
		if x.OperationID == operationID && x.RetryOf != nil && *x.RetryOf == id && x.RetryOfPosition == position {
			full, err := s.repo.GetSession(ctx, x.ID)
			if err != nil {
				return nil, false, err
			}
			v, err := s.view(ctx, full)
			return v, true, err
		}
	}
	return nil, false, domain.ErrNotFound
}

// Get returns one session as seen now.
func (s *ExamService) Get(ctx context.Context, id int64) (*ExamView, error) {
	sess, err := s.repo.GetSession(ctx, id)
	if err != nil {
		return nil, err
	}
	return s.view(ctx, sess)
}

// ExamSummary is one row of the session list.
type ExamSummary struct {
	Session domain.ExamSession
	State   string
	Correct int
	Total   int
	Closed  bool
}

// List returns every session (newest first) with its state and, once
// closed, its result.
func (s *ExamService) List(ctx context.Context) ([]ExamSummary, error) {
	sessions, err := s.repo.ListSessions(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]ExamSummary, 0, len(sessions))
	for _, x := range sessions {
		full, err := s.repo.GetSession(ctx, x.ID)
		if err != nil {
			return nil, err
		}
		v, err := s.view(ctx, full)
		if err != nil {
			return nil, err
		}
		out = append(out, ExamSummary{Session: full, State: v.State, Correct: v.Correct, Total: len(full.Items), Closed: v.Final != nil})
	}
	return out, nil
}

// SaveAnswer records one answer before the deadline.
func (s *ExamService) SaveAnswer(ctx context.Context, id int64, position int, choice *int) (domain.ExamAnswer, *ExamView, error) {
	sess, err := s.repo.GetSession(ctx, id)
	if err != nil {
		return domain.ExamAnswer{}, nil, err
	}
	if err := domain.ValidateExamChoice(sess, position, choice); err != nil {
		return domain.ExamAnswer{}, nil, err
	}
	a, _, err := s.repo.SaveAnswer(ctx, id, position, choice, s.Now())
	if err != nil {
		v, verr := s.view(ctx, sess)
		if verr != nil {
			return domain.ExamAnswer{}, nil, verr
		}
		return domain.ExamAnswer{}, v, err
	}
	v, err := s.view(ctx, sess)
	return a, v, err
}

// Submit closes a session with its answers. A repeated submission with the
// same answers replays (true); after the deadline the expired result is
// returned with ErrExamExpired.
func (s *ExamService) Submit(ctx context.Context, id int64, answers map[int]*int) (*ExamView, bool, error) {
	sess, err := s.repo.GetSession(ctx, id)
	if err != nil {
		return nil, false, err
	}
	for p, c := range answers {
		if err := domain.ValidateExamChoice(sess, p, c); err != nil {
			return nil, false, err
		}
	}
	_, replay, err := s.repo.Submit(ctx, id, answers, s.Now())
	v, verr := s.view(ctx, sess)
	if verr != nil {
		return nil, false, verr
	}
	return v, replay, err
}
