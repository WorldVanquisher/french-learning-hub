package suggester

import (
	"fmt"

	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
)

// New builds the configured suggester, or (nil, nil) when disabled (the
// default). There is no fallback provider.
func New(cfg config.SuggestionConfig) (domain.ConceptSuggester, error) {
	switch cfg.Provider {
	case config.SuggestionDisabled:
		return nil, nil
	case config.SuggestionOpenAI:
		return NewOpenAI(cfg.OpenAIAPIKey, cfg.OpenAIModel, cfg.OpenAIBaseURL, cfg.OpenAITimeout), nil
	default:
		return nil, fmt.Errorf("unsupported suggestion provider %q", string(cfg.Provider))
	}
}
