package config

import (
	"fmt"
	"strings"
	"time"
)

// SpeakingProvider selects one Speaking v1 provider. Transcription and feedback
// are chosen separately, and both are independent of every other provider.
type SpeakingProvider string

const (
	// SpeakingDisabled is the default. With transcription disabled, a take's
	// transcript is typed; with feedback disabled, the request answers 503.
	// Recording, playback, typed transcripts and comparison always work.
	SpeakingDisabled SpeakingProvider = "disabled"
	// SpeakingOpenAI selects the OpenAI-backed implementation (opt-in).
	SpeakingOpenAI SpeakingProvider = "openai"
)

// SpeakingConfig holds the Speaking v1 provider selections and the OpenAI
// settings they reuse (OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_TIMEOUT).
// Feedback uses OPENAI_MODEL; transcription needs its own explicit
// SPEAKING_TRANSCRIPTION_MODEL. The key must never be logged or placed in errors.
type SpeakingConfig struct {
	Feedback           SpeakingProvider // SPEAKING_PROVIDER
	Transcription      SpeakingProvider // SPEAKING_TRANSCRIPTION_PROVIDER
	TranscriptionModel string           // SPEAKING_TRANSCRIPTION_MODEL
	OpenAIAPIKey       string
	OpenAIModel        string
	OpenAIBaseURL      string
	OpenAITimeout      time.Duration
}

func (c *SpeakingConfig) validate() error {
	needKey := false
	switch c.Feedback {
	case SpeakingDisabled:
	case SpeakingOpenAI:
		needKey = true
		if c.OpenAIModel == "" {
			return fmt.Errorf("SPEAKING_PROVIDER=openai requires OPENAI_MODEL to be set")
		}
	default:
		return fmt.Errorf("unknown SPEAKING_PROVIDER %q (supported: disabled, openai)", string(c.Feedback))
	}
	switch c.Transcription {
	case SpeakingDisabled:
	case SpeakingOpenAI:
		needKey = true
		if c.TranscriptionModel == "" {
			return fmt.Errorf("SPEAKING_TRANSCRIPTION_PROVIDER=openai requires SPEAKING_TRANSCRIPTION_MODEL to be set")
		}
	default:
		return fmt.Errorf("unknown SPEAKING_TRANSCRIPTION_PROVIDER %q (supported: disabled, openai)", string(c.Transcription))
	}
	if needKey {
		if strings.TrimSpace(c.OpenAIAPIKey) == "" {
			return fmt.Errorf("an openai Speaking provider requires OPENAI_API_KEY to be set")
		}
		if strings.TrimSpace(c.OpenAIBaseURL) == "" {
			return fmt.Errorf("OPENAI_BASE_URL must not be empty")
		}
	}
	return nil
}
