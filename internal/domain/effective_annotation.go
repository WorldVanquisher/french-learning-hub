package domain

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"
)

// ErrEffectiveAnnotationCorrupt reports internally inconsistent persisted
// annotation facts. Effective projections must fail closed rather than guessing
// or silently repairing contradictory provenance.
var ErrEffectiveAnnotationCorrupt = errors.New("corrupt effective annotation state")

// EffectiveAnnotationStatus is the current unit-level annotation state derived
// from the latest INVALID judgment and the CURRENT SAME membership projection.
type EffectiveAnnotationStatus string

const (
	EffectiveAnnotationInvalid    EffectiveAnnotationStatus = "invalid"
	EffectiveAnnotationResolved   EffectiveAnnotationStatus = "resolved"
	EffectiveAnnotationUnresolved EffectiveAnnotationStatus = "unresolved"
)

// EffectiveSame combines the authoritative CURRENT SAME projection row with the
// immutable accepted SAME event it references. The event preserves source,
// resolver, evidence, score, and timestamp for later audit and eligibility rules.
type EffectiveSame struct {
	Membership CurrentConceptMembership
	Decision   UnitConceptLink
}

// EffectiveAnnotationSnapshot is the deterministic current annotation read model
// for one KnowledgeUnit. It is derived on read and never persisted. Historical
// records remain queryable separately even when they are suppressed here.
type EffectiveAnnotationSnapshot struct {
	UnitID int64
	Status EffectiveAnnotationStatus

	LatestUnitJudgment *UnitResolutionJudgment
	CurrentSame        *EffectiveSame

	Distinctions []UnitConceptDistinction
	Relations    []UnitConceptLink
}

// EffectiveAnnotationRepository retrieves persisted facts needed to derive one
// snapshot. Implementations perform no effective-semantics calculations.
type EffectiveAnnotationRepository interface {
	LatestUnitJudgment(ctx context.Context, unitID int64) (*UnitResolutionJudgment, error)
	GetCurrentMembership(ctx context.Context, unitID int64) (*CurrentConceptMembership, error)
	ListUnitConceptLinks(ctx context.Context, unitID int64) ([]UnitConceptLink, error)
	ListDistinctions(ctx context.Context, unitID int64) ([]UnitConceptDistinction, error)
}

// ResolveEffectiveAnnotation derives the effective snapshot from persisted facts.
// Input ordering is irrelevant. CURRENT SAME comes exclusively from membership;
// accepted SAME history is consulted only to stop older contradictory DISTINCT or
// relation evidence from becoming effective again.
func ResolveEffectiveAnnotation(
	unitID int64,
	latest *UnitResolutionJudgment,
	membership *CurrentConceptMembership,
	links []UnitConceptLink,
	distinctions []UnitConceptDistinction,
) (EffectiveAnnotationSnapshot, error) {
	snapshot := EffectiveAnnotationSnapshot{
		UnitID:       unitID,
		Status:       EffectiveAnnotationUnresolved,
		Distinctions: make([]UnitConceptDistinction, 0),
		Relations:    make([]UnitConceptLink, 0),
	}

	if latest != nil {
		if latest.UnitID != unitID {
			return snapshot, corruptAnnotation("latest unit judgment belongs to unit %d, not %d", latest.UnitID, unitID)
		}
		judgment := *latest
		snapshot.LatestUnitJudgment = &judgment
	}

	linksByID := make(map[int64]UnitConceptLink, len(links))
	supersededLinkIDs := make(map[int64]struct{})
	affirmativeSameByConcept := make(map[int64][]UnitConceptLink)
	for _, link := range links {
		if link.UnitID != unitID {
			return snapshot, corruptAnnotation("link %d belongs to unit %d, not %d", link.ID, link.UnitID, unitID)
		}
		if _, duplicate := linksByID[link.ID]; duplicate {
			return snapshot, corruptAnnotation("duplicate link id %d", link.ID)
		}
		linksByID[link.ID] = link
		if link.SupersedesLinkID != nil {
			supersededLinkIDs[*link.SupersedesLinkID] = struct{}{}
		}
		if isAffirmativeSameDecision(link) {
			affirmativeSameByConcept[link.ConceptID] = append(affirmativeSameByConcept[link.ConceptID], link)
		}
	}

	var effectiveSame *EffectiveSame
	if membership != nil {
		if membership.UnitID != unitID {
			return snapshot, corruptAnnotation("current membership belongs to unit %d, not %d", membership.UnitID, unitID)
		}
		decision, ok := linksByID[membership.LinkID]
		if !ok {
			return snapshot, corruptAnnotation("current membership references missing link %d", membership.LinkID)
		}
		if decision.UnitID != membership.UnitID ||
			decision.ConceptID != membership.ConceptID ||
			decision.Relation != RelationSame ||
			decision.Status != LinkAccepted {
			return snapshot, corruptAnnotation("current membership link %d is not a matching accepted SAME event", membership.LinkID)
		}
		effectiveSame = &EffectiveSame{Membership: *membership, Decision: decision}
	}

	// INVALID is the dominant interpretation. It suppresses all pair-level output,
	// including a projection row that should already have been cleared atomically.
	if EffectiveUnitInvalid(snapshot.LatestUnitJudgment) {
		snapshot.Status = EffectiveAnnotationInvalid
		return snapshot, nil
	}

	if effectiveSame != nil {
		snapshot.Status = EffectiveAnnotationResolved
		snapshot.CurrentSame = effectiveSame
	}

	currentSameConceptID := int64(0)
	if effectiveSame != nil {
		currentSameConceptID = effectiveSame.Membership.ConceptID
	}

	// Collapse repeated DISTINCT evidence to the newest event per Concept before
	// applying SAME contradiction rules. IDs break ties within this one table.
	newestDistinction := make(map[int64]UnitConceptDistinction)
	for _, distinction := range distinctions {
		if distinction.UnitID != unitID {
			return snapshot, corruptAnnotation("distinction %d belongs to unit %d, not %d", distinction.ID, distinction.UnitID, unitID)
		}
		prior, exists := newestDistinction[distinction.ConceptID]
		if !exists || eventAfter(distinction.CreatedAt, distinction.ID, prior.CreatedAt, prior.ID) {
			newestDistinction[distinction.ConceptID] = distinction
		}
	}
	for conceptID, distinction := range newestDistinction {
		if conceptID == currentSameConceptID {
			continue
		}
		if sameAtOrAfterDistinction(affirmativeSameByConcept[conceptID], distinction) {
			continue
		}
		snapshot.Distinctions = append(snapshot.Distinctions, distinction)
	}
	sort.Slice(snapshot.Distinctions, func(i, j int) bool {
		if snapshot.Distinctions[i].ConceptID != snapshot.Distinctions[j].ConceptID {
			return snapshot.Distinctions[i].ConceptID < snapshot.Distinctions[j].ConceptID
		}
		return snapshot.Distinctions[i].ID < snapshot.Distinctions[j].ID
	})

	for _, link := range links {
		if !isNonSameRelation(link.Relation) || link.Status != LinkAccepted {
			continue
		}
		if _, superseded := supersededLinkIDs[link.ID]; superseded {
			continue
		}
		if link.ConceptID == currentSameConceptID {
			continue
		}
		if sameAtOrAfterLink(affirmativeSameByConcept[link.ConceptID], link) {
			continue
		}
		snapshot.Relations = append(snapshot.Relations, link)
	}
	sort.Slice(snapshot.Relations, func(i, j int) bool {
		left, right := snapshot.Relations[i], snapshot.Relations[j]
		if left.ConceptID != right.ConceptID {
			return left.ConceptID < right.ConceptID
		}
		if left.Relation != right.Relation {
			return left.Relation < right.Relation
		}
		return left.ID < right.ID
	})

	return snapshot, nil
}

// isAffirmativeSameDecision includes accepted SAME events and legacy
// status=superseded SAME rows. The legacy status means the row was formerly an
// accepted SAME that migration 006 rewrote; retaining it as contradictory history
// prevents older negative/relation evidence from resurrecting after upgrades.
func isAffirmativeSameDecision(link UnitConceptLink) bool {
	return link.Relation == RelationSame && (link.Status == LinkAccepted || link.Status == LinkSuperseded)
}

func isNonSameRelation(relation ConceptRelation) bool {
	return relation == RelationBroader || relation == RelationNarrower || relation == RelationRelated
}

// Cross-table DISTINCT/SAME ordering has no shared sequence. Equal timestamps are
// therefore intentionally conservative: SAME wins.
func sameAtOrAfterDistinction(sameLinks []UnitConceptLink, distinction UnitConceptDistinction) bool {
	for _, same := range sameLinks {
		if same.CreatedAt.After(distinction.CreatedAt) || same.CreatedAt.Equal(distinction.CreatedAt) {
			return true
		}
	}
	return false
}

// Relation and SAME events share one table and one ID sequence, so an ID breaks
// equal-timestamp ties without inventing ordering.
func sameAtOrAfterLink(sameLinks []UnitConceptLink, relation UnitConceptLink) bool {
	for _, same := range sameLinks {
		if eventAfter(same.CreatedAt, same.ID, relation.CreatedAt, relation.ID) ||
			(same.CreatedAt.Equal(relation.CreatedAt) && same.ID == relation.ID) {
			return true
		}
	}
	return false
}

func eventAfter(leftTime time.Time, leftID int64, rightTime time.Time, rightID int64) bool {
	return leftTime.After(rightTime) || (leftTime.Equal(rightTime) && leftID > rightID)
}

func corruptAnnotation(format string, args ...any) error {
	return fmt.Errorf("%w: %s", ErrEffectiveAnnotationCorrupt, fmt.Sprintf(format, args...))
}
