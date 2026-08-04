package domain

import (
	"errors"
	"testing"
)

func TestValidLearningRecordState(t *testing.T) {
	valid := []LearningRecordState{
		LearningRecordUnanalyzed, LearningRecordUnreviewed,
		LearningRecordAccepted, LearningRecordCorrected, LearningRecordRejected,
	}
	for _, s := range valid {
		if !ValidLearningRecordState(s) {
			t.Errorf("%q should be valid", s)
		}
	}
	for _, s := range []LearningRecordState{"", "bogus", "Accepted", "UNANALYZED"} {
		if ValidLearningRecordState(s) {
			t.Errorf("%q should be invalid", s)
		}
	}
}

func TestLearningRecordStates_IsCopy(t *testing.T) {
	a := LearningRecordStates()
	if len(a) != 5 {
		t.Fatalf("expected 5 states, got %d", len(a))
	}
	a[0] = "mutated"
	b := LearningRecordStates()
	if b[0] == "mutated" {
		t.Fatal("LearningRecordStates must return a copy, not the backing slice")
	}
}

func TestStateFromResolution(t *testing.T) {
	cases := []struct {
		in   Resolution
		want LearningRecordState
	}{
		{ResolutionUnreviewed, LearningRecordUnreviewed},
		{ResolutionAccepted, LearningRecordAccepted},
		{ResolutionCorrected, LearningRecordCorrected},
		{ResolutionRejected, LearningRecordRejected},
	}
	for _, tc := range cases {
		if got := StateFromResolution(tc.in); got != tc.want {
			t.Errorf("StateFromResolution(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
	// It must never return unanalyzed, and an unknown resolution yields "".
	if got := StateFromResolution(Resolution("nonsense")); got != "" {
		t.Errorf("unknown resolution should map to empty state, got %q", got)
	}
	for _, tc := range cases {
		if StateFromResolution(tc.in) == LearningRecordUnanalyzed {
			t.Errorf("StateFromResolution must never return unanalyzed")
		}
	}
}

func TestLearningRecordQuery_Normalize_LimitClamping(t *testing.T) {
	const def, max = 50, 200
	cases := []struct {
		name string
		in   int
		want int
	}{
		{"zero uses default", 0, def},
		{"negative uses default", -5, def},
		{"within range kept", 120, 120},
		{"above max clamped", 5000, max},
		{"exactly max kept", max, max},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			q := LearningRecordQuery{Limit: tc.in}
			if err := q.Normalize(def, max); err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if q.Limit != tc.want {
				t.Fatalf("limit = %d, want %d", q.Limit, tc.want)
			}
		})
	}
}

func TestLearningRecordQuery_Normalize_StateAndCategory(t *testing.T) {
	state := LearningRecordState("  ACCEPTED ")
	cat := Category(" Grammar ")
	q := LearningRecordQuery{State: &state, Category: &cat}
	if err := q.Normalize(50, 200); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if *q.State != LearningRecordAccepted {
		t.Fatalf("state = %q, want accepted (trimmed+lowercased)", *q.State)
	}
	if *q.Category != "grammar" {
		t.Fatalf("category = %q, want grammar (trimmed+lowercased)", *q.Category)
	}
}

func TestLearningRecordQuery_Normalize_InvalidState(t *testing.T) {
	state := LearningRecordState("maybe")
	q := LearningRecordQuery{State: &state}
	err := q.Normalize(50, 200)
	if !errors.Is(err, ErrValidation) {
		t.Fatalf("expected ErrValidation, got %v", err)
	}
}

func TestLearningRecordQuery_Normalize_InvalidCategory(t *testing.T) {
	cat := Category("wingdings")
	q := LearningRecordQuery{Category: &cat}
	err := q.Normalize(50, 200)
	if !errors.Is(err, ErrValidation) {
		t.Fatalf("expected ErrValidation, got %v", err)
	}
}

func TestLearningRecordQuery_Normalize_AnalyzerTrimmedExact(t *testing.T) {
	// A padded analyzer is trimmed but not otherwise altered (exact match).
	an := "  openai:gpt-x:fr_l2_taxonomy_v1  "
	q := LearningRecordQuery{Analyzer: &an}
	if err := q.Normalize(50, 200); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if q.Analyzer == nil || *q.Analyzer != "openai:gpt-x:fr_l2_taxonomy_v1" {
		t.Fatalf("analyzer = %v, want trimmed exact", q.Analyzer)
	}

	// A whitespace-only analyzer becomes "no filter".
	blank := "   "
	q = LearningRecordQuery{Analyzer: &blank}
	if err := q.Normalize(50, 200); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if q.Analyzer != nil {
		t.Fatalf("blank analyzer should become nil, got %v", *q.Analyzer)
	}
}

func TestLearningRecordQuery_Normalize_InvalidCursor(t *testing.T) {
	for _, bad := range []int64{0, -1, -100} {
		v := bad
		q := LearningRecordQuery{BeforeEntryID: &v}
		if err := q.Normalize(50, 200); !errors.Is(err, ErrValidation) {
			t.Fatalf("before_entry_id=%d should be ErrValidation, got %v", bad, err)
		}
	}
	// A positive cursor is accepted and preserved.
	good := int64(5)
	q := LearningRecordQuery{BeforeEntryID: &good}
	if err := q.Normalize(50, 200); err != nil {
		t.Fatalf("positive cursor should be valid, got %v", err)
	}
	if q.BeforeEntryID == nil || *q.BeforeEntryID != 5 {
		t.Fatalf("cursor mangled: %v", q.BeforeEntryID)
	}
}

func TestNewValidationError_IsErrValidation(t *testing.T) {
	err := NewValidationError("bad thing")
	if !errors.Is(err, ErrValidation) {
		t.Fatalf("NewValidationError should wrap ErrValidation, got %v", err)
	}
	if err.Error() == "" {
		t.Fatal("error message should not be empty")
	}
}
