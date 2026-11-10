package config

import (
	"strings"
	"testing"
	"time"
)

func TestLoad_WritingDefaultsToDisabledAndIsIndependent(t *testing.T) {
	clearAIEnv(t)
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Writing.Provider != WritingDisabled {
		t.Fatalf("default writing provider = %q", cfg.Writing.Provider)
	}
	clearAIEnv(t)
	t.Setenv("EXTRACTOR_PROVIDER", "disabled")
	t.Setenv("WRITING_PROVIDER", "openai")
	t.Setenv("OPENAI_API_KEY", "sk-writing-secret")
	t.Setenv("OPENAI_MODEL", "gpt-test")
	t.Setenv("OPENAI_TIMEOUT", "12")
	cfg, err = Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Writing.Provider != WritingOpenAI || cfg.Writing.OpenAITimeout != 12*time.Second || cfg.Listening.Provider != ListeningDisabled || cfg.AI.Provider != ProviderRuleBased {
		t.Fatalf("config = %+v", cfg.Writing)
	}
}

func TestLoad_WritingRequiresKeyAndModelWithoutLeakingKey(t *testing.T) {
	const secret = "sk-writing-secret"
	for name, env := range map[string]map[string]string{
		"no key":   {"WRITING_PROVIDER": "openai", "OPENAI_MODEL": "m"},
		"no model": {"WRITING_PROVIDER": "openai", "OPENAI_API_KEY": secret},
		"unknown":  {"WRITING_PROVIDER": "anthropic", "OPENAI_API_KEY": secret},
	} {
		t.Run(name, func(t *testing.T) {
			clearAIEnv(t)
			t.Setenv("EXTRACTOR_PROVIDER", "disabled")
			for k, v := range env {
				t.Setenv(k, v)
			}
			_, err := Load()
			if err == nil || !strings.Contains(err.Error(), "WRITING_PROVIDER") || strings.Contains(err.Error(), secret) {
				t.Fatalf("err = %v", err)
			}
		})
	}
}
