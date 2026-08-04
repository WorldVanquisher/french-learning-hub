package analyzer

import (
	"context"
	"strings"
	"testing"

	"french-learning-app/internal/domain"
)

// hasRule reports whether the assessment contains a match for the given rule id.
func hasRule(a LocalAssessment, id RuleID) bool {
	for _, m := range a.MatchedRules {
		if m.RuleID == id {
			return true
		}
	}
	return false
}

// hasCategory reports whether any matched rule proposed the given category.
func hasCategory(a LocalAssessment, c domain.Category) bool {
	for _, m := range a.MatchedRules {
		if m.Category == c {
			return true
		}
	}
	return false
}

func assessInput(t *testing.T, input string) LocalAssessment {
	t.Helper()
	return assessEntry(t, input, "")
}

func assessEntry(t *testing.T, input, context string) LocalAssessment {
	t.Helper()
	a, err := NewRuleBased().Assess(context2(), &domain.Entry{OriginalInput: input, OriginalContext: context})
	if err != nil {
		t.Fatalf("Assess: %v", err)
	}
	return a
}

func context2() context.Context { return context.Background() }

// --- explicit categories ---

func TestAssess_ExplicitCategories(t *testing.T) {
	cases := []struct {
		name     string
		input    string
		wantCat  domain.Category
		wantRule RuleID
	}{
		{"translation", "How do I say hello in French", domain.CategoryTranslation, RuleExplicitTranslation},
		{"pronunciation", "How do I pronounce this word", domain.CategoryPronunciation, RuleExplicitPronunciation},
		{"orthography", "How do I spell this", domain.CategoryOrthography, RuleExplicitOrthography},
		{"morphology", "How do I conjugate this verb", domain.CategoryMorphology, RuleExplicitMorphology},
		{"grammar", "Explain the word order here", domain.CategoryGrammar, RuleExplicitGrammar},
		{"vocabulary", "What is the meaning of this term", domain.CategoryVocabulary, RuleExplicitVocabulary},
		{"pragmatics", "Is this formal or informal", domain.CategoryPragmatics, RuleExplicitPragmatics},
		{"whole-utterance comprehension", "What does this sentence mean", domain.CategoryComprehension, RuleWholeUtterance},
		{"translation CJK", "翻译这个", domain.CategoryTranslation, RuleExplicitTranslation},
		{"pronunciation CJK", "这个怎么读", domain.CategoryPronunciation, RuleExplicitPronunciation},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			a := assessInput(t, tc.input)
			if a.Category != tc.wantCat {
				t.Fatalf("category = %q, want %q (matched: %+v)", a.Category, tc.wantCat, a.MatchedRules)
			}
			if !hasRule(a, tc.wantRule) {
				t.Fatalf("expected rule %q to match, got %+v", tc.wantRule, a.MatchedRules)
			}
			assertValidAssessment(t, a)
		})
	}
}

func TestAssess_ExplicitStrongIsConfidentAndNoAI(t *testing.T) {
	// A single clean explicit non-semantic cue should be confident and not need AI.
	a := assessInput(t, "How do I say hello in French")
	if a.NeedsAI {
		t.Fatalf("clean explicit translation should not need AI, reasons: %v", a.UncertaintyReasons)
	}
	if a.Confidence < 0.80 {
		t.Fatalf("confidence = %v, want >= 0.80 for a clean explicit rule", a.Confidence)
	}
}

func TestAssess_PragmaticsAdvisesAIEvenWhenExplicit(t *testing.T) {
	a := assessInput(t, "Should I use tu or vous here, is this polite")
	if a.Category != domain.CategoryPragmatics {
		t.Fatalf("category = %q, want pragmatics", a.Category)
	}
	if !a.NeedsAI {
		t.Fatal("pragmatics requires semantic judgment; NeedsAI should be true")
	}
	if !containsReason(a, "semantic judgment") {
		t.Fatalf("expected a semantic-judgment uncertainty reason, got %v", a.UncertaintyReasons)
	}
}

// --- weak fallbacks ---

func TestAssess_SingleTokenFallback(t *testing.T) {
	a := assessInput(t, "bonjour")
	if a.Category != domain.CategoryVocabulary {
		t.Fatalf("category = %q, want vocabulary", a.Category)
	}
	if !hasRule(a, RuleSingleTokenFallback) {
		t.Fatalf("expected single_token_fallback, got %+v", a.MatchedRules)
	}
	if a.Confidence > 0.55 {
		t.Fatalf("fallback confidence = %v, want <= 0.55", a.Confidence)
	}
	if !a.NeedsAI {
		t.Fatal("weak fallback should set NeedsAI")
	}
}

func TestAssess_MultiTokenFallback(t *testing.T) {
	a := assessInput(t, "je suis fatigué")
	if a.Category != domain.CategoryGrammar {
		t.Fatalf("category = %q, want grammar", a.Category)
	}
	if !hasRule(a, RuleMultiTokenFallback) {
		t.Fatalf("expected multi_token_fallback, got %+v", a.MatchedRules)
	}
	if a.Confidence > 0.55 {
		t.Fatalf("fallback confidence = %v, want <= 0.55", a.Confidence)
	}
	if !a.NeedsAI {
		t.Fatal("weak fallback should set NeedsAI")
	}
}

func TestAssess_NoLinguisticContent(t *testing.T) {
	a := assessInput(t, "123 456")
	if a.Category != domain.CategoryOther {
		t.Fatalf("category = %q, want other", a.Category)
	}
	if !hasRule(a, RuleNoLinguistic) {
		t.Fatalf("expected no_linguistic_content, got %+v", a.MatchedRules)
	}
	if a.Confidence > 0.30 {
		t.Fatalf("confidence = %v, want <= 0.30 for no linguistic content", a.Confidence)
	}
	if !a.NeedsAI {
		t.Fatal("no meaningful evidence should set NeedsAI")
	}
	if !containsReason(a, "no meaningful linguistic evidence") {
		t.Fatalf("expected a 'no meaningful linguistic evidence' reason, got %v", a.UncertaintyReasons)
	}
}

// --- conflict and ambiguity ---

func TestAssess_ConflictTranslationPronunciation(t *testing.T) {
	a := assessInput(t, "How do I say and pronounce this phrase")
	// Deterministic winner: both score equally, taxonomy order breaks the tie
	// (pronunciation precedes translation), so pronunciation is selected.
	if a.Category != domain.CategoryPronunciation {
		t.Fatalf("category = %q, want deterministic pronunciation", a.Category)
	}
	// Competing matches must be preserved.
	if !hasCategory(a, domain.CategoryTranslation) || !hasCategory(a, domain.CategoryPronunciation) {
		t.Fatalf("both competing matches should be preserved, got %+v", a.MatchedRules)
	}
	if !a.NeedsAI {
		t.Fatal("a close conflict should set NeedsAI")
	}
	if !containsReason(a, "similar scores") {
		t.Fatalf("expected a 'similar scores' reason, got %v", a.UncertaintyReasons)
	}
}

func TestAssess_ConflictGrammarMorphology(t *testing.T) {
	a := assessInput(t, "Explain the article and the plural agreement")
	if !hasCategory(a, domain.CategoryGrammar) || !hasCategory(a, domain.CategoryMorphology) {
		t.Fatalf("both grammar and morphology should match, got %+v", a.MatchedRules)
	}
	// Deterministic: grammar (taxonomy index 1) precedes morphology (index 2).
	if a.Category != domain.CategoryGrammar {
		t.Fatalf("category = %q, want deterministic grammar", a.Category)
	}
	if !a.NeedsAI {
		t.Fatal("a close conflict should set NeedsAI")
	}
}

func TestAssess_VeryShortAmbiguousNoContext(t *testing.T) {
	a := assessInput(t, "le")
	if !a.NeedsAI {
		t.Fatal("very short input with no context should set NeedsAI")
	}
	assertValidAssessment(t, a)
}

func TestAssess_StrongInputReinforcedByContext(t *testing.T) {
	a := assessEntry(t, "liaison", "How should this be pronounced?")
	if a.Category != domain.CategoryPronunciation {
		t.Fatalf("category = %q, want pronunciation", a.Category)
	}
	// The pronunciation rule should have fired from both input and context.
	var m *RuleMatch
	for i := range a.MatchedRules {
		if a.MatchedRules[i].RuleID == RuleExplicitPronunciation {
			m = &a.MatchedRules[i]
		}
	}
	if m == nil {
		t.Fatalf("expected explicit_pronunciation_request, got %+v", a.MatchedRules)
	}
	if m.Strength <= strengthExplicit {
		t.Fatalf("context reinforcement should raise strength above %v, got %v", strengthExplicit, m.Strength)
	}
	if a.NeedsAI {
		t.Fatalf("strong reinforced evidence should not need AI, reasons: %v", a.UncertaintyReasons)
	}
}

func TestAssess_ContextOnlyExplicitCue(t *testing.T) {
	// Input carries no cue; the explicit cue lives only in the context.
	a := assessEntry(t, "bonjour", "how do you say this in french")
	if a.Category != domain.CategoryTranslation {
		t.Fatalf("category = %q, want translation (from context)", a.Category)
	}
	if !hasRule(a, RuleExplicitTranslation) {
		t.Fatalf("context cue should introduce the translation rule, got %+v", a.MatchedRules)
	}
}

// --- regression / invariants ---

func TestAssess_QuestionMarkAloneIsNotComprehension(t *testing.T) {
	a := assessInput(t, "Qu'est-ce que c'est?")
	if a.Category == domain.CategoryComprehension {
		t.Fatalf("a bare question mark must not force comprehension, got %+v", a)
	}
}

func TestAssess_AllCategoriesValidAndConfidenceBounded(t *testing.T) {
	inputs := []string{
		"How do I say hello in French",
		"How do I pronounce liaison",
		"How do I spell this",
		"conjugate manger",
		"word order in negation",
		"meaning of this term",
		"is this formal",
		"what does this sentence mean",
		"bonjour",
		"je suis fatigué",
		"123 456",
		"le",
		"",
	}
	for _, in := range inputs {
		a := assessInput(t, in)
		if !domain.ValidCategory(a.Category) {
			t.Fatalf("input %q produced invalid category %q", in, a.Category)
		}
		if a.Confidence < 0 || a.Confidence > 1 {
			t.Fatalf("input %q produced out-of-range confidence %v", in, a.Confidence)
		}
	}
}

func TestAssess_Deterministic(t *testing.T) {
	entry := &domain.Entry{OriginalInput: "How do I say and pronounce this", OriginalContext: "in a polite register"}
	first, _ := NewRuleBased().Assess(context.Background(), entry)
	second, _ := NewRuleBased().Assess(context.Background(), entry)

	if first.Category != second.Category || first.Confidence != second.Confidence || first.NeedsAI != second.NeedsAI {
		t.Fatalf("scalar fields differ across runs: %+v vs %+v", first, second)
	}
	if len(first.MatchedRules) != len(second.MatchedRules) {
		t.Fatalf("match count differs: %d vs %d", len(first.MatchedRules), len(second.MatchedRules))
	}
	for i := range first.MatchedRules {
		if first.MatchedRules[i] != second.MatchedRules[i] {
			t.Fatalf("match %d differs (order not stable): %+v vs %+v", i, first.MatchedRules[i], second.MatchedRules[i])
		}
	}
	if len(first.UncertaintyReasons) != len(second.UncertaintyReasons) {
		t.Fatalf("reason count differs: %v vs %v", first.UncertaintyReasons, second.UncertaintyReasons)
	}
	for i := range first.UncertaintyReasons {
		if first.UncertaintyReasons[i] != second.UncertaintyReasons[i] {
			t.Fatalf("reason %d differs: %q vs %q", i, first.UncertaintyReasons[i], second.UncertaintyReasons[i])
		}
	}
}

func TestAssess_DoesNotMutateEntry(t *testing.T) {
	entry := &domain.Entry{OriginalInput: "  How do I say hello  ", OriginalContext: "  greeting  "}
	inputBefore, contextBefore := entry.OriginalInput, entry.OriginalContext
	_, _ = NewRuleBased().Assess(context.Background(), entry)
	if entry.OriginalInput != inputBefore || entry.OriginalContext != contextBefore {
		t.Fatalf("entry was mutated: input %q->%q, context %q->%q",
			inputBefore, entry.OriginalInput, contextBefore, entry.OriginalContext)
	}
}

// TestAssess_SpecificCueBeatsManyWeakCues proves a single specific rule is not
// overpowered merely because another category accumulated more matches.
func TestAssess_SpecificCueBeatsMultipleSupportingMatches(t *testing.T) {
	// "in french" (translation) is one cue; it must not be diluted by unrelated
	// token counting. A pure translation request stays translation.
	a := assessInput(t, "please translate this sentence into french for me")
	if a.Category != domain.CategoryTranslation {
		t.Fatalf("category = %q, want translation", a.Category)
	}
}

// --- Analyze <-> Assess consistency ---

func TestAnalyze_UsesAssessResult(t *testing.T) {
	entry := &domain.Entry{OriginalInput: "How do I pronounce liaison", OriginalContext: ""}
	a, _ := NewRuleBased().Assess(context.Background(), entry)
	res, err := NewRuleBased().Analyze(context.Background(), entry)
	if err != nil {
		t.Fatalf("Analyze: %v", err)
	}
	if res.Category != a.Category {
		t.Fatalf("Analyze category %q != Assess category %q", res.Category, a.Category)
	}
	if res.Confidence != a.Confidence {
		t.Fatalf("Analyze confidence %v != Assess confidence %v", res.Confidence, a.Confidence)
	}
	if err := res.Validate(); err != nil {
		t.Fatalf("Analyze result failed domain validation: %v", err)
	}
}

func TestAnalyze_ExplanationAndUncertaintyContent(t *testing.T) {
	res, _ := NewRuleBased().Analyze(context.Background(), &domain.Entry{OriginalInput: "bonjour"})
	if err := res.Validate(); err != nil {
		t.Fatalf("validation: %v", err)
	}
	// Explanation should name the selected category and reference a rule.
	if !contains(res.Explanation, "vocabulary") || !contains(res.Explanation, string(RuleSingleTokenFallback)) {
		t.Fatalf("explanation missing category/rule detail: %q", res.Explanation)
	}
	// Uncertainty should advise AI review with a specific reason, never a bare
	// "low confidence".
	if !contains(res.Uncertainty, "AI review advised") {
		t.Fatalf("uncertainty should advise AI review: %q", res.Uncertainty)
	}
	if res.Uncertainty == "low confidence" {
		t.Fatalf("uncertainty must not be a vague 'low confidence'")
	}
}

// --- helpers ---

func assertValidAssessment(t *testing.T, a LocalAssessment) {
	t.Helper()
	if !domain.ValidCategory(a.Category) {
		t.Fatalf("invalid category %q", a.Category)
	}
	if a.Confidence < 0 || a.Confidence > 1 {
		t.Fatalf("confidence %v out of [0,1]", a.Confidence)
	}
	for _, m := range a.MatchedRules {
		if m.Strength < 0 || m.Strength > 1 {
			t.Fatalf("rule %q strength %v out of [0,1]", m.RuleID, m.Strength)
		}
		if m.Evidence == "" {
			t.Fatalf("rule %q has empty evidence", m.RuleID)
		}
	}
}

func containsReason(a LocalAssessment, substr string) bool {
	for _, r := range a.UncertaintyReasons {
		if contains(r, substr) {
			return true
		}
	}
	return false
}

func contains(s, substr string) bool {
	return strings.Contains(s, substr)
}
