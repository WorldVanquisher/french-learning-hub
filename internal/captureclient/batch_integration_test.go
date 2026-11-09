package captureclient_test

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"french-learning-app/internal/captureclient"
)

// lossyProxy forwards every request to the real hub. For a request whose body
// carries dropID it waits for the hub's complete response (the capture is
// committed), then closes the connection without answering: a response lost
// after commit. It also counts requests, so a preview can prove it sent none.
type lossyProxy struct {
	upstream string
	dropID   string
	dropped  atomic.Int32
	requests atomic.Int32
}

func (p *lossyProxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	p.requests.Add(1)
	body, _ := io.ReadAll(r.Body)
	req, _ := http.NewRequestWithContext(r.Context(), r.Method, p.upstream+r.URL.Path, bytes.NewReader(body))
	req.Header = r.Header.Clone()
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		http.Error(w, "upstream", http.StatusBadGateway)
		return
	}
	respBody, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if p.dropID != "" && bytes.Contains(body, []byte(fmt.Sprintf("%q", p.dropID))) && p.dropped.CompareAndSwap(0, 1) {
		conn, _, _ := w.(http.Hijacker).Hijack()
		conn.Close()
		return
	}
	for k, v := range resp.Header {
		w.Header()[k] = v
	}
	w.WriteHeader(resp.StatusCode)
	w.Write(respBody)
}

func entryCount(t *testing.T, base string) int {
	t.Helper()
	return len(listInventory(t, base))
}

func captureFile(t *testing.T, dir, name, id, input string) string {
	t.Helper()
	body := fmt.Sprintf(`{"schema_version":"learning_capture_v1","capture_id":%q,"source":"manual","original_input":%q,"original_context":"integration batch"}`, id, input)
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

// TestE2E_MixedBatch runs one mixed batch against the real handler and a real
// temporary SQLite database: new records, an identical replay, a conflict under
// an existing capture_id, server-invalid and locally invalid input, and a
// response lost after commit. A rerun settles the lost response as a replay and
// creates no duplicate.
func TestE2E_MixedBatch(t *testing.T) {
	hub := setupHub(t)
	proxy := &lossyProxy{upstream: hub.URL, dropID: "batch-lost"}
	front := httptest.NewServer(proxy)
	defer front.Close()

	dir := t.TempDir()
	// Pre-existing capture, imported singly through the existing path.
	pre := captureFile(t, dir, "00-pre.json", "batch-pre", "j'en veux")
	direct, _ := captureclient.New(hub.URL)
	preBytes, _ := os.ReadFile(pre)
	if _, err := direct.Import(context.Background(), preBytes); err != nil {
		t.Fatal(err)
	}
	if n := entryCount(t, hub.URL); n != 1 {
		t.Fatalf("entries before batch = %d, want 1", n)
	}

	paths := []string{
		captureFile(t, dir, "01-new.json", "batch-new-1", "Pourquoi « en » ici ?"),
		captureFile(t, dir, "02-replay.json", "batch-pre", "j'en veux"), // identical to 00-pre
		captureFile(t, dir, "03-conflict.json", "batch-pre", "different words"),
		captureFile(t, dir, "04-lost.json", "batch-lost", "Où mettre « y » ?"),
		captureFile(t, dir, "05-invalid-schema.json", "batch-bad", "x"),
		filepath.Join(dir, "06-missing.json"),
		captureFile(t, dir, "07-new.json", "batch-new-2", "Faut-il le subjonctif ?"),
	}
	// 05: wrong schema version (server 422); 08: not JSON (server 400).
	bad, _ := os.ReadFile(paths[4])
	os.WriteFile(paths[4], bytes.Replace(bad, []byte("learning_capture_v1"), []byte("learning_capture_v9"), 1), 0o600)
	notJSON := filepath.Join(dir, "08-not-json.json")
	os.WriteFile(notJSON, []byte("this is not json"), 0o600)
	paths = append(paths, notJSON)

	// Preview first: no request reaches the proxy or the hub.
	prev, err := captureclient.PreviewBatch(paths)
	if err != nil {
		t.Fatal(err)
	}
	if proxy.requests.Load() != 0 || entryCount(t, hub.URL) != 1 {
		t.Fatalf("preview sent %d requests", proxy.requests.Load())
	}
	if prev.Count(captureclient.OutcomeReady) != 7 || prev.Count(captureclient.OutcomeInvalid) != 1 {
		t.Fatalf("preview ready=%d invalid=%d, want 7/1", prev.Count(captureclient.OutcomeReady), prev.Count(captureclient.OutcomeInvalid))
	}

	client, _ := captureclient.New(front.URL)
	rep, err := client.RunBatch(context.Background(), paths)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]captureclient.Outcome{
		"01-new.json":            captureclient.OutcomeCreated,
		"02-replay.json":         captureclient.OutcomeReplayed,
		"03-conflict.json":       captureclient.OutcomeConflict,
		"04-lost.json":           captureclient.OutcomeUnconfirmed,
		"05-invalid-schema.json": captureclient.OutcomeInvalid,
		"06-missing.json":        captureclient.OutcomeInvalid,
		"07-new.json":            captureclient.OutcomeCreated,
		"08-not-json.json":       captureclient.OutcomeInvalid,
	}
	for _, f := range rep.Files {
		if got := f.Outcome; got != want[filepath.Base(f.Path)] {
			t.Errorf("%s: %s (%s), want %s", filepath.Base(f.Path), got, f.Detail, want[filepath.Base(f.Path)])
		}
		if strings.Contains(f.Detail+f.Warning, "«") {
			t.Errorf("%s: report contains learner text: %q", f.Path, f.Detail)
		}
	}
	// pre + new-1 + lost (committed despite the lost response) + new-2.
	if n := entryCount(t, hub.URL); n != 4 {
		t.Fatalf("entries after batch = %d, want 4", n)
	}
	resp, err := http.Get(hub.URL + "/captures/batch-lost")
	if err != nil || resp.StatusCode != http.StatusOK {
		t.Fatalf("lost-response capture should be committed: %v %v", err, resp)
	}
	resp.Body.Close()

	// Rerun the same files: the lost one settles as replayed, nothing is duplicated.
	rerun, err := client.RunBatch(context.Background(), paths)
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range rerun.Files {
		name := filepath.Base(f.Path)
		w := want[name]
		if w == captureclient.OutcomeCreated || name == "04-lost.json" {
			w = captureclient.OutcomeReplayed
		}
		if f.Outcome != w {
			t.Errorf("rerun %s: %s, want %s", name, f.Outcome, w)
		}
	}
	if n := entryCount(t, hub.URL); n != 4 {
		t.Fatalf("entries after rerun = %d, want 4 (no duplicate)", n)
	}
	if proxy.dropped.Load() != 1 {
		t.Fatalf("proxy dropped %d responses, want exactly 1", proxy.dropped.Load())
	}
}
