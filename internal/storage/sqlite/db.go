// Package sqlite provides a SQLite-backed implementation of the domain
// repository, plus helpers to open the database and apply migrations.
package sqlite

import (
	"database/sql"
	"fmt"
	"io/fs"
	"sort"
	"strings"

	"french-learning-app/migrations"

	_ "modernc.org/sqlite" // pure-Go SQLite driver (no CGO)
)

// Open opens (creating if needed) the SQLite database at path and applies all
// pending migrations. Foreign keys and WAL are enabled for sane defaults.
func Open(path string) (*sql.DB, error) {
	dsn := fmt.Sprintf("file:%s?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)&_pragma=foreign_keys(ON)", path)
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}
	// A single writer avoids "database is locked" under concurrent writes.
	db.SetMaxOpenConns(1)

	if err := db.Ping(); err != nil {
		db.Close()
		return nil, fmt.Errorf("ping sqlite: %w", err)
	}
	if err := migrate(db); err != nil {
		db.Close()
		return nil, fmt.Errorf("apply migrations: %w", err)
	}
	return db, nil
}

// migrate applies each embedded *.sql file in lexical order EXACTLY ONCE,
// tracked in a schema_migrations ledger. Early migrations (001-006) are written
// with idempotent statements (IF NOT EXISTS) and were historically re-run on
// every Open; that remains harmless. Later migrations may use non-idempotent
// statements (e.g. ALTER TABLE ... DROP COLUMN in 007), which must not re-run —
// and, once 007 drops a column an earlier migration references, that earlier
// migration must not re-run either. The ledger guarantees both: on an existing
// database with no ledger yet, all files run once more (idempotently) and are
// recorded; from then on each file is skipped once recorded. Each migration and
// its ledger insert are committed together, so a migration is recorded only if
// it fully applied.
func migrate(db *sql.DB) error {
	if _, err := db.Exec(`CREATE TABLE IF NOT EXISTS schema_migrations (
		name       TEXT PRIMARY KEY,
		applied_at TEXT NOT NULL DEFAULT (datetime('now'))
	)`); err != nil {
		return fmt.Errorf("create schema_migrations: %w", err)
	}

	applied, err := appliedMigrations(db)
	if err != nil {
		return err
	}

	entries, err := fs.ReadDir(migrations.Files, ".")
	if err != nil {
		return err
	}

	names := make([]string, 0, len(entries))
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".sql") {
			names = append(names, e.Name())
		}
	}
	sort.Strings(names)

	for _, name := range names {
		if applied[name] {
			continue
		}
		b, err := fs.ReadFile(migrations.Files, name)
		if err != nil {
			return fmt.Errorf("read migration %s: %w", name, err)
		}
		tx, err := db.Begin()
		if err != nil {
			return fmt.Errorf("begin migration %s: %w", name, err)
		}
		if _, err := tx.Exec(string(b)); err != nil {
			tx.Rollback()
			return fmt.Errorf("exec migration %s: %w", name, err)
		}
		if _, err := tx.Exec(`INSERT INTO schema_migrations (name) VALUES (?)`, name); err != nil {
			tx.Rollback()
			return fmt.Errorf("record migration %s: %w", name, err)
		}
		if err := tx.Commit(); err != nil {
			return fmt.Errorf("commit migration %s: %w", name, err)
		}
	}
	return nil
}

// appliedMigrations returns the set of migration filenames already recorded in
// the ledger.
func appliedMigrations(db *sql.DB) (map[string]bool, error) {
	rows, err := db.Query(`SELECT name FROM schema_migrations`)
	if err != nil {
		return nil, fmt.Errorf("read schema_migrations: %w", err)
	}
	defer rows.Close()
	applied := make(map[string]bool)
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, fmt.Errorf("scan schema_migrations: %w", err)
		}
		applied[name] = true
	}
	return applied, rows.Err()
}
