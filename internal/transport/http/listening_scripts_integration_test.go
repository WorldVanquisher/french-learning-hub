package http_test

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening"
	transporthttp "french-learning-app/internal/transport/http"
)

func embeddedScripts(t *testing.T) domain.ListeningScriptPack {
	t.Helper()
	pack, err := domain.ParseListeningScriptPack(listening.ScriptPack())
	if err != nil {
		t.Fatalf("embedded pack: %v", err)
	}
	return pack
}

func listeningCounts(t *testing.T, db *sql.DB) string {
	t.Helper()
	var parts []string
	for _, table := range []string{"listening_materials", "listening_transcripts", "listening_exercises", "listening_preparations",
		"listening_playlist_items", "learning_entries", "entry_analyses"} {
		parts = append(parts, table+"="+itoa(int64(countRows(t, db, table))))
	}
	return strings.Join(parts, " ")
}

func postScript(t *testing.T, srv *httptest.Server, id string) (int, map[string]any, string) {
	t.Helper()
	req, _ := http.NewRequest(http.MethodPost, srv.URL+"/listening/scripts/"+id, nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return resp.StatusCode, out, resp.Header.Get("Idempotency-Replayed")
}

// All 12 workbook scripts import as script-only lessons without a provider:
// no link, no video ID, no timestamp; lines keep their speakers; the authored
// exercise holds all 10 questions with their choices, key and evidence. A
// repeat import replays the same lesson and writes nothing; reopening reads
// the same lesson; the list labels each one and none is a playlist item.
func TestListeningScripts_ImportAllTwelveReplayAndReopen(t *testing.T) {
	pack := embeddedScripts(t)
	srv, db, _ := buildListeningServer(t, filepath.Join(t.TempDir(), "scripts.db"), nil, application.WithListeningScripts(pack))

	status, list := doJSON(t, http.MethodGet, srv.URL+"/listening/scripts", "")
	scripts, _ := list["scripts"].([]any)
	if status != http.StatusOK || len(scripts) != 12 || list["pack"] != domain.ListeningScriptPackID {
		t.Fatalf("GET /listening/scripts: %d %v", status, list)
	}
	for _, s := range scripts {
		row := s.(map[string]any)
		if row["imported_material_id"] != nil || row["lines"] == nil || row["questions"].(float64) != 10 {
			t.Fatalf("script row before import: %v", row)
		}
		for _, leak := range []string{"choices", "expected_answer", "segments", "text"} {
			if _, ok := row[leak]; ok {
				t.Fatalf("script list exposes %q", leak)
			}
		}
	}

	ids := map[string]float64{}
	for i, sc := range pack.Scripts {
		status, lesson, replayed := postScript(t, srv, sc.ID)
		if status != http.StatusCreated || replayed != "" {
			t.Fatalf("import %s: %d %q %v", sc.ID, status, replayed, lesson)
		}
		m := lesson["material"].(map[string]any)
		if m["source_kind"] != domain.ListeningSourceAuthoredScript || m["video_id"] != nil || m["source_url"] != nil ||
			m["pack_script_id"] != sc.PackScriptID() || m["title"] != sc.Title {
			t.Fatalf("%s material = %v", sc.ID, m)
		}
		ids[sc.ID] = m["id"].(float64)
		tr := lesson["transcript"].(map[string]any)
		segs := tr["segments"].([]any)
		if tr["version"].(float64) != 1 || tr["has_timestamps"] != false || len(segs) != len(sc.Lines) {
			t.Fatalf("%s transcript = %v", sc.ID, tr)
		}
		for k, s := range segs {
			seg := s.(map[string]any)
			if seg["start_seconds"] != nil || seg["speaker"] != sc.Lines[k].Speaker || seg["text"] != sc.Lines[k].Text || seg["index"].(float64) != float64(k+1) {
				t.Fatalf("%s segment %d = %v", sc.ID, k+1, seg)
			}
		}
		ex := lesson["exercises"].([]any)
		if len(ex) != 1 || lesson["state"] != "prepared" || lesson["in_playlist"] != false {
			t.Fatalf("%s: exercises %d, state %v, in_playlist %v", sc.ID, len(ex), lesson["state"], lesson["in_playlist"])
		}
		e := ex[0].(map[string]any)
		if e["generator"] != domain.ListeningAuthoredGenerator || e["status"] != "completed" || e["transcript_id"] != tr["id"] {
			t.Fatalf("%s exercise = %v", sc.ID, e)
		}
		items := path(e, "content", "items").([]any)
		if len(items) != 10 {
			t.Fatalf("%s: %d items", sc.ID, len(items))
		}
		first := items[0].(map[string]any)
		if first["id"] != sc.Questions[0].ID || first["expected_answer"] != sc.Questions[0].ExpectedAnswer || first["evidence"] == nil {
			t.Fatalf("%s item 1 = %v", sc.ID, first)
		}
		if i == 4 { // u05: the script used in the owner walkthrough
			if c := first["choices"].([]any); len(c) != 3 {
				t.Fatalf("u05 item 1 choices = %v", c)
			}
		}
	}
	before := listeningCounts(t, db)
	if !strings.HasPrefix(before, "listening_materials=12 listening_transcripts=12 listening_exercises=12 listening_preparations=0 listening_playlist_items=0") {
		t.Fatalf("after 12 imports: %s", before)
	}

	// Repeat imports replay and write nothing.
	for _, sc := range pack.Scripts {
		status, lesson, replayed := postScript(t, srv, sc.ID)
		if status != http.StatusOK || replayed != "true" || path(lesson, "material", "id").(float64) != ids[sc.ID] {
			t.Fatalf("repeat import %s: %d %q", sc.ID, status, replayed)
		}
	}
	if after := listeningCounts(t, db); after != before {
		t.Fatalf("repeat imports wrote rows: %s -> %s", before, after)
	}

	// Reopening reads the same lesson; the list labels every script.
	u05 := pack.Scripts[4]
	status, reopened := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+itoa(int64(ids[u05.ID])), "")
	if status != http.StatusOK || path(reopened, "material", "source_kind") != domain.ListeningSourceAuthoredScript || path(reopened, "material", "source_url") != nil {
		t.Fatalf("reopen: %d %v", status, reopened)
	}
	_, list = doJSON(t, http.MethodGet, srv.URL+"/listening/materials", "")
	if mats := list["materials"].([]any); len(mats) != 12 {
		t.Fatalf("materials listed: %d", len(mats))
	}
	for _, r := range list["materials"].([]any) {
		row := r.(map[string]any)
		if path(row, "material", "source_kind") != domain.ListeningSourceAuthoredScript || row["state"] != "prepared" || row["in_playlist"] != false {
			t.Fatalf("list row = %v", row)
		}
	}
	_, list = doJSON(t, http.MethodGet, srv.URL+"/listening/scripts", "")
	for _, s := range list["scripts"].([]any) {
		row := s.(map[string]any)
		if row["imported_material_id"].(float64) != ids[row["id"].(string)] {
			t.Fatalf("script row after import: %v", row)
		}
	}
	if status, _, _ := postScript(t, srv, "ls-wb1-u99"); status != http.StatusNotFound {
		t.Fatalf("unknown script: %d", status)
	}
}

// A server whose pack changed refuses to re-import a script with other
// content: 409 script_conflict, nothing written, the stored lesson unchanged.
func TestListeningScripts_ChangedPackConflictsAndWritesNothing(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "scripts.db")
	pack := embeddedScripts(t)
	first, db, _ := buildListeningServer(t, dbPath, nil, application.WithListeningScripts(pack))
	if status, _, _ := postScript(t, first, pack.Scripts[0].ID); status != http.StatusCreated {
		t.Fatalf("first import: %d", status)
	}
	before := listeningCounts(t, db)

	changed := embeddedScripts(t)
	changed.Scripts[0].Questions[1].RationaleEN += " (edited)"
	second, _, _ := buildListeningServer(t, dbPath, nil, application.WithListeningScripts(changed))
	status, body, _ := postScript(t, second, pack.Scripts[0].ID)
	if status != http.StatusConflict || body["code"] != "script_conflict" {
		t.Fatalf("changed import: %d %v", status, body)
	}
	if after := listeningCounts(t, db); after != before {
		t.Fatalf("a refused import wrote rows: %s -> %s", before, after)
	}
}

// An authored script takes no learner transcript; YouTube material is
// unchanged: a link is still required, and a saved link keeps its video ID.
func TestListeningScripts_FixedTextAndYouTubeUnchanged(t *testing.T) {
	pack := embeddedScripts(t)
	srv, db, _ := buildListeningServer(t, filepath.Join(t.TempDir(), "scripts.db"), nil, application.WithListeningScripts(pack))
	_, lesson, _ := postScript(t, srv, pack.Scripts[0].ID)
	id := itoa(int64(path(lesson, "material", "id").(float64)))
	before := listeningCounts(t, db)
	status, body := doJSON(t, http.MethodPost, srv.URL+"/listening/materials/"+id+"/transcripts", `{"transcript":"Une autre version."}`)
	if status != http.StatusConflict || body["code"] != "authored_script" {
		t.Fatalf("transcript on a script: %d %v", status, body)
	}
	if after := listeningCounts(t, db); after != before {
		t.Fatalf("a refused transcript wrote rows: %s -> %s", before, after)
	}

	status, body = doJSON(t, http.MethodPost, srv.URL+"/listening/materials", `{"source_url":"","title":"Sans lien","transcript":"Bonjour."}`)
	if status != http.StatusUnprocessableEntity || !strings.Contains(body["error"].(string), "source_url is required") {
		t.Fatalf("material without a link: %d %v", status, body)
	}
	yt := createLesson(t, srv, authoredTranscript(t))
	_, got := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+itoa(int64(yt)), "")
	m := got["material"].(map[string]any)
	if m["source_kind"] != domain.ListeningSourceYouTube || m["video_id"] != "FLHlisten01" ||
		m["source_url"] != "https://www.youtube.com/watch?v=FLHlisten01" || m["pack_script_id"] != nil {
		t.Fatalf("youtube material = %v", m)
	}
}

// A missed point becomes a learning record only through the explicit capture
// the workbench sends (source manual, no analysis); the script is untouched.
func TestListeningScripts_MissedPointIsAnExplicitCapture(t *testing.T) {
	pack := embeddedScripts(t)
	srv, db, _ := buildListeningServer(t, filepath.Join(t.TempDir(), "scripts.db"), nil, application.WithListeningScripts(pack))
	postScript(t, srv, pack.Scripts[4].ID)
	if n := countRows(t, db, "learning_entries"); n != 0 {
		t.Fatalf("an import created %d learning records", n)
	}
	capture, _ := json.Marshal(map[string]string{
		"schema_version": "learning_capture_v1", "capture_id": "listening-1-1-3-test", "source": "manual",
		"original_input":   "Pourquoi « il reste de la place » veut dire que ce n'est pas complet ?",
		"original_context": "Listening exercise: À l'accueil de la Maison des langues\nSource: authored script (no audio, no video)",
	})
	status, body := doJSON(t, http.MethodPost, srv.URL+"/captures", string(capture))
	if status != http.StatusCreated || body["analysis_id"] != nil {
		t.Fatalf("capture: %d %v", status, body)
	}
	if n := countRows(t, db, "entry_analyses"); n != 0 {
		t.Fatalf("the capture created %d analyses", n)
	}
	if n := countRows(t, db, "listening_exercises"); n != 1 {
		t.Fatalf("listening exercises = %d", n)
	}
}

// The public demo never reaches the script routes, at the root or under /api.
func TestListeningScripts_UnavailableInThePublicDemo(t *testing.T) {
	_, _, handler := buildListeningServer(t, filepath.Join(t.TempDir(), "demo.db"), nil, application.WithListeningScripts(embeddedScripts(t)))
	demo := httptest.NewServer(transporthttp.NewPublicDemoBoundary(handler.Routes(), false))
	t.Cleanup(demo.Close)
	for _, prefix := range []string{"", "/api"} {
		for _, p := range []string{"/listening/scripts", "/listening/scripts/ls-wb1-u01"} {
			if status, _ := doJSON(t, http.MethodGet, demo.URL+prefix+p, ""); status != http.StatusNotFound {
				t.Errorf("GET %s%s in the demo: %d", prefix, p, status)
			}
		}
		if status, _ := doJSON(t, http.MethodPost, demo.URL+prefix+"/listening/scripts/ls-wb1-u01", ""); status != http.StatusMethodNotAllowed {
			t.Errorf("POST %s/listening/scripts/ls-wb1-u01 in the demo: %d", prefix, status)
		}
	}
}

// echoGenerator is a local stand-in for the opt-in generator: it builds a
// valid generated exercise from the segments it receives and records them.
type echoGenerator struct {
	requests []domain.ListeningGenerationRequest
}

func (g *echoGenerator) Name() string { return "openai:local-echo:listening_exercise_v1" }

func (g *echoGenerator) Generate(_ context.Context, req domain.ListeningGenerationRequest) (domain.ListeningExerciseContent, error) {
	g.requests = append(g.requests, req)
	first, last := req.Segments[0], req.Segments[len(req.Segments)-1]
	return domain.ListeningExerciseContent{
		Items: []domain.ListeningItem{
			{Kind: domain.ListeningMainIdea, Question: "Q1", ExpectedAnswer: "A1", RationaleEN: "r", RationaleZH: "r", Segments: []int{first.Index}},
			{Kind: domain.ListeningDetail, Question: "Q2", ExpectedAnswer: "A2", RationaleEN: "r", RationaleZH: "r", Segments: []int{last.Index}},
		},
		Annotations: []domain.ListeningAnnotation{{Kind: "vocabulary", Segment: first.Index, Excerpt: strings.Fields(first.Text)[0], NoteEN: "n", NoteZH: "n"}},
	}, nil
}

// Pins the CURRENT contract for model preparation on a script-only lesson; it
// is documented in docs/ARCHITECTURE.md §4.3 and was not changed by the UI work.
// The explicit route accepts it like any lesson with a transcript: one call
// with the title and the untimed script lines, a stored generated exercise
// newest first beside the authored one (which stays stored), and import still
// replays. With the provider disabled it is 503 and nothing is stored.
func TestListeningScripts_ModelPreparationOnAScriptUsesTheExistingExplicitPath(t *testing.T) {
	pack := embeddedScripts(t)
	gen := &echoGenerator{}
	srv, db, _ := buildListeningServer(t, filepath.Join(t.TempDir(), "scripts.db"), gen, application.WithListeningScripts(pack))
	sc := pack.Scripts[0]
	_, lesson, _ := postScript(t, srv, sc.ID)
	id := itoa(int64(path(lesson, "material", "id").(float64)))

	status, body := doJSON(t, http.MethodPost, srv.URL+"/listening/materials/"+id+"/exercises", "")
	if status != http.StatusCreated || path(body, "exercise", "generator") != gen.Name() {
		t.Fatalf("prepare on a script: %d %v", status, body)
	}
	if len(gen.requests) != 1 || gen.requests[0].Title != sc.Title || len(gen.requests[0].Segments) != len(sc.Lines) {
		t.Fatalf("generator requests = %+v", gen.requests)
	}
	for _, s := range gen.requests[0].Segments {
		if s.StartSeconds != nil {
			t.Fatalf("a script segment reached the generator with a time: %+v", s)
		}
	}
	_, after := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id, "")
	var gens []string
	for _, e := range after["exercises"].([]any) {
		gens = append(gens, e.(map[string]any)["generator"].(string))
	}
	if strings.Join(gens, ",") != gen.Name()+","+domain.ListeningAuthoredGenerator || after["state"] != "prepared" {
		t.Fatalf("exercises newest first = %v, state %v", gens, after["state"])
	}
	before := listeningCounts(t, db)
	if status, _, replayed := postScript(t, srv, sc.ID); status != http.StatusOK || replayed != "true" {
		t.Fatalf("import after a model preparation: %d %q", status, replayed)
	}
	if now := listeningCounts(t, db); now != before {
		t.Fatalf("replay wrote rows: %s -> %s", before, now)
	}

	off, offDB, _ := buildListeningServer(t, filepath.Join(t.TempDir(), "off.db"), nil, application.WithListeningScripts(pack))
	_, offLesson, _ := postScript(t, off, sc.ID)
	offID := itoa(int64(path(offLesson, "material", "id").(float64)))
	if status, _ := doJSON(t, http.MethodPost, off.URL+"/listening/materials/"+offID+"/exercises", ""); status != http.StatusServiceUnavailable {
		t.Fatalf("prepare with the provider disabled: %d", status)
	}
	if n := countRows(t, offDB, "listening_exercises"); n != 1 {
		t.Fatalf("a disabled preparation stored rows: %d exercises", n)
	}
}
