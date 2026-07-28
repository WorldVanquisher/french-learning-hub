package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"french-learning-app/internal/domain"
)

// EntryRepository is a SQLite-backed domain.Repository.
type EntryRepository struct {
	db  *sql.DB
	now func() time.Time
}

// compile-time check that EntryRepository satisfies the domain interface.
var _ domain.Repository = (*EntryRepository)(nil)

// NewEntryRepository builds a repository over an open database.
func NewEntryRepository(db *sql.DB) *EntryRepository {
	return &EntryRepository{
		db:  db,
		now: func() time.Time { return time.Now().UTC() },
	}
}

const rfc3339 = time.RFC3339Nano

// Create inserts a new entry from validated input and returns the stored row.
// Timestamps are generated here; AI metadata columns are left NULL.
func (r *EntryRepository) Create(ctx context.Context, in domain.NewEntryInput) (*domain.Entry, error) {
	now := r.now()
	ts := now.Format(rfc3339)

	res, err := r.db.ExecContext(ctx,
		`INSERT INTO learning_entries (original_input, original_context, created_at, updated_at)
		 VALUES (?, ?, ?, ?)`,
		in.OriginalInput, in.OriginalContext, ts, ts,
	)
	if err != nil {
		return nil, fmt.Errorf("insert entry: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, fmt.Errorf("last insert id: %w", err)
	}

	return &domain.Entry{
		ID:              id,
		OriginalInput:   in.OriginalInput,
		OriginalContext: in.OriginalContext,
		CreatedAt:       now,
		UpdatedAt:       now,
	}, nil
}

// GetByID returns the entry with the given id, or domain.ErrNotFound.
func (r *EntryRepository) GetByID(ctx context.Context, id int64) (*domain.Entry, error) {
	row := r.db.QueryRowContext(ctx,
		`SELECT id, original_input, original_context, created_at, updated_at,
		        category, explanation, confidence
		 FROM learning_entries WHERE id = ?`, id)

	e, err := scanEntry(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, domain.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get entry: %w", err)
	}
	return e, nil
}

// List returns up to limit entries, newest first.
func (r *EntryRepository) List(ctx context.Context, limit int) ([]*domain.Entry, error) {
	rows, err := r.db.QueryContext(ctx,
		`SELECT id, original_input, original_context, created_at, updated_at,
		        category, explanation, confidence
		 FROM learning_entries
		 ORDER BY id DESC
		 LIMIT ?`, limit)
	if err != nil {
		return nil, fmt.Errorf("list entries: %w", err)
	}
	defer rows.Close()

	var out []*domain.Entry
	for rows.Next() {
		e, err := scanEntry(rows)
		if err != nil {
			return nil, fmt.Errorf("scan entry: %w", err)
		}
		out = append(out, e)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate entries: %w", err)
	}
	return out, nil
}

// scanner is satisfied by both *sql.Row and *sql.Rows.
type scanner interface {
	Scan(dest ...any) error
}

func scanEntry(s scanner) (*domain.Entry, error) {
	var (
		e          domain.Entry
		createdStr string
		updatedStr string
		category   sql.NullString
		expl       sql.NullString
		confidence sql.NullFloat64
	)
	if err := s.Scan(&e.ID, &e.OriginalInput, &e.OriginalContext,
		&createdStr, &updatedStr, &category, &expl, &confidence); err != nil {
		return nil, err
	}

	var err error
	if e.CreatedAt, err = time.Parse(rfc3339, createdStr); err != nil {
		return nil, fmt.Errorf("parse created_at: %w", err)
	}
	if e.UpdatedAt, err = time.Parse(rfc3339, updatedStr); err != nil {
		return nil, fmt.Errorf("parse updated_at: %w", err)
	}
	if category.Valid {
		e.Category = &category.String
	}
	if expl.Valid {
		e.Explanation = &expl.String
	}
	if confidence.Valid {
		e.Confidence = &confidence.Float64
	}
	return &e, nil
}
