package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// AnalysisRepository is a SQLite-backed domain.AnalysisRepository.
type AnalysisRepository struct {
	db  *sql.DB
	now func() time.Time
}

// compile-time check.
var _ domain.AnalysisRepository = (*AnalysisRepository)(nil)

// NewAnalysisRepository builds a repository over an open database.
func NewAnalysisRepository(db *sql.DB) *AnalysisRepository {
	return &AnalysisRepository{
		db:  db,
		now: func() time.Time { return time.Now().UTC() },
	}
}

// Create appends a new analysis for entryID, assigning the next per-entry
// version. The version lookup and insert run in a single transaction so
// concurrent writers cannot assign duplicate versions. Returns
// domain.ErrNotFound if the entry does not exist.
func (r *AnalysisRepository) Create(ctx context.Context, entryID int64, result domain.AnalysisResult, analyzer string) (*domain.Analysis, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	// Ensure the entry exists before attaching an analysis.
	var exists int
	err = tx.QueryRowContext(ctx, `SELECT 1 FROM learning_entries WHERE id = ?`, entryID).Scan(&exists)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("check entry: %w", err)
	}

	// Next version = current max for this entry + 1 (starts at 1).
	var maxVersion sql.NullInt64
	if err := tx.QueryRowContext(ctx,
		`SELECT MAX(version) FROM entry_analyses WHERE entry_id = ?`, entryID,
	).Scan(&maxVersion); err != nil {
		return nil, fmt.Errorf("read max version: %w", err)
	}
	version := maxVersion.Int64 + 1

	now := r.now()
	ts := now.Format(rfc3339)

	res, err := tx.ExecContext(ctx,
		`INSERT INTO entry_analyses
		   (entry_id, version, category, explanation, confidence, uncertainty, analyzer, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		entryID, version, result.Category, result.Explanation,
		result.Confidence, result.Uncertainty, analyzer, ts,
	)
	if err != nil {
		return nil, fmt.Errorf("insert analysis: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, fmt.Errorf("last insert id: %w", err)
	}

	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}

	return &domain.Analysis{
		ID:          id,
		EntryID:     entryID,
		Version:     version,
		Category:    result.Category,
		Explanation: result.Explanation,
		Confidence:  result.Confidence,
		Uncertainty: result.Uncertainty,
		Analyzer:    analyzer,
		CreatedAt:   now,
	}, nil
}

// ListByEntry returns all analyses for entryID, oldest version first.
func (r *AnalysisRepository) ListByEntry(ctx context.Context, entryID int64) ([]*domain.Analysis, error) {
	rows, err := r.db.QueryContext(ctx,
		`SELECT id, entry_id, version, category, explanation, confidence, uncertainty, analyzer, created_at
		 FROM entry_analyses
		 WHERE entry_id = ?
		 ORDER BY version ASC`, entryID)
	if err != nil {
		return nil, fmt.Errorf("list analyses: %w", err)
	}
	defer rows.Close()

	var out []*domain.Analysis
	for rows.Next() {
		a, err := scanAnalysis(rows)
		if err != nil {
			return nil, fmt.Errorf("scan analysis: %w", err)
		}
		out = append(out, a)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate analyses: %w", err)
	}
	return out, nil
}

func scanAnalysis(s scanner) (*domain.Analysis, error) {
	var (
		a          domain.Analysis
		createdStr string
	)
	if err := s.Scan(&a.ID, &a.EntryID, &a.Version, &a.Category, &a.Explanation,
		&a.Confidence, &a.Uncertainty, &a.Analyzer, &createdStr); err != nil {
		return nil, err
	}
	var err error
	if a.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, fmt.Errorf("parse created_at: %w", err)
	}
	return &a, nil
}
