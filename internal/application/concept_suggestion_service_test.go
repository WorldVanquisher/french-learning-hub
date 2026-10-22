package application

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

// fakeSuggestionRepo is an in-memory domain.ConceptSuggestionRepository for
// the service's request-recovery rules. Only what Generate uses is real.
type fakeSuggestionRepo struct {
	mu        sync.Mutex
	runs      map[string]*domain.ConceptSuggestionRun
	lookups   int
	gate      chan struct{} // when set, the first lookup waits on it
	commitErr error
}

func newFakeSuggestionRepo() *fakeSuggestionRepo {
	return &fakeSuggestionRepo{runs: map[string]*domain.ConceptSuggestionRun{}}
}

func (r *fakeSuggestionRepo) GetSuggestionRunByOperation(_ context.Context, op string) (*domain.ConceptSuggestionRun, error) {
	r.mu.Lock()
	r.lookups++
	first, gate := r.lookups == 1, r.gate
	run := r.runs[op]
	r.mu.Unlock()
	if first && gate != nil {
		<-gate
		r.mu.Lock()
		run = r.runs[op] // a read taken before the wait would be stale
		r.mu.Unlock()
	}
	if run == nil {
		return nil, domain.ErrNotFound
	}
	return run, nil
}

func (r *fakeSuggestionRepo) CommitSuggestionRun(ctx context.Context, in domain.NewSuggestionRun) (*domain.ConceptSuggestionRun, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	// A canceled context fails the commit, as SQLite's BeginTx would.
	if err := ctx.Err(); err != nil {
		return nil, false, err
	}
	if r.commitErr != nil {
		return nil, false, r.commitErr
	}
	if prior := r.runs[in.OperationID]; prior != nil {
		return prior, true, nil
	}
	run := &domain.ConceptSuggestionRun{ID: int64(len(r.runs) + 1), OperationID: in.OperationID, RequestUnitIDs: in.RequestUnitIDs,
		Status: in.Status, FailureCode: in.FailureCode, ProviderCalled: in.ProviderCalled, ItemCount: len(in.Items)}
	r.runs[in.OperationID] = run
	return run, false, nil
}

func (r *fakeSuggestionRepo) SuggestionSourceUnits(_ context.Context, ids []int64) ([]domain.SuggestionSourceUnit, error) {
	out := make([]domain.SuggestionSourceUnit, 0, len(ids))
	for _, id := range ids {
		out = append(out, domain.SuggestionSourceUnit{Unit: domain.KnowledgeUnit{ID: id, ExtractionID: 1, Kind: "grammar",
			Canonical: "parler langue", Statement: "After parler, no article."}, EntryID: 1, DistinctConceptIDs: map[int64]bool{}})
	}
	return out, nil
}

func (r *fakeSuggestionRepo) SuggestionCatalog(context.Context) ([]domain.KnowledgeConcept, error) {
	identity := domain.DeriveCandidateIdentity(domain.KnowledgeUnit{Kind: "grammar", Canonical: "parler langue"})
	return []domain.KnowledgeConcept{{ID: 40, Target: identity.Target, PedagogicalIntent: identity.PedagogicalIntent,
		IdentityFeatures: map[string]string{}, Signature: identity.Signature(), Lifecycle: domain.LifecycleNormal}}, nil
}

func (r *fakeSuggestionRepo) ConceptMemberExamples(context.Context, []int64, int) (map[int64][]domain.SuggestionMemberExample, error) {
	return map[int64][]domain.SuggestionMemberExample{}, nil
}
func (r *fakeSuggestionRepo) GetSuggestionRun(context.Context, int64) (*domain.ConceptSuggestionRun, error) {
	return nil, domain.ErrNotFound
}
func (r *fakeSuggestionRepo) ListSuggestionRuns(context.Context, int) ([]domain.ConceptSuggestionRun, error) {
	return nil, nil
}
func (r *fakeSuggestionRepo) ConfirmSuggestion(context.Context, int64, int64) (*domain.ConceptSuggestionItem, *domain.UnitConceptLink, bool, error) {
	return nil, nil, false, errors.New("not used")
}

// fakeSuggester answers every unit with its first candidate after an optional
// hook (used to cancel the request context or wait).
type fakeSuggester struct {
	calls  atomic.Int32
	before func(ctx context.Context) error
}

func (f *fakeSuggester) Name() string { return "fake:m:concept_suggestion_v1" }
func (f *fakeSuggester) Suggest(ctx context.Context, req domain.SuggestionRequest) ([]domain.SuggestionProposal, error) {
	f.calls.Add(1)
	if f.before != nil {
		if err := f.before(ctx); err != nil {
			return nil, err
		}
	}
	out := []domain.SuggestionProposal{}
	for _, u := range req.Units {
		id := u.Candidates[0].ConceptID
		out = append(out, domain.SuggestionProposal{UnitID: u.UnitID, Outcome: domain.SuggestionSuggested, ConceptID: &id, Reason: "same"})
	}
	return out, nil
}

const opKey = "6f1c7a0e-2b4d-4c8e-9a1b-0d2e3f4a5b6c"

// A request whose key lookup was overtaken by an earlier same-key request must
// not call the provider again: the lookup happens while holding the slot.
func TestGenerate_SameKeyRequestNeverCallsProviderTwice(t *testing.T) {
	repo := newFakeSuggestionRepo()
	repo.gate = make(chan struct{})
	sug := &fakeSuggester{}
	svc := NewConceptSuggestionService(repo, sug)

	first := make(chan error, 1)
	go func() {
		_, _, err := svc.Generate(context.Background(), opKey, []int64{7})
		first <- err
	}()
	// Wait until the first request is parked in its lookup.
	for deadline := time.Now().Add(2 * time.Second); ; {
		repo.mu.Lock()
		n := repo.lookups
		repo.mu.Unlock()
		if n == 1 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("first request never looked up its key")
		}
		time.Sleep(time.Millisecond)
	}
	if _, _, err := svc.Generate(context.Background(), opKey, []int64{7}); !errors.Is(err, domain.ErrSuggestionInProgress) {
		t.Fatalf("second same-key request while the first is unresolved: %v", err)
	}
	close(repo.gate)
	if err := <-first; err != nil {
		t.Fatal(err)
	}
	run, replay, err := svc.Generate(context.Background(), opKey, []int64{7})
	if err != nil || !replay || run.Status != domain.SuggestionRunCompleted {
		t.Fatalf("replay = %+v %v %v", run, replay, err)
	}
	if n := sug.calls.Load(); n != 1 {
		t.Fatalf("provider calls = %d, want 1", n)
	}
}

// A result the provider already returned is stored even when the client
// disconnects before the commit.
func TestGenerate_ResultIsStoredWhenClientDisconnectsAfterProvider(t *testing.T) {
	repo := newFakeSuggestionRepo()
	ctx, cancel := context.WithCancel(context.Background())
	sug := &fakeSuggester{before: func(context.Context) error { cancel(); return nil }}
	run, _, err := NewConceptSuggestionService(repo, sug).Generate(ctx, opKey, []int64{7})
	if err != nil || run == nil || run.Status != domain.SuggestionRunCompleted || repo.runs[opKey] == nil {
		t.Fatalf("run %+v err %v", run, err)
	}
}

// A provider call interrupted by the client stores nothing: the outcome is
// unknown, so the key stays open (never marked failed for the client's sake).
func TestGenerate_ClientCancellationDuringProviderStoresNothing(t *testing.T) {
	repo := newFakeSuggestionRepo()
	ctx, cancel := context.WithCancel(context.Background())
	sug := &fakeSuggester{before: func(c context.Context) error {
		cancel()
		<-c.Done()
		return domain.ErrProviderUnavailable
	}}
	svc := NewConceptSuggestionService(repo, sug)
	if _, _, err := svc.Generate(ctx, opKey, []int64{7}); !errors.Is(err, domain.ErrProviderUnavailable) {
		t.Fatalf("err %v", err)
	}
	if len(repo.runs) != 0 {
		t.Fatalf("stored %d runs for an interrupted call", len(repo.runs))
	}
	// The slot was released: the key is not stuck "in progress".
	sug.before = nil
	if _, _, err := svc.Generate(context.Background(), opKey, []int64{7}); err != nil {
		t.Fatalf("resend after interruption: %v", err)
	}
}

// A persistence failure after the provider answered is reported, stores
// nothing, and releases the key; a resend may call the provider again.
func TestGenerate_PersistenceFailureReleasesKey(t *testing.T) {
	repo := newFakeSuggestionRepo()
	repo.commitErr = errors.New("disk full")
	sug := &fakeSuggester{}
	svc := NewConceptSuggestionService(repo, sug)
	if _, _, err := svc.Generate(context.Background(), opKey, []int64{7}); err == nil {
		t.Fatal("want the persistence error")
	}
	repo.commitErr = nil
	if _, replay, err := svc.Generate(context.Background(), opKey, []int64{7}); err != nil || replay {
		t.Fatalf("resend: replay=%v err=%v", replay, err)
	}
	if n := sug.calls.Load(); n != 2 {
		t.Fatalf("provider calls = %d, want 2 (nothing was stored the first time)", n)
	}
}
