package application_test

import (
	"context"
	"errors"
	"math"
	"path/filepath"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
)

// ---- deterministic component stubs ----

type stubKeyword struct {
	ids   []int64
	err   error
	calls []application.LibrarySearchQuery
	byID  map[int64]domain.KnowledgeConcept
}

func (s *stubKeyword) Search(_ context.Context, q application.LibrarySearchQuery) (*application.LibrarySearchReport, error) {
	s.calls = append(s.calls, q)
	if s.err != nil {
		return nil, s.err
	}
	r := &application.LibrarySearchReport{Query: q.Text, Limit: q.Limit, TotalMatches: len(s.ids)}
	for _, id := range s.ids {
		r.Results = append(r.Results, application.LibrarySearchResult{Concept: s.byID[id], MatchTier: "identity", MatchedFields: []string{"target"}})
	}
	return r, nil
}

type stubSemantic struct {
	ids   []int64
	err   error
	calls []application.LibrarySearchQuery
	byID  map[int64]domain.KnowledgeConcept
}

func (s *stubSemantic) Search(_ context.Context, q application.LibrarySearchQuery) (*application.SemanticSearchReport, error) {
	s.calls = append(s.calls, q)
	if s.err != nil {
		return nil, s.err
	}
	r := &application.SemanticSearchReport{Query: q.Text, Limit: q.Limit, Collection: "space_r1", Results: []application.SemanticSearchResult{}}
	for i, id := range s.ids {
		r.Results = append(r.Results, application.SemanticSearchResult{Concept: s.byID[id], Similarity: 0.9 - 0.1*float64(i)})
	}
	return r, nil
}

type hybridStubs struct {
	keyword  *stubKeyword
	semantic *stubSemantic
	current  *fakeConcepts
	svc      *application.HybridSearchService
}

// newHybridStubs gives every id a Concept "c<id>"; keyword and semantic return
// their ids in the given order (their ranks), and current is what the final
// re-read sees.
func newHybridStubs(keyword, semantic []int64) *hybridStubs {
	byID := map[int64]domain.KnowledgeConcept{}
	current := newFakeConcepts()
	for _, ids := range [][]int64{keyword, semantic} {
		for _, id := range ids {
			c := concept(id, "c"+itoa64(id), domain.ConceptActive)
			byID[id] = c
			current.set(c)
		}
	}
	h := &hybridStubs{keyword: &stubKeyword{ids: keyword, byID: byID}, semantic: &stubSemantic{ids: semantic, byID: byID}, current: current}
	h.svc = application.NewHybridSearchService(h.keyword, h.semantic, current, fixedSummarizer{})
	return h
}

func itoa64(n int64) string {
	if n == 0 {
		return "0"
	}
	var b []byte
	for n > 0 {
		b = append([]byte{byte('0' + n%10)}, b...)
		n /= 10
	}
	return string(b)
}

func hybridQuery(limit, depth int) application.HybridSearchQuery {
	return application.HybridSearchQuery{Text: "q", Limit: limit, Depth: depth}
}

func resultIDs(r *application.HybridSearchReport) []int64 {
	out := []int64{}
	for _, res := range r.Results {
		out = append(out, res.Concept.ID)
	}
	return out
}

func equalIDs(a, b []int64) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// ---- fusion arithmetic ----

func TestHybridFusion_HandComputedOverlap(t *testing.T) {
	// keyword: A=10 (1), B=20 (2), C=30 (3); semantic: B (1), D=40 (2), A (3).
	// Hand-computed with k = 60 and weights 1:
	//   B = 1/62 + 1/61 = 0.016129032 + 0.016393443 = 0.032522475
	//   A = 1/61 + 1/63 = 0.016393443 + 0.015873016 = 0.032266459
	//   D = 1/62                                    = 0.016129032
	//   C = 1/63                                    = 0.015873016
	h := newHybridStubs([]int64{10, 20, 30}, []int64{20, 40, 10})
	r, err := h.svc.Search(context.Background(), hybridQuery(10, 10))
	if err != nil {
		t.Fatal(err)
	}
	if !equalIDs(resultIDs(r), []int64{20, 10, 40, 30}) {
		t.Fatalf("order = %v", resultIDs(r))
	}
	want := []float64{0.032522475, 0.032266459, 0.016129032, 0.015873016}
	for i, res := range r.Results {
		if math.Abs(res.FusedScore-want[i]) > 1e-9 {
			t.Fatalf("result %d score %.12f, want %.9f", i, res.FusedScore, want[i])
		}
	}
	b := r.Results[0]
	if b.Keyword == nil || b.Keyword.Rank != 2 || b.Semantic == nil || b.Semantic.Rank != 1 || len(b.Sources()) != 2 {
		t.Fatalf("B evidence = %+v", b)
	}
	d := r.Results[2]
	if d.Keyword != nil || d.Semantic.Rank != 2 || d.Semantic.Similarity != 0.8 || d.Sources()[0] != "semantic" {
		t.Fatalf("D evidence = %+v", d)
	}
	c := r.Results[3]
	if c.Semantic != nil || c.Keyword.Rank != 3 || c.Keyword.MatchTier != "identity" || c.Sources()[0] != "keyword" {
		t.Fatalf("C evidence = %+v", c)
	}
	if r.TotalCandidates != 4 || r.Truncated || r.Results[0].CurrentMemberCount != 1 {
		t.Fatalf("report = %+v", r)
	}
}

func TestHybridFusion_TiesBreakByConceptID(t *testing.T) {
	cases := []struct {
		name              string
		keyword, semantic []int64
		want              []int64
	}{
		// 1/61 each: tie → lower id first.
		{"single tops", []int64{5}, []int64{3}, []int64{3, 5}},
		// 7: 1/61 + 1/62, 8: 1/62 + 1/61 — the same sum.
		{"swapped pair", []int64{7, 8}, []int64{8, 7}, []int64{7, 8}},
		// Disjoint: ranks 1 tie (1, 3), ranks 2 tie (2, 4).
		{"disjoint", []int64{1, 2}, []int64{3, 4}, []int64{1, 3, 2, 4}},
		// Identical lists keep their shared order.
		{"identical", []int64{9, 4, 6}, []int64{9, 4, 6}, []int64{9, 4, 6}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			r, err := newHybridStubs(tc.keyword, tc.semantic).svc.Search(context.Background(), hybridQuery(10, 10))
			if err != nil {
				t.Fatal(err)
			}
			if !equalIDs(resultIDs(r), tc.want) {
				t.Fatalf("order = %v, want %v", resultIDs(r), tc.want)
			}
		})
	}
	if application.FuseReciprocalRank(1, 2) != application.FuseReciprocalRank(2, 1) {
		t.Fatal("equal weights must be symmetric")
	}
	if application.FuseReciprocalRank(0, 0) != 0 || application.FuseReciprocalRank(1, 0) != 1.0/61 {
		t.Fatal("absent components contribute nothing")
	}
}

func TestHybridFusion_EmptyAndOneSidedResults(t *testing.T) {
	r, err := newHybridStubs(nil, nil).svc.Search(context.Background(), hybridQuery(5, 10))
	if err != nil || len(r.Results) != 0 || r.TotalCandidates != 0 || r.Truncated {
		t.Fatalf("both empty: %+v %v", r, err)
	}
	r, err = newHybridStubs(nil, []int64{4, 2, 9}).svc.Search(context.Background(), hybridQuery(5, 10))
	if err != nil || !equalIDs(resultIDs(r), []int64{4, 2, 9}) {
		t.Fatalf("semantic only keeps its order: %v %v", resultIDs(r), err)
	}
	r, err = newHybridStubs([]int64{8, 1}, nil).svc.Search(context.Background(), hybridQuery(5, 10))
	if err != nil || !equalIDs(resultIDs(r), []int64{8, 1}) || r.Results[0].Semantic != nil {
		t.Fatalf("keyword only keeps its order: %v %v", resultIDs(r), err)
	}
}

func TestHybridFusion_LimitDepthAndDuplicates(t *testing.T) {
	h := newHybridStubs([]int64{1, 2, 3, 4, 5, 6}, []int64{6, 6, 7, 1})
	r, err := h.svc.Search(context.Background(), application.HybridSearchQuery{Text: "q", Limit: 2, Depth: 4})
	if err != nil {
		t.Fatal(err)
	}
	for _, q := range []application.LibrarySearchQuery{h.keyword.calls[0], h.semantic.calls[0]} {
		if q.Limit != 4 || q.Text != "q" || q.State != nil {
			t.Fatalf("components must be asked for depth candidates: %+v", q)
		}
	}
	// Keyword is cut at depth 4 (5 and 6 are ignored). Semantic: 6 (1), duplicate 6
	// ignored, 7 (3), 1 (4). Fused: 1 = 1/61+1/64, 6 = 1/61, 2 = 1/62, 7 = 1/63, 3, 4.
	if r.Dropped.DuplicateComponentIDs != 1 || r.TotalCandidates != 6 || !r.Truncated || !equalIDs(resultIDs(r), []int64{1, 6}) {
		t.Fatalf("report = %+v ids %v", r.Dropped, resultIDs(r))
	}
	if r.Results[1].Keyword != nil || r.Results[1].Semantic.Rank != 1 {
		t.Fatalf("6 must be semantic-only (keyword 6 is beyond depth): %+v", r.Results[1])
	}
	h = newHybridStubs([]int64{1, 2, 3}, []int64{3})
	r, _ = h.svc.Search(context.Background(), application.HybridSearchQuery{Text: "q", Limit: 3, Depth: 3})
	if r.Truncated || r.TotalCandidates != 3 {
		t.Fatalf("exactly limit is not truncated: %+v", r)
	}
}

func TestHybridSearch_AuthorityRecheckAfterFusion(t *testing.T) {
	h := newHybridStubs([]int64{1, 2, 3, 4}, []int64{4, 5})
	h.current.remove(2)                                               // deleted after the components read it
	h.current.set(concept(3, "c3 renamed", domain.ConceptActive))     // identity changed after ranking
	h.current.set(concept(5, "c5", domain.ConceptRetired))            // state changed after ranking
	r, err := h.svc.Search(context.Background(), hybridQuery(10, 10)) // no state filter
	if err != nil {
		t.Fatal(err)
	}
	if !equalIDs(resultIDs(r), []int64{4, 1}) {
		t.Fatalf("ids = %v", resultIDs(r))
	}
	if r.Dropped.Missing != 1 || r.Dropped.ChangedDuringSearch != 2 || r.Dropped.FilteredByState != 0 {
		t.Fatalf("dropped = %+v", r.Dropped)
	}

	active := domain.ConceptActive
	h = newHybridStubs([]int64{1, 2}, []int64{2})
	h.current.set(concept(2, "c2", domain.ConceptOrphaned))
	r, err = h.svc.Search(context.Background(), application.HybridSearchQuery{Text: "q", State: &active, Limit: 10, Depth: 10})
	if err != nil {
		t.Fatal(err)
	}
	if !equalIDs(resultIDs(r), []int64{1}) || r.Dropped.FilteredByState != 1 {
		t.Fatalf("state filter: ids %v dropped %+v", resultIDs(r), r.Dropped)
	}
	if *h.keyword.calls[0].State != active || *h.semantic.calls[0].State != active {
		t.Fatal("both components must receive the same state filter")
	}
}

func TestHybridSearch_FailsExplicitlyWithoutFallback(t *testing.T) {
	h := newHybridStubs([]int64{1}, []int64{1})
	h.semantic.err = application.ErrEmbeddingProviderUnavailable
	r, err := h.svc.Search(context.Background(), hybridQuery(5, 10))
	if !errors.Is(err, application.ErrEmbeddingProviderUnavailable) || r != nil {
		t.Fatalf("semantic failure must fail hybrid: %v %+v", err, r)
	}
	if len(h.semantic.calls) != 1 {
		t.Fatalf("no retry beyond the semantic service's own contract: %d calls", len(h.semantic.calls))
	}
	for _, e := range []error{application.ErrSemanticIndexNotBuilt, application.ErrSemanticPublicationChanged, application.ErrVectorIndexTimeout} {
		h.semantic.err = e
		if _, err := h.svc.Search(context.Background(), hybridQuery(5, 10)); !errors.Is(err, e) {
			t.Fatalf("%v: got %v", e, err)
		}
	}

	h = newHybridStubs([]int64{1}, []int64{1})
	h.keyword.err = application.ErrKnowledgeLibraryQuery
	if _, err := h.svc.Search(context.Background(), hybridQuery(5, 10)); !errors.Is(err, application.ErrKnowledgeLibraryQuery) {
		t.Fatalf("keyword error: %v", err)
	}
	if len(h.semantic.calls) != 0 {
		t.Fatal("an invalid query must not reach the embedding provider")
	}
	if _, err := h.svc.Search(context.Background(), application.HybridSearchQuery{Text: "", Limit: 5, Depth: 10}); !errors.Is(err, application.ErrKnowledgeLibraryQuery) {
		t.Fatalf("empty q: %v", err)
	}
	if _, err := h.svc.Search(context.Background(), application.HybridSearchQuery{Text: "q", Limit: 9, Depth: 5}); !errors.Is(err, application.ErrKnowledgeLibraryQuery) {
		t.Fatalf("depth < limit: %v", err)
	}
}

func TestParseHybridSearchQuery(t *testing.T) {
	ptr := func(n int) *int { return &n }
	q, err := application.ParseHybridSearchQuery(" subjonctif ", "active", nil, nil)
	if err != nil || q.Text != "subjonctif" || q.Limit != 20 || q.Depth != 50 || *q.State != domain.ConceptActive {
		t.Fatalf("defaults: %+v %v", q, err)
	}
	q, err = application.ParseHybridSearchQuery("x y", "", ptr(5), ptr(5))
	if err != nil || q.Limit != 5 || q.Depth != 5 || q.State != nil {
		t.Fatalf("explicit: %+v %v", q, err)
	}
	bad := []struct {
		text, state  string
		limit, depth *int
	}{
		{"", "", nil, nil},
		{"   ", "", nil, nil},
		{"x", "gone", nil, nil},
		{"x", "", ptr(0), nil},
		{"x", "", ptr(51), nil},
		{"x", "", nil, ptr(0)},
		{"x", "", nil, ptr(51)},
		{"x", "", ptr(30), ptr(20)},
	}
	for _, b := range bad {
		if _, err := application.ParseHybridSearchQuery(b.text, b.state, b.limit, b.depth); !errors.Is(err, application.ErrKnowledgeLibraryQuery) {
			t.Fatalf("%+v: %v", b, err)
		}
	}
}

// ---- real keyword search and real semantic search over one SQLite database ----

type hybridStack struct {
	t        *testing.T
	ctx      context.Context
	ids      map[string]int64
	semantic *application.SemanticSearchService
	hybrid   *application.HybridSearchService
	index    *memIndex
	provider *fakeProvider
	build    func(op string) *application.SemanticIndexReport
	exec     func(query string, args ...any)
	state    func() *application.SemanticIndexSpaceState
}

func newHybridStack(t *testing.T) *hybridStack {
	t.Helper()
	ctx := context.Background()
	db, err := sqlite.Open(filepath.Join(t.TempDir(), "hybrid.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	conceptRepo := sqlite.NewConceptRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	conceptSvc := application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo)
	library := application.NewKnowledgeLibraryService(conceptRepo, knowledgeRepo, sqlite.NewEntryRepository(db),
		sqlite.NewAnalysisRepository(db), sqlite.NewFeedbackRepository(db), application.NewEffectiveAnnotationService(conceptRepo, conceptRepo))
	ids := map[string]int64{}
	for name, id := range map[string]domain.ConceptIdentity{
		"il_faut":  {Target: "subjonctif après il faut que", PedagogicalIntent: "grammar"},
		"mode":     {Target: "mode subjonctif", PedagogicalIntent: "grammar"},
		"pc":       {Target: "passé composé avec être", PedagogicalIntent: "grammar"},
		"manquer":  {Target: "tu me manques", PedagogicalIntent: "vocabulary"},
		"bien_que": {Target: "bien que takes the subjunctive", PedagogicalIntent: "grammar"},
	} {
		c, _, err := conceptSvc.CreateConcept(ctx, id, nil, false)
		if err != nil {
			t.Fatal(err)
		}
		ids[name] = c.ID
	}
	space, err := application.NewSemanticIndexSpace("hybrid", "fake/bag-of-words@1", testDims)
	if err != nil {
		t.Fatal(err)
	}
	store := sqlite.NewSemanticIndexRepository(db)
	index, provider := newMemIndex(), newFakeProvider(testDims)
	semantic := application.NewSemanticSearchService(conceptRepo, library, store, index, provider, space)
	s := &hybridStack{t: t, ctx: ctx, ids: ids, semantic: semantic, index: index, provider: provider,
		hybrid: application.NewHybridSearchService(library, semantic, conceptRepo, library)}
	s.build = func(op string) *application.SemanticIndexReport {
		return mustRun(t, op, application.NewSemanticIndexService(conceptRepo, store, index, provider, space, 10))
	}
	s.exec = func(query string, args ...any) {
		if _, err := db.Exec(query, args...); err != nil {
			t.Fatal(err)
		}
	}
	s.state = func() *application.SemanticIndexSpaceState {
		st, err := store.SpaceState(ctx, space.Collection)
		if err != nil {
			t.Fatal(err)
		}
		return st
	}
	return s
}

func (s *hybridStack) search(text string, limit, depth int) (*application.HybridSearchReport, error) {
	return s.hybrid.Search(s.ctx, application.HybridSearchQuery{Text: text, Limit: limit, Depth: depth})
}

func TestHybridSearch_RealComponentsEvidenceMatchesBothReports(t *testing.T) {
	s := newHybridStack(t)
	built := s.build("build")
	before := *s.state()
	r, err := s.search("subjonctif", 10, 10)
	if err != nil {
		t.Fatal(err)
	}
	if r.Semantic.Collection != built.Collection || r.Keyword.TotalMatches != 2 {
		t.Fatalf("components: keyword %+v semantic %s", r.Keyword, r.Semantic.Collection)
	}
	kwRank, semRank := map[int64]int{}, map[int64]int{}
	for i, res := range r.Keyword.Results {
		kwRank[res.Concept.ID] = i + 1
	}
	for i, res := range r.Semantic.Results {
		semRank[res.Concept.ID] = i + 1
	}
	for _, res := range r.Results {
		kr, sr := 0, 0
		if res.Keyword != nil {
			kr = res.Keyword.Rank
		}
		if res.Semantic != nil {
			sr = res.Semantic.Rank
		}
		if kr != kwRank[res.Concept.ID] || sr != semRank[res.Concept.ID] || res.FusedScore != application.FuseReciprocalRank(kr, sr) {
			t.Fatalf("evidence for %d does not match the component reports: %+v", res.Concept.ID, res)
		}
	}
	for _, name := range []string{"il_faut", "mode"} {
		found := false
		for _, res := range r.Results {
			if res.Concept.ID == s.ids[name] && res.Keyword != nil {
				found = true
			}
		}
		if !found {
			t.Fatalf("keyword match %s missing from the fused results", name)
		}
	}
	// Read-only: the published index state is unchanged and no document was embedded.
	if after := s.state(); after.PublishedCollection != before.PublishedCollection || after.PublishedRunID != before.PublishedRunID {
		t.Fatalf("search changed index state: %+v -> %+v", before, after)
	}
}

func TestHybridSearch_RealComponentsKeepSemanticRechecks(t *testing.T) {
	s := newHybridStack(t)
	s.build("build")
	// After the index was built, a Concept is renamed: its stored vector is stale.
	s.exec(`UPDATE knowledge_concepts SET target = 'subjonctif après il faut que (révisé)' WHERE id = ?`, s.ids["il_faut"])
	r, err := s.search("subjonctif", 10, 10)
	if err != nil {
		t.Fatal(err)
	}
	if r.Semantic.SkippedStale != 1 {
		t.Fatalf("semantic must drop the stale hit: %+v", r.Semantic)
	}
	for _, res := range r.Results {
		if res.Concept.ID == s.ids["il_faut"] && (res.Semantic != nil || res.Keyword == nil) {
			t.Fatalf("renamed concept may only carry keyword evidence: %+v", res)
		}
	}
	// Retired by a person: a state filter applies to both components consistently.
	s.exec(`UPDATE knowledge_concepts SET lifecycle_state = 'retired' WHERE id = ?`, s.ids["mode"])
	retired := domain.ConceptRetired
	r, err = s.hybrid.Search(s.ctx, application.HybridSearchQuery{Text: "subjonctif", State: &retired, Limit: 10, Depth: 10})
	if err != nil {
		t.Fatal(err)
	}
	for _, res := range r.Results {
		if res.Concept.State != domain.ConceptRetired {
			t.Fatalf("state filter leaked %+v", res.Concept)
		}
	}
	if len(r.Results) == 0 || r.Results[0].Concept.ID != s.ids["mode"] {
		t.Fatalf("retired match expected: %+v", resultIDs(r))
	}
}

func TestHybridSearch_RealComponentsOnePublicationAndExplicitFailure(t *testing.T) {
	s := newHybridStack(t)
	q := "subjonctif"
	if _, err := s.search(q, 5, 10); !errors.Is(err, application.ErrSemanticIndexNotBuilt) {
		t.Fatalf("unbuilt index must fail hybrid, not fall back: %v", err)
	}
	first := s.build("build").Collection
	var second string
	s.index.onQuery = func(collection string) {
		if collection == first {
			second = s.build("rebuild").Collection
		}
	}
	r, err := s.search(q, 5, 10)
	if err != nil {
		t.Fatal(err)
	}
	if second == "" || r.Semantic.Collection != second {
		t.Fatalf("hybrid must report the single publication semantic used: %s (second %s)", r.Semantic.Collection, second)
	}
	calls, _ := s.provider.counts()
	s.provider.failCall = calls + 1
	s.provider.failError = application.ErrEmbeddingProviderTimeout
	if r, err := s.search(q, 5, 10); !errors.Is(err, application.ErrEmbeddingProviderTimeout) || r != nil {
		t.Fatalf("provider failure: %v %+v", err, r)
	}
	s.index.unavailable = true
	if _, err := s.search(q, 5, 10); !errors.Is(err, application.ErrVectorIndexUnavailable) {
		t.Fatalf("vector store down: %v", err)
	}
	s.index.unavailable = false
	callsBefore, _ := s.provider.counts()
	if _, err := s.search("à", 5, 10); !errors.Is(err, application.ErrKnowledgeLibraryQuery) {
		t.Fatalf("unsearchable query: %v", err)
	}
	if callsAfter, _ := s.provider.counts(); callsAfter != callsBefore {
		t.Fatal("an invalid query must not call the embedding provider")
	}
}
