package http

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

type logSink struct {
	mu    sync.Mutex
	lines []string
}

func (l *logSink) printf(format string, args ...any) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.lines = append(l.lines, fmt.Sprintf(format, args...))
}

func failingMux() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /speaking/takes/{id}/transcriptions", func(w http.ResponseWriter, r *http.Request) {
		writeError(w, http.StatusBadGateway, "transcription failed")
	})
	mux.HandleFunc("POST /captures", func(w http.ResponseWriter, r *http.Request) {
		writeError(w, http.StatusInternalServerError, "internal error")
	})
	mux.HandleFunc("GET /entries/{id}", func(w http.ResponseWriter, r *http.Request) {
		writeError(w, http.StatusNotFound, "entry not found")
	})
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok"))
	})
	return mux
}

func TestLogFailedRequests_LogsRouteNotContent(t *testing.T) {
	sink := &logSink{}
	h := LogFailedRequests(failingMux(), sink.printf)
	secret := "FIXTURE-PRIVATE-AUDIO-BASE64-UklGRiQAAABXQVZF"
	body := `{"audio_base64":"` + secret + `","original_input":"je parte demain"}`
	req := httptest.NewRequest(http.MethodPost, "/speaking/takes/42/transcriptions?q=je+parte", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer sk-fixture-not-a-key")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d", rec.Code)
	}
	id := rec.Header().Get(RequestIDHeader)
	if len(id) != 16 {
		t.Fatalf("request id %q", id)
	}
	if len(sink.lines) != 1 {
		t.Fatalf("lines = %v, want one", sink.lines)
	}
	line := sink.lines[0]
	want := `request failed: status=502 method=POST route="POST /speaking/takes/{id}/transcriptions"`
	if !strings.HasPrefix(line, want) || !strings.HasSuffix(line, "request_id="+id) {
		t.Fatalf("line = %q", line)
	}
	for _, leak := range []string{secret, "parte", "sk-fixture", "takes/42", "Bearer"} {
		if strings.Contains(line, leak) {
			t.Fatalf("log line leaks %q: %s", leak, line)
		}
	}
}

func TestLogFailedRequests_OnlyServerErrors(t *testing.T) {
	sink := &logSink{}
	h := LogFailedRequests(failingMux(), sink.printf)
	for _, tc := range []struct {
		method, path string
		want         int
	}{
		{http.MethodGet, "/healthz", 200},
		{http.MethodGet, "/entries/7", 404},
		{http.MethodGet, "/nope", 404},
		{http.MethodDelete, "/healthz", 405},
		{http.MethodPost, "/captures", 500},
	} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(tc.method, tc.path, nil))
		if rec.Code != tc.want {
			t.Fatalf("%s %s = %d, want %d", tc.method, tc.path, rec.Code, tc.want)
		}
		if rec.Header().Get(RequestIDHeader) == "" {
			t.Fatalf("%s %s: no request id header", tc.method, tc.path)
		}
	}
	if len(sink.lines) != 1 || !strings.Contains(sink.lines[0], `status=500 method=POST route="POST /captures"`) {
		t.Fatalf("lines = %v, want only the 500", sink.lines)
	}
}

// TestLogFailedRequests_WorkbenchPrefix: wrapped inside the workbench's /api
// prefix strip, the route pattern is still the API route.
func TestLogFailedRequests_WorkbenchPrefix(t *testing.T) {
	sink := &logSink{}
	api := LogFailedRequests(failingMux(), sink.printf)
	outer := http.NewServeMux()
	outer.Handle(WorkbenchAPIPrefix+"/", http.StripPrefix(WorkbenchAPIPrefix, api))
	rec := httptest.NewRecorder()
	outer.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, WorkbenchAPIPrefix+"/captures", nil))
	if rec.Code != http.StatusInternalServerError || len(sink.lines) != 1 ||
		!strings.Contains(sink.lines[0], `route="POST /captures"`) {
		t.Fatalf("code %d lines %v", rec.Code, sink.lines)
	}
}

func TestLogFailedRequests_UnwrapReachesFlusher(t *testing.T) {
	h := LogFailedRequests(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := http.NewResponseController(w).Flush(); err != nil {
			t.Errorf("flush through the recorder: %v", err)
		}
	}), (&logSink{}).printf)
	h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))
}
