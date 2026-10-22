package config

import (
	"strings"
	"testing"
	"time"
)

func TestLoad_SuggestionDefaultsToDisabled(t *testing.T) {
	clearAIEnv(t)
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Suggestion.Provider != SuggestionDisabled {
		t.Fatalf("default suggestion provider = %q, want disabled", cfg.Suggestion.Provider)
	}
}

func TestLoad_SuggestionOpenAIIsIndependentAndReusesOpenAISettings(t *testing.T) {
	clearAIEnv(t)
	t.Setenv("EXTRACTOR_PROVIDER", "disabled")
	t.Setenv("SUGGESTION_PROVIDER", "openai")
	t.Setenv("OPENAI_API_KEY", "sk-test-secret")
	t.Setenv("OPENAI_MODEL", "gpt-test")
	t.Setenv("OPENAI_TIMEOUT", "20")
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	s := cfg.Suggestion
	if s.Provider != SuggestionOpenAI || s.OpenAIModel != "gpt-test" || s.OpenAITimeout != 20*time.Second ||
		s.OpenAIBaseURL == "" || cfg.AI.Provider != ProviderRuleBased {
		t.Fatalf("suggestion config = %+v (ai %q)", s, cfg.AI.Provider)
	}
}

func TestLoad_SuggestionRequiresKeyAndModelWithoutLeakingKey(t *testing.T) {
	const secret = "sk-suggestion-secret"
	for name, env := range map[string]map[string]string{
		"no key":   {"SUGGESTION_PROVIDER": "openai", "OPENAI_MODEL": "m"},
		"no model": {"SUGGESTION_PROVIDER": "openai", "OPENAI_API_KEY": secret},
		"unknown":  {"SUGGESTION_PROVIDER": "anthropic", "OPENAI_API_KEY": secret},
	} {
		t.Run(name, func(t *testing.T) {
			clearAIEnv(t)
			t.Setenv("EXTRACTOR_PROVIDER", "disabled")
			for k, v := range env {
				t.Setenv(k, v)
			}
			_, err := Load()
			if err == nil || !strings.Contains(err.Error(), "SUGGESTION_PROVIDER") || strings.Contains(err.Error(), secret) {
				t.Fatalf("err = %v", err)
			}
		})
	}
}
