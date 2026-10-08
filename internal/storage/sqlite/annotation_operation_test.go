package sqlite

import (
	"context"
	"errors"
	"french-learning-app/internal/domain"
	"path/filepath"
	"sync"
	"testing"
)

func TestAnnotationOperationAtomicReplay(t *testing.T) {
	for _, action := range []string{"distinct", "broader", "narrower", "related"} {
		t.Run(action, func(t *testing.T) {
			entries, knowledge, _, repo := newConceptTestRepos(t)
			ctx := context.Background()
			view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("operation")})
			concept := mustConcept(t, repo, domain.ConceptIdentity{Target: "other", PedagogicalIntent: "grammar"})
			in := domain.AnnotationOperationInput{Action: "distinct", UnitID: view.Units[0].Unit.ID, ConceptID: concept.ID}
			if action != "distinct" {
				in.Action = "relation"
				in.Relation = domain.ConceptRelation(action)
			}
			key := "01234567-89ab-cdef-0123-456789abcdef"
			if _, err := repo.GetAnnotationOperation(ctx, key); !errors.Is(err, domain.ErrNotFound) {
				t.Fatalf("unknown: %v", err)
			}
			var wg sync.WaitGroup
			ids := make(chan int64, 12)
			for i := 0; i < 12; i++ {
				wg.Add(1)
				go func() {
					defer wg.Done()
					op, _, err := repo.CommitAnnotationOperation(ctx, key, in, "{}")
					if err != nil {
						t.Error(err)
						return
					}
					if op.Link != nil {
						ids <- op.Link.ID
					} else {
						ids <- op.Distinction.ID
					}
				}()
			}
			wg.Wait()
			close(ids)
			var first int64
			for id := range ids {
				if first == 0 {
					first = id
				}
				if id != first {
					t.Fatalf("duplicate: %d %d", first, id)
				}
			}
			if first == 0 {
				t.Fatal("no committed event")
			}
			table := "unit_concept_distinctions"
			if action != "distinct" {
				table = "unit_concept_links"
			}
			count := func(table string) int {
				var n int
				if err := repo.db.QueryRow("SELECT count(*) FROM " + table).Scan(&n); err != nil {
					t.Fatal(err)
				}
				return n
			}
			if count(table) != 1 || count("annotation_operations") != 1 {
				t.Fatal("duplicate writes")
			}
			// State changes cannot invalidate the historical receipt or cause another event.
			if _, err := repo.LinkSame(ctx, in.UnitID, concept.ID, domain.SourceHuman, nil, "{}"); err != nil {
				t.Fatal(err)
			}
			op, replay, err := repo.CommitAnnotationOperation(ctx, key, in, "changed service evidence")
			if err != nil || !replay {
				t.Fatalf("historical replay: %v %v", replay, err)
			}
			if op.Input != in {
				t.Fatal("receipt payload changed")
			}
			for _, changed := range []domain.AnnotationOperationInput{
				{Action: in.Action, UnitID: in.UnitID, ConceptID: concept.ID + 100, Relation: in.Relation},
				{Action: in.Action, UnitID: in.UnitID + 100, ConceptID: concept.ID, Relation: in.Relation},
				{Action: "relation", UnitID: in.UnitID, ConceptID: concept.ID, Relation: domain.RelationRelated},
			} {
				if changed == in {
					changed.Action = "distinct"
					changed.Relation = ""
				}
				if _, _, err := repo.CommitAnnotationOperation(ctx, key, changed, "{}"); !errors.Is(err, domain.ErrConceptConflict) {
					t.Fatalf("conflict: %v", err)
				}
			}
			if count("annotation_operations") != 1 {
				t.Fatal("conflict wrote receipt")
			}
			// Force receipt INSERT failure after annotation INSERT; both must roll back.
			if _, err := repo.db.Exec(`CREATE TRIGGER fail_receipt BEFORE INSERT ON annotation_operations BEGIN SELECT RAISE(ABORT, 'fixture failure'); END`); err != nil {
				t.Fatal(err)
			}
			before := count(table)
			failed := in
			failed.ConceptID = concept.ID
			if action == "distinct" {
				if _, err := repo.RejectSame(ctx, in.UnitID, domain.SourceHuman, "{}"); err != nil {
					t.Fatal(err)
				}
			}
			if _, _, err := repo.CommitAnnotationOperation(ctx, "11234567-89ab-cdef-0123-456789abcdef", failed, "{}"); err == nil {
				t.Fatal("expected failure")
			}
			if count(table) != before || count("annotation_operations") != 1 {
				t.Fatal("partial transaction committed")
			}
		})
	}
}

func TestAnnotationOperationRestartAndIndependentConnections(t *testing.T) {
	entries, knowledge, _, repo := newConceptTestRepos(t)
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("restart")})
	c := mustConcept(t, repo, domain.ConceptIdentity{Target: "restart-other", PedagogicalIntent: "grammar"})
	// VACUUM INTO a private fixture lets two independent pools exercise the lock.
	path := filepath.Join(t.TempDir(), "restart.db")
	if _, err := repo.db.Exec("VACUUM INTO ?", path); err != nil {
		t.Fatal(err)
	}
	a, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	b, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	in := domain.AnnotationOperationInput{Action: "relation", UnitID: view.Units[0].Unit.ID, ConceptID: c.ID, Relation: domain.RelationBroader}
	key := "01234567-89ab-cdef-0123-456789abcdef"
	var wg sync.WaitGroup
	for _, db := range []*ConceptRepository{NewConceptRepository(a), NewConceptRepository(b)} {
		wg.Add(1)
		go func(r *ConceptRepository) {
			defer wg.Done()
			if _, _, err := r.CommitAnnotationOperation(context.Background(), key, in, "{}"); err != nil {
				t.Error(err)
			}
		}(db)
	}
	wg.Wait()
	a.Close()
	b.Close()
	restarted, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.Close()
	r := NewConceptRepository(restarted)
	if _, err := r.GetAnnotationOperation(context.Background(), key); err != nil {
		t.Fatal(err)
	}
	var n int
	if err := restarted.QueryRow("SELECT count(*) FROM unit_concept_links").Scan(&n); err != nil || n != 1 {
		t.Fatalf("events=%d err=%v", n, err)
	}
	for _, bad := range []domain.AnnotationOperationInput{{Action: "distinct", UnitID: 0, ConceptID: c.ID}, {Action: "relation", UnitID: in.UnitID, ConceptID: c.ID, Relation: domain.RelationSame}} {
		if _, _, err := r.CommitAnnotationOperation(context.Background(), "11234567-89ab-cdef-0123-456789abcdef", bad, "{}"); !errors.Is(err, domain.ErrValidation) {
			t.Fatalf("invalid: %v", err)
		}
	}
}
