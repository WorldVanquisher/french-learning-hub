// Package captureclient is a thin HTTP client for the French Learning Hub
// POST /captures endpoint. It is a transport adapter, not a domain service: it
// sends a caller-provided learning_capture_v1 payload to the server verbatim and
// decodes the response. All capture business rules — schema, source, entry,
// taxonomy, and analysis validation, fingerprinting, idempotency, and conflict
// detection — remain the server's responsibility and are never reimplemented
// here.
package captureclient

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// defaultTimeout bounds a single import request. The client performs no retries.
const defaultTimeout = 15 * time.Second

// maxErrorBody bounds how much of an error response body the client reads, so a
// misbehaving or hostile server cannot make the client buffer an unbounded body.
const maxErrorBody = 8 << 10 // 8 KiB

// ErrEmptyPayload is returned when an empty payload is passed to Import. This is
// a transport-level sanity check, not domain validation: the server decides
// whether a non-empty payload is actually a valid capture.
var ErrEmptyPayload = errors.New("capture payload is empty")

// Result is the decoded POST /captures response. It mirrors the server's result
// shape: AnalysisID is nil when the capture carried no analysis, and Created
// distinguishes a newly stored capture (true) from an idempotent replay (false).
type Result struct {
	CaptureID  string `json:"capture_id"`
	EntryID    int64  `json:"entry_id"`
	AnalysisID *int64 `json:"analysis_id"`
	Created    bool   `json:"created"`
}

// APIError describes a non-success HTTP response from the server. Message is the
// server's safe public error string (from the {"error":"..."} body) when one is
// present; it is never the raw learning payload or an internal Go error chain.
type APIError struct {
	StatusCode int
	Message    string
}

func (e *APIError) Error() string {
	if e.Message != "" {
		return fmt.Sprintf("server returned %d: %s", e.StatusCode, e.Message)
	}
	return fmt.Sprintf("server returned %d", e.StatusCode)
}

// IsConflict reports whether the error is a 409 conflict (same capture_id,
// different content). Callers can use it to distinguish a conflict from other
// failures without matching on status codes directly.
func (e *APIError) IsConflict() bool { return e.StatusCode == http.StatusConflict }

// Client posts learning captures to a French Learning Hub backend over HTTP.
type Client struct {
	baseURL string
	http    *http.Client
}

// Option configures a Client.
type Option func(*Client)

// WithHTTPClient overrides the underlying *http.Client (useful in tests to point
// at an httptest.Server or to set a custom timeout).
func WithHTTPClient(h *http.Client) Option {
	return func(c *Client) {
		if h != nil {
			c.http = h
		}
	}
}

// New builds a Client for the given backend base URL (e.g.
// "http://localhost:8080"). The base URL must be a valid absolute HTTP(S) URL. A
// trailing slash is trimmed so paths join cleanly.
func New(baseURL string, opts ...Option) (*Client, error) {
	trimmed := strings.TrimSpace(baseURL)
	if trimmed == "" {
		return nil, errors.New("backend URL is empty")
	}
	u, err := url.Parse(trimmed)
	if err != nil {
		return nil, fmt.Errorf("invalid backend URL: %w", err)
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return nil, fmt.Errorf("backend URL must be http or https, got %q", u.Scheme)
	}
	if u.Host == "" {
		return nil, errors.New("backend URL must include a host")
	}

	c := &Client{
		baseURL: strings.TrimRight(trimmed, "/"),
		http:    &http.Client{Timeout: defaultTimeout},
	}
	for _, opt := range opts {
		opt(c)
	}
	return c, nil
}

// Import posts payload to {baseURL}/captures and returns the decoded result.
//
// The payload is sent to the server unchanged: the client does not rewrite,
// normalize, reclassify, or fingerprint any part of it. On a 2xx response it
// decodes the capture result (a malformed success body is an error). On a
// non-2xx response it returns an *APIError carrying the status code and the
// server's public error message, read through a bounded reader.
//
// Errors never include the learning payload, credentials, or authorization
// headers — only the status code and the server's own safe message.
func (c *Client) Import(ctx context.Context, payload []byte) (*Result, error) {
	if len(bytes.TrimSpace(payload)) == 0 {
		return nil, ErrEmptyPayload
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/captures", bytes.NewReader(payload))
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		// Do not wrap the payload into the error; ctx/transport errors from the
		// stdlib do not contain the request body, so this stays leak-free.
		return nil, fmt.Errorf("send capture request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, &APIError{StatusCode: resp.StatusCode, Message: readServerError(resp.Body)}
	}

	var result Result
	dec := json.NewDecoder(io.LimitReader(resp.Body, maxErrorBody))
	if err := dec.Decode(&result); err != nil {
		return nil, fmt.Errorf("decode capture response: %w", err)
	}
	return &result, nil
}

// readServerError extracts the server's public error message from a bounded
// prefix of the response body. It expects the shared {"error":"..."} shape and
// returns "" when the body is empty or not in that shape, so a malformed error
// body never surfaces as a confusing message.
func readServerError(body io.Reader) string {
	b, err := io.ReadAll(io.LimitReader(body, maxErrorBody))
	if err != nil || len(bytes.TrimSpace(b)) == 0 {
		return ""
	}
	// Decode only the first JSON value: a truncated or junk-suffixed body (the
	// bounded read may cut mid-stream) still yields the message if the leading
	// {"error":"..."} object is intact.
	var envelope struct {
		Error string `json:"error"`
	}
	if json.NewDecoder(bytes.NewReader(b)).Decode(&envelope) == nil {
		return strings.TrimSpace(envelope.Error)
	}
	return ""
}
