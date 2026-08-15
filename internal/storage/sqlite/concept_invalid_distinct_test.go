package sqlite

import (
	"context"
	"errors"
	"testing"

	"french-learning-app/internal/domain"
)

// reviewableContains reports whether the entry's reviewable-unit list currently
// includes unitID.
func reviewableContains(t *testing.T, concepts *ConceptRepository, entryID, unitID int64) bool {
	t.Helper()
	reviewable, err := concepts.ListReviewableUnits(context.Background(), &entryID)
	if err != nil {
		t.Fatalf("list reviewable: %v", err)
	}
	for _, ru := range reviewable {
		if ru.Unit.ID == unitID {
			return true
		}
	}
	return false
}

// Milestone 10.6 case A: a freshly extracted unit that never had a SAME
// membership can be marked INVALID. The judgment is an immutable human record
// (no fake concept is invented), and the unit disappears from the review queue.
func TestConceptRepository_MarkUnitInvalidForUnresolvedUnit(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("garbage candidate")})
	unitID := view.Units[0].Unit.ID
	entryID := entryIDForExtraction(t, knowledge, view.Extraction.ID)

	// Precondition: an unresolved (never-SAME) unit is reviewable.
	if !reviewableContains(t, concepts, entryID, unitID) {
		t.Fatal("precondition: a fresh unresolved unit must be reviewable")
	}
	// And it has no current SAME membership.
	if m, _ := concepts.GetCurrentMembership(ctx, unitID); m != nil {
		t.Fatalf("precondition: unresolved unit must have no membership, got %+v", m)
	}

	j, err := concepts.MarkUnitInvalid(ctx, unitID, domain.SourceHuman, "", `{"reason":"human_unit_invalid"}`)
	if err != nil {
		t.Fatalf("mark invalid: %v", err)
	}
	// The judgment is a real recorded human judgment against the unit — no fake
	// concept id is fabricated (the type has no concept field at all).
	if j == nil {
		t.Fatal("mark invalid must return the recorded judgment")
	}
	if j.UnitID != unitID {
		t.Fatalf("judgment must reference the unit, got unit_id=%d", j.UnitID)
	}
	if j.Judgment != domain.UnitInvalid {
		t.Fatalf("judgment kind must be invalid, got %q", j.Judgment)
	}
	if j.DecisionSource != domain.SourceHuman {
		t.Fatalf("judgment must be human-sourced, got %q", j.DecisionSource)
	}
	if j.ID == 0 || j.CreatedAt.IsZero() {
		t.Fatalf("judgment must be persisted with an id and timestamp, got %+v", j)
	}

	// Effective invalid state: the latest judgment marks it invalid.
	latest, err := concepts.LatestUnitJudgment(ctx, unitID)
	if err != nil {
		t.Fatalf("latest judgment: %v", err)
	}
	if !domain.EffectiveUnitInvalid(latest) {
		t.Fatalf("unit must read effectively invalid, latest=%+v", latest)
	}

	// The unit leaves the review queue.
	if reviewableContains(t, concepts, entryID, unitID) {
		t.Fatal("an INVALID unit must not appear in the review queue")
	}

	// Marking INVALID created no SAME membership.
	if m, _ := concepts.GetCurrentMembership(ctx, unitID); m != nil {
		t.Fatalf("INVALID must not create a membership, got %+v", m)
	}
}

// Milestone 10.6 case B: repeated INVALID is deterministic and append-only —
// marking an already-invalid unit does not append a second judgment and yields
// the same effective state.
func TestConceptRepository_MarkUnitInvalidIsIdempotent(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	first, err := concepts.MarkUnitInvalid(ctx, unitID, domain.SourceHuman, "", "")
	if err != nil {
		t.Fatalf("first mark invalid: %v", err)
	}
	second, err := concepts.MarkUnitInvalid(ctx, unitID, domain.SourceHuman, "", "")
	if err != nil {
		t.Fatalf("second mark invalid: %v", err)
	}
	// Idempotent: the second call returns the same in-force judgment, not a new one.
	if second == nil || second.ID != first.ID {
		t.Fatalf("repeated INVALID must be idempotent (same judgment), got first=%+v second=%+v", first, second)
	}

	history, err := concepts.ListUnitJudgments(ctx, unitID)
	if err != nil {
		t.Fatalf("list judgments: %v", err)
	}
	if len(history) != 1 {
		t.Fatalf("repeated INVALID must append only one judgment, got %d", len(history))
	}
	if !domain.EffectiveUnitInvalid(&history[0]) {
		t.Fatalf("unit must remain effectively invalid, got %+v", history[0])
	}
}

// Milestone 10.6 case C: a wrongly-invalidated unit can be restored to the review
// queue. The historical INVALID judgment is preserved (append-only), and the unit
// becomes reviewable again.
func TestConceptRepository_RestoreUnitReversesInvalid(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID
	entryID := entryIDForExtraction(t, knowledge, view.Extraction.ID)

	if _, err := concepts.MarkUnitInvalid(ctx, unitID, domain.SourceHuman, "", ""); err != nil {
		t.Fatalf("mark invalid: %v", err)
	}
	if reviewableContains(t, concepts, entryID, unitID) {
		t.Fatal("precondition: invalid unit must not be reviewable")
	}

	restored, err := concepts.RestoreUnit(ctx, unitID, domain.SourceHuman, "", "")
	if err != nil {
		t.Fatalf("restore: %v", err)
	}
	if restored == nil || restored.Judgment != domain.UnitRestored {
		t.Fatalf("restore must append a 'restored' judgment, got %+v", restored)
	}

	// The unit is reviewable again.
	if !reviewableContains(t, concepts, entryID, unitID) {
		t.Fatal("a restored unit must be reviewable again")
	}
	// Effective state is no longer invalid.
	latest, err := concepts.LatestUnitJudgment(ctx, unitID)
	if err != nil {
		t.Fatalf("latest: %v", err)
	}
	if domain.EffectiveUnitInvalid(latest) {
		t.Fatalf("restored unit must not read invalid, latest=%+v", latest)
	}

	// The historical INVALID judgment is preserved: full history has both events,
	// newest first (restored, then invalid).
	history, err := concepts.ListUnitJudgments(ctx, unitID)
	if err != nil {
		t.Fatalf("history: %v", err)
	}
	if len(history) != 2 {
		t.Fatalf("history must preserve both judgments, got %d", len(history))
	}
	if history[0].Judgment != domain.UnitRestored || history[1].Judgment != domain.UnitInvalid {
		t.Fatalf("history must be [restored, invalid] newest-first, got [%q, %q]", history[0].Judgment, history[1].Judgment)
	}

	// Restoring a unit that is not currently invalid is an idempotent no-op.
	noop, err := concepts.RestoreUnit(ctx, unitID, domain.SourceHuman, "", "")
	if err != nil {
		t.Fatalf("restore no-op: %v", err)
	}
	if noop != nil {
		t.Fatalf("restoring a non-invalid unit must be a no-op, got %+v", noop)
	}
	// And it may be invalidated again (a fresh invalid judgment appends).
	if _, err := concepts.MarkUnitInvalid(ctx, unitID, domain.SourceHuman, "", ""); err != nil {
		t.Fatalf("re-invalidate: %v", err)
	}
	history, err = concepts.ListUnitJudgments(ctx, unitID)
	if err != nil {
		t.Fatalf("history after re-invalidate: %v", err)
	}
	if len(history) != 3 || history[0].Judgment != domain.UnitInvalid {
		t.Fatalf("re-invalidation must append a third judgment (invalid newest), got %d events newest=%q", len(history), history[0].Judgment)
	}
}

// Milestone 10.6 case D: a unit that currently has a SAME membership can be marked
// INVALID. The atomic rule (option A) clears the SAME membership in the same
// transaction, so the unit is never simultaneously SAME to a concept and INVALID.
// The cleared SAME survives as immutable negative evidence.
func TestConceptRepository_MarkUnitInvalidClearsCurrentSame(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID
	entryID := entryIDForExtraction(t, knowledge, view.Extraction.ID)

	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	sameLink, err := concepts.LinkSame(ctx, unitID, a.ID, domain.SourceHuman, nil, "")
	if err != nil {
		t.Fatalf("link A: %v", err)
	}
	if _, err := concepts.SetPreferredUnit(ctx, a.ID, unitID); err != nil {
		t.Fatalf("set preferred: %v", err)
	}
	if ids, _ := concepts.ActiveSupportUnitIDs(ctx, a.ID); len(ids) != 1 {
		t.Fatalf("precondition: A supported by the unit, got %v", ids)
	}

	if _, err := concepts.MarkUnitInvalid(ctx, unitID, domain.SourceHuman, "", ""); err != nil {
		t.Fatalf("mark invalid: %v", err)
	}

	// No contradictory current state: the SAME membership is gone AND the unit is
	// effectively invalid.
	if m, _ := concepts.GetCurrentMembership(ctx, unitID); m != nil {
		t.Fatalf("INVALID must clear the current SAME membership, got %+v", m)
	}
	latest, err := concepts.LatestUnitJudgment(ctx, unitID)
	if err != nil {
		t.Fatalf("latest: %v", err)
	}
	if !domain.EffectiveUnitInvalid(latest) {
		t.Fatalf("unit must read effectively invalid, got %+v", latest)
	}

	// A loses support immediately and its stale preferred unit is cleared.
	if ids, _ := concepts.ActiveSupportUnitIDs(ctx, a.ID); len(ids) != 0 {
		t.Fatalf("A must lose support after its only member was invalidated, got %v", ids)
	}
	aView, err := concepts.GetConcept(ctx, a.ID)
	if err != nil {
		t.Fatalf("get A: %v", err)
	}
	if aView.Concept.PreferredUnitID != nil {
		t.Fatalf("A must not keep a stale preferred_unit_id, got %v", *aView.Concept.PreferredUnitID)
	}

	// The cleared SAME survives as immutable negative evidence: the original accepted
	// event is intact and a rejected-SAME event superseding it exists.
	var foundAccepted, foundRejected bool
	for _, l := range aView.Links {
		if l.ID == sameLink.ID && l.Status == domain.LinkAccepted && l.SupersedesLinkID == nil {
			foundAccepted = true
		}
		if l.Relation == domain.RelationSame && l.Status == domain.LinkRejected &&
			l.SupersedesLinkID != nil && *l.SupersedesLinkID == sameLink.ID {
			foundRejected = true
		}
	}
	if !foundAccepted {
		t.Fatal("original accepted SAME event must remain intact")
	}
	if !foundRejected {
		t.Fatal("clearing SAME on INVALID must leave a rejected-SAME event as negative evidence")
	}

	// The INVALID unit is not reviewable (distinct from a plain reject, which would
	// make it reviewable again).
	if reviewableContains(t, concepts, entryID, unitID) {
		t.Fatal("an INVALID unit must not be reviewable")
	}
}

// Milestone 10.6 case E: recording DISTINCT(unit, concept) persists an explicit
// negative pair, creates no SAME membership, and leaves the unit reviewable.
func TestConceptRepository_RecordDistinctionKeepsUnitReviewable(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID
	entryID := entryIDForExtraction(t, knowledge, view.Extraction.ID)

	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})

	d, err := concepts.RecordDistinction(ctx, unitID, a.ID, domain.SourceHuman, `{"reason":"human_distinct"}`)
	if err != nil {
		t.Fatalf("record distinction: %v", err)
	}
	if d == nil || d.UnitID != unitID || d.ConceptID != a.ID {
		t.Fatalf("distinction must reference the unit and concept, got %+v", d)
	}
	if d.DecisionSource != domain.SourceHuman || d.ID == 0 || d.CreatedAt.IsZero() {
		t.Fatalf("distinction must be a persisted human record, got %+v", d)
	}

	// No SAME membership was created.
	if m, _ := concepts.GetCurrentMembership(ctx, unitID); m != nil {
		t.Fatalf("DISTINCT must not create a membership, got %+v", m)
	}
	// A has no support from this unit (DISTINCT is not a relation or membership).
	if ids, _ := concepts.ActiveSupportUnitIDs(ctx, a.ID); len(ids) != 0 {
		t.Fatalf("DISTINCT must not support the concept, got %v", ids)
	}
	// The unit remains reviewable.
	if !reviewableContains(t, concepts, entryID, unitID) {
		t.Fatal("a unit with only a DISTINCT judgment must remain reviewable")
	}

	// The distinction is queryable.
	list, err := concepts.ListDistinctions(ctx, unitID)
	if err != nil {
		t.Fatalf("list distinctions: %v", err)
	}
	if len(list) != 1 || list[0].ID != d.ID || list[0].ConceptID != a.ID {
		t.Fatalf("distinction must be queryable, got %+v", list)
	}
}

// Milestone 10.6 case F: the reviewer marks the unit DISTINCT from candidate A,
// then creates a NEW concept B and resolves SAME to B. The negative pair (U, A)
// and the positive membership (U, B) coexist as independent evidence.
func TestConceptRepository_DistinctThenSameToNewConcept(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})

	// Reviewer: "this unit is NOT the same as A".
	if _, err := concepts.RecordDistinction(ctx, unitID, a.ID, domain.SourceHuman, ""); err != nil {
		t.Fatalf("distinct from A: %v", err)
	}

	// Reviewer then creates a NEW concept B and attaches the unit SAME to it.
	b, linkB, err := concepts.CreateConcept(ctx, domain.NewConceptInput{
		Identity:       domain.ConceptIdentity{Target: "b", PedagogicalIntent: "grammar"},
		SeedUnitID:     &unitID,
		LinkSeedAsSame: true,
		SeedSource:     domain.SourceHuman,
	})
	if err != nil {
		t.Fatalf("create+attach B: %v", err)
	}

	// Positive: the unit belongs SAME to B.
	m, err := concepts.GetCurrentMembership(ctx, unitID)
	if err != nil {
		t.Fatalf("membership: %v", err)
	}
	if m == nil || m.ConceptID != b.ID || m.LinkID != linkB.ID {
		t.Fatalf("unit must belong SAME to B, got %+v", m)
	}

	// Negative: the (unit, A) DISTINCT pair remains, independent of the B membership.
	dist, err := concepts.ListDistinctions(ctx, unitID)
	if err != nil {
		t.Fatalf("list distinctions: %v", err)
	}
	if len(dist) != 1 || dist[0].ConceptID != a.ID {
		t.Fatalf("the (unit, A) negative pair must persist, got %+v", dist)
	}
	// The distinction did not accidentally reference B.
	if dist[0].ConceptID == b.ID {
		t.Fatal("DISTINCT must reference A, not the newly-created B")
	}
}

// Milestone 10.6 case G: error handling for missing units and concepts across the
// new operations.
func TestConceptRepository_InvalidAndDistinctErrorHandling(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID
	const missing = int64(999999)

	// MarkUnitInvalid / RestoreUnit on a missing unit.
	if _, err := concepts.MarkUnitInvalid(ctx, missing, domain.SourceHuman, "", ""); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("MarkUnitInvalid missing unit: expected ErrNotFound, got %v", err)
	}
	if _, err := concepts.RestoreUnit(ctx, missing, domain.SourceHuman, "", ""); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("RestoreUnit missing unit: expected ErrNotFound, got %v", err)
	}
	if _, err := concepts.LatestUnitJudgment(ctx, missing); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("LatestUnitJudgment missing unit: expected ErrNotFound, got %v", err)
	}
	if _, err := concepts.ListUnitJudgments(ctx, missing); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("ListUnitJudgments missing unit: expected ErrNotFound, got %v", err)
	}

	// RecordDistinction with a missing unit, and with a missing concept.
	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	if _, err := concepts.RecordDistinction(ctx, missing, a.ID, domain.SourceHuman, ""); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("RecordDistinction missing unit: expected ErrNotFound, got %v", err)
	}
	if _, err := concepts.RecordDistinction(ctx, unitID, missing, domain.SourceHuman, ""); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("RecordDistinction missing concept: expected ErrNotFound, got %v", err)
	}
	if _, err := concepts.ListDistinctions(ctx, missing); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("ListDistinctions missing unit: expected ErrNotFound, got %v", err)
	}
}

func TestConceptRepository_InvalidUnitCannotLinkSame(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID
	concept := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})

	if _, err := concepts.MarkUnitInvalid(ctx, unitID, domain.SourceHuman, "", ""); err != nil {
		t.Fatalf("mark invalid: %v", err)
	}
	if _, err := concepts.LinkSame(ctx, unitID, concept.ID, domain.SourceHuman, nil, ""); !errors.Is(err, domain.ErrConceptConflict) {
		t.Fatalf("LinkSame on INVALID unit: expected ErrConceptConflict, got %v", err)
	}
	if membership, err := concepts.GetCurrentMembership(ctx, unitID); err != nil {
		t.Fatalf("get membership: %v", err)
	} else if membership != nil {
		t.Fatalf("failed LinkSame must not establish membership, got %+v", membership)
	}
}

func TestConceptRepository_InvalidUnitCannotReassignSame(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID
	concept := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})

	if _, err := concepts.MarkUnitInvalid(ctx, unitID, domain.SourceHuman, "", ""); err != nil {
		t.Fatalf("mark invalid: %v", err)
	}
	if _, err := concepts.ReassignSame(ctx, unitID, concept.ID, domain.SourceHuman, ""); !errors.Is(err, domain.ErrConceptConflict) {
		t.Fatalf("ReassignSame on INVALID unit: expected ErrConceptConflict, got %v", err)
	}
	if membership, err := concepts.GetCurrentMembership(ctx, unitID); err != nil {
		t.Fatalf("get membership: %v", err)
	} else if membership != nil {
		t.Fatalf("failed ReassignSame must not establish membership, got %+v", membership)
	}
}

func TestConceptRepository_InvalidUnitCreateAndAttachRollsBack(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID

	if _, err := concepts.MarkUnitInvalid(ctx, unitID, domain.SourceHuman, "", ""); err != nil {
		t.Fatalf("mark invalid: %v", err)
	}
	_, link, err := concepts.CreateConcept(ctx, domain.NewConceptInput{
		Identity:       domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"},
		SeedUnitID:     &unitID,
		LinkSeedAsSame: true,
		SeedSource:     domain.SourceHuman,
	})
	if !errors.Is(err, domain.ErrConceptConflict) {
		t.Fatalf("create+attach on INVALID unit: expected ErrConceptConflict, got %v", err)
	}
	if link != nil {
		t.Fatalf("failed create+attach must not return a SAME event, got %+v", link)
	}

	all, err := concepts.ListConcepts(ctx, nil)
	if err != nil {
		t.Fatalf("list concepts: %v", err)
	}
	if len(all) != 0 {
		t.Fatalf("failed create+attach must roll back the concept, got %+v", all)
	}
	if membership, err := concepts.GetCurrentMembership(ctx, unitID); err != nil {
		t.Fatalf("get membership: %v", err)
	} else if membership != nil {
		t.Fatalf("failed create+attach must not establish membership, got %+v", membership)
	}
	var sameEvents int
	if err := concepts.db.QueryRowContext(ctx,
		`SELECT COUNT(*) FROM unit_concept_links WHERE unit_id = ? AND relation = 'same'`, unitID).
		Scan(&sameEvents); err != nil {
		t.Fatalf("count SAME events: %v", err)
	}
	if sameEvents != 0 {
		t.Fatalf("failed create+attach must not persist a SAME event, got %d", sameEvents)
	}
}

func TestConceptRepository_RestoredUnitCanLinkSame(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID
	concept := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})

	if _, err := concepts.MarkUnitInvalid(ctx, unitID, domain.SourceHuman, "", ""); err != nil {
		t.Fatalf("mark invalid: %v", err)
	}
	if _, err := concepts.RestoreUnit(ctx, unitID, domain.SourceHuman, "", ""); err != nil {
		t.Fatalf("restore unit: %v", err)
	}
	link, err := concepts.LinkSame(ctx, unitID, concept.ID, domain.SourceHuman, nil, "")
	if err != nil {
		t.Fatalf("LinkSame after restore: %v", err)
	}
	membership, err := concepts.GetCurrentMembership(ctx, unitID)
	if err != nil {
		t.Fatalf("get membership: %v", err)
	}
	if membership == nil || membership.ConceptID != concept.ID || membership.LinkID != link.ID {
		t.Fatalf("restored unit must establish SAME membership, got %+v", membership)
	}
}

func TestConceptRepository_DistinctFromCurrentSameConflicts(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID
	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	linkA, err := concepts.LinkSame(ctx, unitID, a.ID, domain.SourceHuman, nil, "")
	if err != nil {
		t.Fatalf("link A: %v", err)
	}

	if _, err := concepts.RecordDistinction(ctx, unitID, a.ID, domain.SourceHuman, ""); !errors.Is(err, domain.ErrConceptConflict) {
		t.Fatalf("DISTINCT from CURRENT SAME concept: expected ErrConceptConflict, got %v", err)
	}
	distinctions, err := concepts.ListDistinctions(ctx, unitID)
	if err != nil {
		t.Fatalf("list distinctions: %v", err)
	}
	if len(distinctions) != 0 {
		t.Fatalf("conflicting DISTINCT must insert nothing, got %+v", distinctions)
	}
	membership, err := concepts.GetCurrentMembership(ctx, unitID)
	if err != nil {
		t.Fatalf("get membership: %v", err)
	}
	if membership == nil || membership.ConceptID != a.ID || membership.LinkID != linkA.ID {
		t.Fatalf("conflicting DISTINCT must leave CURRENT SAME A unchanged, got %+v", membership)
	}
}

func TestConceptRepository_DistinctFromOtherConceptKeepsCurrentSame(t *testing.T) {
	entries, knowledge, _, concepts := newConceptTestRepos(t)
	ctx := context.Background()
	view := seedExtractionWithUnits(t, entries, knowledge, []domain.ExtractedUnit{grammarUnit("x")})
	unitID := view.Units[0].Unit.ID
	a := mustConcept(t, concepts, domain.ConceptIdentity{Target: "a", PedagogicalIntent: "grammar"})
	b := mustConcept(t, concepts, domain.ConceptIdentity{Target: "b", PedagogicalIntent: "grammar"})
	linkA, err := concepts.LinkSame(ctx, unitID, a.ID, domain.SourceHuman, nil, "")
	if err != nil {
		t.Fatalf("link A: %v", err)
	}

	distinction, err := concepts.RecordDistinction(ctx, unitID, b.ID, domain.SourceHuman, "")
	if err != nil {
		t.Fatalf("DISTINCT from B: %v", err)
	}
	if distinction == nil || distinction.ConceptID != b.ID {
		t.Fatalf("DISTINCT from B must persist, got %+v", distinction)
	}
	membership, err := concepts.GetCurrentMembership(ctx, unitID)
	if err != nil {
		t.Fatalf("get membership: %v", err)
	}
	if membership == nil || membership.ConceptID != a.ID || membership.LinkID != linkA.ID {
		t.Fatalf("DISTINCT from B must leave CURRENT SAME A unchanged, got %+v", membership)
	}
}
