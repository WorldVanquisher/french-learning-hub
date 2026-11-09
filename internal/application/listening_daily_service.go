package application

import (
	"context"
	"errors"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// ListeningDailySettings configure Daily Listening. Zero values are off.
type ListeningDailySettings struct {
	// AutoPrepare lets a pull prepare at most domain.ListeningDailyPreparationCap
	// lessons per local day (Location) through the shared preparation path.
	AutoPrepare bool
	Location    *time.Location
	// SourceBudget bounds the playlist read (pages x per-request timeout).
	SourceBudget time.Duration
	// NotifyDeadline is how long an unfinished send reads as in progress before
	// its outcome is reported as unknown. It must exceed the notifier's timeout.
	NotifyDeadline time.Duration
}

// ListeningDailyService is the one pull operation, used by the workbench button
// (POST /listening/pull) and by the operator command (cmd/listening-pull, run
// by a timer). Each pull holds a lease so runs never overlap, records every
// step's outcome on its run row, and never retries anything by itself.
type ListeningDailyService struct {
	lessons  *ListeningService
	repo     ListeningStore
	source   domain.ListeningPlaylistSource // nil: no playlist is read
	notifier domain.ListeningNotifier       // nil: nothing is sent
	settings ListeningDailySettings
	lease    time.Duration
}

// leaseMargin is added to the sum of the step budgets.
const leaseMargin = time.Minute

// NewListeningDailyService builds the service over the lesson service, whose
// repository, clock, generator and preparation path it shares.
func NewListeningDailyService(lessons *ListeningService, source domain.ListeningPlaylistSource, notifier domain.ListeningNotifier, settings ListeningDailySettings) *ListeningDailyService {
	if settings.Location == nil {
		settings.Location = time.UTC
	}
	if settings.NotifyDeadline <= 0 {
		settings.NotifyDeadline = DefaultPreparationDeadline
	}
	return &ListeningDailyService{
		lessons: lessons, repo: lessons.repo, source: source, notifier: notifier, settings: settings,
		lease: settings.SourceBudget + lessons.deadline + settings.NotifyDeadline + leaseMargin,
	}
}

func (s *ListeningDailyService) now() time.Time { return s.lessons.now() }

// Now is the service clock (for derived states in responses).
func (s *ListeningDailyService) Now() time.Time { return s.now() }

func (s *ListeningDailyService) autoPrepare() bool {
	return s.settings.AutoPrepare && s.lessons.generator != nil
}

// NotifyChannel reports whether notifications are on, and the channel.
func (s *ListeningDailyService) NotifyChannel() (bool, string) {
	if s.notifier == nil {
		return false, ""
	}
	return true, s.notifier.Channel()
}

// PullEnabled reports whether a pull has anything to do.
func (s *ListeningDailyService) PullEnabled() bool { return s.source != nil || s.autoPrepare() }

// ListeningDailyStatus is the read-only overview for the workbench and the
// operator command.
type ListeningDailyStatus struct {
	PullEnabled    bool
	SourceEnabled  bool
	SourceName     string
	PrepareEnabled bool
	Generator      string
	DailyCap       int
	Timezone       string
	Today          string
	UsedToday      int
	NotifyEnabled  bool
	Channel        string
	LastRun        *domain.ListeningPullRun
	Now            time.Time
}

// Status reads settings, today's use of the cap and the last run. It calls no
// outside service.
func (s *ListeningDailyService) Status(ctx context.Context) (ListeningDailyStatus, error) {
	now := s.now()
	st := ListeningDailyStatus{
		PullEnabled: s.PullEnabled(), SourceEnabled: s.source != nil, PrepareEnabled: s.autoPrepare(),
		DailyCap: domain.ListeningDailyPreparationCap, Timezone: s.settings.Location.String(),
		Today: domain.ListeningDay(now, s.settings.Location), NotifyEnabled: s.notifier != nil, Now: now,
	}
	if s.source != nil {
		st.SourceName = s.source.Name()
	}
	if st.PrepareEnabled {
		st.Generator = s.lessons.generator.Name()
	}
	if s.notifier != nil {
		st.Channel = s.notifier.Channel()
	}
	var err error
	if st.UsedToday, err = s.repo.PullPreparationsOnDay(ctx, st.Today); err != nil {
		return st, err
	}
	st.LastRun, err = s.repo.LatestPullRun(ctx)
	return st, err
}

// Pull runs one pull under operationID (a UUID). The same key returns the
// stored run (true), whether it is still running or finished, and never starts
// another. While another run holds its lease it returns that run with
// domain.ErrListeningPullBusy. The caller decides whether its own cancellation
// should stop the run; the run's own bookkeeping writes are detached from it.
func (s *ListeningDailyService) Pull(ctx context.Context, operationID, trigger string) (domain.ListeningPullRun, bool, error) {
	if !s.PullEnabled() {
		return domain.ListeningPullRun{}, false, domain.ErrListeningPullNotConfigured
	}
	if trigger != domain.ListeningPullManual && trigger != domain.ListeningPullScheduled {
		return domain.ListeningPullRun{}, false, fmt.Errorf("%w: unknown pull trigger", domain.ErrValidation)
	}
	op, err := domain.NormalizeAnnotationOperationID(operationID)
	if err != nil {
		return domain.ListeningPullRun{}, false, fmt.Errorf("%w: invalid idempotency key", domain.ErrValidation)
	}
	now := s.now()
	run, replay, err := s.repo.StartPullRun(ctx, op, trigger, now, now.Add(s.lease))
	if err != nil || replay {
		return run, replay, err
	}
	var rep domain.ListeningPullReport
	if err := s.pullSource(ctx, run.ID, &rep); err != nil {
		return run, false, err
	}
	exercise, err := s.prepareOne(ctx, run.ID, &rep)
	if err != nil {
		return run, false, err
	}
	if err := s.notifyReady(ctx, run.ID, exercise, &rep); err != nil {
		return run, false, err
	}
	storeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), commitTimeout)
	defer cancel()
	finished, err := s.repo.FinishPullRun(storeCtx, run.ID, rep, s.now())
	return finished, false, err
}

// GetPullRun looks a run up by its key. domain.ErrNotFound means nothing is
// recorded under the key (the request may not have arrived yet).
func (s *ListeningDailyService) GetPullRun(ctx context.Context, operationID string) (domain.ListeningPullRun, error) {
	op, err := domain.NormalizeAnnotationOperationID(operationID)
	if err != nil {
		return domain.ListeningPullRun{}, fmt.Errorf("%w: invalid idempotency key", domain.ErrValidation)
	}
	return s.repo.GetPullRunByOperation(ctx, op)
}

// pullSource reads the playlist and records each video ID once. A source
// failure is recorded on the run; the other steps still run.
func (s *ListeningDailyService) pullSource(ctx context.Context, runID int64, rep *domain.ListeningPullReport) error {
	if s.source == nil {
		rep.SourceOutcome = domain.ListeningStepDisabled
		return nil
	}
	listing, err := s.source.List(ctx)
	if err != nil {
		rep.SourceOutcome, rep.SourceFailure = domain.ListeningSourceFailed, domain.PlaylistFailureCode(err)
		return nil
	}
	rep.SourceOutcome, rep.ItemsSkipped = domain.ListeningSourceOK, listing.Skipped
	for _, item := range listing.Items {
		rec, err := s.repo.RecordPlaylistItem(ctx, runID, listing.PlaylistID, item, s.now())
		if errors.Is(err, domain.ErrValidation) {
			rep.ItemsSkipped++
			continue
		}
		if err != nil {
			return err
		}
		rep.ItemsSeen++
		if rec.Created {
			rep.MaterialsCreated++
		} else {
			rep.ItemsKnown++
		}
	}
	return nil
}

// prepareOne prepares at most one lesson within the daily cap, through the same
// path as the Prepare button. Only playlist material whose latest transcript
// was never attempted is eligible; a failed or unknown attempt is never
// retried here. It returns the completed exercise, if any.
func (s *ListeningDailyService) prepareOne(ctx context.Context, runID int64, rep *domain.ListeningPullReport) (*domain.ListeningExercise, error) {
	if !s.autoPrepare() {
		rep.PrepareOutcome = domain.ListeningStepDisabled
		return nil, nil
	}
	day := domain.ListeningDay(s.now(), s.settings.Location)
	used, err := s.repo.PullPreparationsOnDay(ctx, day)
	if err != nil {
		return nil, err
	}
	if used >= domain.ListeningDailyPreparationCap {
		rep.PrepareOutcome = domain.ListeningPrepareCapReached
		return nil, nil
	}
	candidate, err := s.repo.NextPullCandidate(ctx)
	if err != nil {
		return nil, err
	}
	if candidate == nil {
		rep.PrepareOutcome = domain.ListeningPrepareNothing
		return nil, nil
	}
	res, _, err := s.lessons.prepare(ctx, domain.NewListeningPreparation{
		OperationID: domain.PullOperationID("prepare", runID), MaterialID: *candidate,
		Trigger: domain.ListeningTriggerPull, PullRunID: &runID, PullDay: day,
	})
	var genErr *ListeningGenerationError
	switch {
	case errors.Is(err, domain.ErrListeningDailyCapReached):
		rep.PrepareOutcome = domain.ListeningPrepareCapReached
	case errors.Is(err, domain.ErrListeningNotEligible), errors.Is(err, domain.ErrListeningOutcomeUnknown),
		errors.Is(err, domain.ErrListeningPreparationInProgress), errors.Is(err, domain.ErrListeningNoTranscript):
		// The candidate changed between selection and the locked check.
		rep.PrepareOutcome = domain.ListeningPrepareNothing
	case errors.As(err, &genErr):
		rep.PrepareOutcome = genErr.Preparation.Outcome
	case err != nil:
		return nil, err
	default:
		rep.PrepareOutcome = domain.ListeningOutcomeCompleted
		return res.Exercise, nil
	}
	return nil, nil
}

// notifyReady announces the lesson this run prepared, once. Nothing else is
// ever announced by a pull: not waiting material, not earlier lessons.
func (s *ListeningDailyService) notifyReady(ctx context.Context, runID int64, exercise *domain.ListeningExercise, rep *domain.ListeningPullReport) error {
	switch {
	case s.notifier == nil:
		rep.NotifyOutcome = domain.ListeningStepDisabled
		return nil
	case exercise == nil:
		rep.NotifyOutcome = domain.ListeningNotifyNothingReady
		return nil
	}
	n, _, err := s.send(ctx, domain.NewListeningNotification{
		OperationID: domain.PullOperationID("notify", runID), ExerciseID: exercise.ID,
		Channel: s.notifier.Channel(), Trigger: domain.ListeningTriggerPull, PullRunID: &runID,
	})
	if errors.Is(err, domain.ErrListeningNotEligible) || errors.Is(err, domain.ErrListeningNotificationInProgress) {
		rep.NotifyOutcome = domain.ListeningNotifyNothingReady
		return nil
	}
	if err != nil {
		return err
	}
	rep.NotifyOutcome = n.Outcome
	return nil
}

// RetryNotification is the explicit "send again" for a failed or unknown
// notification. An unknown one needs confirmUnknown (the message may already
// have arrived). The same key returns the stored attempt (true).
func (s *ListeningDailyService) RetryNotification(ctx context.Context, exerciseID int64, operationID string, confirmUnknown bool) (domain.ListeningNotification, bool, error) {
	if s.notifier == nil {
		return domain.ListeningNotification{}, false, domain.ErrListeningNotifyDisabled
	}
	op, err := domain.NormalizeAnnotationOperationID(operationID)
	if err != nil {
		return domain.ListeningNotification{}, false, fmt.Errorf("%w: invalid idempotency key", domain.ErrValidation)
	}
	return s.send(ctx, domain.NewListeningNotification{
		OperationID: op, ExerciseID: exerciseID, Channel: s.notifier.Channel(),
		Trigger: domain.ListeningTriggerExplicit, ConfirmUnknownRetry: confirmUnknown,
	})
}

// GetNotification looks a send attempt up by its key.
func (s *ListeningDailyService) GetNotification(ctx context.Context, operationID string) (domain.ListeningNotification, error) {
	op, err := domain.NormalizeAnnotationOperationID(operationID)
	if err != nil {
		op = operationID // pull attempts use generated keys
	}
	return s.repo.GetNotificationByOperation(ctx, op)
}

// send records the attempt, sends once and stores the classified outcome.
func (s *ListeningDailyService) send(ctx context.Context, in domain.NewListeningNotification) (domain.ListeningNotification, bool, error) {
	exercise, err := s.repo.GetExercise(ctx, in.ExerciseID)
	if err != nil {
		return domain.ListeningNotification{}, false, err
	}
	material, err := s.repo.GetMaterial(ctx, exercise.MaterialID)
	if err != nil {
		return domain.ListeningNotification{}, false, err
	}
	now := s.now()
	in.Now, in.Deadline = now, now.Add(s.settings.NotifyDeadline)
	n, replay, err := s.repo.StartNotification(ctx, in)
	if err != nil || replay {
		return n, replay, err
	}
	sendErr := s.notifier.NotifyLessonReady(ctx, domain.LessonReadyNotice{Title: material.Title})
	outcome, code := domain.NotificationResult(sendErr)
	storeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), commitTimeout)
	defer cancel()
	finished, err := s.repo.FinishNotification(storeCtx, n.ID, outcome, code, s.now())
	if err != nil {
		return n, false, err
	}
	return finished, false, nil
}
