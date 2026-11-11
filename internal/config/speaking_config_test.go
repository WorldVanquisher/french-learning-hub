package config

import (
	"strings"
	"testing"
	"time"
)

func TestLoad_SpeakingDefaultsToDisabledAndIsIndependent(t *testing.T) {
	clearAIEnv(t)
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Speaking.Feedback != SpeakingDisabled || cfg.Speaking.Transcription != SpeakingDisabled {
		t.Fatalf("default speaking providers = %+v", cfg.Speaking)
	}
	clearAIEnv(t)
	t.Setenv("EXTRACTOR_PROVIDER", "disabled")
	t.Setenv("SPEAKING_TRANSCRIPTION_PROVIDER", "openai")
	t.Setenv("SPEAKING_TRANSCRIPTION_MODEL", " gpt-transcribe ")
	t.Setenv("OPENAI_API_KEY", "sk-speaking-secret")
	t.Setenv("OPENAI_TIMEOUT", "12")
	cfg, err = Load()
	if err != nil {
		t.Fatal(err)
	}
	// Transcription alone needs no text model; feedback stays off; nothing else changes.
	if cfg.Speaking.Transcription != SpeakingOpenAI || cfg.Speaking.TranscriptionModel != "gpt-transcribe" || cfg.Speaking.Feedback != SpeakingDisabled ||
		cfg.Speaking.OpenAITimeout != 12*time.Second || cfg.Writing.Provider != WritingDisabled || cfg.AI.Provider != ProviderRuleBased {
		t.Fatalf("config = %+v", cfg.Speaking)
	}
}

func TestLoad_SpeakingRequiresKeyAndModelsWithoutLeakingKey(t *testing.T) {
	const secret = "sk-speaking-secret"
	for name, tc := range map[string]struct {
		env  map[string]string
		want string
	}{
		"feedback no key":         {map[string]string{"SPEAKING_PROVIDER": "openai", "OPENAI_MODEL": "m"}, "OPENAI_API_KEY"},
		"feedback no model":       {map[string]string{"SPEAKING_PROVIDER": "openai", "OPENAI_API_KEY": secret}, "SPEAKING_PROVIDER"},
		"feedback unknown":        {map[string]string{"SPEAKING_PROVIDER": "anthropic", "OPENAI_API_KEY": secret}, "SPEAKING_PROVIDER"},
		"transcription no key":    {map[string]string{"SPEAKING_TRANSCRIPTION_PROVIDER": "openai", "SPEAKING_TRANSCRIPTION_MODEL": "m"}, "OPENAI_API_KEY"},
		"transcription no model":  {map[string]string{"SPEAKING_TRANSCRIPTION_PROVIDER": "openai", "OPENAI_API_KEY": secret, "OPENAI_MODEL": "text-model"}, "SPEAKING_TRANSCRIPTION_MODEL"},
		"transcription unknown":   {map[string]string{"SPEAKING_TRANSCRIPTION_PROVIDER": "local", "OPENAI_API_KEY": secret}, "SPEAKING_TRANSCRIPTION_PROVIDER"},
		"transcription empty URL": {map[string]string{"SPEAKING_TRANSCRIPTION_PROVIDER": "openai", "SPEAKING_TRANSCRIPTION_MODEL": "m", "OPENAI_API_KEY": secret, "OPENAI_BASE_URL": " "}, "OPENAI_BASE_URL"},
	} {
		t.Run(name, func(t *testing.T) {
			clearAIEnv(t)
			t.Setenv("EXTRACTOR_PROVIDER", "disabled")
			for k, v := range tc.env {
				t.Setenv(k, v)
			}
			_, err := Load()
			if err == nil || !strings.Contains(err.Error(), tc.want) || strings.Contains(err.Error(), secret) {
				t.Fatalf("err = %v", err)
			}
		})
	}
}
