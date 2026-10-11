package application_test

import (
	"context"
	"database/sql"
	"errors"
	"path/filepath"
	"strings"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
)

const testDims = 64

type semanticFixture struct {
	t        *testing.T
	dbPath   string
	db       *sql.DB
	store    *sqlite.SemanticIndexRepository
	concepts *fakeConcepts
	provider *fakeProvider
	index    *memIndex
	space    application.SemanticIndexSpace
}

func newSemanticFixture(t *testing.T) *semanticFixture {
	t.Helper()
	f := &semanticFixture{t: t, dbPath: filepath.Join(t.TempDir(), "semantic.db"), provider: newFakeProvider(testDims), index: newMemIndex()}
	f.open()
	f.concepts = newFakeConcepts(
		concept(1, "subjunctive after il faut que", domain.ConceptActive),
		concept(2, "passé composé with être", domain.ConceptActive),
		concept(3, "overview of the subjunctive mood", domain.ConceptOrphaned),
		concept(4, "tu me manques", domain.ConceptRetired),
		concept(5, "bien que takes the subjunctive", domain.ConceptActive),
	)
	space, err := application.NewSemanticIndexSpace("test", "fake/bag-of-words@1", testDims)
	if err != nil {
		t.Fatal(err)
	}
	f.space = space
	return f
}

// open (re)opens the SQLite database, simulating a process restart.
func (f *semanticFixture) open() {
	if f.db != nil {
		f.db.Close()
	}
	db, err := sqlite.Open(f.dbPath)
	if err != nil {
		f.t.Fatal(err)
	}
	f.t.Cleanup(func() { db.Close() })
	f.db, f.store = db, sqlite.NewSemanticIndexRepository(db)
}

func (f *semanticFixture) service(batch int) *application.SemanticIndexService {
	return application.NewSemanticIndexService(f.concepts, f.store, f.index, f.provider, f.space, batch).WithClock(fixedClock())
}

func (f *semanticFixture) search() *application.SemanticSearchService {
	return application.NewSemanticSearchService(f.concepts, fixedSummarizer{}, f.store, f.index, f.provider, f.space)
}

func mustSync(t *testing.T, svc *application.SemanticIndexService) *application.SemanticIndexReport {
	t.Helper()
	r, err := svc.Sync(context.Background())
	if err != nil {
		t.Fatalf("sync: %v", err)
	}
	return r
}

func TestSemanticIndex_EmbeddingsAreReusedAcrossRunsAndRestart(t *testing.T) {
	f := newSemanticFixture(t)
	r := mustSync(t, f.service(2))
	if r.EmbeddedTexts != 5 || r.Upserted != 5 || r.State != application.SemanticIndexStateComplete {
		t.Fatalf("first sync = %+v", r)
	}
	calls1, texts1 := f.provider.counts()
	if calls1 != 3 || texts1 != 5 { // batches of 2: 2+2+1
		t.Fatalf("provider calls/texts after first sync = %d/%d", calls1, texts1)
	}

	r = mustSync(t, f.service(2))
	if r.EmbeddedTexts != 0 || r.ReusedVectors != 5 || r.Upserted != 0 || r.Unchanged != 5 || r.State != "complete" {
		t.Fatalf("second sync = %+v", r)
	}

	// Restart: reopen SQLite, drop the vector index entirely and rebuild.
	f.open()
	f.index = newMemIndex()
	r, err := f.service(2).Rebuild(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if r.EmbeddedTexts != 0 || r.ReusedVectors != 5 || r.Upserted != 5 || r.State != "complete" {
		t.Fatalf("rebuild after restart = %+v", r)
	}
	if calls, texts := f.provider.counts(); calls != calls1 || texts != texts1 {
		t.Fatalf("provider was called again: %d/%d", calls, texts)
	}

	// Searches embed only the query and never re-embed documents.
	before, _ := f.provider.counts()
	for i := 0; i < 3; i++ {
		if _, err := f.search().Search(context.Background(), application.LibrarySearchQuery{Text: "subjunctive", Limit: 5}); err != nil {
			t.Fatal(err)
		}
	}
	if after, _ := f.provider.counts(); after != before+3 {
		t.Fatalf("search provider calls = %d, want %d (one per query)", after-before, 3)
	}
}

func TestSemanticIndex_ContentChangeReembedsOnlyThatDocument(t *testing.T) {
	f := newSemanticFixture(t)
	mustSync(t, f.service(10))
	c := concept(2, "passé composé with avoir", domain.ConceptActive)
	f.concepts.set(c)
	st, err := f.service(10).Status(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if st.Stale != 1 || st.UpToDate != 4 || st.SearchableComplete {
		t.Fatalf("status after change = %+v", st)
	}
	r := mustSync(t, f.service(10))
	if r.EmbeddedTexts != 1 || r.Upserted != 1 || r.Unchanged != 4 || r.State != "complete" {
		t.Fatalf("sync after change = %+v", r)
	}
}

func TestSemanticIndex_ModelChangeUsesSeparateSpace(t *testing.T) {
	f := newSemanticFixture(t)
	mustSync(t, f.service(10))
	old := f.space
	space, err := application.NewSemanticIndexSpace("test", "fake/bag-of-words@2", testDims)
	if err != nil {
		t.Fatal(err)
	}
	if space.Collection == old.Collection {
		t.Fatal("a different model identity must map to a different collection")
	}
	f.space = space
	// Search before building the new space must not use the old vectors.
	if _, err := f.search().Search(context.Background(), application.LibrarySearchQuery{Text: "subjunctive", Limit: 5}); !errors.Is(err, application.ErrSemanticIndexNotBuilt) {
		t.Fatalf("search on unbuilt new space: %v", err)
	}
	r := mustSync(t, f.service(10))
	if r.EmbeddedTexts != 5 || r.ReusedVectors != 0 {
		t.Fatalf("new model must re-embed everything: %+v", r)
	}
	st, err := f.service(10).Status(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(st.OtherCollections) != 1 || st.OtherCollections[0].ModelID != old.ModelID || len(st.CacheCounts) != 2 {
		t.Fatalf("status must show the old space separately: %+v", st)
	}
}

func TestSemanticIndex_RejectsDimensionMismatchAndMalformedVectors(t *testing.T) {
	for name, mutate := range map[string]func(*fakeProvider){
		"dimension mismatch": func(p *fakeProvider) { p.badDims = true },
		"nan":                func(p *fakeProvider) { p.nan = true },
		"zero vector":        func(p *fakeProvider) { p.zero = true },
	} {
		t.Run(name, func(t *testing.T) {
			f := newSemanticFixture(t)
			mutate(f.provider)
			r, err := f.service(10).Sync(context.Background())
			if !errors.Is(err, application.ErrInvalidEmbedding) {
				t.Fatalf("err = %v", err)
			}
			if r.State != application.SemanticIndexStatePartial || r.Upserted != 0 {
				t.Fatalf("report = %+v", r)
			}
			col, _ := f.store.Collection(context.Background(), f.space.Collection)
			if col.State != "partial" || !strings.HasPrefix(col.LastError, "invalid embedding") {
				t.Fatalf("collection = %+v", col)
			}
			if counts, _ := f.store.CacheCounts(context.Background()); len(counts) != 0 {
				t.Fatalf("invalid vectors were cached: %+v", counts)
			}
		})
	}
}

func TestSemanticIndex_PartialProviderFailureKeepsCompletedBatches(t *testing.T) {
	f := newSemanticFixture(t)
	f.provider.failCall = 2
	r, err := f.service(2).Sync(context.Background())
	if !errors.Is(err, application.ErrEmbeddingProviderUnavailable) || r.State != "partial" {
		t.Fatalf("err=%v report=%+v", err, r)
	}
	if r.EmbeddedTexts != 2 || r.Upserted != 0 {
		t.Fatalf("first batch should be cached but nothing published: %+v", r)
	}
	st, _ := f.service(2).Status(context.Background())
	if st.SearchableComplete || st.Collection.State != "partial" || st.Collection.LastError != "embedding provider unavailable" {
		t.Fatalf("status = %+v / %+v", st, st.Collection)
	}
	f.provider.failCall = 0
	r = mustSync(t, f.service(2))
	if r.EmbeddedTexts != 3 || r.ReusedVectors != 2 || r.State != "complete" {
		t.Fatalf("recovery sync = %+v", r)
	}
}

func TestSemanticIndex_InterruptedRunIsPartialAndResumable(t *testing.T) {
	f := newSemanticFixture(t)
	ctx, cancel := context.WithCancel(context.Background())
	f.provider.onEmbed = func(call int) {
		if call == 2 {
			cancel() // interrupt during the second provider call
		}
	}
	r, err := f.service(2).Sync(ctx)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("err = %v", err)
	}
	if r.State != "partial" {
		t.Fatalf("report = %+v", r)
	}
	col, _ := f.store.Collection(context.Background(), f.space.Collection)
	if col.State != "partial" || col.LastError != "interrupted (canceled)" {
		t.Fatalf("collection = %+v", col)
	}
	f.provider.onEmbed = nil
	r = mustSync(t, f.service(2))
	if r.ReusedVectors != 2 || r.EmbeddedTexts != 3 || r.State != "complete" {
		t.Fatalf("resume = %+v", r)
	}
}

func TestSemanticIndex_SourceChangeBeforePublicationIsNotReportedComplete(t *testing.T) {
	f := newSemanticFixture(t)
	// ListConcepts call 1 = snapshot; call 2 = re-read before publishing.
	f.concepts.onList = func(call int) {
		if call == 2 {
			f.concepts.set(concept(1, "subjunctive after il faut que (revised)", domain.ConceptActive))
		}
	}
	r, err := f.service(10).Sync(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if r.ChangedDuringRun != 1 || r.Upserted != 4 || r.State != "partial" {
		t.Fatalf("report = %+v", r)
	}
	f.concepts.onList = nil
	r = mustSync(t, f.service(10))
	if r.Upserted != 1 || r.State != "complete" {
		t.Fatalf("follow-up sync = %+v", r)
	}
}

func TestSemanticIndex_SupersededRunDoesNotClaimCompletion(t *testing.T) {
	f := newSemanticFixture(t)
	f.provider.onEmbed = func(call int) {
		if call == 1 { // another operator run takes ownership mid-run
			if err := f.store.BeginRun(context.Background(), f.space, "other-run", "sync", fixedClock()()); err != nil {
				t.Error(err)
			}
		}
	}
	r := mustSync(t, f.service(10))
	if !r.Superseded {
		t.Fatalf("report = %+v", r)
	}
	col, _ := f.store.Collection(context.Background(), f.space.Collection)
	if col.State != "building" || col.RunID != "other-run" {
		t.Fatalf("the newer run's state must be preserved: %+v", col)
	}
}

func TestSemanticIndex_VectorStoreFailureAndLostCollection(t *testing.T) {
	f := newSemanticFixture(t)
	f.index.failUpsert = 2
	r, err := f.service(2).Sync(context.Background())
	if !errors.Is(err, application.ErrVectorIndexUnavailable) || r.State != "partial" || r.Upserted != 2 {
		t.Fatalf("err=%v report=%+v", err, r)
	}
	f.index.failUpsert = 0
	r = mustSync(t, f.service(2))
	if r.Upserted != 3 || r.EmbeddedTexts != 0 || r.State != "complete" {
		t.Fatalf("recovery = %+v", r)
	}

	// The vector store lost its data: bookkeeping must not be trusted.
	f.index = newMemIndex()
	st, _ := f.service(2).Status(context.Background())
	if st.SearchableComplete || st.VectorStore.Exists {
		t.Fatalf("status must expose the lost collection: %+v", st)
	}
	r = mustSync(t, f.service(2))
	if r.Upserted != 5 || r.EmbeddedTexts != 0 || r.State != "complete" {
		t.Fatalf("sync after loss = %+v", r)
	}

	f.index.unavailable = true
	st, err = f.service(2).Status(context.Background())
	if err != nil || st.VectorStoreError != "vector index unavailable" || st.SearchableComplete {
		t.Fatalf("status with unavailable store: err=%v %+v", err, st)
	}
}

func TestSemanticIndex_BuildRefusesExistingIndexAndRemovedConceptsAreDeleted(t *testing.T) {
	f := newSemanticFixture(t)
	if _, err := f.service(10).Build(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, err := f.service(10).Build(context.Background()); !errors.Is(err, application.ErrSemanticIndexExists) {
		t.Fatalf("second build: %v", err)
	}
	f.concepts.remove(5)
	r := mustSync(t, f.service(10))
	if r.Deleted != 1 || r.State != "complete" {
		t.Fatalf("sync after removal = %+v", r)
	}
}

func TestSemanticIndex_IncompatibleCollectionIsRefused(t *testing.T) {
	f := newSemanticFixture(t)
	if err := f.index.CreateCollection(context.Background(), f.space.Collection, testDims+1); err != nil {
		t.Fatal(err)
	}
	if _, err := f.service(10).Sync(context.Background()); !errors.Is(err, application.ErrSemanticIndexIncompatible) {
		t.Fatalf("err = %v", err)
	}
	if _, err := f.service(10).Rebuild(context.Background()); err != nil {
		t.Fatalf("rebuild must recover: %v", err)
	}
}
