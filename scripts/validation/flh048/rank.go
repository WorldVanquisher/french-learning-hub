package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sync"
	"time"

	"french-learning-app/internal/application"
)

// retrievalLimit is the existing evaluation policy's maximum K.
const retrievalLimit = 5

// Retriever states.
const (
	stateCompleted   = "completed"
	stateUnavailable = "unavailable"
	stateFailed      = "failed"
)

// Hit is one ranked candidate as returned by the existing retriever.
type Hit struct {
	ConceptFixtureID string          `json:"concept_fixture_id"`
	ConceptID        int64           `json:"concept_id"`
	Rank             int             `json:"rank"`
	Score            float64         `json:"score"`
	Evidence         json.RawMessage `json:"evidence"`
}

// QueryRun is one Retrieve call. Status is "ok", "error" or
// "not_run_after_error" (a retriever stops at its first error: no retries,
// no fallback).
type QueryRun struct {
	Status     string `json:"status"`
	Hits       []Hit  `json:"hits"`
	Error      string `json:"error,omitempty"`
	DurationNS int64  `json:"duration_ns"`
}

// RetrieverRun is the ranking output of one retriever over all queries.
type RetrieverRun struct {
	Name     string           `json:"name"`
	State    string           `json:"state"`
	Note     string           `json:"note,omitempty"`
	Queries  []QueryRun       `json:"-"` // aligned with RankingInputs.Queries
	Provider *ProviderCounter `json:"provider_counters,omitempty"`
}

// ProviderCounter wraps an EmbeddingProvider and counts what was submitted.
// It enforces an input-position cap before every call and checks observed
// dimensions; it never retries.
type ProviderCounter struct {
	mu         sync.Mutex
	inner      application.EmbeddingProvider
	maxInputs  int
	dimensions int // expected, 0 = not checked

	Requests          int   `json:"requests"`
	InputPositions    int   `json:"input_positions"`
	UniqueInputHashes int   `json:"unique_input_hashes"`
	Failures          int   `json:"failures"`
	RefusedOverCap    int   `json:"refused_over_cap"`
	ObservedDims      []int `json:"observed_dimensions"`
	seen              map[string]int
	inputs            [][]string // per request, for tests only
}

func NewProviderCounter(inner application.EmbeddingProvider, maxInputs, dimensions int) *ProviderCounter {
	return &ProviderCounter{inner: inner, maxInputs: maxInputs, dimensions: dimensions, seen: map[string]int{}, ObservedDims: []int{}}
}

func (p *ProviderCounter) Name() string { return p.inner.Name() }

func (p *ProviderCounter) Embed(ctx context.Context, texts []string) ([][]float64, error) {
	p.mu.Lock()
	if p.InputPositions+len(texts) > p.maxInputs {
		p.RefusedOverCap++
		p.mu.Unlock()
		return nil, fmt.Errorf("%w: input cap %d would be exceeded", application.ErrEmbeddingProviderUnavailable, p.maxInputs)
	}
	p.Requests++
	p.InputPositions += len(texts)
	for _, t := range texts {
		p.seen[sha256Hex([]byte(t))]++
	}
	p.UniqueInputHashes = len(p.seen)
	p.inputs = append(p.inputs, append([]string(nil), texts...))
	p.mu.Unlock()

	vectors, err := p.inner.Embed(ctx, texts)
	p.mu.Lock()
	defer p.mu.Unlock()
	if err != nil {
		p.Failures++
		return nil, err
	}
	for _, v := range vectors {
		if p.dimensions > 0 && len(v) != p.dimensions {
			p.Failures++
			return nil, fmt.Errorf("%w: provider returned %d dimensions, configured %d", application.ErrEmbeddingProviderUnavailable, len(v), p.dimensions)
		}
	}
	if len(vectors) > 0 && !containsInt(p.ObservedDims, len(vectors[0])) {
		p.ObservedDims = append(p.ObservedDims, len(vectors[0]))
	}
	return vectors, nil
}

func containsInt(xs []int, x int) bool {
	for _, v := range xs {
		if v == x {
			return true
		}
	}
	return false
}

// RunRetriever calls the existing implementation for each query, in query
// order, against the complete catalog. Output is checked like the existing
// evaluation service checks it (<= limit, consecutive ranks, unique, in
// catalog, finite scores). The first error stops this retriever.
//
// The overall deadline (ctx) is checked before and after every Retrieve and
// once more before the retriever is declared completed. A canceled or
// expired context fails the retriever explicitly: the query is an "error",
// later queries are not run, and Evaluate publishes no metrics. A result
// returned after the deadline is discarded, not scored. These checks cannot
// interrupt a synchronous Retrieve that ignores its context (the existing
// offline retrievers do); such a call runs to completion first. There is no
// hard process deadline and no extra goroutine.
func RunRetriever(ctx context.Context, r application.ConceptRetriever, in *RankingInputs) RetrieverRun {
	run := RetrieverRun{Name: r.Name(), State: stateCompleted, Queries: make([]QueryRun, len(in.Queries))}
	universe := make(map[int64]bool, len(in.Documents))
	for _, d := range in.Documents {
		universe[d.ConceptID] = true
	}
	failed := false
	for i, q := range in.Queries {
		if failed {
			run.Queries[i] = QueryRun{Status: "not_run_after_error", Hits: []Hit{}}
			continue
		}
		if err := ctx.Err(); err != nil {
			run.Queries[i] = QueryRun{Status: "error", Hits: []Hit{}, Error: deadlineError("before Retrieve", err)}
			run.State, failed = stateFailed, true
			continue
		}
		// Each call gets its own copy of the catalog so no retriever can see
		// another call's mutation.
		docs := cloneDocuments(in.Documents)
		start := time.Now()
		candidates, err := r.Retrieve(ctx, q, docs, retrievalLimit)
		elapsed := time.Since(start).Nanoseconds()
		if cerr := ctx.Err(); cerr != nil {
			// Whatever Retrieve returned, it finished after the deadline.
			msg := deadlineError("during Retrieve; its result is discarded", cerr)
			if err != nil {
				msg += " (Retrieve error: " + err.Error() + ")"
			}
			run.Queries[i] = QueryRun{Status: "error", Hits: []Hit{}, Error: msg, DurationNS: elapsed}
			run.State, failed = stateFailed, true
			continue
		}
		if err == nil {
			err = checkCandidates(candidates, universe)
		}
		if err != nil {
			run.Queries[i] = QueryRun{Status: "error", Hits: []Hit{}, Error: err.Error(), DurationNS: elapsed}
			run.State, failed = stateFailed, true
			continue
		}
		hits := make([]Hit, 0, len(candidates))
		for _, c := range candidates {
			hits = append(hits, Hit{ConceptFixtureID: in.ConceptFixtureIDs[c.ConceptID-1], ConceptID: c.ConceptID,
				Rank: c.Rank, Score: c.Score, Evidence: evidenceJSON(c.Evidence)})
		}
		run.Queries[i] = QueryRun{Status: "ok", Hits: hits, DurationNS: elapsed}
	}
	if err := ctx.Err(); err != nil && run.State == stateCompleted {
		// Never declare completion once the deadline has passed.
		run.State = stateFailed
		run.Note = deadlineError("before the retriever was declared completed", err)
	}
	return run
}

// deadlineError names the overall run deadline or cancellation explicitly.
func deadlineError(when string, err error) string {
	if errors.Is(err, context.DeadlineExceeded) {
		return "overall run timeout (-timeout) expired " + when
	}
	return "run canceled " + when + ": " + err.Error()
}

func cloneDocuments(docs []application.ConceptRetrievalDocument) []application.ConceptRetrievalDocument {
	out := make([]application.ConceptRetrievalDocument, len(docs))
	for i, d := range docs {
		d.IdentityFeatures = cloneMap(d.IdentityFeatures)
		out[i] = d
	}
	return out
}

func cloneMap(m map[string]string) map[string]string {
	out := make(map[string]string, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

func checkCandidates(cs []application.ConceptRetrievalCandidate, universe map[int64]bool) error {
	if len(cs) > retrievalLimit {
		return fmt.Errorf("retriever returned %d candidates, limit %d", len(cs), retrievalLimit)
	}
	seen := map[int64]bool{}
	for i, c := range cs {
		if c.Rank != i+1 {
			return fmt.Errorf("candidate ranks are not consecutive from 1")
		}
		if !universe[c.ConceptID] {
			return fmt.Errorf("candidate concept %d is not in the catalog", c.ConceptID)
		}
		if seen[c.ConceptID] {
			return fmt.Errorf("candidate concept %d returned twice", c.ConceptID)
		}
		if math.IsNaN(c.Score) || math.IsInf(c.Score, 0) {
			return fmt.Errorf("candidate concept %d has a non-finite score", c.ConceptID)
		}
		seen[c.ConceptID] = true
	}
	return nil
}

// evidenceJSON keeps JSON evidence structured and wraps any other text.
func evidenceJSON(s string) json.RawMessage {
	if json.Valid([]byte(s)) {
		return json.RawMessage(s)
	}
	b, _ := json.Marshal(s)
	return b
}

// plannedEmbeddingPositions is what the existing embedding retriever submits
// for this input: one batch of query + every document per query with content.
func plannedEmbeddingPositions(in *RankingInputs) int {
	return len(in.Queries) * (len(in.Documents) + 1)
}
