package http_test

import (
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	transporthttp "french-learning-app/internal/transport/http"
)

// FLH-075 symlink policy: reads are confined to the web root by os.Root. A link
// is followed only when it is relative and resolves inside the root.
func TestWorkbench_StaticReadsStayInsideTheWebRoot(t *testing.T) {
	base := t.TempDir()
	web := filepath.Join(base, "web")
	outside := filepath.Join(base, "outside")
	for _, d := range []string{filepath.Join(web, "assets", "nested"), outside} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	write := func(path, body string) {
		t.Helper()
		if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	link := func(target, name string) {
		t.Helper()
		if err := os.Symlink(target, name); err != nil {
			t.Fatal(err)
		}
	}
	write(filepath.Join(web, "index.html"), "<!doctype html>index")
	write(filepath.Join(web, "assets", "app.js"), "app-bytes")
	write(filepath.Join(web, "assets", "nested", "deep.css"), "deep-bytes")
	write(filepath.Join(outside, "secret.txt"), "OUTSIDE-SENTINEL")
	write(filepath.Join(base, "sibling.txt"), "OUTSIDE-SENTINEL")

	// Escaping links: absolute file, relative file, directory, nested directory.
	link(filepath.Join(outside, "secret.txt"), filepath.Join(web, "assets", "abs-outside.txt"))
	link("../../sibling.txt", filepath.Join(web, "assets", "rel-outside.txt"))
	link(outside, filepath.Join(web, "assets", "outdir"))
	link("../../../outside", filepath.Join(web, "assets", "nested", "outdir"))
	// An absolute link is refused even when it points inside the root.
	link(filepath.Join(web, "assets", "app.js"), filepath.Join(web, "assets", "abs-inside.js"))
	// Relative links that stay inside the root are allowed.
	link("app.js", filepath.Join(web, "assets", "alias.js"))
	link("nested", filepath.Join(web, "assets", "nested-alias"))

	api := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(299)
		io.WriteString(w, "api:"+r.URL.Path)
	})
	h, err := transporthttp.NewWorkbenchHandler(api, web)
	if err != nil {
		t.Fatal(err)
	}
	get := func(path string) (int, string) {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
		return rec.Code, rec.Body.String()
	}
	allowed := map[string]string{
		"/":                             "<!doctype html>index",
		"/assets/app.js":                "app-bytes",
		"/assets/nested/deep.css":       "deep-bytes",
		"/assets/alias.js":              "app-bytes",
		"/assets/nested-alias/deep.css": "deep-bytes",
	}
	for path, want := range allowed {
		if code, body := get(path); code != 200 || body != want {
			t.Fatalf("%s: %d %q", path, code, body)
		}
	}
	for _, path := range []string{"/assets/abs-outside.txt", "/assets/rel-outside.txt", "/assets/outdir/secret.txt",
		"/assets/nested/outdir/secret.txt", "/assets/abs-inside.js", "/assets/", "/assets/nested", "/assets/nested/",
		"/assets/outdir", "/assets/missing.js"} {
		code, body := get(path)
		if code == 200 || body == "OUTSIDE-SENTINEL" {
			t.Fatalf("%s escaped or listed: %d %q", path, code, body)
		}
		if code != http.StatusNotFound && code != http.StatusMovedPermanently {
			t.Fatalf("%s: unexpected %d", path, code)
		}
	}
	// A link swapped in after startup is confined at open time, not by a pre-check.
	target := filepath.Join(web, "assets", "app.js")
	if err := os.Remove(target); err != nil {
		t.Fatal(err)
	}
	link(filepath.Join(outside, "secret.txt"), target)
	if code, body := get("/assets/app.js"); code == 200 || body == "OUTSIDE-SENTINEL" {
		t.Fatalf("swapped link escaped: %d %q", code, body)
	}
	// Routing outside /assets is unchanged.
	if code, body := get("/api/knowledge-library/concepts"); code != 299 || body != "api:/knowledge-library/concepts" {
		t.Fatalf("api prefix: %d %q", code, body)
	}
	if code, body := get("/healthz"); code != 299 || body != "api:/healthz" {
		t.Fatalf("root api: %d %q", code, body)
	}
}

func TestWorkbench_IndexOutsideTheRootIsAStartupError(t *testing.T) {
	base := t.TempDir()
	web := filepath.Join(base, "web")
	if err := os.MkdirAll(web, 0o755); err != nil {
		t.Fatal(err)
	}
	os.WriteFile(filepath.Join(base, "index.html"), []byte("outside"), 0o644)
	if err := os.Symlink("../index.html", filepath.Join(web, "index.html")); err != nil {
		t.Fatal(err)
	}
	if _, err := transporthttp.NewWorkbenchHandler(http.NotFoundHandler(), web); err == nil {
		t.Fatal("an index.html outside the web root must refuse startup")
	}
	// The web directory itself may be a link; it is resolved once.
	real := filepath.Join(base, "real")
	os.MkdirAll(real, 0o755)
	os.WriteFile(filepath.Join(real, "index.html"), []byte("ok"), 0o644)
	alias := filepath.Join(base, "alias")
	if err := os.Symlink(real, alias); err != nil {
		t.Fatal(err)
	}
	h, err := transporthttp.NewWorkbenchHandler(http.NotFoundHandler(), alias)
	if err != nil {
		t.Fatal(err)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/", nil))
	if rec.Code != 200 || rec.Body.String() != "ok" {
		t.Fatalf("linked web dir: %d %q", rec.Code, rec.Body.String())
	}
}
