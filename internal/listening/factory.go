package listening

import (
	"fmt"

	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
)

// New builds the configured generator, or (nil, nil) when disabled (the
// default). There is no fallback provider.
func New(cfg config.ListeningConfig) (domain.ListeningExerciseGenerator, error) {
	switch cfg.Provider {
	case config.ListeningDisabled:
		return nil, nil
	case config.ListeningOpenAI:
		return NewOpenAI(cfg.OpenAIAPIKey, cfg.OpenAIModel, cfg.OpenAIBaseURL, cfg.OpenAITimeout), nil
	default:
		return nil, fmt.Errorf("unsupported listening provider %q", string(cfg.Provider))
	}
}
