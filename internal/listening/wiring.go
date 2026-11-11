package listening

import (
	"fmt"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
)

// deadlineMargin is added to an outside call's own timeout: an attempt left
// unfinished past it is reported as outcome unknown.
const deadlineMargin = 30 * time.Second

// NewServices builds the lesson and Daily Listening services from one
// configuration, with the generator, playlist source and notifier it selects.
// The server and the operator command both use it, so the button and the
// command run the same pull with the same deadlines.
func NewServices(cfg config.Config, repo application.ListeningStore) (*application.ListeningService, *application.ListeningDailyService, error) {
	generator, err := New(cfg.Listening)
	if err != nil {
		return nil, nil, err
	}
	source, err := NewPlaylistSource(cfg.ListeningDaily)
	if err != nil {
		return nil, nil, err
	}
	notifier, err := NewNotifier(cfg.ListeningDaily)
	if err != nil {
		return nil, nil, err
	}
	// The authored-script pack is validated here, so neither the server nor the
	// operator command starts with an invalid one.
	scripts, err := domain.ParseListeningScriptPack(ScriptPack())
	if err != nil {
		return nil, nil, fmt.Errorf("listening scripts: %w", err)
	}
	lessons := application.NewListeningService(repo, generator,
		application.WithPreparationDeadline(cfg.Listening.OpenAITimeout+deadlineMargin),
		application.WithListeningScripts(scripts))
	var budget time.Duration
	if source != nil {
		pages := (cfg.ListeningDaily.PlaylistMaxItems + domain.PlaylistPageSize - 1) / domain.PlaylistPageSize
		budget = time.Duration(pages) * cfg.ListeningDaily.YouTubeTimeout
	}
	daily := application.NewListeningDailyService(lessons, source, notifier, application.ListeningDailySettings{
		AutoPrepare:    cfg.ListeningDaily.AutoPrepare,
		Location:       cfg.ListeningDaily.Location,
		SourceBudget:   budget,
		NotifyDeadline: cfg.ListeningDaily.TelegramTimeout + deadlineMargin,
	})
	return lessons, daily, nil
}
