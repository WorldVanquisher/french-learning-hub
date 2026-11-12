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
	scripts   domain.ListeningScriptPack        // authored scripts offered for import (may be empty)
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

// WithListeningScripts offers a validated authored-script pack for import.
// Without it no script is listed and every import is ErrNotFound.
func WithListeningScripts(pack domain.ListeningScriptPack) ListeningOption {
	return func(s *ListeningService) { s.scripts = pack }
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
	// Current is the exercise the lesson shows (domain.CurrentListeningExercise):
	// for an authored script, the authored exercise of its current revision.
	Current *domain.ListeningExercise
	// Script is the authored script's revision compared with the server's
	// pack; nil for YouTube material.
	Script *ListeningScriptState
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
	m, _, err := s.repo.CreateMaterial(ctx, domain.ListeningMaterial{SourceKind: domain.ListeningSourceYouTube, VideoID: videoID, SourceURL: canonical, Title: t}, segments, timed)
	if err != nil {
		return nil, err
	}
	return s.GetLesson(ctx, m.ID)
}

// AddTranscript stores a new transcript version for existing material. An
// authored script is fixed text and takes none (ErrListeningScriptFixed).
func (s *ListeningService) AddTranscript(ctx context.Context, materialID int64, transcript string) (*ListeningLesson, error) {
	m, err := s.repo.GetMaterial(ctx, materialID)
	if err != nil {
		return nil, err
	}
	if m.IsAuthoredScript() {
		return nil, domain.ErrListeningScriptFixed
	}
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
	lesson := &ListeningLesson{Material: m, Transcript: tr, Exercises: ex, Current: domain.CurrentListeningExercise(m, tr, ex), Status: st, Now: now}
	if m.IsAuthoredScript() {
		rev, err := s.repo.ScriptRevision(ctx, m.ID, 0)
		if err != nil {
			return nil, err
		}
		state, err := s.scriptState(m, rev)
		if err != nil {
			return nil, err
		}
		lesson.Script = &state
	}
	return lesson, nil
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

// ListeningScriptSummary is one authored script offered for import: what it
// is and, once imported, the material that holds it. It carries no line or key.
type ListeningScriptSummary struct {
	ID                 string
	Title              string
	Genre              string
	StyleLevel         string
	SourcePack         string
	Notice             string
	Lines              int
	Questions          int
	ImportedMaterialID *int64
	// ImportedRevision and PackStatus describe an imported script's current
	// revision against this pack (zero and "" when not imported).
	ImportedRevision int
	PackStatus       string
}

// ListScripts lists the authored scripts and whether each is imported. It
// never calls a provider.
func (s *ListeningService) ListScripts(ctx context.Context) ([]ListeningScriptSummary, error) {
	ms, err := s.repo.ListMaterials(ctx)
	if err != nil {
		return nil, err
	}
	imported := map[string]int64{}
	for _, m := range ms {
		if m.PackScriptID != "" {
			imported[m.PackScriptID] = m.ID
		}
	}
	out := make([]ListeningScriptSummary, 0, len(s.scripts.Scripts))
	for _, sc := range s.scripts.Scripts {
		row := ListeningScriptSummary{ID: sc.ID, Title: sc.Title, Genre: sc.Genre, StyleLevel: sc.StyleLevel,
			SourcePack: sc.Source.Pack, Notice: sc.Source.Notice, Lines: len(sc.Lines), Questions: len(sc.Questions)}
		if id, ok := imported[sc.PackScriptID()]; ok {
			row.ImportedMaterialID = &id
			rev, err := s.repo.ScriptRevision(ctx, id, 0)
			if err != nil {
				return nil, err
			}
			state, err := s.scriptStateFor(sc, rev)
			if err != nil {
				return nil, err
			}
			row.ImportedRevision, row.PackStatus = rev.Revision, state.PackStatus
		}
		out = append(out, row)
	}
	return out, nil
}

// ListeningScriptConflictError is ErrListeningScriptConflict with the lesson
// that holds the script: its current revision differs from the pack.
type ListeningScriptConflictError struct {
	MaterialID int64
	Revision   int
	PackStatus string
}

func (e *ListeningScriptConflictError) Error() string {
	return domain.ErrListeningScriptConflict.Error()
}
func (e *ListeningScriptConflictError) Unwrap() error { return domain.ErrListeningScriptConflict }

// ImportScript imports one authored script with its authored exercise, in one
// transaction and without a model call. Importing it again returns the same
// lesson (true) when its current revision has the pack's content.
// ErrNotFound: no such script; *ListeningScriptConflictError: the lesson's
// current revision differs from the pack (nothing is changed; an explicit
// update is UpdateScript).
func (s *ListeningService) ImportScript(ctx context.Context, scriptID string) (*ListeningLesson, bool, error) {
	for _, sc := range s.scripts.Scripts {
		if sc.ID != scriptID {
			continue
		}
		m := domain.ListeningMaterial{SourceKind: domain.ListeningSourceAuthoredScript, PackScriptID: sc.PackScriptID(), Title: sc.Title}
		saved, replay, err := s.repo.ImportAuthoredScript(ctx, m, sc.Segments(), sc.Content(), s.now())
		if errors.Is(err, domain.ErrListeningScriptConflict) && saved.ID != 0 {
			rev, revErr := s.repo.ScriptRevision(ctx, saved.ID, 0)
			if revErr != nil {
				return nil, false, revErr
			}
			state, stateErr := s.scriptStateFor(sc, rev)
			if stateErr != nil {
				return nil, false, stateErr
			}
			return nil, false, &ListeningScriptConflictError{MaterialID: saved.ID, Revision: rev.Revision, PackStatus: state.PackStatus}
		}
		if err != nil {
			return nil, false, err
		}
		lesson, err := s.GetLesson(ctx, saved.ID)
		return lesson, replay, err
	}
	return nil, false, fmt.Errorf("%w: listening script %q", domain.ErrNotFound, scriptID)
}

// ListeningScriptState is an imported script's current revision compared with
// the server's pack.
type ListeningScriptState struct {
	ScriptID        string // the pack's script id, e.g. ls-wb1-u05
	Revision        int
	Fingerprint     string
	PackStatus      string // domain.ListeningScriptUpToDate, …UpdateAvailable, …TitleChanged, …NotInPack
	PackFingerprint string // "" when the pack has no such script
}

func (s *ListeningService) packScript(m domain.ListeningMaterial) (domain.ListeningScript, bool) {
	for _, sc := range s.scripts.Scripts {
		if sc.PackScriptID() == m.PackScriptID {
			return sc, true
		}
	}
	return domain.ListeningScript{}, false
}

func (s *ListeningService) scriptState(m domain.ListeningMaterial, rev domain.ListeningScriptRevision) (ListeningScriptState, error) {
	sc, ok := s.packScript(m)
	if !ok {
		return ListeningScriptState{ScriptID: strings.TrimPrefix(m.PackScriptID, domain.ListeningScriptPackID+"/"), Revision: rev.Revision,
			Fingerprint: rev.Fingerprint, PackStatus: domain.ListeningScriptNotInPack}, nil
	}
	state, err := s.scriptStateFor(sc, rev)
	if err == nil && sc.Title != m.Title {
		state.PackStatus = domain.ListeningScriptTitleChanged
	}
	return state, err
}

func (s *ListeningService) scriptStateFor(sc domain.ListeningScript, rev domain.ListeningScriptRevision) (ListeningScriptState, error) {
	fp, err := sc.Fingerprint()
	if err != nil {
		return ListeningScriptState{}, err
	}
	state := ListeningScriptState{ScriptID: sc.ID, Revision: rev.Revision, Fingerprint: rev.Fingerprint, PackStatus: domain.ListeningScriptUpToDate, PackFingerprint: fp}
	if fp != rev.Fingerprint {
		state.PackStatus = domain.ListeningScriptUpdateAvailable
	}
	return state, nil
}

// ListeningScriptUpdatePreview is what an explicit update of an imported
// script would change: the current revision against the server's pack.
type ListeningScriptUpdatePreview struct {
	MaterialID int64
	State      ListeningScriptState
	Changes    domain.ListeningScriptChanges
}

// ListeningScriptStaleError is ErrListeningScriptRevisionStale with a fresh
// preview of the lesson as it is now.
type ListeningScriptStaleError struct {
	Preview *ListeningScriptUpdatePreview
}

func (e *ListeningScriptStaleError) Error() string {
	return domain.ErrListeningScriptRevisionStale.Error()
}
func (e *ListeningScriptStaleError) Unwrap() error { return domain.ErrListeningScriptRevisionStale }

// ScriptUpdatePreview compares an imported script's current revision with
// the server's pack. It reads only. ErrNotFound: unknown material;
// ErrListeningNotAuthoredScript: YouTube material; ErrListeningScriptNotInPack:
// the pack has no such script.
func (s *ListeningService) ScriptUpdatePreview(ctx context.Context, materialID int64) (*ListeningScriptUpdatePreview, error) {
	m, err := s.repo.GetMaterial(ctx, materialID)
	if err != nil {
		return nil, err
	}
	if !m.IsAuthoredScript() {
		return nil, domain.ErrListeningNotAuthoredScript
	}
	sc, ok := s.packScript(m)
	if !ok {
		return nil, domain.ErrListeningScriptNotInPack
	}
	rev, err := s.repo.ScriptRevision(ctx, materialID, 0)
	if err != nil {
		return nil, err
	}
	state, err := s.scriptState(m, rev)
	if err != nil {
		return nil, err
	}
	changes := domain.DiffListeningScript(rev.Transcript.Segments, *rev.Exercise.Content, sc.Segments(), sc.Content())
	return &ListeningScriptUpdatePreview{MaterialID: m.ID, State: state, Changes: changes}, nil
}

// ListeningScriptUpdateResult is the lesson after an update and its revision.
type ListeningScriptUpdateResult struct {
	Revision int
	Lesson   *ListeningLesson
}

// UpdateScript is the explicit, confirmed update of an imported script to the
// server's pack. fromRevision and packFingerprint are the preview the learner
// confirmed. It appends the next revision (never changing an earlier one) in
// one transaction and makes no provider call. The returned bool is true when
// nothing was written because the lesson already has the pack's content
// (a repeated or concurrent confirmation, or a resend after a lost response).
// Errors, all with nothing written: ErrValidation (malformed confirmation),
// ErrNotFound, ErrListeningNotAuthoredScript, ErrListeningScriptNotInPack,
// ErrListeningScriptTitleChanged, and *ListeningScriptStaleError when the pack
// or the lesson changed since the preview.
func (s *ListeningService) UpdateScript(ctx context.Context, materialID int64, fromRevision int, packFingerprint string) (*ListeningScriptUpdateResult, bool, error) {
	if fromRevision < 1 || !domain.ValidListeningScriptFingerprint(packFingerprint) {
		return nil, false, fmt.Errorf("%w: from_revision must be at least 1 and pack_fingerprint a sha256: fingerprint from the preview", domain.ErrValidation)
	}
	m, err := s.repo.GetMaterial(ctx, materialID)
	if err != nil {
		return nil, false, err
	}
	if !m.IsAuthoredScript() {
		return nil, false, domain.ErrListeningNotAuthoredScript
	}
	sc, ok := s.packScript(m)
	if !ok {
		return nil, false, domain.ErrListeningScriptNotInPack
	}
	if sc.Title != m.Title {
		return nil, false, domain.ErrListeningScriptTitleChanged
	}
	stale := func() error {
		preview, err := s.ScriptUpdatePreview(ctx, materialID)
		if err != nil {
			return err
		}
		return &ListeningScriptStaleError{Preview: preview}
	}
	fp, err := sc.Fingerprint()
	if err != nil {
		return nil, false, err
	}
	if fp != packFingerprint {
		return nil, false, stale()
	}
	rev, replay, err := s.repo.ReviseAuthoredScript(ctx, materialID, fromRevision, sc.Segments(), sc.Content(), s.now())
	if errors.Is(err, domain.ErrListeningScriptRevisionStale) {
		return nil, false, stale()
	}
	if err != nil {
		return nil, false, err
	}
	lesson, err := s.GetLesson(ctx, materialID)
	if err != nil {
		return nil, false, err
	}
	return &ListeningScriptUpdateResult{Revision: rev.Revision, Lesson: lesson}, replay, nil
}

// GetScriptRevision reads one revision of an imported script (its lines and
// authored exercise), e.g. the one a Mistake Notebook record was saved from.
// It reads only. ErrValidation: revision < 1; ErrNotFound: unknown material
// or revision; ErrListeningNotAuthoredScript: YouTube material.
func (s *ListeningService) GetScriptRevision(ctx context.Context, materialID int64, revision int) (*domain.ListeningScriptRevision, int, error) {
	if revision < 1 {
		return nil, 0, fmt.Errorf("%w: revision must be at least 1", domain.ErrValidation)
	}
	rev, err := s.repo.ScriptRevision(ctx, materialID, revision)
	if err != nil {
		return nil, 0, err
	}
	current, err := s.repo.ScriptRevision(ctx, materialID, 0)
	if err != nil {
		return nil, 0, err
	}
	return &rev, current.Revision, nil
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
//   - domain.ErrListeningScriptExerciseFixed: an authored script keeps its
//     authored exercise; refused before any attempt, no call, nothing stored
//     (whether or not a generator is configured);
//   - domain.ErrListeningDisabled: no generator, nothing stored;
//   - domain.ErrNotFound: unknown material;
//   - domain.ErrListeningNoTranscript: no call, nothing stored;
//   - domain.ErrListeningPreparationInProgress / ErrListeningOutcomeUnknown: no
//     call; the blocking attempt is returned in the result;
//   - *ListeningGenerationError: the call failed or its outcome is unknown; the
//     attempt and the failed exercise are stored and returned.
func (s *ListeningService) PrepareExercise(ctx context.Context, req ListeningPrepareRequest) (*ListeningPreparationResult, bool, error) {
	// An authored script's exercise is fixed content. A script never enters a
	// playlist, so pulls never reach it; the explicit route is the only way in.
	switch m, err := s.repo.GetMaterial(ctx, req.MaterialID); {
	case err == nil && m.IsAuthoredScript():
		return nil, false, domain.ErrListeningScriptExerciseFixed
	case err != nil && !errors.Is(err, domain.ErrNotFound):
		return nil, false, err
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
