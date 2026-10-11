package application_test

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"math"
	"sort"
	"strings"
	"sync"
	"time"
	"unicode"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// Deterministic fakes for FLH-040 tests. The fake provider hashes tokens into
// a bag-of-words vector: similarity reflects shared words only. It proves the
// mechanics (caching, publication, re-validation), never semantic quality.

type fakeConcepts struct {
	mu       sync.Mutex
	concepts map[int64]domain.KnowledgeConcept
	onList   func(call int) // optional hook, called before each ListConcepts
	calls    int
}

func newFakeConcepts(cs ...domain.KnowledgeConcept) *fakeConcepts {
	f := &fakeConcepts{concepts: map[int64]domain.KnowledgeConcept{}}
	for _, c := range cs {
		f.concepts[c.ID] = c
	}
	return f
}

func concept(id int64, target string, state domain.ConceptState) domain.KnowledgeConcept {
	return domain.KnowledgeConcept{ID: id, IdentitySchemaVersion: "fr_l2_concept_identity_v1", Target: target,
		PedagogicalIntent: "grammar", IdentityFeatures: map[string]string{}, State: state}
}

func (f *fakeConcepts) set(c domain.KnowledgeConcept) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.concepts[c.ID] = c
}

func (f *fakeConcepts) remove(id int64) {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.concepts, id)
}

func (f *fakeConcepts) ListConcepts(_ context.Context, state *domain.ConceptState) ([]domain.KnowledgeConcept, error) {
	f.mu.Lock()
	f.calls++
	hook, call := f.onList, f.calls
	f.mu.Unlock()
	if hook != nil {
		hook(call)
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	out := []domain.KnowledgeConcept{}
	for _, c := range f.concepts {
		if state == nil || c.State == *state {
			out = append(out, c)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out, nil
}

type fakeProvider struct {
	mu        sync.Mutex
	dims      int
	calls     int
	texts     int
	failCall  int  // fail this call number (1-based); 0 = never
	badDims   bool // return vectors with one extra dimension
	nan       bool // return a NaN component
	zero      bool // return zero vectors
	onEmbed   func(call int)
	failError error
}

func newFakeProvider(dims int) *fakeProvider { return &fakeProvider{dims: dims} }

func (p *fakeProvider) Name() string { return "fake:bag-of-words" }

func (p *fakeProvider) Embed(ctx context.Context, texts []string) ([][]float64, error) {
	p.mu.Lock()
	p.calls++
	call := p.calls
	hook := p.onEmbed
	p.mu.Unlock()
	if hook != nil {
		hook(call)
	}
	if err := ctx.Err(); err != nil {
		return nil, errors.Join(application.ErrEmbeddingProviderUnavailable, err)
	}
	if p.failCall == call {
		if p.failError != nil {
			return nil, p.failError
		}
		return nil, application.ErrEmbeddingProviderUnavailable
	}
	p.mu.Lock()
	p.texts += len(texts)
	p.mu.Unlock()
	out := make([][]float64, len(texts))
	for i, t := range texts {
		v := bagOfWords(t, p.dims)
		switch {
		case p.badDims:
			v = append(v, 1)
		case p.nan:
			v[0] = math.NaN()
		case p.zero:
			v = make([]float64, p.dims)
		}
		out[i] = v
	}
	return out, nil
}

func (p *fakeProvider) counts() (calls, texts int) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.calls, p.texts
}

// bagOfWords lowercases, keeps letter/digit runs of 2+ runes (JSON keys of the
// document representation are ignored) and adds +/-1 at a hashed index.
func bagOfWords(text string, dims int) []float64 {
	ignore := map[string]bool{"representation": true, "type": true, "concept": true, "target": true,
		"pedagogical_intent": true, "pedagogical": true, "intent": true, "scope": true, "identity_features": true,
		"identity": true, "features": true, "key": true, "value": true, "concept_embedding_text_v1": true,
		"embedding": true, "text": true, "v1": true}
	v := make([]float64, dims)
	words := strings.FieldsFunc(strings.ToLower(text), func(r rune) bool { return !unicode.IsLetter(r) && !unicode.IsDigit(r) })
	for _, w := range words {
		if len([]rune(w)) < 2 || ignore[w] {
			continue
		}
		sum := sha256.Sum256([]byte(w))
		idx := int(binary.BigEndian.Uint32(sum[:4]) % uint32(dims))
		sign := 1.0
		if sum[4]&1 == 1 {
			sign = -1
		}
		v[idx] += sign
	}
	nonZero := false
	for _, x := range v {
		if x != 0 {
			nonZero = true
		}
	}
	if !nonZero {
		v[0] = 1 // a text with no words still gets a valid (uninformative) vector
	}
	return v
}

type memPoint struct {
	vector []float32
	hash   string
	space  application.SemanticIndexSpace
}

type memCollection struct {
	dims   int
	points map[int64]memPoint
}

type memIndex struct {
	mu          sync.Mutex
	collections map[string]*memCollection
	unavailable bool
	upserts     int
	failUpsert  int // fail this upsert call number (1-based)
}

func newMemIndex() *memIndex { return &memIndex{collections: map[string]*memCollection{}} }

func (m *memIndex) check() error {
	if m.unavailable {
		return application.ErrVectorIndexUnavailable
	}
	return nil
}

func (m *memIndex) CollectionInfo(_ context.Context, name string) (application.VectorCollectionInfo, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if err := m.check(); err != nil {
		return application.VectorCollectionInfo{}, err
	}
	c, ok := m.collections[name]
	if !ok {
		return application.VectorCollectionInfo{}, nil
	}
	return application.VectorCollectionInfo{Exists: true, Dimensions: c.dims, Distance: "Cosine", PointCount: int64(len(c.points))}, nil
}

func (m *memIndex) CreateCollection(_ context.Context, name string, dims int) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if err := m.check(); err != nil {
		return err
	}
	m.collections[name] = &memCollection{dims: dims, points: map[int64]memPoint{}}
	return nil
}

func (m *memIndex) DeleteCollection(_ context.Context, name string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if err := m.check(); err != nil {
		return err
	}
	delete(m.collections, name)
	return nil
}

func (m *memIndex) Upsert(_ context.Context, space application.SemanticIndexSpace, points []application.VectorPoint) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if err := m.check(); err != nil {
		return err
	}
	m.upserts++
	if m.failUpsert == m.upserts {
		return application.ErrVectorIndexUnavailable
	}
	c, ok := m.collections[space.Collection]
	if !ok {
		return application.ErrSemanticIndexNotBuilt
	}
	for _, p := range points {
		if len(p.Vector) != c.dims {
			return errors.New("dimension mismatch")
		}
		c.points[p.ConceptID] = memPoint{vector: p.Vector, hash: p.ContentHash, space: space}
	}
	return nil
}

func (m *memIndex) Delete(_ context.Context, name string, ids []int64) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if err := m.check(); err != nil {
		return err
	}
	if c, ok := m.collections[name]; ok {
		for _, id := range ids {
			delete(c.points, id)
		}
	}
	return nil
}

func (m *memIndex) Query(_ context.Context, name string, vector []float32, limit int) ([]application.VectorHit, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if err := m.check(); err != nil {
		return nil, err
	}
	c, ok := m.collections[name]
	if !ok {
		return nil, application.ErrSemanticIndexNotBuilt
	}
	hits := []application.VectorHit{}
	for id, p := range c.points {
		hits = append(hits, application.VectorHit{ConceptID: id, Score: cosine32(vector, p.vector), ContentHash: p.hash,
			Representation: p.space.Representation, ModelID: p.space.ModelID, Dimensions: p.space.Dimensions})
	}
	sort.Slice(hits, func(i, j int) bool {
		if hits[i].Score != hits[j].Score {
			return hits[i].Score > hits[j].Score
		}
		return hits[i].ConceptID < hits[j].ConceptID
	})
	if len(hits) > limit {
		hits = hits[:limit]
	}
	return hits, nil
}

// injectPoint writes a point directly (simulating foreign or stale data).
func (m *memIndex) injectPoint(name string, id int64, hash string, space application.SemanticIndexSpace, vector []float32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.collections[name].points[id] = memPoint{vector: vector, hash: hash, space: space}
}

func cosine32(a, b []float32) float64 {
	var dot, na, nb float64
	for i := range a {
		dot += float64(a[i]) * float64(b[i])
		na += float64(a[i]) * float64(a[i])
		nb += float64(b[i]) * float64(b[i])
	}
	if na == 0 || nb == 0 {
		return 0
	}
	return dot / (math.Sqrt(na) * math.Sqrt(nb))
}

type fixedSummarizer struct{}

func (fixedSummarizer) ConceptCounts(context.Context, int64) (int, int, error) { return 1, 1, nil }

func fixedClock() func() time.Time {
	t := time.Date(2026, 10, 10, 12, 0, 0, 0, time.UTC)
	return func() time.Time {
		t = t.Add(time.Second)
		return t
	}
}
