package domain

import (
	"errors"
	"strings"
	"testing"
)

func TestAnalysisResult_Validate(t *testing.T) {
	valid := func() AnalysisResult {
		return AnalysisResult{
			Category:    "vocabulary",
			Explanation: "means 'hello'",
			Confidence:  0.7,
			Uncertainty: "",
		}
	}

	tests := []struct {
		name    string
		mutate  func(r *AnalysisResult)
		wantErr bool
	}{
		{name: "valid", mutate: func(*AnalysisResult) {}, wantErr: false},
		{name: "trims and keeps valid", mutate: func(r *AnalysisResult) { r.Category = "  grammar  " }, wantErr: false},
		{name: "normalizes case", mutate: func(r *AnalysisResult) { r.Category = "Grammar" }, wantErr: false},
		{name: "empty category", mutate: func(r *AnalysisResult) { r.Category = "  " }, wantErr: true},
		{name: "out-of-taxonomy category", mutate: func(r *AnalysisResult) { r.Category = "conjugation" }, wantErr: true},
		{name: "legacy question category rejected", mutate: func(r *AnalysisResult) { r.Category = "question" }, wantErr: true},
		{name: "legacy phrase category rejected", mutate: func(r *AnalysisResult) { r.Category = "phrase" }, wantErr: true},
		{name: "empty explanation", mutate: func(r *AnalysisResult) { r.Explanation = "" }, wantErr: true},
		{name: "explanation too long", mutate: func(r *AnalysisResult) { r.Explanation = strings.Repeat("a", maxExplanationLen+1) }, wantErr: true},
		{name: "confidence below zero", mutate: func(r *AnalysisResult) { r.Confidence = -0.1 }, wantErr: true},
		{name: "confidence above one", mutate: func(r *AnalysisResult) { r.Confidence = 1.1 }, wantErr: true},
		{name: "confidence at bounds ok", mutate: func(r *AnalysisResult) { r.Confidence = 1 }, wantErr: false},
		{name: "uncertainty too long", mutate: func(r *AnalysisResult) { r.Uncertainty = strings.Repeat("a", maxUncertaintyLen+1) }, wantErr: true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			r := valid()
			tc.mutate(&r)
			err := r.Validate()
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

func TestAnalysisResult_Validate_TrimsAndLowercasesCategory(t *testing.T) {
	r := AnalysisResult{Category: "  Grammar  ", Explanation: "  note  ", Confidence: 0.5, Uncertainty: "  caveat  "}
	if err := r.Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if r.Category != "grammar" || r.Explanation != "note" || r.Uncertainty != "caveat" {
		t.Fatalf("fields not normalized: %+v", r)
	}
}

func TestTaxonomy_CategoriesAllValid(t *testing.T) {
	cats := Categories()
	if len(cats) != 11 {
		t.Fatalf("expected 11 taxonomy categories, got %d", len(cats))
	}
	for _, c := range cats {
		if !ValidCategory(c) {
			t.Errorf("Categories() returned %q which ValidCategory rejects", c)
		}
	}
	if ValidCategory("question") || ValidCategory("phrase") {
		t.Error("legacy categories must not be valid under fr_l2_taxonomy_v1")
	}
}
