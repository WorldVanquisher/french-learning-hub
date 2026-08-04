package sqlite

import (
	"context"
	"database/sql"
	"fmt"
	"path/filepath"
	"testing"
	"time"

	"french-learning-app/internal/domain"
	"french-learning-app/migrations"
)

// applyPreM8 opens a raw database and applies only migrations 001..003, leaving
// out 004 so the on-disk schema matches a milestone-7 database created before the
// capture table existed.
func applyPreM8(t *testing.T, path string) {
	t.Helper()
	dsn := fmt.Sprintf("file:%s?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)&_pragma=foreign_keys(ON)", path)
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		t.Fatalf("open raw db: %v", err)
	}
	defer db.Close()
	db.SetMaxOpenConns(1)

	for _, name := range []string{
		"001_create_learning_entries.sql",
		"002_create_entry_analyses.sql",
		"003_create_analysis_feedback.sql",
	} {
		b, err := migrations.Files.ReadFile(name)
		if err != nil {
			t.Fatalf("read %s: %v", name, err)
		}
		if _, err := db.Exec(string(b)); err != nil {
			t.Fatalf("exec %s: %v", name, err)
		}
	}
}

// TestMigration_UpgradeFromPreM8 proves the M8 migration is a safe additive
// upgrade: a database created with the pre-M8 schema and populated with an entry
// keeps that data intact after the capture table is added, a capture can then be
// imported, and both survive a reconnection.
func TestMigration_UpgradeFromPreM8(t *testing.T) {
	ctx := context.Background()
	dbPath := filepath.Join(t.TempDir(), "upgrade.db")

	// 1. Simulate a pre-M8 database with one existing entry.
	applyPreM8(t, dbPath)

	seedDB, err := sql.Open("sqlite",
		fmt.Sprintf("file:%s?_pragma=foreign_keys(ON)", dbPath))
	if err != nil {
		t.Fatalf("open seed db: %v", err)
	}
	seedDB.SetMaxOpenConns(1)
	ts := time.Now().UTC().Format(rfc3339)
	seedRes, err := seedDB.ExecContext(ctx,
		`INSERT INTO learning_entries (original_input, original_context, created_at, updated_at)
		 VALUES (?, ?, ?, ?)`,
		"pre-existing question", "seeded before M8", ts, ts)
	if err != nil {
		t.Fatalf("seed entry: %v", err)
	}
	preEntryID, _ := seedRes.LastInsertId()
	seedDB.Close()

	// 2. Open normally: this applies migration 004 on top of the existing schema.
	db, err := Open(dbPath)
	if err != nil {
		t.Fatalf("open (apply migration 004): %v", err)
	}

	// The pre-M8 entry is still present and unchanged.
	entryRepo := NewEntryRepository(db)
	pre, err := entryRepo.GetByID(ctx, preEntryID)
	if err != nil {
		t.Fatalf("read pre-M8 entry after upgrade: %v", err)
	}
	if pre.OriginalInput != "pre-existing question" || pre.OriginalContext != "seeded before M8" {
		t.Fatalf("pre-M8 entry changed by migration: %+v", pre)
	}

	// 3. Import a capture against the upgraded schema.
	captureRepo := NewCaptureRepository(db)
	res, err := captureRepo.Create(ctx, preparedCapture("cap-upgrade", true))
	if err != nil {
		t.Fatalf("create capture after upgrade: %v", err)
	}
	if !res.Created {
		t.Fatal("expected capture to be created")
	}
	db.Close()

	// 4. Reconnect and confirm both the pre-M8 entry and the new capture persist.
	db2, err := Open(dbPath)
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer db2.Close()

	if _, err := NewEntryRepository(db2).GetByID(ctx, preEntryID); err != nil {
		t.Fatalf("pre-M8 entry lost after reconnect: %v", err)
	}
	got, err := NewCaptureRepository(db2).GetByCaptureID(ctx, "cap-upgrade")
	if err != nil {
		t.Fatalf("capture lost after reconnect: %v", err)
	}
	if got.EntryID != res.EntryID {
		t.Fatalf("reconnected capture entry id = %d, want %d", got.EntryID, res.EntryID)
	}
	if got.SchemaVersion != domain.CaptureSchemaV1 {
		t.Fatalf("schema version = %q", got.SchemaVersion)
	}
}
