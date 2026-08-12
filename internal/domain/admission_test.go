package domain

import (
	"errors"
	"testing"
	"time"
)

func TestApplyAdmissionV1_DefaultActive(t *testing.T) {
	units := []ExtractedUnit{
		{Kind: KindGrammar, Canonical: "vouloir", Statement: "a", Confidence: 0.9},
	}
	recs := ApplyAdmissionV1(units)
	if len(recs) != 1 {
		t.Fatalf("got %d recs, want 1", len(recs))
	}
	if recs[0].State != AdmissionActive || recs[0].Reason != ReasonDefaultActive {
		t.Fatalf("expected default active, got %+v", recs[0])
	}
	if recs[0].Ruleset != AdmissionRulesetName {
		t.Fatalf("ruleset = %q, want %q", recs[0].Ruleset, AdmissionRulesetName)
	}
}

func TestApplyAdmissionV1_LowConfidenceNeedsReview(t *testing.T) {
	units := []ExtractedUnit{
		{Kind: KindGrammar, Canonical: "x", Statement: "a", Confidence: 0.1},
	}
	recs := ApplyAdmissionV1(units)
	if recs[0].State != AdmissionNeedsReview || recs[0].Reason != ReasonLowConfidence {
		t.Fatalf("expected needs_review/low_confidence, got %+v", recs[0])
	}
}

func TestApplyAdmissionV1_ExactDuplicateSuppressed(t *testing.T) {
	units := []ExtractedUnit{
		{Kind: KindGrammar, Canonical: "vouloir", Statement: "a", Confidence: 0.9},
		{Kind: KindGrammar, Canonical: "  Vouloir ", Statement: "different statement", Confidence: 0.9}, // same kind+canonical
	}
	recs := ApplyAdmissionV1(units)
	if recs[0].State != AdmissionActive {
		t.Fatalf("first occurrence should stay active, got %+v", recs[0])
	}
	if recs[1].State != AdmissionSuppressed || recs[1].Reason != ReasonExactDuplicate {
		t.Fatalf("second occurrence should be suppressed as exact_duplicate, got %+v", recs[1])
	}
}

func TestApplyAdmissionV1_DuplicateOfSuppressedStillMatchesFirst(t *testing.T) {
	// Three identical units: the first is kept active, the second and third are
	// both suppressed against the first (a suppressed unit does not itself become
	// the "seen" anchor, but the first kept one already is).
	units := []ExtractedUnit{
		{Kind: KindGrammar, Canonical: "x", Statement: "a", Confidence: 0.9},
		{Kind: KindGrammar, Canonical: "x", Statement: "b", Confidence: 0.9},
		{Kind: KindGrammar, Canonical: "x", Statement: "c", Confidence: 0.9},
	}
	recs := ApplyAdmissionV1(units)
	if recs[0].State != AdmissionActive {
		t.Fatalf("first should be active")
	}
	if recs[1].State != AdmissionSuppressed || recs[2].State != AdmissionSuppressed {
		t.Fatalf("second and third should be suppressed, got %+v %+v", recs[1], recs[2])
	}
}

func TestApplyAdmissionV1_DifferentKindNotDuplicate(t *testing.T) {
	units := []ExtractedUnit{
		{Kind: KindGrammar, Canonical: "vouloir", Statement: "a", Confidence: 0.9},
		{Kind: KindVocabulary, Canonical: "vouloir", Statement: "a", Confidence: 0.9},
	}
	recs := ApplyAdmissionV1(units)
	if recs[0].State != AdmissionActive || recs[1].State != AdmissionActive {
		t.Fatalf("different kinds must both be active, got %+v %+v", recs[0], recs[1])
	}
}

func TestNewAdmissionOverrideInput_Validate(t *testing.T) {
	cases := map[string]struct {
		in      NewAdmissionOverrideInput
		wantErr bool
	}{
		"active no reason": {
			in:      NewAdmissionOverrideInput{Decision: HumanAdmitActive},
			wantErr: false,
		},
		"suppressed mastered": {
			in:      NewAdmissionOverrideInput{Decision: HumanAdmitSuppressed, Reason: "mastered"},
			wantErr: false,
		},
		"suppressed ignored": {
			in:      NewAdmissionOverrideInput{Decision: HumanAdmitSuppressed, Reason: "ignored"},
			wantErr: false,
		},
		"suppressed missing reason": {
			in:      NewAdmissionOverrideInput{Decision: HumanAdmitSuppressed},
			wantErr: true,
		},
		"suppressed bad reason": {
			in:      NewAdmissionOverrideInput{Decision: HumanAdmitSuppressed, Reason: "bored"},
			wantErr: true,
		},
		"active with reason rejected": {
			in:      NewAdmissionOverrideInput{Decision: HumanAdmitActive, Reason: "mastered"},
			wantErr: true,
		},
		"invalid decision": {
			in:      NewAdmissionOverrideInput{Decision: HumanAdmissionDecision("needs_review")},
			wantErr: true,
		},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			in := tc.in
			err := in.Validate()
			if tc.wantErr && !errors.Is(err, ErrValidation) {
				t.Fatalf("expected ErrValidation, got %v", err)
			}
			if !tc.wantErr && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
		})
	}
}

func TestResolveAdmission_NoOverrideUsesMachine(t *testing.T) {
	rec := AdmissionRecommendation{Ruleset: AdmissionRulesetName, State: AdmissionNeedsReview, Reason: ReasonLowConfidence}
	got := ResolveAdmission(rec, nil)
	if got.Effective != AdmissionNeedsReview {
		t.Fatalf("effective = %q, want needs_review", got.Effective)
	}
	if got.LatestOverride != nil {
		t.Fatalf("expected no override")
	}
}

func TestResolveAdmission_HumanOverrideWins(t *testing.T) {
	// Machine suppressed, human reactivates: effective must follow the human.
	rec := AdmissionRecommendation{Ruleset: AdmissionRulesetName, State: AdmissionSuppressed, Reason: ReasonExactDuplicate}
	override := &AdmissionOverride{Decision: HumanAdmitActive, CreatedAt: time.Now()}
	got := ResolveAdmission(rec, override)
	if got.Effective != AdmissionActive {
		t.Fatalf("effective = %q, want active (human wins)", got.Effective)
	}
	// The machine recommendation is preserved, not rewritten.
	if got.Recommendation.State != AdmissionSuppressed {
		t.Fatalf("machine recommendation must be preserved, got %q", got.Recommendation.State)
	}
}

func TestResolveAdmission_HumanSuppressesActive(t *testing.T) {
	rec := AdmissionRecommendation{Ruleset: AdmissionRulesetName, State: AdmissionActive, Reason: ReasonDefaultActive}
	override := &AdmissionOverride{Decision: HumanAdmitSuppressed, Reason: HumanReasonMastered, CreatedAt: time.Now()}
	got := ResolveAdmission(rec, override)
	if got.Effective != AdmissionSuppressed {
		t.Fatalf("effective = %q, want suppressed", got.Effective)
	}
}
