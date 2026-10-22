package domain

import "strings"

// FLH-095 bilingual learning explanations.
//
// Generated explanatory text (an analysis explanation, a knowledge-unit
// statement) may carry an English and a Simplified Chinese variant. The variants
// are explanatory content only: they are not identity, not additional units or
// Concepts, and never feed identity, retrieval or embedding representations,
// which keep reading the primary text. A nil variant means "not recorded";
// nothing is ever translated or backfilled to fill it.

// ExplanationLanguage is one stored explanation language.
type ExplanationLanguage string

const (
	// LanguageEnglish is the English variant.
	LanguageEnglish ExplanationLanguage = "en"
	// LanguageChinese is the Simplified Chinese variant.
	LanguageChinese ExplanationLanguage = "zh"
)

// explanationLanguages is the fixed, ordered set of supported languages.
var explanationLanguages = []ExplanationLanguage{LanguageEnglish, LanguageChinese}

// ExplanationVariants holds the per-language variants of one generated text.
// Both nil means the language of the primary text was not recorded (legacy
// rows, imported analyses, fixture units).
type ExplanationVariants struct {
	EN *string
	ZH *string
}

// Get returns the variant for lang, or nil when it is not stored.
func (v ExplanationVariants) Get(lang ExplanationLanguage) *string {
	switch lang {
	case LanguageEnglish:
		return v.EN
	case LanguageChinese:
		return v.ZH
	}
	return nil
}

// Recorded reports whether any language variant is stored.
func (v ExplanationVariants) Recorded() bool { return v.EN != nil || v.ZH != nil }

// normalize trims the variants (blank becomes nil), checks their bounds and
// requires a present English variant to equal the primary text, which must
// already be trimmed. field names the primary field in errors.
func (v *ExplanationVariants) normalize(primary, field string, max int) error {
	v.EN = trimOptional(v.EN)
	v.ZH = trimOptional(v.ZH)
	for _, s := range []*string{v.EN, v.ZH} {
		if s != nil && len(*s) > max {
			return errWrap(field + " variant exceeds maximum length")
		}
	}
	if v.EN != nil && *v.EN != primary {
		return errWrap(field + "_en must equal the primary " + field)
	}
	return nil
}

// ParseExplanationLanguages validates a list of language codes, rejecting
// unknown or repeated codes, and returns them in canonical order (en, zh).
// An empty list returns nil: "not recorded".
func ParseExplanationLanguages(codes []string) ([]ExplanationLanguage, error) {
	seen := map[ExplanationLanguage]bool{}
	for _, c := range codes {
		lang := ExplanationLanguage(strings.TrimSpace(c))
		if lang != LanguageEnglish && lang != LanguageChinese {
			return nil, errWrap("reviewed_explanation_languages may contain only en and zh")
		}
		if seen[lang] {
			return nil, errWrap("reviewed_explanation_languages must not repeat a language")
		}
		seen[lang] = true
	}
	var out []ExplanationLanguage
	for _, l := range explanationLanguages {
		if seen[l] {
			out = append(out, l)
		}
	}
	return out, nil
}

// ExplanationBasis says where an effective explanation variant comes from and
// whether a person reviewed it in that language.
type ExplanationBasis string

const (
	// BasisUnreviewed: generated text; the analysis has no feedback yet.
	BasisUnreviewed ExplanationBasis = "unreviewed"
	// BasisReviewed: generated text that was shown in this language when a
	// person accepted the analysis (or corrected only its category).
	BasisReviewed ExplanationBasis = "reviewed"
	// BasisNotReviewed: there is feedback, but this language was not shown, so
	// the decision does not approve this text.
	BasisNotReviewed ExplanationBasis = "not_reviewed"
	// BasisCorrected: a person supplied this text in this language.
	BasisCorrected ExplanationBasis = "corrected"
	// BasisOutdated: generated text kept for reference; a person corrected the
	// explanation in another (or an unspecified) language, so it may no longer
	// match the effective interpretation.
	BasisOutdated ExplanationBasis = "outdated"
	// BasisUnavailable: no text is stored in this language.
	BasisUnavailable ExplanationBasis = "unavailable"
)

// EffectiveExplanationVariant is one language of the effective explanation.
type EffectiveExplanationVariant struct {
	Text  *string
	Basis ExplanationBasis
}

// EffectiveExplanations is the per-language effective explanation.
type EffectiveExplanations struct {
	EN EffectiveExplanationVariant
	ZH EffectiveExplanationVariant
}

// resolveExplanations derives the per-language effective explanation of a
// non-rejected analysis from its stored variants and latest feedback (nil when
// unreviewed). It never presents generated text as reviewed in a language that
// was not shown, and never presents text predating a correction as current.
func resolveExplanations(original ExplanationVariants, latest *Feedback) EffectiveExplanations {
	explanationCorrected := latest != nil && latest.Status == FeedbackCorrected &&
		(latest.CorrectedExplanation != nil || latest.CorrectedExplanations.Recorded())
	reviewed := map[ExplanationLanguage]bool{}
	if latest != nil {
		for _, l := range latest.ReviewedLanguages {
			reviewed[l] = true
		}
	}
	one := func(lang ExplanationLanguage) EffectiveExplanationVariant {
		if latest != nil && latest.Status == FeedbackCorrected {
			if c := latest.CorrectedExplanations.Get(lang); c != nil {
				return EffectiveExplanationVariant{Text: c, Basis: BasisCorrected}
			}
		}
		text := original.Get(lang)
		switch {
		case text == nil:
			return EffectiveExplanationVariant{Basis: BasisUnavailable}
		case explanationCorrected:
			return EffectiveExplanationVariant{Text: text, Basis: BasisOutdated}
		case latest == nil:
			return EffectiveExplanationVariant{Text: text, Basis: BasisUnreviewed}
		case reviewed[lang]:
			return EffectiveExplanationVariant{Text: text, Basis: BasisReviewed}
		default:
			return EffectiveExplanationVariant{Text: text, Basis: BasisNotReviewed}
		}
	}
	return EffectiveExplanations{EN: one(LanguageEnglish), ZH: one(LanguageChinese)}
}
