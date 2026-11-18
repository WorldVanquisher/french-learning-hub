package main

import (
	"testing"
	"time"

	"french-learning-app/internal/config"
)

func TestSpeakingDeadlineCoversTheLocalTranscriptionTimeout(t *testing.T) {
	base := config.SpeakingConfig{OpenAITimeout: 8 * time.Second, TranscriptionTimeout: 120 * time.Second}
	if got := speakingDeadline(base); got != 38*time.Second {
		t.Fatalf("openai/disabled deadline = %v", got)
	}
	base.Transcription = config.SpeakingLocal
	if got := speakingDeadline(base); got != 150*time.Second {
		t.Fatalf("local deadline = %v", got)
	}
}
