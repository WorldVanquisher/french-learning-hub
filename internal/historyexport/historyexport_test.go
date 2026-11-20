package historyexport

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSafeFile_RefusesEveryEscape(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"", ".", "..", "../x", "a/b", "/etc/passwd", "a\\b", ".hidden", "x..y", "x.", "a\x00b", strings.Repeat("a", 81), "é", "nom avec espace"} {
		if _, err := SafeFile(dir, name, ".ndjson"); !errors.Is(err, ErrUnsafePath) {
			t.Errorf("%q: %v", name, err)
		}
	}
	if _, err := SafeFile(filepath.Join(dir, "missing"), "ok", ".txt"); !errors.Is(err, ErrUnsafePath) {
		t.Errorf("missing dir: %v", err)
	}
	if _, err := SafeFile("", "ok", ".txt"); !errors.Is(err, ErrUnsafePath) {
		t.Errorf("empty dir: %v", err)
	}
	got, err := SafeFile(dir, "learning-history-20261119", ".ndjson")
	if err != nil || got != filepath.Join(dir, "learning-history-20261119.ndjson") {
		t.Fatalf("plain name: %q %v", got, err)
	}
}

func TestWriteNew_NeverOverwritesOrFollowsALink(t *testing.T) {
	dir := t.TempDir()
	outside := filepath.Join(t.TempDir(), "victim.txt")
	if err := os.WriteFile(outside, []byte("keep"), 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "planted.txt")
	if err := os.Symlink(outside, link); err != nil {
		t.Fatal(err)
	}
	if err := WriteNew(link, []byte("x")); err == nil {
		t.Fatal("followed a planted link")
	}
	if b, _ := os.ReadFile(outside); string(b) != "keep" {
		t.Fatal("the link target changed")
	}
}

func TestRun_WritesBothFilesIntoTheDirectoryOnly(t *testing.T) {
	var asked []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		asked = append(asked, r.URL.RequestURI())
		if r.URL.Query().Get("format") == "text" {
			w.Write([]byte("readable"))
			return
		}
		w.Write([]byte(`{"kind":"header"}` + "\n"))
	}))
	defer srv.Close()
	dir := t.TempDir()
	files, err := Run(srv.Client(), srv.URL, dir, "day", Options{Transcripts: true})
	if err != nil || len(files) != 2 || files[0].AppImport != "preview only" || files[1].AppImport != "none" {
		t.Fatalf("run: %v %v", files, err)
	}
	if strings.Join(asked, " ") != "/learning-history/export?transcripts=true /learning-history/export?format=text&transcripts=true" {
		t.Fatalf("requests: %v", asked)
	}
	entries, _ := os.ReadDir(dir)
	if len(entries) != 2 {
		t.Fatalf("dir holds %d files", len(entries))
	}
	// A second run refuses before any request and changes nothing.
	asked = nil
	if _, err := Run(srv.Client(), srv.URL, dir, "day", Options{}); err == nil || len(asked) != 0 {
		t.Fatalf("second run: %v, requests %v", err, asked)
	}
	// An escaping name is refused before any request.
	if _, err := Run(srv.Client(), srv.URL, dir, "../day", Options{}); !errors.Is(err, ErrUnsafePath) || len(asked) != 0 {
		t.Fatalf("escape: %v %v", err, asked)
	}
}
