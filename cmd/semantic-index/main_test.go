package main

import (
	"bytes"
	"context"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/storage/sqlite"
)

func TestRun_UsageAndConfigurationRefusals(t *testing.T) {
	for _, k := range []string{"SEMANTIC_SEARCH", "EMBEDDING_PROVIDER", "QDRANT_URL", "EMBEDDING_MODEL_ID", "EMBEDDING_DIMENSIONS"} {
		t.Setenv(k, "")
	}
	cases := []struct {
		args []string
		code int
		want string
	}{
		{nil, 2, "usage: semantic-index"},
		{[]string{"reindex"}, 2, `unknown operation "reindex"`},
		{[]string{"sync"}, 1, "semantic search is not configured"},
	}
	for _, c := range cases {
		var out, errOut bytes.Buffer
		if code := run(c.args, &out, &errOut); code != c.code || !strings.Contains(errOut.String(), c.want) {
			t.Fatalf("%v: code %d stderr %q", c.args, code, errOut.String())
		}
	}

	t.Setenv("SEMANTIC_SEARCH", "qdrant")
	t.Setenv("EMBEDDING_PROVIDER", "http")
	t.Setenv("EMBEDDING_MODEL", "m")
	t.Setenv("EMBEDDING_BASE_URL", "http://127.0.0.1:9/v1")
	t.Setenv("QDRANT_URL", "http://127.0.0.1:9")
	t.Setenv("EMBEDDING_MODEL_ID", "m@1")
	t.Setenv("EMBEDDING_DIMENSIONS", "8")
	t.Setenv("DB_PATH", t.TempDir()+"/cli.db")
	var out, errOut bytes.Buffer
	if code := run([]string{"-batch", "999", "sync"}, &out, &errOut); code != 2 || !strings.Contains(errOut.String(), "-batch must be between 1 and 256") {
		t.Fatalf("batch bound: code %d stderr %q", code, errOut.String())
	}
}

func TestRun_BusyLeaseExitsFour(t *testing.T) {
	dbPath := t.TempDir() + "/busy.db"
	for k, v := range map[string]string{
		"SEMANTIC_SEARCH": "qdrant", "EMBEDDING_PROVIDER": "http", "EMBEDDING_MODEL": "m",
		"EMBEDDING_BASE_URL": "http://127.0.0.1:9/v1", "QDRANT_URL": "http://127.0.0.1:9",
		"EMBEDDING_MODEL_ID": "m@1", "EMBEDDING_DIMENSIONS": "8", "DB_PATH": dbPath,
	} {
		t.Setenv(k, v)
	}
	db, err := sqlite.Open(dbPath)
	if err != nil {
		t.Fatal(err)
	}
	space, _ := application.NewSemanticIndexSpace("flh_concepts", "m@1", 8)
	now := time.Now().UTC()
	if err := sqlite.NewSemanticIndexRepository(db).AcquireLease(context.Background(), space, "other-run-000000", "rebuild", now, now.Add(time.Hour), false); err != nil {
		t.Fatal(err)
	}
	db.Close()
	var out, errOut bytes.Buffer
	if code := run([]string{"sync"}, &out, &errOut); code != 4 || !strings.Contains(errOut.String(), "busy:") || !strings.Contains(errOut.String(), "other-run-000000") {
		t.Fatalf("code %d stderr %q", code, errOut.String())
	}
}

// FLH-047 O1: a healthy sync whose deletion of a retired collection failed.
// The text report must show the pending name and error while the outcome
// stays verified_unchanged (the CLI still exits 0 for it).
func TestPrintReport_HealthySyncShowsPendingCleanup(t *testing.T) {
	var out bytes.Buffer
	printReport(&out, &application.SemanticIndexReport{
		Operation: "sync", RunID: "run-b", Space: "flh_concepts_x", Collection: "flh_concepts_x_rnew",
		Concepts: 3, VerifiedUnchanged: true, Outcome: "verified_unchanged",
		CleanupPending: []string{"flh_concepts_x_rold"}, CleanupError: "vector index unavailable",
	})
	text := out.String()
	for _, want := range []string{
		"flh_concepts_x_rnew is healthy; published nothing",
		"cleanup:             removed 0 leftover collection(s); 1 pending",
		"pending:           flh_concepts_x_rold",
		"cleanup error:     vector index unavailable",
		"outcome:             verified_unchanged",
	} {
		if !strings.Contains(text, want) {
			t.Errorf("missing %q in:\n%s", want, text)
		}
	}
	if strings.Contains(text, "nothing written") {
		t.Errorf("healthy sync text still says nothing written:\n%s", text)
	}
}

// A healthy sync that removed leftovers must not claim it wrote nothing.
func TestPrintReport_HealthySyncShowsCleanedCount(t *testing.T) {
	var out bytes.Buffer
	printReport(&out, &application.SemanticIndexReport{
		Operation: "sync", Collection: "c_rnew", VerifiedUnchanged: true, Cleaned: 2, Outcome: "verified_unchanged",
	})
	text := out.String()
	if !strings.Contains(text, "removed 2 leftover collection(s); 0 pending") || strings.Contains(text, "nothing written") {
		t.Fatalf("text:\n%s", text)
	}
	if strings.Contains(text, "pending:  ") || strings.Contains(text, "cleanup error") {
		t.Fatalf("no pending or error expected:\n%s", text)
	}
}

func TestPrintReport_PublishedAndFailedRuns(t *testing.T) {
	var out bytes.Buffer
	printReport(&out, &application.SemanticIndexReport{
		Operation: "rebuild", Collection: "c_rb", Published: true, Replaced: "c_ra", Cleaned: 1,
		CleanupPending: []string{"c_ra"}, CleanupError: "vector index unavailable", Outcome: "published",
	})
	text := out.String()
	for _, want := range []string{"published:           yes (replaced c_ra)", "removed 1 leftover collection(s); 1 pending", "pending:           c_ra", "cleanup error:     vector index unavailable"} {
		if !strings.Contains(text, want) {
			t.Errorf("missing %q in:\n%s", want, text)
		}
	}

	// A run that failed before cleanup reports no cleanup line at all.
	out.Reset()
	printReport(&out, &application.SemanticIndexReport{Operation: "sync", Collection: "c_rc", Outcome: "failed"})
	if strings.Contains(out.String(), "cleanup") {
		t.Fatalf("failed run printed cleanup:\n%s", out.String())
	}
}

// FLH-047 O2: status must not promise that the next (healthy) run removes
// another run's writing collection.
func TestPrintStatus_DistinguishesLeftoverKinds(t *testing.T) {
	space, _ := application.NewSemanticIndexSpace("flh_concepts", "m@1", 8)
	future := time.Now().Add(time.Minute)
	st := &application.SemanticIndexStatus{
		Space: space,
		State: &application.SemanticIndexSpaceState{PublishedCollection: "p_rpub", LeaseRunID: "live-run", LeaseOperation: "rebuild", LeaseExpiresAt: &future},
		Collections: []application.PhysicalCollection{
			{Collection: "p_rpub", Status: application.PhysicalPublished, RunID: "pub"},
			{Collection: "p_rdead", Status: application.PhysicalWriting, RunID: "dead-run"},
			{Collection: "p_rlive", Status: application.PhysicalWriting, RunID: "live-run"},
			{Collection: "p_rold", Status: application.PhysicalRetired, RunID: "old"},
			{Collection: "p_rab", Status: application.PhysicalAbandoned, RunID: "ab"},
		},
	}
	render := func() string {
		var out bytes.Buffer
		printStatus(&out, st)
		return out.String()
	}

	st.LeaseActive = true
	text := render()
	for _, want := range []string{
		"leftover:          p_rdead (writing, run dead-run) — removed only by the next publishing run (build, rebuild, or a sync that republishes); a healthy sync keeps it",
		"in progress:       p_rlive (writing, run live-run holds the lease)",
		"leftover:          p_rold (retired, run old) — removed by the next run, including a healthy sync",
		"leftover:          p_rab (abandoned, run ab) — removed by the next run, including a healthy sync",
	} {
		if !strings.Contains(text, want) {
			t.Errorf("missing %q in:\n%s", want, text)
		}
	}
	if strings.Contains(text, "leftover:          p_rpub") || strings.Contains(text, "writing, run dead-run) — removed by the next run") {
		t.Errorf("wrong leftover wording:\n%s", text)
	}

	// Once the lease has expired, that run's writing collection is an ordinary
	// leftover for the next publishing run.
	st.LeaseActive = false
	if text := render(); !strings.Contains(text, "leftover:          p_rlive (writing, run live-run) — removed only by the next publishing run") {
		t.Errorf("expired holder's collection:\n%s", text)
	}
}
