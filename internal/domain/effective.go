package domain

// Resolution is the derived state of an analysis once its latest feedback is
// taken into account. It is computed on read, never stored.
type Resolution string

const (
	// ResolutionUnreviewed means the analysis has no feedback yet; the effective
	// values equal the original analysis.
	ResolutionUnreviewed Resolution = "unreviewed"
	// ResolutionAccepted means the latest feedback accepted the analysis as-is;
	// the effective values equal the original analysis.
	ResolutionAccepted Resolution = "accepted"
	// ResolutionCorrected means the latest feedback proposed better metadata;
	// present corrected fields override the original, absent ones fall back to it.
	ResolutionCorrected Resolution = "corrected"
	// ResolutionRejected means the latest feedback rejected the analysis; there
	// is no effective interpretation.
	ResolutionRejected Resolution = "rejected"
)

// AnalysisValues is a category/explanation pair, used for both the original and
// the effective view of an analysis.
type AnalysisValues struct {
	Category    string
	Explanation string
}

// EffectiveAnalysis is the resolved read model for a single immutable analysis
// combined with its latest feedback. It is derived on demand and is never
// persisted: no table, no migration. The original analysis and the feedback
// history are never modified to produce it.
type EffectiveAnalysis struct {
	AnalysisID int64
	EntryID    int64
	Version    int64

	// Original is always the analysis as stored.
	Original AnalysisValues
	// OriginalExplanations are the stored language variants (FLH-095).
	OriginalExplanations ExplanationVariants
	// Explanations is the per-language effective explanation; nil exactly when
	// Effective is nil (a rejected analysis).
	Explanations *EffectiveExplanations
	// Effective is the current interpretation. It is nil for a rejected analysis,
	// which deliberately has no effective category or explanation rather than
	// silently reusing the original values.
	Effective *AnalysisValues

	Resolution Resolution
	// FeedbackID is the id of the feedback record that determined the resolution,
	// or nil when the analysis is unreviewed.
	FeedbackID *int64
}

// ResolveEffective computes the effective analysis from an immutable analysis
// and its latest feedback (nil when there is none). It is a pure function: it
// reads a and latest but mutates neither, so resolution is deterministic and
// testable without any I/O. The caller is responsible for having selected
// "latest" deterministically (created_at DESC, id DESC).
func ResolveEffective(a *Analysis, latest *Feedback) EffectiveAnalysis {
	eff := EffectiveAnalysis{
		AnalysisID: a.ID,
		EntryID:    a.EntryID,
		Version:    a.Version,
		Original:   AnalysisValues{Category: a.Category, Explanation: a.Explanation},

		OriginalExplanations: a.Explanations,
	}
	if latest == nil || latest.Status != FeedbackRejected {
		x := resolveExplanations(a.Explanations, latest)
		eff.Explanations = &x
	}

	// No feedback: the analysis stands as its own effective interpretation.
	if latest == nil {
		eff.Resolution = ResolutionUnreviewed
		eff.Effective = &AnalysisValues{Category: a.Category, Explanation: a.Explanation}
		return eff
	}

	id := latest.ID
	eff.FeedbackID = &id

	switch latest.Status {
	case FeedbackAccepted:
		eff.Resolution = ResolutionAccepted
		eff.Effective = &AnalysisValues{Category: a.Category, Explanation: a.Explanation}
	case FeedbackCorrected:
		eff.Resolution = ResolutionCorrected
		// Present corrected fields override the original; absent fields retain it.
		category := a.Category
		if latest.CorrectedCategory != nil {
			category = *latest.CorrectedCategory
		}
		// The language-independent effective explanation (read by the extraction
		// source and every existing consumer) is the person's corrected text in
		// any language, else the original.
		explanation := a.Explanation
		switch c := latest.CorrectedExplanations; {
		case latest.CorrectedExplanation != nil:
			explanation = *latest.CorrectedExplanation
		case c.EN != nil:
			explanation = *c.EN
		case c.ZH != nil:
			explanation = *c.ZH
		}
		eff.Effective = &AnalysisValues{Category: category, Explanation: explanation}
	case FeedbackRejected:
		eff.Resolution = ResolutionRejected
		// Effective is intentionally left nil: a rejected analysis has no current
		// interpretation.
	}

	return eff
}
