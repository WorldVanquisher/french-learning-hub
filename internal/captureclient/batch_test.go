package captureclient

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

// learnerMarker is distinctive learner text; no report field may contain it.
const learnerMarker = "LEARNER-TEXT-MUST-NOT-LEAK"

func captureJSON(id, input string) string {
	return fmt.Sprintf(`{"schema_version":"learning_capture_v1","capture_id":%q,"source":"manual","original_input":%q,"original_context":"ctx %s"}`, id, input, learnerMarker)
}

func writeFile(t *testing.T, dir, name, content string) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

// recorder is a fake server that records each request body and answers by a
// per-capture_id script.
type recorder struct {
	mu     sync.Mutex
	bodies []string
	answer func(body string) (int, string)
}

func (r *recorder) ServeHTTP(w http.ResponseWriter, req *http.Request) {
	b, _ := io.ReadAll(req.Body)
	r.mu.Lock()
	r.bodies = append(r.bodies, string(b))
	r.mu.Unlock()
	code, resp := r.answer(string(b))
	if code == 0 { // drop the connection without a response
		hj, _ := w.(http.Hijacker)
		conn, _, _ := hj.Hijack()
		conn.Close()
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	io.WriteString(w, resp)
}

func (r *recorder) count() int { r.mu.Lock(); defer r.mu.Unlock(); return len(r.bodies) }

func assertNoLeak(t *testing.T, rep *BatchReport) {
	t.Helper()
	for _, f := range rep.Files {
		all := strings.Join([]string{f.Path, f.CaptureID, f.Detail, f.Warning}, " ")
		if strings.Contains(all, learnerMarker) || strings.Contains(all, "original_input") {
			t.Fatalf("report for %s leaks request content: %q", f.Path, all)
		}
	}
}

func TestPlanBatchOrderAndRefusals(t *testing.T) {
	dir := t.TempDir()
	a := writeFile(t, dir, "a.json", "{}")
	b := writeFile(t, dir, "b.json", "{}")
	got, err := PlanBatch([]string{b, a})
	if err != nil || got[0] != a || got[1] != b {
		t.Fatalf("PlanBatch order = %v, %v; want [a b]", got, err)
	}

	tooMany := make([]string, MaxBatchFiles+1)
	for i := range tooMany {
		tooMany[i] = fmt.Sprintf("%s/f%03d.json", dir, i)
	}
	link := filepath.Join(dir, "link.json")
	if err := os.Symlink(a, link); err != nil {
		t.Fatal(err)
	}
	for name, paths := range map[string][]string{
		"empty":     nil,
		"too many":  tooMany,
		"same path": {a, b, a},
		"same file": {a, link},
		"blank":     {""},
	} {
		if _, err := PlanBatch(paths); !errors.Is(err, ErrBatchRefused) {
			t.Errorf("%s: err = %v, want ErrBatchRefused", name, err)
		}
	}
	// A missing file is not a refusal: it is reported per file.
	if _, err := PlanBatch([]string{a, filepath.Join(dir, "missing.json")}); err != nil {
		t.Fatalf("missing file must not refuse the batch: %v", err)
	}
}

func TestPreviewMakesNoRequestAndReportsLocalChecks(t *testing.T) {
	rec := &recorder{answer: func(string) (int, string) { return 500, "" }}
	srv := httptest.NewServer(rec)
	defer srv.Close()

	dir := t.TempDir()
	files := []string{
		writeFile(t, dir, "1-ok.json", captureJSON("id-1", learnerMarker)),
		writeFile(t, dir, "2-empty.json", "  \n"),
		writeFile(t, dir, "3-big.json", strings.Repeat("x", MaxPayloadBytes+1)),
		writeFile(t, dir, "4-notjson.json", "not json "+learnerMarker),
		writeFile(t, dir, "5-dup.json", captureJSON("id-1", "other")),
		writeFile(t, dir, "6-freetext-id.json", captureJSON("has spaces "+learnerMarker, "x")),
		filepath.Join(dir, "7-missing.json"),
	}
	rep, err := PreviewBatch(files)
	if err != nil {
		t.Fatal(err)
	}
	if rec.count() != 0 {
		t.Fatalf("preview sent %d requests, want 0", rec.count())
	}
	want := []Outcome{OutcomeReady, OutcomeInvalid, OutcomeInvalid, OutcomeReady, OutcomeReady, OutcomeReady, OutcomeInvalid}
	for i, f := range rep.Files {
		if f.Outcome != want[i] || f.Checked != CheckedLocal || f.Status != 0 {
			t.Errorf("file %d %s: outcome=%s checked=%s status=%d, want %s/local/0", i+1, filepath.Base(f.Path), f.Outcome, f.Checked, f.Status, want[i])
		}
	}
	if rep.Files[0].CaptureID != "id-1" || rep.Files[4].Warning == "" {
		t.Errorf("label/duplicate warning: %+v / %+v", rep.Files[0], rep.Files[4])
	}
	if rep.Files[3].CaptureID != "" || rep.Files[5].CaptureID != "" {
		t.Errorf("non-identifier capture_id must not be shown: %q %q", rep.Files[3].CaptureID, rep.Files[5].CaptureID)
	}
	assertNoLeak(t, rep)
}

func TestRunBatchClassifiesEveryOutcomeAndSendsBytesUnchanged(t *testing.T) {
	rec := &recorder{}
	rec.answer = func(body string) (int, string) {
		switch {
		case strings.Contains(body, `"new-1"`):
			return 201, `{"capture_id":"new-1","entry_id":7,"analysis_id":null,"created":true}`
		case strings.Contains(body, `"rep-1"`):
			return 200, `{"capture_id":"rep-1","entry_id":3,"analysis_id":4,"created":false}`
		case strings.Contains(body, `"con-1"`):
			return 409, `{"error":"capture_id already exists with different content"}`
		case strings.Contains(body, `"bad-1"`):
			return 422, `{"error":"source must be one of: chatgpt-web, manual"}`
		case strings.Contains(body, `"echo-1"`):
			// A server message that repeats learner text must be withheld.
			return 400, `{"error":"bad ` + learnerMarker + `"}`
		case strings.Contains(body, `"lost-1"`):
			return 0, ""
		case strings.Contains(body, `"oops-1"`):
			return 500, `{"error":"could not import capture"}`
		case strings.Contains(body, `"junk-1"`):
			return 201, `not json`
		}
		return 418, ""
	}
	srv := httptest.NewServer(rec)
	defer srv.Close()

	dir := t.TempDir()
	newBody := "  " + captureJSON("new-1", learnerMarker) + "\n\n" // odd whitespace must survive
	paths := []string{
		writeFile(t, dir, "01.json", newBody),
		writeFile(t, dir, "02.json", captureJSON("rep-1", "x")),
		writeFile(t, dir, "03.json", captureJSON("con-1", "x")),
		writeFile(t, dir, "04.json", captureJSON("bad-1", "x")),
		writeFile(t, dir, "05.json", `{"capture_id":"echo-1","original_input":"bad `+learnerMarker+`"}`),
		writeFile(t, dir, "06.json", ""),
		writeFile(t, dir, "07.json", captureJSON("lost-1", "x")),
		writeFile(t, dir, "08.json", captureJSON("oops-1", "x")),
		writeFile(t, dir, "09.json", captureJSON("junk-1", "x")),
		writeFile(t, dir, "10.json", captureJSON("new-1", "x")),
	}
	c, _ := New(srv.URL)
	rep, err := c.RunBatch(context.Background(), paths)
	if err != nil {
		t.Fatal(err)
	}
	type exp struct {
		o       Outcome
		checked Checked
		status  int
	}
	want := []exp{
		{OutcomeCreated, CheckedServer, 201},
		{OutcomeReplayed, CheckedServer, 200},
		{OutcomeConflict, CheckedServer, 409},
		{OutcomeInvalid, CheckedServer, 422},
		{OutcomeInvalid, CheckedServer, 400},
		{OutcomeInvalid, CheckedLocal, 0},
		{OutcomeUnconfirmed, CheckedNone, 0},
		{OutcomeUnconfirmed, CheckedNone, 500},
		{OutcomeUnconfirmed, CheckedNone, 0},
		// 07, 08, 09 are three unconfirmed in a row, so 10 is never sent.
		{OutcomeNotAttempted, CheckedNone, 0},
	}
	for i, f := range rep.Files {
		if f.Outcome != want[i].o || f.Checked != want[i].checked || f.Status != want[i].status {
			t.Errorf("%s: got %s/%s/%d (%s), want %s/%s/%d", filepath.Base(f.Path), f.Outcome, f.Checked, f.Status, f.Detail, want[i].o, want[i].checked, want[i].status)
		}
	}
	if rep.StoppedWhy == "" || rep.Interrupted {
		t.Errorf("want stopped (not interrupted), got stopped=%q interrupted=%v", rep.StoppedWhy, rep.Interrupted)
	}
	if rep.Files[0].EntryID != 7 || rep.Files[1].AnalysisID == nil || *rep.Files[1].AnalysisID != 4 {
		t.Errorf("ids not carried: %+v %+v", rep.Files[0], rep.Files[1])
	}
	if !strings.Contains(rep.Files[3].Detail, "source must be one of") {
		t.Errorf("server validation message missing: %q", rep.Files[3].Detail)
	}
	if !strings.Contains(rep.Files[4].Detail, "withheld") {
		t.Errorf("echoing server message not withheld: %q", rep.Files[4].Detail)
	}
	// Exactly the eight readable files up to the stop were sent, in order, byte for byte.
	if rec.count() != 8 || rec.bodies[0] != newBody {
		t.Fatalf("sent %d requests; first body unchanged=%v", rec.count(), rec.bodies[0] == newBody)
	}
	assertNoLeak(t, rep)
}

func TestRunBatchOneBadFileDoesNotHideOthers(t *testing.T) {
	rec := &recorder{answer: func(body string) (int, string) {
		if strings.Contains(body, `"bad"`) {
			return 422, `{"error":"schema_version must be learning_capture_v1"}`
		}
		return 201, `{"capture_id":"x","entry_id":1,"analysis_id":null,"created":true}`
	}}
	srv := httptest.NewServer(rec)
	defer srv.Close()
	dir := t.TempDir()
	paths := []string{
		writeFile(t, dir, "a.json", captureJSON("a", "x")),
		writeFile(t, dir, "b.json", captureJSON("bad", "x")),
		filepath.Join(dir, "c-missing.json"),
		writeFile(t, dir, "d.json", captureJSON("d", "x")),
	}
	c, _ := New(srv.URL)
	rep, _ := c.RunBatch(context.Background(), paths)
	got := []Outcome{}
	for _, f := range rep.Files {
		got = append(got, f.Outcome)
	}
	want := []Outcome{OutcomeCreated, OutcomeInvalid, OutcomeInvalid, OutcomeCreated}
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("outcomes = %v, want %v", got, want)
	}
}

func TestRunBatchInterruptionLeavesRestNotAttempted(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	release := make(chan struct{})
	rec := &recorder{}
	rec.answer = func(body string) (int, string) {
		if strings.Contains(body, `"b"`) {
			cancel()  // the operator presses Ctrl-C while b is in flight
			<-release // the server stores b but answers too late
		}
		return 201, `{"capture_id":"x","entry_id":1,"analysis_id":null,"created":true}`
	}
	srv := httptest.NewServer(rec)
	defer func() { close(release); srv.Close() }()
	dir := t.TempDir()
	paths := []string{
		writeFile(t, dir, "a.json", captureJSON("a", "x")),
		writeFile(t, dir, "b.json", captureJSON("b", "x")),
		writeFile(t, dir, "c.json", captureJSON("c", "x")),
		writeFile(t, dir, "d.json", captureJSON("d", "x")),
	}
	c, _ := New(srv.URL)
	rep, err := c.RunBatch(ctx, paths)
	if err != nil {
		t.Fatal(err)
	}
	want := []Outcome{OutcomeCreated, OutcomeUnconfirmed, OutcomeNotAttempted, OutcomeNotAttempted}
	for i, f := range rep.Files {
		if f.Outcome != want[i] {
			t.Errorf("%s: %s (%s), want %s", filepath.Base(f.Path), f.Outcome, f.Detail, want[i])
		}
	}
	if !rep.Interrupted || rec.count() != 2 {
		t.Fatalf("interrupted=%v requests=%d, want true/2", rep.Interrupted, rec.count())
	}
	if rep.Files[2].CaptureID != "c" {
		t.Errorf("not-attempted files keep their label: %+v", rep.Files[2])
	}
}

func TestRunBatchConnectionFailureIsNotAttempted(t *testing.T) {
	srv := httptest.NewServer(http.NotFoundHandler())
	url := srv.URL
	srv.Close() // nothing listens there now
	dir := t.TempDir()
	var paths []string
	for _, id := range []string{"a", "b", "c", "d", "e"} {
		paths = append(paths, writeFile(t, dir, id+".json", captureJSON(id, "x")))
	}
	c, _ := New(url)
	rep, err := c.RunBatch(context.Background(), paths)
	if err != nil {
		t.Fatal(err)
	}
	for i, f := range rep.Files {
		if f.Outcome != OutcomeNotAttempted {
			t.Errorf("file %d: %s (%s), want not_attempted", i+1, f.Outcome, f.Detail)
		}
	}
	if !strings.Contains(rep.Files[0].Detail, "could not connect") || !strings.Contains(rep.Files[4].Detail, "without a server response") {
		t.Errorf("details: %q / %q", rep.Files[0].Detail, rep.Files[4].Detail)
	}
	if rep.StoppedWhy == "" {
		t.Error("batch should stop after 3 connection failures")
	}
}

func TestRunBatchRefusalSendsNothing(t *testing.T) {
	rec := &recorder{answer: func(string) (int, string) { return 201, "{}" }}
	srv := httptest.NewServer(rec)
	defer srv.Close()
	dir := t.TempDir()
	a := writeFile(t, dir, "a.json", captureJSON("a", "x"))
	c, _ := New(srv.URL)
	if _, err := c.RunBatch(context.Background(), []string{a, a}); !errors.Is(err, ErrBatchRefused) {
		t.Fatalf("err = %v, want refusal", err)
	}
	if rec.count() != 0 {
		t.Fatalf("refused batch sent %d requests", rec.count())
	}
}

func TestBoundAndLabel(t *testing.T) {
	if got := bound("a\nb\tc"); got != "a b c" {
		t.Errorf("bound = %q", got)
	}
	long := strings.Repeat("é", 200)
	if got := bound(long); len(got) > maxDetail+len("…") || !strings.HasSuffix(got, "…") {
		t.Errorf("bound long = %d bytes", len(got))
	}
	for in, want := range map[string]string{
		`{"capture_id":" ok-1:x.y_z "}`: "ok-1:x.y_z",
		`{"capture_id":"-lead"}`:        "",
		`{"capture_id":7}`:              "",
		`[1,2]`:                         "",
	} {
		if got := captureLabel([]byte(in)); got != want {
			t.Errorf("captureLabel(%s) = %q, want %q", in, got, want)
		}
	}
}
