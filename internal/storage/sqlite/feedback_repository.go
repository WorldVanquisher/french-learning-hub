package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// FeedbackRepository is a SQLite-backed domain.FeedbackRepository.
type FeedbackRepository struct {
	db  *sql.DB
	now func() time.Time
}

// compile-time check.
var _ domain.FeedbackRepository = (*FeedbackRepository)(nil)

// NewFeedbackRepository builds a repository over an open database.
func NewFeedbackRepository(db *sql.DB) *FeedbackRepository {
	return &FeedbackRepository{
		db:  db,
		now: func() time.Time { return time.Now().UTC() },
	}
}

// Create appends a feedback record for analysisID. The analysis existence check
// and insert run in one transaction. Returns domain.ErrNotFound if the analysis
// does not exist. The referenced analysis is never modified.
func (r *FeedbackRepository) Create(ctx context.Context, analysisID int64, in domain.NewFeedbackInput) (*domain.Feedback, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if err := analysisExists(ctx, tx, analysisID); err != nil {
		return nil, err
	}

	now := r.now()
	ts := now.Format(rfc3339)

	res, err := tx.ExecContext(ctx,
		`INSERT INTO analysis_feedback
		   (analysis_id, status, corrected_category, corrected_explanation, user_note, created_at)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		analysisID, string(in.Status),
		nullString(in.CorrectedCategory), nullString(in.CorrectedExplanation),
		in.UserNote, ts,
	)
	if err != nil {
		return nil, fmt.Errorf("insert feedback: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, fmt.Errorf("last insert id: %w", err)
	}

	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit tx: %w", err)
	}

	return &domain.Feedback{
		ID:                   id,
		AnalysisID:           analysisID,
		Status:               in.Status,
		CorrectedCategory:    in.CorrectedCategory,
		CorrectedExplanation: in.CorrectedExplanation,
		UserNote:             in.UserNote,
		CreatedAt:            now,
	}, nil
}

// ListByAnalysis returns all feedback for analysisID, oldest first. Returns
// domain.ErrNotFound if the analysis does not exist.
func (r *FeedbackRepository) ListByAnalysis(ctx context.Context, analysisID int64) ([]*domain.Feedback, error) {
	if err := analysisExists(ctx, r.db, analysisID); err != nil {
		return nil, err
	}

	rows, err := r.db.QueryContext(ctx,
		`SELECT id, analysis_id, status, corrected_category, corrected_explanation, user_note, created_at
		 FROM analysis_feedback
		 WHERE analysis_id = ?
		 ORDER BY id ASC`, analysisID)
	if err != nil {
		return nil, fmt.Errorf("list feedback: %w", err)
	}
	defer rows.Close()

	var out []*domain.Feedback
	for rows.Next() {
		f, err := scanFeedback(rows)
		if err != nil {
			return nil, fmt.Errorf("scan feedback: %w", err)
		}
		out = append(out, f)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate feedback: %w", err)
	}
	return out, nil
}

// querier is satisfied by both *sql.DB and *sql.Tx.
type querier interface {
	QueryRowContext(ctx context.Context, query string, args ...any) *sql.Row
}

func analysisExists(ctx context.Context, q querier, analysisID int64) error {
	var exists int
	err := q.QueryRowContext(ctx, `SELECT 1 FROM entry_analyses WHERE id = ?`, analysisID).Scan(&exists)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.ErrNotFound
	}
	if err != nil {
		return fmt.Errorf("check analysis: %w", err)
	}
	return nil
}

func scanFeedback(s scanner) (*domain.Feedback, error) {
	var (
		f          domain.Feedback
		status     string
		category   sql.NullString
		expl       sql.NullString
		createdStr string
	)
	if err := s.Scan(&f.ID, &f.AnalysisID, &status, &category, &expl, &f.UserNote, &createdStr); err != nil {
		return nil, err
	}
	f.Status = domain.FeedbackStatus(status)
	if category.Valid {
		f.CorrectedCategory = &category.String
	}
	if expl.Valid {
		f.CorrectedExplanation = &expl.String
	}
	var err error
	if f.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, fmt.Errorf("parse created_at: %w", err)
	}
	return &f, nil
}

// nullString converts an optional string pointer to a sql-friendly value.
func nullString(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}
