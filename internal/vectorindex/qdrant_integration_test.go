package vectorindex_test

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
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

// Integration tests against an actual local Qdrant. They run only when
// FLH_QDRANT_URL is set (for example http://127.0.0.1:6334) and use a unique,
// task-owned collection prefix that is deleted afterwards. The embedding
// provider is a deterministic bag-of-words fake: these tests prove index
// mechanics, never semantic quality.

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
	call := p.calls
	p.mu.Unlock()
	if p.hook != nil {
		p.hook(call)
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
}

func newRig(t *testing.T) *rig {
	url := qdrantURL(t)
	var b [6]byte
	_, _ = rand.Read(b[:])
	prefix := "flh040_it_" + hex.EncodeToString(b[:])
	space, err := application.NewSemanticIndexSpace(prefix, "fake/bag-of-words@it", 32)
	if err != nil {
		t.Fatal(err)
	}
	r := &rig{t: t, dbPath: filepath.Join(t.TempDir(), "it.db"), qdrant: vectorindex.NewQdrant(url, "", 5*time.Second),
		provider: &countingProvider{dims: 32}, space: space,
		concepts: &conceptList{concepts: []domain.KnowledgeConcept{
			mk(1, "subjunctive after il faut que", domain.ConceptActive),
			mk(2, "passé composé with être", domain.ConceptActive),
			mk(3, "overview of the subjunctive mood", domain.ConceptOrphaned),
			mk(4, "bien que takes the subjunctive", domain.ConceptRetired),
		}}}
	r.open()
	t.Cleanup(func() { _ = r.qdrant.DeleteCollection(context.Background(), space.Collection) })
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

func (r *rig) search(q string, state *domain.ConceptState) (*application.SemanticSearchReport, error) {
	return application.NewSemanticSearchService(r.concepts, counts{}, r.store, r.qdrant, r.provider, r.space).
		Search(context.Background(), application.LibrarySearchQuery{Text: q, State: state, Limit: 10})
}

func TestQdrantIntegration_BuildSearchRestartRebuild(t *testing.T) {
	r := newRig(t)
	ctx := context.Background()
	rep, err := r.svc().Build(ctx)
	if err != nil || rep.State != "complete" || rep.EmbeddedTexts != 4 || rep.Upserted != 4 {
		t.Fatalf("build: %+v %v", rep, err)
	}
	info, err := r.qdrant.CollectionInfo(ctx, r.space.Collection)
	if err != nil || info.PointCount != 4 || info.Dimensions != 32 {
		t.Fatalf("qdrant info: %+v %v", info, err)
	}
	res, err := r.search("subjunctive", nil)
	if err != nil {
		t.Fatal(err)
	}
	if !res.IndexComplete || len(res.Results) != 3 {
		t.Fatalf("search: %+v", res)
	}
	active := domain.ConceptActive
	res, err = r.search("subjunctive", &active)
	if err != nil || len(res.Results) != 1 || res.Results[0].Concept.ID != 1 {
		t.Fatalf("active filter: %+v %v", res, err)
	}

	calls, texts := r.provider.calls, r.provider.texts
	r.open() // restart: fresh SQLite connection, same file
	if rep, err := r.svc().Sync(ctx); err != nil || rep.EmbeddedTexts != 0 || rep.Unchanged != 4 || rep.State != "complete" {
		t.Fatalf("sync after restart: %+v %v", rep, err)
	}
	if rep, err := r.svc().Rebuild(ctx); err != nil || rep.EmbeddedTexts != 0 || rep.Upserted != 4 || rep.State != "complete" {
		t.Fatalf("rebuild: %+v %v", rep, err)
	}
	if r.provider.calls != calls || r.provider.texts != texts {
		t.Fatalf("documents were re-embedded: calls %d->%d texts %d->%d", calls, r.provider.calls, texts, r.provider.texts)
	}
	st, err := r.svc().Status(ctx)
	if err != nil || !st.SearchableComplete || st.VectorStore.PointCount != 4 {
		t.Fatalf("status: %+v %v", st, err)
	}
}

func TestQdrantIntegration_StaleAndMissingCandidatesAreDropped(t *testing.T) {
	r := newRig(t)
	ctx := context.Background()
	if _, err := r.svc().Build(ctx); err != nil {
		t.Fatal(err)
	}
	r.concepts.mu.Lock()
	r.concepts.concepts[0] = mk(1, "subjunctive after il faut que (revised)", domain.ConceptActive) // stale point
	r.concepts.concepts = r.concepts.concepts[:3]                                                   // concept 4 vanished
	r.concepts.mu.Unlock()
	res, err := r.search("subjunctive", nil)
	if err != nil {
		t.Fatal(err)
	}
	if res.SkippedStale != 1 || res.SkippedMissing != 1 || len(res.Results) != 1 || res.Results[0].Concept.ID != 3 {
		t.Fatalf("search: %+v", res)
	}
	st, err := r.svc().Status(ctx)
	if err != nil || st.Stale != 1 || st.Orphaned != 1 || st.SearchableComplete {
		t.Fatalf("status: %+v %v", st, err)
	}
	rep, err := r.svc().Sync(ctx)
	if err != nil || rep.Upserted != 1 || rep.Deleted != 1 || rep.EmbeddedTexts != 1 || rep.State != "complete" {
		t.Fatalf("sync: %+v %v", rep, err)
	}
	if info, _ := r.qdrant.CollectionInfo(ctx, r.space.Collection); info.PointCount != 3 {
		t.Fatalf("points = %d", info.PointCount)
	}
}

func TestQdrantIntegration_InterruptedBuildThenRecovery(t *testing.T) {
	r := newRig(t)
	ctx, cancel := context.WithCancel(context.Background())
	r.provider.hook = func(call int) {
		if call == 2 {
			cancel()
		}
	}
	rep, err := r.svc().Build(ctx)
	if !errors.Is(err, context.Canceled) || rep.State != "partial" {
		t.Fatalf("interrupted build: %+v %v", rep, err)
	}
	r.provider.hook = nil
	if _, err := r.search("subjunctive", nil); err != nil {
		t.Fatalf("a partial index is searchable and reported as such: %v", err)
	}
	rep, err = r.svc().Sync(context.Background())
	if err != nil || rep.ReusedVectors != 2 || rep.State != "complete" {
		t.Fatalf("recovery: %+v %v", rep, err)
	}
}

func TestQdrantIntegration_UnavailableQdrant(t *testing.T) {
	_ = qdrantURL(t)
	r := newRig(t)
	r.qdrant = vectorindex.NewQdrant("http://127.0.0.1:1", "", time.Second) // nothing listens on port 1
	rep, err := r.svc().Sync(context.Background())
	if !errors.Is(err, application.ErrVectorIndexUnavailable) || rep.State != "partial" {
		t.Fatalf("sync: %+v %v", rep, err)
	}
	if _, err := r.search("subjunctive", nil); !errors.Is(err, application.ErrVectorIndexUnavailable) {
		t.Fatalf("search: %v", err)
	}
	st, err := r.svc().Status(context.Background())
	if err != nil || st.VectorStoreError != "vector index unavailable" || st.SearchableComplete {
		t.Fatalf("status: %+v %v", st, err)
	}
}
