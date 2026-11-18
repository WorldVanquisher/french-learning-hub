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
		"transcription unknown":   {map[string]string{"SPEAKING_TRANSCRIPTION_PROVIDER": "whisper", "OPENAI_API_KEY": secret}, "SPEAKING_TRANSCRIPTION_PROVIDER"},
		"local no model":          {map[string]string{"SPEAKING_TRANSCRIPTION_PROVIDER": "local", "SPEAKING_TRANSCRIPTION_BASE_URL": "http://127.0.0.1:8765/v1"}, "SPEAKING_TRANSCRIPTION_MODEL"},
		"local no base URL":       {map[string]string{"SPEAKING_TRANSCRIPTION_PROVIDER": "local", "SPEAKING_TRANSCRIPTION_MODEL": "m"}, "SPEAKING_TRANSCRIPTION_BASE_URL"},
		"local bad base URL":      {map[string]string{"SPEAKING_TRANSCRIPTION_PROVIDER": "local", "SPEAKING_TRANSCRIPTION_MODEL": "m", "SPEAKING_TRANSCRIPTION_BASE_URL": "127.0.0.1:8765"}, "SPEAKING_TRANSCRIPTION_BASE_URL"},
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

func TestLoad_SpeakingLocalTranscriptionNeedsNoKeyAndRunsBesideOpenAIFeedback(t *testing.T) {
	clearAIEnv(t)
	t.Setenv("EXTRACTOR_PROVIDER", "disabled")
	t.Setenv("SPEAKING_TRANSCRIPTION_PROVIDER", "local")
	t.Setenv("SPEAKING_TRANSCRIPTION_MODEL", "whisper-base@e37978b90ca9/flh_speaking_transcribe_v1/cpu-fp32/0123456789abcdef")
	t.Setenv("SPEAKING_TRANSCRIPTION_BASE_URL", "http://127.0.0.1:8765/v1")
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Speaking.Transcription != SpeakingLocal || cfg.Speaking.TranscriptionTimeout != 60*time.Second || cfg.Speaking.TranscriptionBaseURL != "http://127.0.0.1:8765/v1" {
		t.Fatalf("config = %+v", cfg.Speaking)
	}
	t.Setenv("SPEAKING_PROVIDER", "openai")
	t.Setenv("OPENAI_API_KEY", "sk-speaking-secret")
	t.Setenv("OPENAI_MODEL", "text-model")
	t.Setenv("SPEAKING_TRANSCRIPTION_TIMEOUT", "90")
	cfg, err = Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Speaking.Feedback != SpeakingOpenAI || cfg.Speaking.OpenAIBaseURL == cfg.Speaking.TranscriptionBaseURL || cfg.Speaking.TranscriptionTimeout != 90*time.Second {
		t.Fatalf("config = %+v", cfg.Speaking)
	}
}
