package config

import (
	"strings"
	"testing"
	"time"
)

func TestLoad_ReadingDefaultsToDisabledAndIsIndependent(t *testing.T) {
	clearAIEnv(t)
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Reading.Provider != ReadingDisabled {
		t.Fatalf("default reading provider = %q", cfg.Reading.Provider)
	}
	clearAIEnv(t)
	t.Setenv("EXTRACTOR_PROVIDER", "disabled")
	t.Setenv("READING_PROVIDER", "openai")
	t.Setenv("OPENAI_API_KEY", "sk-reading-secret")
	t.Setenv("OPENAI_MODEL", "gpt-test")
	t.Setenv("OPENAI_TIMEOUT", "12")
	cfg, err = Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Reading.Provider != ReadingOpenAI || cfg.Reading.OpenAITimeout != 12*time.Second || cfg.Listening.Provider != ListeningDisabled || cfg.AI.Provider != ProviderRuleBased {
		t.Fatalf("config = %+v", cfg.Reading)
	}
}

func TestLoad_ReadingRequiresKeyAndModelWithoutLeakingKey(t *testing.T) {
	const secret = "sk-reading-secret"
	for name, env := range map[string]map[string]string{
		"no key":   {"READING_PROVIDER": "openai", "OPENAI_MODEL": "m"},
		"no model": {"READING_PROVIDER": "openai", "OPENAI_API_KEY": secret},
		"unknown":  {"READING_PROVIDER": "anthropic", "OPENAI_API_KEY": secret},
	} {
		t.Run(name, func(t *testing.T) {
			clearAIEnv(t)
			t.Setenv("EXTRACTOR_PROVIDER", "disabled")
			for k, v := range env {
				t.Setenv(k, v)
			}
			_, err := Load()
			if err == nil || !strings.Contains(err.Error(), "READING_PROVIDER") || strings.Contains(err.Error(), secret) {
				t.Fatalf("err = %v", err)
			}
		})
	}
}
