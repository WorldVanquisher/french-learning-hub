package writing

import (
	"fmt"

	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
)

// New builds the configured feedback generator, or (nil, nil) when disabled
// (the default). There is no fallback provider.
func New(cfg config.WritingConfig) (domain.WritingFeedbackGenerator, error) {
	switch cfg.Provider {
	case config.WritingDisabled:
		return nil, nil
	case config.WritingOpenAI:
		return NewOpenAI(cfg.OpenAIAPIKey, cfg.OpenAIModel, cfg.OpenAIBaseURL, cfg.OpenAITimeout), nil
	default:
		return nil, fmt.Errorf("unsupported writing provider %q", string(cfg.Provider))
	}
}
