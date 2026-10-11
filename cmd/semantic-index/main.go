// Command semantic-index runs the explicit, operator-initiated semantic index
// operations (FLH-040). It reads the same configuration as the server
// (environment plus optional .env in the working directory) and requires
// SEMANTIC_SEARCH=qdrant.
//
//	semantic-index [-json] [-batch N] build    create the index (refuses if it exists)
//	semantic-index [-json] [-batch N] sync     bring the index up to date incrementally
//	semantic-index [-json] [-batch N] rebuild  drop and republish (reuses cached embeddings)
//	semantic-index [-json] status              read-only health report; no provider call
//
// Exit status: 0 complete, 3 finished but partial or superseded, 1 error,
// 2 usage. SIGINT/SIGTERM cancel the run; the index is then marked partial.
// There is no background worker and no automatic retry.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"syscall"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/config"
	"french-learning-app/internal/embedding"
	"french-learning-app/internal/storage/sqlite"
	"french-learning-app/internal/vectorindex"
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

func run(args []string, stdout, stderr io.Writer) int {
	flags := flag.NewFlagSet("semantic-index", flag.ContinueOnError)
	flags.SetOutput(stderr)
	asJSON := flags.Bool("json", false, "print the report as JSON")
	batch := flags.Int("batch", 0, "batch size for provider and vector-store calls (default SEMANTIC_BATCH_SIZE)")
	if err := flags.Parse(args); err != nil {
		return 2
	}
	if flags.NArg() != 1 {
		fmt.Fprintln(stderr, "usage: semantic-index [-json] [-batch N] build|sync|rebuild|status")
		return 2
	}
	operation := flags.Arg(0)
	switch operation {
	case "build", "sync", "rebuild", "status":
	default:
		fmt.Fprintf(stderr, "unknown operation %q (build, sync, rebuild, status)\n", operation)
		return 2
	}

	cfg, err := config.Load()
	if err != nil {
		fmt.Fprintf(stderr, "configuration: %v\n", err)
		return 1
	}
	if cfg.Semantic.Mode != config.SemanticQdrant {
		fmt.Fprintln(stderr, "semantic search is not configured: set SEMANTIC_SEARCH=qdrant with QDRANT_URL, EMBEDDING_MODEL_ID and EMBEDDING_DIMENSIONS")
		return 1
	}
	space, err := application.NewSemanticIndexSpace(cfg.Semantic.CollectionPrefix, cfg.Semantic.ModelID, cfg.Semantic.Dimensions)
	if err != nil {
		fmt.Fprintf(stderr, "configuration: %v\n", err)
		return 1
	}
	batchSize := cfg.Semantic.BatchSize
	if *batch != 0 {
		if *batch < 1 || *batch > application.SemanticIndexMaxBatchSize {
			fmt.Fprintf(stderr, "-batch must be between 1 and %d\n", application.SemanticIndexMaxBatchSize)
			return 2
		}
		batchSize = *batch
	}

	db, err := sqlite.Open(cfg.DBPath)
	if err != nil {
		fmt.Fprintf(stderr, "open database: %v\n", err)
		return 1
	}
	defer db.Close()
	provider, err := embedding.New(cfg.Embedding)
	if err != nil {
		fmt.Fprintf(stderr, "configuration: %v\n", err)
		return 1
	}
	svc := application.NewSemanticIndexService(
		sqlite.NewConceptRepository(db), sqlite.NewSemanticIndexRepository(db),
		vectorindex.NewQdrant(cfg.Semantic.QdrantURL, cfg.Semantic.QdrantAPIKey, cfg.Semantic.QdrantTimeout),
		provider, space, batchSize,
	)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	if operation == "status" {
		st, err := svc.Status(ctx)
		if err != nil {
			fmt.Fprintf(stderr, "status: %v\n", err)
			return 1
		}
		if *asJSON {
			return printJSON(stdout, stderr, statusJSON(st))
		}
		printStatus(stdout, st)
		return 0
	}

	var report *application.SemanticIndexReport
	switch operation {
	case "build":
		report, err = svc.Build(ctx)
	case "sync":
		report, err = svc.Sync(ctx)
	case "rebuild":
		report, err = svc.Rebuild(ctx)
	}
	if report != nil {
		if *asJSON {
			printJSON(stdout, stderr, report)
		} else {
			printReport(stdout, report)
		}
	}
	if err != nil {
		fmt.Fprintf(stderr, "%s failed: %v\n", operation, err)
		if errors.Is(err, context.Canceled) {
			fmt.Fprintln(stderr, "interrupted: the index is marked partial; run sync to finish (cached embeddings are kept)")
		}
		return 1
	}
	if report.Superseded {
		fmt.Fprintln(stderr, "another run took over this index; this run did not record a final state")
		return 3
	}
	if report.State != application.SemanticIndexStateComplete {
		fmt.Fprintf(stderr, "finished with state %s; run sync again\n", report.State)
		return 3
	}
	return 0
}

func printReport(w io.Writer, r *application.SemanticIndexReport) {
	fmt.Fprintf(w, "%s %s (run %s)\n", r.Operation, r.Collection, r.RunID)
	fmt.Fprintf(w, "  concepts:            %d\n", r.Concepts)
	fmt.Fprintf(w, "  embedded (provider): %d texts\n", r.EmbeddedTexts)
	fmt.Fprintf(w, "  reused from cache:   %d\n", r.ReusedVectors)
	fmt.Fprintf(w, "  upserted:            %d\n", r.Upserted)
	fmt.Fprintf(w, "  unchanged:           %d\n", r.Unchanged)
	fmt.Fprintf(w, "  deleted:             %d\n", r.Deleted)
	fmt.Fprintf(w, "  changed during run:  %d\n", r.ChangedDuringRun)
	fmt.Fprintf(w, "  state:               %s\n", r.State)
}

type statusOutput struct {
	Collection         string                                `json:"collection"`
	Representation     string                                `json:"representation"`
	ModelID            string                                `json:"model_id"`
	Dimensions         int                                   `json:"dimensions"`
	State              *string                               `json:"state"`
	LastRun            *string                               `json:"last_run"`
	LastError          string                                `json:"last_error"`
	Concepts           int                                   `json:"concepts"`
	UpToDate           int                                   `json:"up_to_date"`
	Stale              int                                   `json:"stale"`
	Missing            int                                   `json:"missing"`
	Orphaned           int                                   `json:"orphaned"`
	VectorStorePoints  *int64                                `json:"vector_store_points"`
	VectorStoreError   string                                `json:"vector_store_error"`
	SearchableComplete bool                                  `json:"searchable_complete"`
	OtherCollections   []application.SemanticIndexCollection `json:"other_collections"`
	CacheCounts        []application.SemanticCacheCount      `json:"cache_counts"`
}

func statusJSON(st *application.SemanticIndexStatus) statusOutput {
	out := statusOutput{
		Collection: st.Space.Collection, Representation: st.Space.Representation, ModelID: st.Space.ModelID,
		Dimensions: st.Space.Dimensions, Concepts: st.Concepts, UpToDate: st.UpToDate, Stale: st.Stale,
		Missing: st.Missing, Orphaned: st.Orphaned, VectorStoreError: st.VectorStoreError,
		SearchableComplete: st.SearchableComplete, OtherCollections: st.OtherCollections, CacheCounts: st.CacheCounts,
	}
	if st.Collection != nil {
		out.State = &st.Collection.State
		run := fmt.Sprintf("%s %s started %s", st.Collection.RunOperation, st.Collection.RunID, st.Collection.RunStartedAt.Format(time.RFC3339))
		out.LastRun = &run
		out.LastError = st.Collection.LastError
	}
	if st.VectorStoreError == "" && st.VectorStore.Exists {
		n := st.VectorStore.PointCount
		out.VectorStorePoints = &n
	}
	return out
}

func printStatus(w io.Writer, st *application.SemanticIndexStatus) {
	fmt.Fprintf(w, "collection %s\n", st.Space.Collection)
	fmt.Fprintf(w, "  model id:        %s (%d dimensions, %s)\n", st.Space.ModelID, st.Space.Dimensions, st.Space.Representation)
	if st.Collection == nil {
		fmt.Fprintln(w, "  state:           not built")
	} else {
		c := st.Collection
		fmt.Fprintf(w, "  state:           %s (last run: %s %s, started %s)\n", c.State, c.RunOperation, c.RunID, c.RunStartedAt.Format(time.RFC3339))
		if c.State == application.SemanticIndexStateBuilding {
			fmt.Fprintln(w, "                   a run is in progress or was killed; if no run is active, run sync")
		}
		if c.LastError != "" {
			fmt.Fprintf(w, "  last error:      %s\n", c.LastError)
		}
	}
	fmt.Fprintf(w, "  concepts:        %d (up to date %d, stale %d, missing %d, orphaned points %d)\n", st.Concepts, st.UpToDate, st.Stale, st.Missing, st.Orphaned)
	switch {
	case st.VectorStoreError != "":
		fmt.Fprintf(w, "  vector store:    %s\n", st.VectorStoreError)
	case !st.VectorStore.Exists:
		fmt.Fprintln(w, "  vector store:    collection absent")
	default:
		fmt.Fprintf(w, "  vector store:    %d points (%d dimensions, %s)\n", st.VectorStore.PointCount, st.VectorStore.Dimensions, st.VectorStore.Distance)
	}
	for _, c := range st.OtherCollections {
		fmt.Fprintf(w, "  other space:     %s model %s (%d dims) state %s — not used by the current configuration\n", c.Collection, c.ModelID, c.Dimensions, c.State)
	}
	for _, c := range st.CacheCounts {
		fmt.Fprintf(w, "  cached vectors:  %d for model %s (%d dims)\n", c.Vectors, c.ModelID, c.Dimensions)
	}
	if st.SearchableComplete {
		fmt.Fprintln(w, "  searchable:      complete")
	} else {
		fmt.Fprintln(w, "  searchable:      NOT complete — results may be missing or stale (search fails while the vector store is unreachable); run sync")
	}
}

func printJSON(stdout, stderr io.Writer, v any) int {
	enc := json.NewEncoder(stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(v); err != nil {
		fmt.Fprintf(stderr, "encode: %v\n", err)
		return 1
	}
	return 0
}
