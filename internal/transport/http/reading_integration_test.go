package http_test

// Exam Reading v1 end to end: the real handler, SQLite repository and OpenAI
// generator client against a local fake Responses API (listeningfake), with
// the embedded authored pack (internal/reading/pack) as content.

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening/listeningfake"
	"french-learning-app/internal/reading"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

const readingKey = "sk-reading-integration-secret"

type readingFixture struct {
	model  *listeningfake.Responses
	clock  *fakeClock
	srv    *httptest.Server
	db     *sql.DB
	routes http.Handler
	dbPath string
}

// packPassage returns one authored passage of the embedded pack.
func packPassage(t *testing.T, id string) domain.ReadingPackPassage {
	t.Helper()
	pack, err := domain.ParseReadingPack(reading.ExamplePack())
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range pack.Passages {
		if p.ID == id {
			return p
		}
	}
	t.Fatalf("no passage %s", id)
	return domain.ReadingPackPassage{}
}

// passageText joins the paragraphs as a learner would paste them.
func passageText(p domain.ReadingPackPassage) string {
	parts := make([]string, len(p.Segments))
	for i, s := range p.Segments {
		parts[i] = s.Text
	}
	return strings.Join(parts, "\n\n")
}

// modelOutput is what the fake model returns for the chaudière passage: the
// pack's items without IDs or wrong answers (a generated exercise has neither).
func modelOutput(t *testing.T, mutate func(items []map[string]any)) string {
	t.Helper()
	items := []map[string]any{}
	for _, q := range packPassage(t, "rd-email-chaudiere").Questions {
		items = append(items, map[string]any{"kind": q.Kind, "question": q.Question, "reference_answer": q.ReferenceAnswer,
			"accepted_alternatives": q.AcceptedAlternatives, "evidence": q.Evidence, "explanation_en": q.ExplanationEN, "explanation_zh": q.ExplanationZH})
	}
	if mutate != nil {
		mutate(items)
	}
	raw, _ := json.Marshal(map[string]any{"items": items})
	return string(raw)
}

func newReadingFixture(t *testing.T, withGenerator bool, dbPath string, model *listeningfake.Responses, timeout time.Duration) *readingFixture {
	t.Helper()
	if dbPath == "" {
		dbPath = filepath.Join(t.TempDir(), "reading.db")
	}
	if model == nil {
		model = listeningfake.NewResponses(t, readingKey, modelOutput(t, nil))
	}
	if timeout == 0 {
		timeout = 2 * time.Second
	}
	f := &readingFixture{model: model, clock: &fakeClock{t: time.Date(2026, 11, 9, 9, 0, 0, 0, time.UTC)}, dbPath: dbPath}
	db, err := sqlite.Open(dbPath)
	if err != nil {
		t.Fatal(err)
	}
	f.db = db
	var gen domain.ReadingExerciseGenerator
	if withGenerator {
		gen = reading.NewOpenAI(readingKey, "fake-model", model.URL(), timeout)
	}
	svc, err := application.NewReadingService(sqlite.NewReadingRepository(db), gen, reading.ExamplePack(),
		application.WithReadingClock(f.clock.now), application.WithReadingDeadline(timeout+30*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)
	annotation := application.NewEffectiveAnnotationService(conceptRepo, conceptRepo)
	handler := transporthttp.NewHandler(
		application.NewEntryService(entryRepo), application.NewAnalysisService(entryRepo, analysisRepo, nil),
		application.NewFeedbackService(feedbackRepo), application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo),
		application.NewInventoryService(sqlite.NewInventoryRepository(db)), application.NewCaptureService(sqlite.NewCaptureRepository(db)),
		application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, sqlite.NewAdmissionRepository(db), nil),
		application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo), annotation,
		application.NewConceptAnnotationDatasetService(annotation, knowledgeRepo, conceptRepo),
		transporthttp.WithReading(svc),
	)
	f.routes = handler.Routes()
	f.srv = httptest.NewServer(f.routes)
	t.Cleanup(func() { f.srv.Close(); db.Close() })
	return f
}

func (f *readingFixture) create(t *testing.T, title, text, link string) (int64, map[string]any) {
	t.Helper()
	body, _ := json.Marshal(map[string]string{"title": title, "text": text, "source_url": link})
	status, out := doJSON(t, http.MethodPost, f.srv.URL+"/reading/lessons", string(body))
	if status != http.StatusCreated {
		t.Fatalf("create: %d %v", status, out)
	}
	return int64(path(out, "lesson", "id").(float64)), out
}

func (f *readingFixture) prepare(t *testing.T, id int64, key, body string) (int, map[string]any) {
	t.Helper()
	status, out, _, err := keyed(t, http.DefaultClient, http.MethodPost, fmt.Sprintf("%s/reading/lessons/%d/exercises", f.srv.URL, id), key, body)
	if err != nil {
		t.Fatal(err)
	}
	return status, out
}

const (
	rkeyA = "a1111111-1111-4111-8111-111111111111"
	rkeyB = "a2222222-2222-4222-8222-222222222222"
	rkeyC = "a3333333-3333-4333-8333-333333333333"
	rkeyD = "a4444444-4444-4444-8444-444444444444"
)

func TestReading_CreateReopenAfterRestartKeepsWordingAndParagraphIDs(t *testing.T) {
	f := newReadingFixture(t, true, "", nil, 0)
	p := packPassage(t, "rd-article-jardins")
	id, created := f.create(t, "Article sur les jardins", passageText(p), "https://example.org/montclair/jardins")
	segs, _ := json.Marshal(path(created, "passage", "segments"))
	want, _ := json.Marshal(p.Segments)
	if string(segs) != string(want) || path(created, "lesson", "source_url") != "https://example.org/montclair/jardins" ||
		path(created, "lesson", "origin") != "learner" || created["state"] != "ready_to_prepare" {
		t.Fatalf("created = %v", created)
	}
	f.srv.Close()
	f.db.Close()
	again := newReadingFixture(t, true, f.dbPath, f.model, 0)
	_, reopened := doJSON(t, http.MethodGet, fmt.Sprintf("%s/reading/lessons/%d", again.srv.URL, id), "")
	segs2, _ := json.Marshal(path(reopened, "passage", "segments"))
	if string(segs2) != string(want) || path(reopened, "passage", "version") != 1.0 {
		t.Fatalf("after restart: %v", reopened)
	}
	if f.model.Calls() != 0 {
		t.Fatalf("saving and reading made %d model calls", f.model.Calls())
	}
}

func TestReading_AuthoredExampleImportsWithoutAModelCall(t *testing.T) {
	f := newReadingFixture(t, true, "", nil, 0)
	_, list := doJSON(t, http.MethodGet, f.srv.URL+"/reading/examples", "")
	ex := list["examples"].([]any)
	if len(ex) != 6 || list["pack"] != "flh_reading_pack_v1" || !strings.Contains(list["notice"].(string), "not an official exam") {
		t.Fatalf("examples = %v", list)
	}
	status, lesson := doJSON(t, http.MethodPost, f.srv.URL+"/reading/examples/rd-email-chaudiere", "")
	exercise := lesson["exercises"].([]any)[0].(map[string]any)
	items := path(exercise, "content", "items").([]any)
	inference := items[2].(map[string]any)
	if status != http.StatusCreated || lesson["state"] != "prepared" || path(lesson, "lesson", "origin") != "authored" ||
		exercise["generator"] != "authored:flh_reading_pack_v1" || inference["kind"] != "inference" || len(inference["wrong_answers"].([]any)) != 1 {
		t.Fatalf("import: %d %v", status, lesson)
	}
	status, again := doJSON(t, http.MethodPost, f.srv.URL+"/reading/examples/rd-email-chaudiere", "")
	if status != http.StatusOK || path(again, "lesson", "id") != path(lesson, "lesson", "id") || countRows(t, f.db, "reading_lessons") != 1 {
		t.Fatalf("re-import: %d %v", status, again)
	}
	if status, _ := doJSON(t, http.MethodPost, f.srv.URL+"/reading/examples/rd-unknown", ""); status != http.StatusNotFound {
		t.Fatalf("unknown example: %d", status)
	}
	// An authored example's text cannot be replaced.
	if status, _ := doJSON(t, http.MethodPost, fmt.Sprintf("%s/reading/lessons/%v/passages", f.srv.URL, path(lesson, "lesson", "id")), `{"text":"Autre texte."}`); status != http.StatusUnprocessableEntity {
		t.Fatalf("authored passage change: %d", status)
	}
	if f.model.Calls() != 0 {
		t.Fatalf("importing made %d model calls", f.model.Calls())
	}
}

func TestReading_GeneratedExerciseIsValidatedAndTiedToItsPassageVersion(t *testing.T) {
	f := newReadingFixture(t, true, "", nil, 0)
	p := packPassage(t, "rd-email-chaudiere")
	id, created := f.create(t, "Mon courriel", passageText(p), "")
	v1 := path(created, "passage", "id")
	status, res := f.prepare(t, id, rkeyA, "")
	if status != http.StatusCreated || path(res, "preparation", "state") != "completed" || path(res, "exercise", "passage_id") != v1 || f.model.Calls() != 1 {
		t.Fatalf("prepare: %d %v", status, res)
	}
	_, lesson := doJSON(t, http.MethodGet, fmt.Sprintf("%s/reading/lessons/%d", f.srv.URL, id), "")
	items := path(lesson["exercises"].([]any)[0], "content", "items").([]any)
	if lesson["state"] != "prepared" || len(items) != 3 || items[2].(map[string]any)["kind"] != "inference" ||
		path(items[2], "evidence") == nil || f.model.Calls() != 1 {
		t.Fatalf("lesson = %v", lesson)
	}
	// A new version gets its own exercise; the first stays tied to version 1.
	if status, _ := doJSON(t, http.MethodPost, fmt.Sprintf("%s/reading/lessons/%d/passages", f.srv.URL, id), fmt.Sprintf(`{"text":%q}`, passageText(p)+"\n\nPS : merci beaucoup !")); status != http.StatusCreated {
		t.Fatalf("new version: %d", status)
	}
	_, v2lesson := doJSON(t, http.MethodGet, fmt.Sprintf("%s/reading/lessons/%d", f.srv.URL, id), "")
	if v2lesson["state"] != "ready_to_prepare" || path(v2lesson, "passage", "version") != 2.0 || v2lesson["versions"] != 2.0 {
		t.Fatalf("after a new version: %v", v2lesson)
	}
	status, res = f.prepare(t, id, rkeyB, "")
	if status != http.StatusCreated || path(res, "exercise", "passage_id") == v1 {
		t.Fatalf("second prepare: %d %v", status, res)
	}
	_, final := doJSON(t, http.MethodGet, fmt.Sprintf("%s/reading/lessons/%d", f.srv.URL, id), "")
	exs := final["exercises"].([]any)
	if len(exs) != 2 || path(exs[1], "passage_id") != v1 {
		t.Fatalf("exercises = %v", exs)
	}
}

func TestReading_InvalidCitationsAndProviderFailurePreserveThePassage(t *testing.T) {
	f := newReadingFixture(t, true, "", nil, 0)
	p := packPassage(t, "rd-email-chaudiere")
	id, created := f.create(t, "Mon courriel", passageText(p), "")
	original, _ := json.Marshal(created["passage"])
	setEvidence := func(item int, seg, excerpt string) func(items []map[string]any) {
		return func(items []map[string]any) {
			items[item]["evidence"] = []map[string]string{{"segment": seg, "excerpt": excerpt}}
		}
	}
	cases := []struct {
		name   string
		output string
		mode   string
		status int
		code   string
	}{
		{"wrong paragraph", modelOutput(t, setEvidence(1, "p2", "merci de me prévenir avant jeudi soir")), listeningfake.ModeOK, 502, "invalid_output"},
		{"invented excerpt", modelOutput(t, setEvidence(0, "p1", "le technicien viendra lundi")), listeningfake.ModeOK, 502, "invalid_output"},
		{"ambiguous excerpt", modelOutput(t, setEvidence(0, "p1", "de ")), listeningfake.ModeOK, 502, "invalid_output"},
		{"provider failure", modelOutput(t, nil), listeningfake.ModeStatus, 502, "provider_unavailable"},
	}
	for i, c := range cases {
		f.model.SetOutput(c.output)
		f.model.Set(c.mode, http.StatusInternalServerError, 0)
		status, out := f.prepare(t, id, "", "")
		if status != c.status || path(out, "exercise", "status") != "failed" || path(out, "exercise", "failure_code") != c.code ||
			path(out, "preparation", "state") != "failed" || f.model.Calls() != i+1 {
			t.Fatalf("%s: %d %v", c.name, status, out)
		}
		if msg, _ := out["error"].(string); strings.Contains(msg, readingKey) || strings.Contains(msg, "chaudière") {
			t.Fatalf("%s: error leaks: %s", c.name, msg)
		}
	}
	_, after := doJSON(t, http.MethodGet, fmt.Sprintf("%s/reading/lessons/%d", f.srv.URL, id), "")
	now, _ := json.Marshal(after["passage"])
	if string(now) != string(original) || after["state"] != "failed" || len(after["exercises"].([]any)) != 4 {
		t.Fatalf("source changed or failures lost:\n%s\n%s\n%v", original, now, after["state"])
	}
	f.model.SetOutput(modelOutput(t, nil))
	f.model.Set(listeningfake.ModeOK, 0, 0)
	if status, _ := f.prepare(t, id, "", ""); status != http.StatusCreated {
		t.Fatalf("next explicit request: %d", status)
	}
}

func TestReading_UnknownOutcomesAndLostResponsesNeverCallTwiceSilently(t *testing.T) {
	f := newReadingFixture(t, true, "", nil, 300*time.Millisecond)
	id, _ := f.create(t, "Mon courriel", passageText(packPassage(t, "rd-email-chaudiere")), "")
	f.model.Set(listeningfake.ModeDrop, 0, 0)
	status, out := f.prepare(t, id, rkeyA, "")
	if status != http.StatusBadGateway || path(out, "preparation", "state") != "unknown" || !strings.Contains(out["error"].(string), "outcome is unknown") {
		t.Fatalf("dropped: %d %v", status, out)
	}
	f.model.Set(listeningfake.ModeOK, 0, 0)
	if status, out = f.prepare(t, id, rkeyB, ""); status != http.StatusConflict || out["code"] != "outcome_unknown" || f.model.Calls() != 1 {
		t.Fatalf("unacknowledged: %d %v", status, out)
	}
	if status, out = f.prepare(t, id, rkeyB, `{"confirm_unknown_retry":true}`); status != http.StatusCreated || path(out, "preparation", "after_unknown") != true || f.model.Calls() != 2 {
		t.Fatalf("acknowledged: %d %v", status, out)
	}
	// A lost response: the client gives up, the call finishes and is found by key.
	id2, _ := f.create(t, "Autre", passageText(packPassage(t, "rd-email-chaudiere")), "")
	f.model.Set(listeningfake.ModeHang, 0, 150*time.Millisecond)
	impatient := &http.Client{Timeout: 50 * time.Millisecond}
	if _, _, _, err := keyed(t, impatient, http.MethodPost, fmt.Sprintf("%s/reading/lessons/%d/exercises", f.srv.URL, id2), rkeyC, ""); err == nil {
		t.Fatal("expected the client to give up")
	}
	var state any
	for i := 0; i < 50 && state != "completed"; i++ {
		_, got := doJSON(t, http.MethodGet, f.srv.URL+"/reading/preparations/"+rkeyC, "")
		state = path(got, "preparation", "state")
		time.Sleep(20 * time.Millisecond)
	}
	status, out, hdr, _ := keyed(t, http.DefaultClient, http.MethodPost, fmt.Sprintf("%s/reading/lessons/%d/exercises", f.srv.URL, id2), rkeyC, "")
	if state != "completed" || status != http.StatusOK || hdr.Get("Idempotency-Replayed") != "true" || f.model.Calls() != 3 {
		t.Fatalf("lost response: %v, resend %d %v (calls %d)", state, status, out, f.model.Calls())
	}
	if status, _ := doJSON(t, http.MethodGet, f.srv.URL+"/reading/preparations/"+rkeyD, ""); status != http.StatusNotFound {
		t.Fatalf("unknown key: %d", status)
	}
}

func TestReading_ReadingAnsweringAndRevealingCallNothingAndAMissedPointIsTraceable(t *testing.T) {
	f := newReadingFixture(t, true, "", nil, 0)
	_, lesson := doJSON(t, http.MethodPost, f.srv.URL+"/reading/examples/rd-annonce-babysitter", "")
	id := path(lesson, "lesson", "id")
	for i := 0; i < 3; i++ {
		doJSON(t, http.MethodGet, fmt.Sprintf("%s/reading/lessons/%v", f.srv.URL, id), "")
		doJSON(t, http.MethodGet, f.srv.URL+"/reading/lessons", "")
	}
	if f.model.Calls() != 0 {
		t.Fatalf("reading made %d model calls", f.model.Calls())
	}
	doc := map[string]string{"schema_version": "learning_capture_v1", "capture_id": "reading-1-1-q3-test", "source": "manual",
		"original_input":   "J'ai compris « à la rentrée » comme « quand ils rentrent ».",
		"original_context": "Reading lesson: Petite annonce\nParagraph p3: « À la rentrée, ils commencent l'école en français »"}
	raw, _ := json.Marshal(doc)
	status, receipt := doJSON(t, http.MethodPost, f.srv.URL+"/captures", string(raw))
	entry := receipt["entry_id"]
	_, got := doJSON(t, http.MethodGet, fmt.Sprintf("%s/entries/%v", f.srv.URL, entry), "")
	if status != http.StatusCreated || !strings.Contains(got["original_context"].(string), "p3") || countRows(t, f.db, "knowledge_concepts") != 0 ||
		countRows(t, f.db, "reading_exercises") != 1 {
		t.Fatalf("capture: %d %v %v", status, receipt, got)
	}
}

func TestReading_DisabledProviderAndPublicDemo(t *testing.T) {
	f := newReadingFixture(t, false, "", nil, 0)
	id, _ := f.create(t, "Texte", "Un paragraphe.\n\nUn autre.", "")
	if status, _ := f.prepare(t, id, "", ""); status != http.StatusServiceUnavailable || countRows(t, f.db, "reading_preparations") != 0 {
		t.Fatalf("disabled: %d", status)
	}
	if status, _ := doJSON(t, http.MethodPost, f.srv.URL+"/reading/examples/rd-notice-piscine", ""); status != http.StatusCreated {
		t.Fatalf("examples work without a provider: %d", status)
	}
	demo := httptest.NewServer(transporthttp.NewPublicDemoBoundary(f.routes, false))
	t.Cleanup(demo.Close)
	for _, prefix := range []string{"", "/api"} {
		for _, p := range []string{"/reading/lessons", "/reading/lessons/1", "/reading/examples", "/reading/preparations/" + rkeyA} {
			if status, _ := doJSON(t, http.MethodGet, demo.URL+prefix+p, ""); status != http.StatusNotFound {
				t.Errorf("GET %s%s in the demo: %d", prefix, p, status)
			}
		}
		for _, p := range []string{"/reading/lessons", "/reading/lessons/1/exercises", "/reading/lessons/1/passages", "/reading/examples/rd-notice-piscine"} {
			if status, _ := doJSON(t, http.MethodPost, demo.URL+prefix+p, "{}"); status != http.StatusMethodNotAllowed {
				t.Errorf("POST %s%s in the demo: %d", prefix, p, status)
			}
		}
	}
}

func TestReading_InputValidation(t *testing.T) {
	f := newReadingFixture(t, true, "", nil, 0)
	for name, body := range map[string]string{
		"no title":       `{"title":" ","text":"Bonjour."}`,
		"empty text":     `{"title":"t","text":"  "}`,
		"http link":      `{"title":"t","text":"Bonjour.","source_url":"http://example.org"}`,
		"long paragraph": fmt.Sprintf(`{"title":"t","text":%q}`, strings.Repeat("é", domain.MaxReadingParagraphRunes+1)),
	} {
		if status, out := doJSON(t, http.MethodPost, f.srv.URL+"/reading/lessons", body); status != http.StatusUnprocessableEntity {
			t.Errorf("%s: %d %v", name, status, out)
		}
	}
	if status, _ := doJSON(t, http.MethodPost, f.srv.URL+"/reading/lessons", `{"title":"t","text":"x","fetch":true}`); status != http.StatusBadRequest {
		t.Errorf("unknown field: %d", status)
	}
	if countRows(t, f.db, "reading_lessons") != 0 {
		t.Fatal("refused input was stored")
	}
}
