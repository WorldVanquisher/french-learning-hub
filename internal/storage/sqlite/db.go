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

// migrate applies every embedded *.sql file in lexical order. Migration files
// use idempotent statements (IF NOT EXISTS) so re-running Open is safe.
func migrate(db *sql.DB) error {
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
		b, err := fs.ReadFile(migrations.Files, name)
		if err != nil {
			return fmt.Errorf("read migration %s: %w", name, err)
		}
		if _, err := db.Exec(string(b)); err != nil {
			return fmt.Errorf("exec migration %s: %w", name, err)
		}
	}
	return nil
}
