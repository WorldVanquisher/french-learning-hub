package application_test

import (
	"context"
	"database/sql"
	"errors"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
)

const testDims = 64

type semanticFixture struct {
	t        *testing.T
	dbPath   string
	db       *sql.DB
	store    *sqlite.SemanticIndexRepository
	concepts *fakeConcepts
	provider *fakeProvider
	index    *memIndex
	space    application.SemanticIndexSpace
}

func newSemanticFixture(t *testing.T) *semanticFixture {
	t.Helper()
	f := &semanticFixture{t: t, dbPath: filepath.Join(t.TempDir(), "semantic.db"), provider: newFakeProvider(testDims), index: newMemIndex()}
	f.open()
	f.concepts = newFakeConcepts(
		concept(1, "subjunctive after il faut que", domain.ConceptActive),
		concept(2, "passé composé with être", domain.ConceptActive),
		concept(3, "overview of the subjunctive mood", domain.ConceptOrphaned),
		concept(4, "tu me manques", domain.ConceptRetired),
		concept(5, "bien que takes the subjunctive", domain.ConceptActive),
	)
	space, err := application.NewSemanticIndexSpace("test", "fake/bag-of-words@1", testDims)
	if err != nil {
		t.Fatal(err)
	}
	f.space = space
	return f
}

// open (re)opens the SQLite database, simulating a process restart.
func (f *semanticFixture) open() {
	if f.db != nil {
		f.db.Close()
	}
	db, err := sqlite.Open(f.dbPath)
	if err != nil {
		f.t.Fatal(err)
	}
	f.t.Cleanup(func() { db.Close() })
	f.db, f.store = db, sqlite.NewSemanticIndexRepository(db)
}

func (f *semanticFixture) service(batch int) *application.SemanticIndexService {
	return application.NewSemanticIndexService(f.concepts, f.store, f.index, f.provider, f.space, batch)
}

func (f *semanticFixture) search() *application.SemanticSearchService {
	return application.NewSemanticSearchService(f.concepts, fixedSummarizer{}, f.store, f.index, f.provider, f.space)
}

func (f *semanticFixture) state() *application.SemanticIndexSpaceState {
	f.t.Helper()
	s, err := f.store.SpaceState(context.Background(), f.space.Collection)
	if err != nil {
		f.t.Fatal(err)
	}
	return s
}

func (f *semanticFixture) status() *application.SemanticIndexStatus {
	f.t.Helper()
	st, err := f.service(10).Status(context.Background())
	if err != nil {
		f.t.Fatal(err)
	}
	return st
}

var none = application.SemanticRunOptions{}

func mustRun(t *testing.T, op string, svc *application.SemanticIndexService) *application.SemanticIndexReport {
	t.Helper()
	var r *application.SemanticIndexReport
	var err error
	switch op {
	case "build":
		r, err = svc.Build(context.Background(), none)
	case "sync":
		r, err = svc.Sync(context.Background(), none)
	default:
		r, err = svc.Rebuild(context.Background(), none)
	}
	if err != nil {
		t.Fatalf("%s: %v", op, err)
	}
	return r
}

func TestSemanticIndex_ReuseVerifiedSyncAndRebuildAfterRestart(t *testing.T) {
	f := newSemanticFixture(t)
	r := mustRun(t, "build", f.service(2))
	if r.EmbeddedTexts != 5 || r.Upserted != 5 || !r.Published || r.Outcome != "published" {
		t.Fatalf("build = %+v", r)
	}
	first := r.Collection
	calls1, texts1 := f.provider.counts()

	// A healthy publication: sync verifies the inventory and writes nothing.
	r = mustRun(t, "sync", f.service(2))
	if !r.VerifiedUnchanged || r.Published || r.Upserted != 0 || r.Outcome != "verified_unchanged" {
		t.Fatalf("sync on healthy index = %+v", r)
	}
	if names := f.index.names(); len(names) != 1 || names[0] != first {
		t.Fatalf("collections after no-op sync = %v", names)
	}

	// Restart and rebuild: a fresh collection from cached vectors only.
	f.open()
	r = mustRun(t, "rebuild", f.service(2))
	if r.EmbeddedTexts != 0 || r.ReusedVectors != 5 || !r.Published || r.Replaced != first {
		t.Fatalf("rebuild after restart = %+v", r)
	}
	if names := f.index.names(); len(names) != 1 || names[0] != r.Collection {
		t.Fatalf("replaced collection must be removed: %v", names)
	}
	if calls, texts := f.provider.counts(); calls != calls1 || texts != texts1 {
		t.Fatalf("documents were re-embedded: %d/%d", calls, texts)
	}
	st := f.status()
	if !st.VerifiedHealthy || st.State.PublishedCollection != r.Collection || st.State.LastRunOutcome != "published" || len(st.Collections) != 1 {
		t.Fatalf("status = %+v / %+v", st, st.State)
	}

	before, _ := f.provider.counts()
	for i := 0; i < 3; i++ {
		if _, err := f.search().Search(context.Background(), application.LibrarySearchQuery{Text: "subjunctive", Limit: 5}); err != nil {
			t.Fatal(err)
		}
	}
	if after, _ := f.provider.counts(); after != before+3 {
		t.Fatalf("search provider calls = %d, want 3 (one per query)", after-before)
	}
}

func TestSemanticIndex_HealthDetectsDamageThatPointCountHides(t *testing.T) {
	cases := map[string]struct {
		damage func(f *semanticFixture, col string)
		check  func(h *application.SemanticIndexHealth) bool
	}{
		"one point removed": {
			damage: func(f *semanticFixture, col string) { _ = f.index.Delete(context.Background(), col, []int64{2}) },
			check:  func(h *application.SemanticIndexHealth) bool { return len(h.Missing) == 1 && h.Missing[0] == 2 },
		},
		"point replaced with another vector, count preserved": {
			damage: func(f *semanticFixture, col string) {
				doc, _ := application.BuildSemanticIndexDocument(concept(2, "passé composé with être", domain.ConceptActive))
				v, _ := application.ValidateEmbedding(bagOfWords("completely different words", testDims), testDims)
				f.index.injectPoint(col, 2, doc.ContentHash, f.space, v)
			},
			check: func(h *application.SemanticIndexHealth) bool { return len(h.VectorMismatch) == 1 && h.Points == 5 },
		},
		"point replaced with a stale document hash": {
			damage: func(f *semanticFixture, col string) {
				v, _ := application.ValidateEmbedding(bagOfWords("passé composé", testDims), testDims)
				f.index.injectPoint(col, 2, "old-hash", f.space, v)
			},
			check: func(h *application.SemanticIndexHealth) bool { return len(h.Stale) == 1 && h.Points == 5 },
		},
		"point replaced by another model's payload": {
			damage: func(f *semanticFixture, col string) {
				other := f.space
				other.ModelID = "someone-else"
				v, _ := application.ValidateEmbedding(bagOfWords("x", testDims), testDims)
				f.index.injectPoint(col, 2, "h", other, v)
			},
			check: func(h *application.SemanticIndexHealth) bool { return len(h.ForeignPayload) == 1 },
		},
		"extra point for an unknown id": {
			damage: func(f *semanticFixture, col string) {
				v, _ := application.ValidateEmbedding(bagOfWords("x", testDims), testDims)
				f.index.injectPoint(col, 99, "h", f.space, v)
			},
			check: func(h *application.SemanticIndexHealth) bool { return len(h.Extra) == 1 && h.Extra[0] == 99 },
		},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			f := newSemanticFixture(t)
			col := mustRun(t, "build", f.service(10)).Collection
			c.damage(f, col)
			st := f.status()
			if st.VerifiedHealthy || st.Health.Healthy || !c.check(st.Health) {
				t.Fatalf("health = %+v", st.Health)
			}
			if st.State.LastRunOutcome != "published" {
				t.Fatal("the last run record must stay separate from current health")
			}
			before, _ := f.provider.counts()
			r := mustRun(t, "sync", f.service(10))
			if !r.Published || r.Replaced != col || r.EmbeddedTexts != 0 {
				t.Fatalf("repair sync = %+v", r)
			}
			if after, _ := f.provider.counts(); after != before {
				t.Fatal("repair must reuse cached vectors")
			}
			if st := f.status(); !st.VerifiedHealthy {
				t.Fatalf("after repair: %+v", st.Health)
			}
		})
	}
}

func TestSemanticIndex_WholeCollectionLossAndIncompatibleShape(t *testing.T) {
	f := newSemanticFixture(t)
	col := mustRun(t, "build", f.service(10)).Collection
	_ = f.index.DeleteCollection(context.Background(), col)
	st := f.status()
	if st.VerifiedHealthy || st.Health.Exists {
		t.Fatalf("lost collection: %+v", st.Health)
	}
	if _, err := f.search().Search(context.Background(), application.LibrarySearchQuery{Text: "subjunctive", Limit: 5}); !errors.Is(err, application.ErrSemanticIndexNotBuilt) {
		t.Fatalf("search on lost collection: %v", err)
	}
	r := mustRun(t, "sync", f.service(10))
	if !r.Published || r.EmbeddedTexts != 0 {
		t.Fatalf("sync after loss = %+v", r)
	}

	// Same name, wrong shape.
	col = r.Collection
	_ = f.index.DeleteCollection(context.Background(), col)
	_ = f.index.CreateCollection(context.Background(), col, testDims+1)
	st = f.status()
	if st.Health.ShapeOK || st.VerifiedHealthy {
		t.Fatalf("wrong shape: %+v", st.Health)
	}
	if _, err := f.search().Search(context.Background(), application.LibrarySearchQuery{Text: "subjunctive", Limit: 5}); !errors.Is(err, application.ErrSemanticIndexIncompatible) {
		t.Fatalf("search on wrong shape: %v", err)
	}
	if r := mustRun(t, "sync", f.service(10)); !r.Published {
		t.Fatalf("sync must republish: %+v", r)
	}
	if st := f.status(); !st.VerifiedHealthy {
		t.Fatalf("after repair: %+v", st.Health)
	}
}

// pausedRun starts run A in a goroutine and blocks it at the first gate whose
// step equals pauseAt (after the ownership check, before the guarded action).
type pausedRun struct {
	reached chan struct{}
	release chan struct{}
	done    chan struct{}
	report  *application.SemanticIndexReport
	err     error
}

func startPaused(f *semanticFixture, op, pauseAt string) *pausedRun {
	p := &pausedRun{reached: make(chan struct{}), release: make(chan struct{}), done: make(chan struct{})}
	var once sync.Once
	svc := f.service(2).WithGateHook(func(step string) {
		if step == pauseAt {
			once.Do(func() {
				close(p.reached)
				<-p.release
			})
		}
	})
	go func() {
		defer close(p.done)
		switch op {
		case "sync":
			p.report, p.err = svc.Sync(context.Background(), none)
		default:
			p.report, p.err = svc.Rebuild(context.Background(), none)
		}
	}()
	return p
}

func TestSemanticIndex_SupersededRunCannotMutateNewerPublication(t *testing.T) {
	for _, step := range []string{"embed", "register-collection", "create-collection", "upsert", "record-manifest", "publish", "delete-collection"} {
		t.Run(step, func(t *testing.T) {
			f := newSemanticFixture(t)
			if step != "embed" { // "embed" needs cache misses, so do not prebuild
				mustRun(t, "build", f.service(2))
			}
			if step == "delete-collection" {
				// Make the paused run's cleanup have something to delete.
				f.concepts.set(concept(2, "passé composé with avoir", domain.ConceptActive))
			}
			a := startPaused(f, "rebuild", step)
			select {
			case <-a.reached:
			case <-a.done:
				t.Fatalf("run A finished before reaching %s: %+v %v", step, a.report, a.err)
			}

			// B takes over (the operator asserts A is dead) and publishes.
			b, err := f.service(2).Rebuild(context.Background(), application.SemanticRunOptions{Takeover: true})
			if err != nil || !b.Published {
				t.Fatalf("B: %+v %v", b, err)
			}
			manifestB, _ := f.store.Manifest(context.Background(), b.Collection)
			close(a.release)
			<-a.done

			if step != "delete-collection" && !errors.Is(a.err, application.ErrSemanticIndexOwnershipLost) {
				t.Fatalf("A must stop with ownership lost: %+v %v", a.report, a.err)
			}
			if a.report != nil && a.report.Published && step != "delete-collection" {
				t.Fatalf("A must not publish: %+v", a.report)
			}
			s := f.state()
			if s.PublishedCollection != b.Collection || s.PublishedRunID != b.RunID || s.LastRunID != b.RunID || s.LeaseRunID != "" {
				t.Fatalf("B's publication or run record was changed: %+v", s)
			}
			if after, _ := f.store.Manifest(context.Background(), b.Collection); len(after) != len(manifestB) || len(after) != 5 {
				t.Fatalf("B's manifest changed: %v -> %v", manifestB, after)
			}
			if f.index.pointCount(b.Collection) != 5 {
				t.Fatalf("B's collection was mutated: %d points", f.index.pointCount(b.Collection))
			}
			if a.report != nil && a.report.Collection != "" && a.report.Collection != b.Collection && f.index.pointCount(a.report.Collection) != -1 {
				t.Fatalf("A's private collection %s was left in the vector store", a.report.Collection)
			}
			st := f.status()
			if !st.VerifiedHealthy {
				t.Fatalf("published index must stay healthy: %+v", st.Health)
			}
			// Any record A could not clean up is a visible leftover the next run removes.
			mustRun(t, "rebuild", f.service(2))
			if names := f.index.names(); len(names) != 1 {
				t.Fatalf("leftovers after next rebuild: %v", names)
			}
		})
	}
}

func TestSemanticIndex_BusyLeaseAndExpiredLease(t *testing.T) {
	f := newSemanticFixture(t)
	a := startPaused(f, "rebuild", "upsert")
	<-a.reached
	if _, err := f.service(2).Sync(context.Background(), none); !errors.Is(err, application.ErrSemanticIndexBusy) {
		t.Fatalf("second run must be busy: %v", err)
	}
	if st := f.status(); !st.LeaseActive || st.State.LeaseOperation != "rebuild" {
		t.Fatalf("status must show the held lease: %+v", st.State)
	}
	close(a.release)
	<-a.done
	if a.err != nil || !a.report.Published {
		t.Fatalf("A: %+v %v", a.report, a.err)
	}

	// An expired lease (holder silent beyond its TTL) can be taken without -takeover.
	g := newSemanticFixture(t)
	reached, release := make(chan struct{}), make(chan struct{})
	var once sync.Once
	done := make(chan error)
	go func() {
		_, err := g.service(2).WithLeaseTTL(50*time.Millisecond).WithGateHook(func(step string) {
			if step == "upsert" {
				once.Do(func() { close(reached); <-release })
			}
		}).Rebuild(context.Background(), none)
		done <- err
	}()
	<-reached
	time.Sleep(120 * time.Millisecond)
	if r := mustRun(t, "rebuild", g.service(2)); !r.Published {
		t.Fatalf("taking an expired lease: %+v", r)
	}
	close(release)
	if err := <-done; !errors.Is(err, application.ErrSemanticIndexOwnershipLost) {
		t.Fatalf("expired holder must lose ownership: %v", err)
	}
}

func TestSemanticIndex_InvalidVectorsPublishNothing(t *testing.T) {
	for name, mutate := range map[string]func(*fakeProvider){
		"dimension mismatch": func(p *fakeProvider) { p.badDims = true },
		"nan":                func(p *fakeProvider) { p.nan = true },
		"zero vector":        func(p *fakeProvider) { p.zero = true },
	} {
		t.Run(name, func(t *testing.T) {
			f := newSemanticFixture(t)
			mutate(f.provider)
			r, err := f.service(10).Build(context.Background(), none)
			if !errors.Is(err, application.ErrInvalidEmbedding) || r.Published || r.Outcome != "failed" {
				t.Fatalf("err=%v report=%+v", err, r)
			}
			s := f.state()
			if s.PublishedCollection != "" || !strings.HasPrefix(s.LastError, "invalid embedding") || s.LeaseRunID != "" {
				t.Fatalf("state = %+v", s)
			}
			if counts, _ := f.store.CacheCounts(context.Background()); len(counts) != 0 {
				t.Fatalf("invalid vectors were cached: %+v", counts)
			}
			if names := f.index.names(); len(names) != 0 {
				t.Fatalf("collections left: %v", names)
			}
		})
	}
}

func TestSemanticIndex_FailureAndInterruptionKeepPreviousPublication(t *testing.T) {
	f := newSemanticFixture(t)
	col := mustRun(t, "build", f.service(2)).Collection
	f.concepts.set(concept(6, "new concept one", domain.ConceptActive))
	f.concepts.set(concept(7, "new concept two", domain.ConceptActive))
	f.concepts.set(concept(8, "new concept three", domain.ConceptActive))

	// Provider fails on the second batch of misses.
	f.provider.failCall = f.provider.calls + 2
	r, err := f.service(2).Sync(context.Background(), none)
	if !errors.Is(err, application.ErrEmbeddingProviderUnavailable) || r.Published || r.Outcome != "failed" {
		t.Fatalf("failed sync: %v %+v", err, r)
	}
	if s := f.state(); s.PublishedCollection != col || s.LastRunOutcome != "failed" || s.LastError != "embedding provider unavailable" {
		t.Fatalf("previous publication must stay: %+v", s)
	}
	if names := f.index.names(); len(names) != 1 || names[0] != col {
		t.Fatalf("failed run's collection must be removed: %v", names)
	}

	// Interrupted during the next provider call.
	f.provider.failCall = 0
	ctx, cancel := context.WithCancel(context.Background())
	f.provider.onEmbed = func(call int) { cancel() }
	r, err = f.service(2).Sync(ctx, none)
	if !errors.Is(err, context.Canceled) || r.Outcome != "interrupted" {
		t.Fatalf("interrupted sync: %v %+v", err, r)
	}
	if s := f.state(); s.PublishedCollection != col || s.LastError != "interrupted (canceled)" {
		t.Fatalf("state after interruption: %+v", s)
	}
	f.provider.onEmbed = nil
	r = mustRun(t, "sync", f.service(2))
	if !r.Published || r.ReusedVectors != 7 || r.EmbeddedTexts != 1 {
		t.Fatalf("recovery reuses the batches already embedded: %+v", r)
	}
}

func TestSemanticIndex_CatchUpAndContinuouslyChangingSources(t *testing.T) {
	f := newSemanticFixture(t)
	changed := false
	r, err := f.service(2).WithGateHook(func(step string) {
		if step == "record-manifest" && !changed {
			changed = true
			f.concepts.set(concept(1, "subjunctive after il faut que (revised)", domain.ConceptActive))
		}
	}).Build(context.Background(), none)
	if err != nil || !r.Published || r.CatchUpChanges != 1 {
		t.Fatalf("catch-up: %+v %v", r, err)
	}
	if !f.status().VerifiedHealthy {
		t.Fatal("published collection must match current sources")
	}

	col := r.Collection
	n := 0
	r, err = f.service(2).WithGateHook(func(step string) {
		if step == "record-manifest" {
			n++
			f.concepts.set(concept(1, "revision "+strings.Repeat("x", n), domain.ConceptActive))
		}
	}).Rebuild(context.Background(), none)
	if !errors.Is(err, application.ErrSemanticSourcesChanged) || r.Published || r.Outcome != "sources_changed" {
		t.Fatalf("continuous change: %+v %v", r, err)
	}
	if s := f.state(); s.PublishedCollection != col {
		t.Fatalf("previous publication must stay: %+v", s)
	}
}

func TestSemanticIndex_BuildRefusesAndCleanupFailureIsVisible(t *testing.T) {
	f := newSemanticFixture(t)
	col := mustRun(t, "build", f.service(10)).Collection
	if _, err := f.service(10).Build(context.Background(), none); !errors.Is(err, application.ErrSemanticIndexExists) {
		t.Fatalf("second build: %v", err)
	}
	f.index.failDelete[col] = true
	r := mustRun(t, "rebuild", f.service(10))
	if !r.Published || r.Replaced != col {
		t.Fatalf("rebuild: %+v", r)
	}
	st := f.status()
	found := false
	for _, c := range st.Collections {
		if c.Collection == col && c.Status == "retired" {
			found = true
		}
	}
	if !found || !st.VerifiedHealthy {
		t.Fatalf("an undeletable replaced collection must stay visible as retired: %+v", st.Collections)
	}
	delete(f.index.failDelete, col)
	mustRun(t, "rebuild", f.service(10))
	if names := f.index.names(); len(names) != 1 {
		t.Fatalf("next run removes the leftover: %v", names)
	}
}

func TestSemanticIndex_ModelChangeUsesSeparateSpace(t *testing.T) {
	f := newSemanticFixture(t)
	old := mustRun(t, "build", f.service(10))
	space, err := application.NewSemanticIndexSpace("test", "fake/bag-of-words@2", testDims)
	if err != nil {
		t.Fatal(err)
	}
	f.space = space
	if _, err := f.search().Search(context.Background(), application.LibrarySearchQuery{Text: "subjunctive", Limit: 5}); !errors.Is(err, application.ErrSemanticIndexNotBuilt) {
		t.Fatalf("new space must not use old vectors: %v", err)
	}
	r := mustRun(t, "build", f.service(10))
	if r.EmbeddedTexts != 5 || r.ReusedVectors != 0 {
		t.Fatalf("new model re-embeds everything: %+v", r)
	}
	st := f.status()
	if len(st.OtherSpaces) != 1 || st.OtherSpaces[0].PublishedCollection != old.Collection || len(st.CacheCounts) != 2 {
		t.Fatalf("status: %+v", st)
	}
	if f.index.pointCount(old.Collection) != 5 {
		t.Fatal("the old space's collection must be untouched")
	}
}
