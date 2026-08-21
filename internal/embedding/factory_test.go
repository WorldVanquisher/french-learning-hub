package embedding

import (
	"testing"
	"time"

	"french-learning-app/internal/config"
)

func TestNew_DisabledHTTPAndUnsupported(t *testing.T) {
	disabled, err := New(config.EmbeddingConfig{Provider: config.EmbeddingDisabled})
	if err != nil || disabled != nil {
		t.Fatalf("disabled provider = %v, err = %v", disabled, err)
	}

	provider, err := New(config.EmbeddingConfig{
		Provider: config.EmbeddingHTTP, Model: "multilingual-test",
		BaseURL: "https://embeddings.example/v1", Timeout: time.Second,
	})
	if err != nil || provider == nil || provider.Name() != "http:multilingual-test" {
		t.Fatalf("HTTP provider = %v, err = %v", provider, err)
	}

	if _, err := New(config.EmbeddingConfig{Provider: config.EmbeddingProvider("unknown")}); err == nil {
		t.Fatal("expected unsupported provider error")
	}
}
