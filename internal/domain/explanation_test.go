package domain

import (
	"errors"
	"testing"
)

func sp(s string) *string { return &s }

func bilingualAnalysis() *Analysis {
	return &Analysis{
		ID: 1, EntryID: 2, Version: 1, Category: "grammar",
		Explanation:  "The negation surrounds the verb.",
		Explanations: ExplanationVariants{EN: sp("The negation surrounds the verb."), ZH: sp("否定包围动词。")},
	}
}

func variant(t *testing.T, got EffectiveExplanationVariant, text *string, basis ExplanationBasis) {
	t.Helper()
	if got.Basis != basis || (got.Text == nil) != (text == nil) || (text != nil && *got.Text != *text) {
		t.Fatalf("variant = %v/%v, want %v/%v", deref(got.Text), got.Basis, deref(text), basis)
	}
}

func deref(s *string) string {
	if s == nil {
		return "<nil>"
	}
	return *s
}

// The per-language basis never claims a review that did not happen and never
// presents text predating a correction as current (FLH-095).
func TestResolveEffective_ExplanationBasis(t *testing.T) {
	a := bilingualAnalysis()
	en, zh := a.Explanations.EN, a.Explanations.ZH

	t.Run("unreviewed", func(t *testing.T) {
		e := ResolveEffective(a, nil)
		variant(t, e.Explanations.EN, en, BasisUnreviewed)
		variant(t, e.Explanations.ZH, zh, BasisUnreviewed)
	})
	t.Run("accepted with both shown", func(t *testing.T) {
		e := ResolveEffective(a, &Feedback{ID: 9, Status: FeedbackAccepted, ReviewedLanguages: []ExplanationLanguage{LanguageEnglish, LanguageChinese}})
		variant(t, e.Explanations.EN, en, BasisReviewed)
		variant(t, e.Explanations.ZH, zh, BasisReviewed)
	})
	t.Run("accepted with English only shown does not approve Chinese", func(t *testing.T) {
		e := ResolveEffective(a, &Feedback{ID: 9, Status: FeedbackAccepted, ReviewedLanguages: []ExplanationLanguage{LanguageEnglish}})
		variant(t, e.Explanations.EN, en, BasisReviewed)
		variant(t, e.Explanations.ZH, zh, BasisNotReviewed)
	})
	t.Run("accepted without recorded languages approves no language", func(t *testing.T) {
		e := ResolveEffective(a, &Feedback{ID: 9, Status: FeedbackAccepted})
		variant(t, e.Explanations.EN, en, BasisNotReviewed)
		variant(t, e.Explanations.ZH, zh, BasisNotReviewed)
		if e.Effective.Explanation != a.Explanation {
			t.Fatalf("effective explanation changed: %q", e.Effective.Explanation)
		}
	})
	t.Run("Chinese correction marks English outdated and becomes the effective text", func(t *testing.T) {
		e := ResolveEffective(a, &Feedback{ID: 9, Status: FeedbackCorrected,
			CorrectedExplanations: ExplanationVariants{ZH: sp("「ne … pas」包围变位动词。")},
			ReviewedLanguages:     []ExplanationLanguage{LanguageEnglish, LanguageChinese}})
		variant(t, e.Explanations.ZH, sp("「ne … pas」包围变位动词。"), BasisCorrected)
		variant(t, e.Explanations.EN, en, BasisOutdated)
		if e.Effective.Explanation != "「ne … pas」包围变位动词。" {
			t.Fatalf("language-independent effective explanation = %q, want the correction", e.Effective.Explanation)
		}
		if e.Original.Explanation != a.Explanation || *e.OriginalExplanations.EN != *en {
			t.Fatalf("original changed")
		}
	})
	t.Run("both corrected", func(t *testing.T) {
		e := ResolveEffective(a, &Feedback{ID: 9, Status: FeedbackCorrected,
			CorrectedExplanations: ExplanationVariants{EN: sp("Fixed."), ZH: sp("已更正。")}})
		variant(t, e.Explanations.EN, sp("Fixed."), BasisCorrected)
		variant(t, e.Explanations.ZH, sp("已更正。"), BasisCorrected)
		if e.Effective.Explanation != "Fixed." {
			t.Fatalf("effective = %q, want the English correction", e.Effective.Explanation)
		}
	})
	t.Run("legacy unspecified correction marks both outdated", func(t *testing.T) {
		e := ResolveEffective(a, &Feedback{ID: 9, Status: FeedbackCorrected, CorrectedExplanation: sp("Unspecified-language fix.")})
		variant(t, e.Explanations.EN, en, BasisOutdated)
		variant(t, e.Explanations.ZH, zh, BasisOutdated)
		if e.Effective.Explanation != "Unspecified-language fix." {
			t.Fatalf("effective = %q", e.Effective.Explanation)
		}
	})
	t.Run("category-only correction keeps the shown explanation as reviewed", func(t *testing.T) {
		e := ResolveEffective(a, &Feedback{ID: 9, Status: FeedbackCorrected, CorrectedCategory: sp("morphology"),
			ReviewedLanguages: []ExplanationLanguage{LanguageChinese}})
		variant(t, e.Explanations.EN, en, BasisNotReviewed)
		variant(t, e.Explanations.ZH, zh, BasisReviewed)
	})
	t.Run("rejected has no effective explanation in any language", func(t *testing.T) {
		e := ResolveEffective(a, &Feedback{ID: 9, Status: FeedbackRejected, ReviewedLanguages: []ExplanationLanguage{LanguageEnglish}})
		if e.Effective != nil || e.Explanations != nil {
			t.Fatalf("rejected analysis has effective values: %+v %+v", e.Effective, e.Explanations)
		}
	})
	t.Run("legacy analysis without recorded language", func(t *testing.T) {
		legacy := &Analysis{ID: 1, Category: "grammar", Explanation: "Legacy text."}
		e := ResolveEffective(legacy, &Feedback{ID: 9, Status: FeedbackAccepted})
		variant(t, e.Explanations.EN, nil, BasisUnavailable)
		variant(t, e.Explanations.ZH, nil, BasisUnavailable)
		if e.Effective.Explanation != "Legacy text." {
			t.Fatalf("legacy effective explanation changed")
		}
	})
	t.Run("a person may add the missing Chinese text to a legacy analysis", func(t *testing.T) {
		legacy := &Analysis{ID: 1, Category: "grammar", Explanation: "Legacy text."}
		e := ResolveEffective(legacy, &Feedback{ID: 9, Status: FeedbackCorrected, CorrectedExplanations: ExplanationVariants{ZH: sp("人工中文说明。")}})
		variant(t, e.Explanations.ZH, sp("人工中文说明。"), BasisCorrected)
		variant(t, e.Explanations.EN, nil, BasisUnavailable)
	})
}

func TestNewFeedbackInput_BilingualValidation(t *testing.T) {
	cases := []struct {
		name string
		in   NewFeedbackInput
		ok   bool
	}{
		{"zh-only correction", NewFeedbackInput{Status: FeedbackCorrected, CorrectedExplanations: ExplanationVariants{ZH: sp("中文")}}, true},
		{"unspecified plus language-specific", NewFeedbackInput{Status: FeedbackCorrected, CorrectedExplanation: sp("x"), CorrectedExplanations: ExplanationVariants{EN: sp("y")}}, false},
		{"blank variants are absent", NewFeedbackInput{Status: FeedbackCorrected, CorrectedExplanations: ExplanationVariants{ZH: sp("  ")}}, false},
		{"variant on accept", NewFeedbackInput{Status: FeedbackAccepted, CorrectedExplanations: ExplanationVariants{EN: sp("x")}}, false},
		{"reviewed languages on accept", NewFeedbackInput{Status: FeedbackAccepted, ReviewedLanguages: []ExplanationLanguage{"zh", "en"}}, true},
		{"unknown language", NewFeedbackInput{Status: FeedbackAccepted, ReviewedLanguages: []ExplanationLanguage{"fr"}}, false},
		{"repeated language", NewFeedbackInput{Status: FeedbackAccepted, ReviewedLanguages: []ExplanationLanguage{"en", "en"}}, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			in := c.in
			err := in.Validate()
			if c.ok && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if !c.ok && !errors.Is(err, ErrValidation) {
				t.Fatalf("want ErrValidation, got %v", err)
			}
			if c.ok && len(in.ReviewedLanguages) == 2 && in.ReviewedLanguages[0] != LanguageEnglish {
				t.Fatalf("reviewed languages not in canonical order: %v", in.ReviewedLanguages)
			}
		})
	}
}

func TestVariants_EnglishMustEqualPrimary(t *testing.T) {
	r := AnalysisResult{Category: "grammar", Explanation: " Text. ", Explanations: ExplanationVariants{EN: sp("Text."), ZH: sp(" 文本。 ")}}
	if err := r.Validate(); err != nil {
		t.Fatalf("matching English variant rejected: %v", err)
	}
	if *r.Explanations.ZH != "文本。" {
		t.Fatalf("variant not trimmed: %q", *r.Explanations.ZH)
	}
	bad := AnalysisResult{Category: "grammar", Explanation: "Text.", Explanations: ExplanationVariants{EN: sp("Other.")}}
	if err := bad.Validate(); !errors.Is(err, ErrValidation) {
		t.Fatalf("mismatching English variant accepted: %v", err)
	}
	u := ExtractedUnit{Kind: KindGrammar, Canonical: "c", Statement: "S.", Statements: ExplanationVariants{EN: sp("T.")}, Confidence: 0.5}
	if err := u.Validate(); !errors.Is(err, ErrValidation) {
		t.Fatalf("mismatching English statement accepted: %v", err)
	}
	legacy := ExtractedUnit{Kind: KindGrammar, Canonical: "c", Statement: "S.", Confidence: 0.5}
	if err := legacy.Validate(); err != nil {
		t.Fatalf("unit without variants rejected: %v", err)
	}
}

// Language variants are explanatory content only: they never change the
// candidate Concept identity or its signature (FLH-095).
func TestVariants_DoNotChangeConceptIdentity(t *testing.T) {
	plain := KnowledgeUnit{Kind: KindGrammar, Canonical: "ne … plus", Statement: "Ne … plus marks a stopped habit.", Example: sp("Je ne fume plus.")}
	bilingual := plain
	bilingual.Statements = ExplanationVariants{EN: sp(plain.Statement), ZH: sp("「ne … plus」表示习惯已停止。")}
	a, b := DeriveCandidateIdentity(plain), DeriveCandidateIdentity(bilingual)
	if a.Signature() != b.Signature() || a.Target != b.Target {
		t.Fatalf("identity changed with variants: %q vs %q", a.Signature(), b.Signature())
	}
}
