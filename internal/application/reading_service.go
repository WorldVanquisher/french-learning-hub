package application

import (
	"context"
	"errors"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// ReadingService implements Exam Reading v1: lessons from a learner's own
// French passage or from the embedded authored pack, and one explicit, opt-in
// exercise generation per request through the same attempt-first path as
// Listening (record the attempt, one call, validate against the exact passage
// version, store the outcome; a timeout or lost response is unknown and needs
// an acknowledged retry). Reads never call the generator. There is no retry and
// no background work.
type ReadingService struct {
	repo      domain.ReadingRepository
	generator domain.ReadingExerciseGenerator // nil when READING_PROVIDER=disabled
	pack      domain.ReadingPack
	now       func() time.Time
	deadline  time.Duration
}

// ReadingOption configures a ReadingService.
type ReadingOption func(*ReadingService)

// WithReadingClock replaces the clock (tests).
func WithReadingClock(now func() time.Time) ReadingOption {
	return func(s *ReadingService) { s.now = now }
}

// WithReadingDeadline sets how long an unfinished attempt reads as in progress
// before its outcome is reported as unknown. It must exceed the generator's timeout.
func WithReadingDeadline(d time.Duration) ReadingOption {
	return func(s *ReadingService) { s.deadline = d }
}

// NewReadingService builds the service. packJSON is the authored example pack;
// an invalid pack is refused here, so the server does not start with it.
func NewReadingService(repo domain.ReadingRepository, generator domain.ReadingExerciseGenerator, packJSON []byte, opts ...ReadingOption) (*ReadingService, error) {
	pack, err := domain.ParseReadingPack(packJSON)
	if err != nil {
		return nil, fmt.Errorf("reading examples: %w", err)
	}
	s := &ReadingService{repo: repo, generator: generator, pack: pack, now: func() time.Time { return time.Now().UTC() }, deadline: DefaultPreparationDeadline}
	for _, o := range opts {
		o(s)
	}
	return s, nil
}

// Now is the service clock, used for derived attempt states.
func (s *ReadingService) Now() time.Time { return s.now() }

// GeneratorEnabled reports whether preparation can call a provider, and the
// provenance it would record.
func (s *ReadingService) GeneratorEnabled() (bool, string) {
	if s.generator == nil {
		return false, ""
	}
	return true, s.generator.Name()
}

// ReadingLessonView is one lesson with its latest passage and every attempt.
type ReadingLessonView struct {
	Lesson       domain.ReadingLesson
	Passage      domain.ReadingPassage // latest version
	Versions     int
	Exercises    []domain.ReadingExercise    // newest first, every version
	Preparations []domain.ReadingPreparation // newest first
	State        string
	Now          time.Time
}

// ReadingLessonSummary is a list row.
type ReadingLessonSummary struct {
	Lesson         domain.ReadingLesson
	PassageVersion int
	Paragraphs     int
	State          string
}

// ReadingExample is one authored passage offered as an example.
type ReadingExample struct {
	ID               string
	Title            string
	Format           string
	StyleLevel       string
	Paragraphs       int
	Questions        int
	HasInference     bool
	ImportedLessonID *int64
}

// CreateLesson validates and stores a title, a French passage and an optional
// https source link (stored as text, never fetched).
func (s *ReadingService) CreateLesson(ctx context.Context, title, text, sourceURL string) (*ReadingLessonView, error) {
	t, err := domain.NormalizeListeningTitle(title)
	if err != nil {
		return nil, err
	}
	link, err := domain.NormalizeReadingSourceURL(sourceURL)
	if err != nil {
		return nil, err
	}
	segments, err := domain.ParseReadingText(text)
	if err != nil {
		return nil, err
	}
	l, _, err := s.repo.CreateLesson(ctx, domain.ReadingLesson{Title: t, SourceURL: link, Origin: domain.ReadingOriginLearner}, segments, s.now())
	if err != nil {
		return nil, err
	}
	return s.GetLesson(ctx, l.ID)
}

// AddPassage stores the next version of a learner lesson's text. Earlier
// versions and their exercises are kept unchanged.
func (s *ReadingService) AddPassage(ctx context.Context, lessonID int64, text string) (*ReadingLessonView, error) {
	segments, err := domain.ParseReadingText(text)
	if err != nil {
		return nil, err
	}
	if _, err := s.repo.AddPassage(ctx, lessonID, segments, s.now()); err != nil {
		return nil, err
	}
	return s.GetLesson(ctx, lessonID)
}

// GetLesson reads one lesson. It never calls the generator.
func (s *ReadingService) GetLesson(ctx context.Context, id int64) (*ReadingLessonView, error) {
	l, err := s.repo.GetLesson(ctx, id)
	if err != nil {
		return nil, err
	}
	p, err := s.repo.LatestPassage(ctx, id)
	if err != nil {
		return nil, err
	}
	versions, err := s.repo.ListPassages(ctx, id)
	if err != nil {
		return nil, err
	}
	ex, err := s.repo.ListExercises(ctx, id)
	if err != nil {
		return nil, err
	}
	preps, err := s.repo.ListPreparations(ctx, id)
	if err != nil {
		return nil, err
	}
	now := s.now()
	return &ReadingLessonView{Lesson: l, Passage: p, Versions: len(versions), Exercises: ex, Preparations: preps, State: readingState(p, ex, preps, now), Now: now}, nil
}

func readingState(p domain.ReadingPassage, ex []domain.ReadingExercise, preps []domain.ReadingPreparation, now time.Time) string {
	if len(preps) > 0 {
		switch preps[0].State(now) {
		case domain.ListeningStateInProgress:
			return domain.ReadingStateInProgress
		case domain.ListeningOutcomeUnknown:
			return domain.ReadingStateUnknown
		}
	}
	latest := ""
	for _, e := range ex {
		if e.PassageID != p.ID {
			continue
		}
		if e.Status == domain.ListeningExerciseCompleted {
			return domain.ReadingStatePrepared
		}
		if latest == "" {
			latest = e.Status
		}
	}
	if latest == domain.ListeningExerciseFailed {
		return domain.ReadingStateFailed
	}
	return domain.ReadingStateReady
}

// ListLessons lists every lesson, newest first. It never calls the generator.
func (s *ReadingService) ListLessons(ctx context.Context) ([]ReadingLessonSummary, error) {
	ls, err := s.repo.ListLessons(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]ReadingLessonSummary, 0, len(ls))
	for _, l := range ls {
		v, err := s.GetLesson(ctx, l.ID)
		if err != nil {
			return nil, err
		}
		out = append(out, ReadingLessonSummary{Lesson: l, PassageVersion: v.Passage.Version, Paragraphs: len(v.Passage.Segments), State: v.State})
	}
	return out, nil
}

// ListExamples lists the authored pack's passages and whether each is imported.
func (s *ReadingService) ListExamples(ctx context.Context) ([]ReadingExample, error) {
	ls, err := s.repo.ListLessons(ctx)
	if err != nil {
		return nil, err
	}
	imported := map[string]int64{}
	for _, l := range ls {
		if l.PackPassageID != "" {
			imported[l.PackPassageID] = l.ID
		}
	}
	out := make([]ReadingExample, 0, len(s.pack.Passages))
	for _, p := range s.pack.Passages {
		e := ReadingExample{ID: p.ID, Title: p.Title, Format: p.Format, StyleLevel: p.StyleLevel, Paragraphs: len(p.Segments), Questions: len(p.Questions)}
		for _, q := range p.Questions {
			e.HasInference = e.HasInference || q.Kind == domain.ListeningInference
		}
		if id, ok := imported[domain.ReadingPackID+"/"+p.ID]; ok {
			e.ImportedLessonID = &id
		}
		out = append(out, e)
	}
	return out, nil
}

// ImportExample imports one authored passage with its reviewed exercise. It
// makes no model call. Importing it again returns the existing lesson (true).
func (s *ReadingService) ImportExample(ctx context.Context, passageID string) (*ReadingLessonView, bool, error) {
	for _, p := range s.pack.Passages {
		if p.ID != passageID {
			continue
		}
		var link string
		if p.Source != nil && p.Source.Link != nil {
			link = *p.Source.Link
		}
		content := domain.ReadingExerciseContent{Items: p.Questions, NoInferenceReason: p.NoInferenceReason}
		l, replay, err := s.repo.ImportAuthored(ctx, domain.ReadingLesson{Title: p.Title, SourceURL: link, Origin: domain.ReadingOriginAuthored,
			PackPassageID: domain.ReadingPackID + "/" + p.ID}, p.Segments, content, s.now())
		if err != nil {
			return nil, false, err
		}
		v, err := s.GetLesson(ctx, l.ID)
		return v, replay, err
	}
	return nil, false, fmt.Errorf("%w: no authored example %q", domain.ErrNotFound, passageID)
}

// ReadingPrepareRequest is one explicit Prepare click.
type ReadingPrepareRequest struct {
	LessonID            int64
	OperationID         string // UUID; empty: generated
	ConfirmUnknownRetry bool
}

// ReadingPreparationResult is one attempt and, once finished, its exercise.
type ReadingPreparationResult struct {
	Preparation domain.ReadingPreparation
	Exercise    *domain.ReadingExercise
}

// ReadingGenerationError carries the stored attempt and failed exercise.
type ReadingGenerationError struct {
	Exercise    domain.ReadingExercise
	Preparation domain.ReadingPreparation
	Err         error
}

func (e *ReadingGenerationError) Error() string { return e.Err.Error() }
func (e *ReadingGenerationError) Unwrap() error { return e.Err }

// PrepareExercise records an attempt, makes one provider call over the latest
// passage version, validates the output against that exact version and stores
// the outcome. Errors: domain.ErrReadingDisabled (nothing stored),
// domain.ErrNotFound, domain.ErrReadingPreparationInProgress /
// ErrReadingOutcomeUnknown (no call; the blocking attempt is returned),
// ErrReadingOperationConflict, or *ReadingGenerationError (stored failure).
func (s *ReadingService) PrepareExercise(ctx context.Context, req ReadingPrepareRequest) (*ReadingPreparationResult, bool, error) {
	if s.generator == nil {
		return nil, false, domain.ErrReadingDisabled
	}
	op := req.OperationID
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
	p, passage, replay, err := s.repo.StartPreparation(ctx, domain.NewReadingPreparation{
		OperationID: op, LessonID: req.LessonID, ConfirmUnknownRetry: req.ConfirmUnknownRetry, Now: now, Deadline: now.Add(s.deadline),
	})
	if err != nil {
		if p.ID != 0 {
			return &ReadingPreparationResult{Preparation: p}, false, err
		}
		return nil, false, err
	}
	if replay {
		out, err := s.withExercise(ctx, p)
		return out, true, err
	}
	l, err := s.repo.GetLesson(ctx, req.LessonID)
	if err != nil {
		return &ReadingPreparationResult{Preparation: p}, false, err
	}
	content, genErr := s.generator.Generate(ctx, domain.ReadingGenerationRequest{Title: l.Title, Segments: passage.Segments})
	if genErr == nil {
		genErr = domain.ValidateReadingExercise(passage.Segments, &content, false)
	}
	row := domain.ReadingExercise{LessonID: l.ID, PassageID: passage.ID, Generator: s.generator.Name()}
	if genErr != nil {
		if !errors.Is(genErr, domain.ErrProviderTimeout) && !errors.Is(genErr, domain.ErrProviderUnavailable) && !errors.Is(genErr, domain.ErrValidation) {
			genErr = fmt.Errorf("%w: %w: %v", domain.ErrProviderUnavailable, domain.ErrOutcomeUnknown, genErr)
		}
		row.Status, row.FailureCode = domain.ListeningExerciseFailed, domain.ReadingFailureCode(genErr)
	} else {
		row.Status, row.Content = domain.ListeningExerciseCompleted, &content
	}
	storeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), commitTimeout)
	defer cancel()
	finished, stored, err := s.repo.FinishPreparation(storeCtx, p.ID, domain.PreparationOutcome(genErr), row, s.now())
	if err != nil {
		return &ReadingPreparationResult{Preparation: p}, false, err
	}
	out := &ReadingPreparationResult{Preparation: finished, Exercise: &stored}
	if genErr != nil {
		return out, false, &ReadingGenerationError{Exercise: stored, Preparation: finished, Err: genErr}
	}
	return out, false, nil
}

// GetPreparation looks an attempt up by its key.
func (s *ReadingService) GetPreparation(ctx context.Context, operationID string) (*ReadingPreparationResult, error) {
	op, err := domain.NormalizeAnnotationOperationID(operationID)
	if err != nil {
		return nil, fmt.Errorf("%w: invalid idempotency key", domain.ErrValidation)
	}
	p, err := s.repo.GetPreparationByOperation(ctx, op)
	if err != nil {
		return nil, err
	}
	return s.withExercise(ctx, p)
}

func (s *ReadingService) withExercise(ctx context.Context, p domain.ReadingPreparation) (*ReadingPreparationResult, error) {
	out := &ReadingPreparationResult{Preparation: p}
	if p.ExerciseID != nil {
		e, err := s.repo.GetExercise(ctx, *p.ExerciseID)
		if err != nil {
			return nil, err
		}
		out.Exercise = &e
	}
	return out, nil
}
