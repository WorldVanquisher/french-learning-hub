package listening

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptrace"
	"strings"
	"sync/atomic"
	"time"

	"french-learning-app/internal/domain"
)

// maxTelegramResponseBytes bounds the Bot API answer read into memory.
const maxTelegramResponseBytes = 64 << 10

// Telegram sends lesson-ready notices with the Telegram Bot API sendMessage
// method: one request per notice, no retry, no redirects. The token is part of
// the Bot API path, so no error ever includes the URL. The message is
// domain.LessonReadyNotice.Text(): the title only.
type Telegram struct {
	token   string
	chatID  string
	baseURL string
	client  *http.Client
}

var _ domain.ListeningNotifier = (*Telegram)(nil)

// NewTelegram builds the notifier. timeout bounds one request.
func NewTelegram(token, chatID, baseURL string, timeout time.Duration) *Telegram {
	return &Telegram{
		token: token, chatID: chatID, baseURL: strings.TrimRight(baseURL, "/"),
		client: &http.Client{
			Timeout:       timeout,
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		},
	}
}

// Channel names the notification channel.
func (t *Telegram) Channel() string { return "telegram" }

// NotifyLessonReady sends one message. The outcome is classified so that only
// a proven non-delivery is "failed":
//   - the request never left (connection refused, DNS): ErrNotificationNotSent;
//   - the Bot API answered with an error status or ok:false: ErrNotificationRefused;
//   - sent, then a timeout, a dropped connection or an unreadable 200 answer:
//     ErrNotificationNoResponse (the message may have been delivered).
func (t *Telegram) NotifyLessonReady(ctx context.Context, notice domain.LessonReadyNotice) error {
	raw, err := json.Marshal(map[string]any{"chat_id": t.chatID, "text": notice.Text()})
	if err != nil {
		return fmt.Errorf("%w: encode message", domain.ErrNotificationNotSent)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, t.baseURL+"/bot"+t.token+"/sendMessage", bytes.NewReader(raw))
	if err != nil {
		return fmt.Errorf("%w: build request", domain.ErrNotificationNotSent)
	}
	req.Header.Set("Content-Type", "application/json")
	var wrote atomic.Bool
	req = req.WithContext(httptrace.WithClientTrace(ctx, &httptrace.ClientTrace{
		WroteRequest: func(info httptrace.WroteRequestInfo) { wrote.Store(info.Err == nil) },
	}))
	resp, err := t.client.Do(req)
	if err != nil {
		if wrote.Load() {
			return fmt.Errorf("%w: no answer to the sent message", domain.ErrNotificationNoResponse)
		}
		return fmt.Errorf("%w: the request was not sent", domain.ErrNotificationNotSent)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxTelegramResponseBytes+1))
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("%w: HTTP %d", domain.ErrNotificationRefused, resp.StatusCode)
	}
	if err != nil || len(body) > maxTelegramResponseBytes {
		return fmt.Errorf("%w: unreadable answer", domain.ErrNotificationNoResponse)
	}
	var answer struct {
		OK *bool `json:"ok"`
	}
	if json.Unmarshal(body, &answer) != nil || answer.OK == nil {
		return fmt.Errorf("%w: malformed answer", domain.ErrNotificationNoResponse)
	}
	if !*answer.OK {
		return fmt.Errorf("%w: ok is false", domain.ErrNotificationRefused)
	}
	return nil
}
