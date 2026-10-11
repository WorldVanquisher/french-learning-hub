package application

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"french-learning-app/internal/domain"
)

const (
	// SemanticSearchMaxCandidates bounds one vector-store query regardless of
	// the requested page size.
	SemanticSearchMaxCandidates = 200
	// semanticSearchOverfetch asks the index for more hits than the page so
	// that hits dropped by re-validation or the state filter rarely shorten the
	// page. Shortages are reported, never filled with other candidates.
	semanticSearchOverfetch = 4
)

// ErrSemanticPublicationChanged means the published collection was replaced
// again after this search had already used its one replacement retry. The
// index is not known to be broken; the caller may simply search again.
var ErrSemanticPublicationChanged = errors.New("semantic index publication changed during the search")

// ConceptSummarizer provides the same per-Concept counts as keyword search.
type ConceptSummarizer interface {
	ConceptCounts(ctx context.Context, conceptID int64) (currentMembers, supportingUnits int, err error)
}

// SemanticSearchIndexReader is the read-only bookkeeping used by search.
type SemanticSearchIndexReader interface {
	SpaceState(ctx context.Context, space string) (*SemanticIndexSpaceState, error)
}

// SemanticSearchResult is one Concept found by vector similarity, with current
// facts re-read from SQLite. Similarity is cosine similarity between the query
// and the Concept document embeddings: evidence, not a probability or a SAME
// judgment.
type SemanticSearchResult struct {
	Concept             domain.KnowledgeConcept
	Similarity          float64
	CurrentMemberCount  int
	SupportingUnitCount int
}

// SemanticSearchReport is one bounded semantic search page. Publication and
// last-run fields are recorded history; search does not verify index health
// (operators run `semantic-index status`). What this request did verify is
// reported in the per-hit counters.
type SemanticSearchReport struct {
	Query               string
	State               *domain.ConceptState
	Limit               int
	Space               SemanticIndexSpace
	Publication         SemanticIndexSpaceState
	Collection          string // the physical collection actually queried
	Considered          int
	SkippedMissing      int // hit for a Concept no longer in SQLite
	SkippedStale        int // hit whose document hash differs from the current Concept
	SkippedIncompatible int // hit payload from another space or not written by this system
	SkippedNonPositive  int // similarity <= 0
	FilteredByState     int
	Results             []SemanticSearchResult
}

// SemanticSearchService answers user semantic queries. It embeds the query
// (one provider call, never persisted), queries the published collection, and
// re-reads every candidate against SQLite before returning current facts. It
// never writes annotations, memberships or index state.
type SemanticSearchService struct {
	concepts   SemanticConceptReader
	summarizer ConceptSummarizer
	store      SemanticSearchIndexReader
	index      VectorIndex
	provider   EmbeddingProvider
	space      SemanticIndexSpace
}

func NewSemanticSearchService(concepts SemanticConceptReader, summarizer ConceptSummarizer, store SemanticSearchIndexReader, index VectorIndex, provider EmbeddingProvider, space SemanticIndexSpace) *SemanticSearchService {
	return &SemanticSearchService{concepts: concepts, summarizer: summarizer, store: store, index: index, provider: provider, space: space}
}

// published returns the space record and its published collection, checking
// that the collection exists with the configured shape. A missing collection
// returns the state it was read from, so the caller can tell replacement from
// loss.
func (s *SemanticSearchService) published(ctx context.Context) (*SemanticIndexSpaceState, error) {
	state, err := s.store.SpaceState(ctx, s.space.Collection)
	if err != nil {
		return nil, err
	}
	if state == nil || state.PublishedCollection == "" {
		return nil, fmt.Errorf("%w for model %q; run: semantic-index build", ErrSemanticIndexNotBuilt, s.space.ModelID)
	}
	info, err := s.index.CollectionInfo(ctx, state.PublishedCollection)
	if err != nil {
		return nil, err
	}
	if !info.Exists {
		return state, fmt.Errorf("%w: published collection %s is missing from the vector store; run: semantic-index sync", ErrSemanticIndexNotBuilt, state.PublishedCollection)
	}
	if info.Dimensions != s.space.Dimensions || !strings.EqualFold(info.Distance, "cosine") {
		return nil, fmt.Errorf("%w: collection has %d dimensions (%s), configured %d (Cosine)", ErrSemanticIndexIncompatible, info.Dimensions, info.Distance, s.space.Dimensions)
	}
	return state, nil
}

// embedQuery makes the search's single provider call.
func (s *SemanticSearchService) embedQuery(ctx context.Context, text string) ([]float32, error) {
	raw, err := s.provider.Embed(ctx, []string{text})
	if err != nil {
		return nil, fmt.Errorf("embed search query: %w", err)
	}
	if len(raw) != 1 {
		return nil, fmt.Errorf("%w: provider returned %d vectors for 1 text", ErrEmbeddingProviderUnavailable, len(raw))
	}
	v, err := ValidateEmbedding(raw[0], s.space.Dimensions)
	if err != nil {
		return nil, fmt.Errorf("%w: query %v", ErrEmbeddingProviderUnavailable, err)
	}
	return v, nil
}

// attempt reads the publication, embeds the query unless *vector is already
// set, and queries the published collection. On a missing collection it
// returns the state that named it.
func (s *SemanticSearchService) attempt(ctx context.Context, text string, vector *[]float32, k int) (*SemanticIndexSpaceState, []VectorHit, error) {
	state, err := s.published(ctx)
	if err != nil {
		return state, nil, err
	}
	if *vector == nil {
		v, err := s.embedQuery(ctx, text)
		if err != nil {
			return nil, nil, err
		}
		*vector = v
	}
	hits, err := s.index.Query(ctx, state.PublishedCollection, *vector, k)
	return state, hits, err
}

// Search requires a non-empty query; browsing remains keyword search's job.
//
// A run may publish a new collection and delete the one this search read from
// SQLite, either before the collection's metadata is read or before the query
// runs. Both windows report the collection as missing. Search then re-reads
// the pointer: if it is unchanged the collection really is lost and that is
// reported; if it changed, search retries once on the new publication, reusing
// the query vector if it was already computed. One retry per search in total;
// a second replacement ends with ErrSemanticPublicationChanged.
func (s *SemanticSearchService) Search(ctx context.Context, q LibrarySearchQuery) (*SemanticSearchReport, error) {
	if q.Text == "" {
		return nil, fmt.Errorf("%w: semantic search needs a non-empty q", ErrKnowledgeLibraryQuery)
	}
	k := min(q.Limit*semanticSearchOverfetch, SemanticSearchMaxCandidates)
	var queryVector []float32
	retried := false
	var state *SemanticIndexSpaceState
	var hits []VectorHit
	for {
		var err error
		state, hits, err = s.attempt(ctx, q.Text, &queryVector, k)
		if err == nil {
			break
		}
		if !errors.Is(err, ErrSemanticIndexNotBuilt) || state == nil {
			return nil, err
		}
		current, rerr := s.store.SpaceState(ctx, s.space.Collection)
		if rerr != nil {
			return nil, rerr
		}
		if current == nil || current.PublishedCollection == "" || current.PublishedCollection == state.PublishedCollection {
			return nil, err // the pointer did not change: a real loss
		}
		if retried {
			return nil, fmt.Errorf("%w: %s was replaced by %s after one retry; search again", ErrSemanticPublicationChanged, state.PublishedCollection, current.PublishedCollection)
		}
		retried = true
	}

	// Re-read current authority after the vector-store call.
	concepts, err := s.concepts.ListConcepts(ctx, nil)
	if err != nil {
		return nil, err
	}
	byID := make(map[int64]domain.KnowledgeConcept, len(concepts))
	for _, c := range concepts {
		byID[c.ID] = c
	}
	report := &SemanticSearchReport{Query: q.Text, State: q.State, Limit: q.Limit, Space: s.space, Publication: *state,
		Collection: state.PublishedCollection, Considered: len(hits), Results: []SemanticSearchResult{}}
	for _, h := range hits {
		if len(report.Results) == q.Limit {
			break
		}
		if h.Representation != s.space.Representation || h.ModelID != s.space.ModelID || h.Dimensions != s.space.Dimensions {
			report.SkippedIncompatible++
			continue
		}
		c, ok := byID[h.ConceptID]
		if !ok {
			report.SkippedMissing++
			continue
		}
		doc, err := BuildSemanticIndexDocument(c)
		if err != nil {
			return nil, err
		}
		if doc.ContentHash != h.ContentHash {
			report.SkippedStale++
			continue
		}
		if h.Score <= 0 {
			report.SkippedNonPositive++
			continue
		}
		if q.State != nil && c.State != *q.State {
			report.FilteredByState++
			continue
		}
		members, supporting, err := s.summarizer.ConceptCounts(ctx, c.ID)
		if err != nil {
			return nil, err
		}
		report.Results = append(report.Results, SemanticSearchResult{Concept: c, Similarity: h.Score, CurrentMemberCount: members, SupportingUnitCount: supporting})
	}
	return report, nil
}
