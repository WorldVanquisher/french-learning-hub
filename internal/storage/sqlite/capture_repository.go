package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"

	"french-learning-app/internal/domain"
)

// CaptureRepository is a SQLite-backed domain.CaptureRepository. It performs the
// atomic import of a structured capture (entry + optional version-1 analysis +
// receipt) in a single transaction and enforces idempotency / conflict semantics
// on capture_id. All SQL for captures lives here.
type CaptureRepository struct {
	db  *sql.DB
	now func() time.Time
}

// compile-time check.
var _ domain.CaptureRepository = (*CaptureRepository)(nil)

// NewCaptureRepository builds a repository over an open database.
func NewCaptureRepository(db *sql.DB) *CaptureRepository {
	return &CaptureRepository{
		db:  db,
		now: func() time.Time { return time.Now().UTC() },
	}
}

// Create atomically persists a new capture or resolves a repeat submission.
//
// A previously unseen capture_id inserts the learning entry, the optional
// version-1 analysis with server-constructed provenance, and the capture receipt
// — all in one transaction, rolled back entirely on any failure. A repeat with
// an identical content fingerprint returns the existing result (Created=false)
// without writing. A repeat with a different fingerprint returns
// domain.ErrConflict and modifies nothing.
//
// Concurrency: the capture_id UNIQUE constraint is the source of truth. If a
// concurrent writer wins the race between the in-transaction existence check and
// the receipt insert, the insert fails on the constraint; we then reload the
// now-existing capture and resolve it as a replay or a conflict. This never
// relies on the read alone.
func (r *CaptureRepository) Create(ctx context.Context, in domain.PreparedLearningCapture) (domain.LearningCaptureResult, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return domain.LearningCaptureResult{}, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	// Fast path: capture already present? Resolve without writing.
	existing, err := getCaptureTx(ctx, tx, in.CaptureID)
	if err != nil && !errors.Is(err, domain.ErrNotFound) {
		return domain.LearningCaptureResult{}, err
	}
	if existing != nil {
		return resolveRepeat(ctx, tx, in.CaptureID, in.ContentFingerprint)
	}

	result, err := r.insertCapture(ctx, tx, in)
	if err != nil {
		// A uniqueness race: someone inserted this capture_id after our check.
		// Roll back our partial work and resolve against the committed row.
		if isUniqueViolation(err) {
			_ = tx.Rollback()
			return r.resolveRepeatFresh(ctx, in.CaptureID, in.ContentFingerprint)
		}
		return domain.LearningCaptureResult{}, err
	}

	if err := tx.Commit(); err != nil {
		return domain.LearningCaptureResult{}, fmt.Errorf("commit tx: %w", err)
	}
	return result, nil
}

// insertCapture writes the entry, optional analysis, and receipt inside tx.
func (r *CaptureRepository) insertCapture(ctx context.Context, tx *sql.Tx, in domain.PreparedLearningCapture) (domain.LearningCaptureResult, error) {
	now := r.now()
	ts := now.Format(rfc3339)

	// 1. Learning entry (original data is the source of truth).
	entryRes, err := tx.ExecContext(ctx,
		`INSERT INTO learning_entries (original_input, original_context, created_at, updated_at)
		 VALUES (?, ?, ?, ?)`,
		in.OriginalInput, in.OriginalContext, ts, ts,
	)
	if err != nil {
		return domain.LearningCaptureResult{}, fmt.Errorf("insert entry: %w", err)
	}
	entryID, err := entryRes.LastInsertId()
	if err != nil {
		return domain.LearningCaptureResult{}, fmt.Errorf("entry last insert id: %w", err)
	}

	// 2. Optional imported analysis, always version 1 for a new entry.
	var analysisID *int64
	if in.Analysis != nil {
		aRes, err := tx.ExecContext(ctx,
			`INSERT INTO entry_analyses
			   (entry_id, version, category, explanation, confidence, uncertainty, analyzer, created_at)
			 VALUES (?, 1, ?, ?, ?, ?, ?, ?)`,
			entryID, in.Analysis.Category, in.Analysis.Explanation,
			in.Analysis.Confidence, in.Analysis.Uncertainty, in.AnalyzerProvenance, ts,
		)
		if err != nil {
			return domain.LearningCaptureResult{}, fmt.Errorf("insert analysis: %w", err)
		}
		aID, err := aRes.LastInsertId()
		if err != nil {
			return domain.LearningCaptureResult{}, fmt.Errorf("analysis last insert id: %w", err)
		}
		analysisID = &aID
	}

	// 3. Capture receipt (references entry + optional analysis; never duplicates
	//    their content). The capture_id UNIQUE constraint enforces idempotency.
	_, err = tx.ExecContext(ctx,
		`INSERT INTO learning_captures
		   (capture_id, entry_id, analysis_id, source, schema_version, discussion_summary, content_fingerprint, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		in.CaptureID, entryID, nullInt64(analysisID), string(in.Source),
		in.SchemaVersion, in.DiscussionSummary, in.ContentFingerprint, ts,
	)
	if err != nil {
		return domain.LearningCaptureResult{}, fmt.Errorf("insert capture: %w", err)
	}

	return domain.LearningCaptureResult{
		CaptureID:  in.CaptureID,
		EntryID:    entryID,
		AnalysisID: analysisID,
		Created:    true,
	}, nil
}

// resolveRepeat compares the incoming fingerprint against the existing capture
// (read within tx) and returns a replay result or ErrConflict.
func resolveRepeat(ctx context.Context, tx *sql.Tx, captureID, fingerprint string) (domain.LearningCaptureResult, error) {
	stored, storedFP, err := getCaptureWithFingerprintTx(ctx, tx, captureID)
	if err != nil {
		return domain.LearningCaptureResult{}, err
	}
	if storedFP != fingerprint {
		return domain.LearningCaptureResult{}, domain.ErrConflict
	}
	return domain.LearningCaptureResult{
		CaptureID:  stored.CaptureID,
		EntryID:    stored.EntryID,
		AnalysisID: stored.AnalysisID,
		Created:    false,
	}, nil
}

// resolveRepeatFresh resolves a repeat against the committed row using a fresh
// read, used after a uniqueness race rolled back the current transaction.
func (r *CaptureRepository) resolveRepeatFresh(ctx context.Context, captureID, fingerprint string) (domain.LearningCaptureResult, error) {
	stored, err := r.GetByCaptureID(ctx, captureID)
	if err != nil {
		return domain.LearningCaptureResult{}, err
	}
	storedFP, err := r.fingerprintOf(ctx, captureID)
	if err != nil {
		return domain.LearningCaptureResult{}, err
	}
	if storedFP != fingerprint {
		return domain.LearningCaptureResult{}, domain.ErrConflict
	}
	return domain.LearningCaptureResult{
		CaptureID:  stored.CaptureID,
		EntryID:    stored.EntryID,
		AnalysisID: stored.AnalysisID,
		Created:    false,
	}, nil
}

// GetByCaptureID returns the stored capture receipt, or domain.ErrNotFound. The
// content fingerprint is intentionally not part of the returned model.
func (r *CaptureRepository) GetByCaptureID(ctx context.Context, captureID string) (*domain.LearningCapture, error) {
	row := r.db.QueryRowContext(ctx,
		`SELECT id, capture_id, entry_id, analysis_id, source, schema_version, discussion_summary, created_at
		 FROM learning_captures WHERE capture_id = ?`, captureID)
	c, err := scanCapture(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get capture: %w", err)
	}
	return c, nil
}

// fingerprintOf reads only the stored fingerprint for a capture_id. It stays in
// the storage layer so the internal fingerprint never leaves this package except
// as an equality decision.
func (r *CaptureRepository) fingerprintOf(ctx context.Context, captureID string) (string, error) {
	var fp string
	err := r.db.QueryRowContext(ctx,
		`SELECT content_fingerprint FROM learning_captures WHERE capture_id = ?`, captureID).Scan(&fp)
	if errors.Is(err, sql.ErrNoRows) {
		return "", domain.ErrNotFound
	}
	if err != nil {
		return "", fmt.Errorf("get fingerprint: %w", err)
	}
	return fp, nil
}

// getCaptureTx reads a capture within a transaction, returning ErrNotFound when
// absent.
func getCaptureTx(ctx context.Context, tx *sql.Tx, captureID string) (*domain.LearningCapture, error) {
	row := tx.QueryRowContext(ctx,
		`SELECT id, capture_id, entry_id, analysis_id, source, schema_version, discussion_summary, created_at
		 FROM learning_captures WHERE capture_id = ?`, captureID)
	c, err := scanCapture(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get capture (tx): %w", err)
	}
	return c, nil
}

// getCaptureWithFingerprintTx reads a capture and its stored fingerprint within
// a transaction.
func getCaptureWithFingerprintTx(ctx context.Context, tx *sql.Tx, captureID string) (*domain.LearningCapture, string, error) {
	row := tx.QueryRowContext(ctx,
		`SELECT id, capture_id, entry_id, analysis_id, source, schema_version, discussion_summary, created_at, content_fingerprint
		 FROM learning_captures WHERE capture_id = ?`, captureID)
	var (
		c           domain.LearningCapture
		analysisID  sql.NullInt64
		source      string
		createdStr  string
		fingerprint string
	)
	if err := row.Scan(&c.ID, &c.CaptureID, &c.EntryID, &analysisID, &source,
		&c.SchemaVersion, &c.DiscussionSummary, &createdStr, &fingerprint); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, "", domain.ErrNotFound
		}
		return nil, "", fmt.Errorf("get capture+fp (tx): %w", err)
	}
	if analysisID.Valid {
		c.AnalysisID = &analysisID.Int64
	}
	c.Source = domain.CaptureSource(source)
	var err error
	if c.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, "", fmt.Errorf("parse created_at: %w", err)
	}
	return &c, fingerprint, nil
}

// scanCapture scans a capture row (without the fingerprint).
func scanCapture(s scanner) (*domain.LearningCapture, error) {
	var (
		c          domain.LearningCapture
		analysisID sql.NullInt64
		source     string
		createdStr string
	)
	if err := s.Scan(&c.ID, &c.CaptureID, &c.EntryID, &analysisID, &source,
		&c.SchemaVersion, &c.DiscussionSummary, &createdStr); err != nil {
		return nil, err
	}
	if analysisID.Valid {
		c.AnalysisID = &analysisID.Int64
	}
	c.Source = domain.CaptureSource(source)
	var err error
	if c.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, fmt.Errorf("parse created_at: %w", err)
	}
	return &c, nil
}

// nullInt64 converts an optional int64 to a sql-friendly nullable value.
func nullInt64(p *int64) any {
	if p == nil {
		return nil
	}
	return *p
}

// isUniqueViolation reports whether err is a SQLite UNIQUE constraint failure.
// The driver surfaces this as a message containing "UNIQUE constraint failed";
// matching it keeps the driver-specific detail inside the storage package.
func isUniqueViolation(err error) bool {
	return err != nil && strings.Contains(err.Error(), "UNIQUE constraint failed")
}
