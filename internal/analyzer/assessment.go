package analyzer

import (
	"sort"
	"strconv"
	"strings"
	"unicode"

	"french-learning-app/internal/domain"
)

// This file implements the deterministic local rule engine used by RuleBased.
// It is intentionally implementation-specific and lives in internal/analyzer,
// not in the core domain: the domain only knows about AnalysisResult. The engine
// is pure and deterministic — no clock, no randomness, no I/O, no network — so
// the same entry always yields byte-identical output.

// RuleID is a stable, machine-readable identifier for a classification rule.
type RuleID string

// Stable rule identifiers. These are part of the analyzer's observable contract
// (they appear in evidence and tests), so they must not change casually.
const (
	RuleExplicitTranslation   RuleID = "explicit_translation_request"
	RuleExplicitPronunciation RuleID = "explicit_pronunciation_request"
	RuleExplicitOrthography   RuleID = "explicit_orthography_request"
	RuleExplicitMorphology    RuleID = "explicit_morphology_request"
	RuleExplicitGrammar       RuleID = "explicit_grammar_request"
	RuleExplicitVocabulary    RuleID = "explicit_vocabulary_request"
	RuleExplicitPragmatics    RuleID = "explicit_pragmatics_request"
	RuleWholeUtterance        RuleID = "whole_utterance_comprehension"

	RuleSingleTokenFallback RuleID = "single_token_fallback"
	RuleMultiTokenFallback  RuleID = "multi_token_fallback"
	RuleNoLinguistic        RuleID = "no_linguistic_content"
)

// evidenceSource records where a rule's cue was observed.
type evidenceSource string

const (
	sourceInput   evidenceSource = "input"
	sourceContext evidenceSource = "context"
	sourceBoth    evidenceSource = "input+context"
)

// RuleMatch is one rule firing against an entry. Matches are always returned in
// a deterministic order (the order rules are declared).
type RuleMatch struct {
	RuleID   RuleID
	Category domain.Category
	// Strength is bounded within [0, 1]. It reflects how specific/reliable the
	// cue is, not a calibrated probability.
	Strength float64
	// Evidence describes the observable cue that fired the rule, e.g.
	//   rule "explicit_translation_request" matched "how do i say" in the input
	Evidence string
}

// LocalAssessment is the structured explanation of the local decision. It holds
// no HTTP, SQL, provider, timestamp, or random data: given the same entry it is
// always identical.
type LocalAssessment struct {
	Category   domain.Category
	Confidence float64
	// NeedsAI is advisory only in this milestone: it never triggers an API call.
	// It records that a later hybrid policy might want to escalate this entry.
	NeedsAI            bool
	MatchedRules       []RuleMatch
	UncertaintyReasons []string
}

// --- scoring weights and thresholds (named, not magic numbers) ---
//
// Confidence here is a heuristic decision score, NOT a statistically calibrated
// probability. The values below are deliberately conservative and interpretable.
const (
	// Strength assigned to an explicit, specific cue (e.g. "translate", "ipa").
	strengthExplicit = 0.90
	// Strength floors for the weak fallbacks. These are much lower than any
	// explicit rule so a single specific cue always outranks token-count guesses.
	strengthSingleTokenFallback = 0.45
	strengthMultiTokenFallback  = 0.40
	strengthNoLinguistic        = 0.25

	// A rule matched in BOTH the input and the context is slightly stronger:
	// two independent observations of the same cue.
	contextReinforcementBoost = 0.05

	// Aggregation: a category's score is its strongest match plus a small,
	// bounded contribution from additional compatible matches. The support term
	// is capped so ten weak matches can never overpower one specific rule.
	supportWeight = 0.25
	supportCap    = 0.15

	// Confidence tiers.
	confStrongBase       = 0.85 // one clean explicit rule
	confCompatibleBonus  = 0.05 // reinforced by another compatible rule
	confConflictPenalty  = 0.20 // a competing explicit rule of another category
	confNoContextPenalty = 0.05 // short input and no context to disambiguate
	confStrongMax        = 0.95
	confStrongMin        = 0.60

	confFallback      = 0.50 // only weak fallback rules matched
	confFallbackNoCtx = 0.45 // ...and no context either
	confFallbackMax   = 0.55
	confNoLinguistic  = 0.25 // no alphabetic content at all

	// Decision thresholds.
	needsAIConfidenceThreshold = 0.65 // below this, advise AI review
	smallMarginThreshold       = 0.15 // top vs runner-up considered "close"
	shortInputMaxTokens        = 1    // "very short" input, in tokens
)

// rule is a declarative classification rule: if any of its cues appears in the
// (lowercased) input or context, it contributes a match for its category.
type rule struct {
	id       RuleID
	category domain.Category
	strength float64
	cues     []string
}

// explicitRules are the strong, specific rules. They are evaluated in this fixed
// order, which also fixes the order of MatchedRules. Cues are matched as
// lowercase substrings so they work for both ASCII phrases and CJK strings.
var explicitRules = []rule{
	{
		id: RuleExplicitTranslation, category: domain.CategoryTranslation, strength: strengthExplicit,
		cues: []string{"how do i say", "how do you say", "translate", "translation", "in french", "en français", "怎么说", "翻译"},
	},
	{
		id: RuleExplicitPronunciation, category: domain.CategoryPronunciation, strength: strengthExplicit,
		cues: []string{"pronounce", "pronunciation", "ipa", "liaison", "comment prononcer", "发音", "怎么读"},
	},
	{
		id: RuleExplicitOrthography, category: domain.CategoryOrthography, strength: strengthExplicit,
		cues: []string{"spell", "spelling", "accent", "apostrophe", "capitalization", "comment écrire", "拼写", "重音符号"},
	},
	{
		id: RuleExplicitMorphology, category: domain.CategoryMorphology, strength: strengthExplicit,
		cues: []string{"conjugate", "conjugation", "agreement", "gender", "plural", "participle", "conjugaison", "accord", "变位", "阴阳性", "复数"},
	},
	{
		id: RuleExplicitGrammar, category: domain.CategoryGrammar, strength: strengthExplicit,
		cues: []string{"word order", "preposition", "article", "negation", "sentence structure", "grammar", "grammaire", "语序", "介词", "冠词", "语法"},
	},
	{
		id: RuleExplicitVocabulary, category: domain.CategoryVocabulary, strength: strengthExplicit,
		cues: []string{"what does this word mean", "meaning of", "synonym", "collocation", "vocabulary", "vocabulaire", "这个词什么意思", "近义词", "搭配"},
	},
	{
		id: RuleExplicitPragmatics, category: domain.CategoryPragmatics, strength: strengthExplicit,
		cues: []string{"formal", "informal", "polite", "register", "tu or vous", "registre", "礼貌", "正式", "非正式"},
	},
	{
		id: RuleWholeUtterance, category: domain.CategoryComprehension, strength: strengthExplicit,
		cues: []string{"what does this sentence mean", "what does this passage mean", "explain this sentence", "why does this sentence", "这句话什么意思", "解释这句话"},
	},
}

// taxonomyOrder maps each category to its stable position in the taxonomy, used
// as a deterministic tie-breaker when two categories score equally.
var taxonomyOrder = func() map[domain.Category]int {
	m := make(map[domain.Category]int)
	for i, c := range domain.Categories() {
		m[c] = i
	}
	return m
}()

// features are the observable, deterministic properties extracted from an entry.
type features struct {
	inputLower   string
	contextLower string
	inputTokens  int
	hasLetters   bool
	hasContext   bool
}

// extractFeatures reads the entry without mutating it.
func extractFeatures(entry *domain.Entry) features {
	input := strings.TrimSpace(entry.OriginalInput)
	context := strings.TrimSpace(entry.OriginalContext)
	return features{
		inputLower:   strings.ToLower(input),
		contextLower: strings.ToLower(context),
		inputTokens:  len(strings.Fields(input)),
		hasLetters:   containsLetter(input) || containsLetter(context),
		hasContext:   context != "",
	}
}

// assess is the single classification algorithm. Both Assess and Analyze go
// through it so the logic is never duplicated.
func assess(entry *domain.Entry) LocalAssessment {
	f := extractFeatures(entry)

	matches := evaluateExplicitRules(f)
	// Fallback rules apply only when no stronger explicit rule fired, so token
	// counts never dilute or override a specific cue.
	onlyFallback := false
	if len(matches) == 0 {
		matches = append(matches, evaluateFallback(f))
		onlyFallback = true
	}

	scores := aggregateByCategory(matches)
	top, topScore, runnerUp, runnerScore := rankCategories(scores)

	margin := topScore - runnerScore
	conflict := runnerUp != "" && runnerScore > 0 && margin < smallMarginThreshold
	noMeaningful := onlyFallback && top == domain.CategoryOther

	confidence := deriveConfidence(top, topScore, onlyFallback, noMeaningful, conflict, f)
	reasons := uncertaintyReasons(top, onlyFallback, noMeaningful, conflict, f, runnerUp)
	needsAI := deriveNeedsAI(top, confidence, onlyFallback, noMeaningful, conflict, f)

	return LocalAssessment{
		Category:           top,
		Confidence:         confidence,
		NeedsAI:            needsAI,
		MatchedRules:       matches,
		UncertaintyReasons: reasons,
	}
}

// evaluateExplicitRules returns one match per explicit rule that fired, in
// declaration order (deterministic).
func evaluateExplicitRules(f features) []RuleMatch {
	var matches []RuleMatch
	for _, r := range explicitRules {
		inCue, inHit := firstCue(f.inputLower, r.cues)
		ctxCue, ctxHit := firstCue(f.contextLower, r.cues)
		if !inHit && !ctxHit {
			continue
		}
		strength := r.strength
		var src evidenceSource
		var cue string
		switch {
		case inHit && ctxHit:
			src, cue = sourceBoth, inCue
			// Reinforced by two independent observations.
			strength = clamp01(strength + contextReinforcementBoost)
		case inHit:
			src, cue = sourceInput, inCue
		default:
			src, cue = sourceContext, ctxCue
		}
		matches = append(matches, RuleMatch{
			RuleID:   r.id,
			Category: r.category,
			Strength: strength,
			Evidence: formatEvidence(cue, src),
		})
	}
	return matches
}

// evaluateFallback returns exactly one low-strength fallback match, used only
// when no explicit rule fired. Token count alone is treated as weak evidence.
func evaluateFallback(f features) RuleMatch {
	switch {
	case !f.hasLetters:
		return RuleMatch{
			RuleID:   RuleNoLinguistic,
			Category: domain.CategoryOther,
			Strength: strengthNoLinguistic,
			Evidence: "no alphabetic content found in the input or context",
		}
	case f.inputTokens <= 1:
		return RuleMatch{
			RuleID:   RuleSingleTokenFallback,
			Category: domain.CategoryVocabulary,
			Strength: strengthSingleTokenFallback,
			Evidence: "input is a single token with alphabetic content (weak lexical guess)",
		}
	default:
		return RuleMatch{
			RuleID:   RuleMultiTokenFallback,
			Category: domain.CategoryGrammar,
			Strength: strengthMultiTokenFallback,
			Evidence: "input is a multi-token phrase with no explicit cue (weak structural guess)",
		}
	}
}

// aggregateByCategory scores each category as its strongest match plus a bounded
// contribution from additional matches of the same category.
func aggregateByCategory(matches []RuleMatch) map[domain.Category]float64 {
	strongest := make(map[domain.Category]float64)
	supportSum := make(map[domain.Category]float64)
	for _, m := range matches {
		if m.Strength > strongest[m.Category] {
			// The previous strongest becomes support.
			if strongest[m.Category] > 0 {
				supportSum[m.Category] += strongest[m.Category]
			}
			strongest[m.Category] = m.Strength
		} else {
			supportSum[m.Category] += m.Strength
		}
	}
	scores := make(map[domain.Category]float64, len(strongest))
	for cat, s := range strongest {
		support := supportWeight * supportSum[cat]
		if support > supportCap {
			support = supportCap
		}
		scores[cat] = clamp01(s + support)
	}
	return scores
}

// rankCategories returns the top and runner-up categories deterministically:
// highest score wins, ties broken by stable taxonomy order.
func rankCategories(scores map[domain.Category]float64) (top domain.Category, topScore float64, runnerUp domain.Category, runnerScore float64) {
	type entry struct {
		cat   domain.Category
		score float64
	}
	ranked := make([]entry, 0, len(scores))
	for c, s := range scores {
		ranked = append(ranked, entry{c, s})
	}
	sort.Slice(ranked, func(i, j int) bool {
		if ranked[i].score != ranked[j].score {
			return ranked[i].score > ranked[j].score
		}
		return taxonomyOrder[ranked[i].cat] < taxonomyOrder[ranked[j].cat]
	})
	if len(ranked) > 0 {
		top, topScore = ranked[0].cat, ranked[0].score
	}
	if len(ranked) > 1 {
		runnerUp, runnerScore = ranked[1].cat, ranked[1].score
	}
	return top, topScore, runnerUp, runnerScore
}

// deriveConfidence turns the ranked scores into a bounded heuristic confidence.
func deriveConfidence(top domain.Category, topScore float64, onlyFallback, noMeaningful, conflict bool, f features) float64 {
	if noMeaningful {
		return confNoLinguistic
	}
	if onlyFallback {
		conf := confFallback
		if !f.hasContext {
			conf = confFallbackNoCtx
		}
		return clampRange(conf, 0, confFallbackMax)
	}

	// Explicit evidence tier.
	conf := confStrongBase
	if topScore > strengthExplicit {
		// Reinforced by context and/or a compatible supporting rule.
		conf += confCompatibleBonus
	}
	if conflict {
		conf -= confConflictPenalty
	}
	if !f.hasContext && f.inputTokens <= shortInputMaxTokens {
		conf -= confNoContextPenalty
	}
	return clampRange(conf, confStrongMin, confStrongMax)
}

// deriveNeedsAI computes the advisory escalation flag. It never calls anything.
func deriveNeedsAI(top domain.Category, confidence float64, onlyFallback, noMeaningful, conflict bool, f features) bool {
	switch {
	case noMeaningful:
		return true
	case onlyFallback:
		return true
	case conflict:
		return true
	case confidence < needsAIConfidenceThreshold:
		return true
	case f.inputTokens <= shortInputMaxTokens && !f.hasContext:
		return true
	case requiresSemanticJudgment(top):
		// pragmatics/discourse/mixed need semantic judgment beyond deterministic cues.
		return true
	default:
		return false
	}
}

// requiresSemanticJudgment reports whether a category typically needs judgment
// the deterministic engine cannot provide, so AI review is advised even on an
// explicit local match.
func requiresSemanticJudgment(c domain.Category) bool {
	switch c {
	case domain.CategoryPragmatics, domain.CategoryDiscourse, domain.CategoryMixed:
		return true
	default:
		return false
	}
}

// uncertaintyReasons builds meaningful, specific reasons (never a bare
// "low confidence"). Order is deterministic.
func uncertaintyReasons(top domain.Category, onlyFallback, noMeaningful, conflict bool, f features, runnerUp domain.Category) []string {
	var reasons []string
	if noMeaningful {
		reasons = append(reasons, "no meaningful linguistic evidence was found")
	}
	if onlyFallback && !noMeaningful {
		reasons = append(reasons, "only weak fallback rules matched")
	}
	if conflict {
		reasons = append(reasons, "top categories have similar scores ("+top+" vs "+runnerUp+")")
	}
	if requiresSemanticJudgment(top) {
		reasons = append(reasons, top+" requires semantic judgment beyond deterministic cues")
	}
	if f.inputTokens <= shortInputMaxTokens && !f.hasContext {
		reasons = append(reasons, "input is too short to classify reliably and no context was provided")
	} else if !f.hasContext {
		reasons = append(reasons, "original context is empty")
	}
	return reasons
}

// --- small helpers ---

// firstCue returns the first cue (in declaration order) that appears in text.
func firstCue(text string, cues []string) (string, bool) {
	if text == "" {
		return "", false
	}
	for _, cue := range cues {
		if strings.Contains(text, cue) {
			return cue, true
		}
	}
	return "", false
}

// formatEvidence describes the observable cue that fired a rule. It intentionally
// omits the rule id (the caller names the rule) and just states what was seen.
func formatEvidence(cue string, src evidenceSource) string {
	return "matched " + strconv.Quote(cue) + " in the " + string(src)
}

func containsLetter(s string) bool {
	for _, r := range s {
		if unicode.IsLetter(r) {
			return true
		}
	}
	return false
}

func clamp01(v float64) float64 { return clampRange(v, 0, 1) }

func clampRange(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
