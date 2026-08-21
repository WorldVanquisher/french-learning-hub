// Package embedding contains replaceable text-to-vector provider adapters for
// semantic retrieval. Providers implement the narrow application boundary and
// own no retrieval, annotation, persistence, or resolution policy.
package embedding

import (
	"fmt"

	"french-learning-app/internal/application"
	"french-learning-app/internal/config"
)

// New constructs the independently configured embedding provider. Disabled is
// the default and returns nil without requiring a model, key, service, or GPU.
func New(cfg config.EmbeddingConfig) (application.EmbeddingProvider, error) {
	switch cfg.Provider {
	case config.EmbeddingDisabled:
		return nil, nil
	case config.EmbeddingHTTP:
		return NewHTTPProvider(cfg.APIKey, cfg.Model, cfg.BaseURL, cfg.Timeout), nil
	default:
		return nil, fmt.Errorf("unsupported embedding provider %q", string(cfg.Provider))
	}
}
