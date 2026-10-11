// Command semantic-index runs the explicit, operator-initiated semantic index
// operations (FLH-040; run consistency FLH-042). It reads the same
// configuration as the server (environment plus optional .env in the working
// directory) and requires SEMANTIC_SEARCH=qdrant.
//
//	semantic-index [-json] [-batch N] [-takeover] build    publish the first collection
//	semantic-index [-json] [-batch N] [-takeover] sync     verify; republish only if unhealthy
//	semantic-index [-json] [-batch N] [-takeover] rebuild  always republish; remove leftovers
//	semantic-index [-json] status                          last run + live verification; read-only
//
// Every run takes the space's lease. While another run holds an unexpired
// lease the command exits 4 (busy); -takeover takes it anyway and must only be
// used when that run is known to be dead. A run that loses the lease stops at
// its next gate, publishes nothing and exits 3.
//
// Exit status: 0 published or verified unchanged, 1 error, 2 usage,
// 3 ownership lost, 4 busy. SIGINT/SIGTERM interrupt the run; the previously
// published collection stays in use. There is no worker and no retry.
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
	"strings"
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
	takeover := flags.Bool("takeover", false, "take the lease from another run (only if that run is dead)")
	if err := flags.Parse(args); err != nil {
		return 2
	}
	if flags.NArg() != 1 {
		fmt.Fprintln(stderr, "usage: semantic-index [-json] [-batch N] [-takeover] build|sync|rebuild|status")
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
			return printJSON(stdout, stderr, st)
		}
		printStatus(stdout, st)
		return 0
	}

	opts := application.SemanticRunOptions{Takeover: *takeover}
	var report *application.SemanticIndexReport
	switch operation {
	case "build":
		report, err = svc.Build(ctx, opts)
	case "sync":
		report, err = svc.Sync(ctx, opts)
	case "rebuild":
		report, err = svc.Rebuild(ctx, opts)
	}
	if report != nil {
		if *asJSON {
			printJSON(stdout, stderr, report)
		} else {
			printReport(stdout, report)
		}
	}
	switch {
	case errors.Is(err, application.ErrSemanticIndexBusy):
		fmt.Fprintf(stderr, "busy: %v\n", err)
		return 4
	case errors.Is(err, application.ErrSemanticIndexOwnershipLost) && report != nil && report.Published:
		fmt.Fprintln(stderr, "published, but another run took over before this run's record was written; run status")
		return 3
	case errors.Is(err, application.ErrSemanticIndexOwnershipLost):
		fmt.Fprintln(stderr, "ownership lost: a newer run took over; this run published nothing")
		return 3
	case err != nil:
		fmt.Fprintf(stderr, "%s failed: %v\n", operation, err)
		if errors.Is(err, context.Canceled) {
			fmt.Fprintln(stderr, "interrupted: the previously published collection is unchanged; run sync to finish (cached embeddings are kept)")
		}
		return 1
	}
	return 0
}

func printReport(w io.Writer, r *application.SemanticIndexReport) {
	fmt.Fprintf(w, "%s %s (run %s)\n", r.Operation, r.Space, r.RunID)
	fmt.Fprintf(w, "  concepts:            %d\n", r.Concepts)
	if r.VerifiedUnchanged {
		fmt.Fprintf(w, "  verified unchanged:  %s is healthy; nothing written\n", r.Collection)
	} else {
		fmt.Fprintf(w, "  embedded (provider): %d texts\n", r.EmbeddedTexts)
		fmt.Fprintf(w, "  reused from cache:   %d\n", r.ReusedVectors)
		fmt.Fprintf(w, "  new collection:      %s (%d points written)\n", r.Collection, r.Upserted)
		if r.CatchUpChanges > 0 {
			fmt.Fprintf(w, "  catch-up changes:    %d\n", r.CatchUpChanges)
		}
		if r.Published {
			fmt.Fprintf(w, "  published:           yes (replaced %s, removed %d leftover collection(s))\n", orNone(r.Replaced), r.Cleaned)
		} else {
			fmt.Fprintln(w, "  published:           no (the previous publication is unchanged)")
		}
	}
	fmt.Fprintf(w, "  outcome:             %s\n", r.Outcome)
}

func orNone(s string) string {
	if s == "" {
		return "none"
	}
	return s
}

func fmtTime(t *time.Time) string {
	if t == nil {
		return "-"
	}
	return t.Format(time.RFC3339)
}

func ids(list []int64) string {
	if len(list) == 0 {
		return "0"
	}
	parts := make([]string, 0, len(list))
	for i, id := range list {
		if i == 8 {
			parts = append(parts, "…")
			break
		}
		parts = append(parts, fmt.Sprint(id))
	}
	return fmt.Sprintf("%d (%s)", len(list), strings.Join(parts, ", "))
}

func printStatus(w io.Writer, st *application.SemanticIndexStatus) {
	fmt.Fprintf(w, "space %s\n", st.Space.Collection)
	fmt.Fprintf(w, "  model id:          %s (%d dimensions, %s)\n", st.Space.ModelID, st.Space.Dimensions, st.Space.Representation)
	s := st.State
	if s == nil {
		fmt.Fprintln(w, "  nothing recorded:  never built; run build")
	} else {
		fmt.Fprintf(w, "  published:         %s (run %s at %s)\n", orNone(s.PublishedCollection), orNone(s.PublishedRunID), fmtTime(s.PublishedAt))
		fmt.Fprintf(w, "  last run:          %s %s → %s at %s", orNone(s.LastRunOperation), orNone(s.LastRunID), orNone(s.LastRunOutcome), fmtTime(s.LastRunFinishedAt))
		if s.LastError != "" {
			fmt.Fprintf(w, " (%s)", s.LastError)
		}
		fmt.Fprintln(w)
		switch {
		case st.LeaseActive:
			fmt.Fprintf(w, "  lease:             held by %s run %s until %s\n", s.LeaseOperation, s.LeaseRunID, fmtTime(s.LeaseExpiresAt))
		case s.LeaseRunID != "":
			fmt.Fprintf(w, "  lease:             EXPIRED (%s run %s, %s); the next run may take it\n", s.LeaseOperation, s.LeaseRunID, fmtTime(s.LeaseExpiresAt))
		}
	}
	fmt.Fprintf(w, "  concepts:          %d\n", st.Concepts)
	switch {
	case st.HealthError != "":
		fmt.Fprintf(w, "  verification:      could not verify (%s)\n", st.HealthError)
	case st.Health == nil:
		fmt.Fprintln(w, "  verification:      nothing published")
	default:
		h := st.Health
		fmt.Fprintf(w, "  verification:      %s — %s\n", map[bool]string{true: "HEALTHY", false: "UNHEALTHY"}[h.Healthy], h.Summary())
		if h.Exists {
			fmt.Fprintf(w, "    collection:      %d dims %s; %d points for %d concepts\n", h.Dimensions, h.Distance, h.Points, h.Expected)
			fmt.Fprintf(w, "    missing %s · extra %s · foreign %s · stale %s · vector mismatch %s · unverifiable %s\n",
				ids(h.Missing), ids(h.Extra), ids(h.ForeignPayload), ids(h.Stale), ids(h.VectorMismatch), ids(h.Unverifiable))
		}
		if !h.Healthy {
			fmt.Fprintln(w, "    repair:          run sync (republishes a fresh collection from cached embeddings)")
		}
	}
	for _, c := range st.Collections {
		if c.Status != application.PhysicalPublished {
			fmt.Fprintf(w, "  leftover:          %s (%s, run %s) — removed by the next run\n", c.Collection, c.Status, c.RunID)
		}
	}
	for _, n := range st.Unrecorded {
		fmt.Fprintf(w, "  unrecorded:        %s exists in Qdrant without a record — removed by rebuild\n", n)
	}
	for _, o := range st.OtherSpaces {
		fmt.Fprintf(w, "  other space:       %s model %s (%d dims), published %s — not used by this configuration\n", o.Space, o.ModelID, o.Dimensions, orNone(o.PublishedCollection))
	}
	for _, c := range st.CacheCounts {
		fmt.Fprintf(w, "  cached vectors:    %d for model %s (%d dims)\n", c.Vectors, c.ModelID, c.Dimensions)
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
