package listening

import (
	"fmt"

	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
)

// New builds the configured generator, or (nil, nil) when disabled (the
// default). There is no fallback provider.
func New(cfg config.ListeningConfig) (domain.ListeningExerciseGenerator, error) {
	switch cfg.Provider {
	case config.ListeningDisabled:
		return nil, nil
	case config.ListeningOpenAI:
		return NewOpenAI(cfg.OpenAIAPIKey, cfg.OpenAIModel, cfg.OpenAIBaseURL, cfg.OpenAITimeout), nil
	default:
		return nil, fmt.Errorf("unsupported listening provider %q", string(cfg.Provider))
	}
}

// NewPlaylistSource builds the configured Daily Listening playlist source, or
// (nil, nil) when disabled (the default).
func NewPlaylistSource(cfg config.ListeningDailyConfig) (domain.ListeningPlaylistSource, error) {
	switch cfg.Source {
	case config.ListeningSourceDisabled:
		return nil, nil
	case config.ListeningSourceYouTube:
		return NewYouTubePlaylist(cfg.YouTubeAPIKey, cfg.PlaylistID, cfg.YouTubeBaseURL, cfg.PlaylistMaxItems, cfg.YouTubeTimeout), nil
	default:
		return nil, fmt.Errorf("unsupported listening playlist source %q", string(cfg.Source))
	}
}

// NewNotifier builds the configured lesson-ready notifier, or (nil, nil) when
// disabled (the default).
func NewNotifier(cfg config.ListeningDailyConfig) (domain.ListeningNotifier, error) {
	switch cfg.Notify {
	case config.ListeningNotifyDisabled:
		return nil, nil
	case config.ListeningNotifyTelegram:
		return NewTelegram(cfg.TelegramBotToken, cfg.TelegramChatID, cfg.TelegramBaseURL, cfg.TelegramTimeout), nil
	default:
		return nil, fmt.Errorf("unsupported listening notifier %q", string(cfg.Notify))
	}
}
