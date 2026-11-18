package sqlite

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"errors"
	"fmt"

	sqlitedriver "modernc.org/sqlite"
)

// ErrStorageReadOnly means SQLite opened the database read-only. This happens,
// for example, when a restored copy keeps the read-only permissions of its
// backup, or when the filesystem was remounted read-only. Reads work but every
// write fails, so the service is not ready.
var ErrStorageReadOnly = errors.New("database is read-only")

// storageReadOnly carries a fixed reason code for /readyz. The code never names
// a path.
type storageReadOnly struct{}

func (storageReadOnly) Error() string           { return ErrStorageReadOnly.Error() }
func (storageReadOnly) Is(target error) bool    { return target == ErrStorageReadOnly }
func (storageReadOnly) ReadinessReason() string { return "storage_read_only" }

// SQLite result codes (the low byte of an extended code).
const (
	sqliteBusy     = 5
	sqliteReadOnly = 8
)

// Readiness returns the /readyz check for the private service. It is bounded by
// the caller's context and writes nothing:
//   - the database answers (ping);
//   - a write statement can run. Inside BEGIN IMMEDIATE ... ROLLBACK it runs
//     DELETE FROM schema_migrations WHERE 0, which matches no row. BEGIN
//     IMMEDIATE alone is not enough: in WAL mode it succeeds on a read-only
//     database, and only a write statement fails. The probe's connection uses
//     a zero busy timeout. A busy result means another writer holds the lock,
//     so the database is writable.
//
// A read-only database returns ErrStorageReadOnly. Ping alone cannot see it: the
// service would report ready and then answer 500 to every write.
func Readiness(db *sql.DB) func(context.Context) error {
	return func(ctx context.Context) error {
		conn, err := db.Conn(ctx)
		if err != nil {
			return err
		}
		defer conn.Close()
		if err := conn.PingContext(ctx); err != nil {
			return err
		}
		var previous int64
		if err := conn.QueryRowContext(ctx, "PRAGMA busy_timeout").Scan(&previous); err != nil {
			return err
		}
		if _, err := conn.ExecContext(ctx, "PRAGMA busy_timeout = 0"); err != nil {
			return err
		}
		probeErr := writeProbe(ctx, conn)
		if _, err := conn.ExecContext(context.WithoutCancel(ctx), fmt.Sprintf("PRAGMA busy_timeout = %d", previous)); err != nil {
			// Never hand a connection with another busy timeout back to the pool.
			_ = conn.Raw(func(any) error { return driver.ErrBadConn })
			if probeErr == nil {
				return err
			}
		}
		return probeErr
	}
}

func writeProbe(ctx context.Context, conn *sql.Conn) error {
	_, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE")
	if err == nil {
		_, err = conn.ExecContext(ctx, "DELETE FROM schema_migrations WHERE 0")
		if _, rbErr := conn.ExecContext(context.WithoutCancel(ctx), "ROLLBACK"); rbErr != nil {
			_ = conn.Raw(func(any) error { return driver.ErrBadConn })
			if err == nil {
				return rbErr
			}
		}
	}
	switch code := resultCode(err); {
	case err == nil:
		return nil
	case code == sqliteBusy:
		return nil // another connection or process holds the write lock: writable
	case code == sqliteReadOnly:
		return storageReadOnly{}
	default:
		return err
	}
}

func resultCode(err error) int {
	var se *sqlitedriver.Error
	if errors.As(err, &se) {
		return se.Code() & 0xff
	}
	return 0
}
