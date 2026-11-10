package http_test

// Exam Writing v1 end to end: the real handler, SQLite repository and OpenAI
// feedback client against a local fake Responses API (listeningfake), with the
// embedded authored prompts and the authored feedback fixture.

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening/listeningfake"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
	"french-learning-app/internal/writing"
)

const writingKey = "sk-writing-integration-secret"

type writingFixture struct {
	model  *listeningfake.Responses
	srv    *httptest.Server
	db     *sql.DB
	routes http.Handler
}

func feedbackFixture(t *testing.T) string {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "..", "writing", "testdata", "invitation_feedback.json"))
	if err != nil {
		t.Fatal(err)
	}
	return string(raw)
}

func exampleDraft(t *testing.T) string {
	t.Helper()
	set, err := domain.ParseWritingPrompts(writing.ExamplePrompts())
	if err != nil {
		t.Fatal(err)
	}
	return set.Prompts[0].ExampleDraft
}

// revised is the learner's v2: the two located mistakes fixed from the hints.
func revised(t *testing.T) string {
	s := strings.Replace(exampleDraft(t), "Je suis arrivé vers 20 heures", "J'arriverai vers 20 heures", 1)
	return strings.Replace(s, "Je suis pas sûr", "Je ne suis pas sûr", 1)
}

func newWritingFixture(t *testing.T, withGenerator bool, timeout time.Duration) *writingFixture {
	t.Helper()
	if timeout == 0 {
		timeout = 2 * time.Second
	}
	f := &writingFixture{model: listeningfake.NewResponses(t, writingKey, feedbackFixture(t))}
	db, err := sqlite.Open(filepath.Join(t.TempDir(), "writing.db"))
	if err != nil {
		t.Fatal(err)
	}
	f.db = db
	var gen domain.WritingFeedbackGenerator
	if withGenerator {
		gen = writing.NewOpenAI(writingKey, "fake-model", f.model.URL(), timeout)
	}
	svc, err := application.NewWritingService(sqlite.NewWritingRepository(db), gen, writing.ExamplePrompts(), application.WithWritingDeadline(timeout+30*time.Second))
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
		transporthttp.WithWriting(svc),
	)
	f.routes = handler.Routes()
	f.srv = httptest.NewServer(f.routes)
	t.Cleanup(func() { f.srv.Close(); db.Close() })
	return f
}

func (f *writingFixture) startInvitation(t *testing.T) int64 {
	t.Helper()
	status, out := doJSON(t, http.MethodPost, f.srv.URL+"/writing/prompts/wr-invitation-anniversaire", "")
	if status != http.StatusCreated {
		t.Fatalf("start: %d %v", status, out)
	}
	return int64(path(out, "task", "id").(float64))
}

func (f *writingFixture) save(t *testing.T, task int64, text string) map[string]any {
	t.Helper()
	body, _ := json.Marshal(map[string]string{"text": text})
	status, out := doJSON(t, http.MethodPost, fmt.Sprintf("%s/writing/tasks/%d/drafts", f.srv.URL, task), string(body))
	if status != http.StatusCreated {
		t.Fatalf("save: %d %v", status, out)
	}
	return out
}

func draftID(view map[string]any, version int) int64 {
	for _, d := range view["drafts"].([]any) {
		if path(d, "version") == float64(version) {
			return int64(path(d, "id").(float64))
		}
	}
	return 0
}

func (f *writingFixture) request(t *testing.T, draft int64, key, body string) (int, map[string]any) {
	t.Helper()
	status, out, _, err := keyed(t, http.DefaultClient, http.MethodPost, fmt.Sprintf("%s/writing/drafts/%d/feedback", f.srv.URL, draft), key, body)
	if err != nil {
		t.Fatal(err)
	}
	return status, out
}

func groundings(feedback any) []string {
	out := []string{}
	for _, c := range path(feedback, "content", "corrections").([]any) {
		out = append(out, path(c, "grounding").(string))
	}
	return out
}

const (
	wkeyA = "b1111111-1111-4111-8111-111111111111"
	wkeyB = "b2222222-2222-4222-8222-222222222222"
	wkeyC = "b3333333-3333-4333-8333-333333333333"
)

func TestWriting_WholeLoopOnTheAuthoredDraft(t *testing.T) {
	f := newWritingFixture(t, true, 0)
	_, prompts := doJSON(t, http.MethodGet, f.srv.URL+"/writing/prompts", "")
	if len(prompts["prompts"].([]any)) != 3 || !strings.Contains(prompts["notice"].(string), "not official exam items") {
		t.Fatalf("prompts = %v", prompts)
	}
	task := f.startInvitation(t)
	v1view := f.save(t, task, exampleDraft(t))
	v1 := draftID(v1view, 1)
	if path(v1view["drafts"].([]any)[0], "word_count") != float64(domain.CountWritingWords(exampleDraft(t))) || f.model.Calls() != 0 {
		t.Fatalf("v1 = %v (calls %d)", v1view["drafts"], f.model.Calls())
	}
	// One explicit request for v1: grounded against v1's exact text by the server.
	status, res := f.request(t, v1, wkeyA, "")
	fb := res["feedback"]
	if status != http.StatusCreated || path(fb, "draft_id") != float64(v1) || path(res, "request", "state") != "completed" || f.model.Calls() != 1 ||
		strings.Join(groundings(fb), ",") != "located,located,ambiguous,not_found" || path(fb, "content", "task_fulfilment", "rating") != "partly_met" {
		t.Fatalf("feedback on v1: %d %v", status, res)
	}
	corr := path(fb, "content", "corrections").([]any)
	// Rune offsets in v1, also pinned in web/src/test/writingFixture.ts.
	if path(corr[0], "start") != float64(210) || path(corr[1], "start") != float64(314) || path(corr[2], "start") != nil || path(corr[3], "start") != nil {
		t.Fatalf("locations: %v", corr)
	}
	// Revise to v2: v1 stays byte-identical; the report stays on v1.
	v2view := f.save(t, task, revised(t))
	v2 := draftID(v2view, 2)
	drafts := v2view["drafts"].([]any)
	if len(drafts) != 2 || path(drafts[0], "text") != exampleDraft(t) || path(drafts[1], "text") != revised(t) {
		t.Fatalf("drafts = %v", drafts)
	}
	reports := v2view["feedback"].([]any)
	if len(reports) != 1 || path(reports[0], "draft_id") != float64(v1) || f.model.Calls() != 1 {
		t.Fatalf("feedback after v2 = %v", reports)
	}
	// Feedback for v2 is its own report; v1's located quotes are not in v2.
	status, res = f.request(t, v2, wkeyB, "")
	if status != http.StatusCreated || path(res, "feedback", "draft_id") != float64(v2) || groundings(res["feedback"])[0] != "not_found" || groundings(res["feedback"])[1] != "not_found" {
		t.Fatalf("feedback on v2: %d %v", status, res)
	}
	// Capturing one mistake through the existing path.
	doc, _ := json.Marshal(map[string]string{"schema_version": "learning_capture_v1", "capture_id": fmt.Sprintf("writing-%d-%d-1-test", task, v1), "source": "manual",
		"original_input":   "« Je suis arrivé vers 20 heures » → « J'arriverai vers 20 heures »",
		"original_context": fmt.Sprintf("Writing task #%d: Répondre à une invitation\nDraft version 1", task)})
	status, receipt := doJSON(t, http.MethodPost, f.srv.URL+"/captures", string(doc))
	if status != http.StatusCreated || countRows(t, f.db, "knowledge_concepts") != 0 || countRows(t, f.db, "entry_analyses") != 0 {
		t.Fatalf("capture: %d %v", status, receipt)
	}
	// Saving the same text again is refused; nothing is overwritten.
	body, _ := json.Marshal(map[string]string{"text": revised(t)})
	if status, out := doJSON(t, http.MethodPost, fmt.Sprintf("%s/writing/tasks/%d/drafts", f.srv.URL, task), string(body)); status != http.StatusConflict || out["code"] != "unchanged" {
		t.Fatalf("unchanged: %d %v", status, out)
	}
	if status, again := doJSON(t, http.MethodPost, f.srv.URL+"/writing/prompts/wr-invitation-anniversaire", ""); status != http.StatusOK || path(again, "task", "id") != float64(task) {
		t.Fatalf("starting the prompt again: %d", status)
	}
}

func TestWriting_FailedAndUnknownRequestsNeverLoseAVersion(t *testing.T) {
	f := newWritingFixture(t, true, 300*time.Millisecond)
	task := f.startInvitation(t)
	v1 := draftID(f.save(t, task, exampleDraft(t)), 1)
	f.model.Set(listeningfake.ModeStatus, http.StatusInternalServerError, 0)
	status, res := f.request(t, v1, "", "")
	if status != http.StatusBadGateway || path(res, "feedback", "status") != "failed" || path(res, "request", "state") != "failed" {
		t.Fatalf("500: %d %v", status, res)
	}
	f.model.Set(listeningfake.ModeDrop, 0, 0)
	status, res = f.request(t, v1, wkeyA, "")
	if status != http.StatusBadGateway || path(res, "request", "state") != "unknown" || !strings.Contains(res["error"].(string), "outcome is unknown") {
		t.Fatalf("dropped: %d %v", status, res)
	}
	f.model.Set(listeningfake.ModeOK, 0, 0)
	if status, res = f.request(t, v1, wkeyB, ""); status != http.StatusConflict || res["code"] != "outcome_unknown" || f.model.Calls() != 2 {
		t.Fatalf("unacknowledged: %d %v", status, res)
	}
	// A new version is new input: it is not blocked by v1's unknown request.
	v2 := draftID(f.save(t, task, revised(t)), 2)
	if status, _ := f.request(t, v2, "", ""); status != http.StatusCreated || f.model.Calls() != 3 {
		t.Fatalf("v2 request: %d", status)
	}
	if status, res = f.request(t, v1, wkeyB, `{"confirm_unknown_retry":true}`); status != http.StatusCreated || path(res, "request", "after_unknown") != true || f.model.Calls() != 4 {
		t.Fatalf("acknowledged: %d %v", status, res)
	}
	// A lost response: the client gives up, the call finishes and is found by key.
	f.model.Set(listeningfake.ModeHang, 0, 150*time.Millisecond)
	impatient := &http.Client{Timeout: 50 * time.Millisecond}
	if _, _, _, err := keyed(t, impatient, http.MethodPost, fmt.Sprintf("%s/writing/drafts/%d/feedback", f.srv.URL, v2), wkeyC, ""); err == nil {
		t.Fatal("expected the client to give up")
	}
	var state any
	for i := 0; i < 50 && state != "completed"; i++ {
		_, got := doJSON(t, http.MethodGet, f.srv.URL+"/writing/feedback-requests/"+wkeyC, "")
		state = path(got, "request", "state")
		time.Sleep(20 * time.Millisecond)
	}
	status, _, hdr, _ := keyed(t, http.DefaultClient, http.MethodPost, fmt.Sprintf("%s/writing/drafts/%d/feedback", f.srv.URL, v2), wkeyC, "")
	if state != "completed" || status != http.StatusOK || hdr.Get("Idempotency-Replayed") != "true" || f.model.Calls() != 5 {
		t.Fatalf("lost response: %v, resend %d (calls %d)", state, status, f.model.Calls())
	}
	// Both versions are intact after every failure.
	_, view := doJSON(t, http.MethodGet, fmt.Sprintf("%s/writing/tasks/%d", f.srv.URL, task), "")
	ds := view["drafts"].([]any)
	if len(ds) != 2 || path(ds[0], "text") != exampleDraft(t) || path(ds[1], "text") != revised(t) {
		t.Fatalf("drafts after failures = %v", ds)
	}
}

func TestWriting_ModelCannotClaimGroundingAndMissingQuotesAreNeverLocated(t *testing.T) {
	f := newWritingFixture(t, true, 0)
	task := f.startInvitation(t)
	v1 := draftID(f.save(t, task, exampleDraft(t)), 1)
	f.model.SetOutput(strings.Replace(feedbackFixture(t), `"category": "grammar",`, `"category": "grammar", "grounding": "located",`, 1))
	if status, res := f.request(t, v1, "", ""); status != http.StatusBadGateway || path(res, "feedback", "failure_code") != "invalid_output" {
		t.Fatalf("claimed grounding: %d %v", status, res)
	}
	// Every quote invented: the report is stored, but nothing is located.
	var fb map[string]any
	_ = json.Unmarshal([]byte(feedbackFixture(t)), &fb)
	for i, c := range fb["corrections"].([]any) {
		c.(map[string]any)["quote"] = fmt.Sprintf("phrase inventée numéro %d", i)
	}
	raw, _ := json.Marshal(fb)
	f.model.SetOutput(string(raw))
	status, res := f.request(t, v1, "", "")
	if status != http.StatusCreated || strings.Join(groundings(res["feedback"]), ",") != "not_found,not_found,not_found,not_found" {
		t.Fatalf("invented quotes: %d %v", status, res)
	}
}

func TestWriting_DraftingWorksWithoutAProviderAndIsNotInTheDemo(t *testing.T) {
	f := newWritingFixture(t, false, 0)
	body, _ := json.Marshal(map[string]any{"title": "Mon message", "prompt": "Écrivez à votre voisin pour lui demander un service.", "requirements": []string{"Saluez-le."}, "word_min": 30, "word_max": 60})
	status, task := doJSON(t, http.MethodPost, f.srv.URL+"/writing/tasks", string(body))
	if status != http.StatusCreated || path(task, "task", "origin") != "learner" || path(task, "generation", "enabled") != false {
		t.Fatalf("own task: %d %v", status, task)
	}
	id := int64(path(task, "task", "id").(float64))
	v1 := draftID(f.save(t, id, "Bonjour Monsieur Dupont, pourriez-vous arroser mes plantes ?"), 1)
	f.save(t, id, "Bonjour Monsieur Dupont,\n\npourriez-vous arroser mes plantes samedi ?")
	if status, _ := f.request(t, v1, "", ""); status != http.StatusServiceUnavailable || countRows(t, f.db, "writing_feedback_requests") != 0 {
		t.Fatalf("disabled feedback: %d", status)
	}
	for name, b := range map[string]string{
		"inverted range": `{"title":"t","prompt":"p","word_min":80,"word_max":20}`,
		"no prompt":      `{"title":"t","prompt":" "}`,
	} {
		if status, _ := doJSON(t, http.MethodPost, f.srv.URL+"/writing/tasks", b); status != http.StatusUnprocessableEntity {
			t.Errorf("%s: %d", name, status)
		}
	}
	if status, _ := doJSON(t, http.MethodPost, fmt.Sprintf("%s/writing/tasks/%d/drafts", f.srv.URL, id), `{"text":"  "}`); status != http.StatusUnprocessableEntity {
		t.Errorf("empty draft: %d", status)
	}
	demo := httptest.NewServer(transporthttp.NewPublicDemoBoundary(f.routes, false))
	t.Cleanup(demo.Close)
	for _, prefix := range []string{"", "/api"} {
		for _, p := range []string{"/writing/prompts", "/writing/tasks", "/writing/tasks/1", "/writing/feedback-requests/" + wkeyA} {
			if status, _ := doJSON(t, http.MethodGet, demo.URL+prefix+p, ""); status != http.StatusNotFound {
				t.Errorf("GET %s%s in the demo: %d", prefix, p, status)
			}
		}
		for _, p := range []string{"/writing/tasks", "/writing/tasks/1/drafts", "/writing/drafts/1/feedback", "/writing/prompts/wr-invitation-anniversaire"} {
			if status, _ := doJSON(t, http.MethodPost, demo.URL+prefix+p, "{}"); status != http.StatusMethodNotAllowed {
				t.Errorf("POST %s%s in the demo: %d", prefix, p, status)
			}
		}
	}
}
