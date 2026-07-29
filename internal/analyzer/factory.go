package analyzer

import (
	"fmt"

	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
)

// New builds the domain.Analyzer selected by configuration. The rule-based
// analyzer is the default and calls no external service; the openai analyzer is
// opt-in. Provider selection lives here rather than in main.go so wiring stays
// a single call.
//
// config.Load already validates the AI settings, so an unknown provider or
// missing required OpenAI field is normally caught before this is reached; the
// default branch here is a defensive backstop that still refuses to silently
// fall back to another provider.
func New(cfg config.AIConfig) (domain.Analyzer, error) {
	switch cfg.Provider {
	case config.ProviderRuleBased:
		return NewRuleBased(), nil
	case config.ProviderOpenAI:
		return NewOpenAI(cfg.OpenAIAPIKey, cfg.OpenAIModel, cfg.OpenAIBaseURL, cfg.OpenAITimeout), nil
	default:
		return nil, fmt.Errorf("unsupported AI provider %q", string(cfg.Provider))
	}
}
