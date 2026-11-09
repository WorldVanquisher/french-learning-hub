// Package listeningfake holds local stand-ins for the three outside services
// Daily Listening talks to: the YouTube Data API playlistItems.list, the OpenAI
// Responses API, and the Telegram Bot API sendMessage. Tests only: each is an
// httptest server on loopback that records what it received and can be told to
// fail, hang, or drop the connection after reading the request (a lost
// response). Nothing here contacts a real service.
package listeningfake

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

// Modes shared by the fakes.
const (
	ModeOK        = "ok"
	ModeStatus    = "status"    // answer with Status
	ModeHang      = "hang"      // wait Delay (or until the client gives up), then answer
	ModeDrop      = "drop"      // read the request, then close the connection without an answer
	ModeMalformed = "malformed" // 200 with a body that is not the expected JSON
)

type base struct {
	mu     sync.Mutex
	mode   string
	status int
	delay  time.Duration
	calls  int
	// Arrived receives one value per request, without blocking.
	Arrived chan struct{}
	Server  *httptest.Server
}

// Set changes how the next requests are answered.
func (b *base) Set(mode string, status int, delay time.Duration) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.mode, b.status, b.delay = mode, status, delay
}

// Calls counts requests received.
func (b *base) Calls() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.calls
}

// URL is the server's base URL.
func (b *base) URL() string { return b.Server.URL }

// arrive counts a request and returns the current behaviour. It returns false
// when the request was already handled (dropped, or the client went away).
func (b *base) arrive(w http.ResponseWriter, r *http.Request) (status int, ok bool) {
	b.mu.Lock()
	b.calls++
	mode, st, delay := b.mode, b.status, b.delay
	b.mu.Unlock()
	_, _ = io.Copy(io.Discard, r.Body)
	select {
	case b.Arrived <- struct{}{}:
	default:
	}
	switch mode {
	case ModeHang:
		select {
		case <-time.After(delay):
		case <-r.Context().Done():
			return 0, false
		}
	case ModeDrop:
		if hj, ok := w.(http.Hijacker); ok {
			if conn, _, err := hj.Hijack(); err == nil {
				_ = conn.Close()
			}
		}
		return 0, false
	case ModeStatus:
		w.WriteHeader(st)
		_, _ = w.Write([]byte(`{"error":{"message":"fake failure"}}`))
		return 0, false
	case ModeMalformed:
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`not json`))
		return 0, false
	}
	return http.StatusOK, true
}

func newBase() base {
	return base{mode: ModeOK, status: http.StatusOK, Arrived: make(chan struct{}, 64)}
}

// ---- YouTube Data API v3 playlistItems.list ----

// Video is one playlist entry the fake returns.
type Video struct {
	ID          string
	Title       string
	Privacy     string // public (default), unlisted, private
	PublishedAt string // RFC 3339, optional
}

// YouTube stands in for playlistItems.list. It pages by maxResults and checks
// the API key header.
type YouTube struct {
	base
	key      string
	videos   []Video
	queries  []url.Values
	keyInURL bool
}

// NewYouTube starts the fake. key is the X-Goog-Api-Key it accepts.
func NewYouTube(t testing.TB, key string, videos ...Video) *YouTube {
	y := &YouTube{base: newBase(), key: key, videos: videos}
	y.Server = httptest.NewServer(http.HandlerFunc(y.handle))
	t.Cleanup(y.Server.Close)
	return y
}

// SetVideos replaces the playlist.
func (y *YouTube) SetVideos(videos ...Video) {
	y.mu.Lock()
	defer y.mu.Unlock()
	y.videos = videos
}

// Queries returns the query of every request.
func (y *YouTube) Queries() []url.Values {
	y.mu.Lock()
	defer y.mu.Unlock()
	return append([]url.Values{}, y.queries...)
}

// KeyInURL reports whether any request carried the key in its URL.
func (y *YouTube) KeyInURL() bool {
	y.mu.Lock()
	defer y.mu.Unlock()
	return y.keyInURL
}

func (y *YouTube) handle(w http.ResponseWriter, r *http.Request) {
	y.mu.Lock()
	y.queries = append(y.queries, r.URL.Query())
	if y.key != "" && strings.Contains(r.URL.RawQuery, y.key) {
		y.keyInURL = true
	}
	y.mu.Unlock()
	if _, ok := y.arrive(w, r); !ok {
		return
	}
	if r.Method != http.MethodGet || r.URL.Path != "/playlistItems" {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	if r.Header.Get("X-Goog-Api-Key") != y.key {
		w.WriteHeader(http.StatusForbidden)
		_, _ = w.Write([]byte(`{"error":{"code":403}}`))
		return
	}
	q := r.URL.Query()
	size, _ := strconv.Atoi(q.Get("maxResults"))
	start := 0
	if tok := q.Get("pageToken"); tok != "" {
		start, _ = strconv.Atoi(strings.TrimPrefix(tok, "page"))
	}
	y.mu.Lock()
	videos := y.videos
	y.mu.Unlock()
	type item struct {
		Snippet struct {
			Title    string `json:"title"`
			Position int    `json:"position"`
		} `json:"snippet"`
		ContentDetails struct {
			VideoID          string `json:"videoId"`
			VideoPublishedAt string `json:"videoPublishedAt,omitempty"`
		} `json:"contentDetails"`
		Status struct {
			PrivacyStatus string `json:"privacyStatus"`
		} `json:"status"`
	}
	page := struct {
		NextPageToken string `json:"nextPageToken,omitempty"`
		Items         []item `json:"items"`
	}{Items: []item{}}
	for i := start; i < len(videos) && i < start+size; i++ {
		var it item
		it.Snippet.Title, it.Snippet.Position = videos[i].Title, i
		it.ContentDetails.VideoID, it.ContentDetails.VideoPublishedAt = videos[i].ID, videos[i].PublishedAt
		it.Status.PrivacyStatus = videos[i].Privacy
		if it.Status.PrivacyStatus == "" {
			it.Status.PrivacyStatus = "public"
		}
		page.Items = append(page.Items, it)
	}
	if start+size < len(videos) {
		page.NextPageToken = fmt.Sprintf("page%d", start+size)
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(page)
}

// ---- OpenAI Responses API ----

// Responses stands in for POST /responses and returns Output as the
// structured output text.
type Responses struct {
	base
	key    string
	output string
}

// NewResponses starts the fake. key is the bearer token it accepts.
func NewResponses(t testing.TB, key, output string) *Responses {
	f := &Responses{base: newBase(), key: key, output: output}
	f.Server = httptest.NewServer(http.HandlerFunc(f.handle))
	t.Cleanup(f.Server.Close)
	return f
}

// SetOutput replaces the structured output text.
func (f *Responses) SetOutput(output string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.output = output
}

func (f *Responses) handle(w http.ResponseWriter, r *http.Request) {
	if _, ok := f.arrive(w, r); !ok {
		return
	}
	if r.Header.Get("Authorization") != "Bearer "+f.key {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	f.mu.Lock()
	output := f.output
	f.mu.Unlock()
	body, _ := json.Marshal(map[string]any{"status": "completed", "output": []any{map[string]any{
		"type": "message", "content": []any{map[string]any{"type": "output_text", "text": output}}}}})
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write(body)
}

// ---- Telegram Bot API sendMessage ----

// Message is one sendMessage request the fake received.
type Message struct {
	ChatID string
	Text   string
}

// Telegram stands in for POST /bot<token>/sendMessage.
type Telegram struct {
	base
	token    string
	messages []Message
	bodies   []string
}

// NewTelegram starts the fake. token is the bot token it accepts.
func NewTelegram(t testing.TB, token string) *Telegram {
	f := &Telegram{base: newBase(), token: token}
	f.Server = httptest.NewServer(http.HandlerFunc(f.handle))
	t.Cleanup(f.Server.Close)
	return f
}

// Messages returns every message received (including dropped ones).
func (f *Telegram) Messages() []Message {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]Message{}, f.messages...)
}

// Bodies returns every raw request body received.
func (f *Telegram) Bodies() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string{}, f.bodies...)
}

func (f *Telegram) handle(w http.ResponseWriter, r *http.Request) {
	raw, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	var m struct {
		ChatID string `json:"chat_id"`
		Text   string `json:"text"`
	}
	_ = json.Unmarshal(raw, &m)
	f.mu.Lock()
	f.messages = append(f.messages, Message{ChatID: m.ChatID, Text: m.Text})
	f.bodies = append(f.bodies, string(raw))
	f.mu.Unlock()
	r.Body = io.NopCloser(strings.NewReader(""))
	if _, ok := f.arrive(w, r); !ok {
		return
	}
	if r.Method != http.MethodPost || r.URL.Path != "/bot"+f.token+"/sendMessage" {
		w.WriteHeader(http.StatusUnauthorized)
		_, _ = w.Write([]byte(`{"ok":false,"error_code":401,"description":"Unauthorized"}`))
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"ok":true,"result":{"message_id":1}}`))
}
