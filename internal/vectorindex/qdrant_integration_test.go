package vectorindex_test

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"
	"unicode"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
	"french-learning-app/internal/vectorindex"
)

// Integration tests against an actual local Qdrant (FLH-040, run consistency
// FLH-042). They run only when FLH_QDRANT_URL is set (for example
// http://127.0.0.1:16333), use a unique task-owned collection prefix and delete
// every collection with it afterwards. The embedding provider is a
// deterministic bag-of-words fake: these tests prove index mechanics, never
// semantic quality.

func qdrantURL(t *testing.T) string {
	t.Helper()
	u := os.Getenv("FLH_QDRANT_URL")
	if u == "" {
		t.Skip("FLH_QDRANT_URL not set; skipping real-Qdrant integration test")
	}
	return u
}

type countingProvider struct {
	mu    sync.Mutex
	dims  int
	calls int
	texts int
	hook  func(call int)
}

func (p *countingProvider) Name() string { return "fake:bag-of-words" }

func (p *countingProvider) Embed(ctx context.Context, texts []string) ([][]float64, error) {
	p.mu.Lock()
	p.calls++
	call, hook := p.calls, p.hook
	p.mu.Unlock()
	if hook != nil {
		hook(call)
	}
	if err := ctx.Err(); err != nil {
		return nil, errors.Join(application.ErrEmbeddingProviderUnavailable, err)
	}
	p.mu.Lock()
	p.texts += len(texts)
	p.mu.Unlock()
	out := make([][]float64, len(texts))
	for i, t := range texts {
		out[i] = bagOfWords(t, p.dims)
	}
	return out, nil
}

func (p *countingProvider) counts() (int, int) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.calls, p.texts
}

func bagOfWords(text string, dims int) []float64 {
	ignore := map[string]bool{"representation": true, "type": true, "concept": true, "target": true, "pedagogical_intent": true,
		"scope": true, "identity_features": true, "key": true, "value": true, "concept_embedding_text_v1": true}
	v := make([]float64, dims)
	for _, w := range strings.FieldsFunc(strings.ToLower(text), func(r rune) bool { return !unicode.IsLetter(r) && !unicode.IsDigit(r) && r != '_' }) {
		if len([]rune(w)) < 2 || ignore[w] {
			continue
		}
		sum := sha256.Sum256([]byte(w))
		v[int(binary.BigEndian.Uint32(sum[:4])%uint32(dims))] += 1
	}
	for _, x := range v {
		if x != 0 {
			return v
		}
	}
	v[dims-1] = 1 // a text with no words still gets a valid vector
	return v
}

type conceptList struct {
	mu       sync.Mutex
	concepts []domain.KnowledgeConcept
}

func (c *conceptList) ListConcepts(_ context.Context, state *domain.ConceptState) ([]domain.KnowledgeConcept, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	var out []domain.KnowledgeConcept
	for _, x := range c.concepts {
		if state == nil || x.State == *state {
			out = append(out, x)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out, nil
}

type counts struct{}

func (counts) ConceptCounts(context.Context, int64) (int, int, error) { return 0, 0, nil }

func mk(id int64, target string, state domain.ConceptState) domain.KnowledgeConcept {
	return domain.KnowledgeConcept{ID: id, Target: target, PedagogicalIntent: "grammar", IdentityFeatures: map[string]string{"mood": "subjonctif"}, State: state}
}

type rig struct {
	t        *testing.T
	dbPath   string
	store    *sqlite.SemanticIndexRepository
	qdrant   *vectorindex.Qdrant
	provider *countingProvider
	concepts *conceptList
	space    application.SemanticIndexSpace
	prefix   string
}

func newRig(t *testing.T) *rig {
	url := qdrantURL(t)
	var b [6]byte
	_, _ = rand.Read(b[:])
	prefix := "flh042_it_" + hex.EncodeToString(b[:])
	space, err := application.NewSemanticIndexSpace(prefix, "fake/bag-of-words@it", 32)
	if err != nil {
		t.Fatal(err)
	}
	r := &rig{t: t, dbPath: filepath.Join(t.TempDir(), "it.db"), qdrant: vectorindex.NewQdrant(url, "", 5*time.Second),
		provider: &countingProvider{dims: 32}, space: space, prefix: prefix,
		concepts: &conceptList{concepts: []domain.KnowledgeConcept{
			mk(1, "subjunctive after il faut que", domain.ConceptActive),
			mk(2, "passé composé with être", domain.ConceptActive),
			mk(3, "overview of the subjunctive mood", domain.ConceptOrphaned),
			mk(4, "bien que takes the subjunctive", domain.ConceptRetired),
		}}}
	r.open()
	cleanup := vectorindex.NewQdrant(url, "", 5*time.Second)
	t.Cleanup(func() {
		names, _ := cleanup.ListCollections(context.Background())
		for _, n := range names {
			if strings.HasPrefix(n, prefix) {
				_ = cleanup.DeleteCollection(context.Background(), n)
			}
		}
	})
	return r
}

func (r *rig) open() {
	db, err := sqlite.Open(r.dbPath)
	if err != nil {
		r.t.Fatal(err)
	}
	r.t.Cleanup(func() { db.Close() })
	r.store = sqlite.NewSemanticIndexRepository(db)
}

func (r *rig) svc() *application.SemanticIndexService {
	return application.NewSemanticIndexService(r.concepts, r.store, r.qdrant, r.provider, r.space, 2)
}

func (r *rig) run(op string, opts application.SemanticRunOptions) (*application.SemanticIndexReport, error) {
	switch op {
	case "build":
		return r.svc().Build(context.Background(), opts)
	case "sync":
		return r.svc().Sync(context.Background(), opts)
	}
	return r.svc().Rebuild(context.Background(), opts)
}

func (r *rig) mustRun(op string) *application.SemanticIndexReport {
	r.t.Helper()
	rep, err := r.run(op, application.SemanticRunOptions{})
	if err != nil {
		r.t.Fatalf("%s: %v", op, err)
	}
	return rep
}

func (r *rig) search(q string, state *domain.ConceptState) (*application.SemanticSearchReport, error) {
	return application.NewSemanticSearchService(r.concepts, counts{}, r.store, r.qdrant, r.provider, r.space).
		Search(context.Background(), application.LibrarySearchQuery{Text: q, State: state, Limit: 10})
}

func (r *rig) status() *application.SemanticIndexStatus {
	r.t.Helper()
	st, err := r.svc().Status(context.Background())
	if err != nil {
		r.t.Fatal(err)
	}
	return st
}

// collections returns the task's Qdrant collections.
func (r *rig) collections() []string {
	r.t.Helper()
	names, err := r.qdrant.ListCollections(context.Background())
	if err != nil {
		r.t.Fatal(err)
	}
	var out []string
	for _, n := range names {
		if strings.HasPrefix(n, r.prefix) {
			out = append(out, n)
		}
	}
	sort.Strings(out)
	return out
}

// inventory scrolls every point of a collection (payload and vector).
func (r *rig) inventory(collection string) map[int64]application.StoredPoint {
	r.t.Helper()
	out := map[int64]application.StoredPoint{}
	var offset *int64
	for {
		page, next, err := r.qdrant.Scroll(context.Background(), collection, offset, 2)
		if err != nil {
			r.t.Fatal(err)
		}
		for _, p := range page {
			out[p.ConceptID] = p
		}
		if next == nil {
			return out
		}
		offset = next
	}
}

// assertPublishedMatchesSQLite compares the full Qdrant inventory of the
// published collection with the manifest, the current documents and the
// cached vectors.
func (r *rig) assertPublishedMatchesSQLite() string {
	r.t.Helper()
	ctx := context.Background()
	st, err := r.store.SpaceState(ctx, r.space.Collection)
	if err != nil || st == nil || st.PublishedCollection == "" {
		r.t.Fatalf("no publication: %+v %v", st, err)
	}
	inv := r.inventory(st.PublishedCollection)
	manifest, _ := r.store.Manifest(ctx, st.PublishedCollection)
	concepts, _ := r.concepts.ListConcepts(ctx, nil)
	if len(inv) != len(concepts) || len(manifest) != len(concepts) {
		r.t.Fatalf("inventory %d, manifest %d, concepts %d", len(inv), len(manifest), len(concepts))
	}
	for _, c := range concepts {
		doc, _ := application.BuildSemanticIndexDocument(c)
		p := inv[c.ID]
		if !p.PayloadValid || p.ContentHash != doc.ContentHash || manifest[c.ID] != doc.ContentHash || p.ModelID != r.space.ModelID {
			r.t.Fatalf("point %d: %+v manifest %q doc %q", c.ID, p, manifest[c.ID], doc.ContentHash)
		}
		cached, _ := r.store.CachedVectors(ctx, r.space, []string{doc.ContentHash})
		if !sameDirection(p.Vector, cached[doc.ContentHash]) {
			r.t.Fatalf("point %d vector differs from the cached embedding", c.ID)
		}
	}
	return st.PublishedCollection
}

func sameDirection(a, b []float32) bool {
	if len(a) != len(b) || len(a) == 0 {
		return false
	}
	var na, nb float64
	for i := range a {
		na += float64(a[i]) * float64(a[i])
		nb += float64(b[i]) * float64(b[i])
	}
	na, nb = math.Sqrt(na), math.Sqrt(nb)
	for i := range a {
		if math.Abs(float64(a[i])/na-float64(b[i])/nb) > 1e-4 {
			return false
		}
	}
	return true
}

func TestQdrantIntegration_BuildSyncRebuildRestartAndCacheReuse(t *testing.T) {
	r := newRig(t)
	b := r.mustRun("build")
	if !b.Published || b.EmbeddedTexts != 4 {
		t.Fatalf("build: %+v", b)
	}
	r.assertPublishedMatchesSQLite()
	res, err := r.search("subjunctive", nil)
	if err != nil || len(res.Results) != 3 || res.Collection != b.Collection {
		t.Fatalf("search: %+v %v", res, err)
	}
	calls, texts := r.provider.counts()

	s := r.mustRun("sync")
	if !s.VerifiedUnchanged || s.Published {
		t.Fatalf("sync on healthy index: %+v", s)
	}
	if got := r.collections(); len(got) != 1 || got[0] != b.Collection {
		t.Fatalf("collections after no-op sync: %v", got)
	}

	r.open() // restart
	rb := r.mustRun("rebuild")
	if !rb.Published || rb.EmbeddedTexts != 0 || rb.Replaced != b.Collection {
		t.Fatalf("rebuild: %+v", rb)
	}
	if got := r.collections(); len(got) != 1 || got[0] != rb.Collection {
		t.Fatalf("collections after rebuild: %v", got)
	}
	r.assertPublishedMatchesSQLite()
	if c, x := r.provider.counts(); c != calls || x != texts {
		t.Fatalf("documents were re-embedded: %d/%d -> %d/%d", calls, texts, c, x)
	}
	if st := r.status(); !st.VerifiedHealthy || st.State.LastRunOutcome != "published" {
		t.Fatalf("status: %+v", st)
	}
}

func TestQdrantIntegration_SupersededRunCannotMutateNewerPublication(t *testing.T) {
	for _, step := range []string{"upsert", "record-manifest", "publish"} {
		t.Run(step, func(t *testing.T) {
			r := newRig(t)
			r.mustRun("build")
			reached, release, done := make(chan struct{}), make(chan struct{}), make(chan struct{})
			var once sync.Once
			var aRep *application.SemanticIndexReport
			var aErr error
			go func() {
				defer close(done)
				aRep, aErr = r.svc().WithGateHook(func(s string) {
					if s == step {
						once.Do(func() { close(reached); <-release })
					}
				}).Rebuild(context.Background(), application.SemanticRunOptions{})
			}()
			<-reached

			bRep, err := r.run("rebuild", application.SemanticRunOptions{Takeover: true})
			if err != nil || !bRep.Published {
				t.Fatalf("B: %+v %v", bRep, err)
			}
			close(release)
			<-done
			if !errors.Is(aErr, application.ErrSemanticIndexOwnershipLost) || aRep.Published {
				t.Fatalf("A: %+v %v", aRep, aErr)
			}
			published := r.assertPublishedMatchesSQLite()
			if published != bRep.Collection {
				t.Fatalf("published %s, want B's %s", published, bRep.Collection)
			}
			st, _ := r.store.SpaceState(context.Background(), r.space.Collection)
			if st.LastRunID != bRep.RunID || st.PublishedRunID != bRep.RunID || st.LeaseRunID != "" {
				t.Fatalf("B's records changed: %+v", st)
			}
			for _, c := range r.collections() {
				if c == aRep.Collection {
					t.Fatalf("A's private collection %s left in Qdrant", c)
				}
			}
			if !r.status().VerifiedHealthy {
				t.Fatal("published collection must verify healthy")
			}
		})
	}
}

// The narrowest window: A has passed its last gate and is about to publish;
// B takes over with a sync that finds the publication healthy, so B cleans up
// nothing and A's collection record still looks like A's own. Only the lease
// fence on the publish transaction can stop A here.
func TestQdrantIntegration_FencedPublishAfterNoOpTakeover(t *testing.T) {
	r := newRig(t)
	first := r.mustRun("build").Collection
	reached, release, done := make(chan struct{}), make(chan struct{}), make(chan struct{})
	var once sync.Once
	var aRep *application.SemanticIndexReport
	var aErr error
	go func() {
		defer close(done)
		aRep, aErr = r.svc().WithGateHook(func(s string) {
			if s == "publish" {
				once.Do(func() { close(reached); <-release })
			}
		}).Rebuild(context.Background(), application.SemanticRunOptions{})
	}()
	<-reached
	bRep, err := r.run("sync", application.SemanticRunOptions{Takeover: true})
	if err != nil || !bRep.VerifiedUnchanged {
		t.Fatalf("B: %+v %v", bRep, err)
	}
	close(release)
	<-done
	if !errors.Is(aErr, application.ErrSemanticIndexOwnershipLost) || aRep.Published {
		t.Fatalf("A must not publish after losing the lease: %+v %v", aRep, aErr)
	}
	if got := r.assertPublishedMatchesSQLite(); got != first {
		t.Fatalf("publication changed to %s", got)
	}
	st, _ := r.store.SpaceState(context.Background(), r.space.Collection)
	if st.LastRunID != bRep.RunID || st.LastRunOutcome != "verified_unchanged" {
		t.Fatalf("run record: %+v", st)
	}
}

func TestQdrantIntegration_PointLossAndSameCountReplacementAreDetectedAndRepaired(t *testing.T) {
	r := newRig(t)
	col := r.mustRun("build").Collection
	ctx := context.Background()

	if err := r.qdrant.Delete(ctx, col, []int64{2}); err != nil {
		t.Fatal(err)
	}
	st := r.status()
	if st.VerifiedHealthy || len(st.Health.Missing) != 1 || st.Health.Missing[0] != 2 {
		t.Fatalf("missing point: %+v", st.Health)
	}
	s := r.mustRun("sync")
	if !s.Published || s.EmbeddedTexts != 0 {
		t.Fatalf("repair sync: %+v", s)
	}
	col = r.assertPublishedMatchesSQLite()

	// Replace point 3's vector with point 2's, keeping its id, payload and the count.
	inv := r.inventory(col)
	doc3, _ := application.BuildSemanticIndexDocument(mk(3, "overview of the subjunctive mood", domain.ConceptOrphaned))
	if err := r.qdrant.Upsert(ctx, col, r.space, []application.VectorPoint{{ConceptID: 3, ContentHash: doc3.ContentHash, Vector: inv[2].Vector}}); err != nil {
		t.Fatal(err)
	}
	if info, _ := r.qdrant.CollectionInfo(ctx, col); info.PointCount != 4 {
		t.Fatalf("count must be preserved: %d", info.PointCount)
	}
	st = r.status()
	if st.VerifiedHealthy || len(st.Health.VectorMismatch) != 1 || st.Health.VectorMismatch[0] != 3 {
		t.Fatalf("replaced vector: %+v", st.Health)
	}
	r.mustRun("sync")
	r.assertPublishedMatchesSQLite()
	if !r.status().VerifiedHealthy {
		t.Fatal("after repair")
	}
}

func TestQdrantIntegration_WholeCollectionLossAndIncompatibleShape(t *testing.T) {
	r := newRig(t)
	col := r.mustRun("build").Collection
	ctx := context.Background()
	_ = r.qdrant.DeleteCollection(ctx, col)
	if st := r.status(); st.VerifiedHealthy || st.Health.Exists {
		t.Fatalf("lost: %+v", st.Health)
	}
	if _, err := r.search("subjunctive", nil); !errors.Is(err, application.ErrSemanticIndexNotBuilt) {
		t.Fatalf("search on lost collection: %v", err)
	}
	col = r.mustRun("sync").Collection
	_ = r.qdrant.DeleteCollection(ctx, col)
	if err := r.qdrant.CreateCollection(ctx, col, 33); err != nil {
		t.Fatal(err)
	}
	if st := r.status(); st.Health.ShapeOK || st.Health.Dimensions != 33 {
		t.Fatalf("shape: %+v", st.Health)
	}
	if _, err := r.search("subjunctive", nil); !errors.Is(err, application.ErrSemanticIndexIncompatible) {
		t.Fatalf("search on wrong shape: %v", err)
	}
	r.mustRun("sync")
	r.assertPublishedMatchesSQLite()
}

func TestQdrantIntegration_InterruptionKeepsPreviousPublication(t *testing.T) {
	r := newRig(t)
	col := r.mustRun("build").Collection
	r.concepts.mu.Lock()
	r.concepts.concepts = append(r.concepts.concepts, mk(5, "accord du participe passé", domain.ConceptActive))
	r.concepts.mu.Unlock()

	ctx, cancel := context.WithCancel(context.Background())
	n := 0
	rep, err := r.svc().WithGateHook(func(step string) {
		if step == "upsert" {
			if n++; n == 2 {
				cancel() // interrupt between two upsert batches into the new collection
			}
		}
	}).Sync(ctx, application.SemanticRunOptions{})
	if !errors.Is(err, context.Canceled) || rep.Published || rep.Outcome != "interrupted" {
		t.Fatalf("interrupted sync: %+v %v", rep, err)
	}
	if got := r.collections(); len(got) != 1 || got[0] != col {
		t.Fatalf("interrupted run's collection must be removed: %v", got)
	}
	st, _ := r.store.SpaceState(context.Background(), r.space.Collection)
	if st.PublishedCollection != col || st.LastRunOutcome != "interrupted" {
		t.Fatalf("state: %+v", st)
	}
	if res, err := r.search("subjunctive", nil); err != nil || res.Collection != col {
		t.Fatalf("search keeps using the previous publication: %+v %v", res, err)
	}
	s := r.mustRun("sync")
	if !s.Published || s.EmbeddedTexts != 0 {
		t.Fatalf("resume: the new document was embedded before the interruption: %+v", s)
	}
	r.assertPublishedMatchesSQLite()
}

// writeProbe proves that no SQLite write lock is held: an independent
// connection must start and roll back an IMMEDIATE transaction within 50 ms.
func writeProbe(t *testing.T, path string) func() error {
	t.Helper()
	db, err := sql.Open("sqlite", "file:"+path+"?_pragma=busy_timeout(50)")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	return func() error {
		conn, err := db.Conn(context.Background())
		if err != nil {
			return err
		}
		defer conn.Close()
		if _, err := conn.ExecContext(context.Background(), "BEGIN IMMEDIATE"); err != nil {
			return err
		}
		_, err = conn.ExecContext(context.Background(), "ROLLBACK")
		return err
	}
}

type probingTransport struct {
	probe  func() error
	mu     sync.Mutex
	probes int
	errs   []error
}

func (p *probingTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	// Runs while the Qdrant request is in flight from the indexer's view.
	err := p.probe()
	p.mu.Lock()
	p.probes++
	if err != nil {
		p.errs = append(p.errs, err)
	}
	p.mu.Unlock()
	return http.DefaultTransport.RoundTrip(req)
}

func TestQdrantIntegration_NoSQLiteWriteLockDuringNetworkCalls(t *testing.T) {
	r := newRig(t)
	probe := writeProbe(t, r.dbPath)
	// Positive control: the probe must fail while a write transaction is held.
	holder, err := sql.Open("sqlite", "file:"+r.dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer holder.Close()
	conn, err := holder.Conn(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := conn.ExecContext(context.Background(), "BEGIN IMMEDIATE"); err != nil {
		t.Fatal(err)
	}
	if probe() == nil {
		t.Fatal("control: the probe must detect a held write lock")
	}
	_, _ = conn.ExecContext(context.Background(), "ROLLBACK")
	conn.Close()
	var providerErrs []error
	providerProbes := 0
	r.provider.hook = func(int) {
		providerProbes++
		if err := probe(); err != nil {
			providerErrs = append(providerErrs, err)
		}
	}
	transport := &probingTransport{probe: probe}
	r.qdrant = vectorindex.NewQdrantWithClient(qdrantURL(t), "", &http.Client{Timeout: 5 * time.Second, Transport: transport})
	r.mustRun("build")
	r.concepts.mu.Lock()
	r.concepts.concepts[0] = mk(1, "subjunctive after il faut que (revised)", domain.ConceptActive)
	r.concepts.mu.Unlock()
	r.mustRun("sync")
	if len(providerErrs) != 0 || len(transport.errs) != 0 {
		t.Fatalf("a write lock was held during a network call: provider %v qdrant %v", providerErrs, transport.errs)
	}
	if transport.probes < 10 || providerProbes < 2 {
		t.Fatalf("too few calls probed: qdrant %d provider %d", transport.probes, providerProbes)
	}
	t.Logf("probed %d Qdrant calls and %d provider calls; no SQLite write lock was held during any", transport.probes, providerProbes)
}

func TestQdrantIntegration_UnavailableQdrant(t *testing.T) {
	r := newRig(t)
	r.qdrant = vectorindex.NewQdrant("http://127.0.0.1:1", "", time.Second) // nothing listens on port 1
	rep, err := r.run("build", application.SemanticRunOptions{})
	if !errors.Is(err, application.ErrVectorIndexUnavailable) || rep.Published || rep.Outcome != "failed" {
		t.Fatalf("build: %+v %v", rep, err)
	}
	if _, err := r.search("subjunctive", nil); !errors.Is(err, application.ErrSemanticIndexNotBuilt) {
		t.Fatalf("search: %v", err)
	}
	if st := r.status(); st.VerifiedHealthy || st.State.LastError != "vector index unavailable" {
		t.Fatalf("status: %+v", st.State)
	}
}
