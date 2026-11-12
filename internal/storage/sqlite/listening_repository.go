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
// Daily Listening receipts (migration 015) are in listening_daily_repository.go.
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
	id, err := insertMaterial(ctx, tx, m, ts)
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

// insertMaterial stores one material. A YouTube material always has its link;
// an authored script has none (the table's CHECK refuses anything else).
func insertMaterial(ctx context.Context, tx *sql.Tx, m domain.ListeningMaterial, ts string) (int64, error) {
	kind := m.SourceKind
	if kind == "" {
		kind = domain.ListeningSourceYouTube
	}
	res, err := tx.ExecContext(ctx,
		`INSERT INTO listening_materials (source_kind, video_id, source_url, pack_script_id, title, created_at) VALUES (?, ?, ?, ?, ?, ?)`,
		kind, nullable(m.VideoID), nullable(m.SourceURL), nullable(m.PackScriptID), m.Title, ts)
	if err != nil {
		return 0, fmt.Errorf("insert listening material: %w", err)
	}
	return res.LastInsertId()
}

func nullable(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// ImportAuthoredScript stores an authored script, its lines as transcript
// version 1 and its authored exercise (revision 1) in one transaction. If the
// pack script is already imported, its CURRENT revision (latest transcript
// version and its authored exercise) and title are compared with the pack:
// equal is a replay (true) and nothing is written; different is
// domain.ErrListeningScriptConflict and nothing is written. A lesson updated
// to the pack's content therefore replays.
func (r *ListeningRepository) ImportAuthoredScript(ctx context.Context, m domain.ListeningMaterial, segments []domain.TranscriptSegment,
	content domain.ListeningExerciseContent, now time.Time) (domain.ListeningMaterial, bool, error) {
	if m.SourceKind != domain.ListeningSourceAuthoredScript || m.PackScriptID == "" || m.VideoID != "" || m.SourceURL != "" {
		return domain.ListeningMaterial{}, false, fmt.Errorf("%w: an authored script has a pack script id and no link", domain.ErrValidation)
	}
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return domain.ListeningMaterial{}, false, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	// Take the write lock first, so two imports cannot both insert.
	if _, err := tx.ExecContext(ctx, `UPDATE listening_materials SET id = id WHERE 0`); err != nil {
		return domain.ListeningMaterial{}, false, fmt.Errorf("take write lock: %w", err)
	}
	rawSegments, err := json.Marshal(segments)
	if err != nil {
		return domain.ListeningMaterial{}, false, err
	}
	rawContent, err := json.Marshal(content)
	if err != nil {
		return domain.ListeningMaterial{}, false, err
	}
	var existingID int64
	switch err := tx.QueryRowContext(ctx, `SELECT id FROM listening_materials WHERE pack_script_id = ?`, m.PackScriptID).Scan(&existingID); {
	case err == nil:
		existing, err := readMaterial(ctx, tx, existingID)
		if err != nil {
			return domain.ListeningMaterial{}, false, err
		}
		current, err := readScriptRevision(ctx, tx, existingID, 0)
		if err != nil {
			return existing, false, fmt.Errorf("read imported script: %w", err)
		}
		fresh, err := domain.ListeningScriptFingerprint(rawSegments, rawContent)
		if err != nil {
			return existing, false, err
		}
		if current.Fingerprint != fresh || existing.Title != m.Title {
			return existing, false, domain.ErrListeningScriptConflict
		}
		return existing, true, tx.Commit()
	case !errors.Is(err, sql.ErrNoRows):
		return domain.ListeningMaterial{}, false, fmt.Errorf("find imported script: %w", err)
	}
	ts := now.UTC().Format(rfc3339)
	id, err := insertMaterial(ctx, tx, m, ts)
	if err != nil {
		return domain.ListeningMaterial{}, false, err
	}
	t, err := insertTranscript(ctx, tx, id, 1, segments, false, ts)
	if err != nil {
		return domain.ListeningMaterial{}, false, err
	}
	if _, err := insertExercise(ctx, tx, domain.ListeningExercise{MaterialID: id, TranscriptID: t.ID, Status: domain.ListeningExerciseCompleted,
		Generator: domain.ListeningAuthoredGenerator, Content: &content}, ts); err != nil {
		return domain.ListeningMaterial{}, false, err
	}
	saved, err := readMaterial(ctx, tx, id)
	if err != nil {
		return domain.ListeningMaterial{}, false, err
	}
	return saved, false, tx.Commit()
}

// CurrentScriptRevision returns an imported script's current revision: its
// latest transcript version with the newest completed authored exercise on it.
// ErrNotFound: unknown material; ErrListeningNotAuthoredScript: not a script.
func (r *ListeningRepository) CurrentScriptRevision(ctx context.Context, materialID int64) (domain.ListeningScriptRevision, error) {
	return r.ScriptRevision(ctx, materialID, 0)
}

// ScriptRevision returns revision n (transcript version n) of an imported
// script, or its current revision when n is 0. ErrNotFound: unknown material
// or revision; ErrListeningNotAuthoredScript: not a script.
func (r *ListeningRepository) ScriptRevision(ctx context.Context, materialID int64, revision int) (domain.ListeningScriptRevision, error) {
	m, err := readMaterial(ctx, r.db, materialID)
	if err != nil {
		return domain.ListeningScriptRevision{}, err
	}
	if !m.IsAuthoredScript() {
		return domain.ListeningScriptRevision{}, domain.ErrListeningNotAuthoredScript
	}
	return readScriptRevision(ctx, r.db, materialID, revision)
}

// ReviseAuthoredScript appends the next revision of an imported script (its
// lines as the next transcript version, no timestamps, and the authored
// exercise on it) in one transaction, under the write lock. It never changes
// an earlier revision. If the current revision already has this content it
// writes nothing and replays it (true): a repeated or concurrent confirmation
// of the same update, or a resend after a lost response, adds one revision at
// most. Otherwise fromRevision must be the current revision, or nothing is
// written and the error is domain.ErrListeningScriptRevisionStale.
func (r *ListeningRepository) ReviseAuthoredScript(ctx context.Context, materialID int64, fromRevision int, segments []domain.TranscriptSegment,
	content domain.ListeningExerciseContent, now time.Time) (domain.ListeningScriptRevision, bool, error) {
	rawSegments, err := json.Marshal(segments)
	if err != nil {
		return domain.ListeningScriptRevision{}, false, err
	}
	rawContent, err := json.Marshal(content)
	if err != nil {
		return domain.ListeningScriptRevision{}, false, err
	}
	target, err := domain.ListeningScriptFingerprint(rawSegments, rawContent)
	if err != nil {
		return domain.ListeningScriptRevision{}, false, err
	}
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return domain.ListeningScriptRevision{}, false, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	// Take the write lock first, so two confirmations cannot both append.
	if _, err := tx.ExecContext(ctx, `UPDATE listening_transcripts SET id = id WHERE 0`); err != nil {
		return domain.ListeningScriptRevision{}, false, fmt.Errorf("take write lock: %w", err)
	}
	m, err := readMaterial(ctx, tx, materialID)
	if err != nil {
		return domain.ListeningScriptRevision{}, false, err
	}
	if !m.IsAuthoredScript() {
		return domain.ListeningScriptRevision{}, false, domain.ErrListeningNotAuthoredScript
	}
	current, err := readScriptRevision(ctx, tx, materialID, 0)
	if err != nil {
		return domain.ListeningScriptRevision{}, false, err
	}
	if current.Fingerprint == target {
		return current, true, tx.Commit()
	}
	if fromRevision != current.Revision {
		return current, false, domain.ErrListeningScriptRevisionStale
	}
	ts := now.UTC().Format(rfc3339)
	t, err := insertTranscript(ctx, tx, materialID, current.Revision+1, segments, false, ts)
	if err != nil {
		return domain.ListeningScriptRevision{}, false, err
	}
	if _, err := insertExercise(ctx, tx, domain.ListeningExercise{MaterialID: materialID, TranscriptID: t.ID, Status: domain.ListeningExerciseCompleted,
		Generator: domain.ListeningAuthoredGenerator, Content: &content}, ts); err != nil {
		return domain.ListeningScriptRevision{}, false, err
	}
	next, err := readScriptRevision(ctx, tx, materialID, t.Version)
	if err != nil {
		return domain.ListeningScriptRevision{}, false, err
	}
	if next.Fingerprint != target {
		return domain.ListeningScriptRevision{}, false, fmt.Errorf("stored revision %d does not read back as written", next.Revision)
	}
	if err := tx.Commit(); err != nil {
		return domain.ListeningScriptRevision{}, false, fmt.Errorf("commit tx: %w", err)
	}
	return next, false, nil
}

// readScriptRevision reads revision n of a script (0: the latest transcript
// version) with the newest completed authored exercise on it, and fingerprints
// the stored JSON exactly as the import comparison reads it.
func readScriptRevision(ctx context.Context, q queryer, materialID int64, revision int) (domain.ListeningScriptRevision, error) {
	var out domain.ListeningScriptRevision
	query := `SELECT t.id, t.segments, e.id, e.content FROM listening_transcripts t
		JOIN listening_exercises e ON e.transcript_id = t.id AND e.material_id = t.material_id
		WHERE t.material_id = ? AND e.generator = ? AND e.status = ? AND t.version = `
	args := []any{materialID, domain.ListeningAuthoredGenerator, domain.ListeningExerciseCompleted}
	if revision == 0 {
		query += `(SELECT MAX(version) FROM listening_transcripts WHERE material_id = ?)`
		args = append(args, materialID)
	} else {
		query += `?`
		args = append(args, revision)
	}
	var transcriptID, exerciseID int64
	var rawSegments, rawContent string
	err := q.QueryRowContext(ctx, query+` ORDER BY e.id DESC LIMIT 1`, args...).Scan(&transcriptID, &rawSegments, &exerciseID, &rawContent)
	if errors.Is(err, sql.ErrNoRows) {
		return out, fmt.Errorf("%w: listening script revision", domain.ErrNotFound)
	}
	if err != nil {
		return out, fmt.Errorf("read script revision: %w", err)
	}
	if out.Fingerprint, err = domain.ListeningScriptFingerprint([]byte(rawSegments), []byte(rawContent)); err != nil {
		return out, err
	}
	if out.Transcript, err = readTranscript(ctx, q, `id = ?`, transcriptID); err != nil {
		return out, err
	}
	if out.Exercise, err = readExercise(ctx, q, `id = ?`, exerciseID); err != nil {
		return out, err
	}
	out.Revision = out.Transcript.Version
	return out, nil
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
	rows, err := r.db.QueryContext(ctx, `SELECT `+materialColumns+` FROM listening_materials ORDER BY id DESC`)
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
	id, err := insertExercise(ctx, r.db, e, r.now().Format(rfc3339))
	if err != nil {
		return domain.ListeningExercise{}, err
	}
	return readExercise(ctx, r.db, `id = ?`, id)
}

func insertExercise(ctx context.Context, x execer, e domain.ListeningExercise, ts string) (int64, error) {
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
	res, err := x.ExecContext(ctx,
		`INSERT INTO listening_exercises (material_id, transcript_id, status, failure_code, generator, content, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?)`,
		e.MaterialID, e.TranscriptID, e.Status, failure, e.Generator, content, ts)
	if err != nil {
		return 0, fmt.Errorf("insert listening exercise: %w", err)
	}
	return res.LastInsertId()
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

const materialColumns = `id, source_kind, video_id, source_url, pack_script_id, title, created_at`

func readMaterial(ctx context.Context, q queryer, id int64) (domain.ListeningMaterial, error) {
	m, err := scanMaterial(q.QueryRowContext(ctx, `SELECT `+materialColumns+` FROM listening_materials WHERE id = ?`, id).Scan)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.ListeningMaterial{}, fmt.Errorf("%w: listening material %d", domain.ErrNotFound, id)
	}
	return m, err
}

// scanMaterial reads one material. video_id and source_url are NULL for an
// authored script, pack_script_id is NULL for YouTube material; NULL reads as "".
func scanMaterial(scan func(...any) error) (domain.ListeningMaterial, error) {
	var m domain.ListeningMaterial
	var videoID, sourceURL, packScriptID sql.NullString
	var created string
	if err := scan(&m.ID, &m.SourceKind, &videoID, &sourceURL, &packScriptID, &m.Title, &created); err != nil {
		return m, err
	}
	m.VideoID, m.SourceURL, m.PackScriptID = videoID.String, sourceURL.String, packScriptID.String
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
