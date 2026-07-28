package sqlite

import (
	"context"
	"errors"
	"path/filepath"
	"testing"

	"french-learning-app/internal/domain"
)

func newTestRepo(t *testing.T) *EntryRepository {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "test.db")
	db, err := Open(dbPath)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return NewEntryRepository(db)
}

func TestEntryRepository_CreateAndGet(t *testing.T) {
	repo := newTestRepo(t)
	ctx := context.Background()

	created, err := repo.Create(ctx, domain.NewEntryInput{
		OriginalInput:   "Je suis fatigué",
		OriginalContext: "texting a friend",
	})
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	if created.ID == 0 {
		t.Fatal("expected non-zero ID")
	}
	if created.CreatedAt.IsZero() || created.UpdatedAt.IsZero() {
		t.Fatal("expected timestamps to be set")
	}
	if created.Category != nil || created.Explanation != nil || created.Confidence != nil {
		t.Fatal("AI metadata should be nil on create")
	}

	got, err := repo.GetByID(ctx, created.ID)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if got.OriginalInput != "Je suis fatigué" {
		t.Fatalf("OriginalInput = %q", got.OriginalInput)
	}
	if got.OriginalContext != "texting a friend" {
		t.Fatalf("OriginalContext = %q", got.OriginalContext)
	}
	// Timestamps should round-trip to the same instant.
	if !got.CreatedAt.Equal(created.CreatedAt) {
		t.Fatalf("CreatedAt mismatch: %v vs %v", got.CreatedAt, created.CreatedAt)
	}
}

func TestEntryRepository_GetByID_NotFound(t *testing.T) {
	repo := newTestRepo(t)
	_, err := repo.GetByID(context.Background(), 9999)
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestEntryRepository_List(t *testing.T) {
	repo := newTestRepo(t)
	ctx := context.Background()

	for _, s := range []string{"first", "second", "third"} {
		if _, err := repo.Create(ctx, domain.NewEntryInput{OriginalInput: s}); err != nil {
			t.Fatalf("Create %q: %v", s, err)
		}
	}

	entries, err := repo.List(ctx, 10)
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(entries) != 3 {
		t.Fatalf("expected 3 entries, got %d", len(entries))
	}
	// Newest first.
	if entries[0].OriginalInput != "third" {
		t.Fatalf("expected newest-first order, got %q first", entries[0].OriginalInput)
	}

	limited, err := repo.List(ctx, 2)
	if err != nil {
		t.Fatalf("List limited: %v", err)
	}
	if len(limited) != 2 {
		t.Fatalf("expected limit of 2, got %d", len(limited))
	}
}
