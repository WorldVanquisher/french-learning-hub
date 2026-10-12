package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// fakeEmbeddings is a counted local OpenAI-compatible endpoint. It never
// leaves the process; modes produce malformed output, failures or delays.
type fakeEmbeddings struct {
	mu       sync.Mutex
	mode     string // ok, wrong-count, http-500, slow, bad-dims
	requests int
	inputs   int
	auth     []string
	server   *httptest.Server
}

func newFakeEmbeddings(t *testing.T, mode string) *fakeEmbeddings {
	f := &fakeEmbeddings{mode: mode}
	f.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Model string   `json:"model"`
			Input []string `json:"input"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		f.mu.Lock()
		f.requests++
		f.inputs += len(req.Input)
		f.auth = append(f.auth, r.Header.Get("Authorization"))
		f.mu.Unlock()
		switch f.mode {
		case "http-500":
			http.Error(w, "boom", http.StatusInternalServerError)
			return
		case "slow":
			time.Sleep(1500 * time.Millisecond)
		}
		n := len(req.Input)
		if f.mode == "wrong-count" {
			n--
		}
		data := []map[string]any{}
		vecs, _ := (&bagProvider{dims: 16}).Embed(r.Context(), req.Input)
		for i := 0; i < n; i++ {
			v := vecs[i]
			if f.mode == "bad-dims" {
				v = v[:8]
			}
			data = append(data, map[string]any{"index": i, "embedding": v})
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"data": data})
	}))
	t.Cleanup(f.server.Close)
	return f
}

// counts reads the server-side counters under the lock (a slow handler may
// still be running after the client gave up).
func (f *fakeEmbeddings) counts() (requests, inputs int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.requests, f.inputs
}

func outDir(t *testing.T) string {
	return filepath.Join(t.TempDir(), "out")
}

func runCLI(t *testing.T, args ...string) (int, string, string) {
	t.Helper()
	var stdout, stderr bytes.Buffer
	code := run(args, &stdout, &stderr, nil)
	return code, stdout.String(), stderr.String()
}

func readReport(t *testing.T, dir string) map[string]any {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(dir, "report.json"))
	if err != nil {
		t.Fatal(err)
	}
	var r map[string]any
	if err := json.Unmarshal(b, &r); err != nil {
		t.Fatal(err)
	}
	return r
}

func embeddingSection(r map[string]any) map[string]any { return r["embedding"].(map[string]any) }

func TestCLI_OfflineBaselinesAreDeterministicAndLabelled(t *testing.T) {
	a, b := outDir(t), outDir(t)
	if code, _, stderr := runCLI(t, "-out", a); code != 0 {
		t.Fatalf("exit %d: %s", code, stderr)
	}
	if code, _, stderr := runCLI(t, "-out", b); code != 0 {
		t.Fatalf("exit %d: %s", code, stderr)
	}
	ra, rb := readReport(t, a), readReport(t, b)
	for i, x := range ra["offline_baselines"].([]any) {
		da := x.(map[string]any)["ranking_digest"]
		db := rb["offline_baselines"].([]any)[i].(map[string]any)["ranking_digest"]
		if da != db || x.(map[string]any)["state"] != stateCompleted {
			t.Fatalf("baseline %d: %v vs %v", i, da, db)
		}
	}
	e := embeddingSection(ra)
	if e["state"] != stateUnavailable || e["evaluation"].(map[string]any)["overall"] != nil {
		t.Fatalf("embedding must be unavailable by default: %v", e["state"])
	}
	summary, _ := os.ReadFile(filepath.Join(a, "summary.md"))
	for _, l := range Labels {
		if !strings.Contains(string(summary), l) || !strings.Contains(encodeStr(ra["labels"]), l) {
			t.Fatalf("label missing: %s", l)
		}
	}
}

func TestCLI_EmbeddingThroughHTTPProviderIsCounted(t *testing.T) {
	f := newFakeEmbeddings(t, "ok")
	t.Setenv("FLH048_TEST_KEY", "sk-test-not-a-real-secret")
	dir := outDir(t)
	code, _, stderr := runCLI(t, "-out", dir, "-embedding", "http", "-embedding-base-url", f.server.URL, "-embedding-model", "fake",
		"-embedding-api-key-env", "FLH048_TEST_KEY", "-embedding-max-inputs", "1400", "-embedding-dimensions", "16")
	if code != 0 {
		t.Fatalf("exit %d: %s", code, stderr)
	}
	r := readReport(t, dir)
	e := embeddingSection(r)
	p := e["provider_counters"].(map[string]any)
	// 56 queries x (1 query + 24 documents) = 1400 positions in 56 requests.
	if reqs, inputs := f.counts(); e["state"] != stateCompleted || p["requests"].(float64) != 56 || p["input_positions"].(float64) != 1400 || reqs != 56 || inputs != 1400 {
		t.Fatalf("counters %v; server saw %d requests / %d inputs", p, reqs, inputs)
	}
	f.mu.Lock()
	auth := f.auth[0]
	f.mu.Unlock()
	if auth != "Bearer sk-test-not-a-real-secret" {
		t.Fatal("key from the named environment variable was not sent")
	}
	raw, _ := os.ReadFile(filepath.Join(dir, "report.json"))
	summary, _ := os.ReadFile(filepath.Join(dir, "summary.md"))
	if bytes.Contains(raw, []byte("sk-test")) || bytes.Contains(summary, []byte("sk-test")) {
		t.Fatal("credential leaked into output")
	}
	// Fake embedding results stay outside the offline baselines.
	if len(r["offline_baselines"].([]any)) != 3 || !strings.Contains(string(summary), "a stub or fake endpoint tests plumbing") {
		t.Fatal("embedding results must be reported separately")
	}
}

func TestCLI_EmbeddingFailuresAreExplicitWithoutFallback(t *testing.T) {
	for _, mode := range []string{"wrong-count", "http-500", "slow", "bad-dims"} {
		t.Run(mode, func(t *testing.T) {
			f := newFakeEmbeddings(t, mode)
			dir := outDir(t)
			code, _, _ := runCLI(t, "-out", dir, "-embedding", "http", "-embedding-base-url", f.server.URL, "-embedding-model", "fake",
				"-embedding-timeout", "1s", "-embedding-max-inputs", "1400", "-embedding-dimensions", "16")
			if code != 1 {
				t.Fatalf("exit %d, want 1 (report written, retriever failed)", code)
			}
			e := embeddingSection(readReport(t, dir))
			qs := e["queries"].([]any)
			first := qs[0].(map[string]any)
			if e["state"] != stateFailed || first["status"] != "error" || qs[1].(map[string]any)["status"] != "not_run_after_error" {
				t.Fatalf("state %v first %v", e["state"], first)
			}
			if e["evaluation"].(map[string]any)["overall"] != nil {
				t.Fatal("a failed retriever must not be scored")
			}
			if reqs, _ := f.counts(); reqs != 1 {
				t.Fatalf("no retry or fallback: server saw %d requests", reqs)
			}
			if mode == "slow" && !strings.Contains(first["error"].(string), "timeout") {
				t.Fatalf("timeout not reported: %v", first["error"])
			}
		})
	}
}

func TestCLI_ConfigurationRefusals(t *testing.T) {
	f := newFakeEmbeddings(t, "ok")
	cases := map[string][]string{
		"flags without opt-in":   {"-embedding-base-url", f.server.URL},
		"unknown mode":           {"-embedding", "local"},
		"missing cap":            {"-embedding", "http", "-embedding-base-url", f.server.URL, "-embedding-model", "m"},
		"cap below planned":      {"-embedding", "http", "-embedding-base-url", f.server.URL, "-embedding-model", "m", "-embedding-max-inputs", "1399"},
		"missing model":          {"-embedding", "http", "-embedding-base-url", f.server.URL, "-embedding-max-inputs", "1400"},
		"credentials in url":     {"-embedding", "http", "-embedding-base-url", "http://user:pw@127.0.0.1:1", "-embedding-model", "m", "-embedding-max-inputs", "1400"},
		"query string in url":    {"-embedding", "http", "-embedding-base-url", f.server.URL + "?key=x", "-embedding-model", "m", "-embedding-max-inputs", "1400"},
		"relative url":           {"-embedding", "http", "-embedding-base-url", "localhost:9", "-embedding-model", "m", "-embedding-max-inputs", "1400"},
		"empty key env":          {"-embedding", "http", "-embedding-base-url", f.server.URL, "-embedding-model", "m", "-embedding-max-inputs", "1400", "-embedding-api-key-env", "FLH048_UNSET_VAR"},
		"timeout out of range":   {"-embedding", "http", "-embedding-base-url", f.server.URL, "-embedding-model", "m", "-embedding-max-inputs", "1400", "-embedding-timeout", "10m"},
		"stray positional input": {"extra"},
	}
	for name, args := range cases {
		t.Run(name, func(t *testing.T) {
			dir := outDir(t)
			code, _, _ := runCLI(t, append([]string{"-out", dir}, args...)...)
			if code != 2 {
				t.Fatalf("exit %d, want 2", code)
			}
			if _, err := os.Stat(dir); err == nil {
				t.Fatal("nothing may be written on a configuration refusal")
			}
		})
	}
	if reqs, _ := f.counts(); reqs != 0 {
		t.Fatalf("a refused configuration contacted the endpoint %d times", reqs)
	}
}

func TestCLI_OutputSafety(t *testing.T) {
	cwd, _ := os.Getwd()
	root, err := findRepoRoot(cwd)
	if err != nil {
		t.Fatal(err)
	}
	nonEmpty := t.TempDir()
	if err := os.WriteFile(filepath.Join(nonEmpty, "report.json"), []byte("keep"), 0o644); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(t.TempDir(), "into-repo")
	if err := os.Symlink(root, link); err != nil {
		t.Fatal(err)
	}
	cases := map[string]string{
		"missing -out":        "",
		"inside the repo":     filepath.Join(root, "tmp-flh048-out"),
		"fixture directory":   filepath.Join(root, "scripts", "validation", "flh045"),
		"symlink into repo":   filepath.Join(link, "out"),
		"non-empty directory": nonEmpty,
	}
	for name, out := range cases {
		t.Run(name, func(t *testing.T) {
			code, _, stderr := runCLI(t, "-out", out)
			if code != 3 {
				t.Fatalf("exit %d, want 3: %s", code, stderr)
			}
		})
	}
	if b, _ := os.ReadFile(filepath.Join(nonEmpty, "report.json")); string(b) != "keep" {
		t.Fatal("existing output was overwritten")
	}
	if _, err := os.Stat(filepath.Join(root, "tmp-flh048-out")); err == nil {
		t.Fatal("a refused output directory was created inside the repository")
	}

	// A fixture outside the repository: its directory and its contents are
	// protected too, and a modified fixture is refused by hash.
	ext := t.TempDir()
	fixture := filepath.Join(ext, "fixture.json")
	raw := frozenFixture(t)
	if err := os.WriteFile(fixture, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	if code, _, _ := runCLI(t, "-fixture", fixture, "-out", filepath.Join(ext, "out")); code != 3 {
		t.Fatalf("output next to the fixture: exit %d", code)
	}
	if code, _, _ := runCLI(t, "-fixture", fixture, "-out", filepath.Dir(ext)); code != 3 {
		t.Fatalf("fixture inside output: exit %d", code)
	}
	if err := os.WriteFile(fixture, append(raw, ' '), 0o644); err != nil {
		t.Fatal(err)
	}
	if code, _, stderr := runCLI(t, "-fixture", fixture, "-out", outDir(t)); code != 3 || !strings.Contains(stderr, "modified fixture") {
		t.Fatalf("modified fixture: exit %d %s", code, stderr)
	}
}

// The runner reads but never writes FLH-045 files.
func TestCLI_LeavesFLH045ByteIdentical(t *testing.T) {
	dir := filepath.Join("..", "flh045")
	before := map[string]string{}
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		b, _ := os.ReadFile(filepath.Join(dir, e.Name()))
		before[e.Name()] = sha256Hex(b)
	}
	if code, _, stderr := runCLI(t, "-out", outDir(t)); code != 0 {
		t.Fatalf("exit %d: %s", code, stderr)
	}
	entries, _ = os.ReadDir(dir)
	if len(entries) != len(before) {
		t.Fatal("files were added to the FLH-045 directory")
	}
	for _, e := range entries {
		b, _ := os.ReadFile(filepath.Join(dir, e.Name()))
		if before[e.Name()] != sha256Hex(b) {
			t.Fatalf("%s changed", e.Name())
		}
	}
}
