package http

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// writeWorkbench creates a minimal built workbench: index.html plus one asset.
func writeWorkbench(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "index.html"), []byte(`<!doctype html><script type="module" src="/assets/app-1.js"></script>`), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(dir, "assets", "nested"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "assets", "app-1.js"), []byte(`console.log("ok")`), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "assets", "app-1.css"), []byte(`body{}`), 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

// apiStub records the path the API handler received and answers like a route.
type apiStub struct{ gotPath string }

func (a *apiStub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	a.gotPath = r.URL.Path
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusTeapot)
	_, _ = io.WriteString(w, `{"path":"`+r.URL.Path+`"}`)
}

func serve(h http.Handler, method, target string) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(method, target, nil))
	return rec
}

func TestWorkbench_ServesIndexAtRoot(t *testing.T) {
	h, err := NewWorkbenchHandler(&apiStub{}, writeWorkbench(t))
	if err != nil {
		t.Fatal(err)
	}
	rec := serve(h, http.MethodGet, "/")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); !strings.HasPrefix(ct, "text/html") {
		t.Fatalf("content type = %q", ct)
	}
	if rec.Header().Get("Cache-Control") != "no-cache" {
		t.Fatalf("index must revalidate, got %q", rec.Header().Get("Cache-Control"))
	}
	if !strings.Contains(rec.Body.String(), "/assets/app-1.js") {
		t.Fatalf("unexpected body %q", rec.Body.String())
	}
}

func TestWorkbench_ServesAssetsWithTypes(t *testing.T) {
	h, err := NewWorkbenchHandler(&apiStub{}, writeWorkbench(t))
	if err != nil {
		t.Fatal(err)
	}
	for path, wantType := range map[string]string{
		"/assets/app-1.js":  "text/javascript",
		"/assets/app-1.css": "text/css",
	} {
		rec := serve(h, http.MethodGet, path)
		if rec.Code != http.StatusOK {
			t.Fatalf("%s status = %d", path, rec.Code)
		}
		if ct := rec.Header().Get("Content-Type"); !strings.HasPrefix(ct, wantType) {
			t.Fatalf("%s content type = %q, want %s", path, ct, wantType)
		}
	}
}

func TestWorkbench_NoDirectoryListingsOrTraversal(t *testing.T) {
	h, err := NewWorkbenchHandler(&apiStub{}, writeWorkbench(t))
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{"/assets/", "/assets/nested/", "/assets/missing.js", "/assets/../index.html"} {
		rec := serve(h, http.MethodGet, path)
		if rec.Code == http.StatusOK {
			t.Fatalf("%s served %q, want no listing or traversal", path, rec.Body.String())
		}
	}
}

func TestWorkbench_APIPrefixIsStripped(t *testing.T) {
	api := &apiStub{}
	h, err := NewWorkbenchHandler(api, writeWorkbench(t))
	if err != nil {
		t.Fatal(err)
	}
	rec := serve(h, http.MethodPost, "/api/entries/7/extractions")
	if rec.Code != http.StatusTeapot || api.gotPath != "/entries/7/extractions" {
		t.Fatalf("status %d, api path %q", rec.Code, api.gotPath)
	}
}

func TestWorkbench_RootAPIRoutesUnchanged(t *testing.T) {
	api := &apiStub{}
	h, err := NewWorkbenchHandler(api, writeWorkbench(t))
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{"/captures", "/healthz", "/no-such-route", "/index.html", "/api"} {
		api.gotPath = ""
		rec := serve(h, http.MethodGet, path)
		if rec.Code != http.StatusTeapot || api.gotPath != path {
			t.Fatalf("%s: status %d, api path %q; want unchanged dispatch", path, rec.Code, api.gotPath)
		}
	}
	// A non-GET request to the root also reaches the API (not the index).
	rec := serve(h, http.MethodPost, "/")
	if rec.Code != http.StatusTeapot || api.gotPath != "/" {
		t.Fatalf("POST /: status %d, api path %q", rec.Code, api.gotPath)
	}
}

func TestWorkbench_RejectsUnusableDirectory(t *testing.T) {
	if _, err := NewWorkbenchHandler(&apiStub{}, ""); err == nil {
		t.Fatal("expected error for empty directory")
	}
	if _, err := NewWorkbenchHandler(&apiStub{}, t.TempDir()); err == nil {
		t.Fatal("expected error when index.html is missing")
	}
	dir := t.TempDir()
	if err := os.Mkdir(filepath.Join(dir, "index.html"), 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := NewWorkbenchHandler(&apiStub{}, dir); err == nil {
		t.Fatal("expected error when index.html is a directory")
	}
}

// TestWorkbench_RealRoutesThroughPrefix runs the real API mux behind the
// workbench handler, so prefixed and unprefixed paths reach the same route.
func TestWorkbench_RealRoutesThroughPrefix(t *testing.T) {
	ready := false
	api := NewHandler(&fakeService{}, nil, nil, nil, nil, nil, nil, nil, nil, nil,
		WithReadiness(func(context.Context) error {
			if !ready {
				return errNotReady
			}
			return nil
		})).Routes()
	h, err := NewWorkbenchHandler(api, writeWorkbench(t))
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{"/healthz", "/api/healthz"} {
		rec := serve(h, http.MethodGet, path)
		var body map[string]string
		if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil || rec.Code != http.StatusOK || body["status"] != "ok" {
			t.Fatalf("%s: status %d body %q", path, rec.Code, rec.Body.String())
		}
	}
	for _, path := range []string{"/readyz", "/api/readyz"} {
		if rec := serve(h, http.MethodGet, path); rec.Code != http.StatusServiceUnavailable {
			t.Fatalf("%s not ready: status %d", path, rec.Code)
		}
	}
	ready = true
	for _, path := range []string{"/readyz", "/api/readyz"} {
		if rec := serve(h, http.MethodGet, path); rec.Code != http.StatusOK {
			t.Fatalf("%s ready: status %d", path, rec.Code)
		}
	}
	if rec := serve(h, http.MethodGet, "/api/no-such-route"); rec.Code != http.StatusNotFound {
		t.Fatalf("unknown prefixed route: status %d, want 404", rec.Code)
	}
}
