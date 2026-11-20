package application

import (
	"context"
	"errors"
	"fmt"

	"french-learning-app/internal/domain"
)

// Revision studio (private workbench): the revision history of an imported
// script, a block comparison of any two stored revisions, and a previewed
// restore. A restore never rewrites history: it appends the older revision's
// lines and authored exercise as the next revision through the same
// ReviseAuthoredScript path as a pack update, so a repeated or concurrent
// confirmation adds one revision at most, a confirmation made against an
// older current revision is refused as stale, and every Mistake Notebook
// record keeps the exercise (and wording) it was saved from.

// ListeningRevisionHistory is every stored revision of one imported script.
type ListeningRevisionHistory struct {
	MaterialID int64
	Title      string
	State      ListeningScriptState
	Revisions  []domain.ListeningScriptRevision // revision 1 first
}

// ListScriptRevisions reads every revision of an imported script. It reads
// only. ErrNotFound: unknown material; ErrListeningNotAuthoredScript: YouTube.
func (s *ListeningService) ListScriptRevisions(ctx context.Context, materialID int64) (*ListeningRevisionHistory, error) {
	m, err := s.repo.GetMaterial(ctx, materialID)
	if err != nil {
		return nil, err
	}
	if !m.IsAuthoredScript() {
		return nil, domain.ErrListeningNotAuthoredScript
	}
	current, err := s.repo.ScriptRevision(ctx, materialID, 0)
	if err != nil {
		return nil, err
	}
	state, err := s.scriptState(m, current)
	if err != nil {
		return nil, err
	}
	out := &ListeningRevisionHistory{MaterialID: m.ID, Title: m.Title, State: state}
	for n := 1; n <= current.Revision; n++ {
		rev, err := s.repo.ScriptRevision(ctx, materialID, n)
		if err != nil {
			return nil, fmt.Errorf("revision %d: %w", n, err)
		}
		out.Revisions = append(out.Revisions, rev)
	}
	return out, nil
}

// ListeningRevisionComparison is revision From against revision To.
type ListeningRevisionComparison struct {
	MaterialID int64
	Current    int
	From, To   domain.ListeningScriptRevision
	Blocks     []domain.ListeningLineBlock
	Changes    domain.ListeningScriptChanges
}

func (s *ListeningService) compare(materialID int64, current int, from, to domain.ListeningScriptRevision) *ListeningRevisionComparison {
	return &ListeningRevisionComparison{MaterialID: materialID, Current: current, From: from, To: to,
		Blocks:  domain.AlignListeningBlocks(from.Transcript.Segments, to.Transcript.Segments),
		Changes: domain.DiffListeningScript(from.Transcript.Segments, *from.Exercise.Content, to.Transcript.Segments, *to.Exercise.Content)}
}

// CompareScriptRevisions compares two stored revisions (either order). It
// reads only. ErrValidation: a revision below 1; ErrNotFound: unknown
// material or revision.
func (s *ListeningService) CompareScriptRevisions(ctx context.Context, materialID int64, from, to int) (*ListeningRevisionComparison, error) {
	if from < 1 || to < 1 {
		return nil, fmt.Errorf("%w: from and to must be revisions (1 or more)", domain.ErrValidation)
	}
	a, current, err := s.GetScriptRevision(ctx, materialID, from)
	if err != nil {
		return nil, err
	}
	b, _, err := s.GetScriptRevision(ctx, materialID, to)
	if err != nil {
		return nil, err
	}
	return s.compare(materialID, current, *a, *b), nil
}

// Why a restore preview offers no restore.
const (
	RestoreIsCurrent   = "is_current"   // the target is the current revision
	RestoreSameContent = "same_content" // the current revision already has the target's content
)

// ListeningRestorePreview is what restoring revision Target would change:
// the current revision against the target's content, and the revision the
// restore would append.
type ListeningRestorePreview struct {
	Comparison   *ListeningRevisionComparison // From = current, To = target
	NextRevision int                          // 0 when nothing would be written
	Blocked      string                       // "" when a restore is offered
}

// ScriptRestorePreview reads what a restore of revision target would change.
func (s *ListeningService) ScriptRestorePreview(ctx context.Context, materialID int64, target int) (*ListeningRestorePreview, error) {
	if target < 1 {
		return nil, fmt.Errorf("%w: revision must be at least 1", domain.ErrValidation)
	}
	t, current, err := s.GetScriptRevision(ctx, materialID, target)
	if err != nil {
		return nil, err
	}
	cur, _, err := s.GetScriptRevision(ctx, materialID, current)
	if err != nil {
		return nil, err
	}
	out := &ListeningRestorePreview{Comparison: s.compare(materialID, current, *cur, *t)}
	switch {
	case target == current:
		out.Blocked = RestoreIsCurrent
	case t.Fingerprint == cur.Fingerprint:
		out.Blocked = RestoreSameContent
	default:
		out.NextRevision = current + 1
	}
	return out, nil
}

// ListeningRestoreStaleError: the current revision changed since the
// preview; it carries a fresh preview of the same target.
type ListeningRestoreStaleError struct {
	Preview *ListeningRestorePreview
}

func (e *ListeningRestoreStaleError) Error() string {
	return domain.ErrListeningScriptRevisionStale.Error()
}
func (e *ListeningRestoreStaleError) Unwrap() error { return domain.ErrListeningScriptRevisionStale }

// ListeningRestoreResult is the lesson after a restore.
type ListeningRestoreResult struct {
	Revision     int // the revision now current
	RestoredFrom int
	Lesson       *ListeningLesson
}

// RestoreScript is the explicit, confirmed restore of revision target as the
// next revision. fromRevision and targetFingerprint are the preview the
// learner confirmed. The bool is true when nothing was written because the
// current revision already has the target's content (a repeated, concurrent or
// resent confirmation). Errors, all with nothing written: ErrValidation
// (malformed confirmation, or the target is the current revision),
// ErrNotFound, ErrListeningNotAuthoredScript, and *ListeningRestoreStaleError
// when the lesson changed since the preview or the fingerprint no longer names
// the target.
func (s *ListeningService) RestoreScript(ctx context.Context, materialID int64, fromRevision, target int, targetFingerprint string) (*ListeningRestoreResult, bool, error) {
	if fromRevision < 1 || target < 1 || !domain.ValidListeningScriptFingerprint(targetFingerprint) {
		return nil, false, fmt.Errorf("%w: from_revision and revision must be at least 1 and fingerprint a sha256: fingerprint from the preview", domain.ErrValidation)
	}
	t, current, err := s.GetScriptRevision(ctx, materialID, target)
	if err != nil {
		return nil, false, err
	}
	stale := func() error {
		p, err := s.ScriptRestorePreview(ctx, materialID, target)
		if err != nil {
			return err
		}
		return &ListeningRestoreStaleError{Preview: p}
	}
	if t.Fingerprint != targetFingerprint {
		return nil, false, stale()
	}
	if target == fromRevision && target == current {
		return nil, false, fmt.Errorf("%w: revision %d is already the current revision", domain.ErrValidation, target)
	}
	rev, replay, err := s.repo.ReviseAuthoredScript(ctx, materialID, fromRevision, t.Transcript.Segments, *t.Exercise.Content, s.now())
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
	return &ListeningRestoreResult{Revision: rev.Revision, RestoredFrom: target, Lesson: lesson}, replay, nil
}
