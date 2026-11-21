package application

import (
	"context"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

// VOC-054 / VOC-059 / VOC-118: a Concept or a source that can no longer be read
// degrades that part only; the list and the other examples stay.

type fakeVocabRepo struct {
	marks map[int64]domain.VocabularyMark
	exs   map[int64][]domain.VocabularyExample
}

func (r *fakeVocabRepo) Save(context.Context, domain.VocabularyExample, time.Time) (domain.VocabularyMark, bool, bool, error) {
	return domain.VocabularyMark{}, false, false, nil
}
func (r *fakeVocabRepo) Remove(context.Context, int64, time.Time) (domain.VocabularyMark, bool, error) {
	return domain.VocabularyMark{}, false, nil
}
func (r *fakeVocabRepo) Marks(context.Context) (map[int64]domain.VocabularyMark, error) {
	return r.marks, nil
}
func (r *fakeVocabRepo) Examples(_ context.Context, ids []int64) (map[int64][]domain.VocabularyExample, error) {
	out := map[int64][]domain.VocabularyExample{}
	for _, id := range ids {
		out[id] = r.exs[id]
	}
	return out, nil
}

type fakeVocabLibrary struct {
	concepts map[int64]*LibraryConceptDetail
	sources  map[int64]*LibrarySource
}

func (l *fakeVocabLibrary) GetConcept(_ context.Context, id int64) (*LibraryConceptDetail, error) {
	if c, ok := l.concepts[id]; ok {
		return c, nil
	}
	return nil, domain.ErrNotFound
}
func (l *fakeVocabLibrary) GetUnitSource(_ context.Context, id int64) (*LibrarySource, error) {
	if s, ok := l.sources[id]; ok {
		return s, nil
	}
	return nil, domain.ErrNotFound
}

func TestVocabularyList_DegradesOnlyWhatCannotBeRead(t *testing.T) {
	now := time.Date(2026, 11, 21, 8, 0, 0, 0, time.UTC)
	unit := func(id int64, word string) LibraryUnit {
		return LibraryUnit{Unit: domain.KnowledgeUnit{ID: id, Kind: domain.KindVocabulary, Canonical: word, ExtractionID: 50}, EntryID: 7, ExtractionVersion: 1, InCurrentExtraction: true}
	}
	repo := &fakeVocabRepo{
		marks: map[int64]domain.VocabularyMark{1: {ConceptID: 1, Saved: true, At: now}, 2: {ConceptID: 2, Saved: true, At: now}, 3: {ConceptID: 3, Saved: false, At: now}},
		exs: map[int64][]domain.VocabularyExample{
			1: {{ConceptID: 1, UnitID: 10, EntryID: 7, ExtractionID: 50, ExtractionVersion: 1}, {ConceptID: 1, UnitID: 11, EntryID: 8, ExtractionID: 51, ExtractionVersion: 1}},
			2: {{ConceptID: 2, UnitID: 20, EntryID: 9, ExtractionID: 52, ExtractionVersion: 1}},
		},
	}
	ext := int64(50)
	lib := &fakeVocabLibrary{
		concepts: map[int64]*LibraryConceptDetail{1: {Concept: domain.KnowledgeConcept{ID: 1, Target: "apporter", State: domain.ConceptActive}, SupportingUnits: []LibraryUnit{unit(10, "apporter")}}},
		sources:  map[int64]*LibrarySource{10: {Unit: unit(10, "apporter"), Entry: domain.Entry{ID: 7, OriginalInput: "q"}, CurrentSelection: domain.CurrentExtractionSelection{ExtractionID: &ext}}},
	}
	s := NewVocabularyService(repo, lib)
	list, err := s.List(context.Background(), "")
	if err != nil {
		t.Fatal(err)
	}
	if list.Saved != 2 || len(list.Items) != 2 {
		t.Fatalf("saved %d items %d (a removed term is not listed)", list.Saved, len(list.Items))
	}
	a, b := list.Items[0], list.Items[1]
	if a.Concept == nil || a.Examples[0].Status != VocabularyExampleCurrent || a.Examples[1].Status != VocabularyExampleMissing || a.Examples[1].Source != nil {
		t.Fatalf("one unreadable example: %+v", a.Examples)
	}
	// Concept 2 cannot be read: listed last, with its example's IDs kept.
	if b.Concept != nil || b.Mark.ConceptID != 2 || len(b.Examples) != 1 || b.Examples[0].Status != VocabularyExampleMissing || b.ReviewUnits != 0 {
		t.Fatalf("unreadable Concept: %+v", b)
	}
	// Search skips the unreadable parts without failing.
	if l, err := s.List(context.Background(), "apport"); err != nil || len(l.Items) != 1 || l.Items[0].Mark.ConceptID != 1 {
		t.Fatalf("search with unreadable parts: %v %+v", err, l)
	}
}

func TestSavableUnit_Rules(t *testing.T) {
	sup := func(kind domain.KnowledgeKind, id int64) LibraryUnit {
		return LibraryUnit{Unit: domain.KnowledgeUnit{ID: id, Kind: kind}}
	}
	cases := []struct {
		name   string
		d      LibraryConceptDetail
		unit   int64
		reason string
	}{
		{"retired", LibraryConceptDetail{Concept: domain.KnowledgeConcept{State: domain.ConceptRetired}, SupportingUnits: []LibraryUnit{sup(domain.KindVocabulary, 1)}}, 1, domain.VocabularyConceptRetired},
		{"no support", LibraryConceptDetail{Concept: domain.KnowledgeConcept{State: domain.ConceptOrphaned}}, 1, domain.VocabularyNotVocabulary},
		{"mixed kinds", LibraryConceptDetail{SupportingUnits: []LibraryUnit{sup(domain.KindVocabulary, 1), sup(domain.KindGrammar, 2)}}, 1, domain.VocabularyNotVocabulary},
		{"expression", LibraryConceptDetail{SupportingUnits: []LibraryUnit{sup(domain.KindExpression, 1)}}, 1, domain.VocabularyNotVocabulary},
		{"not supporting", LibraryConceptDetail{SupportingUnits: []LibraryUnit{sup(domain.KindVocabulary, 1)}}, 9, domain.VocabularyUnitNotSupporting},
		{"ok", LibraryConceptDetail{SupportingUnits: []LibraryUnit{sup(domain.KindVocabulary, 1)}}, 1, ""},
	}
	for _, c := range cases {
		_, err := savableUnit(&c.d, c.unit)
		got := ""
		if e, ok := err.(*domain.VocabularyNotSavableError); ok {
			got = e.Reason
		}
		if got != c.reason {
			t.Errorf("%s: %q, want %q (%v)", c.name, got, c.reason, err)
		}
	}
}
