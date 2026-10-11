// FLH-041 isolated repository diagnostic. No fake or real vector store is used.
// This proves SQLite mutation behavior only; real-Qdrant interleavings remain
// unexecuted if the required local artifact is absent.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/storage/sqlite"
)

func must(err error) {
	if err != nil {
		panic(err)
	}
}

func main() {
	if len(os.Args) != 2 {
		panic("usage: ownership-probe task-owned-database")
	}
	ctx := context.Background()
	dbA, err := sqlite.Open(os.Args[1])
	must(err)
	defer dbA.Close()
	dbB, err := sqlite.Open(os.Args[1])
	must(err)
	defer dbB.Close()
	a := sqlite.NewSemanticIndexRepository(dbA)
	b := sqlite.NewSemanticIndexRepository(dbB)
	space, err := application.NewSemanticIndexSpace("flh041_diag", "fixture/model@a", 2)
	must(err)
	t := time.Date(2026, 10, 10, 12, 0, 0, 0, time.UTC)
	must(a.BeginRun(ctx, space, "older-run", "rebuild", t))
	must(b.BeginRun(ctx, space, "newer-run", "sync", t.Add(time.Second)))
	must(b.RecordPoints(ctx, space.Collection, map[int64]string{1: "newer-hash"}, t.Add(2*time.Second)))
	owned, err := b.FinishRun(ctx, space.Collection, "newer-run", application.SemanticIndexStateComplete, "", t.Add(3*time.Second))
	must(err)
	if !owned {
		panic("newer-run fixture did not own its final write")
	}
	before, err := b.PublishedPoints(ctx, space.Collection)
	must(err)
	// Simulates the bookkeeping call made by a delayed older publish after its
	// upsert returns. Production RecordPoints accepts no run ID or fence token.
	must(a.RecordPoints(ctx, space.Collection, map[int64]string{1: "older-hash"}, t.Add(4*time.Second)))
	afterOverwrite, err := b.PublishedPoints(ctx, space.Collection)
	must(err)
	olderFinished, err := a.FinishRun(ctx, space.Collection, "older-run", application.SemanticIndexStateComplete, "", t.Add(5*time.Second))
	must(err)
	col, err := b.Collection(ctx, space.Collection)
	must(err)
	must(a.ClearPoints(ctx, space.Collection))
	afterClear, err := b.PublishedPoints(ctx, space.Collection)
	must(err)
	must(b.RecordPoints(ctx, space.Collection, map[int64]string{1: "newer-hash"}, t.Add(6*time.Second)))
	must(a.RemovePoints(ctx, space.Collection, []int64{1}))
	afterRemove, err := b.PublishedPoints(ctx, space.Collection)
	must(err)

	// Independent repository cache round-trip/reopen/key isolation, without any
	// provider or publication claim. Existing key must never be overwritten.
	must(b.SaveVectors(ctx, space, map[string][]float32{"same-hash": {1, 2}}, t))
	must(a.SaveVectors(ctx, space, map[string][]float32{"same-hash": {9, 9}}, t))
	otherModel, err := application.NewSemanticIndexSpace("flh041_diag", "fixture/model@b", 2)
	must(err)
	otherDims, err := application.NewSemanticIndexSpace("flh041_diag", "fixture/model@a", 3)
	must(err)
	otherRepresentation := space
	otherRepresentation.Representation = "fixture-other-representation"
	must(b.SaveVectors(ctx, otherModel, map[string][]float32{"same-hash": {3, 4}}, t))
	must(b.SaveVectors(ctx, otherDims, map[string][]float32{"same-hash": {5, 6, 7}}, t))
	must(b.SaveVectors(ctx, otherRepresentation, map[string][]float32{"same-hash": {7, 8}}, t))
	must(dbA.Close())
	dbA, err = sqlite.Open(os.Args[1])
	must(err)
	defer dbA.Close()
	a = sqlite.NewSemanticIndexRepository(dbA)
	vectors, err := a.CachedVectors(ctx, space, []string{"same-hash"})
	must(err)
	modelVectors, err := a.CachedVectors(ctx, otherModel, []string{"same-hash"})
	must(err)
	dimVectors, err := a.CachedVectors(ctx, otherDims, []string{"same-hash"})
	must(err)
	reprVectors, err := a.CachedVectors(ctx, otherRepresentation, []string{"same-hash"})
	must(err)
	if vectors["same-hash"][0] != 1 || modelVectors["same-hash"][0] != 3 ||
		dimVectors["same-hash"][0] != 5 || reprVectors["same-hash"][0] != 7 {
		panic("cache reopen/isolation assertion failed")
	}
	out := map[string]any{
		"evidence_type": "real production SQLite repository; no Qdrant/provider/service interleaving",
		"expected":      "superseded work cannot overwrite/clear/remove newer run point bookkeeping",
		"before":        before, "after_older_overwrite": afterOverwrite,
		"after_older_clear": afterClear, "after_older_remove": afterRemove,
		"older_finish_owned": olderFinished, "collection_after_older_finish": col,
		"cache_after_reopen": vectors, "other_model_cache": modelVectors,
		"other_dimensions_cache": dimVectors, "other_representation_cache": reprVectors,
		"unfenced_mutations_observed": afterOverwrite[1] == "older-hash" && len(afterClear) == 0 && len(afterRemove) == 0,
	}
	must(json.NewEncoder(os.Stdout).Encode(out))
	fmt.Fprintln(os.Stderr, "diagnostic complete; not real-Qdrant acceptance")
}
