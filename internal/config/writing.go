package config

import (
	"fmt"
	"strings"
	"time"
)

// WritingProvider selects the Exam Writing v1 feedback generator. It is
// independent of every other provider.
type WritingProvider string

const (
	// WritingDisabled is the default: tasks, drafts, revisions and comparison
	// work, and feedback answers 503.
	WritingDisabled WritingProvider = "disabled"
	// WritingOpenAI selects the OpenAI-backed generator (opt-in).
	WritingOpenAI WritingProvider = "openai"
)

// WritingConfig holds the writing feedback generator selection and its OpenAI settings
// (reused from OPENAI_*). The key must never be logged or placed in errors.
type WritingConfig struct {
	Provider      WritingProvider
	OpenAIAPIKey  string
	OpenAIModel   string
	OpenAIBaseURL string
	OpenAITimeout time.Duration
}

func (c *WritingConfig) validate() error {
	switch c.Provider {
	case WritingDisabled:
		return nil
	case WritingOpenAI:
		if strings.TrimSpace(c.OpenAIAPIKey) == "" {
			return fmt.Errorf("WRITING_PROVIDER=openai requires OPENAI_API_KEY to be set")
		}
		if c.OpenAIModel == "" {
			return fmt.Errorf("WRITING_PROVIDER=openai requires OPENAI_MODEL to be set")
		}
		if strings.TrimSpace(c.OpenAIBaseURL) == "" {
			return fmt.Errorf("OPENAI_BASE_URL must not be empty")
		}
		return nil
	default:
		return fmt.Errorf("unknown WRITING_PROVIDER %q (supported: disabled, openai)", string(c.Provider))
	}
}
