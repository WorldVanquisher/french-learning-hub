package http

import (
	"crypto/rand"
	"encoding/hex"
	"net/http"
	"time"
)

// RequestIDHeader carries the identifier of one request. The browser can show
// it next to an error, and the operator finds the same identifier in the log.
const RequestIDHeader = "X-Request-Id"

// LogFailedRequests logs one line for every response with a status of 500 or
// more. Handlers answer such failures with a generic message and do not log
// them, so without this line an operator could not see that writes were
// failing, for example on a read-only or full disk.
//
// The line holds only the method, the route pattern (never the path values or
// the query, which can carry learner text), the status, the duration and a
// random request identifier. That identifier is also set as RequestIDHeader on
// every response. It never logs a body, header, query, audio, key or provider
// message. Wrap the API handler itself (before NewWorkbenchHandler) so that the
// route pattern is known for /api requests too.
func LogFailedRequests(next http.Handler, logf func(format string, args ...any)) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := newRequestID()
		w.Header().Set(RequestIDHeader, id)
		rec := &statusRecorder{ResponseWriter: w}
		start := time.Now()
		next.ServeHTTP(rec, r)
		status := rec.status
		if status == 0 {
			status = http.StatusOK
		}
		if status < http.StatusInternalServerError {
			return
		}
		route := r.Pattern // set by ServeMux on the request it routed
		if route == "" {
			route = "unmatched"
		}
		logf("request failed: status=%d method=%s route=%q duration_ms=%d request_id=%s",
			status, r.Method, route, time.Since(start).Milliseconds(), id)
	})
}

func newRequestID() string {
	var b [8]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "unavailable"
	}
	return hex.EncodeToString(b[:])
}

// statusRecorder remembers the status a handler wrote.
type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (s *statusRecorder) WriteHeader(code int) {
	if s.status == 0 {
		s.status = code
	}
	s.ResponseWriter.WriteHeader(code)
}

func (s *statusRecorder) Write(b []byte) (int, error) {
	if s.status == 0 {
		s.status = http.StatusOK
	}
	return s.ResponseWriter.Write(b)
}

// Unwrap lets http.ResponseController reach the underlying writer (Flush,
// deadlines).
func (s *statusRecorder) Unwrap() http.ResponseWriter { return s.ResponseWriter }
