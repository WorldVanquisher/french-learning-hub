package captureclient

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const samplePayload = `{
  "schema_version": "learning_capture_v1",
  "capture_id": "manual-2026-08-11-001",
  "source": "manual",
  "original_input": "vouloir",
  "original_context": "asking about the conjugation of vouloir",
  "discussion_summary": "learning the common conjugations of vouloir"
}`

// newTestClient builds a client pointed at ts using ts's own client.
func newTestClient(t *testing.T, ts *httptest.Server) *Client {
	t.Helper()
	c, err := New(ts.URL, WithHTTPClient(ts.Client()))
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	return c
}

func TestImport_Created(t *testing.T) {
	var gotMethod, gotPath, gotContentType, gotBody string
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotMethod = r.Method
		gotPath = r.URL.Path
		gotContentType = r.Header.Get("Content-Type")
		b, _ := io.ReadAll(r.Body)
		gotBody = string(b)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		io.WriteString(w, `{"capture_id":"manual-2026-08-11-001","entry_id":42,"analysis_id":null,"created":true}`)
	}))
	defer ts.Close()

	res, err := newTestClient(t, ts).Import(context.Background(), []byte(samplePayload))
	if err != nil {
		t.Fatalf("Import: %v", err)
	}

	// Correct request shape.
	if gotMethod != http.MethodPost {
		t.Errorf("method = %q, want POST", gotMethod)
	}
	if gotPath != "/captures" {
		t.Errorf("path = %q, want /captures", gotPath)
	}
	if gotContentType != "application/json" {
		t.Errorf("content-type = %q, want application/json", gotContentType)
	}
	// Payload must reach the server byte-for-byte unchanged.
	if gotBody != samplePayload {
		t.Errorf("payload modified in transit:\n got: %q\nwant: %q", gotBody, samplePayload)
	}

	// Correct response mapping.
	if !res.Created || res.EntryID != 42 || res.AnalysisID != nil || res.CaptureID != "manual-2026-08-11-001" {
		t.Fatalf("unexpected result: %+v", res)
	}
}

func TestImport_WithAnalysisID(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusCreated)
		io.WriteString(w, `{"capture_id":"c1","entry_id":7,"analysis_id":9,"created":true}`)
	}))
	defer ts.Close()

	res, err := newTestClient(t, ts).Import(context.Background(), []byte(samplePayload))
	if err != nil {
		t.Fatalf("Import: %v", err)
	}
	if res.AnalysisID == nil || *res.AnalysisID != 9 {
		t.Fatalf("analysis_id = %v, want 9", res.AnalysisID)
	}
}

func TestImport_IdempotentReplay(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		// 200 OK with created=false is a replay, not an error.
		w.WriteHeader(http.StatusOK)
		io.WriteString(w, `{"capture_id":"manual-2026-08-11-001","entry_id":42,"analysis_id":null,"created":false}`)
	}))
	defer ts.Close()

	res, err := newTestClient(t, ts).Import(context.Background(), []byte(samplePayload))
	if err != nil {
		t.Fatalf("replay should not be an error: %v", err)
	}
	if res.Created {
		t.Fatal("replay should have created=false")
	}
	if res.EntryID != 42 {
		t.Fatalf("entry_id = %d, want 42", res.EntryID)
	}
}

func TestImport_Conflict(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusConflict)
		io.WriteString(w, `{"error":"capture_id already exists with different content"}`)
	}))
	defer ts.Close()

	_, err := newTestClient(t, ts).Import(context.Background(), []byte(samplePayload))
	var apiErr *APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("expected *APIError, got %v", err)
	}
	if !apiErr.IsConflict() {
		t.Fatalf("expected conflict, got status %d", apiErr.StatusCode)
	}
	if apiErr.Message != "capture_id already exists with different content" {
		t.Fatalf("message = %q", apiErr.Message)
	}
}

func TestImport_ValidationErrors(t *testing.T) {
	for _, tc := range []struct {
		name   string
		status int
		msg    string
	}{
		{"bad request", http.StatusBadRequest, "invalid JSON body"},
		{"unprocessable", http.StatusUnprocessableEntity, "unsupported schema version"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(tc.status)
				io.WriteString(w, `{"error":"`+tc.msg+`"}`)
			}))
			defer ts.Close()

			_, err := newTestClient(t, ts).Import(context.Background(), []byte(samplePayload))
			var apiErr *APIError
			if !errors.As(err, &apiErr) {
				t.Fatalf("expected *APIError, got %v", err)
			}
			if apiErr.StatusCode != tc.status || apiErr.Message != tc.msg {
				t.Fatalf("got status=%d msg=%q, want status=%d msg=%q", apiErr.StatusCode, apiErr.Message, tc.status, tc.msg)
			}
		})
	}
}

func TestImport_ServerError(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		io.WriteString(w, `{"error":"could not import capture"}`)
	}))
	defer ts.Close()

	_, err := newTestClient(t, ts).Import(context.Background(), []byte(samplePayload))
	var apiErr *APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("expected *APIError, got %v", err)
	}
	if apiErr.StatusCode != http.StatusInternalServerError {
		t.Fatalf("status = %d, want 500", apiErr.StatusCode)
	}
}

func TestImport_MalformedSuccessBody(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusCreated)
		io.WriteString(w, `{not valid json`)
	}))
	defer ts.Close()

	_, err := newTestClient(t, ts).Import(context.Background(), []byte(samplePayload))
	if err == nil {
		t.Fatal("expected an error decoding a malformed success body")
	}
	// A decode failure is not an APIError (the HTTP status was a success).
	var apiErr *APIError
	if errors.As(err, &apiErr) {
		t.Fatalf("malformed body should not be an APIError, got %v", err)
	}
}

func TestImport_NetworkFailure(t *testing.T) {
	// Point at a closed server so the request fails at the transport layer.
	ts := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	client := newTestClient(t, ts)
	ts.Close()

	_, err := client.Import(context.Background(), []byte(samplePayload))
	if err == nil {
		t.Fatal("expected a network error")
	}
	// The learning payload must not leak into the error message.
	if strings.Contains(err.Error(), "vouloir") || strings.Contains(err.Error(), "conjugation") {
		t.Fatalf("network error leaked payload content: %v", err)
	}
}

func TestImport_EmptyPayload(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Fatal("server must not be called for an empty payload")
	}))
	defer ts.Close()

	for _, p := range [][]byte{nil, {}, []byte("   \n\t ")} {
		_, err := newTestClient(t, ts).Import(context.Background(), p)
		if !errors.Is(err, ErrEmptyPayload) {
			t.Fatalf("expected ErrEmptyPayload for %q, got %v", p, err)
		}
	}
}

func TestImport_BoundedErrorBody(t *testing.T) {
	// A huge error body must not be read in full; the client caps it and still
	// extracts the message from the bounded prefix.
	huge := strings.Repeat("x", 5<<20) // 5 MiB of trailing junk
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		io.WriteString(w, `{"error":"invalid JSON body"}`)
		io.WriteString(w, huge)
	}))
	defer ts.Close()

	_, err := newTestClient(t, ts).Import(context.Background(), []byte(samplePayload))
	var apiErr *APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("expected *APIError, got %v", err)
	}
	// The message is recovered because {"error":...} fits within the bounded read;
	// the trailing junk beyond the cap is ignored rather than buffered.
	if apiErr.Message != "invalid JSON body" {
		t.Fatalf("message = %q, want 'invalid JSON body'", apiErr.Message)
	}
}

func TestNew_InvalidURLs(t *testing.T) {
	for _, bad := range []string{"", "   ", "ftp://host", "not a url", "http://"} {
		if _, err := New(bad); err == nil {
			t.Errorf("New(%q) should fail", bad)
		}
	}
}

func TestNew_TrimsTrailingSlash(t *testing.T) {
	var gotPath string
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		w.WriteHeader(http.StatusCreated)
		io.WriteString(w, `{"capture_id":"c","entry_id":1,"analysis_id":null,"created":true}`)
	}))
	defer ts.Close()

	c, err := New(ts.URL+"/", WithHTTPClient(ts.Client()))
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if _, err := c.Import(context.Background(), []byte(samplePayload)); err != nil {
		t.Fatalf("Import: %v", err)
	}
	if gotPath != "/captures" {
		t.Fatalf("path = %q, want /captures (no double slash)", gotPath)
	}
}
