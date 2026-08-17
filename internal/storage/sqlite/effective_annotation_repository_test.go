package sqlite

import (
	"context"
	"errors"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

func TestConceptRepository_ListUnitConceptLinksReturnsCompleteStableHistory(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID
	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	b := mustConcept(t, concepts, domain.ConceptIdentity{Target: "b", PedagogicalIntent: "grammar"})

	fixed := time.Date(2026, time.January, 1, 0, 0, 0, 0, time.UTC)
	concepts.now = func() time.Time { return fixed }
	first, err := concepts.LinkRelation(ctx, unitID, a.ID, domain.RelationRelated, domain.SourceHuman, `{"version":1}`)
	if err != nil {
		t.Fatalf("first relation: %v", err)
	}
	second, err := concepts.LinkRelation(ctx, unitID, a.ID, domain.RelationRelated, domain.SourceHuman, `{"version":2}`)
	if err != nil {
		t.Fatalf("second relation: %v", err)
	}
	same, err := concepts.LinkSame(ctx, unitID, b.ID, domain.SourceResolverAutomatic, nil, `{"reason":"exact"}`)
	if err != nil {
		t.Fatalf("same: %v", err)
	}
	rejected, err := concepts.RejectSame(ctx, unitID, domain.SourceHuman, `{"reason":"reject"}`)
	if err != nil {
		t.Fatalf("reject same: %v", err)
	}

	links, err := concepts.ListUnitConceptLinks(ctx, unitID)
	if err != nil {
		t.Fatalf("ListUnitConceptLinks: %v", err)
	}
	wantIDs := []int64{rejected.ID, same.ID, second.ID, first.ID}
	if len(links) != len(wantIDs) {
		t.Fatalf("got %d links, want %d: %+v", len(links), len(wantIDs), links)
	}
	for i, wantID := range wantIDs {
		if links[i].ID != wantID {
			t.Fatalf("links[%d].ID = %d, want %d", i, links[i].ID, wantID)
		}
	}
	if second.SupersedesLinkID == nil || *second.SupersedesLinkID != first.ID {
		t.Fatalf("relation supersession provenance missing: %+v", second)
	}
	if links[0].Status != domain.LinkRejected || links[0].DecisionSource != domain.SourceHuman {
		t.Fatalf("rejected SAME provenance not preserved: %+v", links[0])
	}
	if links[1].Status != domain.LinkAccepted || links[1].DecisionSource != domain.SourceResolverAutomatic {
		t.Fatalf("accepted SAME provenance not preserved: %+v", links[1])
	}
}

func TestConceptRepository_ListUnitConceptLinksRequiresExistingUnit(t *testing.T) {
	_, _, _, concepts := newConceptTestRepos(t)
	_, err := concepts.ListUnitConceptLinks(context.Background(), 999999)
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestConceptRepository_ListCurrentExtractionUnitsExcludesHistoricalUnits(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	first := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{
		grammarUnit("historical"),
	})
	entryID := entryIDForExtraction(t, knowledge, first.Extraction.ID)

	second, err := knowledge.Create(ctx, domain.NewExtractionInput{
		EntryID:          entryID,
		SourceAnalysisID: first.Extraction.SourceAnalysisID,
		Extractor:        "openai:test:knowledge_extraction_v1",
		Units:            []domain.ExtractedUnit{grammarUnit("current")},
		Recommendations:  domain.ApplyAdmissionV1([]domain.ExtractedUnit{grammarUnit("current")}),
	})
	if err != nil {
		t.Fatalf("create second extraction: %v", err)
	}

	units, err := concepts.ListCurrentExtractionUnits(ctx)
	if err != nil {
		t.Fatalf("list current units: %v", err)
	}
	if len(units) != 1 || units[0].ID != second.Units[0].Unit.ID {
		t.Fatalf("default current units = %+v, want only second extraction unit", units)
	}

	if err := concepts.SetCurrentExtraction(ctx, entryID, first.Extraction.ID); err != nil {
		t.Fatalf("select first extraction: %v", err)
	}
	units, err = concepts.ListCurrentExtractionUnits(ctx)
	if err != nil {
		t.Fatalf("list selected current units: %v", err)
	}
	if len(units) != 1 || units[0].ID != first.Units[0].Unit.ID {
		t.Fatalf("selected current units = %+v, want only first extraction unit", units)
	}
}
