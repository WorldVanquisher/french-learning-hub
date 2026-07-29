package config

import (
	"strings"
	"testing"
	"time"
)

// clearAIEnv sets all AI-related environment variables to empty for the test,
// so results do not depend on the host environment. t.Setenv restores them
// automatically at the end of the test.
func clearAIEnv(t *testing.T) {
	t.Helper()
	for _, k := range []string{
		"AI_PROVIDER", "OPENAI_API_KEY", "OPENAI_MODEL",
		"OPENAI_BASE_URL", "OPENAI_TIMEOUT",
	} {
		t.Setenv(k, "")
	}
}

func TestLoad_DefaultProviderIsRuleBased(t *testing.T) {
	clearAIEnv(t)

	cfg, err := Load()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.AI.Provider != ProviderRuleBased {
		t.Fatalf("default provider = %q, want %q", cfg.AI.Provider, ProviderRuleBased)
	}
}

func TestLoad_OpenAIConfigLoads(t *testing.T) {
	clearAIEnv(t)
	t.Setenv("AI_PROVIDER", "openai")
	t.Setenv("OPENAI_API_KEY", "sk-test-secret")
	t.Setenv("OPENAI_MODEL", "gpt-test")
	t.Setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
	t.Setenv("OPENAI_TIMEOUT", "5")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.AI.Provider != ProviderOpenAI {
		t.Fatalf("provider = %q, want openai", cfg.AI.Provider)
	}
	if cfg.AI.OpenAIAPIKey != "sk-test-secret" {
		t.Fatalf("api key not loaded")
	}
	if cfg.AI.OpenAIModel != "gpt-test" {
		t.Fatalf("model = %q, want gpt-test", cfg.AI.OpenAIModel)
	}
	if cfg.AI.OpenAIBaseURL != "https://gateway.example/v1" {
		t.Fatalf("base url = %q", cfg.AI.OpenAIBaseURL)
	}
	if cfg.AI.OpenAITimeout != 5*time.Second {
		t.Fatalf("timeout = %v, want 5s", cfg.AI.OpenAITimeout)
	}
}

func TestLoad_OpenAIDefaultsBaseURLAndTimeout(t *testing.T) {
	clearAIEnv(t)
	t.Setenv("AI_PROVIDER", "openai")
	t.Setenv("OPENAI_API_KEY", "sk-test")
	t.Setenv("OPENAI_MODEL", "gpt-test")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.AI.OpenAIBaseURL != defaultOpenAIBaseURL {
		t.Fatalf("base url = %q, want default %q", cfg.AI.OpenAIBaseURL, defaultOpenAIBaseURL)
	}
	if cfg.AI.OpenAITimeout != defaultOpenAITimeout {
		t.Fatalf("timeout = %v, want default %v", cfg.AI.OpenAITimeout, defaultOpenAITimeout)
	}
	// The provider timeout must stay below the default HTTP write timeout so a
	// provider request cannot normally outlive the response deadline.
	if cfg.AI.OpenAITimeout >= cfg.WriteTimeout {
		t.Fatalf("provider timeout %v must be < HTTP write timeout %v", cfg.AI.OpenAITimeout, cfg.WriteTimeout)
	}
}

func TestLoad_OpenAIWithoutAPIKeyFails(t *testing.T) {
	clearAIEnv(t)
	t.Setenv("AI_PROVIDER", "openai")
	t.Setenv("OPENAI_MODEL", "gpt-test")

	_, err := Load()
	if err == nil {
		t.Fatal("expected error when OPENAI_API_KEY is missing")
	}
	if !strings.Contains(err.Error(), "OPENAI_API_KEY") {
		t.Fatalf("error should mention OPENAI_API_KEY, got %q", err.Error())
	}
}

func TestLoad_OpenAIWithoutModelFails(t *testing.T) {
	clearAIEnv(t)
	t.Setenv("AI_PROVIDER", "openai")
	t.Setenv("OPENAI_API_KEY", "sk-test")

	_, err := Load()
	if err == nil {
		t.Fatal("expected error when OPENAI_MODEL is missing")
	}
	if !strings.Contains(err.Error(), "OPENAI_MODEL") {
		t.Fatalf("error should mention OPENAI_MODEL, got %q", err.Error())
	}
}

func TestLoad_UnknownProviderFails(t *testing.T) {
	clearAIEnv(t)
	t.Setenv("AI_PROVIDER", "banana")

	_, err := Load()
	if err == nil {
		t.Fatal("expected error for unknown provider")
	}
	if !strings.Contains(err.Error(), "banana") {
		t.Fatalf("error should name the unknown provider, got %q", err.Error())
	}
}

// TestLoad_ErrorDoesNotLeakAPIKey ensures the API key value never appears in a
// formatted validation error, even when other required settings are missing.
func TestLoad_ErrorDoesNotLeakAPIKey(t *testing.T) {
	clearAIEnv(t)
	const secret = "sk-super-secret-value"
	t.Setenv("AI_PROVIDER", "openai")
	t.Setenv("OPENAI_API_KEY", secret)
	// Model missing -> validation fails.

	_, err := Load()
	if err == nil {
		t.Fatal("expected validation error")
	}
	if strings.Contains(err.Error(), secret) {
		t.Fatalf("error message leaked the API key: %q", err.Error())
	}
}
