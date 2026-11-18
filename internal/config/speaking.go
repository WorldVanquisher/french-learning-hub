package config

import (
	"fmt"
	"net/url"
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
	// SpeakingLocal selects a local transcription service that speaks the same
	// multipart protocol (tools/speaking, flh_speaking_transcription_v1).
	// Transcription only; it needs no API key and has its own base URL and
	// timeout, so it can run beside OpenAI feedback.
	SpeakingLocal SpeakingProvider = "local"
)

// defaultSpeakingTranscriptionTimeout bounds one local transcription request.
const defaultSpeakingTranscriptionTimeout = 60 * time.Second

// SpeakingConfig holds the Speaking v1 provider selections and the OpenAI
// settings they reuse (OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_TIMEOUT).
// Feedback uses OPENAI_MODEL; transcription needs its own explicit
// SPEAKING_TRANSCRIPTION_MODEL. The key must never be logged or placed in errors.
type SpeakingConfig struct {
	Feedback           SpeakingProvider // SPEAKING_PROVIDER
	Transcription      SpeakingProvider // SPEAKING_TRANSCRIPTION_PROVIDER
	TranscriptionModel string           // SPEAKING_TRANSCRIPTION_MODEL
	// TranscriptionBaseURL and TranscriptionTimeout apply to the local
	// provider only (SPEAKING_TRANSCRIPTION_BASE_URL, SPEAKING_TRANSCRIPTION_TIMEOUT).
	TranscriptionBaseURL string
	TranscriptionTimeout time.Duration
	OpenAIAPIKey         string
	OpenAIModel          string
	OpenAIBaseURL        string
	OpenAITimeout        time.Duration
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
	case SpeakingLocal:
		if c.TranscriptionModel == "" {
			return fmt.Errorf("SPEAKING_TRANSCRIPTION_PROVIDER=local requires SPEAKING_TRANSCRIPTION_MODEL (the service's deployment_id)")
		}
		u, err := url.Parse(c.TranscriptionBaseURL)
		if c.TranscriptionBaseURL == "" || err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
			return fmt.Errorf("SPEAKING_TRANSCRIPTION_PROVIDER=local requires SPEAKING_TRANSCRIPTION_BASE_URL (an http or https URL)")
		}
		if c.TranscriptionTimeout <= 0 {
			return fmt.Errorf("SPEAKING_TRANSCRIPTION_TIMEOUT must be positive")
		}
	default:
		return fmt.Errorf("unknown SPEAKING_TRANSCRIPTION_PROVIDER %q (supported: disabled, openai, local)", string(c.Transcription))
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
