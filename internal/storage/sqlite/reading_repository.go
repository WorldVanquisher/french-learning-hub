package sqlite

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// ReadingRepository stores Exam Reading v1 records (migration 016). Lessons,
// passages and exercises are inserted once and never updated; a preparation
// attempt is inserted before the provider call and finished once, with the
// start rules applied inside one write transaction (as in Daily Listening).
// It writes nothing to entries, analyses, Concepts, annotations or admission.
type ReadingRepository struct {
	db *sql.DB
}

var _ domain.ReadingRepository = (*ReadingRepository)(nil)

// NewReadingRepository builds a repository over an open database.
func NewReadingRepository(db *sql.DB) *ReadingRepository { return &ReadingRepository{db: db} }

func (r *ReadingRepository) beginWrite(ctx context.Context, table string) (*sql.Tx, error) {
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

const readingLessonColumns = `id, title, source_url, origin, pack_passage_id, created_at`

func readReadingLesson(ctx context.Context, q queryer, where string, args ...any) (domain.ReadingLesson, error) {
	var l domain.ReadingLesson
	var src, pack sql.NullString
	var created string
	err := q.QueryRowContext(ctx, `SELECT `+readingLessonColumns+` FROM reading_lessons WHERE `+where, args...).
		Scan(&l.ID, &l.Title, &src, &l.Origin, &pack, &created)
	if errors.Is(err, sql.ErrNoRows) {
		return l, fmt.Errorf("%w: reading lesson", domain.ErrNotFound)
	}
	if err != nil {
		return l, err
	}
	l.SourceURL, l.PackPassageID, l.CreatedAt = src.String, pack.String, parseTime(created)
	return l, nil
}

func readReadingPassage(ctx context.Context, q queryer, where string, args ...any) (domain.ReadingPassage, error) {
	var p domain.ReadingPassage
	var raw, created string
	err := q.QueryRowContext(ctx, `SELECT id, lesson_id, version, segments, created_at FROM reading_passages WHERE `+where, args...).
		Scan(&p.ID, &p.LessonID, &p.Version, &raw, &created)
	if errors.Is(err, sql.ErrNoRows) {
		return p, fmt.Errorf("%w: reading passage", domain.ErrNotFound)
	}
	if err != nil {
		return p, err
	}
	if err := json.Unmarshal([]byte(raw), &p.Segments); err != nil {
		return p, fmt.Errorf("decode passage %d: %w", p.ID, err)
	}
	p.CreatedAt = parseTime(created)
	return p, nil
}

func insertReadingPassage(ctx context.Context, tx *sql.Tx, lessonID int64, version int, segments []domain.ReadingSegment, ts string) (domain.ReadingPassage, error) {
	raw, err := json.Marshal(segments)
	if err != nil {
		return domain.ReadingPassage{}, err
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO reading_passages (lesson_id, version, segments, created_at) VALUES (?, ?, ?, ?)`, lessonID, version, string(raw), ts)
	if err != nil {
		return domain.ReadingPassage{}, fmt.Errorf("insert reading passage: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return domain.ReadingPassage{}, err
	}
	return readReadingPassage(ctx, tx, `id = ?`, id)
}

func insertReadingLesson(ctx context.Context, tx *sql.Tx, l domain.ReadingLesson, ts string) (int64, error) {
	var src, pack any
	if l.SourceURL != "" {
		src = l.SourceURL
	}
	if l.PackPassageID != "" {
		pack = l.PackPassageID
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO reading_lessons (title, source_url, origin, pack_passage_id, created_at) VALUES (?, ?, ?, ?, ?)`,
		l.Title, src, l.Origin, pack, ts)
	if err != nil {
		return 0, fmt.Errorf("insert reading lesson: %w", err)
	}
	return res.LastInsertId()
}

func (r *ReadingRepository) CreateLesson(ctx context.Context, l domain.ReadingLesson, segments []domain.ReadingSegment, now time.Time) (domain.ReadingLesson, domain.ReadingPassage, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return domain.ReadingLesson{}, domain.ReadingPassage{}, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	ts := fmtTime(now)
	id, err := insertReadingLesson(ctx, tx, l, ts)
	if err != nil {
		return domain.ReadingLesson{}, domain.ReadingPassage{}, err
	}
	p, err := insertReadingPassage(ctx, tx, id, 1, segments, ts)
	if err != nil {
		return domain.ReadingLesson{}, domain.ReadingPassage{}, err
	}
	saved, err := readReadingLesson(ctx, tx, `id = ?`, id)
	if err != nil {
		return saved, p, err
	}
	return saved, p, tx.Commit()
}

func (r *ReadingRepository) AddPassage(ctx context.Context, lessonID int64, segments []domain.ReadingSegment, now time.Time) (domain.ReadingPassage, error) {
	tx, err := r.beginWrite(ctx, "reading_passages")
	if err != nil {
		return domain.ReadingPassage{}, err
	}
	defer func() { _ = tx.Rollback() }()
	l, err := readReadingLesson(ctx, tx, `id = ?`, lessonID)
	if err != nil {
		return domain.ReadingPassage{}, err
	}
	if l.Origin == domain.ReadingOriginAuthored {
		return domain.ReadingPassage{}, fmt.Errorf("%w: an authored example's text cannot be changed; save it as your own lesson", domain.ErrValidation)
	}
	var version int
	if err := tx.QueryRowContext(ctx, `SELECT COALESCE(MAX(version), 0) + 1 FROM reading_passages WHERE lesson_id = ?`, lessonID).Scan(&version); err != nil {
		return domain.ReadingPassage{}, err
	}
	p, err := insertReadingPassage(ctx, tx, lessonID, version, segments, fmtTime(now))
	if err != nil {
		return p, err
	}
	return p, tx.Commit()
}

func (r *ReadingRepository) ImportAuthored(ctx context.Context, l domain.ReadingLesson, segments []domain.ReadingSegment, content domain.ReadingExerciseContent, now time.Time) (domain.ReadingLesson, bool, error) {
	tx, err := r.beginWrite(ctx, "reading_lessons")
	if err != nil {
		return domain.ReadingLesson{}, false, err
	}
	defer func() { _ = tx.Rollback() }()
	rawContent, err := json.Marshal(content)
	if err != nil {
		return domain.ReadingLesson{}, false, err
	}
	rawSegments, err := json.Marshal(segments)
	if err != nil {
		return domain.ReadingLesson{}, false, err
	}
	if existing, err := readReadingLesson(ctx, tx, `pack_passage_id = ?`, l.PackPassageID); err == nil {
		var storedSegments, storedContent string
		if err := tx.QueryRowContext(ctx, `SELECT p.segments, e.content FROM reading_passages p JOIN reading_exercises e ON e.passage_id = p.id
			WHERE p.lesson_id = ? AND p.version = 1 AND e.generator = ? ORDER BY e.id LIMIT 1`, existing.ID, domain.ReadingAuthoredGenerator).
			Scan(&storedSegments, &storedContent); err != nil {
			return existing, false, fmt.Errorf("read imported example: %w", err)
		}
		if !jsonEqual(storedSegments, rawSegments) || !jsonEqual(storedContent, rawContent) || existing.Title != l.Title {
			return existing, false, domain.ErrReadingPackConflict
		}
		return existing, true, tx.Commit()
	} else if !errors.Is(err, domain.ErrNotFound) {
		return domain.ReadingLesson{}, false, err
	}
	ts := fmtTime(now)
	id, err := insertReadingLesson(ctx, tx, l, ts)
	if err != nil {
		return domain.ReadingLesson{}, false, err
	}
	p, err := insertReadingPassage(ctx, tx, id, 1, segments, ts)
	if err != nil {
		return domain.ReadingLesson{}, false, err
	}
	if _, err := insertReadingExercise(ctx, tx, domain.ReadingExercise{LessonID: id, PassageID: p.ID, Status: domain.ListeningExerciseCompleted,
		Generator: domain.ReadingAuthoredGenerator, Content: &content}, ts); err != nil {
		return domain.ReadingLesson{}, false, err
	}
	saved, err := readReadingLesson(ctx, tx, `id = ?`, id)
	if err != nil {
		return saved, false, err
	}
	return saved, false, tx.Commit()
}

func jsonEqual(stored string, fresh []byte) bool {
	var a, b any
	if json.Unmarshal([]byte(stored), &a) != nil || json.Unmarshal(fresh, &b) != nil {
		return false
	}
	x, _ := json.Marshal(a)
	y, _ := json.Marshal(b)
	return bytes.Equal(x, y)
}

func (r *ReadingRepository) GetLesson(ctx context.Context, id int64) (domain.ReadingLesson, error) {
	return readReadingLesson(ctx, r.db, `id = ?`, id)
}

func (r *ReadingRepository) ListLessons(ctx context.Context) ([]domain.ReadingLesson, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT id FROM reading_lessons ORDER BY id DESC`)
	if err != nil {
		return nil, err
	}
	ids, err := scanIDs(rows)
	if err != nil {
		return nil, err
	}
	out := []domain.ReadingLesson{}
	for _, id := range ids {
		l, err := r.GetLesson(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, l)
	}
	return out, nil
}

func (r *ReadingRepository) LatestPassage(ctx context.Context, lessonID int64) (domain.ReadingPassage, error) {
	return readReadingPassage(ctx, r.db, `lesson_id = ? ORDER BY version DESC LIMIT 1`, lessonID)
}

func (r *ReadingRepository) ListPassages(ctx context.Context, lessonID int64) ([]domain.ReadingPassage, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT id FROM reading_passages WHERE lesson_id = ? ORDER BY version DESC`, lessonID)
	if err != nil {
		return nil, err
	}
	ids, err := scanIDs(rows)
	if err != nil {
		return nil, err
	}
	out := []domain.ReadingPassage{}
	for _, id := range ids {
		p, err := readReadingPassage(ctx, r.db, `id = ?`, id)
		if err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, nil
}

const readingExerciseColumns = `id, lesson_id, passage_id, status, failure_code, generator, content, created_at`

func readReadingExercise(ctx context.Context, q queryer, where string, args ...any) (domain.ReadingExercise, error) {
	var e domain.ReadingExercise
	var failure, content sql.NullString
	var created string
	err := q.QueryRowContext(ctx, `SELECT `+readingExerciseColumns+` FROM reading_exercises WHERE `+where, args...).
		Scan(&e.ID, &e.LessonID, &e.PassageID, &e.Status, &failure, &e.Generator, &content, &created)
	if errors.Is(err, sql.ErrNoRows) {
		return e, fmt.Errorf("%w: reading exercise", domain.ErrNotFound)
	}
	if err != nil {
		return e, err
	}
	e.FailureCode, e.CreatedAt = failure.String, parseTime(created)
	if content.Valid {
		var c domain.ReadingExerciseContent
		if err := json.Unmarshal([]byte(content.String), &c); err != nil {
			return e, fmt.Errorf("decode reading exercise %d: %w", e.ID, err)
		}
		e.Content = &c
	}
	return e, nil
}

func insertReadingExercise(ctx context.Context, x execer, e domain.ReadingExercise, ts string) (int64, error) {
	var content, failure any
	if e.Content != nil {
		raw, err := json.Marshal(e.Content)
		if err != nil {
			return 0, err
		}
		content = string(raw)
	}
	if e.FailureCode != "" {
		failure = e.FailureCode
	}
	res, err := x.ExecContext(ctx, `INSERT INTO reading_exercises (lesson_id, passage_id, status, failure_code, generator, content, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?)`, e.LessonID, e.PassageID, e.Status, failure, e.Generator, content, ts)
	if err != nil {
		return 0, fmt.Errorf("insert reading exercise: %w", err)
	}
	return res.LastInsertId()
}

func (r *ReadingRepository) ListExercises(ctx context.Context, lessonID int64) ([]domain.ReadingExercise, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT id FROM reading_exercises WHERE lesson_id = ? ORDER BY id DESC`, lessonID)
	if err != nil {
		return nil, err
	}
	ids, err := scanIDs(rows)
	if err != nil {
		return nil, err
	}
	out := []domain.ReadingExercise{}
	for _, id := range ids {
		e, err := r.GetExercise(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, nil
}

func (r *ReadingRepository) GetExercise(ctx context.Context, id int64) (domain.ReadingExercise, error) {
	return readReadingExercise(ctx, r.db, `id = ?`, id)
}

const readingPreparationColumns = `id, operation_id, lesson_id, passage_id, after_unknown, started_at, deadline_at, finished_at, outcome, exercise_id`

func readReadingPreparation(ctx context.Context, q queryer, where string, args ...any) (domain.ReadingPreparation, error) {
	var p domain.ReadingPreparation
	var after int
	var started, deadline string
	var finished, outcome sql.NullString
	var exercise sql.NullInt64
	err := q.QueryRowContext(ctx, `SELECT `+readingPreparationColumns+` FROM reading_preparations WHERE `+where, args...).
		Scan(&p.ID, &p.OperationID, &p.LessonID, &p.PassageID, &after, &started, &deadline, &finished, &outcome, &exercise)
	if errors.Is(err, sql.ErrNoRows) {
		return p, fmt.Errorf("%w: reading preparation", domain.ErrNotFound)
	}
	if err != nil {
		return p, err
	}
	p.AfterUnknown, p.StartedAt, p.DeadlineAt, p.FinishedAt = after == 1, parseTime(started), parseTime(deadline), parseNullTime(finished)
	p.Outcome, p.ExerciseID = outcome.String, nullInt(exercise)
	return p, nil
}

func (r *ReadingRepository) StartPreparation(ctx context.Context, in domain.NewReadingPreparation) (domain.ReadingPreparation, *domain.ReadingPassage, bool, error) {
	var none domain.ReadingPreparation
	tx, err := r.beginWrite(ctx, "reading_preparations")
	if err != nil {
		return none, nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if p, err := readReadingPreparation(ctx, tx, `operation_id = ?`, in.OperationID); err == nil {
		if p.LessonID != in.LessonID {
			return none, nil, false, domain.ErrReadingOperationConflict
		}
		passage, err := readReadingPassage(ctx, tx, `id = ?`, p.PassageID)
		if err != nil {
			return none, nil, false, err
		}
		return p, &passage, true, tx.Commit()
	} else if !errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, err
	}
	if _, err := readReadingLesson(ctx, tx, `id = ?`, in.LessonID); err != nil {
		return none, nil, false, err
	}
	passage, err := readReadingPassage(ctx, tx, `lesson_id = ? ORDER BY version DESC LIMIT 1`, in.LessonID)
	if err != nil {
		return none, nil, false, err
	}
	afterUnknown := false
	if latest, err := readReadingPreparation(ctx, tx, `lesson_id = ? ORDER BY id DESC LIMIT 1`, in.LessonID); err == nil {
		switch latest.State(in.Now) {
		case domain.ListeningStateInProgress:
			return latest, nil, false, domain.ErrReadingPreparationInProgress
		case domain.ListeningOutcomeUnknown:
			if !in.ConfirmUnknownRetry {
				return latest, nil, false, domain.ErrReadingOutcomeUnknown
			}
			afterUnknown = true
		}
	} else if !errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, err
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO reading_preparations (operation_id, lesson_id, passage_id, after_unknown, started_at, deadline_at)
		VALUES (?, ?, ?, ?, ?, ?)`, in.OperationID, in.LessonID, passage.ID, boolInt(afterUnknown), fmtTime(in.Now), fmtTime(in.Deadline))
	if err != nil {
		return none, nil, false, fmt.Errorf("insert reading preparation: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return none, nil, false, err
	}
	p, err := readReadingPreparation(ctx, tx, `id = ?`, id)
	if err != nil {
		return none, nil, false, err
	}
	return p, &passage, false, tx.Commit()
}

func (r *ReadingRepository) FinishPreparation(ctx context.Context, id int64, outcome string, e domain.ReadingExercise, now time.Time) (domain.ReadingPreparation, domain.ReadingExercise, error) {
	tx, err := r.beginWrite(ctx, "reading_preparations")
	if err != nil {
		return domain.ReadingPreparation{}, domain.ReadingExercise{}, err
	}
	defer func() { _ = tx.Rollback() }()
	exerciseID, err := insertReadingExercise(ctx, tx, e, fmtTime(now))
	if err != nil {
		return domain.ReadingPreparation{}, domain.ReadingExercise{}, err
	}
	res, err := tx.ExecContext(ctx, `UPDATE reading_preparations SET outcome = ?, finished_at = ?, exercise_id = ? WHERE id = ? AND finished_at IS NULL`,
		outcome, fmtTime(now), exerciseID, id)
	if err != nil {
		return domain.ReadingPreparation{}, domain.ReadingExercise{}, fmt.Errorf("finish reading preparation: %w", err)
	}
	if n, _ := res.RowsAffected(); n != 1 {
		return domain.ReadingPreparation{}, domain.ReadingExercise{}, fmt.Errorf("reading preparation %d is not pending", id)
	}
	p, err := readReadingPreparation(ctx, tx, `id = ?`, id)
	if err != nil {
		return p, domain.ReadingExercise{}, err
	}
	stored, err := readReadingExercise(ctx, tx, `id = ?`, exerciseID)
	if err != nil {
		return p, stored, err
	}
	return p, stored, tx.Commit()
}

func (r *ReadingRepository) GetPreparationByOperation(ctx context.Context, operationID string) (domain.ReadingPreparation, error) {
	return readReadingPreparation(ctx, r.db, `operation_id = ?`, operationID)
}

func (r *ReadingRepository) ListPreparations(ctx context.Context, lessonID int64) ([]domain.ReadingPreparation, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT id FROM reading_preparations WHERE lesson_id = ? ORDER BY id DESC`, lessonID)
	if err != nil {
		return nil, err
	}
	ids, err := scanIDs(rows)
	if err != nil {
		return nil, err
	}
	out := []domain.ReadingPreparation{}
	for _, id := range ids {
		p, err := readReadingPreparation(ctx, r.db, `id = ?`, id)
		if err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, nil
}
