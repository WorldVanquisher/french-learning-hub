package sqlite

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"french-learning-app/internal/domain"
)

// FLH-090: the paged review queue returns exactly the legacy reviewable units, in
// the strict (entry, ordinal, unit) order, one bounded page at a time.

type queueFixture struct {
	entries   *EntryRepository
	knowledge *KnowledgeRepository
	concepts  *ConceptRepository
	// entry ID -> current-extraction unit IDs, in ordinal order
	units map[int64][]int64
	order []int64 // entry IDs in creation order
	// a historical (non-current) unit, for the locator test
	historical int64
	concept    int64
}

func extractFor(t *testing.T, f *queueFixture, entryID, analysisID int64, n int, tag string) *domain.ExtractionView {
	t.Helper()
	var units []domain.ExtractedUnit
	for i := 0; i < n; i++ {
		units = append(units, grammarUnit(fmt.Sprintf("%s-%d", tag, i)))
	}
	view, err := f.knowledge.Create(context.Background(), domain.NewExtractionInput{
		EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "openai:test:knowledge_extraction_v1",
		Units: units, Recommendations: domain.ApplyAdmissionV1(units),
	})
	if err != nil {
		t.Fatalf("create extraction: %v", err)
	}
	return view
}

func newQueueFixture(t *testing.T) *queueFixture {
	t.Helper()
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	f := &queueFixture{entries: entries, knowledge: knowledge, concepts: concepts, units: map[int64][]int64{}}
	ctx := context.Background()
	c := mustConcept(t, concepts, domain.ConceptIdentity{Target: "queue concept", PedagogicalIntent: "grammar"})
	f.concept = c.ID
	// Entry sizes 3, 1, 5, 2; entry 2 is re-extracted (v2 current); entry 4 is
	// re-extracted then pinned back to v1.
	for i, n := range []int{3, 1, 5, 2} {
		entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
		f.order = append(f.order, entryID)
		v1 := extractFor(t, f, entryID, analysisID, n, fmt.Sprintf("e%d-v1", i))
		ids := func(v *domain.ExtractionView) []int64 {
			var out []int64
			for _, u := range v.Units {
				out = append(out, u.Unit.ID)
			}
			return out
		}
		switch i {
		case 1:
			v2 := extractFor(t, f, entryID, analysisID, 2, "e1-v2")
			f.historical = v1.Units[0].Unit.ID
			f.units[entryID] = ids(v2)
		case 3:
			extractFor(t, f, entryID, analysisID, 4, "e3-v2")
			if err := concepts.SetCurrentExtraction(ctx, entryID, v1.Extraction.ID); err != nil {
				t.Fatalf("pin: %v", err)
			}
			f.units[entryID] = ids(v1)
		default:
			f.units[entryID] = ids(v1)
		}
	}
	return f
}

func (f *queueFixture) legacy(t *testing.T, entryID *int64) []int64 {
	t.Helper()
	all, err := f.concepts.ListReviewableUnits(context.Background(), entryID)
	if err != nil {
		t.Fatalf("legacy: %v", err)
	}
	var out []int64
	for _, ru := range all {
		out = append(out, ru.Unit.ID)
	}
	return out
}

// walk follows the cursor chain and returns every unit ID and the page count.
func (f *queueFixture) walk(t *testing.T, entryID *int64, limit int) ([]int64, int) {
	t.Helper()
	var out []int64
	var after *domain.ReviewQueueCursor
	pages := 0
	for {
		page, err := f.concepts.ListReviewableUnitsPage(context.Background(), domain.ReviewQueuePageQuery{EntryID: entryID, After: after, Limit: limit})
		if err != nil {
			t.Fatalf("page: %v", err)
		}
		pages++
		if len(page.Units) > limit {
			t.Fatalf("page of %d exceeds limit %d", len(page.Units), limit)
		}
		for _, ru := range page.Units {
			if ru.EntryID == 0 {
				t.Fatalf("unit %d has no entry id", ru.Unit.ID)
			}
			out = append(out, ru.Unit.ID)
		}
		if page.Next == nil {
			return out, pages
		}
		after = page.Next
		if pages > 100 {
			t.Fatal("cursor chain did not terminate")
		}
	}
}

func assertEach(t *testing.T, got, want []int64) {
	t.Helper()
	seen := map[int64]bool{}
	for _, id := range got {
		if seen[id] {
			t.Fatalf("unit %d returned twice: %v", id, got)
		}
		seen[id] = true
	}
	if !equalIDs(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestReviewQueuePage_TraversalEqualsLegacyForEveryPageSize(t *testing.T) {
	f := newQueueFixture(t)
	want := f.legacy(t, nil)
	if len(want) != 3+2+5+2 {
		t.Fatalf("fixture: %d reviewable units, want 12 (current extractions only)", len(want))
	}
	for _, limit := range []int{1, 2, 3, 5, 11, 12, 13, 200} {
		got, pages := f.walk(t, nil, limit)
		assertEach(t, got, want)
		// The repository reads one row past the limit, so a queue that ends exactly
		// on a page boundary returns no cursor: no trailing empty page is needed.
		wantPages := (len(want) + limit - 1) / limit
		if pages != wantPages {
			t.Errorf("limit %d: %d pages, want %d", limit, pages, wantPages)
		}
	}
}

func TestReviewQueuePage_EntryScopedEqualsLegacy(t *testing.T) {
	f := newQueueFixture(t)
	for _, entryID := range f.order {
		id := entryID
		got, _ := f.walk(t, &id, 2)
		assertEach(t, got, f.legacy(t, &id))
		assertEach(t, got, f.units[entryID])
	}
	missing := int64(999999)
	if _, err := f.concepts.ListReviewableUnitsPage(context.Background(), domain.ReviewQueuePageQuery{EntryID: &missing, Limit: 5}); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("unknown entry: %v, want ErrNotFound", err)
	}
}

func TestReviewQueuePage_UnitsDecidedBetweenRequests(t *testing.T) {
	f := newQueueFixture(t)
	ctx := context.Background()
	want := f.legacy(t, nil)
	page1, err := f.concepts.ListReviewableUnitsPage(ctx, domain.ReviewQueuePageQuery{Limit: 4})
	if err != nil {
		t.Fatal(err)
	}
	// Between requests: one later unit gets SAME, another is judged INVALID, and
	// a unit already shown on page 1 is resolved too.
	if _, err := f.concepts.LinkSame(ctx, want[5], f.concept, domain.SourceHuman, nil, ""); err != nil {
		t.Fatal(err)
	}
	if _, err := f.concepts.MarkUnitInvalid(ctx, want[7], domain.SourceHuman, "", ""); err != nil {
		t.Fatal(err)
	}
	if _, err := f.concepts.LinkSame(ctx, want[1], f.concept, domain.SourceHuman, nil, ""); err != nil {
		t.Fatal(err)
	}
	var rest []int64
	after := page1.Next
	for after != nil {
		p, err := f.concepts.ListReviewableUnitsPage(ctx, domain.ReviewQueuePageQuery{After: after, Limit: 4})
		if err != nil {
			t.Fatal(err)
		}
		for _, ru := range p.Units {
			rest = append(rest, ru.Unit.ID)
		}
		after = p.Next
	}
	var expectRest []int64
	for _, id := range want[4:] {
		if id != want[5] && id != want[7] {
			expectRest = append(expectRest, id)
		}
	}
	assertEach(t, rest, expectRest)
}

func TestReviewQueuePage_FromUnitLocator(t *testing.T) {
	f := newQueueFixture(t)
	ctx := context.Background()
	want := f.legacy(t, nil)
	from := func(unitID int64, entryID *int64) ([]int64, error) {
		p, err := f.concepts.ListReviewableUnitsPage(ctx, domain.ReviewQueuePageQuery{FromUnitID: &unitID, EntryID: entryID, Limit: 3})
		if err != nil {
			return nil, err
		}
		var out []int64
		for _, ru := range p.Units {
			out = append(out, ru.Unit.ID)
		}
		return out, nil
	}
	// A reviewable unit: the page starts with it (inclusive).
	got, err := from(want[6], nil)
	if err != nil || !equalIDs(got, want[6:9]) {
		t.Fatalf("from reviewable unit: %v %v, want %v", got, err, want[6:9])
	}
	// A unit that left the queue: the page starts at the next unit in order.
	if _, err := f.concepts.LinkSame(ctx, want[6], f.concept, domain.SourceHuman, nil, ""); err != nil {
		t.Fatal(err)
	}
	got, err = from(want[6], nil)
	if err != nil || !equalIDs(got, want[7:10]) {
		t.Fatalf("from decided unit: %v %v, want %v", got, err, want[7:10])
	}
	// A historical unit (no longer in its entry's current extraction) still has a
	// position: its entry's units with a higher (ordinal, id) key, then later entries.
	got, err = from(f.historical, nil)
	if err != nil || len(got) == 0 || got[0] != f.units[f.order[1]][0] {
		t.Fatalf("from historical unit: %v %v", got, err)
	}
	// Unknown unit, a unit outside the scoped entry, and after+from are refused.
	if _, err := from(999999, nil); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("unknown unit: %v", err)
	}
	other := f.order[0]
	if _, err := from(f.units[f.order[2]][0], &other); !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("unit outside scoped entry: %v", err)
	}
	unit := want[0]
	if _, err := f.concepts.ListReviewableUnitsPage(ctx, domain.ReviewQueuePageQuery{FromUnitID: &unit, After: &domain.ReviewQueueCursor{EntryID: 1, Ordinal: 0, UnitID: 1}, Limit: 3}); !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("after+from: %v", err)
	}
}
