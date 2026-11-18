package sqlite

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func readinessCheck(t *testing.T, path string) (func(context.Context) error, func()) {
	t.Helper()
	db, err := Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	return Readiness(db), func() { db.Close() }
}

func TestReadiness_WritableDatabaseIsReady(t *testing.T) {
	path := filepath.Join(t.TempDir(), "app.db")
	check, closeDB := readinessCheck(t, path)
	defer closeDB()
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		if err := check(context.Background()); err != nil {
			t.Fatalf("check %d: %v", i, err)
		}
	}
	after, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(before) != string(after) {
		t.Fatal("the readiness probe changed the database file")
	}
}

// TestReadiness_ReadOnlyDatabaseIsNotReady is the restore defect: a database
// whose files are read-only opens, answers ping and reads, but cannot write.
func TestReadiness_ReadOnlyDatabaseIsNotReady(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("root ignores file permissions")
	}
	dir := t.TempDir()
	path := filepath.Join(dir, "app.db")
	db, err := Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	if _, err := db.Exec("PRAGMA wal_checkpoint(TRUNCATE)"); err != nil {
		t.Fatal(err)
	}
	db.Close()
	for _, f := range []string{"app.db", "app.db-wal", "app.db-shm"} {
		if err := os.Chmod(filepath.Join(dir, f), 0o444); err != nil && !os.IsNotExist(err) {
			t.Fatal(err)
		}
	}
	t.Cleanup(func() {
		for _, f := range []string{"app.db", "app.db-wal", "app.db-shm"} {
			_ = os.Chmod(filepath.Join(dir, f), 0o644)
		}
	})
	check, closeDB := readinessCheck(t, path)
	defer closeDB()
	err = check(context.Background())
	if !errors.Is(err, ErrStorageReadOnly) {
		t.Fatalf("check = %v, want ErrStorageReadOnly", err)
	}
	var reasoner interface{ ReadinessReason() string }
	if !errors.As(err, &reasoner) || reasoner.ReadinessReason() != "storage_read_only" {
		t.Fatalf("reason = %v, want storage_read_only", err)
	}
}

// TestReadiness_BusyWriterIsReady: another connection holding the write lock
// proves the database is writable. The probe must neither wait for the lock
// nor report not ready.
func TestReadiness_BusyWriterIsReady(t *testing.T) {
	path := filepath.Join(t.TempDir(), "app.db")
	check, closeDB := readinessCheck(t, path)
	defer closeDB()
	other, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	tx, err := other.Begin()
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback()
	if _, err := tx.Exec("CREATE TABLE readiness_lock_holder (id INTEGER)"); err != nil {
		t.Fatal(err)
	}
	start := time.Now()
	if err := check(context.Background()); err != nil {
		t.Fatalf("check while another writer holds the lock: %v", err)
	}
	if elapsed := time.Since(start); elapsed > time.Second {
		t.Fatalf("probe waited %v for the lock; want no wait", elapsed)
	}
}

// TestReadiness_RestoresBusyTimeout: the pool's single connection keeps the
// DSN's busy timeout after a probe, so normal writes still wait for a lock.
func TestReadiness_RestoresBusyTimeout(t *testing.T) {
	path := filepath.Join(t.TempDir(), "app.db")
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if err := Readiness(db)(context.Background()); err != nil {
		t.Fatal(err)
	}
	var ms int64
	if err := db.QueryRow("PRAGMA busy_timeout").Scan(&ms); err != nil {
		t.Fatal(err)
	}
	if ms != 5000 {
		t.Fatalf("busy_timeout after the probe = %d, want 5000", ms)
	}
}
