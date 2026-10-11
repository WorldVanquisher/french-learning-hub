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
// that the collection exists with the configured shape.
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

// Search requires a non-empty query; browsing remains keyword search's job.
func (s *SemanticSearchService) Search(ctx context.Context, q LibrarySearchQuery) (*SemanticSearchReport, error) {
	if q.Text == "" {
		return nil, fmt.Errorf("%w: semantic search needs a non-empty q", ErrKnowledgeLibraryQuery)
	}
	state, err := s.published(ctx)
	if err != nil {
		return nil, err
	}

	raw, err := s.provider.Embed(ctx, []string{q.Text})
	if err != nil {
		return nil, fmt.Errorf("embed search query: %w", err)
	}
	if len(raw) != 1 {
		return nil, fmt.Errorf("%w: provider returned %d vectors for 1 text", ErrEmbeddingProviderUnavailable, len(raw))
	}
	queryVector, err := ValidateEmbedding(raw[0], s.space.Dimensions)
	if err != nil {
		return nil, fmt.Errorf("%w: query %v", ErrEmbeddingProviderUnavailable, err)
	}
	k := min(q.Limit*semanticSearchOverfetch, SemanticSearchMaxCandidates)
	hits, err := s.index.Query(ctx, state.PublishedCollection, queryVector, k)
	if errors.Is(err, ErrSemanticIndexNotBuilt) {
		// A newer run may have published and removed this collection between
		// our read and the query. Re-read the pointer once; never loop.
		again, perr := s.published(ctx)
		if perr != nil {
			return nil, perr
		}
		if again.PublishedCollection == state.PublishedCollection {
			return nil, err
		}
		state = again
		hits, err = s.index.Query(ctx, state.PublishedCollection, queryVector, k)
	}
	if err != nil {
		return nil, err
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
