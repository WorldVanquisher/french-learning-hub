package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"

	"french-learning-app/internal/application"
)

// SemanticIndexRepository stores the reusable embedding cache and the semantic
// index bookkeeping (FLH-040). Every method is one short transaction; callers
// never hold one across a provider or vector-store call.
type SemanticIndexRepository struct {
	db *sql.DB
}

var _ application.SemanticIndexStore = (*SemanticIndexRepository)(nil)

func NewSemanticIndexRepository(db *sql.DB) *SemanticIndexRepository {
	return &SemanticIndexRepository{db: db}
}

// sqliteMaxBatch keeps IN-lists far below SQLite's bound-variable limit.
const sqliteMaxBatch = 400

func (r *SemanticIndexRepository) CachedVectors(ctx context.Context, space application.SemanticIndexSpace, hashes []string) (map[string][]float32, error) {
	out := make(map[string][]float32, len(hashes))
	for start := 0; start < len(hashes); start += sqliteMaxBatch {
		chunk := hashes[start:min(start+sqliteMaxBatch, len(hashes))]
		args := []any{space.Representation, space.ModelID, space.Dimensions}
		for _, h := range chunk {
			args = append(args, h)
		}
		rows, err := r.db.QueryContext(ctx, `SELECT content_hash, vector FROM semantic_embedding_cache
			WHERE representation = ? AND model_id = ? AND dimensions = ?
			  AND content_hash IN (`+placeholders(len(chunk))+`)`, args...)
		if err != nil {
			return nil, fmt.Errorf("read embedding cache: %w", err)
		}
		for rows.Next() {
			var hash string
			var blob []byte
			if err := rows.Scan(&hash, &blob); err != nil {
				rows.Close()
				return nil, fmt.Errorf("scan embedding cache: %w", err)
			}
			v, err := application.DecodeFloat32Vector(blob, space.Dimensions)
			if err != nil {
				rows.Close()
				return nil, err
			}
			out[hash] = v
		}
		if err := rows.Close(); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// SaveVectors inserts new cache rows. An existing key is left unchanged: a
// content hash under one model identity and dimension always denotes the same
// document in the same vector space.
func (r *SemanticIndexRepository) SaveVectors(ctx context.Context, space application.SemanticIndexSpace, vectors map[string][]float32, now time.Time) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin embedding cache write: %w", err)
	}
	defer tx.Rollback()
	for hash, v := range vectors {
		if len(v) != space.Dimensions {
			return fmt.Errorf("%w: cache write has %d dimensions, space has %d", application.ErrInvalidEmbedding, len(v), space.Dimensions)
		}
		if _, err := tx.ExecContext(ctx, `INSERT OR IGNORE INTO semantic_embedding_cache
			(content_hash, representation, model_id, dimensions, vector, created_at) VALUES (?, ?, ?, ?, ?, ?)`,
			hash, space.Representation, space.ModelID, space.Dimensions, application.EncodeFloat32Vector(v), now.Format(rfc3339)); err != nil {
			return fmt.Errorf("write embedding cache: %w", err)
		}
	}
	return tx.Commit()
}

// BeginRun takes ownership of the space for a new run. A newer run always
// takes over: an older process that is still running can no longer mark the
// space complete because FinishRun checks the run id.
func (r *SemanticIndexRepository) BeginRun(ctx context.Context, space application.SemanticIndexSpace, runID, operation string, now time.Time) error {
	ts := now.Format(rfc3339)
	_, err := r.db.ExecContext(ctx, `INSERT INTO semantic_index_collections
		(collection, representation, model_id, dimensions, state, run_id, run_operation, run_started_at, updated_at, last_error)
		VALUES (?, ?, ?, ?, 'building', ?, ?, ?, ?, '')
		ON CONFLICT (collection) DO UPDATE SET state = 'building', run_id = excluded.run_id,
			run_operation = excluded.run_operation, run_started_at = excluded.run_started_at,
			updated_at = excluded.updated_at, last_error = ''`,
		space.Collection, space.Representation, space.ModelID, space.Dimensions, runID, operation, ts, ts)
	if err != nil {
		return fmt.Errorf("begin semantic index run: %w", err)
	}
	return nil
}

// FinishRun records the run outcome only if runID still owns the space. It
// reports whether it did.
func (r *SemanticIndexRepository) FinishRun(ctx context.Context, collection, runID, state, lastError string, now time.Time) (bool, error) {
	ts := now.Format(rfc3339)
	var completed any
	if state == application.SemanticIndexStateComplete {
		completed = ts
	}
	res, err := r.db.ExecContext(ctx, `UPDATE semantic_index_collections
		SET state = ?, updated_at = ?, last_error = ?, completed_at = COALESCE(?, completed_at)
		WHERE collection = ? AND run_id = ?`, state, ts, lastError, completed, collection, runID)
	if err != nil {
		return false, fmt.Errorf("finish semantic index run: %w", err)
	}
	n, err := res.RowsAffected()
	if err != nil {
		return false, err
	}
	return n == 1, nil
}

func (r *SemanticIndexRepository) ClearPoints(ctx context.Context, collection string) error {
	if _, err := r.db.ExecContext(ctx, `DELETE FROM semantic_index_points WHERE collection = ?`, collection); err != nil {
		return fmt.Errorf("clear semantic index points: %w", err)
	}
	return nil
}

func (r *SemanticIndexRepository) PublishedPoints(ctx context.Context, collection string) (map[int64]string, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT concept_id, content_hash FROM semantic_index_points WHERE collection = ?`, collection)
	if err != nil {
		return nil, fmt.Errorf("read semantic index points: %w", err)
	}
	defer rows.Close()
	out := map[int64]string{}
	for rows.Next() {
		var id int64
		var hash string
		if err := rows.Scan(&id, &hash); err != nil {
			return nil, err
		}
		out[id] = hash
	}
	return out, rows.Err()
}

func (r *SemanticIndexRepository) RecordPoints(ctx context.Context, collection string, points map[int64]string, now time.Time) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin semantic index point write: %w", err)
	}
	defer tx.Rollback()
	for id, hash := range points {
		if _, err := tx.ExecContext(ctx, `INSERT INTO semantic_index_points (collection, concept_id, content_hash, published_at)
			VALUES (?, ?, ?, ?) ON CONFLICT (collection, concept_id) DO UPDATE SET
			content_hash = excluded.content_hash, published_at = excluded.published_at`,
			collection, id, hash, now.Format(rfc3339)); err != nil {
			return fmt.Errorf("record semantic index point: %w", err)
		}
	}
	return tx.Commit()
}

func (r *SemanticIndexRepository) RemovePoints(ctx context.Context, collection string, conceptIDs []int64) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, id := range conceptIDs {
		if _, err := tx.ExecContext(ctx, `DELETE FROM semantic_index_points WHERE collection = ? AND concept_id = ?`, collection, id); err != nil {
			return fmt.Errorf("remove semantic index point: %w", err)
		}
	}
	return tx.Commit()
}

const collectionColumns = `collection, representation, model_id, dimensions, state, run_id, run_operation,
	run_started_at, updated_at, completed_at, last_error`

func scanCollection(row interface{ Scan(...any) error }) (application.SemanticIndexCollection, error) {
	var c application.SemanticIndexCollection
	var started, updated string
	var completed sql.NullString
	if err := row.Scan(&c.Collection, &c.Representation, &c.ModelID, &c.Dimensions, &c.State, &c.RunID, &c.RunOperation,
		&started, &updated, &completed, &c.LastError); err != nil {
		return c, err
	}
	var err error
	if c.RunStartedAt, err = time.Parse(rfc3339, started); err != nil {
		return c, fmt.Errorf("parse run_started_at: %w", err)
	}
	if c.UpdatedAt, err = time.Parse(rfc3339, updated); err != nil {
		return c, fmt.Errorf("parse updated_at: %w", err)
	}
	if completed.Valid {
		t, err := time.Parse(rfc3339, completed.String)
		if err != nil {
			return c, fmt.Errorf("parse completed_at: %w", err)
		}
		c.CompletedAt = &t
	}
	return c, nil
}

func (r *SemanticIndexRepository) Collection(ctx context.Context, collection string) (*application.SemanticIndexCollection, error) {
	c, err := scanCollection(r.db.QueryRowContext(ctx, `SELECT `+collectionColumns+` FROM semantic_index_collections WHERE collection = ?`, collection))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("read semantic index collection: %w", err)
	}
	return &c, nil
}

func (r *SemanticIndexRepository) Collections(ctx context.Context) ([]application.SemanticIndexCollection, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT `+collectionColumns+` FROM semantic_index_collections ORDER BY collection`)
	if err != nil {
		return nil, fmt.Errorf("read semantic index collections: %w", err)
	}
	defer rows.Close()
	var out []application.SemanticIndexCollection
	for rows.Next() {
		c, err := scanCollection(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

func (r *SemanticIndexRepository) CacheCounts(ctx context.Context) ([]application.SemanticCacheCount, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT representation, model_id, dimensions, COUNT(*) FROM semantic_embedding_cache
		GROUP BY representation, model_id, dimensions ORDER BY representation, model_id, dimensions`)
	if err != nil {
		return nil, fmt.Errorf("count embedding cache: %w", err)
	}
	defer rows.Close()
	var out []application.SemanticCacheCount
	for rows.Next() {
		var c application.SemanticCacheCount
		if err := rows.Scan(&c.Representation, &c.ModelID, &c.Dimensions, &c.Vectors); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

func placeholders(n int) string {
	return strings.TrimSuffix(strings.Repeat("?, ", n), ", ")
}
