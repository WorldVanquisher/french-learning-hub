package sqlite

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"french-learning-app/internal/domain"
)

func readAnnotationOperation(ctx context.Context, q txQuerier, id string) (*domain.AnnotationOperation, string, error) {
	var payload, result string
	err := q.QueryRowContext(ctx, `SELECT payload, result FROM annotation_operations WHERE id = ?`, id).Scan(&payload, &result)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, "", domain.ErrNotFound
	}
	if err != nil {
		return nil, "", err
	}
	var op domain.AnnotationOperation
	if err := json.Unmarshal([]byte(result), &op); err != nil {
		return nil, "", err
	}
	return &op, payload, nil
}
func (r *ConceptRepository) GetAnnotationOperation(ctx context.Context, id string) (*domain.AnnotationOperation, error) {
	op, _, err := readAnnotationOperation(ctx, r.db, id)
	return op, err
}

// Acquire SQLite's writer lock before checking the key. The unique key and the
// event are in the same transaction, including across separate DB connections.
func (r *ConceptRepository) CommitAnnotationOperation(ctx context.Context, id string, in domain.AnnotationOperationInput, evidence string) (*domain.AnnotationOperation, bool, error) {
	id, err := domain.NormalizeAnnotationOperationID(id)
	if err != nil {
		return nil, false, err
	}
	if err := in.Validate(); err != nil {
		return nil, false, err
	}
	payloadBytes, err := json.Marshal(in)
	if err != nil {
		return nil, false, err
	}
	payload := string(payloadBytes)
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()
	// A no-row UPDATE obtains the write lock without creating a pending receipt.
	if _, err := tx.ExecContext(ctx, `UPDATE annotation_operations SET id = id WHERE 0`); err != nil {
		return nil, false, err
	}
	prior, priorPayload, err := readAnnotationOperation(ctx, tx, id)
	if err == nil {
		if payload != priorPayload {
			return nil, false, fmt.Errorf("%w: annotation operation key conflicts", domain.ErrConceptConflict)
		}
		return prior, true, nil
	}
	if !errors.Is(err, domain.ErrNotFound) {
		return nil, false, err
	}
	op := &domain.AnnotationOperation{ID: id, Input: in}
	if in.Action == "distinct" {
		op.Distinction, err = r.recordDistinctionTx(ctx, tx, in.UnitID, in.ConceptID, domain.SourceHuman, evidence)
	} else {
		op.Link, err = r.linkRelationTx(ctx, tx, in.UnitID, in.ConceptID, in.Relation, domain.SourceHuman, evidence)
	}
	if err != nil {
		return nil, false, err
	}
	result, err := json.Marshal(op)
	if err != nil {
		return nil, false, err
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO annotation_operations (id, payload, result, created_at) VALUES (?, ?, ?, ?)`, id, payload, string(result), r.now().Format(rfc3339)); err != nil {
		return nil, false, err
	}
	if err := tx.Commit(); err != nil {
		return nil, false, err
	}
	return op, false, nil
}
