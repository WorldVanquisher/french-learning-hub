package http

import "french-learning-app/internal/domain"

// FLH-095 wire shapes for bilingual explanatory text. A null variant means the
// language was not recorded; clients must not present another language's text
// in its place.

// explanationVariantsResponse is the stored English/Chinese variants of one
// generated text (an analysis explanation or a unit statement).
type explanationVariantsResponse struct {
	EN *string `json:"en"`
	ZH *string `json:"zh"`
}

func toVariants(v domain.ExplanationVariants) explanationVariantsResponse {
	return explanationVariantsResponse{EN: v.EN, ZH: v.ZH}
}

// effectiveExplanationResponse is one language of the effective explanation:
// its text (null when unavailable) and its basis (unreviewed, reviewed,
// not_reviewed, corrected, outdated or unavailable).
type effectiveExplanationResponse struct {
	Text  *string `json:"text"`
	Basis string  `json:"basis"`
}

type effectiveExplanationsResponse struct {
	EN effectiveExplanationResponse `json:"en"`
	ZH effectiveExplanationResponse `json:"zh"`
}

func toEffectiveExplanations(e *domain.EffectiveExplanations) *effectiveExplanationsResponse {
	if e == nil {
		return nil
	}
	return &effectiveExplanationsResponse{
		EN: effectiveExplanationResponse{Text: e.EN.Text, Basis: string(e.EN.Basis)},
		ZH: effectiveExplanationResponse{Text: e.ZH.Text, Basis: string(e.ZH.Basis)},
	}
}

// languageCodes renders reviewed languages as a JSON array, or null when the
// decision did not record them.
func languageCodes(langs []domain.ExplanationLanguage) []string {
	if len(langs) == 0 {
		return nil
	}
	out := make([]string, len(langs))
	for i, l := range langs {
		out[i] = string(l)
	}
	return out
}
