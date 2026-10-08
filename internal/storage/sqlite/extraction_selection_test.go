package sqlite

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"reflect"
	"sort"
	"strings"
	"testing"

	"french-learning-app/internal/domain"
)

// Snapshot all persisted tables except the mutable pin. Compare full contents,
// not only row counts, so unnoticed label updates/deletes cannot pass.
func selectionEvidenceSnapshot(t *testing.T, db *sql.DB) map[string][]string {
	t.Helper()
	rows, err := db.Query(`SELECT name FROM sqlite_master WHERE type='table' AND name <> 'entry_current_extractions' ORDER BY name`)
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			t.Fatal(err)
		}
		names = append(names, name)
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	rows.Close()
	result := map[string][]string{}
	for _, name := range names {
		rows, err := db.Query(`SELECT * FROM "` + strings.ReplaceAll(name, `"`, `""`) + `"`)
		if err != nil {
			t.Fatal(err)
		}
		columns, err := rows.Columns()
		if err != nil {
			t.Fatal(err)
		}
		result[name] = []string{}
		for rows.Next() {
			values := make([]any, len(columns))
			dest := make([]any, len(columns))
			for i := range values {
				dest[i] = &values[i]
			}
			if err := rows.Scan(dest...); err != nil {
				t.Fatal(err)
			}
			encoded, err := json.Marshal(values)
			if err != nil {
				t.Fatal(err)
			}
			result[name] = append(result[name], string(encoded))
		}
		if err := rows.Err(); err != nil {
			t.Fatal(err)
		}
		rows.Close()
		sort.Strings(result[name])
	}
	return result
}

func assertSelection(t *testing.T, selection domain.CurrentExtractionSelection, mode domain.ExtractionSelectionMode, id *int64) {
	t.Helper()
	if selection.Mode != mode || !reflect.DeepEqual(selection.ExtractionID, id) {
		t.Fatalf("selection=%+v want mode=%s id=%v", selection, mode, id)
	}
}

func TestExtractionSelectionPinClearAutomaticAndPreserveEvidence(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
	makeExtraction := func(prefix string) *domain.ExtractionView {
		t.Helper()
		units := []domain.ExtractedUnit{grammarUnit(prefix + " same"), grammarUnit(prefix + " invalid"), grammarUnit(prefix + " distinct"), grammarUnit(prefix + " unresolved")}
		view, err := knowledge.Create(ctx, domain.NewExtractionInput{EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "fake:test", Units: units, Recommendations: domain.ApplyAdmissionV1(units)})
		if err != nil {
			t.Fatal(err)
		}
		return view
	}
	check := func(mode domain.ExtractionSelectionMode, id int64) {
		t.Helper()
		selection, err := concepts.GetCurrentExtractionSelection(ctx, entryID)
		if err != nil {
			t.Fatal(err)
		}
		assertSelection(t, selection, mode, &id)
		legacy, err := concepts.GetCurrentExtractionID(ctx, entryID)
		if err != nil || !reflect.DeepEqual(legacy, &id) {
			t.Fatalf("legacy selection=%v err=%v", legacy, err)
		}
	}
	first := makeExtraction("first")
	check(domain.ExtractionSelectionAutomatic, first.Extraction.ID)
	concept := mustConcept(t, concepts, domain.ConceptIdentity{Target: "selection concept", PedagogicalIntent: "grammar"})
	if _, err := concepts.LinkSame(ctx, first.Units[0].Unit.ID, concept.ID, domain.SourceHuman, nil, "{}"); err != nil {
		t.Fatal(err)
	}
	if _, err := concepts.MarkUnitInvalid(ctx, first.Units[1].Unit.ID, domain.SourceHuman, "synthetic", "{}"); err != nil {
		t.Fatal(err)
	}
	if _, err := concepts.RecordDistinction(ctx, first.Units[2].Unit.ID, concept.ID, domain.SourceHuman, "{}"); err != nil {
		t.Fatal(err)
	}
	second := makeExtraction("second")
	// Automatic selection moves support away from the historical SAME unit.
	check(domain.ExtractionSelectionAutomatic, second.Extraction.ID)
	assertState := func(supported bool, wantUnits []int64) {
		t.Helper()
		view, err := concepts.GetConcept(ctx, concept.ID)
		if err != nil {
			t.Fatal(err)
		}
		wantState := domain.ConceptOrphaned
		if supported {
			wantState = domain.ConceptActive
		}
		if view.Concept.State != wantState {
			t.Fatalf("state=%s want=%s", view.Concept.State, wantState)
		}
		support, err := concepts.ActiveSupportUnitIDs(ctx, concept.ID)
		if err != nil {
			t.Fatal(err)
		}
		if supported {
			if !reflect.DeepEqual(support, []int64{first.Units[0].Unit.ID}) {
				t.Fatalf("support=%v", support)
			}
		} else if len(support) != 0 {
			t.Fatalf("support=%v", support)
		}
		reviewable, err := concepts.ListReviewableUnits(ctx, &entryID)
		if err != nil {
			t.Fatal(err)
		}
		var got []int64
		for _, u := range reviewable {
			got = append(got, u.Unit.ID)
		}
		sort.Slice(got, func(i, j int) bool { return got[i] < got[j] })
		sort.Slice(wantUnits, func(i, j int) bool { return wantUnits[i] < wantUnits[j] })
		if !reflect.DeepEqual(got, wantUnits) {
			t.Fatalf("reviewable=%v want=%v", got, wantUnits)
		}
	}
	allIDs := func(view *domain.ExtractionView) []int64 {
		var ids []int64
		for _, u := range view.Units {
			ids = append(ids, u.Unit.ID)
		}
		return ids
	}
	assertState(false, allIDs(second))
	evidence := selectionEvidenceSnapshot(t, knowledge.db)
	if err := concepts.SetCurrentExtraction(ctx, entryID, first.Extraction.ID); err != nil {
		t.Fatal(err)
	}
	check(domain.ExtractionSelectionPinned, first.Extraction.ID)
	assertState(true, []int64{first.Units[2].Unit.ID, first.Units[3].Unit.ID})
	if !reflect.DeepEqual(evidence, selectionEvidenceSnapshot(t, knowledge.db)) {
		t.Fatal("pin rewrote evidence")
	}
	third := makeExtraction("third")
	check(domain.ExtractionSelectionPinned, first.Extraction.ID)
	// Verify persistence with a separately reopened database/repository.
	var seq int
	var name, path string
	if err := knowledge.db.QueryRow("PRAGMA database_list").Scan(&seq, &name, &path); err != nil {
		t.Fatal(err)
	}
	reopened, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	persisted, err := NewConceptRepository(reopened).GetCurrentExtractionSelection(ctx, entryID)
	if err != nil {
		t.Fatal(err)
	}
	assertSelection(t, persisted, domain.ExtractionSelectionPinned, &first.Extraction.ID)
	evidence = selectionEvidenceSnapshot(t, knowledge.db)
	selection, err := concepts.ClearCurrentExtraction(ctx, entryID)
	if err != nil {
		t.Fatal(err)
	}
	assertSelection(t, selection, domain.ExtractionSelectionAutomatic, &third.Extraction.ID)
	check(domain.ExtractionSelectionAutomatic, third.Extraction.ID)
	assertState(false, allIDs(third))
	currentUnits, err := concepts.ListCurrentExtractionUnits(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(currentUnits) != len(third.Units) {
		t.Fatalf("current units=%v", currentUnits)
	}
	for _, u := range currentUnits {
		if u.ExtractionID != third.Extraction.ID {
			t.Fatal("current projection contains historical unit")
		}
	}
	for i := 0; i < 2; i++ {
		selection, err = concepts.ClearCurrentExtraction(ctx, entryID)
		if err != nil {
			t.Fatal(err)
		}
		assertSelection(t, selection, domain.ExtractionSelectionAutomatic, &third.Extraction.ID)
	}
	if !reflect.DeepEqual(evidence, selectionEvidenceSnapshot(t, knowledge.db)) {
		t.Fatal("clear rewrote extraction/unit/label/history data")
	}
	fourth := makeExtraction("fourth")
	check(domain.ExtractionSelectionAutomatic, fourth.Extraction.ID)
	assertState(false, allIDs(fourth))
	// Pinning latest has identical ID but still explicitly reports pinned.
	if err := concepts.SetCurrentExtraction(ctx, entryID, fourth.Extraction.ID); err != nil {
		t.Fatal(err)
	}
	check(domain.ExtractionSelectionPinned, fourth.Extraction.ID)
	if _, err := concepts.ClearCurrentExtraction(ctx, entryID); err != nil {
		t.Fatal(err)
	}
	check(domain.ExtractionSelectionAutomatic, fourth.Extraction.ID)
	// Returning to the old pin restores support; invalid/distinct decisions remain.
	if err := concepts.SetCurrentExtraction(ctx, entryID, first.Extraction.ID); err != nil {
		t.Fatal(err)
	}
	assertState(true, []int64{first.Units[2].Unit.ID, first.Units[3].Unit.ID})
	if _, err := concepts.ClearCurrentExtraction(ctx, entryID); err != nil {
		t.Fatal(err)
	}
	assertState(false, allIDs(fourth))
}

func TestExtractionSelectionEmptyUnknownInvalidAndFailedClear(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	entry, err := entries.Create(ctx, domain.NewEntryInput{OriginalInput: "empty"})
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		selection, err := concepts.ClearCurrentExtraction(ctx, entry.ID)
		if err != nil {
			t.Fatal(err)
		}
		assertSelection(t, selection, domain.ExtractionSelectionAutomatic, nil)
	}
	selection, err := concepts.GetCurrentExtractionSelection(ctx, entry.ID)
	if err != nil {
		t.Fatal(err)
	}
	assertSelection(t, selection, domain.ExtractionSelectionAutomatic, nil)
	if _, err := concepts.GetCurrentExtractionSelection(ctx, 99999); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("unknown read=%v", err)
	}
	if _, err := concepts.ClearCurrentExtraction(ctx, 99999); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("unknown clear=%v", err)
	}
	first := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("first")})
	other := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("other")})
	if err := concepts.SetCurrentExtraction(ctx, first.Extraction.EntryID, first.Extraction.ID); err != nil {
		t.Fatal(err)
	}
	for _, bad := range []int64{0, -1, 99999, other.Extraction.ID} {
		if err := concepts.SetCurrentExtraction(ctx, first.Extraction.EntryID, bad); !errors.Is(err, domain.ErrValidation) {
			t.Fatalf("bad pin %d=%v", bad, err)
		}
		selection, err := concepts.GetCurrentExtractionSelection(ctx, first.Extraction.EntryID)
		if err != nil {
			t.Fatal(err)
		}
		assertSelection(t, selection, domain.ExtractionSelectionPinned, &first.Extraction.ID)
	}
	if err := concepts.SetCurrentExtraction(ctx, other.Extraction.EntryID, other.Extraction.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := knowledge.db.Exec(`CREATE TRIGGER fail_clear AFTER DELETE ON entry_current_extractions BEGIN SELECT RAISE(ABORT, 'synthetic clear failure'); END`); err != nil {
		t.Fatal(err)
	}
	if _, err := concepts.ClearCurrentExtraction(ctx, first.Extraction.EntryID); err == nil {
		t.Fatal("injected delete failure should fail")
	}
	selection, err = concepts.GetCurrentExtractionSelection(ctx, first.Extraction.EntryID)
	if err != nil {
		t.Fatal(err)
	}
	assertSelection(t, selection, domain.ExtractionSelectionPinned, &first.Extraction.ID)
	if _, err := knowledge.db.Exec("DROP TRIGGER fail_clear"); err != nil {
		t.Fatal(err)
	}
	if _, err := concepts.ClearCurrentExtraction(ctx, first.Extraction.EntryID); err != nil {
		t.Fatal(err)
	}
	selection, err = concepts.GetCurrentExtractionSelection(ctx, other.Extraction.EntryID)
	if err != nil {
		t.Fatal(err)
	}
	assertSelection(t, selection, domain.ExtractionSelectionPinned, &other.Extraction.ID)
	// A latest zero-unit success is still current after reset.
	zero, err := knowledge.Create(ctx, domain.NewExtractionInput{EntryID: first.Extraction.EntryID, SourceAnalysisID: first.Extraction.SourceAnalysisID, Extractor: "fake:zero"})
	if err != nil {
		t.Fatal(err)
	}
	if err := concepts.SetCurrentExtraction(ctx, first.Extraction.EntryID, first.Extraction.ID); err != nil {
		t.Fatal(err)
	}
	selection, err = concepts.ClearCurrentExtraction(ctx, first.Extraction.EntryID)
	if err != nil {
		t.Fatal(err)
	}
	assertSelection(t, selection, domain.ExtractionSelectionAutomatic, &zero.Extraction.ID)
}
