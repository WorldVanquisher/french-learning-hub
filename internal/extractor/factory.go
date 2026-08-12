package extractor

import (
	"fmt"

	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
)

// New builds the domain.Extractor selected by configuration, or (nil, nil) when
// extraction is disabled. Disabled is the default: the server still starts and
// runs normally, and the application layer reports the extraction feature as
// unavailable rather than silently falling back to another provider. Provider
// selection lives here so wiring stays a single call.
//
// config.Load already validates the extractor settings, so a missing required
// OpenAI field is normally caught before this is reached; the default branch is
// a defensive backstop that refuses to silently pick a provider.
func New(cfg config.ExtractorConfig) (domain.Extractor, error) {
	switch cfg.Provider {
	case config.ExtractorDisabled:
		return nil, nil
	case config.ExtractorOpenAI:
		return NewOpenAI(cfg.OpenAIAPIKey, cfg.OpenAIModel, cfg.OpenAIBaseURL, cfg.OpenAITimeout), nil
	default:
		return nil, fmt.Errorf("unsupported extractor provider %q", string(cfg.Provider))
	}
}
