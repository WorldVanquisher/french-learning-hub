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

// ExtractorProvider selects which knowledge extractor the server wires in. It is
// deliberately decoupled from AIProvider: knowledge extraction is a separate,
// opt-in capability with its own on/off switch, so a deployment may run the
// rule-based analyzer and the OpenAI extractor at the same time (or neither).
type ExtractorProvider string

const (
	// ExtractorDisabled is the default. No extractor is wired in; the extraction
	// endpoints return a safe service-unavailable error rather than silently
	// falling back to another provider.
	ExtractorDisabled ExtractorProvider = "disabled"
	// ExtractorOpenAI selects the OpenAI-backed knowledge extractor (opt-in). It
	// reuses the OPENAI_* settings below.
	ExtractorOpenAI ExtractorProvider = "openai"
)

// EmbeddingProvider selects the text-to-vector implementation used only by the
// semantic retrieval baseline. It is independent of analyzer and extractor
// provider selection.
type EmbeddingProvider string

const (
	// EmbeddingDisabled is the default. The server starts without an embedding
	// service and does not register the semantic retriever.
	EmbeddingDisabled EmbeddingProvider = "disabled"
	// EmbeddingHTTP selects the generic OpenAI-compatible HTTP embedding client.
	// The endpoint may be remote, rented, or hosted on another local machine.
	EmbeddingHTTP EmbeddingProvider = "http"
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

	// Extractor holds knowledge-extractor configuration, independent of AI.
	Extractor ExtractorConfig

	// Embedding holds semantic-retrieval provider configuration, independent of
	// both the analyzer and extractor.
	Embedding EmbeddingConfig
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

// ExtractorConfig holds knowledge-extractor selection and its OpenAI settings.
// When Provider is openai it reuses the same OPENAI_* environment variables the
// analyzer reads, but it resolves and validates them independently so extractor
// wiring never depends on the analyzer's configuration. Secrets in this struct
// (OpenAIAPIKey) must never be logged or placed in error messages.
type ExtractorConfig struct {
	// Provider selects the extractor implementation. Defaults to disabled.
	Provider ExtractorProvider
	// OpenAIAPIKey authenticates OpenAI requests. Required only when Provider is
	// openai. Never has a default and must never be logged.
	OpenAIAPIKey string
	// OpenAIModel is the model identifier. Required when Provider is openai.
	OpenAIModel string
	// OpenAIBaseURL is the API base (default https://api.openai.com/v1).
	OpenAIBaseURL string
	// OpenAITimeout bounds a single provider request.
	OpenAITimeout time.Duration
}

// EmbeddingConfig holds the optional semantic-retrieval provider settings.
// APIKey is optional so a trusted local service can be used without credentials;
// when present it must never be logged or included in errors.
type EmbeddingConfig struct {
	Provider EmbeddingProvider
	APIKey   string
	Model    string
	BaseURL  string
	Timeout  time.Duration
}

const (
	defaultOpenAIBaseURL = "https://api.openai.com/v1"
	// defaultOpenAITimeout is deliberately below the default HTTP write
	// timeout (10s) so the provider request cannot normally exceed it.
	defaultOpenAITimeout    = 8 * time.Second
	defaultEmbeddingTimeout = 8 * time.Second
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
//	EMBEDDING_PROVIDER -> Embedding.Provider, default disabled
//	EMBEDDING_MODEL    -> Embedding.Model (required for http)
//	EMBEDDING_BASE_URL -> Embedding.BaseURL (required for http)
//	EMBEDDING_API_KEY  -> Embedding.APIKey (optional; never logged)
//	EMBEDDING_TIMEOUT  -> Embedding.Timeout (seconds), default 8
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
		Extractor: ExtractorConfig{
			Provider:      ExtractorProvider(getenv("EXTRACTOR_PROVIDER", string(ExtractorDisabled))),
			OpenAIAPIKey:  os.Getenv("OPENAI_API_KEY"),
			OpenAIModel:   strings.TrimSpace(os.Getenv("OPENAI_MODEL")),
			OpenAIBaseURL: getenv("OPENAI_BASE_URL", defaultOpenAIBaseURL),
			OpenAITimeout: getdur("OPENAI_TIMEOUT", defaultOpenAITimeout),
		},
		Embedding: EmbeddingConfig{
			Provider: EmbeddingProvider(getenv("EMBEDDING_PROVIDER", string(EmbeddingDisabled))),
			APIKey:   os.Getenv("EMBEDDING_API_KEY"),
			Model:    strings.TrimSpace(os.Getenv("EMBEDDING_MODEL")),
			BaseURL:  strings.TrimSpace(os.Getenv("EMBEDDING_BASE_URL")),
			Timeout:  getdur("EMBEDDING_TIMEOUT", defaultEmbeddingTimeout),
		},
	}

	if err := cfg.AI.validate(); err != nil {
		return Config{}, err
	}
	if err := cfg.Extractor.validate(); err != nil {
		return Config{}, err
	}
	if err := cfg.Embedding.validate(); err != nil {
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

// validate checks extractor selection and required OpenAI settings. It is
// independent of the analyzer configuration, so EXTRACTOR_PROVIDER=openai is
// valid regardless of AI_PROVIDER. Error messages never include the API key
// value. The default (disabled) requires nothing: the server runs normally and
// the extraction endpoints report the feature as unavailable.
func (c *ExtractorConfig) validate() error {
	switch c.Provider {
	case ExtractorDisabled:
		return nil
	case ExtractorOpenAI:
		if strings.TrimSpace(c.OpenAIAPIKey) == "" {
			return fmt.Errorf("EXTRACTOR_PROVIDER=openai requires OPENAI_API_KEY to be set")
		}
		if c.OpenAIModel == "" {
			return fmt.Errorf("EXTRACTOR_PROVIDER=openai requires OPENAI_MODEL to be set")
		}
		if strings.TrimSpace(c.OpenAIBaseURL) == "" {
			return fmt.Errorf("OPENAI_BASE_URL must not be empty")
		}
		return nil
	default:
		return fmt.Errorf("unknown EXTRACTOR_PROVIDER %q (supported: disabled, openai)", string(c.Provider))
	}
}

// validate checks semantic-retrieval provider selection independently. The
// default requires no model, endpoint, key, GPU, or external service.
func (c *EmbeddingConfig) validate() error {
	switch c.Provider {
	case EmbeddingDisabled:
		return nil
	case EmbeddingHTTP:
		if c.Model == "" {
			return fmt.Errorf("EMBEDDING_PROVIDER=http requires EMBEDDING_MODEL to be set")
		}
		if c.BaseURL == "" {
			return fmt.Errorf("EMBEDDING_PROVIDER=http requires EMBEDDING_BASE_URL to be set")
		}
		return nil
	default:
		return fmt.Errorf("unknown EMBEDDING_PROVIDER %q (supported: disabled, http)", string(c.Provider))
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
