package http_test

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// Portable learning history (learning_history_export_v1) end to end on
// disposable databases: options, omitted vs absent, no audio or credentials,
// stable keys, a read-only import preview (round trip, fresh server,
// truncated, corrupted, conflicting, older Speaking export).

func rawGet(t *testing.T, url string) (int, []byte) {
	t.Helper()
	resp, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, b
}

func importPreview(t *testing.T, srv *httptest.Server, body []byte) map[string]any {
	t.Helper()
	resp, err := http.Post(srv.URL+"/learning-history/import-preview", "application/x-ndjson", bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&out)
	if resp.StatusCode != http.StatusOK || out["writes"] != false {
		t.Fatalf("import preview: %d %v", resp.StatusCode, out)
	}
	return out
}

func ndjsonLines(b []byte) []map[string]any {
	var out []map[string]any
	for _, l := range bytes.Split(bytes.TrimSpace(b), []byte("\n")) {
		var m map[string]any
		_ = json.Unmarshal(l, &m)
		out = append(out, m)
	}
	return out
}

// seedHistory stores one of each record kind; it returns the transcript text.
func seedHistory(t *testing.T, srv *httptest.Server) string {
	t.Helper()
	_, lesson, _ := postScript(t, srv, "ls-wb1-u05")
	if status, body := saveMistake(t, srv, "history-l01", lesson["current_exercise_id"].(float64), 1, "Le lundi."); status != http.StatusCreated {
		t.Fatalf("save: %d %v", status, body)
	}
	_, started := doJSON(t, http.MethodPost, srv.URL+"/speaking/prompts/sp-invitation-reponse", "")
	ex := int64(path(started, "exercise", "id").(float64))
	_, saved := doJSON(t, http.MethodPost, fmt.Sprintf("%s/speaking/exercises/%d/takes", srv.URL, ex), `{"audio_source":"none"}`)
	text := "Salut Léa ! Merci pour ton invitation, j'arrive samedi."
	doJSON(t, http.MethodPost, fmt.Sprintf("%s/speaking/takes/%d/transcripts", srv.URL, int64(saved["take_id"].(float64))), fmt.Sprintf(`{"text":%q}`, text))
	// A second take with no transcript: its transcripts are absent, not omitted.
	doJSON(t, http.MethodPost, fmt.Sprintf("%s/speaking/exercises/%d/takes", srv.URL, ex), `{"audio_source":"none"}`)
	_, task := doJSON(t, http.MethodPost, srv.URL+"/writing/tasks", `{"title":"Lettre","prompt":"Écrivez.","requirements":[],"word_min":3,"word_max":80}`)
	doJSON(t, http.MethodPost, fmt.Sprintf("%s/writing/tasks/%d/drafts", srv.URL, int64(path(task, "task", "id").(float64))), `{"text":"Chère Éloïse, à bientôt."}`)
	return text
}

func TestHistoryExport_OptionsOmittedAbsentAndNeverAudioOrCredentials(t *testing.T) {
	srv, _, _ := buildReviewTodayServer(t)
	text := seedHistory(t, srv)
	// The preview says what an export holds before downloading it.
	status, prev := doJSON(t, http.MethodGet, srv.URL+"/learning-history/export-preview", "")
	if status != http.StatusOK || path(prev, "header", "format") != "learning_history_export_v1" ||
		path(prev, "header", "included", "audio") != false || path(prev, "header", "included", "credentials") != false ||
		path(prev, "header", "included", "transcripts") != false || path(prev, "header", "omitted_texts", "transcripts") != 1.0 {
		t.Fatalf("preview: %d %v", status, prev)
	}
	files := prev["files"].([]any)
	if len(files) != 2 || path(files[0], "app_import") != "preview_only" || path(files[1], "app_import") != "none" || path(files[1], "opens_as_text") != true {
		t.Fatalf("files: %v", files)
	}
	for _, q := range []string{"?audio=true", "?credentials=true", "?transcripts=yes", "?format=pdf"} {
		if status, _ := rawGet(t, srv.URL+"/learning-history/export"+q); status != http.StatusBadRequest {
			t.Fatalf("%s: %d", q, status)
		}
	}
	// Default: metadata only. Texts are omitted, not missing.
	_, body := rawGet(t, srv.URL+"/learning-history/export")
	if bytes.Contains(body, []byte("Salut Léa")) || bytes.Contains(body, []byte("Chère Éloïse")) || bytes.Contains(body, []byte("Je n'ai pas compris")) {
		t.Fatal("texts were exported without being selected")
	}
	lines := ndjsonLines(body)
	if lines[0]["kind"] != "header" || lines[len(lines)-1]["kind"] != "footer" || int(lines[len(lines)-1]["records"].(float64)) != len(lines)-2 {
		t.Fatalf("frame: %v … %v", lines[0], lines[len(lines)-1])
	}
	states := map[string]string{}
	keys := map[string]bool{}
	for _, r := range lines[1 : len(lines)-1] {
		keys[r["key"].(string)] = true
		if r["kind"] == "speaking_take" {
			states[fmt.Sprint(r["number"])] = r["transcripts_state"].(string)
			if r["audio_bytes_exported"] != false {
				t.Fatalf("audio flag: %v", r)
			}
		}
		if r["kind"] == "notebook_record" && (r["original_input_state"] != "omitted" || r["original_input"] != nil) {
			t.Fatalf("notebook text: %v", r)
		}
	}
	if states["1"] != "omitted" || states["2"] != "absent" {
		t.Fatalf("transcript states: %v", states)
	}
	for _, k := range []string{"speaking:prompt:sp-invitation-reponse:take:1", "notebook:capture:history-l01", "listening:script:flh_listening_script_pack_v1/ls-wb1-u05"} {
		if !keys[k] {
			t.Fatalf("stable key %s missing: %v", k, keys)
		}
	}
	// Selected: the texts are there, exactly.
	_, full := rawGet(t, srv.URL+"/learning-history/export?transcripts=true&notes=true")
	if !bytes.Contains(full, []byte(text)) || !bytes.Contains(full, []byte("Chère Éloïse, à bientôt.")) {
		t.Fatal("selected texts missing")
	}
	// Nothing resembling a credential or configuration value.
	for _, b := range [][]byte{body, full} {
		for _, bad := range []string{"OPENAI", "sk-", "api_key", "Bearer", "DB_PATH", "/home/"} {
			if bytes.Contains(b, []byte(bad)) {
				t.Fatalf("export contains %q", bad)
			}
		}
	}
	_, txt := rawGet(t, srv.URL+"/learning-history/export?format=text&transcripts=true")
	if !strings.Contains(string(txt), text) || !strings.Contains(string(txt), "not importable") && !strings.Contains(string(txt), "for reading") {
		t.Fatalf("text copy: %s", txt)
	}
}

func TestHistoryExport_ImportPreviewRoundTripIntegrityConflictsAndOlderExports(t *testing.T) {
	srv, _, db := buildReviewTodayServer(t)
	seedHistory(t, srv)
	_, body := rawGet(t, srv.URL+"/learning-history/export?transcripts=true&notes=true")
	before := listeningCounts(t, db)
	// Round trip on the same server: complete, everything already stored, nothing written.
	p := importPreview(t, srv, body)
	if p["integrity"] != "complete" || p["new"] != 0.0 || p["conflicts"] != 0.0 || p["same"].(float64) < 5 {
		t.Fatalf("round trip: %v", p)
	}
	if after := listeningCounts(t, db); after != before {
		t.Fatalf("the preview wrote: %s → %s", before, after)
	}
	// A fresh server: everything would be new.
	fresh, _, _ := buildReviewTodayServer(t)
	if p := importPreview(t, fresh, body); p["integrity"] != "complete" || p["same"] != 0.0 || p["new"] != p["same"].(float64)+float64(len(p["rows"].([]any))) {
		t.Fatalf("fresh: %v", p)
	}
	// Truncated: no footer; cut mid-line.
	lines := bytes.Split(bytes.TrimSpace(body), []byte("\n"))
	noFooter := bytes.Join(lines[:len(lines)-1], []byte("\n"))
	if p := importPreview(t, srv, noFooter); p["integrity"] != "truncated" {
		t.Fatalf("no footer: %v", p)
	}
	if p := importPreview(t, srv, body[:len(body)-40]); p["integrity"] != "truncated" || !strings.Contains(fmt.Sprint(p["problems"]), "not complete JSON") {
		t.Fatalf("cut: %v", p)
	}
	// Corrupted: a record edited after export, still valid JSON.
	edited := bytes.Replace(body, []byte(`"word_count":`), []byte(`"word_count":1`), 1)
	if p := importPreview(t, srv, edited); p["integrity"] != "corrupted" {
		t.Fatalf("edited: %v", p)
	}
	if p := importPreview(t, srv, []byte("not an export")); p["integrity"] != "unreadable" {
		t.Fatalf("garbage: %v", p)
	}
	// A conflict: the stored take gained a version after the export.
	var take int64
	for _, r := range ndjsonLines(body) {
		if r["kind"] == "speaking_take" && r["number"] == 1.0 {
			fmt.Sscanf(r["ref"].(string), "speaking:take:%d", &take)
		}
	}
	doJSON(t, http.MethodPost, fmt.Sprintf("%s/speaking/takes/%d/transcripts", srv.URL, take), `{"text":"Salut Léa, merci : j'arrive samedi midi."}`)
	p = importPreview(t, srv, body)
	if p["conflicts"] != 1.0 {
		t.Fatalf("conflict: %v", p)
	}
	for _, r := range p["rows"].([]any) {
		if path(r, "status") == "conflict" && (path(r, "kind") != "speaking_take" || fmt.Sprint(path(r, "fields")) != "[transcripts]" ||
			!strings.Contains(path(r, "resolution").(string), "keep the stored record")) {
			t.Fatalf("conflict row: %v", r)
		}
	}
	// An older Speaking export (speaking_attempt_export_v1): no header or checksum.
	_, older := rawGet(t, srv.URL+"/speaking/export")
	p = importPreview(t, srv, older)
	if p["format"] != "speaking_attempt_export_v1" || p["integrity"] != "unchecked" || p["conflicts"] != 0.0 || p["same"] != 2.0 ||
		!strings.Contains(fmt.Sprint(p["missing_fields"]), "header and checksum") {
		t.Fatalf("older export: %v", p)
	}
}
