package speaking

import (
	"fmt"

	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
)

// New builds the configured transcriber and feedback generator. Either is nil
// when disabled (the default). There is no fallback provider.
func New(cfg config.SpeakingConfig) (domain.SpeakingTranscriber, domain.SpeakingFeedbackGenerator, error) {
	var tr domain.SpeakingTranscriber
	var gen domain.SpeakingFeedbackGenerator
	switch cfg.Transcription {
	case config.SpeakingDisabled:
	case config.SpeakingOpenAI:
		tr = NewTranscriber(cfg.OpenAIAPIKey, cfg.TranscriptionModel, cfg.OpenAIBaseURL, cfg.OpenAITimeout)
	default:
		return nil, nil, fmt.Errorf("unsupported speaking transcription provider %q", string(cfg.Transcription))
	}
	switch cfg.Feedback {
	case config.SpeakingDisabled:
	case config.SpeakingOpenAI:
		gen = NewOpenAI(cfg.OpenAIAPIKey, cfg.OpenAIModel, cfg.OpenAIBaseURL, cfg.OpenAITimeout)
	default:
		return nil, nil, fmt.Errorf("unsupported speaking feedback provider %q", string(cfg.Feedback))
	}
	return tr, gen, nil
}
