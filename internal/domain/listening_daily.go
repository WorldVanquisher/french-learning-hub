package domain

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// Daily Listening: pull, prepare and notify. One pull operation, shared by the
// workbench button and the operator command (and so by a scheduled timer):
//
//  1. read the configured YouTube playlist's official metadata (bounded) and
//     record each new video ID once as material waiting for a transcript; no
//     transcript is fetched, scraped or transcribed;
//  2. when explicitly enabled, prepare at most one lesson per local day, only
//     from playlist material the learner has given a transcript, through the
//     same preparation path as the explicit Prepare button;
//  3. when explicitly enabled, announce a lesson that pull prepared.
//
// Every outside call is preceded by a stored attempt row, so a timeout, a crash
// or a lost response leaves an honest pending or unknown record. Nothing is
// retried automatically: an unknown outcome needs an explicit, acknowledged
// retry.

// Pull triggers.
const (
	ListeningPullManual    = "manual"
	ListeningPullScheduled = "scheduled"
)

// Pull run statuses.
const (
	ListeningPullRunning     = "running"
	ListeningPullFinished    = "finished"
	ListeningPullInterrupted = "interrupted"
)

// Step outcomes recorded on a finished pull run.
const (
	ListeningStepDisabled = "disabled"

	ListeningSourceOK     = "ok"
	ListeningSourceFailed = "failed"

	ListeningPrepareNothing    = "nothing_to_prepare"
	ListeningPrepareCapReached = "daily_cap_reached"

	ListeningNotifyNothingReady = "nothing_ready"
)

// Source failure codes (non-secret).
const (
	ListeningSourceTimeout         = "source_timeout"
	ListeningSourceUnavailable     = "source_unavailable"
	ListeningSourceRefused         = "source_refused"
	ListeningSourceInvalidResponse = "invalid_response"
)

// Attempt triggers and outcomes, shared by preparations and notifications.
const (
	ListeningTriggerExplicit = "explicit"
	ListeningTriggerPull     = "pull"

	ListeningOutcomeCompleted = "completed"
	ListeningOutcomeFailed    = "failed"
	ListeningOutcomeUnknown   = "unknown"
	ListeningOutcomeSent      = "sent"

	// ListeningStateInProgress is derived: unfinished and before its deadline.
	// Unfinished after the deadline is ListeningOutcomeUnknown.
	ListeningStateInProgress = "in_progress"
)

// Notification failure codes (non-secret).
const (
	NotificationNotSent    = "not_sent"    // the request never left: definitely not delivered
	NotificationRefused    = "refused"     // the service answered with an error: not delivered
	NotificationNoResponse = "no_response" // sent, no usable answer: delivery unknown
)

// Material states derived for the list and lesson views.
const (
	ListeningMaterialWaiting    = "waiting_for_transcript"
	ListeningMaterialReady      = "ready_to_prepare"
	ListeningMaterialInProgress = "in_progress"
	ListeningMaterialPrepared   = "prepared"
	ListeningMaterialFailed     = "failed"
	ListeningMaterialUnknown    = "outcome_unknown"
)

// ListeningDailyPreparationCap is the number of lessons pulls may prepare per
// local day (LISTENING_TIMEZONE). Explicit Prepare clicks are not counted.
const ListeningDailyPreparationCap = 1

// Playlist bounds: the YouTube Data API returns at most 50 items per page.
const (
	MaxPlaylistItems     = 200
	PlaylistPageSize     = 50
	DefaultPlaylistItems = 50
)

var (
	ErrListeningPullBusy               = errors.New("another listening pull is running")
	ErrListeningPullNotConfigured      = errors.New("daily listening is not configured: no playlist source and no automatic preparation")
	ErrListeningPreparationInProgress  = errors.New("a preparation for this material is still in progress")
	ErrListeningOutcomeUnknown         = errors.New("the outcome of the previous attempt is unknown; check it, then confirm an explicit retry")
	ErrListeningOperationConflict      = errors.New("this key was already used for a different request")
	ErrListeningNotEligible            = errors.New("this material is not eligible for automatic preparation")
	ErrListeningDailyCapReached        = errors.New("today's automatic preparation has already been used")
	ErrListeningNotifyDisabled         = errors.New("listening notifications are not enabled")
	ErrListeningNotRetryable           = errors.New("only a failed or unknown notification can be sent again")
	ErrListeningNotificationInProgress = errors.New("a notification for this exercise is still being sent")
	ErrListeningPullLeaseLost          = errors.New("the pull run's lease expired and it was marked interrupted")
	ErrListeningExerciseNotCompleted   = errors.New("only a completed exercise can be announced")

	// ErrOutcomeUnknown marks a provider call that was sent but returned no
	// usable answer (a timeout or a lost response): it may have been processed
	// and billed. It is wrapped together with ErrProviderTimeout or
	// ErrProviderUnavailable.
	ErrOutcomeUnknown = errors.New("the request was sent, but no usable answer arrived")

	ErrPlaylistTimeout     = errors.New("playlist source timed out")
	ErrPlaylistUnavailable = errors.New("playlist source unavailable")
	ErrPlaylistRefused     = errors.New("playlist source refused the request")
	ErrPlaylistInvalid     = errors.New("playlist source returned an invalid response")

	ErrNotificationNotSent    = errors.New("notification was not sent")
	ErrNotificationRefused    = errors.New("notification service refused the message")
	ErrNotificationNoResponse = errors.New("notification was sent, but no usable answer arrived")
)

// PlaylistFailureCode maps a playlist source error to its stored code.
func PlaylistFailureCode(err error) string {
	switch {
	case errors.Is(err, ErrPlaylistTimeout):
		return ListeningSourceTimeout
	case errors.Is(err, ErrPlaylistRefused):
		return ListeningSourceRefused
	case errors.Is(err, ErrPlaylistInvalid):
		return ListeningSourceInvalidResponse
	default:
		return ListeningSourceUnavailable
	}
}

// NotificationResult maps a notifier error to its stored outcome and code.
// A nil error is "sent". Anything not proven undelivered is unknown.
func NotificationResult(err error) (outcome, code string) {
	switch {
	case err == nil:
		return ListeningOutcomeSent, ""
	case errors.Is(err, ErrNotificationNotSent):
		return ListeningOutcomeFailed, NotificationNotSent
	case errors.Is(err, ErrNotificationRefused):
		return ListeningOutcomeFailed, NotificationRefused
	default:
		return ListeningOutcomeUnknown, NotificationNoResponse
	}
}

// PreparationOutcome maps a generation error to the attempt outcome: a timeout
// or a lost response is unknown (the provider may have finished and billed);
// any answer that arrived and was unusable is failed.
func PreparationOutcome(err error) string {
	switch {
	case err == nil:
		return ListeningOutcomeCompleted
	case errors.Is(err, ErrProviderTimeout), errors.Is(err, ErrOutcomeUnknown):
		return ListeningOutcomeUnknown
	default:
		return ListeningOutcomeFailed
	}
}

// PlaylistItem is one video from the playlist's official metadata.
type PlaylistItem struct {
	VideoID     string
	Title       string
	PublishedAt *time.Time
	Position    int
}

// PlaylistListing is one bounded read of the playlist. Skipped counts entries
// that cannot be used: private, deleted or malformed.
type PlaylistListing struct {
	PlaylistID string
	Items      []PlaylistItem
	Skipped    int
}

// ListeningPlaylistSource reads a playlist's official metadata. Errors wrap
// ErrPlaylistTimeout, ErrPlaylistUnavailable, ErrPlaylistRefused or
// ErrPlaylistInvalid and never carry the API key or a response body.
type ListeningPlaylistSource interface {
	Name() string
	List(ctx context.Context) (PlaylistListing, error)
}

// LessonReadyNotice is everything a notification may say: the title. It never
// carries transcript text, answers, links to the workbench or credentials.
type LessonReadyNotice struct {
	Title string
}

// Text is the message sent to the learner.
func (n LessonReadyNotice) Text() string {
	return "French Learning Hub: a listening lesson is ready.\n听力练习已准备好。\n\n«" + n.Title + "»\n\nOpen Listening in your workbench."
}

// ListeningNotifier sends a lesson-ready notice. Errors wrap
// ErrNotificationNotSent, ErrNotificationRefused or ErrNotificationNoResponse
// and never carry the token, the chat or the response body.
type ListeningNotifier interface {
	Channel() string
	NotifyLessonReady(ctx context.Context, notice LessonReadyNotice) error
}

// ListeningPullRun is one pull. Step fields are set when it finished.
type ListeningPullRun struct {
	ID               int64
	OperationID      string
	Trigger          string
	Status           string
	StartedAt        time.Time
	LeaseExpiresAt   time.Time
	FinishedAt       *time.Time
	SourceOutcome    string
	SourceFailure    string
	ItemsSeen        int
	MaterialsCreated int
	ItemsKnown       int
	ItemsSkipped     int
	PrepareOutcome   string
	NotifyOutcome    string
	Preparation      *ListeningPreparation  // the run's preparation attempt, if any
	Notification     *ListeningNotification // the run's notification attempt, if any
}

// EffectiveStatus reports a running run whose lease has expired as interrupted.
func (r ListeningPullRun) EffectiveStatus(now time.Time) string {
	if r.Status == ListeningPullRunning && !now.Before(r.LeaseExpiresAt) {
		return ListeningPullInterrupted
	}
	return r.Status
}

// ListeningPullReport is what a pull records when it finishes.
type ListeningPullReport struct {
	SourceOutcome    string
	SourceFailure    string
	ItemsSeen        int
	MaterialsCreated int
	ItemsKnown       int
	ItemsSkipped     int
	PrepareOutcome   string
	NotifyOutcome    string
}

// ListeningPreparation is one preparation attempt.
type ListeningPreparation struct {
	ID           int64
	OperationID  string
	MaterialID   int64
	TranscriptID int64
	Trigger      string
	PullRunID    *int64
	PullDay      string
	AfterUnknown bool
	StartedAt    time.Time
	DeadlineAt   time.Time
	FinishedAt   *time.Time
	Outcome      string // empty while unfinished
	ExerciseID   *int64
}

// State is the stored outcome, or in_progress / unknown while unfinished.
func (p ListeningPreparation) State(now time.Time) string {
	return attemptState(p.Outcome, p.DeadlineAt, now)
}

// ListeningNotification is one notification send attempt.
type ListeningNotification struct {
	ID           int64
	OperationID  string
	ExerciseID   int64
	Channel      string
	Trigger      string
	PullRunID    *int64
	AfterUnknown bool
	StartedAt    time.Time
	DeadlineAt   time.Time
	FinishedAt   *time.Time
	Outcome      string
	FailureCode  string
}

// State is the stored outcome, or in_progress / unknown while unfinished.
func (n ListeningNotification) State(now time.Time) string {
	return attemptState(n.Outcome, n.DeadlineAt, now)
}

func attemptState(outcome string, deadline, now time.Time) string {
	if outcome != "" {
		return outcome
	}
	if now.Before(deadline) {
		return ListeningStateInProgress
	}
	return ListeningOutcomeUnknown
}

// NewListeningPreparation asks the repository to record an attempt before the
// provider is called. The repository applies the rules atomically.
type NewListeningPreparation struct {
	OperationID string
	MaterialID  int64
	Trigger     string
	PullRunID   *int64
	PullDay     string
	// ConfirmUnknownRetry is the learner's acknowledgement that the previous
	// attempt's outcome is unknown and a new, possibly billed call is wanted.
	ConfirmUnknownRetry bool
	Now                 time.Time
	Deadline            time.Time
}

// NewListeningNotification asks the repository to record a send attempt.
type NewListeningNotification struct {
	OperationID         string
	ExerciseID          int64
	Channel             string
	Trigger             string
	PullRunID           *int64
	ConfirmUnknownRetry bool
	Now                 time.Time
	Deadline            time.Time
}

// PlaylistRecord is the outcome of recording one playlist item.
type PlaylistRecord struct {
	MaterialID int64
	Created    bool // a new material was created; false: the video ID was known
}

// ListeningMaterialStatus is derived per material for list and lesson views.
type ListeningMaterialStatus struct {
	State         string
	InPlaylist    bool
	Preparations  []ListeningPreparation  // newest first
	Notifications []ListeningNotification // newest first
}

// ListeningDailyRepository stores daily listening receipts. Rules that decide
// whether an attempt may start are applied inside one write transaction, so a
// button, the operator command and a timer can never start overlapping calls.
type ListeningDailyRepository interface {
	// StartPullRun inserts a running run. The same operation ID returns the
	// stored run (replay). While another run holds an unexpired lease it returns
	// that run with ErrListeningPullBusy; an expired one is marked interrupted.
	StartPullRun(ctx context.Context, operationID, trigger string, now, leaseExpires time.Time) (ListeningPullRun, bool, error)
	FinishPullRun(ctx context.Context, id int64, report ListeningPullReport, now time.Time) (ListeningPullRun, error)
	GetPullRunByOperation(ctx context.Context, operationID string) (ListeningPullRun, error)
	LatestPullRun(ctx context.Context) (*ListeningPullRun, error)

	// RecordPlaylistItem records a video ID once. A known ID (from an earlier
	// pull, or a material saved by hand) creates nothing.
	RecordPlaylistItem(ctx context.Context, runID int64, playlistID string, item PlaylistItem, now time.Time) (PlaylistRecord, error)

	// NextPullCandidate is the oldest playlist material whose latest transcript
	// has no exercise and no preparation attempt, and that has no unfinished
	// attempt. nil when there is none.
	NextPullCandidate(ctx context.Context) (*int64, error)
	PullPreparationsOnDay(ctx context.Context, day string) (int, error)

	// StartPreparation records an attempt before the provider call, or refuses
	// with ErrListeningNoTranscript, ErrListeningPreparationInProgress,
	// ErrListeningOutcomeUnknown, ErrListeningNotEligible,
	// ErrListeningDailyCapReached or ErrListeningOperationConflict. The same
	// operation ID returns the stored attempt (replay).
	StartPreparation(ctx context.Context, in NewListeningPreparation) (ListeningPreparation, *ListeningTranscript, bool, error)
	// FinishPreparation stores the exercise row and finishes the attempt in one
	// transaction.
	FinishPreparation(ctx context.Context, id int64, outcome string, exercise ListeningExercise, now time.Time) (ListeningPreparation, ListeningExercise, error)
	GetPreparationByOperation(ctx context.Context, operationID string) (ListeningPreparation, error)
	GetExercise(ctx context.Context, id int64) (ListeningExercise, error)

	StartNotification(ctx context.Context, in NewListeningNotification) (ListeningNotification, bool, error)
	FinishNotification(ctx context.Context, id int64, outcome, code string, now time.Time) (ListeningNotification, error)
	GetNotificationByOperation(ctx context.Context, operationID string) (ListeningNotification, error)

	MaterialStatus(ctx context.Context, materialID int64, now time.Time) (ListeningMaterialStatus, error)
}

var playlistIDPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{2,64}$`)

// ValidPlaylistID reports whether id looks like a YouTube playlist ID.
func ValidPlaylistID(id string) bool { return playlistIDPattern.MatchString(id) }

// ValidYouTubeVideoID reports whether id is an 11-character YouTube video ID.
func ValidYouTubeVideoID(id string) bool { return youTubeID.MatchString(id) }

// NormalizePlaylistTitle makes an official title fit the material title rules:
// control characters become spaces, runs of space collapse, and an over-long
// title is cut at a rune boundary with an ellipsis. Empty stays empty.
func NormalizePlaylistTitle(raw string) string {
	t := strings.Join(strings.FieldsFunc(raw, func(r rune) bool { return unicode.IsSpace(r) || unicode.IsControl(r) }), " ")
	if utf8.RuneCountInString(t) > MaxListeningTitleRunes {
		r := []rune(t)
		t = strings.TrimSpace(string(r[:MaxListeningTitleRunes-1])) + "…"
	}
	return t
}

// YouTubeWatchURL is the canonical link stored for a video ID.
func YouTubeWatchURL(videoID string) string { return "https://www.youtube.com/watch?v=" + videoID }

// ListeningDay is the local calendar day used for the daily cap.
func ListeningDay(now time.Time, loc *time.Location) string {
	return now.In(loc).Format("2006-01-02")
}

// PullOperationID is the stored key of the attempts a pull run makes.
func PullOperationID(kind string, runID int64) string {
	return fmt.Sprintf("pull-%s-%d", kind, runID)
}
