package sqlite

import (
	"context"
	"errors"
	"path/filepath"
	"testing"

	"french-learning-app/internal/domain"
)

func newTestDBRepos(t *testing.T) (*EntryRepository, *AnalysisRepository) {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "test.db")
	db, err := Open(dbPath)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return NewEntryRepository(db), NewAnalysisRepository(db)
}

func sampleResult() domain.AnalysisResult {
	return domain.AnalysisResult{
		Category:    "vocabulary",
		Explanation: "means hello",
		Confidence:  0.7,
		Uncertainty: "placeholder",
	}
}

func TestAnalysisRepository_Create_AssignsIncrementingVersions(t *testing.T) {
	entries, analyses := newTestDBRepos(t)
	ctx := context.Background()

	entry, err := entries.Create(ctx, domain.NewEntryInput{OriginalInput: "bonjour"})
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}

	first, err := analyses.Create(ctx, entry.ID, sampleResult(), "rule-based")
	if err != nil {
		t.Fatalf("create analysis 1: %v", err)
	}
	if first.Version != 1 {
		t.Fatalf("first version = %d, want 1", first.Version)
	}

	second, err := analyses.Create(ctx, entry.ID, sampleResult(), "rule-based")
	if err != nil {
		t.Fatalf("create analysis 2: %v", err)
	}
	if second.Version != 2 {
		t.Fatalf("second version = %d, want 2", second.Version)
	}
	if second.CreatedAt.IsZero() {
		t.Fatal("expected created_at to be set")
	}
}

func TestAnalysisRepository_Create_EntryNotFound(t *testing.T) {
	_, analyses := newTestDBRepos(t)
	_, err := analyses.Create(context.Background(), 9999, sampleResult(), "rule-based")
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestAnalysisRepository_ListByEntry(t *testing.T) {
	entries, analyses := newTestDBRepos(t)
	ctx := context.Background()

	entry, err := entries.Create(ctx, domain.NewEntryInput{OriginalInput: "bonjour"})
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}

	// No analyses yet.
	got, err := analyses.ListByEntry(ctx, entry.ID)
	if err != nil {
		t.Fatalf("list empty: %v", err)
	}
	if len(got) != 0 {
		t.Fatalf("expected 0 analyses, got %d", len(got))
	}

	for i := 0; i < 3; i++ {
		if _, err := analyses.Create(ctx, entry.ID, sampleResult(), "rule-based"); err != nil {
			t.Fatalf("create analysis: %v", err)
		}
	}

	got, err = analyses.ListByEntry(ctx, entry.ID)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(got) != 3 {
		t.Fatalf("expected 3 analyses, got %d", len(got))
	}
	// Oldest version first.
	for i, a := range got {
		if a.Version != int64(i+1) {
			t.Fatalf("analyses[%d].Version = %d, want %d", i, a.Version, i+1)
		}
	}
}

func TestAnalysisRepository_DoesNotMutateEntry(t *testing.T) {
	entries, analyses := newTestDBRepos(t)
	ctx := context.Background()

	entry, err := entries.Create(ctx, domain.NewEntryInput{
		OriginalInput:   "Je suis fatigué",
		OriginalContext: "texting",
	})
	if err != nil {
		t.Fatalf("create entry: %v", err)
	}
	if _, err := analyses.Create(ctx, entry.ID, sampleResult(), "rule-based"); err != nil {
		t.Fatalf("create analysis: %v", err)
	}

	// Original entry data must be untouched by analysis.
	reloaded, err := entries.GetByID(ctx, entry.ID)
	if err != nil {
		t.Fatalf("reload entry: %v", err)
	}
	if reloaded.OriginalInput != "Je suis fatigué" || reloaded.OriginalContext != "texting" {
		t.Fatalf("original entry data changed: %+v", reloaded)
	}
}
