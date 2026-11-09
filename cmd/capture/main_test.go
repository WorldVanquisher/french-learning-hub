package main

import (
	"bytes"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
)

const okBody = `{"schema_version":"learning_capture_v1","capture_id":"cli-1","source":"manual","original_input":"LEARNER-TEXT","original_context":"c"}`

// fakeHub answers by capture_id and counts requests.
func fakeHub(t *testing.T) (*httptest.Server, *atomic.Int32, *[]string) {
	t.Helper()
	var n atomic.Int32
	var bodies []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n.Add(1)
		b, _ := io.ReadAll(r.Body)
		bodies = append(bodies, string(b))
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.Contains(string(b), `"conflict"`):
			w.WriteHeader(409)
			io.WriteString(w, `{"error":"capture_id already exists with different content"}`)
		case strings.Contains(string(b), `"replay"`):
			w.WriteHeader(200)
			io.WriteString(w, `{"capture_id":"replay","entry_id":2,"analysis_id":null,"created":false}`)
		case strings.Contains(string(b), `"down"`):
			w.WriteHeader(503)
		default:
			w.WriteHeader(201)
			io.WriteString(w, `{"capture_id":"cli-1","entry_id":1,"analysis_id":null,"created":true}`)
		}
	}))
	t.Cleanup(srv.Close)
	return srv, &n, &bodies
}

func write(t *testing.T, dir, name, body string) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

func code(err error) int {
	if err == nil {
		return 0
	}
	var ee *exitError
	if errors.As(err, &ee) {
		return ee.code
	}
	return 1
}

func TestSingleFileAndStdinUnchanged(t *testing.T) {
	srv, n, bodies := fakeHub(t)
	dir := t.TempDir()
	f := write(t, dir, "one.json", okBody)

	var out, errb bytes.Buffer
	if err := run([]string{"-url", srv.URL, "-file", f}, strings.NewReader(""), &out, &errb); err != nil {
		t.Fatalf("-file: %v", err)
	}
	want := "capture stored (new)\ncapture_id:  cli-1\nentry_id:    1\nanalysis_id: null\ncreated:     true\n"
	if out.String() != want {
		t.Fatalf("-file output changed:\n%s", out.String())
	}

	out.Reset()
	if err := run([]string{"-url", srv.URL}, strings.NewReader(okBody), &out, &errb); err != nil || out.String() != want {
		t.Fatalf("stdin: %v\n%s", err, out.String())
	}
	if n.Load() != 2 || (*bodies)[0] != okBody || (*bodies)[1] != okBody {
		t.Fatalf("requests=%d, bodies unchanged=%v", n.Load(), (*bodies)[0] == okBody)
	}

	// A single-file conflict is still a plain error (exit 1).
	c := write(t, dir, "c.json", strings.Replace(okBody, "cli-1", "conflict", 1))
	err := run([]string{"-url", srv.URL, "-file", c}, nil, &out, &errb)
	if code(err) != 1 || !strings.Contains(err.Error(), "409") {
		t.Fatalf("single conflict: code=%d err=%v", code(err), err)
	}
}

func TestUsageErrorsExit2WithoutRequests(t *testing.T) {
	srv, n, _ := fakeHub(t)
	dir := t.TempDir()
	f := write(t, dir, "a.json", okBody)
	for name, args := range map[string][]string{
		"preview without batch": {"-url", srv.URL, "-preview"},
		"file with batch":       {"-url", srv.URL, "-batch", "-file", f, f},
		"args without batch":    {"-url", srv.URL, f},
		"no files":              {"-url", srv.URL, "-batch"},
		"flag after files":      {"-batch", f, "-url", srv.URL},
		"same file twice":       {"-url", srv.URL, "-batch", f, f},
	} {
		var out, errb bytes.Buffer
		if got := code(run(args, strings.NewReader(okBody), &out, &errb)); got != exitUsage {
			t.Errorf("%s: exit %d, want %d", name, got, exitUsage)
		}
	}
	if n.Load() != 0 {
		t.Fatalf("usage errors sent %d requests", n.Load())
	}
}

func TestBatchExitStatusesAndReport(t *testing.T) {
	srv, _, _ := fakeHub(t)
	dir := t.TempDir()
	ok := write(t, dir, "1.json", okBody)
	rep := write(t, dir, "2.json", strings.Replace(okBody, "cli-1", "replay", 1))
	con := write(t, dir, "3.json", strings.Replace(okBody, "cli-1", "conflict", 1))
	down := write(t, dir, "4.json", strings.Replace(okBody, "cli-1", "down", 1))

	cases := []struct {
		name  string
		files []string
		code  int
	}{
		{"all stored", []string{ok, rep}, exitOK},
		{"conflict", []string{ok, con}, exitRejected},
		{"unconfirmed wins", []string{con, down}, exitUnconfirmed},
	}
	for _, tc := range cases {
		var out, errb bytes.Buffer
		err := run(append([]string{"-url", srv.URL, "-batch"}, tc.files...), nil, &out, &errb)
		if code(err) != tc.code {
			t.Errorf("%s: exit %d, want %d\n%s", tc.name, code(err), tc.code, out.String())
		}
		if !strings.Contains(out.String(), "summary: total=") || strings.Contains(out.String(), "LEARNER-TEXT") {
			t.Errorf("%s: report missing summary or leaks learner text:\n%s", tc.name, out.String())
		}
	}
	var out, errb bytes.Buffer
	// Arguments in reverse order: the report follows byte-wise path order.
	run([]string{"-url", srv.URL, "-batch", down, con, ok}, nil, &out, &errb)
	for _, s := range []string{"[1/3] created", "[2/3] conflict", "[3/3] unconfirmed", "status=503", "unconfirmed=1", "next: rerun the same command"} {
		if !strings.Contains(out.String(), s) {
			t.Errorf("report lacks %q:\n%s", s, out.String())
		}
	}
}

func TestPreviewSendsNothing(t *testing.T) {
	srv, n, _ := fakeHub(t)
	dir := t.TempDir()
	ok := write(t, dir, "1.json", okBody)
	empty := write(t, dir, "2.json", "")

	var out, errb bytes.Buffer
	if err := run([]string{"-url", srv.URL, "-batch", "-preview", ok}, nil, &out, &errb); err != nil {
		t.Fatalf("preview ok: %v", err)
	}
	if !strings.Contains(out.String(), "no HTTP request is made") || !strings.Contains(out.String(), "summary: total=1 ready=1 invalid=0") {
		t.Fatalf("preview report:\n%s", out.String())
	}
	out.Reset()
	if got := code(run([]string{"-url", srv.URL, "-batch", "-preview", ok, empty}, nil, &out, &errb)); got != exitRejected {
		t.Fatalf("preview with invalid file: exit %d, want %d", got, exitRejected)
	}
	// Even an unreachable URL is fine: preview never connects.
	if err := run([]string{"-url", "http://127.0.0.1:1", "-batch", "-preview", ok}, nil, &out, &errb); err != nil {
		t.Fatalf("preview against an unreachable URL: %v", err)
	}
	if n.Load() != 0 {
		t.Fatalf("preview sent %d requests", n.Load())
	}
}

func TestRedactURL(t *testing.T) {
	if got := redactURL("http://user:secret@127.0.0.1:8080"); strings.Contains(got, "secret") {
		t.Fatalf("redactURL kept the password: %s", got)
	}
}
