package http

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

var errNotReady = errors.New("database unavailable at /secret/path.db")

func readyz(t *testing.T, h http.Handler) (int, string, map[string]string) {
	t.Helper()
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/readyz", nil))
	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode %q: %v", rec.Body.String(), err)
	}
	return rec.Code, rec.Body.String(), body
}

func TestReadiness_Ready(t *testing.T) {
	h := NewHandler(&fakeService{}, nil, nil, nil, nil, nil, nil, nil, nil, nil,
		WithReadiness(func(context.Context) error { return nil })).Routes()
	code, _, body := readyz(t, h)
	if code != http.StatusOK || body["status"] != "ready" {
		t.Fatalf("got %d %v", code, body)
	}
}

func TestReadiness_FailureHidesDetail(t *testing.T) {
	h := NewHandler(&fakeService{}, nil, nil, nil, nil, nil, nil, nil, nil, nil,
		WithReadiness(func(context.Context) error { return errNotReady })).Routes()
	code, raw, body := readyz(t, h)
	if code != http.StatusServiceUnavailable || body["status"] != "not_ready" {
		t.Fatalf("got %d %v", code, body)
	}
	if strings.Contains(raw, "secret") {
		t.Fatalf("readiness leaked error detail: %s", raw)
	}
}

func TestReadiness_NotConfiguredIsNotReady(t *testing.T) {
	code, _, _ := readyz(t, newServer(&fakeService{}))
	if code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", code)
	}
}

// TestReadiness_Bounded proves a hung check cannot hang the probe: the handler
// cancels it at the readiness timeout and reports not ready.
func TestReadiness_Bounded(t *testing.T) {
	handler := NewHandler(&fakeService{}, nil, nil, nil, nil, nil, nil, nil, nil, nil,
		WithReadiness(func(ctx context.Context) error {
			<-ctx.Done()
			return ctx.Err()
		}))
	handler.readinessTimeout = 50 * time.Millisecond
	start := time.Now()
	code, _, _ := readyz(t, handler.Routes())
	if code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", code)
	}
	if elapsed := time.Since(start); elapsed > 2*time.Second {
		t.Fatalf("readiness took %v, want bounded", elapsed)
	}
}

func TestReadiness_LivenessIndependent(t *testing.T) {
	h := NewHandler(&fakeService{}, nil, nil, nil, nil, nil, nil, nil, nil, nil,
		WithReadiness(func(context.Context) error { return errNotReady })).Routes()
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("liveness status = %d, want 200 even when not ready", rec.Code)
	}
}
