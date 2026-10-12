package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
	"french-learning-app/internal/vectorindex"
)

// TestCLIQdrant_CleanupReportingAgainstRealQdrant reproduces FLH-047's O1
// (healthy sync with a persistently failing deletion) and O2 (another run's
// writing collection) through the real CLI against an actual Qdrant. It runs
// only when FLH_QDRANT_URL is set; embeddings come from a local fake, and a
// loopback proxy in front of Qdrant answers 503 to selected DELETEs.
func TestCLIQdrant_CleanupReportingAgainstRealQdrant(t *testing.T) {
	qdrantURL := os.Getenv("FLH_QDRANT_URL")
	if qdrantURL == "" {
		t.Skip("FLH_QDRANT_URL not set; real-Qdrant CLI reproduction skipped")
	}
	ctx := context.Background()
	var b [5]byte
	_, _ = rand.Read(b[:])
	prefix := "flh050_it_" + hex.EncodeToString(b[:])
	direct := vectorindex.NewQdrant(qdrantURL, "", 5*time.Second)
	t.Cleanup(func() {
		names, _ := direct.ListCollections(context.Background())
		for _, n := range names {
			if strings.HasPrefix(n, prefix) {
				_ = direct.DeleteCollection(context.Background(), n)
			}
		}
	})

	embeddings := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req struct{ Input []string }
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		type item struct {
			Index     int       `json:"index"`
			Embedding []float64 `json:"embedding"`
		}
		data := make([]item, len(req.Input))
		for i, in := range req.Input {
			sum := sha256.Sum256([]byte(in))
			vec := make([]float64, 8)
			for j := range vec {
				vec[j] = float64(sum[j]) + 1
			}
			data[i] = item{Index: i, Embedding: vec}
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"data": data})
	}))
	t.Cleanup(embeddings.Close)

	target, err := url.Parse(qdrantURL)
	if err != nil {
		t.Fatal(err)
	}
	var blocked atomic.Value // collection name whose DELETE answers 503
	blocked.Store("")
	proxy := httputil.NewSingleHostReverseProxy(target)
	front := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if name := blocked.Load().(string); name != "" && r.Method == http.MethodDelete && r.URL.Path == "/collections/"+name {
			http.Error(w, "blocked by FLH-050 test", http.StatusServiceUnavailable)
			return
		}
		proxy.ServeHTTP(w, r)
	}))
	t.Cleanup(front.Close)

	dbPath := filepath.Join(t.TempDir(), "cli.db")
	for k, v := range map[string]string{
		"SEMANTIC_SEARCH": "qdrant", "QDRANT_URL": front.URL, "QDRANT_COLLECTION_PREFIX": prefix,
		"EMBEDDING_PROVIDER": "http", "EMBEDDING_MODEL": "fake", "EMBEDDING_BASE_URL": embeddings.URL,
		"EMBEDDING_MODEL_ID": "fake/flh050@1", "EMBEDDING_DIMENSIONS": "8", "DB_PATH": dbPath,
	} {
		t.Setenv(k, v)
	}
	db, err := sqlite.Open(dbPath)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	concepts := sqlite.NewConceptRepository(db)
	for _, target := range []string{"subjonctif après il faut que", "passé composé avec être", "accord du participe passé"} {
		if _, _, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: domain.ConceptIdentity{Target: target, PedagogicalIntent: "grammar"}}); err != nil {
			t.Fatal(err)
		}
	}
	space, err := application.NewSemanticIndexSpace(prefix, "fake/flh050@1", 8)
	if err != nil {
		t.Fatal(err)
	}
	store := sqlite.NewSemanticIndexRepository(db)

	cli := func(want int, args ...string) string {
		t.Helper()
		var out, errOut bytes.Buffer
		if code := run(args, &out, &errOut); code != want {
			t.Fatalf("%v: exit %d, want %d\nstdout:\n%s\nstderr:\n%s", args, code, want, out.String(), errOut.String())
		}
		t.Logf("semantic-index %s\n%s%s", strings.Join(args, " "), out.String(), errOut.String())
		return out.String()
	}
	contains := func(text string, wants ...string) {
		t.Helper()
		for _, w := range wants {
			if !strings.Contains(text, w) {
				t.Errorf("missing %q in:\n%s", w, text)
			}
		}
	}
	exists := func(name string) bool {
		t.Helper()
		names, err := direct.ListCollections(ctx)
		if err != nil {
			t.Fatal(err)
		}
		for _, n := range names {
			if n == name {
				return true
			}
		}
		return false
	}
	published := func() string {
		t.Helper()
		st, err := store.SpaceState(ctx, space.Collection)
		if err != nil || st == nil {
			t.Fatalf("space state: %v", err)
		}
		return st.PublishedCollection
	}

	cli(0, "-batch", "2", "build")
	first := published()

	// O1: the replaced collection's deletion keeps failing.
	blocked.Store(first)
	text := cli(0, "-batch", "2", "rebuild")
	contains(text, "published:           yes (replaced "+first+")", "1 pending", "pending:           "+first, "cleanup error:")
	second := published()

	text = cli(0, "-batch", "2", "sync") // exact FLH-047 O1 command
	contains(text, second+" is healthy; published nothing", "cleanup:             removed 0 leftover collection(s); 1 pending",
		"pending:           "+first, "cleanup error:     vector index unavailable", "outcome:             verified_unchanged")
	if strings.Contains(text, "nothing written") {
		t.Errorf("still says nothing written:\n%s", text)
	}
	contains(cli(0, "status"), "leftover:          "+first+" (retired, run ", "removed by the next run, including a healthy sync")
	if !exists(first) {
		t.Fatalf("%s should still exist while its DELETE is blocked", first)
	}

	// Point 4: a healthy sync that cleaned must say so.
	blocked.Store("")
	text = cli(0, "-batch", "2", "sync")
	contains(text, "published nothing", "cleanup:             removed 1 leftover collection(s); 0 pending")
	if strings.Contains(text, "pending:  ") || strings.Contains(text, "cleanup error") {
		t.Errorf("unexpected pending/error:\n%s", text)
	}
	if exists(first) {
		t.Fatalf("%s should have been deleted by the healthy sync", first)
	}

	// O2: another (dead) run's writing collection.
	now := time.Now().UTC()
	other := "other-run-flh050"
	if err := store.AcquireLease(ctx, space, other, "rebuild", now, now.Add(time.Hour), false); err != nil {
		t.Fatal(err)
	}
	orphan := space.PhysicalCollectionName(other)
	if err := store.RegisterCollection(ctx, space.Collection, other, orphan, now); err != nil {
		t.Fatal(err)
	}
	if err := direct.CreateCollection(ctx, orphan, 8); err != nil {
		t.Fatal(err)
	}
	contains(cli(0, "status"), "in progress:       "+orphan+" (writing, run "+other+" holds the lease)")

	text = cli(0, "-batch", "2", "-takeover", "sync")
	contains(text, "published nothing", "removed 0 leftover collection(s); 1 pending", "pending:           "+orphan)
	if strings.Contains(text, "cleanup error") {
		t.Errorf("an ineligible writing collection is not a cleanup error:\n%s", text)
	}
	status := cli(0, "status")
	contains(status, "leftover:          "+orphan+" (writing, run "+other+") — removed only by the next publishing run")
	if strings.Contains(status, orphan+" (writing, run "+other+") — removed by the next run") {
		t.Errorf("status still promises the next run:\n%s", status)
	}
	cli(0, "-batch", "2", "sync") // another healthy sync keeps it, as status says
	if !exists(orphan) {
		t.Fatalf("a healthy sync removed %s", orphan)
	}
	contains(cli(0, "-batch", "2", "rebuild"), "removed 2 leftover collection(s); 0 pending")
	if exists(orphan) {
		t.Fatalf("rebuild left %s", orphan)
	}
	if strings.Contains(cli(0, "status"), "leftover:") {
		t.Errorf("leftovers remain after rebuild")
	}
}
