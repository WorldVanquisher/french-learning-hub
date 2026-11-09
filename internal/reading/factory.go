package reading

import (
	"fmt"

	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
)

// New builds the configured generator, or (nil, nil) when disabled (the
// default). There is no fallback provider.
func New(cfg config.ReadingConfig) (domain.ReadingExerciseGenerator, error) {
	switch cfg.Provider {
	case config.ReadingDisabled:
		return nil, nil
	case config.ReadingOpenAI:
		return NewOpenAI(cfg.OpenAIAPIKey, cfg.OpenAIModel, cfg.OpenAIBaseURL, cfg.OpenAITimeout), nil
	default:
		return nil, fmt.Errorf("unsupported reading provider %q", string(cfg.Provider))
	}
}
