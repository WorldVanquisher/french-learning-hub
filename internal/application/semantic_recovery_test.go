package application_test

import (
	"context"
	"errors"
	"slices"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/application"
)

// FLH-044: publication replacement during search, and leftover cleanup on a
// healthy (verified unchanged) sync.

var recoveryQuery = application.LibrarySearchQuery{Text: "subjunctive", Limit: 5}

// replacer makes the fake index publish a new collection (a full
// rebuild, which also deletes the replaced one) the first time search touches
// each listed collection through the given hook point. Calls made by the
// rebuild itself are ignored.
type replacer struct {
	f         *semanticFixture
	targets   map[string]bool
	inRebuild bool
	chain     bool // also replace each newly published collection when touched
	published []string
}

func (r *replacer) hit(collection string) {
	if r.inRebuild || !r.targets[collection] {
		return
	}
	delete(r.targets, collection)
	r.inRebuild = true
	defer func() { r.inRebuild = false }()
	next := mustRun(r.f.t, "rebuild", r.f.service(10)).Collection
	r.published = append(r.published, next)
	if r.chain {
		r.targets[next] = true
	}
}

func (r *replacer) withChain() *replacer { r.chain = true; return r }

func newReplacer(f *semanticFixture, targets ...string) *replacer {
	r := &replacer{f: f, targets: map[string]bool{}}
	for _, t := range targets {
		r.targets[t] = true
	}
	return r
}

type searchRun struct {
	rep                   *application.SemanticSearchReport
	err                   error
	calls, texts, queries int // provider calls/texts and vector queries made by this search
}

func searchCounts(f *semanticFixture) searchRun {
	c0, t0 := f.provider.counts()
	q0 := f.index.queries
	rep, err := f.search().Search(context.Background(), recoveryQuery)
	c1, t1 := f.provider.counts()
	return searchRun{rep, err, c1 - c0, t1 - t0, f.index.queries - q0}
}

func TestSemanticSearch_ReplacementBeforeMetadataRecoversWithOneEmbedding(t *testing.T) {
	f := newSemanticFixture(t)
	first := mustRun(t, "build", f.service(10)).Collection
	r := newReplacer(f, first)
	f.index.onInfo = r.hit

	s := searchCounts(f)
	rep, err, calls, texts, queries := s.rep, s.err, s.calls, s.texts, s.queries
	if err != nil {
		t.Fatalf("search across a replacement before CollectionInfo: %v", err)
	}
	if len(r.published) != 1 || rep.Collection != r.published[0] || rep.Publication.PublishedCollection != r.published[0] || len(rep.Results) != 3 {
		t.Fatalf("report = %+v (replaced by %v)", rep, r.published)
	}
	if slices.Contains(f.index.names(), first) {
		t.Fatal("the replaced collection must really be gone for this case")
	}
	// The query was embedded once, after the retry found the new publication.
	if calls != 1 || texts != 1 || queries != 1 {
		t.Fatalf("provider calls %d, texts %d, vector queries %d; want 1, 1, 1", calls, texts, queries)
	}
}

func TestSemanticSearch_ReplacementBeforeQueryReusesTheQueryVector(t *testing.T) {
	f := newSemanticFixture(t)
	first := mustRun(t, "build", f.service(10)).Collection
	r := newReplacer(f, first)
	f.index.onQuery = r.hit

	s := searchCounts(f)
	rep, err, calls, texts, queries := s.rep, s.err, s.calls, s.texts, s.queries
	if err != nil {
		t.Fatalf("search across a replacement before Query: %v", err)
	}
	if len(r.published) != 1 || rep.Collection != r.published[0] || len(rep.Results) != 3 {
		t.Fatalf("report = %+v (replaced by %v)", rep, r.published)
	}
	if calls != 1 || texts != 1 || queries != 2 {
		t.Fatalf("provider calls %d, texts %d, vector queries %d; want 1, 1, 2 (vector reused)", calls, texts, queries)
	}
}

func TestSemanticSearch_RepeatedReplacementEndsAfterOneRetry(t *testing.T) {
	cases := []struct {
		name                   string
		hook                   func(f *semanticFixture, r *replacer)
		wantCalls, wantQueries int
	}{
		{"metadata then metadata", func(f *semanticFixture, r *replacer) { f.index.onInfo = r.hit }, 0, 0},
		{"query then metadata", func(f *semanticFixture, r *replacer) {
			f.index.onQuery = r.hit // one-shot: the first query
			f.index.onInfo = func(c string) {
				if len(r.published) > 0 { // only after the first replacement
					r.hit(c)
				}
			}
		}, 1, 1},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			f := newSemanticFixture(t)
			first := mustRun(t, "build", f.service(10)).Collection
			r := newReplacer(f, first).withChain()
			tc.hook(f, r)

			s := searchCounts(f)
			err, calls, queries := s.err, s.calls, s.queries
			if !errors.Is(err, application.ErrSemanticPublicationChanged) {
				t.Fatalf("second replacement: %v", err)
			}
			if errors.Is(err, application.ErrSemanticIndexNotBuilt) {
				t.Fatal("a replaced publication must not be reported as not built")
			}
			// Exactly two replacements were observed: the budget is one retry.
			if len(r.published) != 2 || calls != tc.wantCalls || queries != tc.wantQueries {
				t.Fatalf("replacements %v, provider calls %d, queries %d", r.published, calls, queries)
			}
			f.index.onInfo, f.index.onQuery = nil, nil
			// The index is healthy; the next search simply works.
			if rep, err := f.search().Search(context.Background(), recoveryQuery); err != nil || rep.Collection != r.published[1] {
				t.Fatalf("next search: %+v, %v", rep, err)
			}
		})
	}
}

func TestSemanticSearch_MissingCollectionWithUnchangedPointerStaysAnError(t *testing.T) {
	f := newSemanticFixture(t)
	col := mustRun(t, "build", f.service(10)).Collection

	// Lost before metadata: no provider call, no query.
	if err := f.index.DeleteCollection(context.Background(), col); err != nil {
		t.Fatal(err)
	}
	s := searchCounts(f)
	err, calls, queries := s.err, s.calls, s.queries
	if !errors.Is(err, application.ErrSemanticIndexNotBuilt) || !strings.Contains(err.Error(), col) || calls != 0 || queries != 0 {
		t.Fatalf("lost collection: %v (calls %d, queries %d)", err, calls, queries)
	}

	// Lost between metadata and query: one embedding, one query, no retry.
	mustRun(t, "sync", f.service(10))
	col = f.state().PublishedCollection
	f.index.onQuery = func(c string) { _ = f.index.DeleteCollection(context.Background(), c) }
	s = searchCounts(f)
	err, calls, queries = s.err, s.calls, s.queries
	if !errors.Is(err, application.ErrSemanticIndexNotBuilt) || calls != 1 || queries != 1 {
		t.Fatalf("lost before query: %v (calls %d, queries %d)", err, calls, queries)
	}
	if f.state().PublishedCollection != col {
		t.Fatal("search must not write")
	}
}

// leftover returns the physical record for collection, or nil.
func leftover(t *testing.T, f *semanticFixture, collection string) *application.PhysicalCollection {
	t.Helper()
	cs, err := f.store.PhysicalCollections(context.Background(), f.space.Collection)
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range cs {
		if c.Collection == collection {
			return &c
		}
	}
	return nil
}

func manifestSize(t *testing.T, f *semanticFixture, collection string) int {
	t.Helper()
	m, err := f.store.Manifest(context.Background(), collection)
	if err != nil {
		t.Fatal(err)
	}
	return len(m)
}

func TestSemanticIndex_HealthySyncRemovesRecordedLeftovers(t *testing.T) {
	f := newSemanticFixture(t)
	old := mustRun(t, "build", f.service(10)).Collection
	f.index.failDelete[old] = true
	r := mustRun(t, "rebuild", f.service(10))
	current := r.Collection
	if !r.Published || r.Replaced != old || !slices.Equal(r.CleanupPending, []string{old}) || r.CleanupError != "vector index unavailable" {
		t.Fatalf("rebuild with failed deletion: %+v", r)
	}
	if st := f.state(); !strings.HasPrefix(st.LastError, "cleanup incomplete: 1 leftover") || st.LastRunOutcome != "published" {
		t.Fatalf("a successful run with incomplete cleanup must say so: %+v", st)
	}
	if c := leftover(t, f, old); c == nil || c.Status != "retired" || manifestSize(t, f, old) != 5 {
		t.Fatalf("retired record must be kept: %+v", c)
	}

	// The fault persists: a healthy sync tries again and reports the failure.
	r = mustRun(t, "sync", f.service(10))
	if !r.VerifiedUnchanged || r.Outcome != "verified_unchanged" || r.Cleaned != 0 || !slices.Equal(r.CleanupPending, []string{old}) || r.CleanupError == "" {
		t.Fatalf("healthy sync with failing deletion: %+v", r)
	}
	if st := f.status(); !st.VerifiedHealthy || !strings.HasPrefix(st.State.LastError, "cleanup incomplete") || leftover(t, f, old) == nil {
		t.Fatalf("status must show the failure and the leftover: %+v", st.State)
	}

	// The fault clears; only a healthy sync runs. It removes the real old
	// collection and its record and manifest, embeds nothing and keeps the
	// publication.
	delete(f.index.failDelete, old)
	_, texts0 := f.provider.counts()
	r = mustRun(t, "sync", f.service(10))
	if _, texts1 := f.provider.counts(); texts1 != texts0 {
		t.Fatalf("cleanup sync embedded %d texts", texts1-texts0)
	}
	if !r.VerifiedUnchanged || r.Published || r.Upserted != 0 || r.Cleaned != 1 || len(r.CleanupPending) != 0 || r.CleanupError != "" {
		t.Fatalf("healthy sync cleanup: %+v", r)
	}
	if names := f.index.names(); !slices.Equal(names, []string{current}) {
		t.Fatalf("vector collections = %v, want only %s", names, current)
	}
	if leftover(t, f, old) != nil || manifestSize(t, f, old) != 0 {
		t.Fatal("old record and manifest must be removed")
	}
	st := f.status()
	if st.State.PublishedCollection != current || st.State.LastError != "" || !st.VerifiedHealthy || len(st.Collections) != 1 {
		t.Fatalf("status after cleanup: %+v %+v", st.State, st.Collections)
	}
}

func TestSemanticIndex_HealthySyncLeavesOtherRunsWritingCollections(t *testing.T) {
	f := newSemanticFixture(t)
	mustRun(t, "build", f.service(10))
	// A run that registered and created its private collection, then died or
	// was superseded. Its collection is "writing", not a terminal leftover.
	ctx := context.Background()
	now := time.Now()
	ghost := f.space.PhysicalCollectionName("0123456789abcdef01234567")
	if err := f.store.AcquireLease(ctx, f.space, "0123456789abcdef01234567", "rebuild", now, now.Add(time.Hour), false); err != nil {
		t.Fatal(err)
	}
	if err := f.store.RegisterCollection(ctx, f.space.Collection, "0123456789abcdef01234567", ghost, now); err != nil {
		t.Fatal(err)
	}
	if err := f.index.CreateCollection(ctx, ghost, testDims); err != nil {
		t.Fatal(err)
	}

	r, err := f.service(10).Sync(ctx, application.SemanticRunOptions{Takeover: true})
	if err != nil {
		t.Fatal(err)
	}
	if !r.VerifiedUnchanged || r.Cleaned != 0 || !slices.Equal(r.CleanupPending, []string{ghost}) {
		t.Fatalf("no-op sync must not delete another run's writing collection: %+v", r)
	}
	if !slices.Contains(f.index.names(), ghost) || leftover(t, f, ghost) == nil {
		t.Fatal("writing collection must remain")
	}
	// A publishing run (which held the lease throughout) removes it as before.
	if r := mustRun(t, "rebuild", f.service(10)); r.Cleaned < 2 || len(r.CleanupPending) != 0 || slices.Contains(f.index.names(), ghost) {
		t.Fatalf("rebuild cleanup: %+v, %v", r, f.index.names())
	}
}

func TestSemanticIndex_LeaseLossStopsHealthySyncCleanup(t *testing.T) {
	f := newSemanticFixture(t)
	a := mustRun(t, "build", f.service(10)).Collection
	f.index.failDelete[a] = true
	b := mustRun(t, "rebuild", f.service(10)).Collection
	f.index.failDelete[b] = true
	c := mustRun(t, "rebuild", f.service(10)).Collection
	f.index.failDelete = map[string]bool{}
	before := f.state()

	// At the first deletion gate (lease just renewed), another run takes over.
	ctx := context.Background()
	gates := 0
	svc := f.service(10).WithGateHook(func(step string) {
		if step != "delete-collection" {
			return
		}
		gates++
		if gates == 1 {
			now := time.Now()
			if err := f.store.AcquireLease(ctx, f.space, "fedcba9876543210fedcba98", "sync", now, now.Add(time.Hour), true); err != nil {
				t.Error(err)
			}
		}
	})
	r, err := svc.Sync(ctx, none)
	if !errors.Is(err, application.ErrSemanticIndexOwnershipLost) || !r.OwnershipLost || gates != 1 {
		t.Fatalf("sync after lease loss: %+v, %v (gates %d)", r, err, gates)
	}
	// The first leftover was already past its gate: deleting a retired
	// collection is harmless, but its record could not be forgotten (fenced).
	// The other was never touched.
	if leftover(t, f, a) == nil || leftover(t, f, b) == nil || len(f.index.names()) != 2 {
		t.Fatalf("records must remain and one leftover must be untouched; collections %v", f.index.names())
	}
	pending := slices.Sorted(slices.Values(r.CleanupPending))
	if want := slices.Sorted(slices.Values([]string{a, b})); !slices.Equal(pending, want) || r.Cleaned != 0 {
		t.Fatalf("pending = %v, cleaned %d", r.CleanupPending, r.Cleaned)
	}
	after := f.state()
	if after.PublishedCollection != c || after.LeaseRunID != "fedcba9876543210fedcba98" || after.LastRunID != before.LastRunID || !slices.Contains(f.index.names(), c) {
		t.Fatalf("publication, lease and run record must belong to the newer owner: %+v", after)
	}
}
