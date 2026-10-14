package publicdemo

import (
	"context"
	"errors"
	"fmt"
	"math"
	"sort"
	"sync/atomic"
	"time"

	"french-learning-app/internal/application"
)

// ErrReadOnlyIndex is returned by every write method of ArtifactIndex.
var ErrReadOnlyIndex = errors.New("public demo vector index is read-only")

// ArtifactIndex is an in-process, read-only application.VectorIndex holding
// the artifact's Concept-document vectors. Query is exact cosine similarity.
// It answers only for the artifact's one physical collection.
type ArtifactIndex struct{ a *Artifact }

var _ application.VectorIndex = ArtifactIndex{}

// NewIndex returns the artifact's read-only vector index.
func NewIndex(a *Artifact) ArtifactIndex { return ArtifactIndex{a: a} }

func (x ArtifactIndex) CollectionInfo(ctx context.Context, collection string) (application.VectorCollectionInfo, error) {
	if err := ctx.Err(); err != nil {
		return application.VectorCollectionInfo{}, err
	}
	if collection != x.a.Collection {
		return application.VectorCollectionInfo{Exists: false}, nil
	}
	return application.VectorCollectionInfo{Exists: true, Dimensions: x.a.Space.Dimensions, Distance: "Cosine", PointCount: int64(len(x.a.documents))}, nil
}

func (x ArtifactIndex) ListCollections(context.Context) ([]string, error) {
	return []string{x.a.Collection}, nil
}

func (ArtifactIndex) CreateCollection(context.Context, string, int) error { return ErrReadOnlyIndex }
func (ArtifactIndex) DeleteCollection(context.Context, string) error      { return ErrReadOnlyIndex }
func (ArtifactIndex) Upsert(context.Context, string, application.SemanticIndexSpace, []application.VectorPoint) error {
	return ErrReadOnlyIndex
}
func (ArtifactIndex) Delete(context.Context, string, []int64) error { return ErrReadOnlyIndex }

func (ArtifactIndex) Scroll(context.Context, string, *int64, int) ([]application.StoredPoint, *int64, error) {
	return nil, nil, ErrReadOnlyIndex
}

func (x ArtifactIndex) Query(ctx context.Context, collection string, vector []float32, limit int) ([]application.VectorHit, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if collection != x.a.Collection {
		return nil, fmt.Errorf("%w: unknown collection", application.ErrVectorIndexUnavailable)
	}
	if len(vector) != x.a.Space.Dimensions || limit < 1 {
		return nil, fmt.Errorf("%w: bad query", application.ErrVectorIndexUnavailable)
	}
	hits := make([]application.VectorHit, 0, len(x.a.documents))
	for id, d := range x.a.documents {
		hits = append(hits, application.VectorHit{ConceptID: id, Score: cosine(vector, d.vector), ContentHash: d.hash,
			Representation: x.a.Space.Representation, ModelID: x.a.Space.ModelID, Dimensions: x.a.Space.Dimensions})
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

func cosine(a, b []float32) float64 {
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

// ArtifactPublication is the fixed publication record of the artifact's space.
type ArtifactPublication struct{ a *Artifact }

// NewPublication returns the artifact's publication record.
func NewPublication(a *Artifact) ArtifactPublication { return ArtifactPublication{a: a} }

func (p ArtifactPublication) SpaceState(_ context.Context, space string) (*application.SemanticIndexSpaceState, error) {
	if space != p.a.Space.Collection {
		return nil, nil
	}
	return &application.SemanticIndexSpaceState{
		Space: p.a.Space.Collection, Representation: p.a.Space.Representation, ModelID: p.a.Space.ModelID, Dimensions: p.a.Space.Dimensions,
		PublishedCollection: p.a.Collection, PublishedRunID: p.a.Manifest.ArtifactVersion,
		LastRunID: p.a.Manifest.ArtifactVersion, LastRunOperation: "artifact", LastRunOutcome: "published",
	}, nil
}

// PresetQueryVectors is the demo's application.EmbeddingProvider. It returns
// the cached vector for the exact query envelope of a catalog preset and
// refuses any other text. It has no network code: arbitrary input can never
// cause an embedding computation or an outbound request.
type PresetQueryVectors struct {
	a       *Artifact
	lookups atomic.Int64
	refused atomic.Int64
}

var _ application.EmbeddingProvider = (*PresetQueryVectors)(nil)

// NewPresetQueryVectors returns the preset-only provider.
func NewPresetQueryVectors(a *Artifact) *PresetQueryVectors { return &PresetQueryVectors{a: a} }

func (p *PresetQueryVectors) Name() string {
	return "public-demo:preset-query-vectors:" + p.a.Manifest.ArtifactVersion
}

func (p *PresetQueryVectors) Embed(ctx context.Context, texts []string) ([][]float64, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	out := make([][]float64, 0, len(texts))
	for _, t := range texts {
		i, ok := p.a.byEnvelope[t]
		if !ok {
			p.refused.Add(1)
			return nil, fmt.Errorf("%w: the public demo has no cached vector for this text and computes no embeddings", application.ErrEmbeddingProviderUnavailable)
		}
		p.lookups.Add(1)
		v := p.a.Presets[i].vector
		f := make([]float64, len(v))
		for j, x := range v {
			f[j] = float64(x)
		}
		out = append(out, f)
	}
	return out, nil
}

// Counters reports cached-vector lookups and refused texts since startup.
func (p *PresetQueryVectors) Counters() (lookups, refused int64) {
	return p.lookups.Load(), p.refused.Load()
}

// startedAt is fixed per process for the demo info response.
var startedAt = time.Now().UTC()

// StartedAt is the process start time reported by the demo.
func StartedAt() time.Time { return startedAt }
