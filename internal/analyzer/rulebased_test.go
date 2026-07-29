package analyzer

import (
	"context"
	"testing"

	"french-learning-app/internal/domain"
)

func TestRuleBased_Analyze_Classification(t *testing.T) {
	a := NewRuleBased()
	ctx := context.Background()

	tests := []struct {
		name         string
		input        string
		wantCategory string
	}{
		{name: "comprehension", input: "Qu'est-ce que c'est?", wantCategory: domain.CategoryComprehension},
		{name: "grammar", input: "Je suis fatigué", wantCategory: domain.CategoryGrammar},
		{name: "vocabulary", input: "bonjour", wantCategory: domain.CategoryVocabulary},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			res, err := a.Analyze(ctx, &domain.Entry{OriginalInput: tc.input})
			if err != nil {
				t.Fatalf("Analyze: %v", err)
			}
			if res.Category != tc.wantCategory {
				t.Fatalf("Category = %q, want %q", res.Category, tc.wantCategory)
			}
			// Output must always pass domain validation.
			if err := res.Validate(); err != nil {
				t.Fatalf("result failed validation: %v", err)
			}
		})
	}
}

func TestRuleBased_Analyze_Deterministic(t *testing.T) {
	a := NewRuleBased()
	entry := &domain.Entry{OriginalInput: "Je suis fatigué"}

	first, err := a.Analyze(context.Background(), entry)
	if err != nil {
		t.Fatalf("Analyze: %v", err)
	}
	second, err := a.Analyze(context.Background(), entry)
	if err != nil {
		t.Fatalf("Analyze: %v", err)
	}
	if first != second {
		t.Fatalf("analyzer not deterministic: %+v vs %+v", first, second)
	}
}

func TestRuleBased_Analyze_NonAlphabetic(t *testing.T) {
	a := NewRuleBased()
	res, err := a.Analyze(context.Background(), &domain.Entry{OriginalInput: "123 456"})
	if err != nil {
		t.Fatalf("Analyze: %v", err)
	}
	if res.Category != domain.CategoryOther {
		t.Fatalf("expected category %q for non-alphabetic input, got %q", domain.CategoryOther, res.Category)
	}
	if res.Confidence != 0.3 {
		t.Fatalf("expected low confidence 0.3 for non-alphabetic input, got %v", res.Confidence)
	}
	if err := res.Validate(); err != nil {
		t.Fatalf("result failed validation: %v", err)
	}
}

func TestRuleBased_Name(t *testing.T) {
	if got := NewRuleBased().Name(); got != "rule-based" {
		t.Fatalf("Name() = %q, want %q", got, "rule-based")
	}
}
