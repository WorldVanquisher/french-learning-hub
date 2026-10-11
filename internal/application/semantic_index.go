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

// Semantic index (FLH-040, run consistency FLH-042). SQLite remains the
// authority for Concepts; Qdrant holds disposable, rebuildable collections.
//
// Run model (FLH-042):
//   - A run first takes the space's lease in SQLite (busy if another unexpired
//     lease exists). The lease is renewed and re-checked at every gate: before
//     each vector-store mutation and before each bookkeeping write.
//   - A run writes only into its own new physical collection. No run mutates a
//     collection another run created or published.
//   - Publication is one SQLite compare-and-set that succeeds only while the run
//     still holds the lease. A superseded run can therefore never change what
//     search reads, nor any other run's bookkeeping.
//   - No SQLite transaction is held across a provider or vector-store call, and
//     no atomicity across SQLite and Qdrant is claimed: the compare-and-set is
//     the single publication point, and search re-validates every hit.

const (
	// ConceptIndexRepresentationV1 is the indexed document form: the existing
	// concept_embedding_text_v1 Concept document (identity fields only).
	ConceptIndexRepresentationV1 = ConceptEmbeddingTextV1
	// ConceptSearchQueryRepresentationV1 is the user query form: the trimmed
	// query text, embedded as-is. Query vectors are never persisted.
	ConceptSearchQueryRepresentationV1 = "concept_search_query_v1"

	// Run outcomes recorded by the run that owned the space at the end.
	RunOutcomePublished         = "published"
	RunOutcomeVerifiedUnchanged = "verified_unchanged"
	RunOutcomeFailed            = "failed"
	RunOutcomeInterrupted       = "interrupted"
	RunOutcomeSourcesChanged    = "sources_changed"

	// Physical collection statuses.
	PhysicalWriting   = "writing"
	PhysicalPublished = "published"
	PhysicalRetired   = "retired"
	PhysicalAbandoned = "abandoned"

	SemanticIndexDefaultBatchSize = 32
	SemanticIndexMaxBatchSize     = 256
	SemanticIndexMaxDimensions    = 8192
	// SemanticIndexDefaultLeaseTTL bounds how long a silent run keeps the lease.
	// It is renewed at every gate; one provider or Qdrant call is bounded by its
	// own timeout (seconds), far below this.
	SemanticIndexDefaultLeaseTTL = 2 * time.Minute
	// semanticCatchUpPasses bounds how often a run re-reads changed sources
	// before giving up on publication.
	semanticCatchUpPasses = 2
	// vectorMatchTolerance compares a stored (Qdrant-normalized) vector with the
	// normalized cached vector.
	vectorMatchTolerance = 1e-4
)

var (
	// ErrSemanticSearchDisabled means the server has no semantic configuration.
	ErrSemanticSearchDisabled = errors.New("semantic search is not configured")
	// ErrSemanticIndexNotBuilt means no collection is published for the space.
	ErrSemanticIndexNotBuilt = errors.New("semantic index has not been built")
	// ErrSemanticIndexIncompatible means a collection's shape does not match.
	ErrSemanticIndexIncompatible = errors.New("semantic index is incompatible with the configured model")
	// ErrSemanticIndexExists is returned by Build when a publication exists.
	ErrSemanticIndexExists = errors.New("semantic index already exists")
	// ErrSemanticIndexBusy means another run holds an unexpired lease.
	ErrSemanticIndexBusy = errors.New("another semantic index run holds the lease")
	// ErrSemanticIndexOwnershipLost means this run's lease was taken over or
	// released; the run must stop before any further mutation.
	ErrSemanticIndexOwnershipLost = errors.New("semantic index run lost ownership")
	// ErrSemanticSourcesChanged means Concepts kept changing during the run, so
	// it did not publish.
	ErrSemanticSourcesChanged = errors.New("concepts changed during the run")
	// ErrSemanticVerificationFailed means the run's own collection did not
	// verify before publication.
	ErrSemanticVerificationFailed = errors.New("new collection failed verification")
	// ErrVectorIndexUnavailable and ErrVectorIndexTimeout classify vector
	// store failures. Transport may expose only the category.
	ErrVectorIndexUnavailable = errors.New("vector index unavailable")
	ErrVectorIndexTimeout     = errors.New("vector index timeout")
	// ErrInvalidEmbedding classifies vectors that cannot be stored or indexed.
	ErrInvalidEmbedding = errors.New("invalid embedding vector")
)

// SemanticIndexSpace identifies one vector space. Collection is the space's
// base name, derived from the representation, model identity and dimensions
// (the FLH-040 collection name). Since FLH-042 each run's physical collection is
// named Collection + "_r" + run prefix; the base name itself is not queried.
type SemanticIndexSpace struct {
	Representation string
	ModelID        string
	Dimensions     int
	Collection     string
}

// NewSemanticIndexSpace derives the space name, so a space (and every
// physical collection in it) only ever holds one model's vectors.
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

// PhysicalCollectionName is the private collection of one run.
func (s SemanticIndexSpace) PhysicalCollectionName(runID string) string {
	return s.Collection + "_r" + runID[:12]
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

// VectorPoint is one Concept vector written to a collection.
type VectorPoint struct {
	ConceptID   int64
	ContentHash string
	Vector      []float32
}

// VectorHit is one query match with the payload written at publication.
type VectorHit struct {
	ConceptID      int64
	Score          float64
	ContentHash    string
	Representation string
	ModelID        string
	Dimensions     int
}

// StoredPoint is one point as the vector store returns it on a full scan.
// PayloadValid is false when the point's id and payload disagree or the
// payload is not one this system writes.
type StoredPoint struct {
	ConceptID      int64
	PayloadValid   bool
	ContentHash    string
	Representation string
	ModelID        string
	Dimensions     int
	Vector         []float32
}

// VectorCollectionInfo describes a collection as the vector store reports it.
type VectorCollectionInfo struct {
	Exists     bool
	Dimensions int
	Distance   string
	PointCount int64
}

// VectorIndex is the disposable vector store (one Qdrant instance). It owns no
// Concept, membership or support authority.
type VectorIndex interface {
	CollectionInfo(ctx context.Context, collection string) (VectorCollectionInfo, error)
	ListCollections(ctx context.Context) ([]string, error)
	CreateCollection(ctx context.Context, collection string, dimensions int) error
	DeleteCollection(ctx context.Context, collection string) error
	Upsert(ctx context.Context, collection string, space SemanticIndexSpace, points []VectorPoint) error
	Delete(ctx context.Context, collection string, conceptIDs []int64) error
	Query(ctx context.Context, collection string, vector []float32, limit int) ([]VectorHit, error)
	// Scroll returns up to limit points with payloads and vectors, ordered by
	// id, starting at offset (nil = first). next is nil after the last page.
	Scroll(ctx context.Context, collection string, offset *int64, limit int) (points []StoredPoint, next *int64, err error)
}

// SemanticIndexSpaceState is the SQLite record of one space: its lease, its
// publication and its last run. None of it is verified index health.
type SemanticIndexSpaceState struct {
	Space               string     `json:"space"`
	Representation      string     `json:"representation"`
	ModelID             string     `json:"model_id"`
	Dimensions          int        `json:"dimensions"`
	LeaseRunID          string     `json:"lease_run_id"`
	LeaseOperation      string     `json:"lease_operation"`
	LeaseStartedAt      *time.Time `json:"lease_started_at"`
	LeaseExpiresAt      *time.Time `json:"lease_expires_at"`
	PublishedCollection string     `json:"published_collection"`
	PublishedRunID      string     `json:"published_run_id"`
	PublishedAt         *time.Time `json:"published_at"`
	LastRunID           string     `json:"last_run_id"`
	LastRunOperation    string     `json:"last_run_operation"`
	LastRunOutcome      string     `json:"last_run_outcome"`
	LastRunStartedAt    *time.Time `json:"last_run_started_at"`
	LastRunFinishedAt   *time.Time `json:"last_run_finished_at"`
	LastError           string     `json:"last_error"`
}

// PhysicalCollection is one recorded collection of a space.
type PhysicalCollection struct {
	Collection string    `json:"collection"`
	Space      string    `json:"space"`
	RunID      string    `json:"run_id"`
	Status     string    `json:"status"`
	CreatedAt  time.Time `json:"created_at"`
	UpdatedAt  time.Time `json:"updated_at"`
}

// SemanticCacheCount counts cached vectors for one model space.
type SemanticCacheCount struct {
	Representation string `json:"representation"`
	ModelID        string `json:"model_id"`
	Dimensions     int    `json:"dimensions"`
	Vectors        int    `json:"vectors"`
}

// SemanticRunOutcome is what the owning run records when it finishes.
type SemanticRunOutcome struct {
	Outcome    string
	LastError  string
	StartedAt  time.Time
	FinishedAt time.Time
}

// SemanticIndexStore is the SQLite bookkeeping. Every method is one short
// transaction. Methods taking a runID are fenced: they act only while that run
// holds the space's lease and otherwise return ErrSemanticIndexOwnershipLost.
type SemanticIndexStore interface {
	CachedVectors(ctx context.Context, space SemanticIndexSpace, hashes []string) (map[string][]float32, error)
	SaveVectors(ctx context.Context, space SemanticIndexSpace, vectors map[string][]float32, now time.Time) error

	AcquireLease(ctx context.Context, space SemanticIndexSpace, runID, operation string, now, expires time.Time, takeover bool) error
	RenewLease(ctx context.Context, space, runID string, expires time.Time) error
	CompleteRun(ctx context.Context, space, runID, operation string, outcome SemanticRunOutcome) error

	RegisterCollection(ctx context.Context, space, runID, collection string, now time.Time) error
	RecordManifest(ctx context.Context, space, runID, collection string, points map[int64]string) error
	RemoveManifest(ctx context.Context, space, runID, collection string, conceptIDs []int64) error
	Publish(ctx context.Context, space, runID, collection string, now time.Time) (previous string, err error)
	MarkCollection(ctx context.Context, space, runID, collection, status string, now time.Time) error
	ForgetCollection(ctx context.Context, space, runID, collection string) error

	Manifest(ctx context.Context, collection string) (map[int64]string, error)
	SpaceState(ctx context.Context, space string) (*SemanticIndexSpaceState, error)
	SpaceStates(ctx context.Context) ([]SemanticIndexSpaceState, error)
	PhysicalCollections(ctx context.Context, space string) ([]PhysicalCollection, error)
	CacheCounts(ctx context.Context) ([]SemanticCacheCount, error)
}

// SemanticConceptReader is the read-only Concept source for indexing/search.
type SemanticConceptReader interface {
	ListConcepts(ctx context.Context, state *domain.ConceptState) ([]domain.KnowledgeConcept, error)
}

// SemanticIndexReport summarizes one build, sync or rebuild run.
type SemanticIndexReport struct {
	Operation         string `json:"operation"`
	RunID             string `json:"run_id"`
	Space             string `json:"space"`
	Collection        string `json:"collection"` // this run's physical collection, if created
	Concepts          int    `json:"concepts"`
	EmbeddedTexts     int    `json:"embedded_texts"` // texts sent to the provider in this run
	ReusedVectors     int    `json:"reused_vectors"` // documents served from the SQLite cache
	Upserted          int    `json:"upserted"`
	CatchUpChanges    int    `json:"catch_up_changes"` // source changes absorbed before publication
	Published         bool   `json:"published"`
	Replaced          string `json:"replaced"`            // previously published collection
	Cleaned           int    `json:"cleaned_collections"` // leftover collections deleted
	VerifiedUnchanged bool   `json:"verified_unchanged"`  // sync found the publication healthy
	// CleanupPending lists recorded leftover collections still present after
	// this run's cleanup (deletion failed, cleanup stopped, or not eligible
	// for this operation); CleanupError says why cleanup was incomplete.
	CleanupPending []string `json:"cleanup_pending"`
	CleanupError   string   `json:"cleanup_error,omitempty"`
	Outcome        string   `json:"outcome"`
	OwnershipLost  bool     `json:"ownership_lost"`
}

// SemanticIndexService runs explicit, operator-initiated index operations.
// Work is sequential and bounded by batchSize; every external call receives
// the caller's context.
type SemanticIndexService struct {
	concepts  SemanticConceptReader
	store     SemanticIndexStore
	index     VectorIndex
	provider  EmbeddingProvider
	space     SemanticIndexSpace
	batchSize int
	leaseTTL  time.Duration
	now       func() time.Time
	// gate is a test hook called after a gate re-validated ownership and
	// immediately before the guarded external mutation or bookkeeping write:
	// the worst point for a run to be paused.
	gate func(step string)
}

func NewSemanticIndexService(concepts SemanticConceptReader, store SemanticIndexStore, index VectorIndex, provider EmbeddingProvider, space SemanticIndexSpace, batchSize int) *SemanticIndexService {
	if batchSize < 1 {
		batchSize = SemanticIndexDefaultBatchSize
	}
	if batchSize > SemanticIndexMaxBatchSize {
		batchSize = SemanticIndexMaxBatchSize
	}
	return &SemanticIndexService{concepts: concepts, store: store, index: index, provider: provider, space: space,
		batchSize: batchSize, leaseTTL: SemanticIndexDefaultLeaseTTL, now: func() time.Time { return time.Now().UTC() }}
}

// WithClock replaces the clock (tests).
func (s *SemanticIndexService) WithClock(now func() time.Time) *SemanticIndexService {
	s.now = now
	return s
}

// WithLeaseTTL replaces the lease duration (tests and operators).
func (s *SemanticIndexService) WithLeaseTTL(ttl time.Duration) *SemanticIndexService {
	if ttl > 0 {
		s.leaseTTL = ttl
	}
	return s
}

// WithGateHook installs a hook called at every gate, after the ownership check
// and immediately before the guarded action. Tests use it to pause a run.
func (s *SemanticIndexService) WithGateHook(hook func(step string)) *SemanticIndexService {
	s.gate = hook
	return s
}

// SemanticRunOptions controls lease takeover.
type SemanticRunOptions struct {
	// Takeover takes the lease even if another run holds it unexpired. Use only
	// when that run is known to be dead; a superseded live run will stop at its
	// next gate and can never publish.
	Takeover bool
}

// Build publishes the first collection; it refuses if one is published.
func (s *SemanticIndexService) Build(ctx context.Context, opts SemanticRunOptions) (*SemanticIndexReport, error) {
	return s.run(ctx, "build", opts)
}

// Sync verifies the published collection against SQLite and the cache. If it
// is healthy nothing is written; otherwise a fresh collection is published.
func (s *SemanticIndexService) Sync(ctx context.Context, opts SemanticRunOptions) (*SemanticIndexReport, error) {
	return s.run(ctx, "sync", opts)
}

// Rebuild always publishes a fresh collection and removes leftover ones.
func (s *SemanticIndexService) Rebuild(ctx context.Context, opts SemanticRunOptions) (*SemanticIndexReport, error) {
	return s.run(ctx, "rebuild", opts)
}

// checkpoint renews the lease and fails if ownership is gone. It is called
// before every vector-store mutation and every bookkeeping write.
func (s *SemanticIndexService) checkpoint(ctx context.Context, runID, step string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if err := s.store.RenewLease(ctx, s.space.Collection, runID, s.now().Add(s.leaseTTL)); err != nil {
		return err
	}
	if s.gate != nil {
		s.gate(step)
	}
	return nil
}

// mutationErr explains a failed vector-store mutation: if this run has lost
// the lease meanwhile (a newer run may already have removed this run's private
// collection), report the ownership loss rather than the vector-store error.
func (s *SemanticIndexService) mutationErr(ctx context.Context, runID string, err error) error {
	if err == nil {
		return nil
	}
	if lost := s.store.RenewLease(context.WithoutCancel(ctx), s.space.Collection, runID, s.now().Add(s.leaseTTL)); errors.Is(lost, ErrSemanticIndexOwnershipLost) {
		return fmt.Errorf("%w (vector store: %v)", ErrSemanticIndexOwnershipLost, err)
	}
	return err
}

func (s *SemanticIndexService) run(ctx context.Context, operation string, opts SemanticRunOptions) (report *SemanticIndexReport, err error) {
	if s.provider == nil {
		return nil, fmt.Errorf("%w: no embedding provider", ErrSemanticSearchDisabled)
	}
	runID, err := newRunID()
	if err != nil {
		return nil, err
	}
	started := s.now()
	if err := s.store.AcquireLease(ctx, s.space, runID, operation, started, started.Add(s.leaseTTL), opts.Takeover); err != nil {
		return nil, err
	}
	report = &SemanticIndexReport{Operation: operation, RunID: runID, Space: s.space.Collection, CleanupPending: []string{}}
	created := "" // this run's physical collection, once registered

	defer func() {
		// Adapters may report a canceled request as "unavailable"; attach the
		// context error so the outcome says "interrupted".
		if err != nil && ctx.Err() != nil && !errors.Is(err, ctx.Err()) {
			err = fmt.Errorf("%w (%w)", ctx.Err(), err)
		}
		cleanCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 10*time.Second)
		defer cancel()
		if created != "" && !report.Published {
			// Our own unpublished collection: deleting it cannot affect any
			// other run. Bookkeeping for it is fenced like everything else.
			if delErr := s.index.DeleteCollection(cleanCtx, created); delErr == nil {
				_ = s.store.ForgetCollection(cleanCtx, s.space.Collection, runID, created)
			} else {
				_ = s.store.MarkCollection(cleanCtx, s.space.Collection, runID, created, PhysicalAbandoned, s.now())
			}
		}
		outcome := SemanticRunOutcome{StartedAt: started, FinishedAt: s.now()}
		switch {
		case err == nil && report.VerifiedUnchanged:
			outcome.Outcome, outcome.LastError = RunOutcomeVerifiedUnchanged, cleanupNote(report)
		case err == nil:
			outcome.Outcome, outcome.LastError = RunOutcomePublished, cleanupNote(report)
		case errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded):
			outcome.Outcome, outcome.LastError = RunOutcomeInterrupted, semanticErrorCategory(err)
		case errors.Is(err, ErrSemanticSourcesChanged):
			outcome.Outcome, outcome.LastError = RunOutcomeSourcesChanged, semanticErrorCategory(err)
		default:
			outcome.Outcome, outcome.LastError = RunOutcomeFailed, semanticErrorCategory(err)
		}
		report.Outcome = outcome.Outcome
		if errors.Is(err, ErrSemanticIndexOwnershipLost) {
			report.OwnershipLost = true
			return // a superseded run records nothing about the space
		}
		// CompleteRun also releases the lease; it is fenced, so it records
		// nothing if another run took over meanwhile.
		if finishErr := s.store.CompleteRun(cleanCtx, s.space.Collection, runID, operation, outcome); finishErr != nil {
			switch {
			case errors.Is(finishErr, ErrSemanticIndexOwnershipLost) && err != nil:
				report.OwnershipLost = true
				err = fmt.Errorf("%w (%w)", finishErr, err)
			case errors.Is(finishErr, ErrSemanticIndexOwnershipLost):
				report.OwnershipLost = true
				err = finishErr
			case err == nil:
				err = finishErr
			}
		}
	}()

	state, err := s.store.SpaceState(ctx, s.space.Collection)
	if err != nil {
		return report, err
	}
	docs, err := s.currentDocs(ctx)
	if err != nil {
		return report, err
	}
	report.Concepts = len(docs)

	if operation == "build" && state != nil && state.PublishedCollection != "" {
		return report, fmt.Errorf("%w (%s); use sync or rebuild", ErrSemanticIndexExists, state.PublishedCollection)
	}
	if operation == "sync" && state != nil && state.PublishedCollection != "" {
		health, herr := s.verify(ctx, state.PublishedCollection, docs)
		if herr != nil {
			return report, herr
		}
		if health.Healthy {
			report.VerifiedUnchanged = true
			report.Collection = state.PublishedCollection
			// Nothing to publish, but leftovers recorded by earlier runs
			// (a failed deletion, an abandoned collection) are retried now
			// under this run's lease. Other runs' "writing" collections are
			// left to a publishing run.
			s.cleanup(ctx, runID, state.PublishedCollection, cleanupLeftovers, report)
			return report, nil
		}
	}

	vectors, err := s.ensureVectors(ctx, runID, docs, report)
	if err != nil {
		return report, err
	}

	collection := s.space.PhysicalCollectionName(runID)
	if err := s.checkpoint(ctx, runID, "register-collection"); err != nil {
		return report, err
	}
	if err := s.store.RegisterCollection(ctx, s.space.Collection, runID, collection, s.now()); err != nil {
		return report, err
	}
	created, report.Collection = collection, collection
	if err := s.checkpoint(ctx, runID, "create-collection"); err != nil {
		return report, err
	}
	if err := s.index.CreateCollection(ctx, collection, s.space.Dimensions); err != nil {
		return report, s.mutationErr(ctx, runID, err)
	}

	written := map[int64]string{}
	if err := s.writePoints(ctx, runID, collection, docs, vectors, written, report); err != nil {
		return report, err
	}
	// Catch up with sources that changed while we were writing.
	for pass := 0; ; pass++ {
		current, err := s.currentDocs(ctx)
		if err != nil {
			return report, err
		}
		changed, removed := diffManifest(current, written)
		if len(changed) == 0 && len(removed) == 0 {
			docs = current
			break
		}
		if pass == semanticCatchUpPasses {
			return report, fmt.Errorf("%w: %d still differ after %d catch-up passes", ErrSemanticSourcesChanged, len(changed)+len(removed), semanticCatchUpPasses)
		}
		report.CatchUpChanges += len(changed) + len(removed)
		more, err := s.ensureVectors(ctx, runID, changed, report)
		if err != nil {
			return report, err
		}
		for h, v := range more {
			vectors[h] = v
		}
		if err := s.writePoints(ctx, runID, collection, changed, vectors, written, report); err != nil {
			return report, err
		}
		for start := 0; start < len(removed); start += s.batchSize {
			batch := removed[start:min(start+s.batchSize, len(removed))]
			if err := s.checkpoint(ctx, runID, "delete-points"); err != nil {
				return report, err
			}
			if err := s.index.Delete(ctx, collection, batch); err != nil {
				return report, s.mutationErr(ctx, runID, err)
			}
			if err := s.checkpoint(ctx, runID, "remove-manifest"); err != nil {
				return report, err
			}
			if err := s.store.RemoveManifest(ctx, s.space.Collection, runID, collection, batch); err != nil {
				return report, err
			}
			for _, id := range batch {
				delete(written, id)
			}
		}
	}

	// Verify our own collection completely before anyone can read it.
	health, err := s.verify(ctx, collection, docs)
	if err != nil {
		return report, s.mutationErr(ctx, runID, err)
	}
	if !health.Healthy {
		return report, fmt.Errorf("%w: %s", ErrSemanticVerificationFailed, health.Summary())
	}

	if err := s.checkpoint(ctx, runID, "publish"); err != nil {
		return report, err
	}
	previous, err := s.store.Publish(ctx, s.space.Collection, runID, collection, s.now())
	if err != nil {
		return report, err
	}
	report.Published, report.Replaced = true, previous

	// Remove the replaced collection and leftovers. The new publication is
	// already committed; a failure here only leaves recorded "retired" or
	// "abandoned" collections that status lists and the next run removes.
	scope := cleanupRecorded
	if operation == "rebuild" {
		scope = cleanupUnrecorded
	}
	s.cleanup(ctx, runID, collection, scope, report)
	return report, nil
}

// writePoints upserts documents in bounded batches into this run's own
// collection, recording each batch only after the vector store acknowledged it.
func (s *SemanticIndexService) writePoints(ctx context.Context, runID, collection string, docs []SemanticIndexDocument, vectors map[string][]float32, written map[int64]string, report *SemanticIndexReport) error {
	for start := 0; start < len(docs); start += s.batchSize {
		batch := docs[start:min(start+s.batchSize, len(docs))]
		points := make([]VectorPoint, 0, len(batch))
		recorded := make(map[int64]string, len(batch))
		for _, d := range batch {
			points = append(points, VectorPoint{ConceptID: d.ConceptID, ContentHash: d.ContentHash, Vector: vectors[d.ContentHash]})
			recorded[d.ConceptID] = d.ContentHash
		}
		if err := s.checkpoint(ctx, runID, "upsert"); err != nil {
			return err
		}
		if err := s.index.Upsert(ctx, collection, s.space, points); err != nil {
			return s.mutationErr(ctx, runID, err)
		}
		if err := s.checkpoint(ctx, runID, "record-manifest"); err != nil {
			return err
		}
		if err := s.store.RecordManifest(ctx, s.space.Collection, runID, collection, recorded); err != nil {
			return err
		}
		for id, h := range recorded {
			written[id] = h
		}
		report.Upserted += len(points)
	}
	return nil
}

// cleanupScope selects which collections of this space a run may delete.
type cleanupScope int

const (
	// cleanupLeftovers: recorded retired and abandoned collections. Neither
	// status is ever published again or written by any run, so deleting them
	// cannot affect a live run or the current publication.
	cleanupLeftovers cleanupScope = iota
	// cleanupRecorded adds "writing" collections of other runs. Only a run
	// that has just published uses it: such a run held the lease throughout,
	// so those runs are dead or superseded and can never publish.
	cleanupRecorded
	// cleanupUnrecorded adds Qdrant collections named for this space that
	// SQLite does not record (rebuild only), for example an FLH-040 collection.
	cleanupUnrecorded
)

// cleanup deletes collections of this space other than keep and the
// published one, within scope. Each deletion is gated by the lease; each
// record is forgotten by a fenced write only after its deletion succeeded.
// Failures never undo the run's result: what remains is reported in
// CleanupPending/CleanupError, stays recorded, and status lists it.
func (s *SemanticIndexService) cleanup(ctx context.Context, runID, keep string, scope cleanupScope, report *SemanticIndexReport) {
	fail := func(err error) {
		if report.CleanupError == "" {
			report.CleanupError = semanticErrorCategory(err)
		}
	}
	recorded, err := s.store.PhysicalCollections(ctx, s.space.Collection)
	if err != nil {
		fail(err)
		return
	}
	known := map[string]bool{}
	var stopped error
	for _, c := range recorded {
		known[c.Collection] = true
		if c.Collection == keep || c.Status == PhysicalPublished {
			continue
		}
		eligible := c.Status == PhysicalRetired || c.Status == PhysicalAbandoned || (scope >= cleanupRecorded && c.RunID != runID)
		if !eligible || stopped != nil {
			report.CleanupPending = append(report.CleanupPending, c.Collection)
			continue
		}
		if stopped = s.checkpoint(ctx, runID, "delete-collection"); stopped != nil {
			fail(stopped)
			report.CleanupPending = append(report.CleanupPending, c.Collection)
			continue
		}
		if err := s.index.DeleteCollection(ctx, c.Collection); err != nil {
			fail(err)
			report.CleanupPending = append(report.CleanupPending, c.Collection)
			continue
		}
		if err := s.store.ForgetCollection(ctx, s.space.Collection, runID, c.Collection); err != nil {
			// Deleted from Qdrant but still recorded (for example the lease
			// was lost meanwhile); the next run's deletion is a no-op.
			fail(err)
			report.CleanupPending = append(report.CleanupPending, c.Collection)
			continue
		}
		report.Cleaned++
	}
	if scope < cleanupUnrecorded || stopped != nil {
		return
	}
	names, err := s.index.ListCollections(ctx)
	if err != nil {
		fail(err)
		return
	}
	for _, name := range names {
		if known[name] || !(name == s.space.Collection || strings.HasPrefix(name, s.space.Collection+"_r")) {
			continue
		}
		if err := s.checkpoint(ctx, runID, "delete-collection"); err != nil {
			fail(err)
			return
		}
		if err := s.index.DeleteCollection(ctx, name); err != nil {
			fail(err)
			continue
		}
		report.Cleaned++
	}
}

// cleanupNote is the last_error recorded for a successful run whose cleanup
// was incomplete, so that `status` shows it next to the leftovers.
func cleanupNote(r *SemanticIndexReport) string {
	if len(r.CleanupPending) == 0 && r.CleanupError == "" {
		return ""
	}
	note := fmt.Sprintf("cleanup incomplete: %d leftover collection(s) remain", len(r.CleanupPending))
	if r.CleanupError != "" {
		note += " (" + r.CleanupError + ")"
	}
	return note
}

func (s *SemanticIndexService) currentDocs(ctx context.Context) ([]SemanticIndexDocument, error) {
	concepts, err := s.concepts.ListConcepts(ctx, nil)
	if err != nil {
		return nil, err
	}
	docs := make([]SemanticIndexDocument, 0, len(concepts))
	for _, c := range concepts {
		d, err := BuildSemanticIndexDocument(c)
		if err != nil {
			return nil, err
		}
		docs = append(docs, d)
	}
	sort.Slice(docs, func(i, j int) bool { return docs[i].ConceptID < docs[j].ConceptID })
	return docs, nil
}

func diffManifest(current []SemanticIndexDocument, written map[int64]string) (changed []SemanticIndexDocument, removed []int64) {
	present := make(map[int64]bool, len(current))
	for _, d := range current {
		present[d.ConceptID] = true
		if written[d.ConceptID] != d.ContentHash {
			changed = append(changed, d)
		}
	}
	for id := range written {
		if !present[id] {
			removed = append(removed, id)
		}
	}
	sort.Slice(removed, func(i, j int) bool { return removed[i] < removed[j] })
	return changed, removed
}

// ensureVectors returns a vector for every document, embedding only cache
// misses in sequential bounded batches. Each batch is saved (content-addressed,
// shared by all runs, never overwritten) before the next provider call, so an
// interrupted run keeps the work already paid for.
func (s *SemanticIndexService) ensureVectors(ctx context.Context, runID string, docs []SemanticIndexDocument, report *SemanticIndexReport) (map[string][]float32, error) {
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
		// Renewing here keeps the lease alive through long embedding phases and
		// stops a superseded run before it spends more provider calls.
		if err := s.checkpoint(ctx, runID, "embed"); err != nil {
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

// SemanticIndexHealth is a live verification of one collection against the
// current SQLite documents and the cached vectors. It is computed from the full
// point inventory, never from the point count alone.
type SemanticIndexHealth struct {
	Collection     string  `json:"collection"`
	Exists         bool    `json:"exists"`
	Dimensions     int     `json:"dimensions"`
	Distance       string  `json:"distance"`
	ShapeOK        bool    `json:"shape_ok"`
	Expected       int     `json:"expected"`
	Points         int     `json:"points"`
	Missing        []int64 `json:"missing"`         // current Concepts with no point
	Extra          []int64 `json:"extra"`           // points for ids not in SQLite
	ForeignPayload []int64 `json:"foreign_payload"` // payload not written for this space
	Stale          []int64 `json:"stale"`           // payload hash differs from the current document
	VectorMismatch []int64 `json:"vector_mismatch"` // vector differs from the cached embedding
	Unverifiable   []int64 `json:"unverifiable"`    // no cached vector to compare with
	Healthy        bool    `json:"healthy"`
}

// Summary is a short human-readable description of the problems found.
func (h SemanticIndexHealth) Summary() string {
	if !h.Exists {
		return "collection missing"
	}
	if !h.ShapeOK {
		return fmt.Sprintf("collection shape %d dims %s", h.Dimensions, h.Distance)
	}
	parts := []string{}
	for _, p := range []struct {
		name string
		ids  []int64
	}{{"missing", h.Missing}, {"extra", h.Extra}, {"foreign payload", h.ForeignPayload}, {"stale", h.Stale}, {"vector mismatch", h.VectorMismatch}, {"unverifiable", h.Unverifiable}} {
		if len(p.ids) > 0 {
			parts = append(parts, fmt.Sprintf("%d %s", len(p.ids), p.name))
		}
	}
	if len(parts) == 0 {
		return "healthy"
	}
	return strings.Join(parts, ", ")
}

// verify scans the whole collection in bounded pages and compares every point
// with the current documents and cached vectors.
func (s *SemanticIndexService) verify(ctx context.Context, collection string, docs []SemanticIndexDocument) (SemanticIndexHealth, error) {
	h := SemanticIndexHealth{Collection: collection, Expected: len(docs)}
	info, err := s.index.CollectionInfo(ctx, collection)
	if err != nil {
		return h, err
	}
	h.Exists, h.Dimensions, h.Distance = info.Exists, info.Dimensions, info.Distance
	if !info.Exists {
		return h, nil
	}
	h.ShapeOK = info.Dimensions == s.space.Dimensions && strings.EqualFold(info.Distance, "cosine")
	if !h.ShapeOK {
		return h, nil
	}
	expected := make(map[int64]string, len(docs))
	hashes := make([]string, 0, len(docs))
	for _, d := range docs {
		expected[d.ConceptID] = d.ContentHash
		hashes = append(hashes, d.ContentHash)
	}
	cached, err := s.store.CachedVectors(ctx, s.space, hashes)
	if err != nil {
		return h, err
	}
	seen := map[int64]bool{}
	var offset *int64
	for {
		points, next, err := s.index.Scroll(ctx, collection, offset, s.batchSize)
		if err != nil {
			return h, err
		}
		for _, p := range points {
			h.Points++
			seen[p.ConceptID] = true
			want, ok := expected[p.ConceptID]
			switch {
			case !ok:
				h.Extra = append(h.Extra, p.ConceptID)
			case !p.PayloadValid || p.Representation != s.space.Representation || p.ModelID != s.space.ModelID || p.Dimensions != s.space.Dimensions:
				h.ForeignPayload = append(h.ForeignPayload, p.ConceptID)
			case p.ContentHash != want:
				h.Stale = append(h.Stale, p.ConceptID)
			default:
				v, ok := cached[want]
				if !ok {
					h.Unverifiable = append(h.Unverifiable, p.ConceptID)
				} else if !sameDirection(p.Vector, v) {
					h.VectorMismatch = append(h.VectorMismatch, p.ConceptID)
				}
			}
		}
		if next == nil || len(points) == 0 {
			break
		}
		offset = next
	}
	for _, d := range docs {
		if !seen[d.ConceptID] {
			h.Missing = append(h.Missing, d.ConceptID)
		}
	}
	h.Healthy = len(h.Missing)+len(h.Extra)+len(h.ForeignPayload)+len(h.Stale)+len(h.VectorMismatch)+len(h.Unverifiable) == 0 &&
		h.Points == len(docs)
	return h, nil
}

// sameDirection compares a stored vector (Qdrant normalizes cosine vectors on
// write) with a cached one after normalizing both.
func sameDirection(stored, cached []float32) bool {
	if len(stored) != len(cached) {
		return false
	}
	var ns, nc float64
	for i := range stored {
		ns += float64(stored[i]) * float64(stored[i])
		nc += float64(cached[i]) * float64(cached[i])
	}
	if ns == 0 || nc == 0 {
		return false
	}
	ns, nc = math.Sqrt(ns), math.Sqrt(nc)
	for i := range stored {
		if math.Abs(float64(stored[i])/ns-float64(cached[i])/nc) > vectorMatchTolerance {
			return false
		}
	}
	return true
}

// SemanticIndexStatus separates three things: the run record (history), the
// lease, and a live verification of the published collection.
type SemanticIndexStatus struct {
	Space           SemanticIndexSpace        `json:"-"`
	State           *SemanticIndexSpaceState  `json:"state"`
	LeaseActive     bool                      `json:"lease_active"`
	Concepts        int                       `json:"concepts"`
	Health          *SemanticIndexHealth      `json:"health"` // nil when nothing is published
	HealthError     string                    `json:"health_error"`
	Collections     []PhysicalCollection      `json:"collections"`
	Unrecorded      []string                  `json:"unrecorded_collections"` // Qdrant collections of this space with no record
	OtherSpaces     []SemanticIndexSpaceState `json:"other_spaces"`
	CacheCounts     []SemanticCacheCount      `json:"cache_counts"`
	VerifiedHealthy bool                      `json:"verified_healthy"`
}

// Status is read-only: it writes nothing and never calls the embedding
// provider. A vector-store failure is reported in the result.
func (s *SemanticIndexService) Status(ctx context.Context) (*SemanticIndexStatus, error) {
	st := &SemanticIndexStatus{Space: s.space}
	state, err := s.store.SpaceState(ctx, s.space.Collection)
	if err != nil {
		return nil, err
	}
	st.State = state
	if state != nil && state.LeaseRunID != "" && state.LeaseExpiresAt != nil && state.LeaseExpiresAt.After(s.now()) {
		st.LeaseActive = true
	}
	docs, err := s.currentDocs(ctx)
	if err != nil {
		return nil, err
	}
	st.Concepts = len(docs)
	if st.Collections, err = s.store.PhysicalCollections(ctx, s.space.Collection); err != nil {
		return nil, err
	}
	all, err := s.store.SpaceStates(ctx)
	if err != nil {
		return nil, err
	}
	for _, o := range all {
		if o.Space != s.space.Collection {
			st.OtherSpaces = append(st.OtherSpaces, o)
		}
	}
	if st.CacheCounts, err = s.store.CacheCounts(ctx); err != nil {
		return nil, err
	}
	if state != nil && state.PublishedCollection != "" {
		h, err := s.verify(ctx, state.PublishedCollection, docs)
		if err != nil {
			st.HealthError = semanticErrorCategory(err)
		} else {
			st.Health = &h
			st.VerifiedHealthy = h.Healthy
		}
	}
	if names, err := s.index.ListCollections(ctx); err == nil {
		known := map[string]bool{}
		for _, c := range st.Collections {
			known[c.Collection] = true
		}
		for _, n := range names {
			if !known[n] && (n == s.space.Collection || strings.HasPrefix(n, s.space.Collection+"_r")) {
				st.Unrecorded = append(st.Unrecorded, n)
			}
		}
	}
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
	case errors.Is(err, ErrSemanticIndexOwnershipLost):
		return "ownership lost to a newer run"
	case errors.Is(err, ErrSemanticSourcesChanged):
		return "concepts kept changing during the run"
	case errors.Is(err, ErrSemanticVerificationFailed):
		return "new collection failed verification: " + strings.TrimPrefix(err.Error(), ErrSemanticVerificationFailed.Error()+": ")
	case errors.Is(err, ErrSemanticIndexExists):
		return "index already exists"
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
