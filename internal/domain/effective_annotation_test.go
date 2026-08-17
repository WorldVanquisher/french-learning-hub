package domain

import (
	"errors"
	"reflect"
	"testing"
	"time"
)

var annotationEpoch = time.Date(2026, time.January, 1, 0, 0, 0, 0, time.UTC)

func annotationTime(second int) time.Time {
	return annotationEpoch.Add(time.Duration(second) * time.Second)
}

func annotationLink(id, unitID, conceptID int64, relation ConceptRelation, status LinkStatus, second int) UnitConceptLink {
	return UnitConceptLink{
		ID:              id,
		UnitID:          unitID,
		ConceptID:       conceptID,
		Relation:        relation,
		Status:          status,
		DecisionSource:  SourceHuman,
		ResolverVersion: ConceptResolverVersion,
		Evidence:        "{}",
		CreatedAt:       annotationTime(second),
	}
}

func annotationDistinction(id, unitID, conceptID int64, second int) UnitConceptDistinction {
	return UnitConceptDistinction{
		ID:              id,
		UnitID:          unitID,
		ConceptID:       conceptID,
		DecisionSource:  SourceHuman,
		ResolverVersion: ConceptResolverVersion,
		Evidence:        "{}",
		CreatedAt:       annotationTime(second),
	}
}

func annotationMembership(unitID, conceptID, linkID int64) *CurrentConceptMembership {
	return &CurrentConceptMembership{
		UnitID:    unitID,
		ConceptID: conceptID,
		LinkID:    linkID,
		UpdatedAt: annotationTime(20),
	}
}

func resolveAnnotation(
	t *testing.T,
	latest *UnitResolutionJudgment,
	membership *CurrentConceptMembership,
	links []UnitConceptLink,
	distinctions []UnitConceptDistinction,
) EffectiveAnnotationSnapshot {
	t.Helper()
	snapshot, err := ResolveEffectiveAnnotation(7, latest, membership, links, distinctions)
	if err != nil {
		t.Fatalf("ResolveEffectiveAnnotation: %v", err)
	}
	return snapshot
}

func TestResolveEffectiveAnnotation_EmptyHistoryIsUnresolved(t *testing.T) {
	snapshot := resolveAnnotation(t, nil, nil, nil, nil)
	if snapshot.Status != EffectiveAnnotationUnresolved {
		t.Fatalf("status = %q, want unresolved", snapshot.Status)
	}
	if snapshot.CurrentSame != nil || snapshot.LatestUnitJudgment != nil {
		t.Fatalf("empty history emitted authority: %+v", snapshot)
	}
	if len(snapshot.Distinctions) != 0 || len(snapshot.Relations) != 0 {
		t.Fatalf("empty history emitted pair labels: %+v", snapshot)
	}
}

func TestResolveEffectiveAnnotation_CurrentSamePreservesProvenance(t *testing.T) {
	for _, source := range []DecisionSource{SourceHuman, SourceResolverAutomatic} {
		t.Run(string(source), func(t *testing.T) {
			decision := annotationLink(11, 7, 42, RelationSame, LinkAccepted, 1)
			decision.DecisionSource = source
			decision.Evidence = `{"reason":"exact"}`
			snapshot := resolveAnnotation(t, nil, annotationMembership(7, 42, 11), []UnitConceptLink{decision}, nil)

			if snapshot.Status != EffectiveAnnotationResolved || snapshot.CurrentSame == nil {
				t.Fatalf("CURRENT SAME must resolve the unit: %+v", snapshot)
			}
			if snapshot.CurrentSame.Membership.LinkID != 11 || snapshot.CurrentSame.Decision.ID != 11 {
				t.Fatalf("membership provenance not preserved: %+v", snapshot.CurrentSame)
			}
			if snapshot.CurrentSame.Decision.DecisionSource != source || snapshot.CurrentSame.Decision.Evidence != decision.Evidence {
				t.Fatalf("decision source/evidence not preserved: %+v", snapshot.CurrentSame.Decision)
			}
		})
	}
}

func TestResolveEffectiveAnnotation_ReassignUsesOnlyCurrentMembership(t *testing.T) {
	a := annotationLink(1, 7, 10, RelationSame, LinkAccepted, 1)
	b := annotationLink(2, 7, 20, RelationSame, LinkAccepted, 2)
	b.SupersedesLinkID = &a.ID

	snapshot := resolveAnnotation(t, nil, annotationMembership(7, 20, 2), []UnitConceptLink{b, a}, nil)
	if snapshot.CurrentSame == nil || snapshot.CurrentSame.Decision.ID != b.ID || snapshot.CurrentSame.Membership.ConceptID != 20 {
		t.Fatalf("only CURRENT SAME B should survive: %+v", snapshot.CurrentSame)
	}
}

func TestResolveEffectiveAnnotation_InvalidSuppressesPairSemantics(t *testing.T) {
	same := annotationLink(1, 7, 10, RelationSame, LinkAccepted, 1)
	relation := annotationLink(2, 7, 20, RelationRelated, LinkAccepted, 2)
	latest := &UnitResolutionJudgment{
		ID:             9,
		UnitID:         7,
		Judgment:       UnitInvalid,
		DecisionSource: SourceHuman,
		Evidence:       `{"reason":"invalid"}`,
		CreatedAt:      annotationTime(3),
	}
	snapshot := resolveAnnotation(
		t,
		latest,
		annotationMembership(7, 10, 1),
		[]UnitConceptLink{same, relation},
		[]UnitConceptDistinction{annotationDistinction(1, 7, 30, 2)},
	)
	if snapshot.Status != EffectiveAnnotationInvalid || snapshot.CurrentSame != nil {
		t.Fatalf("INVALID must win and suppress SAME: %+v", snapshot)
	}
	if snapshot.LatestUnitJudgment == nil || snapshot.LatestUnitJudgment.ID != latest.ID {
		t.Fatalf("latest INVALID provenance not preserved: %+v", snapshot.LatestUnitJudgment)
	}
	if len(snapshot.Distinctions) != 0 || len(snapshot.Relations) != 0 {
		t.Fatalf("INVALID must suppress pair labels: %+v", snapshot)
	}
}

func TestResolveEffectiveAnnotation_RestoredDoesNotResurrectClearedSame(t *testing.T) {
	same := annotationLink(1, 7, 10, RelationSame, LinkAccepted, 1)
	rejected := annotationLink(2, 7, 10, RelationSame, LinkRejected, 2)
	rejected.SupersedesLinkID = &same.ID
	latest := &UnitResolutionJudgment{ID: 4, UnitID: 7, Judgment: UnitRestored, DecisionSource: SourceHuman, CreatedAt: annotationTime(4)}

	snapshot := resolveAnnotation(t, latest, nil, []UnitConceptLink{same, rejected}, nil)
	if snapshot.Status != EffectiveAnnotationUnresolved || snapshot.CurrentSame != nil {
		t.Fatalf("restored unit without membership must be unresolved: %+v", snapshot)
	}
}

func TestResolveEffectiveAnnotation_DistinctionSuppressionAndRenewal(t *testing.T) {
	t.Run("explicit distinction is effective", func(t *testing.T) {
		distinction := annotationDistinction(1, 7, 10, 1)
		snapshot := resolveAnnotation(t, nil, nil, nil, []UnitConceptDistinction{distinction})
		if len(snapshot.Distinctions) != 1 || snapshot.Distinctions[0].ID != distinction.ID {
			t.Fatalf("explicit DISTINCT should be effective: %+v", snapshot.Distinctions)
		}
	})

	t.Run("later or tied SAME suppresses distinction", func(t *testing.T) {
		distinction := annotationDistinction(1, 7, 10, 1)
		same := annotationLink(2, 7, 10, RelationSame, LinkAccepted, 1)
		snapshot := resolveAnnotation(t, nil, annotationMembership(7, 10, 2), []UnitConceptLink{same}, []UnitConceptDistinction{distinction})
		if len(snapshot.Distinctions) != 0 {
			t.Fatalf("SAME at the same timestamp must conservatively suppress DISTINCT: %+v", snapshot.Distinctions)
		}
	})

	t.Run("old distinction stays suppressed after SAME moves away", func(t *testing.T) {
		distinction := annotationDistinction(1, 7, 10, 1)
		sameA := annotationLink(2, 7, 10, RelationSame, LinkAccepted, 2)
		sameB := annotationLink(3, 7, 20, RelationSame, LinkAccepted, 3)
		sameB.SupersedesLinkID = &sameA.ID
		snapshot := resolveAnnotation(
			t,
			nil,
			annotationMembership(7, 20, 3),
			[]UnitConceptLink{sameB, sameA},
			[]UnitConceptDistinction{distinction},
		)
		if len(snapshot.Distinctions) != 0 {
			t.Fatalf("old DISTINCT A must not resurrect after moving SAME to B: %+v", snapshot.Distinctions)
		}
	})

	t.Run("new distinction after correction is effective", func(t *testing.T) {
		oldDistinct := annotationDistinction(1, 7, 10, 1)
		sameA := annotationLink(2, 7, 10, RelationSame, LinkAccepted, 2)
		sameB := annotationLink(3, 7, 20, RelationSame, LinkAccepted, 3)
		sameB.SupersedesLinkID = &sameA.ID
		newDistinct := annotationDistinction(4, 7, 10, 4)
		snapshot := resolveAnnotation(
			t,
			nil,
			annotationMembership(7, 20, 3),
			[]UnitConceptLink{sameB, sameA},
			[]UnitConceptDistinction{oldDistinct, newDistinct},
		)
		if len(snapshot.Distinctions) != 1 || snapshot.Distinctions[0].ID != newDistinct.ID {
			t.Fatalf("new DISTINCT A should re-establish the negative: %+v", snapshot.Distinctions)
		}
	})

	t.Run("multiple distinctions collapse to newest", func(t *testing.T) {
		older := annotationDistinction(1, 7, 10, 1)
		newer := annotationDistinction(2, 7, 10, 2)
		snapshot := resolveAnnotation(t, nil, nil, nil, []UnitConceptDistinction{newer, older})
		if len(snapshot.Distinctions) != 1 || snapshot.Distinctions[0].ID != newer.ID {
			t.Fatalf("newest DISTINCT provenance should win: %+v", snapshot.Distinctions)
		}
	})
}

func TestResolveEffectiveAnnotation_RelationSemantics(t *testing.T) {
	t.Run("later SAME suppresses old relations without resurrection", func(t *testing.T) {
		links := []UnitConceptLink{
			annotationLink(1, 7, 10, RelationRelated, LinkAccepted, 1),
			annotationLink(2, 7, 10, RelationBroader, LinkAccepted, 1),
			annotationLink(3, 7, 10, RelationNarrower, LinkAccepted, 1),
			annotationLink(4, 7, 10, RelationSame, LinkAccepted, 2),
			annotationLink(5, 7, 20, RelationSame, LinkAccepted, 3),
		}
		links[4].SupersedesLinkID = &links[3].ID
		snapshot := resolveAnnotation(t, nil, annotationMembership(7, 20, 5), links, nil)
		if len(snapshot.Relations) != 0 {
			t.Fatalf("old relations to A must not resurrect after SAME moves to B: %+v", snapshot.Relations)
		}
	})

	t.Run("unrelated relation remains effective", func(t *testing.T) {
		sameA := annotationLink(2, 7, 10, RelationSame, LinkAccepted, 2)
		relatedB := annotationLink(1, 7, 20, RelationRelated, LinkAccepted, 1)
		snapshot := resolveAnnotation(t, nil, annotationMembership(7, 10, 2), []UnitConceptLink{sameA, relatedB}, nil)
		if len(snapshot.Relations) != 1 || snapshot.Relations[0].ID != relatedB.ID {
			t.Fatalf("relation to unrelated B should remain effective: %+v", snapshot.Relations)
		}
	})

	t.Run("structurally superseded and legacy rows are not effective", func(t *testing.T) {
		old := annotationLink(1, 7, 10, RelationRelated, LinkAccepted, 1)
		current := annotationLink(2, 7, 10, RelationRelated, LinkAccepted, 2)
		current.SupersedesLinkID = &old.ID
		legacy := annotationLink(3, 7, 20, RelationBroader, LinkSuperseded, 3)
		rejected := annotationLink(4, 7, 30, RelationNarrower, LinkRejected, 4)
		snapshot := resolveAnnotation(t, nil, nil, []UnitConceptLink{old, legacy, rejected, current}, nil)
		if len(snapshot.Relations) != 1 || snapshot.Relations[0].ID != current.ID {
			t.Fatalf("only current accepted relation should survive: %+v", snapshot.Relations)
		}
	})

	t.Run("new relation after SAME is effective and cross-type evidence coexists", func(t *testing.T) {
		same := annotationLink(1, 7, 10, RelationSame, LinkAccepted, 1)
		broader := annotationLink(2, 7, 10, RelationBroader, LinkAccepted, 2)
		related := annotationLink(3, 7, 10, RelationRelated, LinkAccepted, 3)
		snapshot := resolveAnnotation(t, nil, nil, []UnitConceptLink{related, same, broader}, nil)
		if len(snapshot.Relations) != 2 {
			t.Fatalf("later explicit cross-type relations should coexist: %+v", snapshot.Relations)
		}
	})
}

func TestResolveEffectiveAnnotation_RejectSameDoesNotInferDistinct(t *testing.T) {
	accepted := annotationLink(1, 7, 10, RelationSame, LinkAccepted, 1)
	rejected := annotationLink(2, 7, 10, RelationSame, LinkRejected, 2)
	rejected.SupersedesLinkID = &accepted.ID
	snapshot := resolveAnnotation(t, nil, nil, []UnitConceptLink{accepted, rejected}, nil)
	if snapshot.Status != EffectiveAnnotationUnresolved || len(snapshot.Distinctions) != 0 {
		t.Fatalf("RejectSame must not become DISTINCT: %+v", snapshot)
	}
}

func TestResolveEffectiveAnnotation_DeterministicOrdering(t *testing.T) {
	distinctions := []UnitConceptDistinction{
		annotationDistinction(4, 7, 30, 1),
		annotationDistinction(2, 7, 10, 1),
		annotationDistinction(3, 7, 20, 1),
	}
	links := []UnitConceptLink{
		annotationLink(9, 7, 30, RelationRelated, LinkAccepted, 3),
		annotationLink(7, 7, 10, RelationRelated, LinkAccepted, 2),
		annotationLink(8, 7, 10, RelationBroader, LinkAccepted, 1),
	}
	snapshot := resolveAnnotation(t, nil, nil, links, distinctions)

	gotDistinct := []int64{snapshot.Distinctions[0].ConceptID, snapshot.Distinctions[1].ConceptID, snapshot.Distinctions[2].ConceptID}
	if !reflect.DeepEqual(gotDistinct, []int64{10, 20, 30}) {
		t.Fatalf("DISTINCT order = %v", gotDistinct)
	}
	gotRelations := []int64{snapshot.Relations[0].ID, snapshot.Relations[1].ID, snapshot.Relations[2].ID}
	if !reflect.DeepEqual(gotRelations, []int64{8, 7, 9}) {
		t.Fatalf("relation order = %v", gotRelations)
	}
}

func TestResolveEffectiveAnnotation_CorruptMembershipProvenanceFails(t *testing.T) {
	valid := annotationLink(11, 7, 42, RelationSame, LinkAccepted, 1)
	tests := []struct {
		name       string
		membership *CurrentConceptMembership
		links      []UnitConceptLink
	}{
		{name: "missing event", membership: annotationMembership(7, 42, 999), links: []UnitConceptLink{valid}},
		{name: "wrong unit", membership: annotationMembership(8, 42, 11), links: []UnitConceptLink{valid}},
		{name: "wrong concept", membership: annotationMembership(7, 99, 11), links: []UnitConceptLink{valid}},
		{name: "non same", membership: annotationMembership(7, 42, 11), links: []UnitConceptLink{annotationLink(11, 7, 42, RelationRelated, LinkAccepted, 1)}},
		{name: "non accepted", membership: annotationMembership(7, 42, 11), links: []UnitConceptLink{annotationLink(11, 7, 42, RelationSame, LinkRejected, 1)}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := ResolveEffectiveAnnotation(7, nil, tt.membership, tt.links, nil)
			if !errors.Is(err, ErrEffectiveAnnotationCorrupt) {
				t.Fatalf("expected ErrEffectiveAnnotationCorrupt, got %v", err)
			}
		})
	}
}
