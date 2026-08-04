// Package analyzer provides local, non-AI implementations of domain.Analyzer.
// These let the full analysis workflow run and be tested without calling an
// external AI provider.
package analyzer

import (
	"context"
	"strings"

	"french-learning-app/internal/domain"
)

// ruleBasedVersion identifies the ruleset behind the local analyzer. It is bumped
// when the rules change materially so analyses produced by different rulesets are
// distinguishable in stored provenance. v2 is the explainable, uncertainty-aware
// rule engine (milestone 6); v1 was the original four-branch switch.
const ruleBasedVersion = "v2"

// RuleBased is a deterministic, local domain.Analyzer built on a named,
// weighted rule engine (see assessment.go). Given the same entry it always
// produces the same result — no clock, no randomness, no network — which keeps
// local development and tests stable.
//
// It evaluates explicit linguistic cues in the original input and context,
// falling back to weak token-count heuristics only when no explicit rule fires,
// and maps the winning category onto the shared fr_l2_taxonomy_v1 taxonomy. The
// confidence it reports is a heuristic decision score, not a calibrated
// probability, and it can advise (but never trigger) later AI review.
type RuleBased struct{}

// NewRuleBased returns a ready-to-use rule-based analyzer.
func NewRuleBased() *RuleBased { return &RuleBased{} }

// compile-time check.
var _ domain.Analyzer = (*RuleBased)(nil)

// Name identifies this analyzer in stored records. The provenance is versioned
// and carries the taxonomy version, e.g. "rule-based:v2:fr_l2_taxonomy_v1", so
// records created before and after a ruleset change remain distinguishable.
func (RuleBased) Name() string {
	return "rule-based:" + ruleBasedVersion + ":" + domain.TaxonomyVersion
}

// Assess runs the deterministic rule engine over the entry and returns the
// structured local assessment: the selected category, a heuristic confidence, an
// advisory NeedsAI flag, the matched rules (in deterministic order), and
// meaningful uncertainty reasons. It never mutates the entry and never performs
// any I/O. The context is accepted for interface symmetry with fallible
// analyzers; this local engine does not use it.
func (RuleBased) Assess(_ context.Context, entry *domain.Entry) (LocalAssessment, error) {
	return assess(entry), nil
}

// Analyze classifies the entry by delegating to Assess and converting the
// assessment into the shared domain.AnalysisResult. The classification algorithm
// lives only in the engine, so Analyze and Assess never diverge. It never
// returns an error; the signature keeps the interface uniform with future
// fallible analyzers.
func (r RuleBased) Analyze(ctx context.Context, entry *domain.Entry) (domain.AnalysisResult, error) {
	a, err := r.Assess(ctx, entry)
	if err != nil {
		return domain.AnalysisResult{}, err
	}
	return domain.AnalysisResult{
		Category:    a.Category,
		Explanation: buildExplanation(a),
		Confidence:  a.Confidence,
		Uncertainty: buildUncertainty(a),
	}, nil
}

// buildExplanation describes the decision in terms of the strongest matching
// rule and its observable evidence, listing supporting rules when present.
func buildExplanation(a LocalAssessment) string {
	if len(a.MatchedRules) == 0 {
		// Defensive: assess always returns at least one match.
		return "Local classification selected \"" + a.Category + "\" with no matching rule."
	}
	strongest := a.MatchedRules[0]
	for _, m := range a.MatchedRules[1:] {
		if m.Strength > strongest.Strength {
			strongest = m
		}
	}

	var b strings.Builder
	b.WriteString("Local classification selected \"")
	b.WriteString(a.Category)
	b.WriteString("\" because rule \"")
	b.WriteString(string(strongest.RuleID))
	b.WriteString("\" ")
	b.WriteString(strongest.Evidence)
	b.WriteString(".")

	// Note any other matched rules as supporting/competing evidence.
	var supporting []string
	for _, m := range a.MatchedRules {
		if m.RuleID == strongest.RuleID {
			continue
		}
		supporting = append(supporting, string(m.RuleID)+" ("+m.Category+")")
	}
	if len(supporting) > 0 {
		b.WriteString(" Supporting/competing rules: ")
		b.WriteString(strings.Join(supporting, ", "))
		b.WriteString(".")
	}
	return b.String()
}

// buildUncertainty summarizes whether AI review is advised and why, using the
// engine's specific uncertainty reasons (never a bare "low confidence").
func buildUncertainty(a LocalAssessment) string {
	lead := "AI review not advised: local evidence is explicit and unambiguous."
	if a.NeedsAI {
		lead = "AI review advised"
		if len(a.UncertaintyReasons) > 0 {
			lead += ": " + strings.Join(a.UncertaintyReasons, "; ")
		}
		lead += "."
	} else if len(a.UncertaintyReasons) > 0 {
		lead = "AI review not advised. Notes: " + strings.Join(a.UncertaintyReasons, "; ") + "."
	}
	return lead
}
