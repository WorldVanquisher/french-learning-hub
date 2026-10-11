package sqlite

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"french-learning-app/internal/application"
)

func TestSemanticIndexRepository_CacheRoundTripAndKeying(t *testing.T) {
	db, err := Open(filepath.Join(t.TempDir(), "s.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	r := NewSemanticIndexRepository(db)
	ctx := context.Background()
	now := time.Date(2026, 10, 10, 1, 2, 3, 0, time.UTC)
	a := application.SemanticIndexSpace{Representation: "rep", ModelID: "m1", Dimensions: 3, Collection: "c_a"}
	b := a
	b.ModelID = "m2"

	if err := r.SaveVectors(ctx, a, map[string][]float32{"h1": {1, -2.5, 3}}, now); err != nil {
		t.Fatal(err)
	}
	// A second write of the same key never overwrites the first.
	if err := r.SaveVectors(ctx, a, map[string][]float32{"h1": {9, 9, 9}}, now); err != nil {
		t.Fatal(err)
	}
	got, err := r.CachedVectors(ctx, a, []string{"h1", "h2"})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got["h1"][1] != -2.5 || got["h1"][2] != 3 {
		t.Fatalf("cached = %v", got)
	}
	// Another model identity does not see the vector.
	if got, _ := r.CachedVectors(ctx, b, []string{"h1"}); len(got) != 0 {
		t.Fatalf("model identity leaked: %v", got)
	}
	if err := r.SaveVectors(ctx, a, map[string][]float32{"bad": {1, 2}}, now); err == nil {
		t.Fatal("a vector of the wrong dimension must be refused")
	}
	if _, err := db.Exec(`INSERT INTO semantic_embedding_cache VALUES ('x','rep','m1',3,X'00',?)`, now.Format(rfc3339)); err == nil {
		t.Fatal("the blob-length CHECK must reject a truncated vector")
	}
	counts, err := r.CacheCounts(ctx)
	if err != nil || len(counts) != 1 || counts[0].Vectors != 1 {
		t.Fatalf("counts = %+v %v", counts, err)
	}
}

func TestSemanticIndexRepository_RunOwnershipAndPoints(t *testing.T) {
	db, err := Open(filepath.Join(t.TempDir(), "s.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	r := NewSemanticIndexRepository(db)
	ctx := context.Background()
	now := time.Date(2026, 10, 10, 1, 2, 3, 0, time.UTC)
	space := application.SemanticIndexSpace{Representation: "rep", ModelID: "m1", Dimensions: 3, Collection: "c_a"}

	if c, err := r.Collection(ctx, "c_a"); err != nil || c != nil {
		t.Fatalf("absent collection = %+v %v", c, err)
	}
	if err := r.BeginRun(ctx, space, "run1", "build", now); err != nil {
		t.Fatal(err)
	}
	if err := r.BeginRun(ctx, space, "run2", "sync", now); err != nil {
		t.Fatal(err)
	}
	owned, err := r.FinishRun(ctx, "c_a", "run1", "complete", "", now)
	if err != nil || owned {
		t.Fatalf("superseded run must not finish: owned=%v err=%v", owned, err)
	}
	owned, err = r.FinishRun(ctx, "c_a", "run2", "complete", "", now)
	if err != nil || !owned {
		t.Fatalf("owner must finish: owned=%v err=%v", owned, err)
	}
	c, err := r.Collection(ctx, "c_a")
	if err != nil || c.State != "complete" || c.RunID != "run2" || c.RunOperation != "sync" || c.CompletedAt == nil {
		t.Fatalf("collection = %+v %v", c, err)
	}
	if _, err := r.FinishRun(ctx, "c_a", "run2", "bogus", "", now); err == nil {
		t.Fatal("state CHECK must reject unknown states")
	}

	if err := r.RecordPoints(ctx, "c_a", map[int64]string{1: "h1", 2: "h2"}, now); err != nil {
		t.Fatal(err)
	}
	if err := r.RecordPoints(ctx, "c_a", map[int64]string{2: "h2b"}, now); err != nil {
		t.Fatal(err)
	}
	if err := r.RemovePoints(ctx, "c_a", []int64{1}); err != nil {
		t.Fatal(err)
	}
	pts, err := r.PublishedPoints(ctx, "c_a")
	if err != nil || len(pts) != 1 || pts[2] != "h2b" {
		t.Fatalf("points = %v %v", pts, err)
	}
	if err := r.ClearPoints(ctx, "c_a"); err != nil {
		t.Fatal(err)
	}
	if pts, _ := r.PublishedPoints(ctx, "c_a"); len(pts) != 0 {
		t.Fatalf("clear left %v", pts)
	}
	all, err := r.Collections(ctx)
	if err != nil || len(all) != 1 {
		t.Fatalf("collections = %+v %v", all, err)
	}
}
