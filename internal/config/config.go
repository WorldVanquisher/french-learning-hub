// Package config loads runtime configuration from the environment, applying
// safe defaults for local development.
package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// AIProvider selects which analyzer implementation the server wires in.
type AIProvider string

const (
	// ProviderRuleBased is the default, local, no-cost analyzer. It calls no
	// external service.
	ProviderRuleBased AIProvider = "rule-based"
	// ProviderOpenAI selects the OpenAI-backed analyzer (opt-in).
	ProviderOpenAI AIProvider = "openai"
)

// Config holds the server's runtime settings.
type Config struct {
	// Addr is the TCP address the HTTP server listens on (e.g. ":8080").
	Addr string
	// DBPath is the filesystem path to the SQLite database file.
	DBPath string
	// ReadTimeout and WriteTimeout bound HTTP request handling.
	ReadTimeout  time.Duration
	WriteTimeout time.Duration

	// AI holds analyzer-provider configuration.
	AI AIConfig
}

// AIConfig holds analyzer-provider selection and OpenAI settings. Secrets in
// this struct (OpenAIAPIKey) must never be logged or placed in error messages.
type AIConfig struct {
	// Provider selects the analyzer implementation. Defaults to rule-based.
	Provider AIProvider
	// OpenAIAPIKey authenticates OpenAI requests. Required only when
	// Provider is openai. Never has a default and must never be logged.
	OpenAIAPIKey string
	// OpenAIModel is the model identifier. Required when Provider is openai.
	// Intentionally has no permanent application default.
	OpenAIModel string
	// OpenAIBaseURL is the API base (default https://api.openai.com/v1). Kept
	// configurable for tests and compatible gateways.
	OpenAIBaseURL string
	// OpenAITimeout bounds a single provider request. Kept below the HTTP
	// write timeout so a provider call cannot normally outlive the response
	// deadline.
	OpenAITimeout time.Duration
}

const (
	defaultOpenAIBaseURL = "https://api.openai.com/v1"
	// defaultOpenAITimeout is deliberately below the default HTTP write
	// timeout (10s) so the provider request cannot normally exceed it.
	defaultOpenAITimeout = 8 * time.Second
)

// Load builds a Config from environment variables, falling back to defaults
// suitable for local development, then validates it. It returns an error rather
// than silently selecting a provider when configuration is invalid (unknown
// AI_PROVIDER, or missing required OpenAI settings).
//
//	PORT             -> Addr (":" + PORT), default ":8080"
//	DB_PATH          -> DBPath, default "data/app.db"
//	AI_PROVIDER      -> AI.Provider, default "rule-based"
//	OPENAI_API_KEY   -> AI.OpenAIAPIKey (required for openai; never logged)
//	OPENAI_MODEL     -> AI.OpenAIModel (required for openai)
//	OPENAI_BASE_URL  -> AI.OpenAIBaseURL, default https://api.openai.com/v1
//	OPENAI_TIMEOUT   -> AI.OpenAITimeout (seconds), default 8
func Load() (Config, error) {
	cfg := Config{
		Addr:         ":" + getenv("PORT", "8080"),
		DBPath:       getenv("DB_PATH", "data/app.db"),
		ReadTimeout:  getdur("HTTP_READ_TIMEOUT", 10*time.Second),
		WriteTimeout: getdur("HTTP_WRITE_TIMEOUT", 10*time.Second),
		AI: AIConfig{
			Provider:      AIProvider(getenv("AI_PROVIDER", string(ProviderRuleBased))),
			OpenAIAPIKey:  os.Getenv("OPENAI_API_KEY"),
			OpenAIModel:   strings.TrimSpace(os.Getenv("OPENAI_MODEL")),
			OpenAIBaseURL: getenv("OPENAI_BASE_URL", defaultOpenAIBaseURL),
			OpenAITimeout: getdur("OPENAI_TIMEOUT", defaultOpenAITimeout),
		},
	}

	if err := cfg.AI.validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

// validate checks provider selection and required OpenAI settings. Error
// messages never include the API key value.
func (c *AIConfig) validate() error {
	switch c.Provider {
	case ProviderRuleBased:
		return nil
	case ProviderOpenAI:
		if strings.TrimSpace(c.OpenAIAPIKey) == "" {
			return fmt.Errorf("AI_PROVIDER=openai requires OPENAI_API_KEY to be set")
		}
		if c.OpenAIModel == "" {
			return fmt.Errorf("AI_PROVIDER=openai requires OPENAI_MODEL to be set")
		}
		if strings.TrimSpace(c.OpenAIBaseURL) == "" {
			return fmt.Errorf("OPENAI_BASE_URL must not be empty")
		}
		return nil
	default:
		return fmt.Errorf("unknown AI_PROVIDER %q (supported: rule-based, openai)", string(c.Provider))
	}
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getdur(key string, def time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if secs, err := strconv.Atoi(v); err == nil && secs > 0 {
			return time.Duration(secs) * time.Second
		}
	}
	return def
}
