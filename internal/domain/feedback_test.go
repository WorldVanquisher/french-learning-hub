package domain

import (
	"errors"
	"strings"
	"testing"
)

func strptr(s string) *string { return &s }

func TestNewFeedbackInput_Validate(t *testing.T) {
	tests := []struct {
		name    string
		in      NewFeedbackInput
		wantErr bool
	}{
		{
			name: "accepted without corrections",
			in:   NewFeedbackInput{Status: FeedbackAccepted},
		},
		{
			name: "rejected with a note",
			in:   NewFeedbackInput{Status: FeedbackRejected, UserNote: "not quite right"},
		},
		{
			name: "corrected with both fields",
			in:   NewFeedbackInput{Status: FeedbackCorrected, CorrectedCategory: strptr("grammar"), CorrectedExplanation: strptr("verb tense")},
		},
		{
			name:    "unknown status",
			in:      NewFeedbackInput{Status: FeedbackStatus("maybe")},
			wantErr: true,
		},
		{
			name:    "empty status",
			in:      NewFeedbackInput{Status: ""},
			wantErr: true,
		},
		{
			name: "corrected with only explanation",
			in:   NewFeedbackInput{Status: FeedbackCorrected, CorrectedExplanation: strptr("verb tense")},
		},
		{
			name: "corrected with only category",
			in:   NewFeedbackInput{Status: FeedbackCorrected, CorrectedCategory: strptr("grammar")},
		},
		{
			name: "corrected with blank category but real explanation",
			in:   NewFeedbackInput{Status: FeedbackCorrected, CorrectedCategory: strptr("   "), CorrectedExplanation: strptr("x")},
		},
		{
			name:    "corrected with neither field",
			in:      NewFeedbackInput{Status: FeedbackCorrected},
			wantErr: true,
		},
		{
			name:    "corrected with both fields blank",
			in:      NewFeedbackInput{Status: FeedbackCorrected, CorrectedCategory: strptr("   "), CorrectedExplanation: strptr("  ")},
			wantErr: true,
		},
		{
			name:    "accepted with stray correction",
			in:      NewFeedbackInput{Status: FeedbackAccepted, CorrectedCategory: strptr("grammar")},
			wantErr: true,
		},
		{
			name:    "rejected with stray explanation",
			in:      NewFeedbackInput{Status: FeedbackRejected, CorrectedExplanation: strptr("x")},
			wantErr: true,
		},
		{
			name:    "user_note too long",
			in:      NewFeedbackInput{Status: FeedbackAccepted, UserNote: strings.Repeat("a", maxUserNoteLen+1)},
			wantErr: true,
		},
		{
			name:    "corrected_category too long",
			in:      NewFeedbackInput{Status: FeedbackCorrected, CorrectedCategory: strptr(strings.Repeat("a", 101)), CorrectedExplanation: strptr("x")},
			wantErr: true,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.in.Validate()
			if tc.wantErr {
				if err == nil {
					t.Fatal("expected error, got nil")
				}
				if !errors.Is(err, ErrValidation) {
					t.Fatalf("error should wrap ErrValidation, got %v", err)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
		})
	}
}

func TestNewFeedbackInput_Validate_TrimsAndNormalizes(t *testing.T) {
	in := NewFeedbackInput{
		Status:               FeedbackCorrected,
		CorrectedCategory:    strptr("  grammar  "),
		CorrectedExplanation: strptr("  wrong tense  "),
		UserNote:             "  see note  ",
	}
	if err := in.Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if in.CorrectedCategory == nil || *in.CorrectedCategory != "grammar" {
		t.Fatalf("CorrectedCategory not trimmed: %v", in.CorrectedCategory)
	}
	if in.CorrectedExplanation == nil || *in.CorrectedExplanation != "wrong tense" {
		t.Fatalf("CorrectedExplanation not trimmed: %v", in.CorrectedExplanation)
	}
	if in.UserNote != "see note" {
		t.Fatalf("UserNote not trimmed: %q", in.UserNote)
	}
}

func TestNewFeedbackInput_Validate_EmptyOptionalBecomesNil(t *testing.T) {
	// An empty (whitespace) corrected field on a non-corrected status should
	// normalize to nil and therefore be allowed.
	in := NewFeedbackInput{Status: FeedbackAccepted, CorrectedCategory: strptr("   ")}
	if err := in.Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if in.CorrectedCategory != nil {
		t.Fatalf("expected nil after normalization, got %v", in.CorrectedCategory)
	}
}
