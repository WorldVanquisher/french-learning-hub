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

// SemanticIndexRepository stores the reusable embedding cache (FLH-040) and the
// run/publication bookkeeping (FLH-042). Every method is one short transaction;
// callers never hold one across a provider or vector-store call. Methods taking
// a runID are fenced by the space's lease.
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

// leaseTime is a fixed-width UTC layout, so lease expiry can be compared as
// text inside SQL.
const leaseTime = "2006-01-02T15:04:05.000000000Z"

func fmtLease(t time.Time) string { return t.UTC().Format(leaseTime) }

// AcquireLease takes the space's lease for runID. It fails with
// ErrSemanticIndexBusy while another run holds an unexpired lease, unless
// takeover is set. The space row is created on first use.
func (r *SemanticIndexRepository) AcquireLease(ctx context.Context, space application.SemanticIndexSpace, runID, operation string, now, expires time.Time, takeover bool) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin lease: %w", err)
	}
	defer tx.Rollback()
	if _, err := tx.ExecContext(ctx, `INSERT OR IGNORE INTO semantic_index_spaces (space, representation, model_id, dimensions)
		VALUES (?, ?, ?, ?)`, space.Collection, space.Representation, space.ModelID, space.Dimensions); err != nil {
		return fmt.Errorf("create semantic index space: %w", err)
	}
	cond := `lease_run_id IS NULL OR lease_expires_at IS NULL OR lease_expires_at < ?`
	args := []any{runID, operation, fmtLease(now), fmtLease(expires), space.Collection, fmtLease(now)}
	if takeover {
		cond, args = `1`, args[:5]
	}
	res, err := tx.ExecContext(ctx, `UPDATE semantic_index_spaces
		SET lease_run_id = ?, lease_operation = ?, lease_started_at = ?, lease_expires_at = ?
		WHERE space = ? AND (`+cond+`)`, args...)
	if err != nil {
		return fmt.Errorf("take semantic index lease: %w", err)
	}
	if n, _ := res.RowsAffected(); n != 1 {
		var holder, op, until sql.NullString
		_ = tx.QueryRowContext(ctx, `SELECT lease_run_id, lease_operation, lease_expires_at FROM semantic_index_spaces WHERE space = ?`,
			space.Collection).Scan(&holder, &op, &until)
		return fmt.Errorf("%w: %s run %s until %s (use -takeover only if that run is dead)",
			application.ErrSemanticIndexBusy, op.String, holder.String, until.String)
	}
	return tx.Commit()
}

// RenewLease extends the lease if runID still holds it.
func (r *SemanticIndexRepository) RenewLease(ctx context.Context, space, runID string, expires time.Time) error {
	res, err := r.db.ExecContext(ctx, `UPDATE semantic_index_spaces SET lease_expires_at = ?
		WHERE space = ? AND lease_run_id = ?`, fmtLease(expires), space, runID)
	if err != nil {
		return fmt.Errorf("renew semantic index lease: %w", err)
	}
	if n, _ := res.RowsAffected(); n != 1 {
		return application.ErrSemanticIndexOwnershipLost
	}
	return nil
}

// fenced runs fn in one transaction whose first statement is a write that
// matches only while runID holds the lease. That write takes SQLite's write
// lock, so the lease cannot change before fn's statements commit.
func (r *SemanticIndexRepository) fenced(ctx context.Context, space, runID string, fn func(*sql.Tx) error) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin fenced write: %w", err)
	}
	defer tx.Rollback()
	res, err := tx.ExecContext(ctx, `UPDATE semantic_index_spaces SET lease_run_id = lease_run_id
		WHERE space = ? AND lease_run_id = ?`, space, runID)
	if err != nil {
		return fmt.Errorf("check semantic index lease: %w", err)
	}
	if n, _ := res.RowsAffected(); n != 1 {
		return application.ErrSemanticIndexOwnershipLost
	}
	if err := fn(tx); err != nil {
		return err
	}
	return tx.Commit()
}

// CompleteRun records the owning run's outcome and releases the lease.
func (r *SemanticIndexRepository) CompleteRun(ctx context.Context, space, runID, operation string, o application.SemanticRunOutcome) error {
	return r.fenced(ctx, space, runID, func(tx *sql.Tx) error {
		_, err := tx.ExecContext(ctx, `UPDATE semantic_index_spaces SET
			last_run_id = ?, last_run_operation = ?, last_run_outcome = ?, last_run_started_at = ?,
			last_run_finished_at = ?, last_error = ?,
			lease_run_id = NULL, lease_operation = NULL, lease_started_at = NULL, lease_expires_at = NULL
			WHERE space = ?`, runID, operation, o.Outcome, fmtLease(o.StartedAt), fmtLease(o.FinishedAt), o.LastError, space)
		if err != nil {
			return fmt.Errorf("record semantic index run: %w", err)
		}
		return nil
	})
}

// RegisterCollection records a run's physical collection before it is created
// in the vector store, so every task-created collection is recorded.
func (r *SemanticIndexRepository) RegisterCollection(ctx context.Context, space, runID, collection string, now time.Time) error {
	return r.fenced(ctx, space, runID, func(tx *sql.Tx) error {
		_, err := tx.ExecContext(ctx, `INSERT INTO semantic_index_physical_collections
			(collection, space, run_id, status, created_at, updated_at) VALUES (?, ?, ?, 'writing', ?, ?)`,
			collection, space, runID, fmtLease(now), fmtLease(now))
		if err != nil {
			return fmt.Errorf("register semantic index collection: %w", err)
		}
		return nil
	})
}

// ownCollection checks that collection belongs to runID and is still being written.
func ownCollection(ctx context.Context, tx *sql.Tx, space, runID, collection string) error {
	var owner, status string
	err := tx.QueryRowContext(ctx, `SELECT run_id, status FROM semantic_index_physical_collections WHERE collection = ? AND space = ?`,
		collection, space).Scan(&owner, &status)
	if err != nil || owner != runID || status != application.PhysicalWriting {
		return fmt.Errorf("%w: collection %s is not this run's writing collection", application.ErrSemanticIndexOwnershipLost, collection)
	}
	return nil
}

func (r *SemanticIndexRepository) RecordManifest(ctx context.Context, space, runID, collection string, points map[int64]string) error {
	return r.fenced(ctx, space, runID, func(tx *sql.Tx) error {
		if err := ownCollection(ctx, tx, space, runID, collection); err != nil {
			return err
		}
		for id, hash := range points {
			if _, err := tx.ExecContext(ctx, `INSERT INTO semantic_index_manifest (collection, concept_id, content_hash)
				VALUES (?, ?, ?) ON CONFLICT (collection, concept_id) DO UPDATE SET content_hash = excluded.content_hash`,
				collection, id, hash); err != nil {
				return fmt.Errorf("record semantic index manifest: %w", err)
			}
		}
		return nil
	})
}

func (r *SemanticIndexRepository) RemoveManifest(ctx context.Context, space, runID, collection string, conceptIDs []int64) error {
	return r.fenced(ctx, space, runID, func(tx *sql.Tx) error {
		if err := ownCollection(ctx, tx, space, runID, collection); err != nil {
			return err
		}
		for _, id := range conceptIDs {
			if _, err := tx.ExecContext(ctx, `DELETE FROM semantic_index_manifest WHERE collection = ? AND concept_id = ?`, collection, id); err != nil {
				return fmt.Errorf("remove semantic index manifest row: %w", err)
			}
		}
		return nil
	})
}

// Publish is the single publication point: in one fenced transaction it makes
// collection the space's published collection, marks it published and the
// previous one retired, and returns the previous name.
func (r *SemanticIndexRepository) Publish(ctx context.Context, space, runID, collection string, now time.Time) (string, error) {
	var previous string
	err := r.fenced(ctx, space, runID, func(tx *sql.Tx) error {
		if err := ownCollection(ctx, tx, space, runID, collection); err != nil {
			return err
		}
		var prev sql.NullString
		if err := tx.QueryRowContext(ctx, `SELECT published_collection FROM semantic_index_spaces WHERE space = ?`, space).Scan(&prev); err != nil {
			return fmt.Errorf("read publication: %w", err)
		}
		previous = prev.String
		ts := fmtLease(now)
		if _, err := tx.ExecContext(ctx, `UPDATE semantic_index_spaces SET published_collection = ?, published_run_id = ?, published_at = ?
			WHERE space = ?`, collection, runID, ts, space); err != nil {
			return fmt.Errorf("publish semantic index collection: %w", err)
		}
		if _, err := tx.ExecContext(ctx, `UPDATE semantic_index_physical_collections SET status = 'published', updated_at = ?
			WHERE collection = ?`, ts, collection); err != nil {
			return err
		}
		if previous != "" && previous != collection {
			if _, err := tx.ExecContext(ctx, `UPDATE semantic_index_physical_collections SET status = 'retired', updated_at = ?
				WHERE collection = ?`, ts, previous); err != nil {
				return err
			}
		}
		return nil
	})
	return previous, err
}

// MarkCollection changes the status of a collection that is not published.
func (r *SemanticIndexRepository) MarkCollection(ctx context.Context, space, runID, collection, status string, now time.Time) error {
	return r.fenced(ctx, space, runID, func(tx *sql.Tx) error {
		_, err := tx.ExecContext(ctx, `UPDATE semantic_index_physical_collections SET status = ?, updated_at = ?
			WHERE collection = ? AND space = ? AND status != 'published'`, status, fmtLease(now), collection, space)
		return err
	})
}

// ForgetCollection deletes the record (and manifest) of a collection that was
// removed from the vector store. A published collection is never forgotten.
func (r *SemanticIndexRepository) ForgetCollection(ctx context.Context, space, runID, collection string) error {
	return r.fenced(ctx, space, runID, func(tx *sql.Tx) error {
		_, err := tx.ExecContext(ctx, `DELETE FROM semantic_index_physical_collections
			WHERE collection = ? AND space = ? AND status != 'published'`, collection, space)
		return err
	})
}

func (r *SemanticIndexRepository) Manifest(ctx context.Context, collection string) (map[int64]string, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT concept_id, content_hash FROM semantic_index_manifest WHERE collection = ?`, collection)
	if err != nil {
		return nil, fmt.Errorf("read semantic index manifest: %w", err)
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

const spaceColumns = `space, representation, model_id, dimensions, lease_run_id, lease_operation, lease_started_at,
	lease_expires_at, published_collection, published_run_id, published_at, last_run_id, last_run_operation,
	last_run_outcome, last_run_started_at, last_run_finished_at, last_error`

func scanSpace(row interface{ Scan(...any) error }) (application.SemanticIndexSpaceState, error) {
	var s application.SemanticIndexSpaceState
	var leaseRun, leaseOp, leaseStart, leaseExp, pubCol, pubRun, pubAt, lastRun, lastOp, lastOut, lastStart, lastEnd sql.NullString
	if err := row.Scan(&s.Space, &s.Representation, &s.ModelID, &s.Dimensions, &leaseRun, &leaseOp, &leaseStart, &leaseExp,
		&pubCol, &pubRun, &pubAt, &lastRun, &lastOp, &lastOut, &lastStart, &lastEnd, &s.LastError); err != nil {
		return s, err
	}
	s.LeaseRunID, s.LeaseOperation, s.PublishedCollection, s.PublishedRunID = leaseRun.String, leaseOp.String, pubCol.String, pubRun.String
	s.LastRunID, s.LastRunOperation, s.LastRunOutcome = lastRun.String, lastOp.String, lastOut.String
	for _, f := range []struct {
		src sql.NullString
		dst **time.Time
	}{{leaseStart, &s.LeaseStartedAt}, {leaseExp, &s.LeaseExpiresAt}, {pubAt, &s.PublishedAt}, {lastStart, &s.LastRunStartedAt}, {lastEnd, &s.LastRunFinishedAt}} {
		if f.src.Valid {
			t, err := time.Parse(leaseTime, f.src.String)
			if err != nil {
				return s, fmt.Errorf("parse semantic index time: %w", err)
			}
			*f.dst = &t
		}
	}
	return s, nil
}

func (r *SemanticIndexRepository) SpaceState(ctx context.Context, space string) (*application.SemanticIndexSpaceState, error) {
	s, err := scanSpace(r.db.QueryRowContext(ctx, `SELECT `+spaceColumns+` FROM semantic_index_spaces WHERE space = ?`, space))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("read semantic index space: %w", err)
	}
	return &s, nil
}

func (r *SemanticIndexRepository) SpaceStates(ctx context.Context) ([]application.SemanticIndexSpaceState, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT `+spaceColumns+` FROM semantic_index_spaces ORDER BY space`)
	if err != nil {
		return nil, fmt.Errorf("read semantic index spaces: %w", err)
	}
	defer rows.Close()
	var out []application.SemanticIndexSpaceState
	for rows.Next() {
		s, err := scanSpace(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

func (r *SemanticIndexRepository) PhysicalCollections(ctx context.Context, space string) ([]application.PhysicalCollection, error) {
	rows, err := r.db.QueryContext(ctx, `SELECT collection, space, run_id, status, created_at, updated_at
		FROM semantic_index_physical_collections WHERE space = ? ORDER BY created_at, collection`, space)
	if err != nil {
		return nil, fmt.Errorf("read semantic index collections: %w", err)
	}
	defer rows.Close()
	var out []application.PhysicalCollection
	for rows.Next() {
		var c application.PhysicalCollection
		var created, updated string
		if err := rows.Scan(&c.Collection, &c.Space, &c.RunID, &c.Status, &created, &updated); err != nil {
			return nil, err
		}
		if c.CreatedAt, err = time.Parse(leaseTime, created); err != nil {
			return nil, err
		}
		if c.UpdatedAt, err = time.Parse(leaseTime, updated); err != nil {
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
