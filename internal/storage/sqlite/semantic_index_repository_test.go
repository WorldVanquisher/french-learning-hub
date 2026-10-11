package sqlite

import (
	"context"
	"errors"
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

// The FLH-041 F1 sequence against the FLH-042 API: two database handles stand
// for two processes. A superseded run's every bookkeeping write is refused and
// leaves the newer run's records unchanged.
func TestSemanticIndexRepository_FencedWritesRejectSupersededRun(t *testing.T) {
	path := filepath.Join(t.TempDir(), "s.db")
	dbA, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer dbA.Close()
	dbB, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer dbB.Close()
	a, b := NewSemanticIndexRepository(dbA), NewSemanticIndexRepository(dbB)
	ctx := context.Background()
	now := time.Date(2026, 10, 10, 12, 0, 0, 0, time.UTC)
	space := application.SemanticIndexSpace{Representation: "rep", ModelID: "m1", Dimensions: 2, Collection: "space"}
	lost := application.ErrSemanticIndexOwnershipLost

	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	must(a.AcquireLease(ctx, space, "older", "rebuild", now, now.Add(time.Minute), false))
	must(a.RegisterCollection(ctx, "space", "older", "space_rolder", now))
	must(a.RecordManifest(ctx, "space", "older", "space_rolder", map[int64]string{1: "older-hash"}))

	if err := b.AcquireLease(ctx, space, "newer", "sync", now, now.Add(time.Minute), false); !errors.Is(err, application.ErrSemanticIndexBusy) {
		t.Fatalf("unexpired lease must be busy: %v", err)
	}
	// Taking an expired lease needs no takeover.
	must(b.AcquireLease(ctx, space, "newer", "sync", now.Add(2*time.Minute), now.Add(3*time.Minute), false))
	must(b.RegisterCollection(ctx, "space", "newer", "space_rnewer", now))
	must(b.RecordManifest(ctx, "space", "newer", "space_rnewer", map[int64]string{1: "newer-hash"}))
	prev, err := b.Publish(ctx, "space", "newer", "space_rnewer", now)
	must(err)
	if prev != "" {
		t.Fatalf("previous = %q", prev)
	}
	must(b.CompleteRun(ctx, "space", "newer", "sync", application.SemanticRunOutcome{Outcome: "published", StartedAt: now, FinishedAt: now}))

	// Every write by the superseded run is refused.
	for name, write := range map[string]func() error{
		"renew":      func() error { return a.RenewLease(ctx, "space", "older", now.Add(time.Hour)) },
		"record own": func() error { return a.RecordManifest(ctx, "space", "older", "space_rolder", map[int64]string{2: "x"}) },
		"record newer's": func() error {
			return a.RecordManifest(ctx, "space", "older", "space_rnewer", map[int64]string{1: "older-hash"})
		},
		"remove newer's": func() error { return a.RemoveManifest(ctx, "space", "older", "space_rnewer", []int64{1}) },
		"publish":        func() error { _, err := a.Publish(ctx, "space", "older", "space_rolder", now); return err },
		"mark newer's":   func() error { return a.MarkCollection(ctx, "space", "older", "space_rnewer", "abandoned", now) },
		"forget newer's": func() error { return a.ForgetCollection(ctx, "space", "older", "space_rnewer") },
		"register":       func() error { return a.RegisterCollection(ctx, "space", "older", "space_rolder2", now) },
		"complete": func() error {
			return a.CompleteRun(ctx, "space", "older", "rebuild", application.SemanticRunOutcome{Outcome: "published"})
		},
	} {
		if err := write(); !errors.Is(err, lost) {
			t.Fatalf("%s: err = %v, want ownership lost", name, err)
		}
	}
	st, err := b.SpaceState(ctx, "space")
	must(err)
	if st.PublishedCollection != "space_rnewer" || st.PublishedRunID != "newer" || st.LastRunID != "newer" || st.LastRunOutcome != "published" || st.LeaseRunID != "" {
		t.Fatalf("newer records changed: %+v", st)
	}
	m, err := b.Manifest(ctx, "space_rnewer")
	must(err)
	if len(m) != 1 || m[1] != "newer-hash" {
		t.Fatalf("newer manifest changed: %v", m)
	}

	// Even the lease holder cannot write another run's manifest, and a
	// published record is never forgotten.
	must(b.AcquireLease(ctx, space, "third", "rebuild", now, now.Add(time.Minute), true))
	if err := b.RecordManifest(ctx, "space", "third", "space_rnewer", map[int64]string{1: "x"}); !errors.Is(err, lost) {
		t.Fatalf("writing another run's manifest: %v", err)
	}
	must(b.ForgetCollection(ctx, "space", "third", "space_rnewer"))
	cols, err := b.PhysicalCollections(ctx, "space")
	must(err)
	statuses := map[string]string{}
	for _, c := range cols {
		statuses[c.Collection] = c.Status
	}
	if statuses["space_rnewer"] != "published" || statuses["space_rolder"] != "writing" {
		t.Fatalf("collections = %v", statuses)
	}
	// Publishing a new collection retires the previous one in the same transaction.
	must(b.RegisterCollection(ctx, "space", "third", "space_rthird", now))
	prev, err = b.Publish(ctx, "space", "third", "space_rthird", now)
	must(err)
	cols, _ = b.PhysicalCollections(ctx, "space")
	for _, c := range cols {
		statuses[c.Collection] = c.Status
	}
	if prev != "space_rnewer" || statuses["space_rnewer"] != "retired" || statuses["space_rthird"] != "published" {
		t.Fatalf("prev %q statuses %v", prev, statuses)
	}
}
