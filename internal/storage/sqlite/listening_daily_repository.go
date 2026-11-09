package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// Daily Listening receipts (migration 015). They are methods of the same
// ListeningRepository so the explicit Prepare button and a pull share one
// preparation path. Attempt rows are inserted before the outside call and
// finished once by an UPDATE guarded by "finished_at IS NULL". The rules that
// decide whether an attempt may start run inside one write transaction (taken
// first with a no-op UPDATE), so two processes on the same database file — the
// server and the operator command — cannot both start one.

var _ domain.ListeningDailyRepository = (*ListeningRepository)(nil)

type execer interface {
	ExecContext(ctx context.Context, query string, args ...any) (sql.Result, error)
}

func fmtTime(t time.Time) string { return t.UTC().Format(rfc3339) }

func parseTime(s string) time.Time {
	t, _ := time.Parse(rfc3339, s)
	return t
}

func parseNullTime(s sql.NullString) *time.Time {
	if !s.Valid {
		return nil
	}
	t := parseTime(s.String)
	return &t
}

func nullInt(n sql.NullInt64) *int64 {
	if !n.Valid {
		return nil
	}
	v := n.Int64
	return &v
}

func boolInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

// begin opens a transaction and takes SQLite's write lock at once.
func (r *ListeningRepository) begin(ctx context.Context, lockTable string) (*sql.Tx, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `UPDATE `+lockTable+` SET rowid = rowid WHERE 0`); err != nil {
		_ = tx.Rollback()
		return nil, fmt.Errorf("take write lock: %w", err)
	}
	return tx, nil
}

// ---- pull runs ----

const pullRunColumns = `id, operation_id, trigger, status, started_at, lease_expires_at, finished_at,
	source_outcome, source_failure, items_seen, materials_created, items_known, items_skipped,
	prepare_outcome, notify_outcome`

func readPullRun(ctx context.Context, q queryer, where string, args ...any) (domain.ListeningPullRun, error) {
	var run domain.ListeningPullRun
	var started, lease string
	var finished, srcOut, srcFail, prepOut, notifyOut sql.NullString
	err := q.QueryRowContext(ctx, `SELECT `+pullRunColumns+` FROM listening_pull_runs WHERE `+where, args...).Scan(
		&run.ID, &run.OperationID, &run.Trigger, &run.Status, &started, &lease, &finished,
		&srcOut, &srcFail, &run.ItemsSeen, &run.MaterialsCreated, &run.ItemsKnown, &run.ItemsSkipped, &prepOut, &notifyOut)
	if errors.Is(err, sql.ErrNoRows) {
		return run, fmt.Errorf("%w: listening pull run", domain.ErrNotFound)
	}
	if err != nil {
		return run, err
	}
	run.StartedAt, run.LeaseExpiresAt, run.FinishedAt = parseTime(started), parseTime(lease), parseNullTime(finished)
	run.SourceOutcome, run.SourceFailure, run.PrepareOutcome, run.NotifyOutcome = srcOut.String, srcFail.String, prepOut.String, notifyOut.String
	return run, nil
}

// attachRunAttempts loads the preparation and notification a run made.
func attachRunAttempts(ctx context.Context, q queryer, run *domain.ListeningPullRun) error {
	if p, err := readPreparation(ctx, q, `pull_run_id = ?`, run.ID); err == nil {
		run.Preparation = &p
	} else if !errors.Is(err, domain.ErrNotFound) {
		return err
	}
	if n, err := readNotification(ctx, q, `pull_run_id = ?`, run.ID); err == nil {
		run.Notification = &n
	} else if !errors.Is(err, domain.ErrNotFound) {
		return err
	}
	return nil
}

func (r *ListeningRepository) StartPullRun(ctx context.Context, operationID, trigger string, now, leaseExpires time.Time) (domain.ListeningPullRun, bool, error) {
	tx, err := r.begin(ctx, "listening_pull_runs")
	if err != nil {
		return domain.ListeningPullRun{}, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if run, err := readPullRun(ctx, tx, `operation_id = ?`, operationID); err == nil {
		if err := attachRunAttempts(ctx, tx, &run); err != nil {
			return run, false, err
		}
		return run, true, tx.Commit()
	} else if !errors.Is(err, domain.ErrNotFound) {
		return domain.ListeningPullRun{}, false, err
	}
	if running, err := readPullRun(ctx, tx, `status = 'running'`); err == nil {
		if now.Before(running.LeaseExpiresAt) {
			return running, false, domain.ErrListeningPullBusy
		}
		// Its process is gone or overran its lease: record that, and nothing else.
		if _, err := tx.ExecContext(ctx, `UPDATE listening_pull_runs SET status = 'interrupted', finished_at = ? WHERE id = ? AND status = 'running'`,
			fmtTime(now), running.ID); err != nil {
			return domain.ListeningPullRun{}, false, fmt.Errorf("mark pull run interrupted: %w", err)
		}
	} else if !errors.Is(err, domain.ErrNotFound) {
		return domain.ListeningPullRun{}, false, err
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO listening_pull_runs (operation_id, trigger, status, started_at, lease_expires_at) VALUES (?, ?, 'running', ?, ?)`,
		operationID, trigger, fmtTime(now), fmtTime(leaseExpires))
	if err != nil {
		return domain.ListeningPullRun{}, false, fmt.Errorf("insert pull run: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return domain.ListeningPullRun{}, false, err
	}
	run, err := readPullRun(ctx, tx, `id = ?`, id)
	if err != nil {
		return run, false, err
	}
	return run, false, tx.Commit()
}

func (r *ListeningRepository) FinishPullRun(ctx context.Context, id int64, rep domain.ListeningPullReport, now time.Time) (domain.ListeningPullRun, error) {
	var failure any
	if rep.SourceFailure != "" {
		failure = rep.SourceFailure
	}
	res, err := r.db.ExecContext(ctx, `UPDATE listening_pull_runs SET status = 'finished', finished_at = ?,
		source_outcome = ?, source_failure = ?, items_seen = ?, materials_created = ?, items_known = ?, items_skipped = ?,
		prepare_outcome = ?, notify_outcome = ? WHERE id = ? AND status = 'running'`,
		fmtTime(now), rep.SourceOutcome, failure, rep.ItemsSeen, rep.MaterialsCreated, rep.ItemsKnown, rep.ItemsSkipped,
		rep.PrepareOutcome, rep.NotifyOutcome, id)
	if err != nil {
		return domain.ListeningPullRun{}, fmt.Errorf("finish pull run: %w", err)
	}
	if n, _ := res.RowsAffected(); n != 1 {
		return domain.ListeningPullRun{}, domain.ErrListeningPullLeaseLost
	}
	return r.pullRun(ctx, `id = ?`, id)
}

func (r *ListeningRepository) pullRun(ctx context.Context, where string, args ...any) (domain.ListeningPullRun, error) {
	run, err := readPullRun(ctx, r.db, where, args...)
	if err != nil {
		return run, err
	}
	return run, attachRunAttempts(ctx, r.db, &run)
}

func (r *ListeningRepository) GetPullRunByOperation(ctx context.Context, operationID string) (domain.ListeningPullRun, error) {
	return r.pullRun(ctx, `operation_id = ?`, operationID)
}

func (r *ListeningRepository) LatestPullRun(ctx context.Context) (*domain.ListeningPullRun, error) {
	run, err := r.pullRun(ctx, `1 ORDER BY id DESC LIMIT 1`)
	if errors.Is(err, domain.ErrNotFound) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &run, nil
}

// ---- playlist items ----

func (r *ListeningRepository) RecordPlaylistItem(ctx context.Context, runID int64, playlistID string, item domain.PlaylistItem, now time.Time) (domain.PlaylistRecord, error) {
	if !domain.ValidYouTubeVideoID(item.VideoID) {
		return domain.PlaylistRecord{}, fmt.Errorf("%w: invalid video ID", domain.ErrValidation)
	}
	title, err := domain.NormalizeListeningTitle(item.Title)
	if err != nil {
		return domain.PlaylistRecord{}, err
	}
	tx, err := r.begin(ctx, "listening_playlist_items")
	if err != nil {
		return domain.PlaylistRecord{}, err
	}
	defer func() { _ = tx.Rollback() }()
	var known int64
	err = tx.QueryRowContext(ctx, `SELECT material_id FROM listening_playlist_items WHERE video_id = ?`, item.VideoID).Scan(&known)
	if err == nil {
		return domain.PlaylistRecord{MaterialID: known}, tx.Commit()
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return domain.PlaylistRecord{}, err
	}
	ts := fmtTime(now)
	created := false
	// A material saved by hand for the same video is matched, never duplicated.
	err = tx.QueryRowContext(ctx, `SELECT id FROM listening_materials WHERE video_id = ? ORDER BY id LIMIT 1`, item.VideoID).Scan(&known)
	if errors.Is(err, sql.ErrNoRows) {
		res, err := tx.ExecContext(ctx, `INSERT INTO listening_materials (video_id, source_url, title, created_at) VALUES (?, ?, ?, ?)`,
			item.VideoID, domain.YouTubeWatchURL(item.VideoID), title, ts)
		if err != nil {
			return domain.PlaylistRecord{}, fmt.Errorf("insert listening material: %w", err)
		}
		if known, err = res.LastInsertId(); err != nil {
			return domain.PlaylistRecord{}, err
		}
		created = true
	} else if err != nil {
		return domain.PlaylistRecord{}, err
	}
	var published any
	if item.PublishedAt != nil {
		published = fmtTime(*item.PublishedAt)
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO listening_playlist_items
		(video_id, material_id, playlist_id, material_created, source_title, published_at, pull_run_id, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)`, item.VideoID, known, playlistID, boolInt(created), title, published, runID, ts); err != nil {
		return domain.PlaylistRecord{}, fmt.Errorf("insert playlist item: %w", err)
	}
	return domain.PlaylistRecord{MaterialID: known, Created: created}, tx.Commit()
}

// ---- preparations ----

const latestTranscriptID = `(SELECT id FROM listening_transcripts WHERE material_id = m.id ORDER BY version DESC LIMIT 1)`

func (r *ListeningRepository) NextPullCandidate(ctx context.Context) (*int64, error) {
	var id int64
	err := r.db.QueryRowContext(ctx, `SELECT m.id FROM listening_materials m
		WHERE EXISTS (SELECT 1 FROM listening_playlist_items pi WHERE pi.material_id = m.id)
		  AND `+latestTranscriptID+` IS NOT NULL
		  AND NOT EXISTS (SELECT 1 FROM listening_exercises e WHERE e.transcript_id = `+latestTranscriptID+`)
		  AND NOT EXISTS (SELECT 1 FROM listening_preparations p WHERE p.transcript_id = `+latestTranscriptID+`)
		  AND NOT EXISTS (SELECT 1 FROM listening_preparations p
		                  WHERE p.id = (SELECT MAX(id) FROM listening_preparations WHERE material_id = m.id)
		                    AND (p.finished_at IS NULL OR p.outcome = 'unknown'))
		ORDER BY m.id LIMIT 1`).Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("select pull candidate: %w", err)
	}
	return &id, nil
}

func (r *ListeningRepository) PullPreparationsOnDay(ctx context.Context, day string) (int, error) {
	var n int
	err := r.db.QueryRowContext(ctx, `SELECT COUNT(*) FROM listening_preparations WHERE trigger = 'pull' AND pull_day = ?`, day).Scan(&n)
	return n, err
}

const preparationColumns = `id, operation_id, material_id, transcript_id, trigger, pull_run_id, pull_day, after_unknown,
	started_at, deadline_at, finished_at, outcome, exercise_id`

func readPreparation(ctx context.Context, q queryer, where string, args ...any) (domain.ListeningPreparation, error) {
	var p domain.ListeningPreparation
	var runID, exerciseID sql.NullInt64
	var day, finished, outcome sql.NullString
	var started, deadline string
	var after int
	err := q.QueryRowContext(ctx, `SELECT `+preparationColumns+` FROM listening_preparations WHERE `+where, args...).Scan(
		&p.ID, &p.OperationID, &p.MaterialID, &p.TranscriptID, &p.Trigger, &runID, &day, &after,
		&started, &deadline, &finished, &outcome, &exerciseID)
	if errors.Is(err, sql.ErrNoRows) {
		return p, fmt.Errorf("%w: listening preparation", domain.ErrNotFound)
	}
	if err != nil {
		return p, err
	}
	p.PullRunID, p.PullDay, p.AfterUnknown = nullInt(runID), day.String, after == 1
	p.StartedAt, p.DeadlineAt, p.FinishedAt = parseTime(started), parseTime(deadline), parseNullTime(finished)
	p.Outcome, p.ExerciseID = outcome.String, nullInt(exerciseID)
	return p, nil
}

func exists(ctx context.Context, q queryer, query string, args ...any) (bool, error) {
	var one int
	err := q.QueryRowContext(ctx, `SELECT 1 WHERE EXISTS (`+query+`)`, args...).Scan(&one)
	if errors.Is(err, sql.ErrNoRows) {
		return false, nil
	}
	return err == nil, err
}

func (r *ListeningRepository) StartPreparation(ctx context.Context, in domain.NewListeningPreparation) (domain.ListeningPreparation, *domain.ListeningTranscript, bool, error) {
	var none domain.ListeningPreparation
	tx, err := r.begin(ctx, "listening_preparations")
	if err != nil {
		return none, nil, false, err
	}
	defer func() { _ = tx.Rollback() }()

	if p, err := readPreparation(ctx, tx, `operation_id = ?`, in.OperationID); err == nil {
		if p.MaterialID != in.MaterialID || p.Trigger != in.Trigger {
			return none, nil, false, domain.ErrListeningOperationConflict
		}
		tr, err := readTranscript(ctx, tx, `id = ?`, p.TranscriptID)
		if err != nil {
			return none, nil, false, err
		}
		return p, &tr, true, tx.Commit()
	} else if !errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, err
	}
	if _, err := readMaterial(ctx, tx, in.MaterialID); err != nil {
		return none, nil, false, err
	}
	tr, err := readTranscript(ctx, tx, `material_id = ? ORDER BY version DESC LIMIT 1`, in.MaterialID)
	if errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, domain.ErrListeningNoTranscript
	}
	if err != nil {
		return none, nil, false, err
	}

	// The latest attempt decides: one still in progress blocks everyone; one whose
	// outcome is unknown blocks pulls and needs the learner's acknowledgement.
	afterUnknown := false
	if latest, err := readPreparation(ctx, tx, `material_id = ? ORDER BY id DESC LIMIT 1`, in.MaterialID); err == nil {
		switch latest.State(in.Now) {
		case domain.ListeningStateInProgress:
			return latest, nil, false, domain.ErrListeningPreparationInProgress
		case domain.ListeningOutcomeUnknown:
			if in.Trigger == domain.ListeningTriggerPull || !in.ConfirmUnknownRetry {
				return latest, nil, false, domain.ErrListeningOutcomeUnknown
			}
			afterUnknown = true
		}
	} else if !errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, err
	}

	var runID, day any
	if in.Trigger == domain.ListeningTriggerPull {
		// A pull only prepares playlist material, once per transcript version,
		// never after an earlier attempt for it, and within the daily cap.
		inPlaylist, err := exists(ctx, tx, `SELECT 1 FROM listening_playlist_items WHERE material_id = ?`, in.MaterialID)
		if err != nil {
			return none, nil, false, err
		}
		attempted, err := exists(ctx, tx, `SELECT 1 FROM listening_preparations WHERE transcript_id = ?`, tr.ID)
		if err != nil {
			return none, nil, false, err
		}
		prepared, err := exists(ctx, tx, `SELECT 1 FROM listening_exercises WHERE transcript_id = ?`, tr.ID)
		if err != nil {
			return none, nil, false, err
		}
		if !inPlaylist || attempted || prepared || in.PullRunID == nil || in.PullDay == "" {
			return none, nil, false, domain.ErrListeningNotEligible
		}
		var used int
		if err := tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM listening_preparations WHERE trigger = 'pull' AND pull_day = ?`, in.PullDay).Scan(&used); err != nil {
			return none, nil, false, err
		}
		if used >= domain.ListeningDailyPreparationCap {
			return none, nil, false, domain.ErrListeningDailyCapReached
		}
		runID, day = *in.PullRunID, in.PullDay
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO listening_preparations
		(operation_id, material_id, transcript_id, trigger, pull_run_id, pull_day, after_unknown, started_at, deadline_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		in.OperationID, in.MaterialID, tr.ID, in.Trigger, runID, day, boolInt(afterUnknown), fmtTime(in.Now), fmtTime(in.Deadline))
	if err != nil {
		return none, nil, false, fmt.Errorf("insert listening preparation: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return none, nil, false, err
	}
	p, err := readPreparation(ctx, tx, `id = ?`, id)
	if err != nil {
		return none, nil, false, err
	}
	return p, &tr, false, tx.Commit()
}

func (r *ListeningRepository) FinishPreparation(ctx context.Context, id int64, outcome string, e domain.ListeningExercise, now time.Time) (domain.ListeningPreparation, domain.ListeningExercise, error) {
	tx, err := r.begin(ctx, "listening_preparations")
	if err != nil {
		return domain.ListeningPreparation{}, domain.ListeningExercise{}, err
	}
	defer func() { _ = tx.Rollback() }()
	exerciseID, err := insertExercise(ctx, tx, e, fmtTime(now))
	if err != nil {
		return domain.ListeningPreparation{}, domain.ListeningExercise{}, err
	}
	res, err := tx.ExecContext(ctx, `UPDATE listening_preparations SET outcome = ?, finished_at = ?, exercise_id = ?
		WHERE id = ? AND finished_at IS NULL`, outcome, fmtTime(now), exerciseID, id)
	if err != nil {
		return domain.ListeningPreparation{}, domain.ListeningExercise{}, fmt.Errorf("finish listening preparation: %w", err)
	}
	if n, _ := res.RowsAffected(); n != 1 {
		return domain.ListeningPreparation{}, domain.ListeningExercise{}, fmt.Errorf("listening preparation %d is not pending", id)
	}
	p, err := readPreparation(ctx, tx, `id = ?`, id)
	if err != nil {
		return p, domain.ListeningExercise{}, err
	}
	stored, err := readExercise(ctx, tx, `id = ?`, exerciseID)
	if err != nil {
		return p, stored, err
	}
	return p, stored, tx.Commit()
}

func (r *ListeningRepository) GetPreparationByOperation(ctx context.Context, operationID string) (domain.ListeningPreparation, error) {
	return readPreparation(ctx, r.db, `operation_id = ?`, operationID)
}

func (r *ListeningRepository) GetExercise(ctx context.Context, id int64) (domain.ListeningExercise, error) {
	return readExercise(ctx, r.db, `id = ?`, id)
}

// ---- notifications ----

const notificationColumns = `id, operation_id, exercise_id, channel, trigger, pull_run_id, after_unknown,
	started_at, deadline_at, finished_at, outcome, failure_code`

func readNotification(ctx context.Context, q queryer, where string, args ...any) (domain.ListeningNotification, error) {
	var n domain.ListeningNotification
	var runID sql.NullInt64
	var finished, outcome, code sql.NullString
	var started, deadline string
	var after int
	err := q.QueryRowContext(ctx, `SELECT `+notificationColumns+` FROM listening_notifications WHERE `+where, args...).Scan(
		&n.ID, &n.OperationID, &n.ExerciseID, &n.Channel, &n.Trigger, &runID, &after, &started, &deadline, &finished, &outcome, &code)
	if errors.Is(err, sql.ErrNoRows) {
		return n, fmt.Errorf("%w: listening notification", domain.ErrNotFound)
	}
	if err != nil {
		return n, err
	}
	n.PullRunID, n.AfterUnknown = nullInt(runID), after == 1
	n.StartedAt, n.DeadlineAt, n.FinishedAt = parseTime(started), parseTime(deadline), parseNullTime(finished)
	n.Outcome, n.FailureCode = outcome.String, code.String
	return n, nil
}

func (r *ListeningRepository) StartNotification(ctx context.Context, in domain.NewListeningNotification) (domain.ListeningNotification, bool, error) {
	var none domain.ListeningNotification
	tx, err := r.begin(ctx, "listening_notifications")
	if err != nil {
		return none, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if n, err := readNotification(ctx, tx, `operation_id = ?`, in.OperationID); err == nil {
		if n.ExerciseID != in.ExerciseID || n.Trigger != in.Trigger {
			return none, false, domain.ErrListeningOperationConflict
		}
		return n, true, tx.Commit()
	} else if !errors.Is(err, domain.ErrNotFound) {
		return none, false, err
	}
	e, err := readExercise(ctx, tx, `id = ?`, in.ExerciseID)
	if err != nil {
		return none, false, err
	}
	if e.Status != domain.ListeningExerciseCompleted {
		return none, false, domain.ErrListeningExerciseNotCompleted
	}
	afterUnknown := false
	latest, err := readNotification(ctx, tx, `exercise_id = ? ORDER BY id DESC LIMIT 1`, in.ExerciseID)
	switch {
	case errors.Is(err, domain.ErrNotFound):
		if in.Trigger == domain.ListeningTriggerExplicit {
			return none, false, domain.ErrListeningNotRetryable
		}
	case err != nil:
		return none, false, err
	default:
		state := latest.State(in.Now)
		switch {
		case state == domain.ListeningStateInProgress:
			return latest, false, domain.ErrListeningNotificationInProgress
		case in.Trigger == domain.ListeningTriggerPull:
			return latest, false, domain.ErrListeningNotEligible
		case state == domain.ListeningOutcomeSent:
			return latest, false, domain.ErrListeningNotRetryable
		case state == domain.ListeningOutcomeUnknown && !in.ConfirmUnknownRetry:
			return latest, false, domain.ErrListeningOutcomeUnknown
		case state == domain.ListeningOutcomeUnknown:
			afterUnknown = true
		}
	}
	var runID any
	if in.PullRunID != nil {
		runID = *in.PullRunID
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO listening_notifications
		(operation_id, exercise_id, channel, trigger, pull_run_id, after_unknown, started_at, deadline_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		in.OperationID, in.ExerciseID, in.Channel, in.Trigger, runID, boolInt(afterUnknown), fmtTime(in.Now), fmtTime(in.Deadline))
	if err != nil {
		return none, false, fmt.Errorf("insert listening notification: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return none, false, err
	}
	n, err := readNotification(ctx, tx, `id = ?`, id)
	if err != nil {
		return n, false, err
	}
	return n, false, tx.Commit()
}

func (r *ListeningRepository) FinishNotification(ctx context.Context, id int64, outcome, code string, now time.Time) (domain.ListeningNotification, error) {
	var failure any
	if code != "" {
		failure = code
	}
	res, err := r.db.ExecContext(ctx, `UPDATE listening_notifications SET outcome = ?, failure_code = ?, finished_at = ?
		WHERE id = ? AND finished_at IS NULL`, outcome, failure, fmtTime(now), id)
	if err != nil {
		return domain.ListeningNotification{}, fmt.Errorf("finish listening notification: %w", err)
	}
	if n, _ := res.RowsAffected(); n != 1 {
		return domain.ListeningNotification{}, fmt.Errorf("listening notification %d is not pending", id)
	}
	return readNotification(ctx, r.db, `id = ?`, id)
}

func (r *ListeningRepository) GetNotificationByOperation(ctx context.Context, operationID string) (domain.ListeningNotification, error) {
	return readNotification(ctx, r.db, `operation_id = ?`, operationID)
}

// ---- derived material status ----

func (r *ListeningRepository) MaterialStatus(ctx context.Context, materialID int64, now time.Time) (domain.ListeningMaterialStatus, error) {
	st := domain.ListeningMaterialStatus{Preparations: []domain.ListeningPreparation{}, Notifications: []domain.ListeningNotification{}}
	var err error
	if st.InPlaylist, err = exists(ctx, r.db, `SELECT 1 FROM listening_playlist_items WHERE material_id = ?`, materialID); err != nil {
		return st, err
	}
	rows, err := r.db.QueryContext(ctx, `SELECT id FROM listening_preparations WHERE material_id = ? ORDER BY id DESC`, materialID)
	if err != nil {
		return st, err
	}
	ids, err := scanIDs(rows)
	if err != nil {
		return st, err
	}
	for _, id := range ids {
		p, err := readPreparation(ctx, r.db, `id = ?`, id)
		if err != nil {
			return st, err
		}
		st.Preparations = append(st.Preparations, p)
	}
	rows, err = r.db.QueryContext(ctx, `SELECT n.id FROM listening_notifications n JOIN listening_exercises e ON e.id = n.exercise_id
		WHERE e.material_id = ? ORDER BY n.id DESC`, materialID)
	if err != nil {
		return st, err
	}
	if ids, err = scanIDs(rows); err != nil {
		return st, err
	}
	for _, id := range ids {
		n, err := readNotification(ctx, r.db, `id = ?`, id)
		if err != nil {
			return st, err
		}
		st.Notifications = append(st.Notifications, n)
	}

	tr, err := r.LatestTranscript(ctx, materialID)
	if err != nil {
		return st, err
	}
	if tr == nil {
		st.State = domain.ListeningMaterialWaiting
		return st, nil
	}
	if len(st.Preparations) > 0 {
		switch st.Preparations[0].State(now) {
		case domain.ListeningStateInProgress:
			st.State = domain.ListeningMaterialInProgress
			return st, nil
		case domain.ListeningOutcomeUnknown:
			st.State = domain.ListeningMaterialUnknown
			return st, nil
		}
	}
	completed, err := exists(ctx, r.db, `SELECT 1 FROM listening_exercises WHERE transcript_id = ? AND status = 'completed'`, tr.ID)
	if err != nil {
		return st, err
	}
	var latestStatus sql.NullString
	if err := r.db.QueryRowContext(ctx, `SELECT status FROM listening_exercises WHERE transcript_id = ? ORDER BY id DESC LIMIT 1`, tr.ID).
		Scan(&latestStatus); err != nil && !errors.Is(err, sql.ErrNoRows) {
		return st, err
	}
	switch {
	case completed:
		st.State = domain.ListeningMaterialPrepared
	case latestStatus.String == domain.ListeningExerciseFailed:
		st.State = domain.ListeningMaterialFailed
	default:
		st.State = domain.ListeningMaterialReady
	}
	return st, nil
}

func scanIDs(rows *sql.Rows) ([]int64, error) {
	defer rows.Close()
	var ids []int64
	for rows.Next() {
		var id int64
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, rows.Err()
}
