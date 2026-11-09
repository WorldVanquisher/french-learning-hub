package http_test

// Exam Listening Lesson v1 end to end: the real handler and SQLite repository,
// the real OpenAI generator client, and a local fake Responses API. The French
// transcript is the authored example in examples/listening.

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

const listeningKey = "sk-listening-integration-secret"

// The exercise the fake provider returns for the authored transcript.
const listeningExercise = `{"items":[
 {"kind":"main_idea","question":"Quel est le sujet principal de cette chronique ?","expected_answer":"L'ouverture d'une nouvelle bibliothèque dans le quartier, samedi.","rationale_en":"Segment 2 announces the opening.","rationale_zh":"第2段宣布了开馆。","segments":[2]},
 {"kind":"detail","question":"Que faut-il apporter pour s'inscrire ?","expected_answer":"Un justificatif de domicile.","rationale_en":"Segment 4 states the condition.","rationale_zh":"第4段说明了条件。","segments":[4]},
 {"kind":"inference","question":"Quelle est l'attitude du chroniqueur ?","expected_answer":"Il est enthousiaste et encourage les auditeurs à venir.","rationale_en":"« Une excellente nouvelle » and « n'hésitez pas » show it.","rationale_zh":"« une excellente nouvelle » 和 « n'hésitez pas » 表明了这一点。","segments":[6,7]}],
 "annotations":[
 {"kind":"vocabulary","segment":4,"excerpt":"justificatif de domicile","note_en":"proof of address","note_zh":"住址证明"},
 {"kind":"grammar","segment":7,"excerpt":"n'hésitez pas à","note_en":"imperative + à + infinitive: don't hesitate to","note_zh":"命令式 + à + 不定式：不要犹豫……"}]}`

// fakeResponses is a local stand-in for the OpenAI Responses API.
type fakeResponses struct {
	mu     sync.Mutex
	calls  int
	status int
	output string
}

func (f *fakeResponses) set(status int, output string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.status, f.output = status, output
}

func (f *fakeResponses) count() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.calls
}

func (f *fakeResponses) handler(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	f.calls++
	status, output := f.status, f.output
	f.mu.Unlock()
	_, _ = io.Copy(io.Discard, r.Body)
	if r.Header.Get("Authorization") != "Bearer "+listeningKey {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	w.WriteHeader(status)
	body, _ := json.Marshal(map[string]any{"status": "completed", "output": []any{map[string]any{
		"type": "message", "content": []any{map[string]any{"type": "output_text", "text": output}}}}})
	_, _ = w.Write(body)
}

func authoredTranscript(t *testing.T) string {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "examples", "listening", "synthetic-lesson.fr.txt"))
	if err != nil {
		t.Fatal(err)
	}
	return string(raw)
}

// buildListeningServer serves the full API over dbPath. generator may be nil
// (LISTENING_PROVIDER=disabled).
func buildListeningServer(t *testing.T, dbPath string, generator domain.ListeningExerciseGenerator) (*httptest.Server, *sql.DB, *transporthttp.Handler) {
	t.Helper()
	db, err := sqlite.Open(dbPath)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)
	conceptSvc := application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo)
	effectiveAnnotationSvc := application.NewEffectiveAnnotationService(conceptRepo, conceptRepo)
	datasetSvc := application.NewConceptAnnotationDatasetService(effectiveAnnotationSvc, knowledgeRepo, conceptRepo)
	handler := transporthttp.NewHandler(
		application.NewEntryService(entryRepo), application.NewAnalysisService(entryRepo, analysisRepo, nil),
		application.NewFeedbackService(feedbackRepo), application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo),
		application.NewInventoryService(sqlite.NewInventoryRepository(db)), application.NewCaptureService(sqlite.NewCaptureRepository(db)),
		application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, sqlite.NewAdmissionRepository(db), nil),
		conceptSvc, effectiveAnnotationSvc, datasetSvc,
		transporthttp.WithListening(application.NewListeningService(sqlite.NewListeningRepository(db), generator)),
	)
	srv := httptest.NewServer(handler.Routes())
	t.Cleanup(func() { srv.Close(); db.Close() })
	return srv, db, handler
}

func newListeningFixture(t *testing.T) (*fakeResponses, string, *httptest.Server, *sql.DB) {
	t.Helper()
	fake := &fakeResponses{status: http.StatusOK, output: listeningExercise}
	provider := httptest.NewServer(http.HandlerFunc(fake.handler))
	t.Cleanup(provider.Close)
	dbPath := filepath.Join(t.TempDir(), "listening.db")
	gen := listening.NewOpenAI(listeningKey, "fake-model", provider.URL, 5*time.Second)
	srv, db, _ := buildListeningServer(t, dbPath, gen)
	return fake, dbPath, srv, db
}

func createLesson(t *testing.T, srv *httptest.Server, transcript string) int64 {
	t.Helper()
	body, _ := json.Marshal(map[string]string{"source_url": "https://youtu.be/FLHlisten01", "title": "La minute du quartier", "transcript": transcript})
	status, out := doJSON(t, http.MethodPost, srv.URL+"/listening/materials", string(body))
	if status != http.StatusCreated {
		t.Fatalf("create material: %d %v", status, out)
	}
	return int64(path(out, "material", "id").(float64))
}

func countRows(t *testing.T, db *sql.DB, table string) int {
	t.Helper()
	var n int
	if err := db.QueryRow(`SELECT COUNT(*) FROM ` + table).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}

func TestListeningLesson_PrepareReopenAndSaveMissedPoint(t *testing.T) {
	fake, dbPath, srv, db := newListeningFixture(t)
	id := createLesson(t, srv, authoredTranscript(t))

	// Browsing calls no provider.
	for _, p := range []string{"/listening/materials", fmt.Sprintf("/listening/materials/%d", id)} {
		if status, out := doJSON(t, http.MethodGet, srv.URL+p, ""); status != http.StatusOK {
			t.Fatalf("GET %s: %d %v", p, status, out)
		}
	}
	status, lesson := doJSON(t, http.MethodGet, fmt.Sprintf("%s/listening/materials/%d", srv.URL, id), "")
	if status != http.StatusOK || path(lesson, "material", "source_url") != "https://www.youtube.com/watch?v=FLHlisten01" ||
		path(lesson, "transcript", "has_timestamps") != true || len(path(lesson, "transcript", "segments").([]any)) != 8 ||
		path(lesson, "generation", "enabled") != true {
		t.Fatalf("lesson = %v", lesson)
	}
	if fake.count() != 0 {
		t.Fatalf("browsing made %d provider calls", fake.count())
	}

	// One explicit preparation, one call.
	status, res := doJSON(t, http.MethodPost, fmt.Sprintf("%s/listening/materials/%d/exercises", srv.URL, id), "")
	ex, _ := res["exercise"].(map[string]any)
	if status != http.StatusCreated || ex["status"] != "completed" || ex["generator"] != "openai:fake-model:listening_exercise_v1" ||
		path(res, "preparation", "state") != "completed" || path(res, "preparation", "trigger") != "explicit" || fake.count() != 1 {
		t.Fatalf("prepare: %d %v (calls %d)", status, res, fake.count())
	}
	// The list carries the status, never the answers.
	_, list := doJSON(t, http.MethodGet, srv.URL+"/listening/materials", "")
	row := list["materials"].([]any)[0].(map[string]any)
	if path(row, "latest_exercise", "status") != "completed" || path(row, "latest_exercise", "content") != nil || row["segment_count"] != float64(8) {
		t.Fatalf("list row = %v", row)
	}

	// Reload: a new server process over the same database file sees the lesson.
	srv.Close()
	db.Close()
	srv2, db2, _ := buildListeningServer(t, dbPath, nil)
	_, again := doJSON(t, http.MethodGet, fmt.Sprintf("%s/listening/materials/%d", srv2.URL, id), "")
	exercises := again["exercises"].([]any)
	if len(exercises) != 1 || path(exercises[0], "content", "items") == nil || path(again, "generation", "enabled") != false {
		t.Fatalf("after reload: %v", again)
	}
	first := path(exercises[0], "content", "items").([]any)[0].(map[string]any)
	if first["kind"] != "main_idea" || first["expected_answer"] != "L'ouverture d'une nouvelle bibliothèque dans le quartier, samedi." {
		t.Fatalf("reloaded item = %v", first)
	}

	// A missed point becomes a normal learning record through the unchanged
	// capture path (the workbench sends this only after explicit confirmation).
	before := map[string]int{}
	for _, table := range []string{"knowledge_concepts", "unit_concept_links", "unit_concept_memberships", "knowledge_extractions", "entry_analyses", "listening_exercises"} {
		before[table] = countRows(t, db2, table)
	}
	capture, _ := json.Marshal(map[string]any{
		"schema_version": "learning_capture_v1", "capture_id": "listening-1-1-3f2a9c", "source": "manual",
		"original_input": "J'ai compris « justificatif d'identité » au lieu de « justificatif de domicile ».",
		"original_context": "Listening: La minute du quartier\nVideo: https://www.youtube.com/watch?v=FLHlisten01&t=16s\n" +
			"Question: Que faut-il apporter pour s'inscrire ?\nExcerpt (segment 4, 0:16): « L'inscription est gratuite pour les habitants du quartier ; il suffit d'apporter un justificatif de domicile. »",
	})
	status, receipt := doJSON(t, http.MethodPost, srv2.URL+"/captures", string(capture))
	if status != http.StatusCreated {
		t.Fatalf("capture: %d %v", status, receipt)
	}
	entryID := receipt["entry_id"].(float64)
	if receipt["analysis_id"] != nil || receipt["created"] != true {
		t.Fatalf("receipt = %v", receipt)
	}
	status, traced := doJSON(t, http.MethodGet, srv2.URL+"/captures/listening-1-1-3f2a9c", "")
	if status != http.StatusOK || traced["entry_id"] != entryID || traced["source"] != "manual" {
		t.Fatalf("trace: %d %v", status, traced)
	}
	status, entry := doJSON(t, http.MethodGet, fmt.Sprintf("%s/entries/%d", srv2.URL, int64(entryID)), "")
	if status != http.StatusOK || !strings.Contains(fmt.Sprint(entry["original_context"]), "https://www.youtube.com/watch?v=FLHlisten01&t=16s") ||
		!strings.Contains(fmt.Sprint(entry["original_input"]), "justificatif de domicile") {
		t.Fatalf("entry: %d %v", status, entry)
	}
	for table, n := range before {
		if got := countRows(t, db2, table); got != n {
			t.Fatalf("%s changed from %d to %d", table, n, got)
		}
	}
	if fake.count() != 1 {
		t.Fatalf("provider calls = %d, want exactly the one preparation", fake.count())
	}
}

func TestListeningLesson_LinkWithoutTranscriptNeverProducesALesson(t *testing.T) {
	fake, _, srv, db := newListeningFixture(t)
	id := createLesson(t, srv, "   ")
	_, lesson := doJSON(t, http.MethodGet, fmt.Sprintf("%s/listening/materials/%d", srv.URL, id), "")
	if lesson["transcript"] != nil {
		t.Fatalf("transcript = %v", lesson["transcript"])
	}
	status, out := doJSON(t, http.MethodPost, fmt.Sprintf("%s/listening/materials/%d/exercises", srv.URL, id), "")
	if status != http.StatusConflict || fake.count() != 0 || countRows(t, db, "listening_exercises") != 0 {
		t.Fatalf("prepare without transcript: %d %v (calls %d)", status, out, fake.count())
	}
	// Adding the transcript later makes it a normal, preparable lesson.
	body, _ := json.Marshal(map[string]string{"transcript": authoredTranscript(t)})
	status, out = doJSON(t, http.MethodPost, fmt.Sprintf("%s/listening/materials/%d/transcripts", srv.URL, id), string(body))
	if status != http.StatusCreated || path(out, "transcript", "version") != float64(1) || fake.count() != 0 {
		t.Fatalf("add transcript: %d %v", status, out)
	}
}

func TestListeningLesson_FailuresAreStoredAndPreserveTheSource(t *testing.T) {
	fake, _, srv, db := newListeningFixture(t)
	transcript := authoredTranscript(t)
	id := createLesson(t, srv, transcript)
	_, original := doJSON(t, http.MethodGet, fmt.Sprintf("%s/listening/materials/%d", srv.URL, id), "")
	cases := []struct {
		name   string
		status int
		output string
		code   string
	}{
		{"reference outside the transcript", http.StatusOK, strings.Replace(listeningExercise, `"segments":[4]}`, `"segments":[12]}`, 1), "invalid_output"},
		{"fabricated timestamp", http.StatusOK, strings.Replace(listeningExercise, "Segment 4 states the condition.", "Said at 0:16.", 1), "invalid_output"},
		{"fabricated excerpt", http.StatusOK, strings.Replace(listeningExercise, `"excerpt":"justificatif de domicile"`, `"excerpt":"pièce d'identité"`, 1), "invalid_output"},
		{"provider failure", http.StatusInternalServerError, listeningExercise, "provider_unavailable"},
	}
	for i, c := range cases {
		fake.set(c.status, c.output)
		status, out := doJSON(t, http.MethodPost, fmt.Sprintf("%s/listening/materials/%d/exercises", srv.URL, id), "")
		if status != http.StatusBadGateway || path(out, "exercise", "status") != "failed" || path(out, "exercise", "failure_code") != c.code ||
			path(out, "exercise", "content") != nil || fake.count() != i+1 {
			t.Fatalf("%s: %d %v", c.name, status, out)
		}
		if msg, _ := out["error"].(string); strings.Contains(msg, listeningKey) || strings.Contains(msg, "bibliothèque") {
			t.Fatalf("%s: error leaks: %s", c.name, msg)
		}
	}
	// The material and transcript are exactly as saved; every attempt is kept.
	_, after := doJSON(t, http.MethodGet, fmt.Sprintf("%s/listening/materials/%d", srv.URL, id), "")
	a, _ := json.Marshal(after["transcript"])
	o, _ := json.Marshal(original["transcript"])
	if string(a) != string(o) || path(after, "material", "title") != "La minute du quartier" {
		t.Fatalf("source changed:\n%s\n%s", a, o)
	}
	if exs := after["exercises"].([]any); len(exs) != 4 || countRows(t, db, "listening_transcripts") != 1 {
		t.Fatalf("exercises = %v", exs)
	}
	// The next explicit request may succeed; failures stay in the history.
	fake.set(http.StatusOK, listeningExercise)
	status, ex := doJSON(t, http.MethodPost, fmt.Sprintf("%s/listening/materials/%d/exercises", srv.URL, id), "")
	if status != http.StatusCreated || path(ex, "exercise", "status") != "completed" {
		t.Fatalf("retry by request: %d %v", status, ex)
	}
}

func TestListeningLesson_DisabledProviderStoresNothing(t *testing.T) {
	srv, db, _ := buildListeningServer(t, filepath.Join(t.TempDir(), "off.db"), nil)
	id := createLesson(t, srv, authoredTranscript(t))
	status, out := doJSON(t, http.MethodPost, fmt.Sprintf("%s/listening/materials/%d/exercises", srv.URL, id), "")
	if status != http.StatusServiceUnavailable || countRows(t, db, "listening_exercises") != 0 {
		t.Fatalf("disabled: %d %v", status, out)
	}
	_, lesson := doJSON(t, http.MethodGet, fmt.Sprintf("%s/listening/materials/%d", srv.URL, id), "")
	if path(lesson, "generation", "enabled") != false || path(lesson, "generation", "generator") != nil || lesson["transcript"] == nil {
		t.Fatalf("lesson = %v", lesson)
	}
}

func TestListeningLesson_InputValidation(t *testing.T) {
	_, _, srv, db := newListeningFixture(t)
	for name, body := range map[string]string{
		"not youtube":          `{"source_url":"https://example.com/watch?v=FLHlisten01","title":"x"}`,
		"playlist":             `{"source_url":"https://www.youtube.com/playlist?list=PLabc","title":"x"}`,
		"no title":             `{"source_url":"https://youtu.be/FLHlisten01","title":"  "}`,
		"mixed timestamps":     `{"source_url":"https://youtu.be/FLHlisten01","title":"x","transcript":"[00:01] Un.\nDeux."}`,
		"oversized segment":    fmt.Sprintf(`{"source_url":"https://youtu.be/FLHlisten01","title":"x","transcript":%q}`, strings.Repeat("é", domain.MaxSegmentRunes+1)),
		"oversized transcript": fmt.Sprintf(`{"source_url":"https://youtu.be/FLHlisten01","title":"x","transcript":%q}`, strings.Repeat("Bonjour.\n", 1400)),
	} {
		status, out := doJSON(t, http.MethodPost, srv.URL+"/listening/materials", body)
		if status != http.StatusUnprocessableEntity {
			t.Errorf("%s: %d %v", name, status, out)
		}
		if msg, _ := out["error"].(string); strings.Contains(msg, "example.com") || strings.Contains(msg, "Bonjour") {
			t.Errorf("%s echoes input: %s", name, msg)
		}
	}
	if status, _ := doJSON(t, http.MethodPost, srv.URL+"/listening/materials", `{"source_url":"https://youtu.be/FLHlisten01","title":"x","fetch":true}`); status != http.StatusBadRequest {
		t.Errorf("unknown field: %d", status)
	}
	if status, _ := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/999", ""); status != http.StatusNotFound {
		t.Errorf("unknown material: %d", status)
	}
	if n := countRows(t, db, "listening_materials"); n != 0 {
		t.Fatalf("refused input stored %d materials", n)
	}
}

func TestListeningLesson_UnavailableInThePublicDemo(t *testing.T) {
	_, _, handler := buildListeningServer(t, filepath.Join(t.TempDir(), "demo.db"), nil)
	demo := httptest.NewServer(transporthttp.NewPublicDemoBoundary(handler.Routes(), false))
	t.Cleanup(demo.Close)
	for _, prefix := range []string{"", "/api"} {
		for _, p := range []string{"/listening/materials", "/listening/materials/1"} {
			if status, _ := doJSON(t, http.MethodGet, demo.URL+prefix+p, ""); status != http.StatusNotFound {
				t.Errorf("GET %s%s in the demo: %d", prefix, p, status)
			}
		}
		for _, p := range []string{"/listening/materials", "/listening/materials/1/exercises", "/listening/materials/1/transcripts"} {
			if status, _ := doJSON(t, http.MethodPost, demo.URL+prefix+p, "{}"); status != http.StatusMethodNotAllowed {
				t.Errorf("POST %s%s in the demo: %d", prefix, p, status)
			}
		}
	}
}
