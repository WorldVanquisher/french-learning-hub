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
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening"
	"french-learning-app/internal/storage/sqlite"
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

// An authored script keeps its fixed, authored exercise. The explicit
// preparation route refuses it with 409 authored_script before any attempt is
// recorded: the generator is never called and nothing is stored, with the
// provider enabled or disabled, with or without an Idempotency-Key. The lesson
// read names the authored exercise as current_exercise_id. A generated row
// stored on a script by the earlier contract (simulated here through the
// repository's preparation path) stays stored but is never current, and import
// still replays. YouTube preparation is unchanged: 201, and the generated
// exercise becomes current.
// exerciseField reads one field of the lesson's i-th exercise (newest first).
func exerciseField(lesson map[string]any, i int, key string) any {
	ex, ok := lesson["exercises"].([]any)
	if !ok || i >= len(ex) {
		return nil
	}
	return ex[i].(map[string]any)[key]
}

func TestListeningScripts_ModelPreparationNeverDisplacesTheAuthoredExercise(t *testing.T) {
	pack := embeddedScripts(t)
	gen := &echoGenerator{}
	dbPath := filepath.Join(t.TempDir(), "scripts.db")
	srv, db, _ := buildListeningServer(t, dbPath, gen, application.WithListeningScripts(pack))
	sc := pack.Scripts[0]
	_, lesson, _ := postScript(t, srv, sc.ID)
	materialID := int64(path(lesson, "material", "id").(float64))
	id := itoa(materialID)
	authoredID := exerciseField(lesson, 0, "id")
	if lesson["current_exercise_id"] != authoredID || exerciseField(lesson, 0, "generator") != domain.ListeningAuthoredGenerator {
		t.Fatalf("imported lesson: current %v, exercises %v", lesson["current_exercise_id"], lesson["exercises"])
	}

	before := listeningCounts(t, db)
	for _, key := range []string{"", "0b8f3c1e-2d4a-4b6c-8e9f-1a2b3c4d5e6f"} {
		req, _ := http.NewRequest(http.MethodPost, srv.URL+"/listening/materials/"+id+"/exercises", nil)
		if key != "" {
			req.Header.Set("Idempotency-Key", key)
		}
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		var body map[string]any
		_ = json.NewDecoder(resp.Body).Decode(&body)
		resp.Body.Close()
		if resp.StatusCode != http.StatusConflict || body["code"] != "authored_script" {
			t.Fatalf("prepare on a script (key %q): %d %v", key, resp.StatusCode, body)
		}
	}
	if len(gen.requests) != 0 {
		t.Fatalf("the generator was called for a script: %+v", gen.requests)
	}
	if after := listeningCounts(t, db); after != before {
		t.Fatalf("a refused preparation wrote rows: %s -> %s", before, after)
	}
	if status, _ := doJSON(t, http.MethodGet, srv.URL+"/listening/preparations/0b8f3c1e-2d4a-4b6c-8e9f-1a2b3c4d5e6f", ""); status != http.StatusNotFound {
		t.Fatalf("a refused preparation left an attempt: %d", status)
	}

	// A generated row stored on the script by the earlier contract.
	repo := sqlite.NewListeningRepository(db)
	now := time.Now().UTC()
	prep, tr, _, err := repo.StartPreparation(context.Background(), domain.NewListeningPreparation{
		OperationID: "legacy-script-preparation", MaterialID: materialID, Trigger: domain.ListeningTriggerExplicit, Now: now, Deadline: now.Add(time.Minute)})
	if err != nil {
		t.Fatalf("legacy attempt: %v", err)
	}
	legacy, _ := gen.Generate(context.Background(), domain.ListeningGenerationRequest{Title: sc.Title, Segments: tr.Segments})
	if _, _, err := repo.FinishPreparation(context.Background(), prep.ID, domain.PreparationOutcome(nil),
		domain.ListeningExercise{MaterialID: materialID, TranscriptID: tr.ID, Status: domain.ListeningExerciseCompleted, Generator: gen.Name(), Content: &legacy}, now); err != nil {
		t.Fatalf("legacy exercise: %v", err)
	}
	_, after := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id, "")
	if exerciseField(after, 0, "generator") != gen.Name() || after["current_exercise_id"] != authoredID {
		t.Fatalf("legacy generated row: newest %v, current %v (authored %v)", exerciseField(after, 0, "generator"), after["current_exercise_id"], authoredID)
	}
	if status, _, replayed := postScript(t, srv, sc.ID); status != http.StatusOK || replayed != "true" {
		t.Fatalf("import after a legacy preparation: %d %q", status, replayed)
	}

	// Disabled provider: still the script rule, nothing stored.
	off, offDB, _ := buildListeningServer(t, filepath.Join(t.TempDir(), "off.db"), nil, application.WithListeningScripts(pack))
	_, offLesson, _ := postScript(t, off, sc.ID)
	offID := itoa(int64(path(offLesson, "material", "id").(float64)))
	if status, body := doJSON(t, http.MethodPost, off.URL+"/listening/materials/"+offID+"/exercises", ""); status != http.StatusConflict || body["code"] != "authored_script" {
		t.Fatalf("prepare on a script with the provider disabled: %d %v", status, body)
	}
	if n := countRows(t, offDB, "listening_exercises"); n != 1 {
		t.Fatalf("a refused preparation stored rows: %d exercises", n)
	}
	if status, _ := doJSON(t, http.MethodPost, off.URL+"/listening/materials/999/exercises", ""); status != http.StatusServiceUnavailable {
		t.Fatalf("unknown material with the provider disabled: %d", status)
	}

	// YouTube preparation is unchanged.
	yt := itoa(int64(createLesson(t, srv, authoredTranscript(t))))
	status, body := doJSON(t, http.MethodPost, srv.URL+"/listening/materials/"+yt+"/exercises", "")
	if status != http.StatusCreated || path(body, "exercise", "generator") != gen.Name() || len(gen.requests) != 2 {
		t.Fatalf("prepare on YouTube material: %d %v (%d calls)", status, body, len(gen.requests))
	}
	_, ytLesson := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+yt, "")
	if ytLesson["current_exercise_id"] != path(body, "exercise", "id") || ytLesson["state"] != "prepared" {
		t.Fatalf("youtube lesson after preparation: current %v, state %v", ytLesson["current_exercise_id"], ytLesson["state"])
	}
}

// A pack correction (here: the evidence audit that rewrote u05-l04's
// explanation, which had relied on the reading brochure) does not touch a
// script imported before it. Item IDs and positions are stable. The earlier
// lesson keeps its stored wording, stays listed as imported and keeps
// opening; re-importing it is 409 script_conflict and writes nothing; a
// Mistake Notebook item saved from it still resolves to the words it was saved
// from. A script imported after the correction gets the corrected wording.
func TestListeningScripts_EarlierImportKeepsItsContentAfterAPackCorrection(t *testing.T) {
	ctx := context.Background()
	dbPath := filepath.Join(t.TempDir(), "scripts.db")
	current := embeddedScripts(t)
	earlier := embeddedScripts(t)
	const at = 4 // ls-wb1-u05
	q := &earlier.Scripts[at].Questions[3]
	if earlier.Scripts[at].ID != "ls-wb1-u05" || q.ID != "u05-l04" {
		t.Fatalf("pack order changed: %s %s", earlier.Scripts[at].ID, q.ID)
	}
	q.RationaleEN, q.RationaleZH = "Work ends before the 18:30 class.", "她在18点30分上课前就下班了。"
	q.Evidence, q.Segments = []domain.ListeningEvidence{{Segment: 5, Excerpt: "Je finis le travail à 17 h 30"}}, []int{5}
	if strings.Contains(current.Scripts[at].Questions[3].RationaleEN, "18:30") {
		t.Fatalf("the current pack still relies on the brochure's class time: %q", current.Scripts[at].Questions[3].RationaleEN)
	}

	old, db, _ := buildListeningServer(t, dbPath, nil, application.WithListeningScripts(earlier))
	status, lesson, _ := postScript(t, old, "ls-wb1-u05")
	if status != http.StatusCreated {
		t.Fatalf("earlier import: %d", status)
	}
	materialID := path(lesson, "material", "id")
	exerciseID := int64(exerciseField(lesson, 0, "id").(float64))
	resolver := application.NewMistakeSourceResolver(sqlite.NewListeningRepository(db), nil, nil, nil)
	saved, err := resolver.ResolveSource(ctx, domain.CaptureSourceRef{Type: domain.SourceListeningItem, RecordID: exerciseID, Item: 4})
	if err != nil || saved.ExplanationEN != "Work ends before the 18:30 class." {
		t.Fatalf("earlier item: %+v %v", saved, err)
	}
	before := listeningCounts(t, db)

	srv, _, _ := buildListeningServer(t, dbPath, nil, application.WithListeningScripts(current))
	_, list := doJSON(t, http.MethodGet, srv.URL+"/listening/scripts", "")
	for _, s := range list["scripts"].([]any) {
		row := s.(map[string]any)
		if row["id"] == "ls-wb1-u05" && row["imported_material_id"] != materialID {
			t.Fatalf("the earlier import is no longer listed as imported: %v", row)
		}
	}
	status, body, _ := postScript(t, srv, "ls-wb1-u05")
	if status != http.StatusConflict || body["code"] != "script_conflict" {
		t.Fatalf("re-import after the correction: %d %v", status, body)
	}
	if after := listeningCounts(t, db); after != before {
		t.Fatalf("a refused re-import wrote rows: %s -> %s", before, after)
	}
	_, reopened := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+itoa(int64(materialID.(float64))), "")
	items := path(reopened, "exercises").([]any)[0].(map[string]any)["content"].(map[string]any)["items"].([]any)
	if items[3].(map[string]any)["id"] != "u05-l04" || items[3].(map[string]any)["rationale_en"] != "Work ends before the 18:30 class." ||
		int64(reopened["current_exercise_id"].(float64)) != exerciseID {
		t.Fatalf("reopened earlier lesson: item 4 %v, current %v", items[3], reopened["current_exercise_id"])
	}
	again, err := resolver.ResolveSource(ctx, domain.CaptureSourceRef{Type: domain.SourceListeningItem, RecordID: exerciseID, Item: 4})
	if err != nil || again.ExplanationEN != saved.ExplanationEN || again.Prompt != saved.Prompt || again.Reference != saved.Reference {
		t.Fatalf("the saved item changed: %+v %v", again, err)
	}

	status, fresh, _ := postScript(t, srv, "ls-wb1-u06")
	if status != http.StatusCreated {
		t.Fatalf("import after the correction: %d", status)
	}
	freshItems := path(fresh, "exercises").([]any)[0].(map[string]any)["content"].(map[string]any)["items"].([]any)
	if got := freshItems[9].(map[string]any)["rationale_en"]; got != current.Scripts[5].Questions[9].RationaleEN {
		t.Fatalf("a new import did not get the corrected wording: %v", got)
	}
}
