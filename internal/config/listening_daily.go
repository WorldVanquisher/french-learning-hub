package config

import (
	"fmt"
	"net"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
	// The daily cap's local day needs IANA zone data even in a minimal image.
	_ "time/tzdata"
)

// ListeningSourceKind selects the Daily Listening playlist source.
type ListeningSourceKind string

const (
	// ListeningSourceDisabled is the default: no playlist is read.
	ListeningSourceDisabled ListeningSourceKind = "disabled"
	// ListeningSourceYouTube reads one playlist's official metadata through the
	// YouTube Data API (playlistItems.list). No media, captions or pages.
	ListeningSourceYouTube ListeningSourceKind = "youtube"
)

// ListeningNotifyKind selects the lesson-ready notification channel.
type ListeningNotifyKind string

const (
	// ListeningNotifyDisabled is the default: nothing is sent.
	ListeningNotifyDisabled ListeningNotifyKind = "disabled"
	// ListeningNotifyTelegram sends one Telegram Bot API message per lesson a
	// pull prepared.
	ListeningNotifyTelegram ListeningNotifyKind = "telegram"
)

const (
	defaultYouTubeBaseURL  = "https://www.googleapis.com/youtube/v3"
	defaultTelegramBaseURL = "https://api.telegram.org"
	defaultYouTubeTimeout  = 10 * time.Second
	defaultTelegramTimeout = 10 * time.Second
	defaultPlaylistItems   = 50
	maxPlaylistItems       = 200
)

// ListeningDailyConfig holds Daily Listening (pull, prepare, notify). Every part
// is off by default. The API key and bot token must never be logged or placed
// in error messages; neither is the chat ID echoed.
type ListeningDailyConfig struct {
	Source           ListeningSourceKind
	PlaylistID       string
	YouTubeAPIKey    string
	YouTubeBaseURL   string
	YouTubeTimeout   time.Duration
	PlaylistMaxItems int

	// AutoPrepare (LISTENING_AUTO_PREPARE=daily) lets a pull prepare at most one
	// lesson per local day with the listening generator.
	AutoPrepare bool
	Timezone    string
	Location    *time.Location

	Notify           ListeningNotifyKind
	TelegramBotToken string
	TelegramChatID   string
	TelegramBaseURL  string
	TelegramTimeout  time.Duration
}

// PullEnabled reports whether a pull has anything to do.
func (c ListeningDailyConfig) PullEnabled() bool {
	return c.Source != ListeningSourceDisabled || c.AutoPrepare
}

var (
	telegramChatID = regexp.MustCompile(`^(-?[0-9]{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$`)
	playlistID     = regexp.MustCompile(`^[A-Za-z0-9_-]{2,64}$`)
)

// loadListeningDaily reads and validates:
//
//	LISTENING_PLAYLIST_SOURCE  disabled (default) | youtube
//	LISTENING_PLAYLIST_ID      required for youtube
//	YOUTUBE_API_KEY            required for youtube (never logged)
//	YOUTUBE_API_BASE_URL       default https://www.googleapis.com/youtube/v3
//	YOUTUBE_TIMEOUT            seconds per request, default 10
//	LISTENING_PLAYLIST_MAX_ITEMS 1..200, default 50 (50 per request)
//	LISTENING_AUTO_PREPARE     disabled (default) | daily (needs LISTENING_PROVIDER=openai)
//	LISTENING_TIMEZONE         IANA zone for the daily cap, default UTC
//	LISTENING_NOTIFY           disabled (default) | telegram (needs LISTENING_AUTO_PREPARE=daily)
//	TELEGRAM_BOT_TOKEN         required for telegram (never logged)
//	TELEGRAM_CHAT_ID           required for telegram
//	TELEGRAM_API_BASE_URL      default https://api.telegram.org
//	TELEGRAM_TIMEOUT           seconds, default 10
func loadListeningDaily(src source, getenv func(string, string) string, getdur func(string, time.Duration) time.Duration, generator ListeningProvider) (ListeningDailyConfig, error) {
	c := ListeningDailyConfig{
		Source:           ListeningSourceKind(strings.TrimSpace(getenv("LISTENING_PLAYLIST_SOURCE", string(ListeningSourceDisabled)))),
		PlaylistID:       strings.TrimSpace(src.get("LISTENING_PLAYLIST_ID")),
		YouTubeAPIKey:    src.get("YOUTUBE_API_KEY"),
		YouTubeBaseURL:   strings.TrimRight(strings.TrimSpace(getenv("YOUTUBE_API_BASE_URL", defaultYouTubeBaseURL)), "/"),
		YouTubeTimeout:   getdur("YOUTUBE_TIMEOUT", defaultYouTubeTimeout),
		PlaylistMaxItems: defaultPlaylistItems,
		Timezone:         strings.TrimSpace(getenv("LISTENING_TIMEZONE", "UTC")),
		Notify:           ListeningNotifyKind(strings.TrimSpace(getenv("LISTENING_NOTIFY", string(ListeningNotifyDisabled)))),
		TelegramBotToken: src.get("TELEGRAM_BOT_TOKEN"),
		TelegramChatID:   strings.TrimSpace(src.get("TELEGRAM_CHAT_ID")),
		TelegramBaseURL:  strings.TrimRight(strings.TrimSpace(getenv("TELEGRAM_API_BASE_URL", defaultTelegramBaseURL)), "/"),
		TelegramTimeout:  getdur("TELEGRAM_TIMEOUT", defaultTelegramTimeout),
	}
	if v := strings.TrimSpace(src.get("LISTENING_PLAYLIST_MAX_ITEMS")); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 1 || n > maxPlaylistItems {
			return c, fmt.Errorf("LISTENING_PLAYLIST_MAX_ITEMS must be a whole number from 1 to %d", maxPlaylistItems)
		}
		c.PlaylistMaxItems = n
	}

	switch c.Source {
	case ListeningSourceDisabled:
	case ListeningSourceYouTube:
		if strings.TrimSpace(c.YouTubeAPIKey) == "" {
			return c, fmt.Errorf("LISTENING_PLAYLIST_SOURCE=youtube requires YOUTUBE_API_KEY to be set")
		}
		if !playlistID.MatchString(c.PlaylistID) {
			return c, fmt.Errorf("LISTENING_PLAYLIST_SOURCE=youtube requires LISTENING_PLAYLIST_ID to be a YouTube playlist ID")
		}
		if err := httpBaseURL("YOUTUBE_API_BASE_URL", c.YouTubeBaseURL); err != nil {
			return c, err
		}
	default:
		return c, fmt.Errorf("unknown LISTENING_PLAYLIST_SOURCE %q (supported: disabled, youtube)", string(c.Source))
	}

	switch auto := strings.TrimSpace(getenv("LISTENING_AUTO_PREPARE", "disabled")); auto {
	case "disabled":
	case "daily":
		if generator != ListeningOpenAI {
			return c, fmt.Errorf("LISTENING_AUTO_PREPARE=daily requires LISTENING_PROVIDER=openai")
		}
		c.AutoPrepare = true
	default:
		return c, fmt.Errorf("unknown LISTENING_AUTO_PREPARE %q (supported: disabled, daily)", auto)
	}

	loc, err := time.LoadLocation(c.Timezone)
	if err != nil || c.Timezone == "" || c.Timezone == "Local" {
		return c, fmt.Errorf("LISTENING_TIMEZONE must be an IANA time zone name such as Europe/Paris")
	}
	c.Location = loc

	switch c.Notify {
	case ListeningNotifyDisabled:
	case ListeningNotifyTelegram:
		if !c.AutoPrepare {
			return c, fmt.Errorf("LISTENING_NOTIFY=telegram requires LISTENING_AUTO_PREPARE=daily (only a lesson a pull prepared is announced)")
		}
		if strings.TrimSpace(c.TelegramBotToken) == "" || strings.ContainsAny(c.TelegramBotToken, " \t\r\n/?#") {
			return c, fmt.Errorf("LISTENING_NOTIFY=telegram requires TELEGRAM_BOT_TOKEN to be set to a bot token")
		}
		if !telegramChatID.MatchString(c.TelegramChatID) {
			return c, fmt.Errorf("LISTENING_NOTIFY=telegram requires TELEGRAM_CHAT_ID to be a numeric chat ID or an @channel name")
		}
		if err := httpBaseURL("TELEGRAM_API_BASE_URL", c.TelegramBaseURL); err != nil {
			return c, err
		}
	default:
		return c, fmt.Errorf("unknown LISTENING_NOTIFY %q (supported: disabled, telegram)", string(c.Notify))
	}
	return c, nil
}

// httpBaseURL accepts an absolute https URL without credentials, query or
// fragment. Plain http is accepted only for a loopback host (a local test
// server): these URLs carry an API key or a bot token.
func httpBaseURL(key, raw string) error {
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return fmt.Errorf("%s must be an absolute https URL without credentials, query or fragment", key)
	}
	if u.Scheme == "http" {
		host := u.Hostname()
		if ip := net.ParseIP(host); host != "localhost" && (ip == nil || !ip.IsLoopback()) {
			return fmt.Errorf("%s must use https (plain http is accepted only for a loopback test server)", key)
		}
	}
	return nil
}
