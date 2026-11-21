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

// VocabularyRepository stores the learner's saved vocabulary (migration 022):
// append-only marks and examples. It writes nothing else.
type VocabularyRepository struct {
	db *sql.DB
}

var _ domain.VocabularyRepository = (*VocabularyRepository)(nil)

// NewVocabularyRepository builds a repository over an open database.
func NewVocabularyRepository(db *sql.DB) *VocabularyRepository { return &VocabularyRepository{db: db} }

type queryRower interface {
	QueryRowContext(ctx context.Context, query string, args ...any) *sql.Row
}

func currentVocabularyMark(ctx context.Context, q queryRower, conceptID int64) (domain.VocabularyMark, bool, error) {
	m := domain.VocabularyMark{ConceptID: conceptID}
	var saved int
	var at, first string
	err := q.QueryRowContext(ctx, `SELECT saved, created_at, (SELECT min(created_at) FROM vocabulary_marks WHERE concept_id = ? AND saved = 1)
		FROM vocabulary_marks WHERE concept_id = ? ORDER BY id DESC LIMIT 1`, conceptID, conceptID).Scan(&saved, &at, &first)
	switch {
	case errors.Is(err, sql.ErrNoRows):
		return m, false, nil
	case err != nil:
		return m, false, err
	}
	m.Saved, m.At, m.FirstAt = saved == 1, parseTime(at), parseTime(first)
	return m, true, nil
}

// Save records the save and the example in one write transaction; only a
// change of state or a new (Concept, unit) pair adds a row.
func (r *VocabularyRepository) Save(ctx context.Context, ex domain.VocabularyExample, now time.Time) (domain.VocabularyMark, bool, bool, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return domain.VocabularyMark{}, false, false, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := tx.ExecContext(ctx, `UPDATE vocabulary_marks SET rowid = rowid WHERE 0`); err != nil {
		return domain.VocabularyMark{}, false, false, fmt.Errorf("take write lock: %w", err)
	}
	cur, _, err := currentVocabularyMark(ctx, tx, ex.ConceptID)
	if err != nil {
		return cur, false, false, err
	}
	saved := false
	if !cur.Saved {
		if _, err := tx.ExecContext(ctx, `INSERT INTO vocabulary_marks (concept_id, saved, created_at) VALUES (?, 1, ?)`, ex.ConceptID, fmtTime(now)); err != nil {
			return cur, false, false, fmt.Errorf("insert vocabulary mark: %w", err)
		}
		saved = true
	}
	res, err := tx.ExecContext(ctx, `INSERT OR IGNORE INTO vocabulary_examples (concept_id, unit_id, entry_id, extraction_id, extraction_version, created_at)
		VALUES (?, ?, ?, ?, ?, ?)`, ex.ConceptID, ex.UnitID, ex.EntryID, ex.ExtractionID, ex.ExtractionVersion, fmtTime(now))
	if err != nil {
		return cur, false, false, fmt.Errorf("insert vocabulary example: %w", err)
	}
	n, err := res.RowsAffected()
	if err != nil {
		return cur, false, false, err
	}
	mark, _, err := currentVocabularyMark(ctx, tx, ex.ConceptID)
	if err != nil {
		return cur, false, false, err
	}
	return mark, saved, n == 1, tx.Commit()
}

// Remove records a removal when the Concept is saved now.
func (r *VocabularyRepository) Remove(ctx context.Context, conceptID int64, now time.Time) (domain.VocabularyMark, bool, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return domain.VocabularyMark{}, false, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := tx.ExecContext(ctx, `UPDATE vocabulary_marks SET rowid = rowid WHERE 0`); err != nil {
		return domain.VocabularyMark{}, false, fmt.Errorf("take write lock: %w", err)
	}
	cur, found, err := currentVocabularyMark(ctx, tx, conceptID)
	if err != nil {
		return cur, false, err
	}
	if !found {
		return cur, false, domain.ErrNotFound
	}
	if !cur.Saved {
		return cur, false, tx.Commit()
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO vocabulary_marks (concept_id, saved, created_at) VALUES (?, 0, ?)`, conceptID, fmtTime(now)); err != nil {
		return cur, false, fmt.Errorf("insert vocabulary mark: %w", err)
	}
	mark, _, err := currentVocabularyMark(ctx, tx, conceptID)
	if err != nil {
		return cur, false, err
	}
	return mark, true, tx.Commit()
}

// Marks returns the current decision per Concept ever saved.
func (r *VocabularyRepository) Marks(ctx context.Context) (map[int64]domain.VocabularyMark, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT m.concept_id, m.saved, m.created_at,
		(SELECT min(f.created_at) FROM vocabulary_marks f WHERE f.concept_id = m.concept_id AND f.saved = 1)
		FROM vocabulary_marks m WHERE m.id = (SELECT max(id) FROM vocabulary_marks WHERE concept_id = m.concept_id)`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[int64]domain.VocabularyMark{}
	for rows.Next() {
		var m domain.VocabularyMark
		var saved int
		var at, first string
		if err := rows.Scan(&m.ConceptID, &saved, &at, &first); err != nil {
			return nil, err
		}
		m.Saved, m.At, m.FirstAt = saved == 1, parseTime(at), parseTime(first)
		out[m.ConceptID] = m
	}
	return out, rows.Err()
}

// Examples returns the examples of the given Concepts, oldest first.
func (r *VocabularyRepository) Examples(ctx context.Context, conceptIDs []int64) (map[int64][]domain.VocabularyExample, error) {
	out := map[int64][]domain.VocabularyExample{}
	if len(conceptIDs) == 0 {
		return out, nil
	}
	args := make([]any, len(conceptIDs))
	for i, id := range conceptIDs {
		args[i] = id
	}
	rows, err := r.db.QueryContext(ctx, `SELECT id, concept_id, unit_id, entry_id, extraction_id, extraction_version, created_at
		FROM vocabulary_examples WHERE concept_id IN (?`+strings.Repeat(",?", len(conceptIDs)-1)+`) ORDER BY id`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var e domain.VocabularyExample
		var created string
		if err := rows.Scan(&e.ID, &e.ConceptID, &e.UnitID, &e.EntryID, &e.ExtractionID, &e.ExtractionVersion, &created); err != nil {
			return nil, err
		}
		e.CreatedAt = parseTime(created)
		out[e.ConceptID] = append(out[e.ConceptID], e)
	}
	return out, rows.Err()
}
