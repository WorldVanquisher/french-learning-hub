package http_test

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/exam"
	"french-learning-app/internal/reading"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

// Mock Exam v1 over real SQLite and the real handler, with a controllable
// server clock.

type examClock struct {
	mu  sync.Mutex
	now time.Time
}

func (c *examClock) Now() time.Time { c.mu.Lock(); defer c.mu.Unlock(); return c.now }
func (c *examClock) Add(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.now = c.now.Add(d)
}

type examFixture struct {
	srv    *httptest.Server
	routes http.Handler
	db     *sql.DB
	clock  *examClock
}

func newExamFixture(t *testing.T) *examFixture {
	t.Helper()
	db, err := sqlite.Open(filepath.Join(t.TempDir(), "exam.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	clock := &examClock{now: time.Date(2026, 11, 10, 9, 0, 0, 0, time.UTC)}
	examSvc, err := application.NewExamService(sqlite.NewExamRepository(db), exam.Forms(), reading.ExamplePack(), application.WithExamClock(clock.Now))
	if err != nil {
		t.Fatal(err)
	}
	readingSvc, err := application.NewReadingService(sqlite.NewReadingRepository(db), nil, reading.ExamplePack())
	if err != nil {
		t.Fatal(err)
	}
	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)
	annotation := application.NewEffectiveAnnotationService(conceptRepo, conceptRepo)
	resolver := application.NewMistakeSourceResolver(sqlite.NewListeningRepository(db), sqlite.NewReadingRepository(db), sqlite.NewWritingRepository(db), sqlite.NewSpeakingRepository(db))
	library := application.NewKnowledgeLibraryService(conceptRepo, knowledgeRepo, entryRepo, analysisRepo, feedbackRepo, annotation)
	handler := transporthttp.NewHandler(
		application.NewEntryService(entryRepo), application.NewAnalysisService(entryRepo, analysisRepo, nil),
		application.NewFeedbackService(feedbackRepo), application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo),
		application.NewInventoryService(sqlite.NewInventoryRepository(db)),
		application.NewCaptureService(sqlite.NewCaptureRepository(db), application.WithSourceResolver(resolver)),
		application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, sqlite.NewAdmissionRepository(db), nil),
		application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo), annotation,
		application.NewConceptAnnotationDatasetService(annotation, knowledgeRepo, conceptRepo),
		transporthttp.WithExam(examSvc), transporthttp.WithReading(readingSvc),
		transporthttp.WithMistakeNotebook(application.NewMistakeNotebookService(sqlite.NewNotebookRepository(db), resolver, entryRepo, library)),
	)
	f := &examFixture{routes: handler.Routes(), db: db, clock: clock}
	f.srv = httptest.NewServer(f.routes)
	t.Cleanup(f.srv.Close)
	return f
}

const examKeyA = "6f1d2c3b-0000-4000-8000-0000000000a1"

func (f *examFixture) start(t *testing.T, form, key string) (int, map[string]any) {
	t.Helper()
	status, out, _, err := keyed(t, http.DefaultClient, http.MethodPost, f.srv.URL+"/exam/sessions", key, `{"form_id":"`+form+`"}`)
	if err != nil {
		t.Fatal(err)
	}
	return status, out
}

func (f *examFixture) put(t *testing.T, id string, position, choice string) (int, map[string]any) {
	t.Helper()
	return doJSON(t, http.MethodPut, f.srv.URL+"/exam/sessions/"+id+"/answers/"+position, `{"choice":`+choice+`}`)
}

func sid(out map[string]any) string {
	return itoa(int64(out["session"].(map[string]any)["id"].(float64)))
}

// keyOf reads the authored key of a position from the stored frozen item (the
// test's view of the answer key, never from an in-progress response).
func (f *examFixture) keyOf(t *testing.T, session string, position int) int {
	t.Helper()
	var raw string
	if err := f.db.QueryRow(`SELECT content_json FROM exam_session_items WHERE session_id = ? AND position = ?`, session, position).Scan(&raw); err != nil {
		t.Fatal(err)
	}
	var it domain.ExamItem
	if err := json.Unmarshal([]byte(raw), &it); err != nil {
		t.Fatal(err)
	}
	return it.Key
}

func TestExam_StartFreezesAuthoredQuestionsAndHidesEveryKey(t *testing.T) {
	f := newExamFixture(t)
	status, forms := doJSON(t, http.MethodGet, f.srv.URL+"/exam/forms", "")
	if status != http.StatusOK || len(forms["forms"].([]any)) != 2 || !strings.Contains(forms["notice"].(string), "not an official exam") {
		t.Fatalf("forms = %d %v", status, forms)
	}
	status, out := f.start(t, "ce-examen-blanc-1", examKeyA)
	if status != http.StatusCreated || out["state"] != "in_progress" || out["remaining_seconds"] != float64(1200) {
		t.Fatalf("start = %d %v", status, out)
	}
	if len(out["questions"].([]any)) != 9 || len(out["passages"].([]any)) != 3 || out["result"] != nil {
		t.Fatalf("assembly = %v", out)
	}
	raw, _ := json.Marshal(out)
	body := string(raw)
	for _, leak := range []string{`"key"`, "explanation", "why_wrong", "evidence", "The notice gives a reopening date", "The first paragraph states"} {
		if strings.Contains(body, leak) {
			t.Errorf("an in-progress view contains %q", leak)
		}
	}
	// Frozen copies with content hashes, from the authored pack.
	var n int
	var sum string
	if err := f.db.QueryRow(`SELECT COUNT(*), MIN(content_sha256) FROM exam_session_items WHERE session_id = ?`, sid(out)).Scan(&n, &sum); err != nil || n != 9 || len(sum) != 64 {
		t.Fatalf("frozen items = %d %q %v", n, sum, err)
	}
	keys := map[int]bool{}
	for p := 1; p <= 9; p++ {
		keys[f.keyOf(t, sid(out), p)] = true
	}
	if len(keys) < 2 {
		t.Errorf("the authored answer is always at the same position: %v", keys)
	}
	// The same key replays the same session; another form under it conflicts.
	if status, again := f.start(t, "ce-examen-blanc-1", examKeyA); status != http.StatusOK || sid(again) != sid(out) {
		t.Errorf("replay = %d %v", status, again)
	}
	if status, _ := f.start(t, "ce-entrainement-express", examKeyA); status != http.StatusConflict {
		t.Errorf("another form under the same key = %d", status)
	}
	if status, _ := f.start(t, "ce-examen-blanc-1", ""); status != http.StatusBadRequest {
		t.Errorf("no key = %d", status)
	}
	if status, _ := f.start(t, "no-such-form", "6f1d2c3b-0000-4000-8000-0000000000a2"); status != http.StatusUnprocessableEntity {
		t.Errorf("unknown form = %d", status)
	}
}

func TestExam_AnswersResumeAndSubmissionReplaysSafely(t *testing.T) {
	f := newExamFixture(t)
	_, out := f.start(t, "ce-entrainement-express", examKeyA)
	id := sid(out)
	k1, k2 := f.keyOf(t, id, 1), f.keyOf(t, id, 2)
	wrong2 := (k2 + 1) % len(out["questions"].([]any)[1].(map[string]any)["choices"].([]any))
	if status, a := f.put(t, id, "1", itoa(int64(k1))); status != http.StatusOK || a["remaining_seconds"] != float64(90) {
		t.Fatalf("answer 1 = %d %v", status, a)
	}
	if status, _ := f.put(t, id, "2", "99"); status != http.StatusUnprocessableEntity {
		t.Errorf("out-of-range choice = %d", status)
	}
	f.clock.Add(30 * time.Second)
	// A reload (or another device) resumes from the server: answers and time.
	status, again := doJSON(t, http.MethodGet, f.srv.URL+"/exam/sessions/"+id, "")
	if status != http.StatusOK || again["remaining_seconds"] != float64(60) || len(again["answers"].([]any)) != 1 {
		t.Fatalf("resume = %d %v", status, again)
	}
	// Submit with the second answer only in the body (its PUT was lost).
	submit := `{"answers":{"1":` + itoa(int64(k1)) + `,"2":` + itoa(int64(wrong2)) + `}}`
	status, res := doJSON(t, http.MethodPost, f.srv.URL+"/exam/sessions/"+id+"/submit", submit)
	if status != http.StatusOK || res["state"] != "submitted" || res["replayed"] != false {
		t.Fatalf("submit = %d %v", status, res)
	}
	result := res["result"].(map[string]any)
	if result["correct"] != float64(1) || result["total"] != float64(3) {
		t.Fatalf("result = %v", result)
	}
	items := result["items"].([]any)
	second := items[1].(map[string]any)
	if second["correct"] != false || second["why_wrong"] == nil || second["explanation_en"] == "" || len(second["evidence"].([]any)) == 0 {
		t.Errorf("explained miss = %v", second)
	}
	src := second["source"].(map[string]any)
	if src["pack"] != domain.ReadingPackID || src["passage_id"] != "rd-annonce-ligne-b" || src["question_id"] != "rd-annonce-ligne-b:q2" || src["pack_item"] != float64(2) {
		t.Errorf("source = %v", src)
	}
	// A repeated submission (lost response) replays the same result.
	status, rep := doJSON(t, http.MethodPost, f.srv.URL+"/exam/sessions/"+id+"/submit", submit)
	if status != http.StatusOK || rep["replayed"] != true || rep["result"].(map[string]any)["correct"] != float64(1) {
		t.Errorf("repeat = %d %v", status, rep)
	}
	// Different answers after submission conflict and change nothing.
	status, conflict := doJSON(t, http.MethodPost, f.srv.URL+"/exam/sessions/"+id+"/submit", `{"answers":{"2":`+itoa(int64(k2))+`}}`)
	if status != http.StatusConflict || conflict["code"] != "already_submitted" || conflict["exam"].(map[string]any)["result"].(map[string]any)["correct"] != float64(1) {
		t.Errorf("changed resubmission = %d %v", status, conflict)
	}
	if status, closed := f.put(t, id, "3", "0"); status != http.StatusConflict || closed["code"] != "exam_submitted" {
		t.Errorf("answer after submit = %d %v", status, closed)
	}
	var subs int
	f.db.QueryRow(`SELECT COUNT(*) FROM exam_submissions`).Scan(&subs)
	if subs != 1 {
		t.Errorf("submissions = %d", subs)
	}
}

func TestExam_TheServerDeadlineClosesTheExam(t *testing.T) {
	f := newExamFixture(t)
	_, out := f.start(t, "ce-entrainement-express", examKeyA)
	id := sid(out)
	k1 := f.keyOf(t, id, 1)
	f.put(t, id, "1", itoa(int64(k1)))
	f.clock.Add(90 * time.Second) // exactly at the deadline: still open
	if status, _ := f.put(t, id, "2", "0"); status != http.StatusOK {
		t.Fatalf("answer at the deadline = %d", status)
	}
	f.clock.Add(time.Second)
	if status, late := f.put(t, id, "3", "0"); status != http.StatusConflict || late["code"] != "exam_expired" {
		t.Errorf("late answer = %d %v", status, late)
	}
	status, res := doJSON(t, http.MethodPost, f.srv.URL+"/exam/sessions/"+id+"/submit", `{"answers":{"3":0}}`)
	if status != http.StatusConflict || res["code"] != "exam_expired" {
		t.Fatalf("late submit = %d %v", status, res)
	}
	view := res["exam"].(map[string]any)
	result := view["result"].(map[string]any)
	if view["state"] != "expired" || result["closed"] != "expired" || result["total"] != float64(3) {
		t.Fatalf("expired view = %v", view)
	}
	if third := result["items"].([]any)[2].(map[string]any); third["choice"] != nil {
		t.Errorf("an answer sent after the deadline was counted: %v", third)
	}
	// Reading an expired exam writes nothing.
	var answers, subs int
	f.db.QueryRow(`SELECT COUNT(*) FROM exam_answers`).Scan(&answers)
	f.db.QueryRow(`SELECT COUNT(*) FROM exam_submissions`).Scan(&subs)
	doJSON(t, http.MethodGet, f.srv.URL+"/exam/sessions/"+id, "")
	doJSON(t, http.MethodGet, f.srv.URL+"/exam/sessions", "")
	var answers2, subs2 int
	f.db.QueryRow(`SELECT COUNT(*) FROM exam_answers`).Scan(&answers2)
	f.db.QueryRow(`SELECT COUNT(*) FROM exam_submissions`).Scan(&subs2)
	if answers != 2 || subs != 0 || answers2 != answers || subs2 != subs {
		t.Errorf("answers %d->%d submissions %d->%d", answers, answers2, subs, subs2)
	}
}

func TestExam_MissedPointSavesTheAuthoredItemAndARelatedQuestionCanBeRetried(t *testing.T) {
	f := newExamFixture(t)
	_, out := f.start(t, "ce-entrainement-express", examKeyA)
	id := sid(out)
	// A retry needs a closed exam.
	if status, _, _, _ := keyed(t, http.DefaultClient, http.MethodPost, f.srv.URL+"/exam/sessions/"+id+"/retries", "6f1d2c3b-0000-4000-8000-0000000000b1", `{"position":2}`); status != http.StatusConflict {
		t.Errorf("retry before closing = %d", status)
	}
	wrong := (f.keyOf(t, id, 2) + 1) % 2
	doJSON(t, http.MethodPost, f.srv.URL+"/exam/sessions/"+id+"/submit", `{"answers":{"2":`+itoa(int64(wrong))+`}}`)
	// Save the missed point: the authored example becomes a reading lesson (no
	// provider) and the record links its exact item.
	status, imported := doJSON(t, http.MethodPost, f.srv.URL+"/reading/examples/rd-annonce-ligne-b", "")
	if status != http.StatusCreated && status != http.StatusOK {
		t.Fatalf("import = %d %v", status, imported)
	}
	exercise := int64(imported["exercises"].([]any)[0].(map[string]any)["id"].(float64))
	doc := `{"schema_version":"learning_capture_v1","capture_id":"exam-` + id + `-2","source":"manual","original_input":"J'avais choisi la mauvaise date.","original_context":"Mock exam session #` + id + `, question 2","source_ref":{"type":"reading_item","record_id":` + itoa(exercise) + `,"item":2}}`
	if status, saved := doJSON(t, http.MethodPost, f.srv.URL+"/captures", doc); status != http.StatusCreated {
		t.Fatalf("save = %d %v", status, saved)
	}
	_, nb := doJSON(t, http.MethodGet, f.srv.URL+"/mistake-notebook/items", "")
	item := nb["items"].([]any)[0].(map[string]any)
	if item["prompt"] != out["questions"].([]any)[1].(map[string]any)["question"] || item["reference_origin"] != "authored" {
		t.Errorf("notebook item = %v", item)
	}
	// A related question: same kind, another passage, not already asked.
	key := "6f1d2c3b-0000-4000-8000-0000000000b2"
	status, retry, _, _ := keyed(t, http.DefaultClient, http.MethodPost, f.srv.URL+"/exam/sessions/"+id+"/retries", key, `{"position":2}`)
	if status != http.StatusCreated {
		t.Fatalf("retry = %d %v", status, retry)
	}
	q := retry["questions"].([]any)[0].(map[string]any)
	if retry["session"].(map[string]any)["kind"] != "retry" || q["kind"] != "detail" || q["passage_id"] == "rd-annonce-ligne-b" || retry["remaining_seconds"] != float64(120) {
		t.Errorf("related question = %v", retry)
	}
	if status, again, _, _ := keyed(t, http.DefaultClient, http.MethodPost, f.srv.URL+"/exam/sessions/"+id+"/retries", key, `{"position":2}`); status != http.StatusOK || sid(again) != sid(retry) {
		t.Errorf("retry replay = %d", status)
	}
	_, second, _, _ := keyed(t, http.DefaultClient, http.MethodPost, f.srv.URL+"/exam/sessions/"+id+"/retries", "6f1d2c3b-0000-4000-8000-0000000000b3", `{"position":2}`)
	if second["questions"].([]any)[0].(map[string]any)["question"] == q["question"] {
		t.Errorf("the second related question repeats the first")
	}
}

func TestExam_NotInThePublicDemo(t *testing.T) {
	f := newExamFixture(t)
	demo := httptest.NewServer(transporthttp.NewPublicDemoBoundary(f.routes, false))
	t.Cleanup(demo.Close)
	for _, prefix := range []string{"", "/api"} {
		for _, p := range []string{"/exam/forms", "/exam/sessions", "/exam/sessions/1"} {
			if status, _ := doJSON(t, http.MethodGet, demo.URL+prefix+p, ""); status != http.StatusNotFound {
				t.Errorf("GET %s%s in the demo: %d", prefix, p, status)
			}
		}
		if status, _, _, _ := keyed(t, http.DefaultClient, http.MethodPost, demo.URL+prefix+"/exam/sessions", examKeyA, `{"form_id":"ce-entrainement-express"}`); status != http.StatusMethodNotAllowed {
			t.Errorf("POST %s start in the demo: %d", prefix, status)
		}
	}
}
