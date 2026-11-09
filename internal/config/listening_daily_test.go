package config

import (
	"strings"
	"testing"
	"time"
)

func TestLoad_ListeningDailyDefaultsToOff(t *testing.T) {
	clearAIEnv(t)
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	d := cfg.ListeningDaily
	if d.Source != ListeningSourceDisabled || d.AutoPrepare || d.Notify != ListeningNotifyDisabled || d.PullEnabled() ||
		d.Timezone != "UTC" || d.Location == nil || d.PlaylistMaxItems != 50 {
		t.Fatalf("defaults = %+v", d)
	}
}

func dailyEnv(t *testing.T, extra map[string]string) {
	t.Helper()
	clearAIEnv(t)
	t.Setenv("EXTRACTOR_PROVIDER", "disabled")
	base := map[string]string{
		"LISTENING_PROVIDER":        "openai",
		"OPENAI_API_KEY":            "sk-daily-secret",
		"OPENAI_MODEL":              "m",
		"LISTENING_PLAYLIST_SOURCE": "youtube",
		"LISTENING_PLAYLIST_ID":     "PLflhDailyListening01",
		"YOUTUBE_API_KEY":           "yt-daily-secret",
		"LISTENING_AUTO_PREPARE":    "daily",
		"LISTENING_TIMEZONE":        "Europe/Paris",
		"LISTENING_NOTIFY":          "telegram",
		"TELEGRAM_BOT_TOKEN":        "123456:tg-daily-secret",
		"TELEGRAM_CHAT_ID":          "-1001234567890",
	}
	for k, v := range extra {
		base[k] = v
	}
	for k, v := range base {
		t.Setenv(k, v)
	}
}

func TestLoad_ListeningDailyFullConfiguration(t *testing.T) {
	dailyEnv(t, map[string]string{"YOUTUBE_TIMEOUT": "7", "TELEGRAM_TIMEOUT": "4", "LISTENING_PLAYLIST_MAX_ITEMS": "120"})
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	d := cfg.ListeningDaily
	if d.Source != ListeningSourceYouTube || !d.AutoPrepare || d.Notify != ListeningNotifyTelegram || !d.PullEnabled() ||
		d.Location.String() != "Europe/Paris" || d.YouTubeTimeout != 7*time.Second || d.TelegramTimeout != 4*time.Second ||
		d.PlaylistMaxItems != 120 || d.YouTubeBaseURL != "https://www.googleapis.com/youtube/v3" || d.TelegramBaseURL != "https://api.telegram.org" {
		t.Fatalf("config = %+v", d)
	}
}

func TestLoad_ListeningDailyRefusalsNeverEchoSecrets(t *testing.T) {
	secrets := []string{"sk-daily-secret", "yt-daily-secret", "tg-daily-secret", "-1001234567890"}
	cases := map[string]struct {
		env  map[string]string
		want string
	}{
		"unknown source":           {map[string]string{"LISTENING_PLAYLIST_SOURCE": "rss"}, "LISTENING_PLAYLIST_SOURCE"},
		"youtube without key":      {map[string]string{"YOUTUBE_API_KEY": ""}, "YOUTUBE_API_KEY"},
		"youtube without playlist": {map[string]string{"LISTENING_PLAYLIST_ID": ""}, "LISTENING_PLAYLIST_ID"},
		"malformed playlist":       {map[string]string{"LISTENING_PLAYLIST_ID": "PL/../x"}, "LISTENING_PLAYLIST_ID"},
		"bad youtube base url":     {map[string]string{"YOUTUBE_API_BASE_URL": "ftp://example"}, "YOUTUBE_API_BASE_URL"},
		"too many items":           {map[string]string{"LISTENING_PLAYLIST_MAX_ITEMS": "201"}, "LISTENING_PLAYLIST_MAX_ITEMS"},
		"no items":                 {map[string]string{"LISTENING_PLAYLIST_MAX_ITEMS": "0"}, "LISTENING_PLAYLIST_MAX_ITEMS"},
		"unknown auto prepare":     {map[string]string{"LISTENING_AUTO_PREPARE": "always"}, "LISTENING_AUTO_PREPARE"},
		"auto without generator":   {map[string]string{"LISTENING_PROVIDER": "disabled"}, "LISTENING_AUTO_PREPARE=daily requires LISTENING_PROVIDER=openai"},
		"bad timezone":             {map[string]string{"LISTENING_TIMEZONE": "Mars/Olympus"}, "LISTENING_TIMEZONE"},
		"local timezone":           {map[string]string{"LISTENING_TIMEZONE": "Local"}, "LISTENING_TIMEZONE"},
		"unknown notify":           {map[string]string{"LISTENING_NOTIFY": "email"}, "LISTENING_NOTIFY"},
		"notify without prepare":   {map[string]string{"LISTENING_AUTO_PREPARE": "disabled"}, "LISTENING_NOTIFY=telegram requires LISTENING_AUTO_PREPARE=daily"},
		"telegram without token":   {map[string]string{"TELEGRAM_BOT_TOKEN": ""}, "TELEGRAM_BOT_TOKEN"},
		"token with a path":        {map[string]string{"TELEGRAM_BOT_TOKEN": "123:tg-daily-secret/x"}, "TELEGRAM_BOT_TOKEN"},
		"telegram without chat":    {map[string]string{"TELEGRAM_CHAT_ID": ""}, "TELEGRAM_CHAT_ID"},
		"malformed chat":           {map[string]string{"TELEGRAM_CHAT_ID": "-1001234567890 x"}, "TELEGRAM_CHAT_ID"},
		"telegram base with query": {map[string]string{"TELEGRAM_API_BASE_URL": "https://example.test/?token=1"}, "TELEGRAM_API_BASE_URL"},
		"plain http telegram":      {map[string]string{"TELEGRAM_API_BASE_URL": "http://api.telegram.org"}, "TELEGRAM_API_BASE_URL must use https"},
		"plain http youtube":       {map[string]string{"YOUTUBE_API_BASE_URL": "http://10.0.0.5:8080/youtube/v3"}, "YOUTUBE_API_BASE_URL must use https"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			dailyEnv(t, c.env)
			_, err := Load()
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("err = %v, want it to mention %q", err, c.want)
			}
			for _, s := range secrets {
				if strings.Contains(err.Error(), s) {
					t.Fatalf("error %q echoes a secret or the chat ID", err)
				}
			}
		})
	}
}

func TestLoad_ListeningDailyAcceptsALoopbackTestServer(t *testing.T) {
	dailyEnv(t, map[string]string{"YOUTUBE_API_BASE_URL": "http://127.0.0.1:18991", "TELEGRAM_API_BASE_URL": "http://localhost:18993/"})
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.ListeningDaily.YouTubeBaseURL != "http://127.0.0.1:18991" || cfg.ListeningDaily.TelegramBaseURL != "http://localhost:18993" {
		t.Fatalf("config = %+v", cfg.ListeningDaily)
	}
}

func TestLoad_ListeningDailyPrepareWithoutSourceIsAPull(t *testing.T) {
	dailyEnv(t, map[string]string{"LISTENING_PLAYLIST_SOURCE": "disabled", "LISTENING_NOTIFY": "disabled"})
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.ListeningDaily.PullEnabled() || cfg.ListeningDaily.Source != ListeningSourceDisabled {
		t.Fatalf("config = %+v", cfg.ListeningDaily)
	}
}
