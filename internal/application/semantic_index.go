package application

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"french-learning-app/internal/domain"
)

// Semantic index (FLH-040). SQLite remains the authority for Concepts; the
// vector index is a disposable, rebuildable search structure. Reusable document
// embeddings are cached in SQLite under a key that covers the document content
// hash, the representation version, the operator-declared model identity and
// the vector dimensions, so unchanged documents are never re-embedded and two
// models' vector spaces cannot mix.

const (
	// ConceptIndexRepresentationV1 is the indexed document form: the existing
	// concept_embedding_text_v1 Concept document (identity fields only).
	ConceptIndexRepresentationV1 = ConceptEmbeddingTextV1
	// ConceptSearchQueryRepresentationV1 is the user query form: the trimmed
	// query text, embedded as-is. Query vectors are never persisted.
	ConceptSearchQueryRepresentationV1 = "concept_search_query_v1"

	SemanticIndexStateBuilding = "building"
	SemanticIndexStateComplete = "complete"
	SemanticIndexStatePartial  = "partial"

	SemanticIndexDefaultBatchSize = 32
	SemanticIndexMaxBatchSize     = 256
	SemanticIndexMaxDimensions    = 8192
)

var (
	// ErrSemanticSearchDisabled means the server has no semantic configuration.
	ErrSemanticSearchDisabled = errors.New("semantic search is not configured")
	// ErrSemanticIndexNotBuilt means no index exists for the configured space.
	ErrSemanticIndexNotBuilt = errors.New("semantic index has not been built")
	// ErrSemanticIndexIncompatible means the vector store holds a collection
	// whose shape does not match the configured space.
	ErrSemanticIndexIncompatible = errors.New("semantic index is incompatible with the configured model")
	// ErrSemanticIndexExists is returned by Build when an index already exists.
	ErrSemanticIndexExists = errors.New("semantic index already exists")
	// ErrVectorIndexUnavailable and ErrVectorIndexTimeout classify vector
	// store failures. Transport may expose only the category.
	ErrVectorIndexUnavailable = errors.New("vector index unavailable")
	ErrVectorIndexTimeout     = errors.New("vector index timeout")
	// ErrInvalidEmbedding classifies vectors that cannot be stored or indexed.
	ErrInvalidEmbedding = errors.New("invalid embedding vector")
)

// SemanticIndexSpace identifies one vector space. A model or representation
// change produces a different space and therefore a different collection.
type SemanticIndexSpace struct {
	Representation string
	ModelID        string
	Dimensions     int
	Collection     string
}

// NewSemanticIndexSpace derives the collection name from the space key, so a
// collection can only ever hold vectors of one representation, model identity
// and dimension.
func NewSemanticIndexSpace(prefix, modelID string, dimensions int) (SemanticIndexSpace, error) {
	if strings.TrimSpace(modelID) == "" {
		return SemanticIndexSpace{}, errors.New("model identity is required")
	}
	if dimensions < 1 || dimensions > SemanticIndexMaxDimensions {
		return SemanticIndexSpace{}, fmt.Errorf("dimensions must be between 1 and %d", SemanticIndexMaxDimensions)
	}
	sum := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%s\x00%d", ConceptIndexRepresentationV1, modelID, dimensions)))
	return SemanticIndexSpace{
		Representation: ConceptIndexRepresentationV1,
		ModelID:        modelID,
		Dimensions:     dimensions,
		Collection:     fmt.Sprintf("%s_%s", prefix, hex.EncodeToString(sum[:])[:16]),
	}, nil
}

// SemanticIndexDocument is one Concept's indexed text and its content hash.
type SemanticIndexDocument struct {
	ConceptID   int64
	Text        string
	ContentHash string
}

// BuildSemanticIndexDocument renders the deterministic document for a Concept.
func BuildSemanticIndexDocument(concept domain.KnowledgeConcept) (SemanticIndexDocument, error) {
	text, err := conceptEmbeddingDocumentText(toConceptRetrievalDocument(concept))
	if err != nil {
		return SemanticIndexDocument{}, err
	}
	sum := sha256.Sum256([]byte(text))
	return SemanticIndexDocument{ConceptID: concept.ID, Text: text, ContentHash: hex.EncodeToString(sum[:])}, nil
}

// VectorPoint is one Concept vector published to the vector index.
type VectorPoint struct {
	ConceptID   int64
	ContentHash string
	Vector      []float32
}

// VectorHit is one vector-index match with the payload written at publication.
type VectorHit struct {
	ConceptID      int64
	Score          float64
	ContentHash    string
	Representation string
	ModelID        string
	Dimensions     int
}

// VectorCollectionInfo describes a collection as the vector store reports it.
type VectorCollectionInfo struct {
	Exists     bool
	Dimensions int
	Distance   string
	PointCount int64
}

// VectorIndex is the disposable vector store (one Qdrant instance in
// production). It owns no Concept, membership or support authority.
type VectorIndex interface {
	CollectionInfo(ctx context.Context, collection string) (VectorCollectionInfo, error)
	CreateCollection(ctx context.Context, collection string, dimensions int) error
	DeleteCollection(ctx context.Context, collection string) error
	Upsert(ctx context.Context, space SemanticIndexSpace, points []VectorPoint) error
	Delete(ctx context.Context, collection string, conceptIDs []int64) error
	Query(ctx context.Context, collection string, vector []float32, limit int) ([]VectorHit, error)
}

// SemanticIndexCollection is the bookkeeping row for one space.
type SemanticIndexCollection struct {
	Collection     string     `json:"collection"`
	Representation string     `json:"representation"`
	ModelID        string     `json:"model_id"`
	Dimensions     int        `json:"dimensions"`
	State          string     `json:"state"`
	RunID          string     `json:"run_id"`
	RunOperation   string     `json:"run_operation"`
	RunStartedAt   time.Time  `json:"run_started_at"`
	UpdatedAt      time.Time  `json:"updated_at"`
	CompletedAt    *time.Time `json:"completed_at"`
	LastError      string     `json:"last_error"`
}

// SemanticCacheCount counts cached vectors for one model space.
type SemanticCacheCount struct {
	Representation string `json:"representation"`
	ModelID        string `json:"model_id"`
	Dimensions     int    `json:"dimensions"`
	Vectors        int    `json:"vectors"`
}

// SemanticIndexStore is the SQLite bookkeeping: the reusable embedding cache
// and what this system believes it published. Every method is one short
// transaction; none is held across a provider or vector-store call.
type SemanticIndexStore interface {
	CachedVectors(ctx context.Context, space SemanticIndexSpace, hashes []string) (map[string][]float32, error)
	SaveVectors(ctx context.Context, space SemanticIndexSpace, vectors map[string][]float32, now time.Time) error
	BeginRun(ctx context.Context, space SemanticIndexSpace, runID, operation string, now time.Time) error
	FinishRun(ctx context.Context, collection, runID, state, lastError string, now time.Time) (bool, error)
	ClearPoints(ctx context.Context, collection string) error
	PublishedPoints(ctx context.Context, collection string) (map[int64]string, error)
	RecordPoints(ctx context.Context, collection string, points map[int64]string, now time.Time) error
	RemovePoints(ctx context.Context, collection string, conceptIDs []int64) error
	Collection(ctx context.Context, collection string) (*SemanticIndexCollection, error)
	Collections(ctx context.Context) ([]SemanticIndexCollection, error)
	CacheCounts(ctx context.Context) ([]SemanticCacheCount, error)
}

// SemanticConceptReader is the read-only Concept source for indexing/search.
type SemanticConceptReader interface {
	ListConcepts(ctx context.Context, state *domain.ConceptState) ([]domain.KnowledgeConcept, error)
}

// SemanticIndexReport summarizes one build, sync or rebuild run.
type SemanticIndexReport struct {
	Operation        string `json:"operation"`
	RunID            string `json:"run_id"`
	Collection       string `json:"collection"`
	Concepts         int    `json:"concepts"`
	EmbeddedTexts    int    `json:"embedded_texts"` // texts sent to the provider in this run
	ReusedVectors    int    `json:"reused_vectors"` // documents served from the SQLite cache
	Upserted         int    `json:"upserted"`
	Deleted          int    `json:"deleted"`
	Unchanged        int    `json:"unchanged"`
	ChangedDuringRun int    `json:"changed_during_run"` // documents whose source changed before publication
	State            string `json:"state"`
	Superseded       bool   `json:"superseded"` // another run took over; this run did not set the state
}

// SemanticIndexService runs explicit, operator-initiated index operations.
// Work is sequential and bounded by batchSize; every external call receives
// the caller's context, so cancellation stops the run between or during calls.
type SemanticIndexService struct {
	concepts  SemanticConceptReader
	store     SemanticIndexStore
	index     VectorIndex
	provider  EmbeddingProvider
	space     SemanticIndexSpace
	batchSize int
	now       func() time.Time
}

func NewSemanticIndexService(concepts SemanticConceptReader, store SemanticIndexStore, index VectorIndex, provider EmbeddingProvider, space SemanticIndexSpace, batchSize int) *SemanticIndexService {
	if batchSize < 1 {
		batchSize = SemanticIndexDefaultBatchSize
	}
	if batchSize > SemanticIndexMaxBatchSize {
		batchSize = SemanticIndexMaxBatchSize
	}
	return &SemanticIndexService{concepts: concepts, store: store, index: index, provider: provider, space: space, batchSize: batchSize, now: func() time.Time { return time.Now().UTC() }}
}

// WithClock replaces the clock (tests).
func (s *SemanticIndexService) WithClock(now func() time.Time) *SemanticIndexService {
	s.now = now
	return s
}

// Build creates the index for the configured space. It refuses when the space
// already has published points; use Sync or Rebuild then.
func (s *SemanticIndexService) Build(ctx context.Context) (*SemanticIndexReport, error) {
	published, err := s.store.PublishedPoints(ctx, s.space.Collection)
	if err != nil {
		return nil, err
	}
	if len(published) > 0 {
		return nil, fmt.Errorf("%w for %s (%d points); use sync or rebuild", ErrSemanticIndexExists, s.space.Collection, len(published))
	}
	return s.run(ctx, "build", false)
}

// Sync incrementally brings the index up to date with SQLite.
func (s *SemanticIndexService) Sync(ctx context.Context) (*SemanticIndexReport, error) {
	return s.run(ctx, "sync", false)
}

// Rebuild drops the collection and republishes every Concept. Cached
// embeddings are reused, so a rebuild needs no provider call for unchanged
// documents.
func (s *SemanticIndexService) Rebuild(ctx context.Context) (*SemanticIndexReport, error) {
	return s.run(ctx, "rebuild", true)
}

func (s *SemanticIndexService) run(ctx context.Context, operation string, drop bool) (report *SemanticIndexReport, err error) {
	if s.provider == nil {
		return nil, fmt.Errorf("%w: no embedding provider", ErrSemanticSearchDisabled)
	}
	runID, err := newRunID()
	if err != nil {
		return nil, err
	}
	report = &SemanticIndexReport{Operation: operation, RunID: runID, Collection: s.space.Collection}
	if err := s.store.BeginRun(ctx, s.space, runID, operation, s.now()); err != nil {
		return nil, err
	}
	// Whatever happens next, record an honest final state. The bookkeeping
	// write uses its own short context so that cancellation of the run still
	// leaves a visible "partial" record instead of a stale "building" one.
	defer func() {
		// An adapter may report a canceled request as "unavailable"; attach the
		// context error so callers and the stored state say "interrupted".
		if err != nil && ctx.Err() != nil && !errors.Is(err, ctx.Err()) {
			err = fmt.Errorf("%w (%w)", ctx.Err(), err)
		}
		state := SemanticIndexStateComplete
		lastError := ""
		if err != nil {
			state, lastError = SemanticIndexStatePartial, semanticErrorCategory(err)
		} else if report.ChangedDuringRun > 0 {
			state, lastError = SemanticIndexStatePartial, fmt.Sprintf("%d concept(s) changed during the run; run sync again", report.ChangedDuringRun)
		}
		finishCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
		defer cancel()
		owned, finishErr := s.store.FinishRun(finishCtx, s.space.Collection, runID, state, lastError, s.now())
		if finishErr != nil && err == nil {
			err = finishErr
		}
		report.State = state
		report.Superseded = finishErr == nil && !owned
	}()

	if drop {
		if err := s.index.DeleteCollection(ctx, s.space.Collection); err != nil {
			return report, err
		}
		if err := s.store.ClearPoints(ctx, s.space.Collection); err != nil {
			return report, err
		}
	}
	if err := s.ensureCollection(ctx); err != nil {
		return report, err
	}

	concepts, err := s.concepts.ListConcepts(ctx, nil)
	if err != nil {
		return report, err
	}
	docs := make([]SemanticIndexDocument, 0, len(concepts))
	for _, c := range concepts {
		doc, err := BuildSemanticIndexDocument(c)
		if err != nil {
			return report, err
		}
		docs = append(docs, doc)
	}
	report.Concepts = len(docs)
	sort.Slice(docs, func(i, j int) bool { return docs[i].ConceptID < docs[j].ConceptID })

	vectors, err := s.ensureVectors(ctx, docs, report)
	if err != nil {
		return report, err
	}

	published, err := s.store.PublishedPoints(ctx, s.space.Collection)
	if err != nil {
		return report, err
	}
	pending := make([]SemanticIndexDocument, 0)
	present := make(map[int64]bool, len(docs))
	for _, d := range docs {
		present[d.ConceptID] = true
		if published[d.ConceptID] == d.ContentHash {
			report.Unchanged++
			continue
		}
		pending = append(pending, d)
	}
	for start := 0; start < len(pending); start += s.batchSize {
		batch := pending[start:min(start+s.batchSize, len(pending))]
		if err := s.publish(ctx, batch, vectors, report); err != nil {
			return report, err
		}
	}

	// Concepts are not deleted in this system, but an index must never keep
	// points for IDs that no longer exist in the authority.
	var gone []int64
	for id := range published {
		if !present[id] {
			gone = append(gone, id)
		}
	}
	sort.Slice(gone, func(i, j int) bool { return gone[i] < gone[j] })
	for start := 0; start < len(gone); start += s.batchSize {
		batch := gone[start:min(start+s.batchSize, len(gone))]
		if err := s.index.Delete(ctx, s.space.Collection, batch); err != nil {
			return report, err
		}
		if err := s.store.RemovePoints(ctx, s.space.Collection, batch); err != nil {
			return report, err
		}
		report.Deleted += len(batch)
	}

	// Final revalidation: every current Concept must be published with its
	// current hash; otherwise the run is reported partial, never complete.
	stale, err := s.staleCount(ctx)
	if err != nil {
		return report, err
	}
	if stale > report.ChangedDuringRun {
		report.ChangedDuringRun = stale
	}
	return report, nil
}

// ensureCollection creates the collection or verifies an existing one. If the
// vector store lost the collection, bookkeeping is cleared so every point is
// republished instead of being trusted.
func (s *SemanticIndexService) ensureCollection(ctx context.Context) error {
	info, err := s.index.CollectionInfo(ctx, s.space.Collection)
	if err != nil {
		return err
	}
	if !info.Exists {
		if err := s.store.ClearPoints(ctx, s.space.Collection); err != nil {
			return err
		}
		return s.index.CreateCollection(ctx, s.space.Collection, s.space.Dimensions)
	}
	if info.Dimensions != s.space.Dimensions || !strings.EqualFold(info.Distance, "cosine") {
		return fmt.Errorf("%w: collection %s has %d dimensions (%s), configured %d (cosine); run rebuild", ErrSemanticIndexIncompatible, s.space.Collection, info.Dimensions, info.Distance, s.space.Dimensions)
	}
	return nil
}

// ensureVectors returns a vector for every document, embedding only cache
// misses, in sequential bounded batches. Each batch is saved before the next
// provider call, so an interrupted run keeps the work already paid for.
func (s *SemanticIndexService) ensureVectors(ctx context.Context, docs []SemanticIndexDocument, report *SemanticIndexReport) (map[string][]float32, error) {
	hashes := make([]string, 0, len(docs))
	textByHash := make(map[string]string, len(docs))
	for _, d := range docs {
		if _, ok := textByHash[d.ContentHash]; !ok {
			hashes = append(hashes, d.ContentHash)
			textByHash[d.ContentHash] = d.Text
		}
	}
	vectors, err := s.store.CachedVectors(ctx, s.space, hashes)
	if err != nil {
		return nil, err
	}
	for _, d := range docs {
		if _, ok := vectors[d.ContentHash]; ok {
			report.ReusedVectors++
		}
	}
	var missing []string
	for _, h := range hashes {
		if _, ok := vectors[h]; !ok {
			missing = append(missing, h)
		}
	}
	for start := 0; start < len(missing); start += s.batchSize {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		batch := missing[start:min(start+s.batchSize, len(missing))]
		texts := make([]string, len(batch))
		for i, h := range batch {
			texts[i] = textByHash[h]
		}
		raw, err := s.provider.Embed(ctx, texts)
		if err != nil {
			return nil, fmt.Errorf("embed index batch: %w", err)
		}
		report.EmbeddedTexts += len(texts)
		if len(raw) != len(texts) {
			return nil, fmt.Errorf("%w: provider returned %d vectors for %d texts", ErrEmbeddingProviderUnavailable, len(raw), len(texts))
		}
		fresh := make(map[string][]float32, len(batch))
		for i, h := range batch {
			v, err := ValidateEmbedding(raw[i], s.space.Dimensions)
			if err != nil {
				return nil, err
			}
			fresh[h] = v
		}
		if err := s.store.SaveVectors(ctx, s.space, fresh, s.now()); err != nil {
			return nil, err
		}
		for h, v := range fresh {
			vectors[h] = v
		}
	}
	return vectors, nil
}

// publish re-reads the authority immediately before upserting a batch and
// skips any Concept whose document changed since its vector was prepared.
func (s *SemanticIndexService) publish(ctx context.Context, batch []SemanticIndexDocument, vectors map[string][]float32, report *SemanticIndexReport) error {
	current, err := s.currentHashes(ctx)
	if err != nil {
		return err
	}
	points := make([]VectorPoint, 0, len(batch))
	recorded := make(map[int64]string, len(batch))
	for _, d := range batch {
		if current[d.ConceptID] != d.ContentHash {
			report.ChangedDuringRun++
			continue
		}
		points = append(points, VectorPoint{ConceptID: d.ConceptID, ContentHash: d.ContentHash, Vector: vectors[d.ContentHash]})
		recorded[d.ConceptID] = d.ContentHash
	}
	if len(points) == 0 {
		return nil
	}
	if err := s.index.Upsert(ctx, s.space, points); err != nil {
		return err
	}
	// Recorded only after the vector store acknowledged the write.
	if err := s.store.RecordPoints(ctx, s.space.Collection, recorded, s.now()); err != nil {
		return err
	}
	report.Upserted += len(points)
	return nil
}

func (s *SemanticIndexService) currentHashes(ctx context.Context) (map[int64]string, error) {
	concepts, err := s.concepts.ListConcepts(ctx, nil)
	if err != nil {
		return nil, err
	}
	out := make(map[int64]string, len(concepts))
	for _, c := range concepts {
		doc, err := BuildSemanticIndexDocument(c)
		if err != nil {
			return nil, err
		}
		out[c.ID] = doc.ContentHash
	}
	return out, nil
}

func (s *SemanticIndexService) staleCount(ctx context.Context) (int, error) {
	current, err := s.currentHashes(ctx)
	if err != nil {
		return 0, err
	}
	published, err := s.store.PublishedPoints(ctx, s.space.Collection)
	if err != nil {
		return 0, err
	}
	stale := 0
	for id, h := range current {
		if published[id] != h {
			stale++
		}
	}
	for id := range published {
		if _, ok := current[id]; !ok {
			stale++
		}
	}
	return stale, nil
}

// SemanticIndexStatus is the read-only comparison of SQLite, bookkeeping and
// the vector store. It never calls the embedding provider.
type SemanticIndexStatus struct {
	Space              SemanticIndexSpace
	Collection         *SemanticIndexCollection
	Concepts           int
	UpToDate           int
	Stale              int // published with an outdated hash
	Missing            int // not published at all
	Orphaned           int // published for an ID that no longer exists
	VectorStore        VectorCollectionInfo
	VectorStoreError   string
	OtherCollections   []SemanticIndexCollection
	CacheCounts        []SemanticCacheCount
	SearchableComplete bool
}

// Status reports index health. A vector-store failure is reported in the
// result rather than hiding the SQLite-side facts.
func (s *SemanticIndexService) Status(ctx context.Context) (*SemanticIndexStatus, error) {
	st := &SemanticIndexStatus{Space: s.space}
	col, err := s.store.Collection(ctx, s.space.Collection)
	if err != nil {
		return nil, err
	}
	st.Collection = col
	current, err := s.currentHashes(ctx)
	if err != nil {
		return nil, err
	}
	st.Concepts = len(current)
	published, err := s.store.PublishedPoints(ctx, s.space.Collection)
	if err != nil {
		return nil, err
	}
	for id, h := range current {
		switch p, ok := published[id]; {
		case !ok:
			st.Missing++
		case p != h:
			st.Stale++
		default:
			st.UpToDate++
		}
	}
	for id := range published {
		if _, ok := current[id]; !ok {
			st.Orphaned++
		}
	}
	all, err := s.store.Collections(ctx)
	if err != nil {
		return nil, err
	}
	for _, c := range all {
		if c.Collection != s.space.Collection {
			st.OtherCollections = append(st.OtherCollections, c)
		}
	}
	if st.CacheCounts, err = s.store.CacheCounts(ctx); err != nil {
		return nil, err
	}
	info, err := s.index.CollectionInfo(ctx, s.space.Collection)
	if err != nil {
		st.VectorStoreError = semanticErrorCategory(err)
	} else {
		st.VectorStore = info
	}
	st.SearchableComplete = col != nil && col.State == SemanticIndexStateComplete &&
		st.Stale == 0 && st.Missing == 0 && st.Orphaned == 0 && err == nil &&
		info.Exists && info.PointCount == int64(len(published))
	return st, nil
}

// ValidateEmbedding converts a provider vector to the stored float32 form,
// rejecting wrong dimensions, non-finite values, values outside float32 range
// and zero vectors (cosine is undefined for them).
func ValidateEmbedding(vector []float64, dimensions int) ([]float32, error) {
	if len(vector) != dimensions {
		return nil, fmt.Errorf("%w: got %d dimensions, configured %d", ErrInvalidEmbedding, len(vector), dimensions)
	}
	out := make([]float32, len(vector))
	var norm float64
	for i, v := range vector {
		if math.IsNaN(v) || math.IsInf(v, 0) || math.Abs(v) > math.MaxFloat32 {
			return nil, fmt.Errorf("%w: non-finite or out-of-range component", ErrInvalidEmbedding)
		}
		out[i] = float32(v)
		norm += v * v
	}
	if norm == 0 {
		return nil, fmt.Errorf("%w: zero vector", ErrInvalidEmbedding)
	}
	return out, nil
}

// EncodeFloat32Vector and DecodeFloat32Vector define the cache blob format:
// little-endian IEEE-754 float32, exactly 4*dimensions bytes.
func EncodeFloat32Vector(v []float32) []byte {
	out := make([]byte, 4*len(v))
	for i, x := range v {
		binary.LittleEndian.PutUint32(out[4*i:], math.Float32bits(x))
	}
	return out
}

func DecodeFloat32Vector(b []byte, dimensions int) ([]float32, error) {
	if len(b) != 4*dimensions {
		return nil, fmt.Errorf("%w: cached vector has %d bytes, expected %d", ErrInvalidEmbedding, len(b), 4*dimensions)
	}
	out := make([]float32, dimensions)
	for i := range out {
		out[i] = math.Float32frombits(binary.LittleEndian.Uint32(b[4*i:]))
	}
	return out, nil
}

// semanticErrorCategory maps an error to a stored/printed message that never
// includes provider bodies, keys or learning content.
func semanticErrorCategory(err error) string {
	switch {
	case errors.Is(err, context.Canceled):
		return "interrupted (canceled)"
	case errors.Is(err, context.DeadlineExceeded):
		return "interrupted (deadline exceeded)"
	case errors.Is(err, ErrEmbeddingProviderTimeout):
		return "embedding provider timeout"
	case errors.Is(err, ErrEmbeddingProviderUnavailable):
		return "embedding provider unavailable"
	case errors.Is(err, ErrInvalidEmbedding):
		return "invalid embedding: " + strings.TrimPrefix(err.Error(), ErrInvalidEmbedding.Error()+": ")
	case errors.Is(err, ErrVectorIndexTimeout):
		return "vector index timeout"
	case errors.Is(err, ErrVectorIndexUnavailable):
		return "vector index unavailable"
	case errors.Is(err, ErrSemanticIndexIncompatible):
		return "incompatible vector collection"
	default:
		return "internal error"
	}
}

func newRunID() (string, error) {
	var b [12]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", fmt.Errorf("generate run id: %w", err)
	}
	return hex.EncodeToString(b[:]), nil
}
