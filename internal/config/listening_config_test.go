package config

import (
	"strings"
	"testing"
	"time"
)

func TestLoad_ListeningDefaultsToDisabled(t *testing.T) {
	clearAIEnv(t)
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Listening.Provider != ListeningDisabled {
		t.Fatalf("default listening provider = %q, want disabled", cfg.Listening.Provider)
	}
}

func TestLoad_ListeningOpenAIIsIndependentAndReusesOpenAISettings(t *testing.T) {
	clearAIEnv(t)
	t.Setenv("EXTRACTOR_PROVIDER", "disabled")
	t.Setenv("LISTENING_PROVIDER", "openai")
	t.Setenv("OPENAI_API_KEY", "sk-test-secret")
	t.Setenv("OPENAI_MODEL", "gpt-test")
	t.Setenv("OPENAI_TIMEOUT", "20")
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	l := cfg.Listening
	if l.Provider != ListeningOpenAI || l.OpenAIModel != "gpt-test" || l.OpenAITimeout != 20*time.Second || l.OpenAIBaseURL == "" ||
		cfg.AI.Provider != ProviderRuleBased || cfg.Suggestion.Provider != SuggestionDisabled {
		t.Fatalf("listening config = %+v (ai %q, suggestion %q)", l, cfg.AI.Provider, cfg.Suggestion.Provider)
	}
}

func TestLoad_ListeningRequiresKeyAndModelWithoutLeakingKey(t *testing.T) {
	const secret = "sk-listening-secret"
	for name, env := range map[string]map[string]string{
		"no key":   {"LISTENING_PROVIDER": "openai", "OPENAI_MODEL": "m"},
		"no model": {"LISTENING_PROVIDER": "openai", "OPENAI_API_KEY": secret},
		"unknown":  {"LISTENING_PROVIDER": "anthropic", "OPENAI_API_KEY": secret},
	} {
		t.Run(name, func(t *testing.T) {
			clearAIEnv(t)
			t.Setenv("EXTRACTOR_PROVIDER", "disabled")
			for k, v := range env {
				t.Setenv(k, v)
			}
			_, err := Load()
			if err == nil || !strings.Contains(err.Error(), "LISTENING_PROVIDER") || strings.Contains(err.Error(), secret) {
				t.Fatalf("err = %v", err)
			}
		})
	}
}
