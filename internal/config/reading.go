package config

import (
	"fmt"
	"strings"
	"time"
)

// ReadingProvider selects the Exam Reading v1 exercise generator. It is
// independent of every other provider.
type ReadingProvider string

const (
	// ReadingDisabled is the default: lessons and authored examples work, and
	// generation answers 503.
	ReadingDisabled ReadingProvider = "disabled"
	// ReadingOpenAI selects the OpenAI-backed generator (opt-in).
	ReadingOpenAI ReadingProvider = "openai"
)

// ReadingConfig holds the reading generator selection and its OpenAI settings
// (reused from OPENAI_*). The key must never be logged or placed in errors.
type ReadingConfig struct {
	Provider      ReadingProvider
	OpenAIAPIKey  string
	OpenAIModel   string
	OpenAIBaseURL string
	OpenAITimeout time.Duration
}

func (c *ReadingConfig) validate() error {
	switch c.Provider {
	case ReadingDisabled:
		return nil
	case ReadingOpenAI:
		if strings.TrimSpace(c.OpenAIAPIKey) == "" {
			return fmt.Errorf("READING_PROVIDER=openai requires OPENAI_API_KEY to be set")
		}
		if c.OpenAIModel == "" {
			return fmt.Errorf("READING_PROVIDER=openai requires OPENAI_MODEL to be set")
		}
		if strings.TrimSpace(c.OpenAIBaseURL) == "" {
			return fmt.Errorf("OPENAI_BASE_URL must not be empty")
		}
		return nil
	default:
		return fmt.Errorf("unknown READING_PROVIDER %q (supported: disabled, openai)", string(c.Provider))
	}
}
