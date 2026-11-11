package sqlite

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"time"

	"french-learning-app/internal/domain"
)

// ExamRepository stores Mock Exam v1 sessions (migration 020). Items are
// written once with their session; answers are append-only events; a session
// has at most one submission. Every write re-checks the session's state in its
// own write transaction.
type ExamRepository struct {
	db *sql.DB
}

var _ domain.ExamRepository = (*ExamRepository)(nil)

// NewExamRepository builds a repository over an open database.
func NewExamRepository(db *sql.DB) *ExamRepository { return &ExamRepository{db: db} }

func (r *ExamRepository) beginWrite(ctx context.Context) (*sql.Tx, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `UPDATE exam_sessions SET rowid = rowid WHERE 0`); err != nil {
		_ = tx.Rollback()
		return nil, fmt.Errorf("take write lock: %w", err)
	}
	return tx, nil
}

const examSessionColumns = `id, operation_id, kind, form_id, form_title, retry_of_session_id, retry_of_position,
	forms_sha256, pack_sha256, duration_seconds, started_at, deadline_at`

type rowScanner interface {
	Scan(dest ...any) error
}

func scanExamSession(row rowScanner) (domain.ExamSession, error) {
	var s domain.ExamSession
	var retryOf, retryPos sql.NullInt64
	var started, deadline string
	err := row.Scan(&s.ID, &s.OperationID, &s.Kind, &s.FormID, &s.FormTitle, &retryOf, &retryPos,
		&s.FormsSHA256, &s.PackSHA256, &s.DurationSeconds, &started, &deadline)
	if errors.Is(err, sql.ErrNoRows) {
		return s, fmt.Errorf("%w: exam session", domain.ErrNotFound)
	}
	if err != nil {
		return s, err
	}
	if retryOf.Valid {
		id := retryOf.Int64
		s.RetryOf = &id
		s.RetryOfPosition = int(retryPos.Int64)
	}
	s.StartedAt, s.DeadlineAt = parseTime(started), parseTime(deadline)
	return s, nil
}

func (r *ExamRepository) loadItems(ctx context.Context, q interface {
	QueryContext(ctx context.Context, query string, args ...any) (*sql.Rows, error)
}, s *domain.ExamSession) error {
	rows, err := q.QueryContext(ctx, `SELECT position, content_json, content_sha256 FROM exam_session_items WHERE session_id = ? ORDER BY position`, s.ID)
	if err != nil {
		return err
	}
	defer rows.Close()
	s.Items, s.ItemSHA256 = nil, nil
	for rows.Next() {
		var pos int
		var content, sum string
		if err := rows.Scan(&pos, &content, &sum); err != nil {
			return err
		}
		if pos != len(s.Items)+1 {
			return fmt.Errorf("exam session %d: item positions are not contiguous", s.ID)
		}
		var it domain.ExamItem
		if err := json.Unmarshal([]byte(content), &it); err != nil {
			return fmt.Errorf("decode exam item %d/%d: %w", s.ID, pos, err)
		}
		s.Items, s.ItemSHA256 = append(s.Items, it), append(s.ItemSHA256, sum)
	}
	return rows.Err()
}

// CreateSession stores a session and its items, or replays the session stored
// under the same operation id.
func (r *ExamRepository) CreateSession(ctx context.Context, s domain.ExamSession) (domain.ExamSession, bool, error) {
	tx, err := r.beginWrite(ctx)
	if err != nil {
		return s, false, err
	}
	defer func() { _ = tx.Rollback() }()
	existing, err := scanExamSession(tx.QueryRowContext(ctx, `SELECT `+examSessionColumns+` FROM exam_sessions WHERE operation_id = ?`, s.OperationID))
	switch {
	case err == nil:
		same := existing.Kind == s.Kind && existing.FormID == s.FormID && existing.RetryOfPosition == s.RetryOfPosition &&
			((existing.RetryOf == nil && s.RetryOf == nil) || (existing.RetryOf != nil && s.RetryOf != nil && *existing.RetryOf == *s.RetryOf))
		if !same {
			return s, false, domain.ErrExamOperationConflict
		}
		if err := r.loadItems(ctx, tx, &existing); err != nil {
			return s, false, err
		}
		return existing, true, nil
	case !errors.Is(err, domain.ErrNotFound):
		return s, false, err
	}
	var retryOf, retryPos any
	if s.RetryOf != nil {
		retryOf, retryPos = *s.RetryOf, s.RetryOfPosition
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO exam_sessions (operation_id, kind, form_id, form_title, retry_of_session_id, retry_of_position,
		forms_sha256, pack_sha256, duration_seconds, started_at, deadline_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		s.OperationID, s.Kind, s.FormID, s.FormTitle, retryOf, retryPos, s.FormsSHA256, s.PackSHA256, s.DurationSeconds,
		fmtTime(s.StartedAt), fmtTime(s.DeadlineAt))
	if err != nil {
		return s, false, fmt.Errorf("insert exam session: %w", err)
	}
	if s.ID, err = res.LastInsertId(); err != nil {
		return s, false, err
	}
	s.ItemSHA256 = nil
	for i, it := range s.Items {
		sum, raw, err := it.ContentSHA256()
		if err != nil {
			return s, false, err
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO exam_session_items (session_id, position, pack_id, passage_id, question_id, content_json, content_sha256)
			VALUES (?, ?, ?, ?, ?, ?, ?)`, s.ID, i+1, it.PackID, it.PassageID, it.QuestionID, string(raw), sum); err != nil {
			return s, false, fmt.Errorf("insert exam item: %w", err)
		}
		s.ItemSHA256 = append(s.ItemSHA256, sum)
	}
	if err := tx.Commit(); err != nil {
		return s, false, err
	}
	return s, false, nil
}

// GetSession returns a session with its frozen items.
func (r *ExamRepository) GetSession(ctx context.Context, id int64) (domain.ExamSession, error) {
	s, err := scanExamSession(r.db.QueryRowContext(ctx, `SELECT `+examSessionColumns+` FROM exam_sessions WHERE id = ?`, id))
	if err != nil {
		return s, err
	}
	return s, r.loadItems(ctx, r.db, &s)
}

// ListSessions returns every session, newest first, without items.
func (r *ExamRepository) ListSessions(ctx context.Context) ([]domain.ExamSession, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT `+examSessionColumns+` FROM exam_sessions ORDER BY id DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []domain.ExamSession{}
	for rows.Next() {
		s, err := scanExamSession(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

// RetryQuestionIDs lists the questions already asked in retries of a session.
func (r *ExamRepository) RetryQuestionIDs(ctx context.Context, sessionID int64) ([]string, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT i.question_id FROM exam_session_items i JOIN exam_sessions s ON s.id = i.session_id
		WHERE s.retry_of_session_id = ? ORDER BY s.id, i.position`, sessionID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var q string
		if err := rows.Scan(&q); err != nil {
			return nil, err
		}
		out = append(out, q)
	}
	return out, rows.Err()
}

func currentAnswers(ctx context.Context, q interface {
	QueryContext(ctx context.Context, query string, args ...any) (*sql.Rows, error)
}, sessionID int64) (map[int]domain.ExamAnswer, error) {
	rows, err := q.QueryContext(ctx, `SELECT position, choice, saved_at FROM exam_answers WHERE session_id = ? ORDER BY id`, sessionID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[int]domain.ExamAnswer{}
	for rows.Next() {
		var a domain.ExamAnswer
		var choice sql.NullInt64
		var saved string
		if err := rows.Scan(&a.Position, &choice, &saved); err != nil {
			return nil, err
		}
		if choice.Valid {
			c := int(choice.Int64)
			a.Choice = &c
		}
		a.SavedAt = parseTime(saved)
		out[a.Position] = a // the latest event wins
	}
	return out, rows.Err()
}

// CurrentAnswers returns the latest answer event per position.
func (r *ExamRepository) CurrentAnswers(ctx context.Context, sessionID int64) (map[int]domain.ExamAnswer, error) {
	return currentAnswers(ctx, r.db, sessionID)
}

func getSubmission(ctx context.Context, q queryer, sessionID int64) (*domain.ExamSubmission, error) {
	var sub domain.ExamSubmission
	var answers, at string
	err := q.QueryRowContext(ctx, `SELECT session_id, answers_json, answers_sha256, correct, total, submitted_at FROM exam_submissions WHERE session_id = ?`, sessionID).
		Scan(&sub.SessionID, &answers, &sub.AnswersSHA256, &sub.Correct, &sub.Total, &at)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	byKey := map[string]*int{}
	if err := json.Unmarshal([]byte(answers), &byKey); err != nil {
		return nil, fmt.Errorf("decode submission %d: %w", sessionID, err)
	}
	sub.Answers = map[int]*int{}
	for k, v := range byKey {
		p, err := strconv.Atoi(k)
		if err != nil {
			return nil, fmt.Errorf("decode submission %d: %w", sessionID, err)
		}
		sub.Answers[p] = v
	}
	sub.SubmittedAt = parseTime(at)
	return &sub, nil
}

// GetSubmission returns the session's submission, or nil.
func (r *ExamRepository) GetSubmission(ctx context.Context, sessionID int64) (*domain.ExamSubmission, error) {
	return getSubmission(ctx, r.db, sessionID)
}

// writableSession loads a session and its submission inside a write
// transaction; the caller decides from its state.
func writableSession(ctx context.Context, tx *sql.Tx, sessionID int64) (domain.ExamSession, *domain.ExamSubmission, error) {
	s, err := scanExamSession(tx.QueryRowContext(ctx, `SELECT `+examSessionColumns+` FROM exam_sessions WHERE id = ?`, sessionID))
	if err != nil {
		return s, nil, err
	}
	sub, err := getSubmission(ctx, tx, sessionID)
	return s, sub, err
}

func sameChoice(a, b *int) bool {
	return (a == nil && b == nil) || (a != nil && b != nil && *a == *b)
}

// SaveAnswer appends an answer event if it changes the current answer.
func (r *ExamRepository) SaveAnswer(ctx context.Context, sessionID int64, position int, choice *int, now time.Time) (domain.ExamAnswer, bool, error) {
	tx, err := r.beginWrite(ctx)
	if err != nil {
		return domain.ExamAnswer{}, false, err
	}
	defer func() { _ = tx.Rollback() }()
	s, sub, err := writableSession(ctx, tx, sessionID)
	if err != nil {
		return domain.ExamAnswer{}, false, err
	}
	switch domain.ExamState(s, sub, now) {
	case domain.ExamSubmitted:
		return domain.ExamAnswer{}, false, domain.ErrExamClosed
	case domain.ExamExpired:
		return domain.ExamAnswer{}, false, domain.ErrExamExpired
	}
	cur, err := currentAnswers(ctx, tx, sessionID)
	if err != nil {
		return domain.ExamAnswer{}, false, err
	}
	if a, ok := cur[position]; ok && sameChoice(a.Choice, choice) {
		return a, false, nil
	}
	if !hasAnswer(cur, position) && choice == nil {
		return domain.ExamAnswer{Position: position}, false, nil
	}
	var c any
	if choice != nil {
		c = *choice
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO exam_answers (session_id, position, choice, saved_at) VALUES (?, ?, ?, ?)`,
		sessionID, position, c, fmtTime(now)); err != nil {
		return domain.ExamAnswer{}, false, fmt.Errorf("insert exam answer: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return domain.ExamAnswer{}, false, err
	}
	return domain.ExamAnswer{Position: position, Choice: choice, SavedAt: now}, true, nil
}

func hasAnswer(m map[int]domain.ExamAnswer, p int) bool { _, found := m[p]; return found }

// Submit merges answers over the current ones and closes the session.
func (r *ExamRepository) Submit(ctx context.Context, sessionID int64, answers map[int]*int, now time.Time) (domain.ExamSubmission, bool, error) {
	tx, err := r.beginWrite(ctx)
	if err != nil {
		return domain.ExamSubmission{}, false, err
	}
	defer func() { _ = tx.Rollback() }()
	s, sub, err := writableSession(ctx, tx, sessionID)
	if err != nil {
		return domain.ExamSubmission{}, false, err
	}
	if err := r.loadItems(ctx, tx, &s); err != nil {
		return domain.ExamSubmission{}, false, err
	}
	cur, err := currentAnswers(ctx, tx, sessionID)
	if err != nil {
		return domain.ExamSubmission{}, false, err
	}
	final := map[int]*int{}
	for p, a := range cur {
		final[p] = a.Choice
	}
	for p, c := range answers {
		final[p] = c
	}
	n := len(s.Items)
	sum := domain.ExamAnswersSHA256(n, final)
	if sub != nil {
		if sub.AnswersSHA256 == sum {
			return *sub, true, nil
		}
		return *sub, false, domain.ErrExamAlreadySubmitted
	}
	if now.After(s.DeadlineAt) {
		return domain.ExamSubmission{}, false, domain.ErrExamExpired
	}
	for p := 1; p <= n; p++ {
		prev, had := cur[p]
		if had && sameChoice(prev.Choice, final[p]) || !had && final[p] == nil {
			continue
		}
		var c any
		if final[p] != nil {
			c = *final[p]
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO exam_answers (session_id, position, choice, saved_at) VALUES (?, ?, ?, ?)`,
			sessionID, p, c, fmtTime(now)); err != nil {
			return domain.ExamSubmission{}, false, fmt.Errorf("insert exam answer: %w", err)
		}
	}
	byKey := map[string]*int{}
	for p := 1; p <= n; p++ {
		byKey[strconv.Itoa(p)] = final[p]
	}
	raw, err := json.Marshal(byKey)
	if err != nil {
		return domain.ExamSubmission{}, false, err
	}
	correct, total := domain.ScoreExam(s.Items, final)
	if _, err := tx.ExecContext(ctx, `INSERT INTO exam_submissions (session_id, answers_json, answers_sha256, correct, total, submitted_at) VALUES (?, ?, ?, ?, ?, ?)`,
		sessionID, string(raw), sum, correct, total, fmtTime(now)); err != nil {
		return domain.ExamSubmission{}, false, fmt.Errorf("insert exam submission: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return domain.ExamSubmission{}, false, err
	}
	out := domain.ExamSubmission{SessionID: sessionID, Answers: map[int]*int{}, AnswersSHA256: sum, Correct: correct, Total: total, SubmittedAt: now}
	for p := 1; p <= n; p++ {
		out.Answers[p] = final[p]
	}
	return out, false, nil
}
