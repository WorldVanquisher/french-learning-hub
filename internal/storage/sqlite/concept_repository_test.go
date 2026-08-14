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
	c, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: identity, SeedUnitID: &seedUnit})
	if err != nil {
		t.Fatalf("create concept: %v", err)
	}
	if c.State != domain.ConceptActive {
		t.Fatalf("new concept should be active, got %q", c.State)
	}

	// A second active concept with the same identity is refused.
	if _, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: identity}); !errors.Is(err, domain.ErrConceptConflict) {
		t.Fatalf("expected ErrConceptConflict for duplicate active identity, got %v", err)
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

	// Two units whose DERIVED identities differ, but we give them the SAME explicit
	// identity to model "different wording, same objective".
	v1 := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "vouloir + infinitif", Statement: "one wording", Confidence: 0.9},
	})
	v2 := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{
		{Kind: domain.KindGrammar, Canonical: "on utilise vouloir puis un infinitif", Statement: "another wording", Confidence: 0.9},
	})
	unitA := v1.Units[0].Unit.ID
	unitB := v2.Units[0].Unit.ID

	identity := domain.ConceptIdentity{Target: "vouloir + infinitive", PedagogicalIntent: "grammar"}
	c, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: identity})
	if err != nil {
		t.Fatalf("create concept: %v", err)
	}

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
		t.Fatalf("expected 2 accepted SAME links, got %d", sameCount)
	}
}

// Required case 3: one unit cannot hold two accepted SAME memberships.
func TestConceptRepository_OneAcceptedSamePerUnit(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	c1, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"}})
	if err != nil {
		t.Fatalf("create c1: %v", err)
	}
	c2, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: domain.ConceptIdentity{Target: "b", PedagogicalIntent: "grammar"}})
	if err != nil {
		t.Fatalf("create c2: %v", err)
	}

	if _, err := concepts.LinkSame(ctx, unitID, c1.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("first same: %v", err)
	}
	// Second SAME to a different concept must conflict.
	if _, err := concepts.LinkSame(ctx, unitID, c2.ID, domain.SourceHuman, nil, ""); !errors.Is(err, domain.ErrConceptConflict) {
		t.Fatalf("expected ErrConceptConflict on second SAME, got %v", err)
	}
	// Re-affirming the same concept is idempotent (no error).
	if _, err := concepts.LinkSame(ctx, unitID, c1.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("idempotent re-affirmation should succeed, got %v", err)
	}
}

// Required case 4 & 5: SAME membership does not auto-set preferred unit; and the
// preferred unit must have an accepted SAME membership to that concept.
func TestConceptRepository_PreferredUnitRules(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x"), grammarUnit("y")})
	memberUnit := view.Units[0].Unit.ID
	nonMemberUnit := view.Units[1].Unit.ID

	c, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"}})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
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

// Required cases 6 & 8: a newer successful extraction becomes current, and units
// from the old extraction no longer provide current support.
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

	// Link the old unit as SAME to a concept: it supports the concept while v1 is current.
	c, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"}})
	if err != nil {
		t.Fatalf("create concept: %v", err)
	}
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

	// A newer successful extraction becomes current by default.
	second := mk("v2 unit")
	current, err := concepts.GetCurrentExtractionID(ctx, entryID)
	if err != nil {
		t.Fatalf("current: %v", err)
	}
	if current == nil || *current != second.Extraction.ID {
		t.Fatalf("newer extraction should be current, got %v want %d", current, second.Extraction.ID)
	}

	// The old unit no longer provides current support (case 8).
	supported, err = concepts.ActiveSupportUnitIDs(ctx, c.ID)
	if err != nil {
		t.Fatalf("support after v2: %v", err)
	}
	if len(supported) != 0 {
		t.Fatalf("old-extraction unit must not support the current pool, got %v", supported)
	}

	// The old unit and link remain queryable (case 10).
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

// Required case 11: a concept that loses all current support becomes orphaned, not
// deleted.
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

	c, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"}})
	if err != nil {
		t.Fatalf("create concept: %v", err)
	}
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

	// Support recompute is triggered by an explicit current-extraction set (also
	// covers rollback plumbing). Re-selecting the latest is a no-op selection but
	// forces a recompute of affected concepts.
	current, _ := concepts.GetCurrentExtractionID(ctx, entryID)
	if err := concepts.SetCurrentExtraction(ctx, entryID, *current); err != nil {
		t.Fatalf("set current: %v", err)
	}

	got, err := concepts.GetConcept(ctx, c.ID)
	if err != nil {
		t.Fatalf("concept must still exist (not deleted): %v", err)
	}
	if got.Concept.State != domain.ConceptOrphaned {
		t.Fatalf("unsupported concept should be orphaned, got %q", got.Concept.State)
	}
}

// Required case 9: a failed extraction persists nothing, so it cannot replace the
// last successful current extraction. We model the storage guarantee: only
// successful Create calls write rows, and the current pointer derives from what is
// stored.
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
	// writing nothing (the failure mode a real extractor error would surface as
	// no persisted extraction).
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

// Required case 7: a successful zero-unit extraction is current and contributes
// zero units to the pool.
func TestConceptRepository_ZeroUnitExtractionIsCurrentWithNoUnits(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()

	entryID, analysisID := seedEntryWithAnalysis(t, entries, knowledge)
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
}

// Explicit rollback to an older successful extraction makes its units current
// again (design requirement: future explicit human rollback is possible).
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
	c, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"}})
	if err != nil {
		t.Fatalf("concept: %v", err)
	}
	if _, err := concepts.LinkSame(ctx, oldUnit, c.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("link: %v", err)
	}
	_ = mk("v2") // v2 becomes current, old support drops

	if ids, _ := concepts.ActiveSupportUnitIDs(ctx, c.ID); len(ids) != 0 {
		t.Fatalf("expected no support under v2, got %v", ids)
	}

	// Roll back to the first extraction: the old unit supports again.
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

// A suppressed (non-active) admission unit does not provide current support even
// when it is in the current extraction and has an accepted SAME link.
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

	c, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"}})
	if err != nil {
		t.Fatalf("concept: %v", err)
	}
	if _, err := concepts.LinkSame(ctx, suppressed, c.ID, domain.SourceHuman, nil, ""); err != nil {
		t.Fatalf("link suppressed: %v", err)
	}
	ids, err := concepts.ActiveSupportUnitIDs(ctx, c.ID)
	if err != nil {
		t.Fatalf("support: %v", err)
	}
	if len(ids) != 0 {
		t.Fatalf("suppressed unit must not support the pool, got %v", ids)
	}

	// A human override re-activating the unit restores support.
	if _, err := admission.Create(ctx, suppressed, domain.NewAdmissionOverrideInput{Decision: domain.HumanAdmitActive}); err != nil {
		t.Fatalf("override: %v", err)
	}
	ids, err = concepts.ActiveSupportUnitIDs(ctx, c.ID)
	if err != nil {
		t.Fatalf("support after override: %v", err)
	}
	if len(ids) != 1 || ids[0] != suppressed {
		t.Fatalf("re-activated unit should support, got %v", ids)
	}
}

func TestConceptRepository_RelationsAreNotMembership(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	c, err := concepts.CreateConcept(ctx, domain.NewConceptInput{Identity: domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"}})
	if err != nil {
		t.Fatalf("concept: %v", err)
	}

	if _, err := concepts.LinkRelation(ctx, unitID, c.ID, domain.RelationBroader, domain.SourceHuman, ""); err != nil {
		t.Fatalf("broader: %v", err)
	}
	// A BROADER relation does not make the unit a member / supporter.
	if ids, _ := concepts.ActiveSupportUnitIDs(ctx, c.ID); len(ids) != 0 {
		t.Fatalf("relation must not create support, got %v", ids)
	}
	// The unit still has no accepted SAME, so it is reviewable.
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
