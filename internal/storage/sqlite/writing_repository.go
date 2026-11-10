package sqlite

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"time"

	"french-learning-app/internal/domain"
)

// WritingRepository stores Exam Writing v1 records (migration 017). Tasks,
// drafts and feedback are inserted once and never updated; a feedback request
// is inserted before the provider call and finished once, with its start
// rules applied inside one write transaction. It writes nothing to entries,
// analyses, Concepts, annotations or admission.
type WritingRepository struct {
	db *sql.DB
}

var _ domain.WritingRepository = (*WritingRepository)(nil)

// NewWritingRepository builds a repository over an open database.
func NewWritingRepository(db *sql.DB) *WritingRepository { return &WritingRepository{db: db} }

func (r *WritingRepository) beginWrite(ctx context.Context, table string) (*sql.Tx, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `UPDATE `+table+` SET rowid = rowid WHERE 0`); err != nil {
		_ = tx.Rollback()
		return nil, fmt.Errorf("take write lock: %w", err)
	}
	return tx, nil
}

const writingTaskColumns = `id, title, prompt, requirements, word_min, word_max, origin, prompt_id, created_at`

func readWritingTask(ctx context.Context, q queryer, where string, args ...any) (domain.WritingTask, error) {
	var t domain.WritingTask
	var reqs, created string
	var prompt sql.NullString
	err := q.QueryRowContext(ctx, `SELECT `+writingTaskColumns+` FROM writing_tasks WHERE `+where, args...).
		Scan(&t.ID, &t.Title, &t.Prompt, &reqs, &t.WordMin, &t.WordMax, &t.Origin, &prompt, &created)
	if errors.Is(err, sql.ErrNoRows) {
		return t, fmt.Errorf("%w: writing task", domain.ErrNotFound)
	}
	if err != nil {
		return t, err
	}
	if err := json.Unmarshal([]byte(reqs), &t.Requirements); err != nil {
		return t, fmt.Errorf("decode task %d: %w", t.ID, err)
	}
	t.PromptID, t.CreatedAt = prompt.String, parseTime(created)
	return t, nil
}

func insertWritingTask(ctx context.Context, x execer, t domain.WritingTask, now time.Time) (int64, error) {
	reqs, err := json.Marshal(t.Requirements)
	if err != nil {
		return 0, err
	}
	var prompt any
	if t.PromptID != "" {
		prompt = t.PromptID
	}
	res, err := x.ExecContext(ctx, `INSERT INTO writing_tasks (title, prompt, requirements, word_min, word_max, origin, prompt_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		t.Title, t.Prompt, string(reqs), t.WordMin, t.WordMax, t.Origin, prompt, fmtTime(now))
	if err != nil {
		return 0, fmt.Errorf("insert writing task: %w", err)
	}
	return res.LastInsertId()
}

func (r *WritingRepository) CreateTask(ctx context.Context, t domain.WritingTask, now time.Time) (domain.WritingTask, error) {
	id, err := insertWritingTask(ctx, r.db, t, now)
	if err != nil {
		return domain.WritingTask{}, err
	}
	return r.GetTask(ctx, id)
}

func (r *WritingRepository) StartAuthoredTask(ctx context.Context, t domain.WritingTask, now time.Time) (domain.WritingTask, bool, error) {
	tx, err := r.beginWrite(ctx, "writing_tasks")
	if err != nil {
		return domain.WritingTask{}, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if existing, err := readWritingTask(ctx, tx, `prompt_id = ?`, t.PromptID); err == nil {
		if existing.Title != t.Title || existing.Prompt != t.Prompt || existing.WordMin != t.WordMin || existing.WordMax != t.WordMax ||
			!reflect.DeepEqual(existing.Requirements, t.Requirements) {
			return existing, false, domain.ErrWritingPromptConflict
		}
		return existing, true, tx.Commit()
	} else if !errors.Is(err, domain.ErrNotFound) {
		return domain.WritingTask{}, false, err
	}
	id, err := insertWritingTask(ctx, tx, t, now)
	if err != nil {
		return domain.WritingTask{}, false, err
	}
	saved, err := readWritingTask(ctx, tx, `id = ?`, id)
	if err != nil {
		return saved, false, err
	}
	return saved, false, tx.Commit()
}

func (r *WritingRepository) GetTask(ctx context.Context, id int64) (domain.WritingTask, error) {
	return readWritingTask(ctx, r.db, `id = ?`, id)
}

func (r *WritingRepository) ListTasks(ctx context.Context) ([]domain.WritingTask, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT id FROM writing_tasks ORDER BY id DESC`)
	if err != nil {
		return nil, err
	}
	ids, err := scanIDs(rows)
	if err != nil {
		return nil, err
	}
	out := []domain.WritingTask{}
	for _, id := range ids {
		t, err := r.GetTask(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	return out, nil
}

func readWritingDraft(ctx context.Context, q queryer, where string, args ...any) (domain.WritingDraft, error) {
	var d domain.WritingDraft
	var created string
	err := q.QueryRowContext(ctx, `SELECT id, task_id, version, text, word_count, created_at FROM writing_drafts WHERE `+where, args...).
		Scan(&d.ID, &d.TaskID, &d.Version, &d.Text, &d.WordCount, &created)
	if errors.Is(err, sql.ErrNoRows) {
		return d, fmt.Errorf("%w: writing draft", domain.ErrNotFound)
	}
	d.CreatedAt = parseTime(created)
	return d, err
}

func (r *WritingRepository) AddDraft(ctx context.Context, taskID int64, text string, words int, now time.Time) (domain.WritingDraft, error) {
	tx, err := r.beginWrite(ctx, "writing_drafts")
	if err != nil {
		return domain.WritingDraft{}, err
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := readWritingTask(ctx, tx, `id = ?`, taskID); err != nil {
		return domain.WritingDraft{}, err
	}
	var version int
	if err := tx.QueryRowContext(ctx, `SELECT COALESCE(MAX(version), 0) FROM writing_drafts WHERE task_id = ?`, taskID).Scan(&version); err != nil {
		return domain.WritingDraft{}, err
	}
	if version >= domain.MaxWritingVersions {
		return domain.WritingDraft{}, domain.ErrWritingTooManyVersions
	}
	if version > 0 {
		latest, err := readWritingDraft(ctx, tx, `task_id = ? AND version = ?`, taskID, version)
		if err != nil {
			return domain.WritingDraft{}, err
		}
		if latest.Text == text {
			return latest, domain.ErrWritingDraftUnchanged
		}
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO writing_drafts (task_id, version, text, word_count, created_at) VALUES (?, ?, ?, ?, ?)`,
		taskID, version+1, text, words, fmtTime(now))
	if err != nil {
		return domain.WritingDraft{}, fmt.Errorf("insert writing draft: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return domain.WritingDraft{}, err
	}
	d, err := readWritingDraft(ctx, tx, `id = ?`, id)
	if err != nil {
		return d, err
	}
	return d, tx.Commit()
}

func (r *WritingRepository) GetDraft(ctx context.Context, id int64) (domain.WritingDraft, error) {
	return readWritingDraft(ctx, r.db, `id = ?`, id)
}

func (r *WritingRepository) ListDrafts(ctx context.Context, taskID int64) ([]domain.WritingDraft, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT id FROM writing_drafts WHERE task_id = ? ORDER BY version`, taskID)
	if err != nil {
		return nil, err
	}
	ids, err := scanIDs(rows)
	if err != nil {
		return nil, err
	}
	out := []domain.WritingDraft{}
	for _, id := range ids {
		d, err := r.GetDraft(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, nil
}

func readWritingFeedback(ctx context.Context, q queryer, where string, args ...any) (domain.WritingFeedback, error) {
	var f domain.WritingFeedback
	var failure, content sql.NullString
	var created string
	err := q.QueryRowContext(ctx, `SELECT id, task_id, draft_id, status, failure_code, generator, content, created_at FROM writing_feedback WHERE `+where, args...).
		Scan(&f.ID, &f.TaskID, &f.DraftID, &f.Status, &failure, &f.Generator, &content, &created)
	if errors.Is(err, sql.ErrNoRows) {
		return f, fmt.Errorf("%w: writing feedback", domain.ErrNotFound)
	}
	if err != nil {
		return f, err
	}
	f.FailureCode, f.CreatedAt = failure.String, parseTime(created)
	if content.Valid {
		var c domain.WritingFeedbackContent
		if err := json.Unmarshal([]byte(content.String), &c); err != nil {
			return f, fmt.Errorf("decode writing feedback %d: %w", f.ID, err)
		}
		f.Content = &c
	}
	return f, nil
}

func (r *WritingRepository) ListFeedback(ctx context.Context, taskID int64) ([]domain.WritingFeedback, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT id FROM writing_feedback WHERE task_id = ? ORDER BY id DESC`, taskID)
	if err != nil {
		return nil, err
	}
	ids, err := scanIDs(rows)
	if err != nil {
		return nil, err
	}
	out := []domain.WritingFeedback{}
	for _, id := range ids {
		f, err := r.GetFeedback(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, f)
	}
	return out, nil
}

func (r *WritingRepository) GetFeedback(ctx context.Context, id int64) (domain.WritingFeedback, error) {
	return readWritingFeedback(ctx, r.db, `id = ?`, id)
}

const writingRequestColumns = `id, operation_id, task_id, draft_id, after_unknown, started_at, deadline_at, finished_at, outcome, feedback_id`

func readWritingRequest(ctx context.Context, q queryer, where string, args ...any) (domain.WritingFeedbackRequest, error) {
	var w domain.WritingFeedbackRequest
	var after int
	var started, deadline string
	var finished, outcome sql.NullString
	var feedback sql.NullInt64
	err := q.QueryRowContext(ctx, `SELECT `+writingRequestColumns+` FROM writing_feedback_requests WHERE `+where, args...).
		Scan(&w.ID, &w.OperationID, &w.TaskID, &w.DraftID, &after, &started, &deadline, &finished, &outcome, &feedback)
	if errors.Is(err, sql.ErrNoRows) {
		return w, fmt.Errorf("%w: writing feedback request", domain.ErrNotFound)
	}
	if err != nil {
		return w, err
	}
	w.AfterUnknown, w.StartedAt, w.DeadlineAt, w.FinishedAt = after == 1, parseTime(started), parseTime(deadline), parseNullTime(finished)
	w.Outcome, w.FeedbackID = outcome.String, nullInt(feedback)
	return w, nil
}

// StartFeedbackRequest: a request still in progress for the same task blocks
// any new one; an unknown outcome for the same draft version needs the
// learner's acknowledgement. A new version is a new input and is not blocked
// by an unknown request about an older one.
func (r *WritingRepository) StartFeedbackRequest(ctx context.Context, in domain.NewWritingFeedbackRequest) (domain.WritingFeedbackRequest, *domain.WritingDraft, bool, error) {
	var none domain.WritingFeedbackRequest
	tx, err := r.beginWrite(ctx, "writing_feedback_requests")
	if err != nil {
		return none, nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if w, err := readWritingRequest(ctx, tx, `operation_id = ?`, in.OperationID); err == nil {
		if w.DraftID != in.DraftID {
			return none, nil, false, domain.ErrWritingOperationConflict
		}
		d, err := readWritingDraft(ctx, tx, `id = ?`, w.DraftID)
		if err != nil {
			return none, nil, false, err
		}
		return w, &d, true, tx.Commit()
	} else if !errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, err
	}
	d, err := readWritingDraft(ctx, tx, `id = ?`, in.DraftID)
	if err != nil {
		return none, nil, false, err
	}
	if latest, err := readWritingRequest(ctx, tx, `task_id = ? ORDER BY id DESC LIMIT 1`, d.TaskID); err == nil && latest.State(in.Now) == domain.ListeningStateInProgress {
		return latest, nil, false, domain.ErrWritingRequestInProgress
	} else if err != nil && !errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, err
	}
	afterUnknown := false
	if latest, err := readWritingRequest(ctx, tx, `draft_id = ? ORDER BY id DESC LIMIT 1`, d.ID); err == nil && latest.State(in.Now) == domain.ListeningOutcomeUnknown {
		if !in.ConfirmUnknownRetry {
			return latest, nil, false, domain.ErrWritingOutcomeUnknown
		}
		afterUnknown = true
	} else if err != nil && !errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, err
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO writing_feedback_requests (operation_id, task_id, draft_id, after_unknown, started_at, deadline_at) VALUES (?, ?, ?, ?, ?, ?)`,
		in.OperationID, d.TaskID, d.ID, boolInt(afterUnknown), fmtTime(in.Now), fmtTime(in.Deadline))
	if err != nil {
		return none, nil, false, fmt.Errorf("insert writing feedback request: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return none, nil, false, err
	}
	w, err := readWritingRequest(ctx, tx, `id = ?`, id)
	if err != nil {
		return none, nil, false, err
	}
	return w, &d, false, tx.Commit()
}

func (r *WritingRepository) FinishFeedbackRequest(ctx context.Context, id int64, outcome string, f domain.WritingFeedback, now time.Time) (domain.WritingFeedbackRequest, domain.WritingFeedback, error) {
	tx, err := r.beginWrite(ctx, "writing_feedback_requests")
	if err != nil {
		return domain.WritingFeedbackRequest{}, domain.WritingFeedback{}, err
	}
	defer func() { _ = tx.Rollback() }()
	var content, failure any
	if f.Content != nil {
		raw, err := json.Marshal(f.Content)
		if err != nil {
			return domain.WritingFeedbackRequest{}, domain.WritingFeedback{}, err
		}
		content = string(raw)
	}
	if f.FailureCode != "" {
		failure = f.FailureCode
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO writing_feedback (task_id, draft_id, status, failure_code, generator, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		f.TaskID, f.DraftID, f.Status, failure, f.Generator, content, fmtTime(now))
	if err != nil {
		return domain.WritingFeedbackRequest{}, domain.WritingFeedback{}, fmt.Errorf("insert writing feedback: %w", err)
	}
	feedbackID, err := res.LastInsertId()
	if err != nil {
		return domain.WritingFeedbackRequest{}, domain.WritingFeedback{}, err
	}
	upd, err := tx.ExecContext(ctx, `UPDATE writing_feedback_requests SET outcome = ?, finished_at = ?, feedback_id = ? WHERE id = ? AND finished_at IS NULL`,
		outcome, fmtTime(now), feedbackID, id)
	if err != nil {
		return domain.WritingFeedbackRequest{}, domain.WritingFeedback{}, fmt.Errorf("finish writing feedback request: %w", err)
	}
	if n, _ := upd.RowsAffected(); n != 1 {
		return domain.WritingFeedbackRequest{}, domain.WritingFeedback{}, fmt.Errorf("writing feedback request %d is not pending", id)
	}
	w, err := readWritingRequest(ctx, tx, `id = ?`, id)
	if err != nil {
		return w, domain.WritingFeedback{}, err
	}
	stored, err := readWritingFeedback(ctx, tx, `id = ?`, feedbackID)
	if err != nil {
		return w, stored, err
	}
	return w, stored, tx.Commit()
}

func (r *WritingRepository) GetFeedbackRequestByOperation(ctx context.Context, operationID string) (domain.WritingFeedbackRequest, error) {
	return readWritingRequest(ctx, r.db, `operation_id = ?`, operationID)
}

func (r *WritingRepository) ListFeedbackRequests(ctx context.Context, taskID int64) ([]domain.WritingFeedbackRequest, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT id FROM writing_feedback_requests WHERE task_id = ? ORDER BY id DESC`, taskID)
	if err != nil {
		return nil, err
	}
	ids, err := scanIDs(rows)
	if err != nil {
		return nil, err
	}
	out := []domain.WritingFeedbackRequest{}
	for _, id := range ids {
		w, err := readWritingRequest(ctx, r.db, `id = ?`, id)
		if err != nil {
			return nil, err
		}
		out = append(out, w)
	}
	return out, nil
}
