package application

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"time"

	"french-learning-app/internal/domain"
)

// ListeningService implements Exam Listening Lesson v1: saving YouTube material
// with an optional learner-supplied transcript, and one explicit, opt-in
// exercise generation per request. Reads never call the generator. A provider
// failure or unusable output is stored as a failed exercise next to the
// untouched material and transcript; there is no retry and no background work.
// Every preparation, explicit or made by a Daily Listening pull, goes through
// prepare: an attempt row first, then one call, then the stored outcome.
type ListeningService struct {
	repo      ListeningStore
	generator domain.ListeningExerciseGenerator // nil when LISTENING_PROVIDER=disabled
	now       func() time.Time
	deadline  time.Duration
}

// ListeningStore is the listening repository: lessons plus the Daily Listening
// receipts, which the shared preparation path needs.
type ListeningStore interface {
	domain.ListeningRepository
	domain.ListeningDailyRepository
}

// ListeningOption configures a ListeningService.
type ListeningOption func(*ListeningService)

// WithListeningClock replaces the clock (tests).
func WithListeningClock(now func() time.Time) ListeningOption {
	return func(s *ListeningService) { s.now = now }
}

// WithPreparationDeadline sets how long an unfinished attempt reads as in
// progress before its outcome is reported as unknown. It must exceed the
// generator's own timeout.
func WithPreparationDeadline(d time.Duration) ListeningOption {
	return func(s *ListeningService) { s.deadline = d }
}

// DefaultPreparationDeadline is used when no deadline is configured.
const DefaultPreparationDeadline = 2 * time.Minute

// NewListeningService builds the service. generator may be nil (disabled).
func NewListeningService(repo ListeningStore, generator domain.ListeningExerciseGenerator, opts ...ListeningOption) *ListeningService {
	s := &ListeningService{repo: repo, generator: generator, now: func() time.Time { return time.Now().UTC() }, deadline: DefaultPreparationDeadline}
	for _, o := range opts {
		o(s)
	}
	return s
}

// ListeningLesson is one material with its latest transcript and every stored
// exercise attempt (newest first).
type ListeningLesson struct {
	Material   domain.ListeningMaterial
	Transcript *domain.ListeningTranscript
	Exercises  []domain.ListeningExercise
	// Status is derived: state, playlist membership, attempts and notifications.
	Status domain.ListeningMaterialStatus
	Now    time.Time
}

// ListeningMaterialSummary is a list row.
type ListeningMaterialSummary struct {
	Material          domain.ListeningMaterial
	TranscriptVersion int // 0 when no transcript
	SegmentCount      int
	LatestExercise    *domain.ListeningExercise
	State             string
	InPlaylist        bool
}

// ListeningGenerationError carries the stored attempt and failed exercise for a
// provider failure, an unknown outcome or invalid output, so the caller can show it.
type ListeningGenerationError struct {
	Exercise    domain.ListeningExercise
	Preparation domain.ListeningPreparation
	Err         error
}

func (e *ListeningGenerationError) Error() string { return e.Err.Error() }
func (e *ListeningGenerationError) Unwrap() error { return e.Err }

// Now is the service clock, used for derived attempt states.
func (s *ListeningService) Now() time.Time { return s.now() }

// GeneratorEnabled reports whether preparation can call a provider, and the
// provenance it would record.
func (s *ListeningService) GeneratorEnabled() (bool, string) {
	if s.generator == nil {
		return false, ""
	}
	return true, s.generator.Name()
}

// CreateMaterial validates and stores a link, a title and an optional
// transcript (blank means "no transcript yet").
func (s *ListeningService) CreateMaterial(ctx context.Context, sourceURL, title, transcript string) (*ListeningLesson, error) {
	videoID, canonical, err := domain.ParseYouTubeURL(sourceURL)
	if err != nil {
		return nil, err
	}
	t, err := domain.NormalizeListeningTitle(title)
	if err != nil {
		return nil, err
	}
	var segments []domain.TranscriptSegment
	var timed bool
	if strings.TrimSpace(transcript) != "" {
		if segments, timed, err = domain.ParseTranscript(transcript); err != nil {
			return nil, err
		}
	}
	m, _, err := s.repo.CreateMaterial(ctx, domain.ListeningMaterial{VideoID: videoID, SourceURL: canonical, Title: t}, segments, timed)
	if err != nil {
		return nil, err
	}
	return s.GetLesson(ctx, m.ID)
}

// AddTranscript stores a new transcript version for existing material.
func (s *ListeningService) AddTranscript(ctx context.Context, materialID int64, transcript string) (*ListeningLesson, error) {
	segments, timed, err := domain.ParseTranscript(transcript)
	if err != nil {
		return nil, err
	}
	if _, err := s.repo.AddTranscript(ctx, materialID, segments, timed); err != nil {
		return nil, err
	}
	return s.GetLesson(ctx, materialID)
}

// GetLesson reads one lesson. It never calls the generator.
func (s *ListeningService) GetLesson(ctx context.Context, materialID int64) (*ListeningLesson, error) {
	m, err := s.repo.GetMaterial(ctx, materialID)
	if err != nil {
		return nil, err
	}
	tr, err := s.repo.LatestTranscript(ctx, materialID)
	if err != nil {
		return nil, err
	}
	ex, err := s.repo.ListExercises(ctx, materialID)
	if err != nil {
		return nil, err
	}
	now := s.now()
	st, err := s.repo.MaterialStatus(ctx, materialID, now)
	if err != nil {
		return nil, err
	}
	return &ListeningLesson{Material: m, Transcript: tr, Exercises: ex, Status: st, Now: now}, nil
}

// ListMaterials lists every material, newest first. It never calls the generator.
func (s *ListeningService) ListMaterials(ctx context.Context) ([]ListeningMaterialSummary, error) {
	ms, err := s.repo.ListMaterials(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]ListeningMaterialSummary, 0, len(ms))
	for _, m := range ms {
		row := ListeningMaterialSummary{Material: m}
		tr, err := s.repo.LatestTranscript(ctx, m.ID)
		if err != nil {
			return nil, err
		}
		if tr != nil {
			row.TranscriptVersion, row.SegmentCount = tr.Version, len(tr.Segments)
		}
		ex, err := s.repo.ListExercises(ctx, m.ID)
		if err != nil {
			return nil, err
		}
		if len(ex) > 0 {
			row.LatestExercise = &ex[0]
		}
		st, err := s.repo.MaterialStatus(ctx, m.ID, s.now())
		if err != nil {
			return nil, err
		}
		row.State, row.InPlaylist = st.State, st.InPlaylist
		out = append(out, row)
	}
	return out, nil
}

// ListeningPrepareRequest is one explicit Prepare click.
type ListeningPrepareRequest struct {
	MaterialID int64
	// OperationID is the caller's key (a UUID). Resending the same key returns
	// the stored attempt instead of calling the provider again. Empty: one is
	// generated and the attempt can only be found through the lesson.
	OperationID string
	// ConfirmUnknownRetry acknowledges that the previous attempt's outcome is
	// unknown (it may have been processed and billed) and asks for a new call.
	ConfirmUnknownRetry bool
}

// ListeningPreparationResult is one attempt and, once finished, its exercise.
type ListeningPreparationResult struct {
	Preparation domain.ListeningPreparation
	Exercise    *domain.ListeningExercise
}

// PrepareExercise is the explicit Prepare button. It goes through the same
// preparation path as a pull (see prepare). The returned bool is true for a
// same-key replay. Errors:
//   - domain.ErrListeningDisabled: no generator, nothing stored;
//   - domain.ErrNotFound: unknown material;
//   - domain.ErrListeningNoTranscript: no call, nothing stored;
//   - domain.ErrListeningPreparationInProgress / ErrListeningOutcomeUnknown: no
//     call; the blocking attempt is returned in the result;
//   - *ListeningGenerationError: the call failed or its outcome is unknown; the
//     attempt and the failed exercise are stored and returned.
func (s *ListeningService) PrepareExercise(ctx context.Context, req ListeningPrepareRequest) (*ListeningPreparationResult, bool, error) {
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
	return s.prepare(ctx, domain.NewListeningPreparation{
		OperationID: op, MaterialID: req.MaterialID, Trigger: domain.ListeningTriggerExplicit,
		ConfirmUnknownRetry: req.ConfirmUnknownRetry,
	})
}

// GetPreparation looks an attempt up by its key, with its exercise when it has
// finished. domain.ErrNotFound means nothing was recorded under the key.
func (s *ListeningService) GetPreparation(ctx context.Context, operationID string) (*ListeningPreparationResult, error) {
	op, err := domain.NormalizeAnnotationOperationID(operationID)
	if err != nil {
		op = operationID // pull attempts use generated keys
	}
	p, err := s.repo.GetPreparationByOperation(ctx, op)
	if err != nil {
		return nil, err
	}
	return s.withExercise(ctx, p)
}

func (s *ListeningService) withExercise(ctx context.Context, p domain.ListeningPreparation) (*ListeningPreparationResult, error) {
	out := &ListeningPreparationResult{Preparation: p}
	if p.ExerciseID != nil {
		e, err := s.repo.GetExercise(ctx, *p.ExerciseID)
		if err != nil {
			return nil, err
		}
		out.Exercise = &e
	}
	return out, nil
}

// prepare is the one preparation path, shared by the Prepare button and pulls.
// It records the attempt BEFORE calling the provider (the repository decides,
// atomically, whether it may start), makes exactly one call, validates the
// output against the exact transcript, and finishes the attempt with its
// exercise row. A timeout or a lost provider response is stored as outcome
// unknown, never retried. The finishing write is detached from the caller's
// cancellation, so a client that went away does not discard a result.
func (s *ListeningService) prepare(ctx context.Context, in domain.NewListeningPreparation) (*ListeningPreparationResult, bool, error) {
	if s.generator == nil {
		return nil, false, domain.ErrListeningDisabled
	}
	now := s.now()
	in.Now, in.Deadline = now, now.Add(s.deadline)
	p, tr, replay, err := s.repo.StartPreparation(ctx, in)
	if err != nil {
		if p.ID != 0 {
			return &ListeningPreparationResult{Preparation: p}, false, err
		}
		return nil, false, err
	}
	if replay {
		out, err := s.withExercise(ctx, p)
		return out, true, err
	}
	m, err := s.repo.GetMaterial(ctx, in.MaterialID)
	if err != nil {
		return &ListeningPreparationResult{Preparation: p}, false, err
	}
	content, genErr := s.generator.Generate(ctx, domain.ListeningGenerationRequest{Title: m.Title, Segments: tr.Segments})
	if genErr == nil {
		genErr = domain.ValidateListeningExercise(tr.Segments, &content)
	}
	row := domain.ListeningExercise{MaterialID: m.ID, TranscriptID: tr.ID, Generator: s.generator.Name()}
	if genErr != nil {
		if !errors.Is(genErr, domain.ErrProviderTimeout) && !errors.Is(genErr, domain.ErrProviderUnavailable) && !errors.Is(genErr, domain.ErrValidation) {
			genErr = fmt.Errorf("%w: %w: %v", domain.ErrProviderUnavailable, domain.ErrOutcomeUnknown, genErr)
		}
		row.Status, row.FailureCode = domain.ListeningExerciseFailed, domain.ListeningFailureCode(genErr)
	} else {
		row.Status, row.Content = domain.ListeningExerciseCompleted, &content
	}
	storeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), commitTimeout)
	defer cancel()
	finished, stored, err := s.repo.FinishPreparation(storeCtx, p.ID, domain.PreparationOutcome(genErr), row, s.now())
	if err != nil {
		// The attempt stays unfinished and reads as unknown after its deadline.
		return &ListeningPreparationResult{Preparation: p}, false, err
	}
	out := &ListeningPreparationResult{Preparation: finished, Exercise: &stored}
	if genErr != nil {
		return out, false, &ListeningGenerationError{Exercise: stored, Preparation: finished, Err: genErr}
	}
	return out, false, nil
}

func newOperationKey() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", fmt.Errorf("generate operation key: %w", err)
	}
	b[6] = b[6]&0x0f | 0x40
	b[8] = b[8]&0x3f | 0x80
	h := hex.EncodeToString(b[:])
	return h[0:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:32], nil
}
