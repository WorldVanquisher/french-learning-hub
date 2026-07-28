package domain

import (
	"errors"
	"strings"
	"testing"
)

func TestNewEntryInput_Validate(t *testing.T) {
	tests := []struct {
		name      string
		in        NewEntryInput
		wantErr   bool
		wantInput string // expected normalized OriginalInput on success
	}{
		{
			name:      "valid trims whitespace",
			in:        NewEntryInput{OriginalInput: "  Qu'est-ce que c'est?  ", OriginalContext: "  chat  "},
			wantErr:   false,
			wantInput: "Qu'est-ce que c'est?",
		},
		{
			name:    "empty input is rejected",
			in:      NewEntryInput{OriginalInput: "   "},
			wantErr: true,
		},
		{
			name:    "input over max length is rejected",
			in:      NewEntryInput{OriginalInput: strings.Repeat("a", maxInputLen+1)},
			wantErr: true,
		},
		{
			name:    "context over max length is rejected",
			in:      NewEntryInput{OriginalInput: "ok", OriginalContext: strings.Repeat("a", maxInputLen+1)},
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
			if tc.in.OriginalInput != tc.wantInput {
				t.Fatalf("OriginalInput = %q, want %q", tc.in.OriginalInput, tc.wantInput)
			}
		})
	}
}
