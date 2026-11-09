package sqlite

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// ListeningRepository stores Exam Listening Lesson v1 records in their own
// tables (migration 014). Every row is inserted once and never updated; it
// writes nothing to entries, analyses, Concepts, annotations or admission.
type ListeningRepository struct {
	db  *sql.DB
	now func() time.Time
}

var _ domain.ListeningRepository = (*ListeningRepository)(nil)

// NewListeningRepository builds a repository over an open database.
func NewListeningRepository(db *sql.DB) *ListeningRepository {
	return &ListeningRepository{db: db, now: func() time.Time { return time.Now().UTC() }}
}

type queryer interface {
	QueryRowContext(ctx context.Context, query string, args ...any) *sql.Row
}

// CreateMaterial stores the material and, when given, its first transcript in
// one transaction.
func (r *ListeningRepository) CreateMaterial(ctx context.Context, m domain.ListeningMaterial, segments []domain.TranscriptSegment, hasTimestamps bool) (domain.ListeningMaterial, *domain.ListeningTranscript, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return domain.ListeningMaterial{}, nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	ts := r.now().Format(rfc3339)
	res, err := tx.ExecContext(ctx, `INSERT INTO listening_materials (video_id, source_url, title, created_at) VALUES (?, ?, ?, ?)`,
		m.VideoID, m.SourceURL, m.Title, ts)
	if err != nil {
		return domain.ListeningMaterial{}, nil, fmt.Errorf("insert listening material: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return domain.ListeningMaterial{}, nil, err
	}
	var transcript *domain.ListeningTranscript
	if len(segments) > 0 {
		t, err := insertTranscript(ctx, tx, id, 1, segments, hasTimestamps, ts)
		if err != nil {
			return domain.ListeningMaterial{}, nil, err
		}
		transcript = &t
	}
	saved, err := readMaterial(ctx, tx, id)
	if err != nil {
		return domain.ListeningMaterial{}, nil, err
	}
	if err := tx.Commit(); err != nil {
		return domain.ListeningMaterial{}, nil, fmt.Errorf("commit tx: %w", err)
	}
	return saved, transcript, nil
}

// AddTranscript stores the next transcript version for an existing material.
func (r *ListeningRepository) AddTranscript(ctx context.Context, materialID int64, segments []domain.TranscriptSegment, hasTimestamps bool) (domain.ListeningTranscript, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return domain.ListeningTranscript{}, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	// Take the write lock first, so two additions cannot pick the same version.
	if _, err := tx.ExecContext(ctx, `UPDATE listening_transcripts SET id = id WHERE 0`); err != nil {
		return domain.ListeningTranscript{}, err
	}
	if _, err := readMaterial(ctx, tx, materialID); err != nil {
		return domain.ListeningTranscript{}, err
	}
	var version int
	if err := tx.QueryRowContext(ctx, `SELECT COALESCE(MAX(version), 0) + 1 FROM listening_transcripts WHERE material_id = ?`, materialID).Scan(&version); err != nil {
		return domain.ListeningTranscript{}, err
	}
	t, err := insertTranscript(ctx, tx, materialID, version, segments, hasTimestamps, r.now().Format(rfc3339))
	if err != nil {
		return domain.ListeningTranscript{}, err
	}
	if err := tx.Commit(); err != nil {
		return domain.ListeningTranscript{}, fmt.Errorf("commit tx: %w", err)
	}
	return t, nil
}

func insertTranscript(ctx context.Context, tx *sql.Tx, materialID int64, version int, segments []domain.TranscriptSegment, hasTimestamps bool, ts string) (domain.ListeningTranscript, error) {
	raw, err := json.Marshal(segments)
	if err != nil {
		return domain.ListeningTranscript{}, err
	}
	timed := 0
	if hasTimestamps {
		timed = 1
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO listening_transcripts (material_id, version, segments, has_timestamps, created_at) VALUES (?, ?, ?, ?, ?)`,
		materialID, version, string(raw), timed, ts)
	if err != nil {
		return domain.ListeningTranscript{}, fmt.Errorf("insert listening transcript: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return domain.ListeningTranscript{}, err
	}
	return readTranscript(ctx, tx, `id = ?`, id)
}

// GetMaterial returns one material or domain.ErrNotFound.
func (r *ListeningRepository) GetMaterial(ctx context.Context, id int64) (domain.ListeningMaterial, error) {
	return readMaterial(ctx, r.db, id)
}

// ListMaterials returns every material, newest first.
func (r *ListeningRepository) ListMaterials(ctx context.Context) ([]domain.ListeningMaterial, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT id, video_id, source_url, title, created_at FROM listening_materials ORDER BY id DESC`)
	if err != nil {
		return nil, fmt.Errorf("list listening materials: %w", err)
	}
	defer rows.Close()
	out := []domain.ListeningMaterial{}
	for rows.Next() {
		m, err := scanMaterial(rows.Scan)
		if err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

// LatestTranscript returns the newest transcript version, or nil when none.
func (r *ListeningRepository) LatestTranscript(ctx context.Context, materialID int64) (*domain.ListeningTranscript, error) {
	t, err := readTranscript(ctx, r.db, `material_id = ? ORDER BY version DESC LIMIT 1`, materialID)
	if errors.Is(err, domain.ErrNotFound) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &t, nil
}

// GetTranscript returns one transcript version or domain.ErrNotFound.
func (r *ListeningRepository) GetTranscript(ctx context.Context, id int64) (domain.ListeningTranscript, error) {
	return readTranscript(ctx, r.db, `id = ?`, id)
}

// CreateExercise stores one generation attempt (completed or failed).
func (r *ListeningRepository) CreateExercise(ctx context.Context, e domain.ListeningExercise) (domain.ListeningExercise, error) {
	var content, failure any
	if e.Content != nil {
		raw, err := json.Marshal(e.Content)
		if err != nil {
			return domain.ListeningExercise{}, err
		}
		content = string(raw)
	}
	if e.FailureCode != "" {
		failure = e.FailureCode
	}
	res, err := r.db.ExecContext(ctx,
		`INSERT INTO listening_exercises (material_id, transcript_id, status, failure_code, generator, content, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?)`,
		e.MaterialID, e.TranscriptID, e.Status, failure, e.Generator, content, r.now().Format(rfc3339))
	if err != nil {
		return domain.ListeningExercise{}, fmt.Errorf("insert listening exercise: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return domain.ListeningExercise{}, err
	}
	return readExercise(ctx, r.db, `id = ?`, id)
}

// ListExercises returns a material's exercises, newest first.
func (r *ListeningRepository) ListExercises(ctx context.Context, materialID int64) ([]domain.ListeningExercise, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT `+exerciseColumns+` FROM listening_exercises WHERE material_id = ? ORDER BY id DESC`, materialID)
	if err != nil {
		return nil, fmt.Errorf("list listening exercises: %w", err)
	}
	defer rows.Close()
	out := []domain.ListeningExercise{}
	for rows.Next() {
		e, err := scanExercise(rows.Scan)
		if err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

func readMaterial(ctx context.Context, q queryer, id int64) (domain.ListeningMaterial, error) {
	m, err := scanMaterial(q.QueryRowContext(ctx, `SELECT id, video_id, source_url, title, created_at FROM listening_materials WHERE id = ?`, id).Scan)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.ListeningMaterial{}, fmt.Errorf("%w: listening material %d", domain.ErrNotFound, id)
	}
	return m, err
}

func scanMaterial(scan func(...any) error) (domain.ListeningMaterial, error) {
	var m domain.ListeningMaterial
	var created string
	if err := scan(&m.ID, &m.VideoID, &m.SourceURL, &m.Title, &created); err != nil {
		return m, err
	}
	m.CreatedAt, _ = time.Parse(rfc3339, created)
	return m, nil
}

func readTranscript(ctx context.Context, q queryer, where string, args ...any) (domain.ListeningTranscript, error) {
	var t domain.ListeningTranscript
	var raw, created string
	var timed int
	err := q.QueryRowContext(ctx, `SELECT id, material_id, version, segments, has_timestamps, created_at FROM listening_transcripts WHERE `+where, args...).
		Scan(&t.ID, &t.MaterialID, &t.Version, &raw, &timed, &created)
	if errors.Is(err, sql.ErrNoRows) {
		return t, fmt.Errorf("%w: listening transcript", domain.ErrNotFound)
	}
	if err != nil {
		return t, err
	}
	if err := json.Unmarshal([]byte(raw), &t.Segments); err != nil {
		return t, fmt.Errorf("decode transcript %d: %w", t.ID, err)
	}
	t.HasTimestamps = timed == 1
	t.CreatedAt, _ = time.Parse(rfc3339, created)
	return t, nil
}

const exerciseColumns = `id, material_id, transcript_id, status, failure_code, generator, content, created_at`

func readExercise(ctx context.Context, q queryer, where string, args ...any) (domain.ListeningExercise, error) {
	e, err := scanExercise(q.QueryRowContext(ctx, `SELECT `+exerciseColumns+` FROM listening_exercises WHERE `+where, args...).Scan)
	if errors.Is(err, sql.ErrNoRows) {
		return e, fmt.Errorf("%w: listening exercise", domain.ErrNotFound)
	}
	return e, err
}

func scanExercise(scan func(...any) error) (domain.ListeningExercise, error) {
	var e domain.ListeningExercise
	var failure, content sql.NullString
	var created string
	if err := scan(&e.ID, &e.MaterialID, &e.TranscriptID, &e.Status, &failure, &e.Generator, &content, &created); err != nil {
		return e, err
	}
	e.FailureCode = failure.String
	if content.Valid {
		var c domain.ListeningExerciseContent
		if err := json.Unmarshal([]byte(content.String), &c); err != nil {
			return e, fmt.Errorf("decode exercise %d: %w", e.ID, err)
		}
		e.Content = &c
	}
	e.CreatedAt, _ = time.Parse(rfc3339, created)
	return e, nil
}
