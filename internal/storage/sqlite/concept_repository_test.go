package sqlite

import (
	"context"
	"errors"
	"path/filepath"
	"testing"

	"french-learning-app/internal/domain"
)

// newConceptTestRepos opens a fresh migrated database and returns the repos
// needed to exercise concept resolution end to end at the storage layer.
func newConceptTestRepos(t *testing.T) (*EntryRepository, *KnowledgeRepository, *AdmissionRepository, *ConceptRepository) {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "concept.db")
	db, err := Open(dbPath)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return NewEntryRepository(db), NewKnowledgeRepository(db), NewAdmissionRepository(db), NewConceptRepository(db)
}

// seedExtractionWithUnits creates an entry + analysis, then an extraction with the
// given units (default admission recommendations), returning the extraction view.
func seedExtractionWithUnits(t *testing.T, entries *EntryRepository, knowledge *KnowledgeRepository, units []domain.ExtractedUnit) *domain.ExtractionView {
	t.Helper()
	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
	view, err := knowledge.Create(context.Background(), domain.NewExtractionInput{
		EntryID:          entryID,
		SourceAnalysisID: analysisID,
		Extractor:        "openai:test:knowledge_extraction_v1",
		Units:            units,
		Recommendations:  domain.ApplyAdmissionV1(units),
	})
	if err != nil {
		t.Fatalf("create extraction: %v", err)
	}
	return view
}

func grammarUnit(canonical string) domain.ExtractedUnit {
	return domain.ExtractedUnit{Kind: domain.KindGrammar, Canonical: canonical, Statement: "s: " + canonical, Confidence: 0.9}
}

// mustConcept creates a concept and fails the test on error. It hides the seed
// link (unused by most callers) behind the three-value signature.
func mustConcept(t *testing.T, concepts *ConceptRepository, identity domain.ConceptIdentity) *domain.KnowledgeConcept {
	t.Helper()
	c, _, err := concepts.CreateConcept(context.Background(), domain.NewConceptInput{Identity: identity})
	if err != nil {
		t.Fatalf("create concept %q: %v", identity.Target, err)
	}
	return c
}

// entryIDForExtraction reads back the entry id that owns an extraction.
func entryIDForExtraction(t *testing.T, knowledge *KnowledgeRepository, extractionID int64) int64 {
	t.Helper()
	view, err := knowledge.GetByID(context.Background(), extractionID)
	if err != nil {
		t.Fatalf("get extraction: %v", err)
	}
	return view.Extraction.EntryID
}

func TestConceptRepository_CreateAndFindBySignature(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("vouloir + inf")})
	seedUnit := view.Units[0].Unit.ID

	identity := domain.DeriveCandidateIdentity(view.Units[0].Unit)
	c, _, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: identity, SeedUnitID: &seedUnit})
	if err != nil {
		t.Fatalf("create concept: %v", err)
	}
	// A newly created concept with no supporting unit is orphaned (derived), not
	// active: support is computed, not assumed.
	if c.State != domain.ConceptOrphaned {
		t.Fatalf("new unsupported concept should be orphaned, got %q", c.State)
	}
	if c.Lifecycle != domain.LifecycleNormal {
		t.Fatalf("new concept lifecycle should be normal, got %q", c.Lifecycle)
	}

	// A second concept with the same durable identity is refused.
	if _, _, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: identity}); !errors.Is(err, domain.ErrConceptConflict) {
		t.Fatalf("expected ErrConceptConflict for duplicate identity, got %v", err)
	}

	found, err := concepts.FindActiveBySignature(ctx, identity.Signature())
	if err != nil {
		t.Fatalf("find by signature: %v", err)
	}
	if len(found) != 1 || found[0].ID != c.ID {
		t.Fatalf("expected exactly the created concept, got %+v", found)
	}
}

// Required case 1 (storage level): two different unit wordings with identical
// complete identity signatures resolve SAME to the same concept.
func TestConceptRepository_SameSignatureDifferentWordingLinks(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()

	v1 := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "vouloir + infinitif", Statement: "one wording", Confidence: 0.9},
	})
	v2 := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "on utilise vouloir puis un infinitif", Statement: "another wording", Confidence: 0.9},
	})
	unitA := v1.Units[0].Unit.ID
	unitB := v2.Units[0].Unit.ID

	c := mustConcept(t, concepts, domain.ConceptIdentity{Target: "vouloir + infinitive", PedagogicalIntent: "grammar"})

	if _, err := concepts.LinkSame(ctx, unitA, c.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("link A: %v", err)
	}
	if _, err := concepts.LinkSame(ctx, unitB, c.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("link B (different wording, same concept): %v", err)
	}

	view, err := concepts.GetConcept(ctx, c.ID)
	if err != nil {
		t.Fatalf("get concept: %v", err)
	}
	sameCount := 0
	for _, l := range view.Links {
		if l.Relation == domain.RelationSame && l.Status == domain.LinkAccepted {
			sameCount++
		}
	}
	if sameCount != 2 {
		t.Fatalf("expected 2 accepted SAME events, got %d", sameCount)
	}
}

// Required case 3: one unit cannot hold two CURRENT SAME memberships via LinkSame.
func TestConceptRepository_OneAcceptedSamePerUnit(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	c1 := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	c2 := mustConcept(t, concepts, domain.ConceptIdentity{Target: "b", PedagogicalIntent: "grammar"})

	if _, err := concepts.LinkSame(ctx, unitID, c1.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("first same: %v", err)
	}
	// LinkSame to a different concept must conflict (use ReassignSame to correct).
	if _, err := concepts.LinkSame(ctx, unitID, c2.ID, domain.SourceHuman, nil, ""); !errors.Is(err, domain.ErrConceptConflict) {
		t.Fatalf("expected ErrConceptConflict on second SAME, got %v", err)
	}
	// Re-affirming the same concept is idempotent (no error).
	if _, err := concepts.LinkSame(ctx, unitID, c1.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("idempotent re-affirmation should succeed, got %v", err)
	}
}

// Required case A: a human can move a wrong SAME membership to a different concept,
// the new one becomes current, the old is history only, and both remain queryable.
func TestConceptRepository_ReassignSameCorrectsMembership(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	b := mustConcept(t, concepts, domain.ConceptIdentity{Target: "b", PedagogicalIntent: "grammar"})

	first, err := concepts.LinkSame(ctx, unitID, a.ID, domain.SourceHuman, nil, "")
	if err != nil {
		t.Fatalf("link A: %v", err)
	}

	// Human correction: move the unit to B even though it already belongs to A.
	moved, err := concepts.ReassignSame(ctx, unitID, b.ID, domain.SourceHuman, "")
	if err != nil {
		t.Fatalf("reassign to B: %v", err)
	}
	if moved.SupersedesLinkID == nil || *moved.SupersedesLinkID != first.ID {
		t.Fatalf("new event must supersede the old link %d, got %v", first.ID, moved.SupersedesLinkID)
	}

	// Exactly one CURRENT SAME membership, now to B.
	supB, _ := concepts.ActiveSupportUnitIDs(ctx, b.ID)
	if len(supB) != 1 || supB[0] != unitID {
		t.Fatalf("unit should now support B, got %v", supB)
	}
	supA, _ := concepts.ActiveSupportUnitIDs(ctx, a.ID)
	if len(supA) != 0 {
		t.Fatalf("A must no longer be supported by the moved unit, got %v", supA)
	}

	// Case D: the OLD accepted event for A is unchanged (append-only). Its row still
	// says accepted, relation same, concept A — history was not rewritten.
	aView, err := concepts.GetConcept(ctx, a.ID)
	if err != nil {
		t.Fatalf("get A: %v", err)
	}
	var found *domain.UnitConceptLink
	for i := range aView.Links {
		if aView.Links[i].ID == first.ID {
			found = &aView.Links[i]
		}
	}
	if found == nil {
		t.Fatalf("original decision to A must remain queryable")
	}
	if found.Status != domain.LinkAccepted || found.ConceptID != a.ID || found.Relation != domain.RelationSame {
		t.Fatalf("historical event content must be intact, got %+v", *found)
	}
	if found.SupersedesLinkID != nil {
		t.Fatalf("the original event must not have gained a supersedes pointer")
	}
}

// Required case B: an automatic SAME link can be corrected by a human. Human wins.
func TestConceptRepository_HumanCorrectsAutomaticSame(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	b := mustConcept(t, concepts, domain.ConceptIdentity{Target: "b", PedagogicalIntent: "grammar"})

	score := 1.0
	if _, err := concepts.LinkSame(ctx, unitID, a.ID, domain.SourceResolverAutomatic, &score, ""); err != nil {
		t.Fatalf("automatic same: %v", err)
	}
	moved, err := concepts.ReassignSame(ctx, unitID, b.ID, domain.SourceHuman, "")
	if err != nil {
		t.Fatalf("human correction: %v", err)
	}
	if moved.DecisionSource != domain.SourceHuman {
		t.Fatalf("current decision should be human, got %q", moved.DecisionSource)
	}
	sup, _ := concepts.ActiveSupportUnitIDs(ctx, b.ID)
	if len(sup) != 1 || sup[0] != unitID {
		t.Fatalf("human decision must win: unit should support B, got %v", sup)
	}
}

// Required case C: if a unit was the preferred representation of concept A and its
// SAME membership is moved to B, A must not retain an invalid preferred_unit_id.
func TestConceptRepository_ReassignClearsStalePreferred(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	b := mustConcept(t, concepts, domain.ConceptIdentity{Target: "b", PedagogicalIntent: "grammar"})

	if _, err := concepts.LinkSame(ctx, unitID, a.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("link A: %v", err)
	}
	if _, err := concepts.SetPreferredUnit(ctx, a.ID, unitID); err != nil {
		t.Fatalf("set preferred on A: %v", err)
	}

	if _, err := concepts.ReassignSame(ctx, unitID, b.ID, domain.SourceHuman, ""); err != nil {
		t.Fatalf("reassign to B: %v", err)
	}

	aView, err := concepts.GetConcept(ctx, a.ID)
	if err != nil {
		t.Fatalf("get A: %v", err)
	}
	if aView.Concept.PreferredUnitID != nil {
		t.Fatalf("A must not keep an invalid preferred_unit_id after the member moved, got %v", *aView.Concept.PreferredUnitID)
	}
}

// Required cases 4 & 5: SAME membership does not auto-set preferred unit; and the
// preferred unit must currently hold the SAME membership to that concept.
func TestConceptRepository_PreferredUnitRules(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x"), grammarUnit("y")})
	memberUnit := view.Units[0].Unit.ID
	nonMemberUnit := view.Units[1].Unit.ID

	c := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	if _, err := concepts.LinkSame(ctx, memberUnit, c.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("link same: %v", err)
	}

	// Accepting SAME must not have set a preferred unit.
	got, err := concepts.GetConcept(ctx, c.ID)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.Concept.PreferredUnitID != nil {
		t.Fatalf("SAME membership must not auto-set preferred_unit_id, got %v", *got.Concept.PreferredUnitID)
	}

	// A non-member unit cannot become preferred.
	if _, err := concepts.SetPreferredUnit(ctx, c.ID, nonMemberUnit); !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation for non-member preferred unit, got %v", err)
	}
	// A member unit can.
	updated, err := concepts.SetPreferredUnit(ctx, c.ID, memberUnit)
	if err != nil {
		t.Fatalf("set preferred: %v", err)
	}
	if updated.PreferredUnitID == nil || *updated.PreferredUnitID != memberUnit {
		t.Fatalf("preferred unit not set to member, got %v", updated.PreferredUnitID)
	}
	// Concept id is stable across the preferred-representation change.
	if updated.ID != c.ID {
		t.Fatalf("concept id must be stable, got %d want %d", updated.ID, c.ID)
	}
}

// Required cases 6, 8, 10 & E: a newer successful extraction becomes current, units
// from the old extraction stop providing current support IMMEDIATELY (no manual
// recompute), and historical extractions/links remain queryable.
func TestConceptRepository_NewerExtractionBecomesCurrent(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()

	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
	mk := func(canonical string) *domain.ExtractionView {
		units := []domain.ExtractedUnit{grammarUnit(canonical)}
		v, err := knowledge.Create(ctx, domain.NewExtractionInput{
			EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "x",
			Units: units, Recommendations: domain.ApplyAdmissionV1(units),
		})
		if err != nil {
			t.Fatalf("create extraction: %v", err)
		}
		return v
	}
	first := mk("v1 unit")
	oldUnit := first.Units[0].Unit.ID

	c := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	if _, err := concepts.LinkSame(ctx, oldUnit, c.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("link old unit: %v", err)
	}
	supported, err := concepts.ActiveSupportUnitIDs(ctx, c.ID)
	if err != nil {
		t.Fatalf("support: %v", err)
	}
	if len(supported) != 1 || supported[0] != oldUnit {
		t.Fatalf("old unit should support concept while v1 current, got %v", supported)
	}
	// And the derived concept state reads active.
	if cv, _ := concepts.GetConcept(ctx, c.ID); cv.Concept.State != domain.ConceptActive {
		t.Fatalf("concept should read active while supported, got %q", cv.Concept.State)
	}

	// A newer successful extraction becomes current by default.
	second := mk("v2 unit")
	current, err := concepts.GetCurrentExtractionID(ctx, entryID)
	if err != nil {
		t.Fatalf("current: %v", err)
	}
	if current == nil || *current != second.Extraction.ID {
		t.Fatalf("newer extraction should be current, got %v want %d", current, second.Extraction.ID)
	}

	// Case E: without any SetCurrentExtraction call, the old unit no longer supports
	// and the concept reads orphaned immediately.
	supported, err = concepts.ActiveSupportUnitIDs(ctx, c.ID)
	if err != nil {
		t.Fatalf("support after v2: %v", err)
	}
	if len(supported) != 0 {
		t.Fatalf("old-extraction unit must not support the current pool, got %v", supported)
	}
	if cv, _ := concepts.GetConcept(ctx, c.ID); cv.Concept.State != domain.ConceptOrphaned {
		t.Fatalf("concept should read orphaned after support dropped, got %q", cv.Concept.State)
	}

	// Case 10: the old unit and link remain queryable.
	oldView, err := knowledge.GetByID(ctx, first.Extraction.ID)
	if err != nil {
		t.Fatalf("historical extraction must remain queryable: %v", err)
	}
	if len(oldView.Units) != 1 || oldView.Units[0].Unit.ID != oldUnit {
		t.Fatalf("historical unit missing")
	}
	cView, err := concepts.GetConcept(ctx, c.ID)
	if err != nil {
		t.Fatalf("get concept: %v", err)
	}
	if len(cView.Links) == 0 {
		t.Fatalf("historical link must remain queryable")
	}
}

// Required case 11: a concept that loses all current support reads orphaned (not
// deleted) with NO manual recompute call.
func TestConceptRepository_UnsupportedConceptBecomesOrphaned(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()

	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
	units := []domain.ExtractedUnit{grammarUnit("v1")}
	first, err := knowledge.Create(ctx, domain.NewExtractionInput{
		EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "x",
		Units: units, Recommendations: domain.ApplyAdmissionV1(units),
	})
	if err != nil {
		t.Fatalf("first extraction: %v", err)
	}
	oldUnit := first.Units[0].Unit.ID

	c := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	if _, err := concepts.LinkSame(ctx, oldUnit, c.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("link: %v", err)
	}

	// New extraction supersedes v1 as current, removing the only support.
	units2 := []domain.ExtractedUnit{grammarUnit("v2")}
	if _, err := knowledge.Create(ctx, domain.NewExtractionInput{
		EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "x",
		Units: units2, Recommendations: domain.ApplyAdmissionV1(units2),
	}); err != nil {
		t.Fatalf("second extraction: %v", err)
	}

	// No manual recompute call: the derived state must already read orphaned.
	got, err := concepts.GetConcept(ctx, c.ID)
	if err != nil {
		t.Fatalf("concept must still exist (not deleted): %v", err)
	}
	if got.Concept.State != domain.ConceptOrphaned {
		t.Fatalf("unsupported concept should be orphaned, got %q", got.Concept.State)
	}
}

// Required case G: a failed extraction persists nothing, so it cannot replace the
// last successful current extraction.
func TestConceptRepository_FailedExtractionDoesNotReplaceCurrent(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()

	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
	units := []domain.ExtractedUnit{grammarUnit("good")}
	ok, err := knowledge.Create(ctx, domain.NewExtractionInput{
		EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "x",
		Units: units, Recommendations: domain.ApplyAdmissionV1(units),
	})
	if err != nil {
		t.Fatalf("successful extraction: %v", err)
	}

	// A "failed" run: mismatched recommendations makes Create fail atomically,
	// writing nothing.
	if _, err := knowledge.Create(ctx, domain.NewExtractionInput{
		EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "x",
		Units: units, Recommendations: nil,
	}); err == nil {
		t.Fatal("expected failed create")
	}

	current, err := concepts.GetCurrentExtractionID(ctx, entryID)
	if err != nil {
		t.Fatalf("current: %v", err)
	}
	if current == nil || *current != ok.Extraction.ID {
		t.Fatalf("failed extraction must not replace current; got %v want %d", current, ok.Extraction.ID)
	}
}

// Required case F: a successful zero-unit extraction becomes current immediately
// and removes support from old-extraction units.
func TestConceptRepository_ZeroUnitExtractionIsCurrentWithNoUnits(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()

	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
	// First a unit-bearing extraction supporting a concept.
	firstUnits := []domain.ExtractedUnit{grammarUnit("v1")}
	first, err := knowledge.Create(ctx, domain.NewExtractionInput{
		EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "x",
		Units: firstUnits, Recommendations: domain.ApplyAdmissionV1(firstUnits),
	})
	if err != nil {
		t.Fatalf("first extraction: %v", err)
	}
	oldUnit := first.Units[0].Unit.ID
	c := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	if _, err := concepts.LinkSame(ctx, oldUnit, c.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("link: %v", err)
	}

	// A successful zero-unit extraction becomes current.
	zero, err := knowledge.Create(ctx, domain.NewExtractionInput{
		EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "x",
	})
	if err != nil {
		t.Fatalf("zero-unit extraction: %v", err)
	}
	current, err := concepts.GetCurrentExtractionID(ctx, entryID)
	if err != nil {
		t.Fatalf("current: %v", err)
	}
	if current == nil || *current != zero.Extraction.ID {
		t.Fatalf("zero-unit extraction should be current, got %v", current)
	}
	reviewable, err := concepts.ListReviewableUnits(ctx, &entryID)
	if err != nil {
		t.Fatalf("reviewable: %v", err)
	}
	if len(reviewable) != 0 {
		t.Fatalf("zero-unit extraction contributes no units, got %d", len(reviewable))
	}
	// Old-extraction support is gone under the zero-unit current extraction.
	if ids, _ := concepts.ActiveSupportUnitIDs(ctx, c.ID); len(ids) != 0 {
		t.Fatalf("zero-unit current extraction must remove old support, got %v", ids)
	}
}

// Required case K: explicit rollback to an older successful extraction still works
// and immediately restores that extraction's support.
func TestConceptRepository_ExplicitRollbackRestoresOldSupport(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()

	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
	mk := func(c string) *domain.ExtractionView {
		u := []domain.ExtractedUnit{grammarUnit(c)}
		v, err := knowledge.Create(ctx, domain.NewExtractionInput{
			EntryID: entryID, SourceAnalysisID: analysisID, Extractor: "x",
			Units: u, Recommendations: domain.ApplyAdmissionV1(u),
		})
		if err != nil {
			t.Fatalf("create: %v", err)
		}
		return v
	}
	first := mk("v1")
	oldUnit := first.Units[0].Unit.ID
	c := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	if _, err := concepts.LinkSame(ctx, oldUnit, c.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("link: %v", err)
	}
	_ = mk("v2") // v2 becomes current, old support drops

	if ids, _ := concepts.ActiveSupportUnitIDs(ctx, c.ID); len(ids) != 0 {
		t.Fatalf("expected no support under v2, got %v", ids)
	}

	// Roll back to the first extraction: the old unit supports again immediately.
	if err := concepts.SetCurrentExtraction(ctx, entryID, first.Extraction.ID); err != nil {
		t.Fatalf("rollback: %v", err)
	}
	ids, err := concepts.ActiveSupportUnitIDs(ctx, c.ID)
	if err != nil {
		t.Fatalf("support after rollback: %v", err)
	}
	if len(ids) != 1 || ids[0] != oldUnit {
		t.Fatalf("expected old unit to support after rollback, got %v", ids)
	}

	// Rollback target must belong to the entry.
	otherView := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("z")})
	if err := concepts.SetCurrentExtraction(ctx, entryID, otherView.Extraction.ID); !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("expected ErrValidation for foreign extraction, got %v", err)
	}
	_ = entryIDForExtraction
}

// Required case H: admission override flips derived support immediately, with no
// manual concept recompute call.
func TestConceptRepository_SuppressedUnitDoesNotSupport(t *testing.T) {
	entries, knowledge, admission, concepts := newConceptTestRepos(t)
	ctx := context.Background()

	// Two identical-canonical units in one extraction: the second is suppressed as
	// an exact duplicate by knowledge_admission_v1.
	units := []domain.ExtractedUnit{grammarUnit("dup"), grammarUnit("dup")}
	view := seedExtractionWithUnits(t, entries, knowledge, units)
	if view.Units[1].Admission.Effective != domain.AdmissionSuppressed {
		t.Fatalf("second unit should be suppressed, got %q", view.Units[1].Admission.Effective)
	}
	suppressed := view.Units[1].Unit.ID

	c := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	if _, err := concepts.LinkSame(ctx, suppressed, c.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("link suppressed: %v", err)
	}
	if ids, _ := concepts.ActiveSupportUnitIDs(ctx, c.ID); len(ids) != 0 {
		t.Fatalf("suppressed unit must not support the pool, got %v", ids)
	}
	if cv, _ := concepts.GetConcept(ctx, c.ID); cv.Concept.State != domain.ConceptOrphaned {
		t.Fatalf("concept with only a suppressed member should read orphaned, got %q", cv.Concept.State)
	}

	// A human override re-activating the unit restores support immediately.
	if _, err := admission.Create(ctx, suppressed, domain.NewAdmissionOverrideInput{Decision: domain.HumanAdmitActive}); err != nil {
		t.Fatalf("override active: %v", err)
	}
	if ids, _ := concepts.ActiveSupportUnitIDs(ctx, c.ID); len(ids) != 1 || ids[0] != suppressed {
		t.Fatalf("re-activated unit should support, got %v", ids)
	}
	if cv, _ := concepts.GetConcept(ctx, c.ID); cv.Concept.State != domain.ConceptActive {
		t.Fatalf("concept should read active after reactivation, got %q", cv.Concept.State)
	}

	// Suppressing again immediately drops support back to orphaned.
	if _, err := admission.Create(ctx, suppressed, domain.NewAdmissionOverrideInput{Decision: domain.HumanAdmitSuppressed, Reason: domain.HumanReasonIgnored}); err != nil {
		t.Fatalf("override suppress: %v", err)
	}
	if ids, _ := concepts.ActiveSupportUnitIDs(ctx, c.ID); len(ids) != 0 {
		t.Fatalf("re-suppressed unit must not support, got %v", ids)
	}
}

// Required case I: identity is not released by orphaning. Create a concept, make it
// orphaned (unsupported), then attempt to create another with the same signature —
// it must conflict rather than create a duplicate durable identity.
func TestConceptRepository_OrphanedIdentityNotReleased(t *testing.T) {
	_, _, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()

	// A concept with no supporting unit is immediately orphaned (derived).
	identity := domain.ConceptIdentity{Target: "vouloir", PedagogicalIntent: "grammar"}
	c := mustConcept(t, concepts, identity)
	got, err := concepts.GetConcept(ctx, c.ID)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.Concept.State != domain.ConceptOrphaned {
		t.Fatalf("expected orphaned, got %q", got.Concept.State)
	}

	// A second concept with the same durable identity must be refused even though the
	// first is currently unsupported.
	if _, _, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: identity}); !errors.Is(err, domain.ErrConceptConflict) {
		t.Fatalf("orphaning must not release identity; expected ErrConceptConflict, got %v", err)
	}

	// And the resolver still finds the orphaned concept for that signature, so a new
	// unit resolves SAME to it rather than spawning a duplicate.
	found, err := concepts.FindActiveBySignature(ctx, identity.Signature())
	if err != nil {
		t.Fatalf("find: %v", err)
	}
	if len(found) != 1 || found[0].ID != c.ID {
		t.Fatalf("orphaned concept must still own its identity, got %+v", found)
	}
}

// Required case J: atomic create + seed SAME. On success both persist; the seed unit
// gains the current membership in the same call.
func TestConceptRepository_CreateAndAttachAtomic(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	c, link, err := concepts.CreateConcept(ctx, domain.NewConceptInput{
		Identity:       domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"},
		SeedUnitID:     &unitID,
		LinkSeedAsSame: true,
		SeedSource:     domain.SourceHuman,
	})
	if err != nil {
		t.Fatalf("create+attach: %v", err)
	}
	if link == nil || link.ConceptID != c.ID || link.UnitID != unitID {
		t.Fatalf("expected a seed SAME link, got %+v", link)
	}
	// The seed unit holds the current membership and supports the concept.
	sup, _ := concepts.ActiveSupportUnitIDs(ctx, c.ID)
	if len(sup) != 1 || sup[0] != unitID {
		t.Fatalf("seed unit should support the new concept, got %v", sup)
	}
	if c.State != domain.ConceptActive {
		t.Fatalf("create+attach with a supporting unit should read active, got %q", c.State)
	}
}

// Required case J (failure half): if the seed link is impossible (a non-existent
// unit), the whole operation fails and NO concept is persisted.
func TestConceptRepository_CreateAndAttachRollsBack(t *testing.T) {
	_, _, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()

	bogusUnit := int64(999999)
	_, _, err := concepts.CreateConcept(ctx, domain.NewConceptInput{
		Identity:       domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"},
		SeedUnitID:     &bogusUnit,
		LinkSeedAsSame: true,
	})
	if !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound for missing seed unit, got %v", err)
	}
	// No concept must have been left behind.
	all, err := concepts.ListConcepts(ctx, nil)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(all) != 0 {
		t.Fatalf("failed create+attach must persist no concept, got %d", len(all))
	}
}

// Create+seed only ESTABLISHES membership for an unresolved unit (spec 1, case A):
// with no current membership, create+attach succeeds atomically.
func TestConceptRepository_CreateAndAttachEstablishesForUnresolvedUnit(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	c, link, err := concepts.CreateConcept(ctx, domain.NewConceptInput{
		Identity:       domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"},
		SeedUnitID:     &unitID,
		LinkSeedAsSame: true,
		SeedSource:     domain.SourceHuman,
	})
	if err != nil {
		t.Fatalf("create+attach for unresolved unit: %v", err)
	}
	m, err := concepts.GetCurrentMembership(ctx, unitID)
	if err != nil {
		t.Fatalf("get membership: %v", err)
	}
	if m == nil || m.ConceptID != c.ID || m.LinkID != link.ID {
		t.Fatalf("membership should point at the new concept and seed link, got %+v", m)
	}
}

// Create+seed must NOT be a hidden reassignment side door (spec 1, case B): when the
// seed unit already has a current SAME membership, creating another concept with
// link_seed_as_same fails with ErrConceptConflict and persists nothing.
func TestConceptRepository_CreateAndAttachRefusesExistingMembership(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	// Establish current SAME to concept A and make the unit A's preferred rep.
	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	firstLink, err := concepts.LinkSame(ctx, unitID, a.ID, domain.SourceHuman, nil, "")
	if err != nil {
		t.Fatalf("link A: %v", err)
	}
	if _, err := concepts.SetPreferredUnit(ctx, a.ID, unitID); err != nil {
		t.Fatalf("set preferred on A: %v", err)
	}

	// Snapshot A's event history before the attempt.
	beforeA, err := concepts.GetConcept(ctx, a.ID)
	if err != nil {
		t.Fatalf("get A before: %v", err)
	}

	// Attempt to create concept B seeding the SAME already-resolved unit.
	_, link, err := concepts.CreateConcept(ctx, domain.NewConceptInput{
		Identity:       domain.ConceptIdentity{Target: "b", PedagogicalIntent: "grammar"},
		SeedUnitID:     &unitID,
		LinkSeedAsSame: true,
		SeedSource:     domain.SourceHuman,
	})
	if !errors.Is(err, domain.ErrConceptConflict) {
		t.Fatalf("expected ErrConceptConflict from create+seed on a resolved unit, got %v", err)
	}
	if link != nil {
		t.Fatalf("no seed link may be returned, got %+v", link)
	}

	// Concept B must not persist: only A exists.
	all, err := concepts.ListConcepts(ctx, nil)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(all) != 1 || all[0].ID != a.ID {
		t.Fatalf("concept B must not persist; concepts = %+v", all)
	}

	// Current membership is still A via the original link (no new SAME event, no
	// projection change).
	m, err := concepts.GetCurrentMembership(ctx, unitID)
	if err != nil {
		t.Fatalf("get membership: %v", err)
	}
	if m == nil || m.ConceptID != a.ID || m.LinkID != firstLink.ID {
		t.Fatalf("membership must remain A on the original link, got %+v", m)
	}

	// A's preferred unit is unchanged, and its event history is unchanged (no extra
	// SAME event was appended).
	afterA, err := concepts.GetConcept(ctx, a.ID)
	if err != nil {
		t.Fatalf("get A after: %v", err)
	}
	if afterA.Concept.PreferredUnitID == nil || *afterA.Concept.PreferredUnitID != unitID {
		t.Fatalf("A's preferred unit must be unchanged, got %v", afterA.Concept.PreferredUnitID)
	}
	if len(afterA.Links) != len(beforeA.Links) {
		t.Fatalf("A's history must be unchanged: before %d events, after %d", len(beforeA.Links), len(afterA.Links))
	}
}

// GetCurrentMembership reads the projection, not the event log (spec 2). It returns
// nil for an unresolved unit and the current concept for a resolved one.
func TestConceptRepository_GetCurrentMembership(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	// Unresolved: nil membership.
	m, err := concepts.GetCurrentMembership(ctx, unitID)
	if err != nil {
		t.Fatalf("get membership (unresolved): %v", err)
	}
	if m != nil {
		t.Fatalf("unresolved unit must have nil current membership, got %+v", m)
	}

	// Missing unit: ErrNotFound.
	if _, err := concepts.GetCurrentMembership(ctx, 999999); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound for missing unit, got %v", err)
	}

	// After SAME to A: returns A and the establishing link.
	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	linkA, err := concepts.LinkSame(ctx, unitID, a.ID, domain.SourceHuman, nil, "")
	if err != nil {
		t.Fatalf("link A: %v", err)
	}
	m, err = concepts.GetCurrentMembership(ctx, unitID)
	if err != nil {
		t.Fatalf("get membership (A): %v", err)
	}
	if m == nil || m.UnitID != unitID || m.ConceptID != a.ID || m.LinkID != linkA.ID {
		t.Fatalf("expected membership to A on link %d, got %+v", linkA.ID, m)
	}

	// After ReassignSame A->B: immediately returns B and the new superseding link,
	// while the historical A event remains queryable and does not confuse the read.
	b := mustConcept(t, concepts, domain.ConceptIdentity{Target: "b", PedagogicalIntent: "grammar"})
	linkB, err := concepts.ReassignSame(ctx, unitID, b.ID, domain.SourceHuman, "")
	if err != nil {
		t.Fatalf("reassign to B: %v", err)
	}
	m, err = concepts.GetCurrentMembership(ctx, unitID)
	if err != nil {
		t.Fatalf("get membership (B): %v", err)
	}
	if m == nil || m.ConceptID != b.ID || m.LinkID != linkB.ID {
		t.Fatalf("expected membership to B on link %d, got %+v", linkB.ID, m)
	}
	// The historical accepted A event is still present in A's history.
	aView, err := concepts.GetConcept(ctx, a.ID)
	if err != nil {
		t.Fatalf("get A: %v", err)
	}
	foundA := false
	for _, l := range aView.Links {
		if l.ID == linkA.ID && l.ConceptID == a.ID && l.Status == domain.LinkAccepted {
			foundA = true
		}
	}
	if !foundA {
		t.Fatalf("historical A event must remain queryable and accepted")
	}
}

// Milestone 10.6: an explicit human INVALID judgment clears a unit's current SAME
// membership, records the rejection as immutable negative evidence, clears a stale
// preferred_unit_id, and drops the concept's derived support immediately — while
// leaving all historical events queryable. A missing unit is ErrNotFound; a unit
// with no current membership is a deterministic no-op.
func TestConceptRepository_RejectSameClearsMembership(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})

	// Establish current SAME to A and make the unit A's preferred representation, so
	// A is currently supported.
	sameLink, err := concepts.LinkSame(ctx, unitID, a.ID, domain.SourceHuman, nil, "")
	if err != nil {
		t.Fatalf("link A: %v", err)
	}
	if _, err := concepts.SetPreferredUnit(ctx, a.ID, unitID); err != nil {
		t.Fatalf("set preferred on A: %v", err)
	}
	if ids, _ := concepts.ActiveSupportUnitIDs(ctx, a.ID); len(ids) != 1 || ids[0] != unitID {
		t.Fatalf("precondition: A should be supported by the unit, got %v", ids)
	}

	// INVALID: the human rejects the candidate.
	rej, err := concepts.RejectSame(ctx, unitID, domain.SourceHuman, "")
	if err != nil {
		t.Fatalf("reject same: %v", err)
	}
	// The rejection event is an immutable append-only record: relation stays SAME
	// (it is a rejected SAME membership, not a new relation kind), status rejected,
	// human source, and it points back at the SAME event it invalidates.
	if rej == nil {
		t.Fatal("reject must return the appended rejection event")
	}
	if rej.Relation != domain.RelationSame || rej.Status != domain.LinkRejected {
		t.Fatalf("rejection event must be a rejected SAME, got relation=%q status=%q", rej.Relation, rej.Status)
	}
	if rej.DecisionSource != domain.SourceHuman {
		t.Fatalf("rejection must be human-sourced, got %q", rej.DecisionSource)
	}
	if rej.ConceptID != a.ID {
		t.Fatalf("rejection must reference the previously-current concept A, got %d", rej.ConceptID)
	}
	if rej.SupersedesLinkID == nil || *rej.SupersedesLinkID != sameLink.ID {
		t.Fatalf("rejection must supersede the in-force SAME event %d, got %v", sameLink.ID, rej.SupersedesLinkID)
	}

	// Current membership is cleared: the unit belongs to no concept now.
	m, err := concepts.GetCurrentMembership(ctx, unitID)
	if err != nil {
		t.Fatalf("get membership after reject: %v", err)
	}
	if m != nil {
		t.Fatalf("INVALID must clear current membership, got %+v", m)
	}

	// A immediately loses support (support is derived, not stored).
	if ids, _ := concepts.ActiveSupportUnitIDs(ctx, a.ID); len(ids) != 0 {
		t.Fatalf("A must lose support after its only member was rejected, got %v", ids)
	}

	aView, err := concepts.GetConcept(ctx, a.ID)
	if err != nil {
		t.Fatalf("get A: %v", err)
	}
	// Effective state falls to orphaned (normal lifecycle + no support).
	if aView.Concept.State != domain.ConceptOrphaned {
		t.Fatalf("A should be orphaned after losing its only support, got %q", aView.Concept.State)
	}
	// The stale preferred_unit_id is cleared: the unit is no longer a member of A.
	if aView.Concept.PreferredUnitID != nil {
		t.Fatalf("A must not keep an invalid preferred_unit_id, got %v", *aView.Concept.PreferredUnitID)
	}
	// The original accepted SAME event is untouched (append-only history) and both
	// it and the rejection event remain queryable in A's history.
	var foundAccepted, foundRejected bool
	for _, l := range aView.Links {
		if l.ID == sameLink.ID {
			if l.Status != domain.LinkAccepted || l.SupersedesLinkID != nil {
				t.Fatalf("original SAME event must be intact, got %+v", l)
			}
			foundAccepted = true
		}
		if l.ID == rej.ID && l.Status == domain.LinkRejected {
			foundRejected = true
		}
	}
	if !foundAccepted {
		t.Fatal("original accepted SAME event must remain queryable")
	}
	if !foundRejected {
		t.Fatal("the rejection event must be preserved as queryable negative evidence")
	}

	// The unit is reviewable again (no current SAME membership).
	reviewable, err := concepts.ListReviewableUnits(ctx, nil)
	if err != nil {
		t.Fatalf("list reviewable: %v", err)
	}
	seen := false
	for _, ru := range reviewable {
		if ru.Unit.ID == unitID {
			seen = true
		}
	}
	if !seen {
		t.Fatal("a rejected unit with no current membership must be reviewable again")
	}
}

// Rejecting a unit that has no current SAME membership is a deterministic no-op:
// the postcondition (no current membership) already holds, so no rejection event is
// fabricated. A missing unit is ErrNotFound.
func TestConceptRepository_RejectSameDeterministicWithoutMembership(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	// Missing unit.
	if _, err := concepts.RejectSame(ctx, 999999, domain.SourceHuman, ""); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("expected ErrNotFound for missing unit, got %v", err)
	}

	// Unresolved unit: no-op, nil link, no event written.
	link, err := concepts.RejectSame(ctx, unitID, domain.SourceHuman, "")
	if err != nil {
		t.Fatalf("reject unresolved: %v", err)
	}
	if link != nil {
		t.Fatalf("rejecting an unresolved unit must be a no-op, got link %+v", link)
	}

	// Repeated reject after an actual rejection is also a no-op (membership already
	// cleared), and does not append a second rejection event.
	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	if _, err := concepts.LinkSame(ctx, unitID, a.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("link A: %v", err)
	}
	if _, err := concepts.RejectSame(ctx, unitID, domain.SourceHuman, ""); err != nil {
		t.Fatalf("first reject: %v", err)
	}
	before, err := concepts.GetConcept(ctx, a.ID)
	if err != nil {
		t.Fatalf("get A: %v", err)
	}
	if link, err := concepts.RejectSame(ctx, unitID, domain.SourceHuman, ""); err != nil || link != nil {
		t.Fatalf("second reject must be a no-op, got link=%+v err=%v", link, err)
	}
	after, err := concepts.GetConcept(ctx, a.ID)
	if err != nil {
		t.Fatalf("get A again: %v", err)
	}
	if len(after.Links) != len(before.Links) {
		t.Fatalf("a repeated reject must not append another event: had %d links, now %d", len(before.Links), len(after.Links))
	}
}

// After a rejection, the same unit can be resolved SAME again (to any concept) with
// a plain LinkSame — INVALID does not permanently block a unit, it only records that
// the earlier candidate was rejected.
func TestConceptRepository_RejectThenResolveAgain(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	b := mustConcept(t, concepts, domain.ConceptIdentity{Target: "b", PedagogicalIntent: "grammar"})

	if _, err := concepts.LinkSame(ctx, unitID, a.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("link A: %v", err)
	}
	if _, err := concepts.RejectSame(ctx, unitID, domain.SourceHuman, ""); err != nil {
		t.Fatalf("reject: %v", err)
	}
	// With no current membership, a fresh SAME to B is allowed (not a conflict).
	linkB, err := concepts.LinkSame(ctx, unitID, b.ID, domain.SourceHuman, nil, "")
	if err != nil {
		t.Fatalf("link B after reject: %v", err)
	}
	m, err := concepts.GetCurrentMembership(ctx, unitID)
	if err != nil {
		t.Fatalf("get membership: %v", err)
	}
	if m == nil || m.ConceptID != b.ID || m.LinkID != linkB.ID {
		t.Fatalf("unit should now belong SAME to B, got %+v", m)
	}
}

func TestConceptRepository_RelationsAreNotMembership(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	c := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})

	if _, err := concepts.LinkRelation(ctx, unitID, c.ID, domain.RelationBroader, domain.SourceHuman, ""); err != nil {
		t.Fatalf("broader: %v", err)
	}
	// A BROADER relation does not make the unit a member / supporter.
	if ids, _ := concepts.ActiveSupportUnitIDs(ctx, c.ID); len(ids) != 0 {
		t.Fatalf("relation must not create support, got %v", ids)
	}
	// The unit still has no current SAME, so it is reviewable.
	reviewable, err := concepts.ListReviewableUnits(ctx, nil)
	if err != nil {
		t.Fatalf("reviewable: %v", err)
	}
	found := false
	for _, ru := range reviewable {
		if ru.Unit.ID == unitID {
			found = true
		}
	}
	if !found {
		t.Fatalf("unit with only a BROADER relation should remain reviewable")
	}

	// LinkRelation rejects SAME.
	if _, err := concepts.LinkRelation(ctx, unitID, c.ID, domain.RelationSame, domain.SourceHuman, ""); !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("LinkRelation must reject SAME, got %v", err)
	}
}

// Required case D (relations): superseding a relation is append-only — the old
// event row keeps its data and the new one points back at it.
func TestConceptRepository_RelationHistoryIsAppendOnly(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID
	c := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})

	first, err := concepts.LinkRelation(ctx, unitID, c.ID, domain.RelationRelated, domain.SourceHuman, `{"v":1}`)
	if err != nil {
		t.Fatalf("first relation: %v", err)
	}
	second, err := concepts.LinkRelation(ctx, unitID, c.ID, domain.RelationRelated, domain.SourceHuman, `{"v":2}`)
	if err != nil {
		t.Fatalf("second relation: %v", err)
	}
	if second.SupersedesLinkID == nil || *second.SupersedesLinkID != first.ID {
		t.Fatalf("second event must supersede the first, got %v", second.SupersedesLinkID)
	}

	// The first event row is unchanged (still accepted, still its original evidence).
	view2, err := concepts.GetConcept(ctx, c.ID)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	var orig *domain.UnitConceptLink
	for i := range view2.Links {
		if view2.Links[i].ID == first.ID {
			orig = &view2.Links[i]
		}
	}
	if orig == nil {
		t.Fatalf("original relation event must remain queryable")
	}
	if orig.Status != domain.LinkAccepted || orig.Evidence != `{"v":1}` {
		t.Fatalf("original event content must be intact, got %+v", *orig)
	}
}
