package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// NotebookRepository reads the structured capture sources (migration 019,
// written by CaptureRepository with their capture) and stores the learner's
// append-only retry marks. It writes nothing else.
type NotebookRepository struct {
	db *sql.DB
}

var _ domain.NotebookRepository = (*NotebookRepository)(nil)

// NewNotebookRepository builds a repository over an open database.
func NewNotebookRepository(db *sql.DB) *NotebookRepository { return &NotebookRepository{db: db} }

const sourceColumns = `s.capture_row_id, s.entry_id, c.capture_id, s.source_type, s.record_id, s.item, s.attempt, s.created_at`

func scanSource(scan func(...any) error) (domain.LearningCaptureSource, error) {
	var s domain.LearningCaptureSource
	var attempt sql.NullString
	var created string
	if err := scan(&s.CaptureRowID, &s.EntryID, &s.CaptureID, &s.Ref.Type, &s.Ref.RecordID, &s.Ref.Item, &attempt, &created); err != nil {
		return s, err
	}
	s.Ref.Attempt, s.CreatedAt = attempt.String, parseTime(created)
	return s, nil
}

func (r *NotebookRepository) ListSources(ctx context.Context) ([]domain.LearningCaptureSource, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT `+sourceColumns+` FROM learning_capture_sources s JOIN learning_captures c ON c.id = s.capture_row_id ORDER BY s.capture_row_id DESC`)
	if err != nil {
		return nil, fmt.Errorf("list capture sources: %w", err)
	}
	defer rows.Close()
	out := []domain.LearningCaptureSource{}
	for rows.Next() {
		s, err := scanSource(rows.Scan)
		if err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

func readSourceByEntry(ctx context.Context, q queryer, entryID int64) (domain.LearningCaptureSource, error) {
	s, err := scanSource(q.QueryRowContext(ctx, `SELECT `+sourceColumns+` FROM learning_capture_sources s JOIN learning_captures c ON c.id = s.capture_row_id WHERE s.entry_id = ?`, entryID).Scan)
	if errors.Is(err, sql.ErrNoRows) {
		return s, fmt.Errorf("%w: no structured source for record %d", domain.ErrNotFound, entryID)
	}
	return s, err
}

func (r *NotebookRepository) GetSourceByEntry(ctx context.Context, entryID int64) (domain.LearningCaptureSource, error) {
	return readSourceByEntry(ctx, r.db, entryID)
}

func (r *NotebookRepository) CurrentMarks(ctx context.Context) (map[int64]domain.RetryMark, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT m.entry_id, m.marked, m.created_at FROM mistake_retry_marks m
		WHERE m.id = (SELECT MAX(id) FROM mistake_retry_marks WHERE entry_id = m.entry_id)`)
	if err != nil {
		return nil, fmt.Errorf("read retry marks: %w", err)
	}
	defer rows.Close()
	out := map[int64]domain.RetryMark{}
	for rows.Next() {
		var m domain.RetryMark
		var marked int
		var at string
		if err := rows.Scan(&m.EntryID, &marked, &at); err != nil {
			return nil, err
		}
		m.Marked, m.At = marked == 1, parseTime(at)
		out[m.EntryID] = m
	}
	return out, rows.Err()
}

// SetMark appends the decision only when it changes the current state, inside
// one write transaction; a record without a structured source is not a
// notebook record (ErrNotFound).
func (r *NotebookRepository) SetMark(ctx context.Context, entryID int64, marked bool, now time.Time) (domain.RetryMark, bool, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return domain.RetryMark{}, false, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := tx.ExecContext(ctx, `UPDATE mistake_retry_marks SET rowid = rowid WHERE 0`); err != nil {
		return domain.RetryMark{}, false, fmt.Errorf("take write lock: %w", err)
	}
	if _, err := readSourceByEntry(ctx, tx, entryID); err != nil {
		return domain.RetryMark{}, false, err
	}
	current := domain.RetryMark{EntryID: entryID}
	var was int
	var at string
	err = tx.QueryRowContext(ctx, `SELECT marked, created_at FROM mistake_retry_marks WHERE entry_id = ? ORDER BY id DESC LIMIT 1`, entryID).Scan(&was, &at)
	switch {
	case errors.Is(err, sql.ErrNoRows):
	case err != nil:
		return current, false, err
	default:
		current.Marked, current.At = was == 1, parseTime(at)
	}
	// No row means "not marked". Only a change of state is recorded.
	if current.Marked == marked {
		return current, false, tx.Commit()
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO mistake_retry_marks (entry_id, marked, created_at) VALUES (?, ?, ?)`, entryID, boolInt(marked), fmtTime(now)); err != nil {
		return current, false, fmt.Errorf("insert retry mark: %w", err)
	}
	return domain.RetryMark{EntryID: entryID, Marked: marked, At: now}, true, tx.Commit()
}
