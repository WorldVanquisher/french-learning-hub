// Package speakingfake is a local stand-in for the OpenAI transcription
// endpoint (POST /audio/transcriptions, multipart). Tests only: an httptest
// server on loopback that records what it received (model, fields, filename,
// part type, audio size and SHA-256, never the audio itself beyond the call)
// and can be told to fail, hang, return unusable output or drop the
// connection after reading the request (a lost response).
package speakingfake

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"
)

// Modes.
const (
	ModeOK        = "ok"
	ModeStatus    = "status"    // answer with Status
	ModeHang      = "hang"      // wait Delay (or until the client gives up)
	ModeDrop      = "drop"      // read the request, then close the connection
	ModeMalformed = "malformed" // 200 with a body that is not JSON
	ModeEmpty     = "empty"     // 200 {"text": ""}
)

// Received is what one request carried.
type Received struct {
	Auth        string
	Fields      map[string]string // every non-file form field
	Filename    string
	PartType    string
	AudioBytes  int
	AudioSHA256 string
}

// Transcriptions stands in for POST /audio/transcriptions.
type Transcriptions struct {
	mu       sync.Mutex
	key      string
	text     string
	mode     string
	status   int
	delay    time.Duration
	received []Received
	Arrived  chan struct{}
	Server   *httptest.Server
}

// New starts the fake. key is the bearer token it accepts; text is the transcript it returns.
func New(t testing.TB, key, text string) *Transcriptions {
	f := &Transcriptions{key: key, text: text, mode: ModeOK, status: http.StatusOK, Arrived: make(chan struct{}, 64)}
	f.Server = httptest.NewServer(http.HandlerFunc(f.handle))
	t.Cleanup(f.Server.Close)
	return f
}

// URL is the base URL (the client appends /audio/transcriptions).
func (f *Transcriptions) URL() string { return f.Server.URL }

// Set changes how the next requests are answered.
func (f *Transcriptions) Set(mode string, status int, delay time.Duration) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.mode, f.status, f.delay = mode, status, delay
}

// SetText replaces the transcript returned.
func (f *Transcriptions) SetText(text string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.text = text
}

// Calls counts requests received.
func (f *Transcriptions) Calls() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.received)
}

// Received returns what every request carried.
func (f *Transcriptions) Received() []Received {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]Received{}, f.received...)
}

func (f *Transcriptions) handle(w http.ResponseWriter, r *http.Request) {
	rec := Received{Auth: r.Header.Get("Authorization"), Fields: map[string]string{}}
	if _, params, err := mime.ParseMediaType(r.Header.Get("Content-Type")); err == nil && r.URL.Path == "/audio/transcriptions" {
		mr := multipart.NewReader(r.Body, params["boundary"])
		for {
			p, err := mr.NextPart()
			if err != nil {
				break
			}
			data, _ := io.ReadAll(p)
			if p.FormName() == "file" {
				sum := sha256.Sum256(data)
				rec.Filename, rec.PartType, rec.AudioBytes, rec.AudioSHA256 = p.FileName(), p.Header.Get("Content-Type"), len(data), hex.EncodeToString(sum[:])
			} else {
				rec.Fields[p.FormName()] = string(data)
			}
		}
	}
	_, _ = io.Copy(io.Discard, r.Body)
	f.mu.Lock()
	f.received = append(f.received, rec)
	mode, status, delay, text := f.mode, f.status, f.delay, f.text
	f.mu.Unlock()
	select {
	case f.Arrived <- struct{}{}:
	default:
	}
	switch mode {
	case ModeHang:
		select {
		case <-time.After(delay):
		case <-r.Context().Done():
			return
		}
	case ModeDrop:
		if hj, ok := w.(http.Hijacker); ok {
			if conn, _, err := hj.Hijack(); err == nil {
				_ = conn.Close()
			}
		}
		return
	case ModeStatus:
		w.WriteHeader(status)
		_, _ = w.Write([]byte(`{"error":{"message":"fake failure","type":"server_error"}}`))
		return
	case ModeMalformed:
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`not json`))
		return
	case ModeEmpty:
		text = ""
	}
	if r.Method != http.MethodPost || r.URL.Path != "/audio/transcriptions" {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	if rec.Auth != "Bearer "+f.key {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"text": text, "usage": map[string]any{"type": "duration", "seconds": 3}})
}
