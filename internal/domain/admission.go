package domain

import (
	"context"
	"errors"
	"strings"
	"time"
)

// ErrNotEligible is returned when an entry is not in an eligible state for
// knowledge extraction. The eligible states are unreviewed, accepted, and
// corrected; an unanalyzed entry or a rejected current analysis is not eligible.
// It is distinct from ErrValidation (the request itself is well-formed) and from
// ErrNotFound (the entry exists).
var ErrNotEligible = errors.New("entry not eligible for extraction")

// AdmissionRulesetName identifies the single fixed admission ruleset implemented
// in this milestone. The ruleset does not learn, does not rewrite itself, and
// does not change its own thresholds; it is a fixed, versioned policy. Its name
// is recorded with every machine recommendation so a future milestone could
// analyze machine-vs-human decisions per ruleset version.
const AdmissionRulesetName = "knowledge_admission_v1"

// admissionNeedsReviewConfidence is the confidence threshold below which
// knowledge_admission_v1 routes a unit to needs_review instead of active. It is a
// conservative, deliberately un-calibrated heuristic: the extractor's confidence
// is its own belief that a unit is a genuine learning objective, not a measured
// probability, so this threshold only decides "auto-admit vs. ask a human". It is
// a single named constant so it is easy to change in one place; it is not claimed
// to be tuned or validated.
const admissionNeedsReviewConfidence = 0.5

// MachineAdmissionState is the machine's admission classification for a unit.
type MachineAdmissionState string

const (
	// AdmissionActive means the unit should currently enter the active learning
	// pool.
	AdmissionActive MachineAdmissionState = "active"
	// AdmissionSuppressed means the unit should not currently enter the pool
	// (e.g. an exact duplicate of another unit in the same extraction).
	AdmissionSuppressed MachineAdmissionState = "suppressed"
	// AdmissionNeedsReview means the machine is not confident enough to decide
	// and defers to a human, rather than suppressing.
	AdmissionNeedsReview MachineAdmissionState = "needs_review"
)

// Machine recommendation reasons. These are stable identifiers, not prose.
const (
	// ReasonDefaultActive: a valid unit admitted by the conservative default.
	ReasonDefaultActive = "default_active"
	// ReasonExactDuplicate: same kind + normalized canonical as an earlier unit
	// in the same extraction. The unit is suppressed, not deleted; it still
	// exists historically.
	ReasonExactDuplicate = "exact_duplicate"
	// ReasonLowConfidence: confidence below the needs-review threshold.
	ReasonLowConfidence = "low_confidence"
)

// AdmissionRecommendation is the machine's non-authoritative recommendation for
// one unit, produced by a named, versioned ruleset. It never has irreversible
// authority: a human can override it, and the override wins when deriving the
// effective state.
type AdmissionRecommendation struct {
	Ruleset string
	State   MachineAdmissionState
	Reason  string
}

// ApplyAdmissionV1 runs the fixed knowledge_admission_v1 ruleset over the units
// of a single extraction, in output order, returning one recommendation per unit
// aligned by index. It is pure and deterministic.
//
// Rules, in priority order:
//  1. Exact duplicate — if an earlier unit in this same extraction has the same
//     KnowledgeKind and the same normalized canonical (trim + lowercase +
//     collapsed whitespace; accents preserved), the later unit is SUPPRESSED with
//     reason exact_duplicate. The first occurrence is kept. This is exact textual
//     matching only: no embeddings, vectors, stemming, or semantic similarity.
//  2. Low confidence — a non-duplicate unit whose confidence is below the
//     conservative needs-review threshold is routed to NEEDS_REVIEW (never
//     silently suppressed) so a human can decide.
//  3. Default active — any other valid unit defaults to ACTIVE.
func ApplyAdmissionV1(units []ExtractedUnit) []AdmissionRecommendation {
	recs := make([]AdmissionRecommendation, len(units))
	seen := make(map[string]struct{}, len(units))
	for i := range units {
		key := string(units[i].Kind) + "\x00" + NormalizeCanonical(units[i].Canonical)
		switch {
		case dupSeen(seen, key):
			recs[i] = AdmissionRecommendation{
				Ruleset: AdmissionRulesetName,
				State:   AdmissionSuppressed,
				Reason:  ReasonExactDuplicate,
			}
		case units[i].Confidence < admissionNeedsReviewConfidence:
			recs[i] = AdmissionRecommendation{
				Ruleset: AdmissionRulesetName,
				State:   AdmissionNeedsReview,
				Reason:  ReasonLowConfidence,
			}
			seen[key] = struct{}{}
		default:
			recs[i] = AdmissionRecommendation{
				Ruleset: AdmissionRulesetName,
				State:   AdmissionActive,
				Reason:  ReasonDefaultActive,
			}
			seen[key] = struct{}{}
		}
	}
	return recs
}

// dupSeen reports whether key was already recorded. A suppressed duplicate does
// not itself become a "seen" key (only kept units do), so a run of three
// identical units keeps the first and suppresses the second and third against
// that first one.
func dupSeen(seen map[string]struct{}, key string) bool {
	_, ok := seen[key]
	return ok
}

// HumanAdmissionDecision is the direction of a human override. A human may move a
// unit into or out of the active pool; they cannot set the machine-only
// needs_review state (that state expresses machine uncertainty, which a human
// decision resolves).
type HumanAdmissionDecision string

const (
	// HumanAdmitActive keeps or reactivates a unit in the active pool (e.g. the
	// human judges it a distinct, worthwhile objective).
	HumanAdmitActive HumanAdmissionDecision = "active"
	// HumanAdmitSuppressed removes a unit from the active pool (e.g. already
	// mastered, or the learner does not want to study it).
	HumanAdmitSuppressed HumanAdmissionDecision = "suppressed"
)

func (d HumanAdmissionDecision) valid() bool {
	return d == HumanAdmitActive || d == HumanAdmitSuppressed
}

// Human suppression reasons. A suppression must carry one of these; an
// activation does not require a reason.
const (
	// HumanReasonMastered: the learner already knows this.
	HumanReasonMastered = "mastered"
	// HumanReasonIgnored: the learner does not want to study this.
	HumanReasonIgnored = "ignored"
	// HumanReasonOther: any other reason (optionally elaborated in the note).
	HumanReasonOther = "other"
)

// maxAdmissionNoteLen bounds the optional free-form override note.
const maxAdmissionNoteLen = 2000

// AdmissionOverride is an immutable, append-only record of a human decision about
// one unit's admission. Overrides never mutate or delete the machine
// recommendation; the full history of overrides is preserved, and the latest one
// determines the effective state.
type AdmissionOverride struct {
	ID        int64
	UnitID    int64
	Decision  HumanAdmissionDecision
	Reason    string
	Note      string
	CreatedAt time.Time
}

// NewAdmissionOverrideInput carries the fields a caller supplies when adding an
// override.
type NewAdmissionOverrideInput struct {
	Decision HumanAdmissionDecision
	Reason   string
	Note     string
}

// Validate normalizes and checks an override input, returning a wrapped
// ErrValidation on failure. A suppression requires a recognized reason
// (mastered, ignored, other). An activation must not carry a suppression reason,
// so an activation never smuggles a "mastered" tag. The note is optional and
// bounded.
func (in *NewAdmissionOverrideInput) Validate() error {
	if !in.Decision.valid() {
		return errWrap("decision must be one of: active, suppressed")
	}

	in.Reason = strings.TrimSpace(strings.ToLower(in.Reason))
	in.Note = strings.TrimSpace(in.Note)
	if len(in.Note) > maxAdmissionNoteLen {
		return errWrap("note exceeds maximum length")
	}

	if in.Decision == HumanAdmitSuppressed {
		switch in.Reason {
		case HumanReasonMastered, HumanReasonIgnored, HumanReasonOther:
		default:
			return errWrap("reason must be one of: mastered, ignored, other when suppressing")
		}
	} else {
		// Activation: no suppression reason is allowed.
		if in.Reason != "" {
			return errWrap("reason is only allowed when suppressing")
		}
	}
	return nil
}

// AdmissionState is the resolved admission view for one unit: the immutable
// machine recommendation, the latest human override (nil if none), and the
// derived effective state. It is assembled on read; the effective state is never
// stored, so history is preserved and the human decision always wins on read.
type AdmissionState struct {
	Recommendation AdmissionRecommendation
	LatestOverride *AdmissionOverride
	// Effective is the current admission state after applying any human override
	// on top of the machine recommendation.
	Effective MachineAdmissionState
}

// ResolveAdmission derives the effective admission state for one unit from its
// machine recommendation and the latest human override. The human decision wins:
// when an override exists, the effective state is exactly the override's
// direction (active or suppressed). With no override, the effective state is the
// machine recommendation's state (including needs_review, which stays pending
// until a human decides). It is pure and never mutates its inputs.
func ResolveAdmission(rec AdmissionRecommendation, latest *AdmissionOverride) AdmissionState {
	state := AdmissionState{Recommendation: rec, LatestOverride: latest}
	if latest != nil {
		state.Effective = MachineAdmissionState(latest.Decision)
	} else {
		state.Effective = rec.State
	}
	return state
}

// AdmissionOverrideRepository is the persistence boundary for human admission
// overrides. Implementations live in the storage layer and keep all SQL there.
type AdmissionOverrideRepository interface {
	// Create appends an override for a unit. Returns ErrNotFound if the unit does
	// not exist.
	Create(ctx context.Context, unitID int64, in NewAdmissionOverrideInput) (*AdmissionOverride, error)
	// ListByUnit returns every override for a unit, oldest first. Returns
	// ErrNotFound if the unit does not exist (distinct from a unit with no
	// overrides yet).
	ListByUnit(ctx context.Context, unitID int64) ([]*AdmissionOverride, error)
	// GetAdmission returns the resolved admission state (machine recommendation +
	// latest override + effective state) for a unit. Returns ErrNotFound if the
	// unit does not exist.
	GetAdmission(ctx context.Context, unitID int64) (*AdmissionState, error)
}
