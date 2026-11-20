package http_test

// Review Today end to end over the real handler and repositories: Speaking
// steps of started, incomplete exercises and Mistake Notebook items marked for
// retry, in one stable order; saved history stays out of the queue; a
// completed action leaves it on the next read; never in the public demo.

import (
	"database/sql"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/speaking"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
	"french-learning-app/internal/writing"
)

func buildReviewTodayServer(t *testing.T) (*httptest.Server, http.Handler, *sql.DB) {
	t.Helper()
	db, err := sqlite.Open(filepath.Join(t.TempDir(), "today.db"))
	if err != nil {
		t.Fatal(err)
	}
	entryRepo := sqlite.NewEntryRepository(db)
	analysisRepo := sqlite.NewAnalysisRepository(db)
	feedbackRepo := sqlite.NewFeedbackRepository(db)
	knowledgeRepo := sqlite.NewKnowledgeRepository(db)
	conceptRepo := sqlite.NewConceptRepository(db)
	lrepo := sqlite.NewListeningRepository(db)
	srepo := sqlite.NewSpeakingRepository(db)
	annotation := application.NewEffectiveAnnotationService(conceptRepo, conceptRepo)
	library := application.NewKnowledgeLibraryService(conceptRepo, knowledgeRepo, entryRepo, analysisRepo, feedbackRepo, annotation)
	resolver := application.NewMistakeSourceResolver(lrepo, sqlite.NewReadingRepository(db), sqlite.NewWritingRepository(db), srepo)
	spk, err := application.NewSpeakingService(srepo, nil, nil, speaking.ExamplePrompts())
	if err != nil {
		t.Fatal(err)
	}
	wrepo := sqlite.NewWritingRepository(db)
	wrt, err := application.NewWritingService(wrepo, nil, writing.ExamplePrompts())
	if err != nil {
		t.Fatal(err)
	}
	nrepo := sqlite.NewNotebookRepository(db)
	handler := transporthttp.NewHandler(
		application.NewEntryService(entryRepo), application.NewAnalysisService(entryRepo, analysisRepo, nil),
		application.NewFeedbackService(feedbackRepo), application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo),
		application.NewInventoryService(sqlite.NewInventoryRepository(db)),
		application.NewCaptureService(sqlite.NewCaptureRepository(db), application.WithSourceResolver(resolver)),
		application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, sqlite.NewAdmissionRepository(db), nil),
		application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo), annotation,
		application.NewConceptAnnotationDatasetService(annotation, knowledgeRepo, conceptRepo),
		transporthttp.WithListening(application.NewListeningService(lrepo, nil, application.WithListeningScripts(embeddedScripts(t)))),
		transporthttp.WithMistakeNotebook(application.NewMistakeNotebookService(nrepo, resolver, entryRepo, library)),
		transporthttp.WithSpeaking(spk),
		transporthttp.WithWriting(wrt),
		transporthttp.WithLearningWeek(application.NewLearningWeekService(srepo, wrepo, nrepo)),
		transporthttp.WithHistoryExport(application.NewHistoryExportService(srepo, wrepo, nrepo, entryRepo, lrepo)),
	)
	routes := handler.Routes()
	srv := httptest.NewServer(routes)
	t.Cleanup(func() { srv.Close(); db.Close() })
	return srv, routes, db
}

func reviewToday(t *testing.T, srv *httptest.Server) map[string]any {
	t.Helper()
	status, out := doJSON(t, http.MethodGet, srv.URL+"/review-today", "")
	if status != http.StatusOK || out["schema_version"] != application.ReviewTodayVersion {
		t.Fatalf("review today: %d %v", status, out)
	}
	return out
}

func todayKeys(out map[string]any) []string {
	keys := []string{}
	for _, it := range out["items"].([]any) {
		keys = append(keys, fmt.Sprintf("%v=%v", path(it, "key"), path(it, "reason")))
	}
	return keys
}

func TestReviewToday_MergesDueItemsKeepsHistoryOutAndDropsCompletedActions(t *testing.T) {
	srv, _, _ := buildReviewTodayServer(t)
	// Nothing yet: no item, no history.
	out := reviewToday(t, srv)
	if len(out["items"].([]any)) != 0 || path(out, "history", "notebook_items") != 0.0 || path(out, "history", "speaking_takes") != 0.0 {
		t.Fatalf("empty: %v", out)
	}
	// Workbook: an authored listening script, two saved mistakes, one marked for retry.
	status, lesson, _ := postScript(t, srv, "ls-wb1-u05")
	if status != http.StatusCreated {
		t.Fatalf("import: %d", status)
	}
	ex := lesson["current_exercise_id"].(float64)
	for capture, item := range map[string]int{"today-l01": 1, "today-l02": 2} {
		if status, body := saveMistake(t, srv, capture, ex, item, "Parce qu'il est moins cher"); status != http.StatusCreated {
			t.Fatalf("save %s: %d %v", capture, status, body)
		}
	}
	marked := notebookItem(t, srv, "today-l01")["entry_id"].(float64)
	if status, body := doJSON(t, http.MethodPut, fmt.Sprintf("%s/mistake-notebook/items/%d/retry", srv.URL, int64(marked)), `{"marked": true}`); status != http.StatusOK {
		t.Fatalf("mark: %d %v", status, body)
	}
	// Speaking: one started exercise with a typed take waiting for feedback
	// (feedback is off here), one prompt started with no take, one not started.
	_, started := doJSON(t, http.MethodPost, srv.URL+"/speaking/prompts/sp-invitation-reponse", "")
	spk := int64(path(started, "exercise", "id").(float64))
	_, saved := doJSON(t, http.MethodPost, fmt.Sprintf("%s/speaking/exercises/%d/takes", srv.URL, spk), `{"audio_source":"none"}`)
	take := int64(saved["take_id"].(float64))
	if status, body := doJSON(t, http.MethodPost, fmt.Sprintf("%s/speaking/takes/%d/transcripts", srv.URL, take), `{"text":"Salut Léa, merci pour ton invitation. À samedi !"}`); status != http.StatusCreated {
		t.Fatalf("transcript: %d %v", status, body)
	}
	time.Sleep(5 * time.Millisecond) // a later start, so the order below is not a tie
	_, second := doJSON(t, http.MethodPost, srv.URL+"/speaking/prompts/sp-demande-renseignements", "")
	spk2 := int64(path(second, "exercise", "id").(float64))

	out = reviewToday(t, srv)
	want := []string{
		fmt.Sprintf("speaking:exercise:%d=%s", spk, domain.SpeakingQueueReviewWithoutFeedback),
		fmt.Sprintf("notebook:entry:%d=%s", int64(marked), application.ReviewRetryMarked),
		fmt.Sprintf("speaking:exercise:%d=%s", spk2, domain.SpeakingQueueFirstTake),
	}
	if got := todayKeys(out); fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("queue:\n got %v\nwant %v", got, want)
	}
	items := out["items"].([]any)
	if path(items[0], "speaking", "take_id") != float64(take) || path(items[0], "notebook") != nil ||
		path(items[1], "notebook", "entry_id") != marked || path(items[1], "notebook", "retry", "marked") != true ||
		path(items[1], "notebook", "source_status") != "resolved" || path(items[1], "speaking") != nil {
		t.Fatalf("item payloads: %v", items)
	}
	// History stays out of the queue but is counted for its link.
	if path(out, "history", "notebook_items") != 2.0 || path(out, "history", "speaking_exercises") != 2.0 || path(out, "history", "speaking_takes") != 1.0 {
		t.Fatalf("history: %v", out["history"])
	}
	// Completing the notebook action (removing the mark) drops it on the next read.
	if status, _ := doJSON(t, http.MethodPut, fmt.Sprintf("%s/mistake-notebook/items/%d/retry", srv.URL, int64(marked)), `{"marked": false}`); status != http.StatusOK {
		t.Fatalf("unmark: %d", status)
	}
	if got := todayKeys(reviewToday(t, srv)); len(got) != 2 || got[0] != want[0] || got[1] != want[2] {
		t.Fatalf("after completing the retry: %v", got)
	}
	if path(reviewToday(t, srv), "history", "notebook_items") != 2.0 {
		t.Fatal("the completed item left the history")
	}
}

func TestReviewToday_NeverInThePublicDemo(t *testing.T) {
	_, handler, _ := buildReviewTodayServer(t)
	demo := httptest.NewServer(transporthttp.NewPublicDemoBoundary(handler, false))
	t.Cleanup(demo.Close)
	// Review Today and the revision studio routes are private: the boundary
	// answers before any handler runs (GET 404; POST is not an allowed method).
	for _, prefix := range []string{"", "/api"} {
		for _, path := range []string{"/review-today", "/learning-week", "/learning-history/export", "/learning-history/export-preview", "/listening/materials/1/revisions", "/listening/materials/1/revision-compare?from=1&to=2", "/listening/materials/1/restore?revision=1"} {
			if status, _ := doJSON(t, http.MethodGet, demo.URL+prefix+path, ""); status != http.StatusNotFound {
				t.Fatalf("demo GET %s%s: %d", prefix, path, status)
			}
		}
		for _, path := range []string{"/listening/materials/1/restore", "/learning-history/import-preview"} {
			if status, _ := doJSON(t, http.MethodPost, demo.URL+prefix+path, `{}`); status != http.StatusNotFound && status != http.StatusMethodNotAllowed {
				t.Fatalf("demo POST %s%s: %d", prefix, path, status)
			}
		}
	}
}

// The learning week counts stored work once per item and day, in the
// learner's zone, and Review Today names the same local day for the same zone.
func TestLearningWeek_CountsStoredWorkOnceInTheLearnersZone(t *testing.T) {
	srv, _, _ := buildReviewTodayServer(t)
	week := func(zone string) map[string]any {
		t.Helper()
		status, out := doJSON(t, http.MethodGet, srv.URL+"/learning-week?zone="+zone, "")
		if status != http.StatusOK || out["schema_version"] != application.LearningWeekVersion {
			t.Fatalf("learning week: %d %v", status, out)
		}
		return out
	}
	if w := week("Asia/Shanghai"); path(w, "totals", "production") != 0.0 || w["sparse"] != true || w["production_share"] != nil || len(w["days"].([]any)) != 7 {
		t.Fatalf("empty week: %v", w)
	}
	// Speaking: a typed take, then the learner's own correction.
	_, started := doJSON(t, http.MethodPost, srv.URL+"/speaking/prompts/sp-invitation-reponse", "")
	spk := int64(path(started, "exercise", "id").(float64))
	_, saved := doJSON(t, http.MethodPost, fmt.Sprintf("%s/speaking/exercises/%d/takes", srv.URL, spk), `{"audio_source":"none"}`)
	take := int64(saved["take_id"].(float64))
	for _, text := range []string{"Salut Léa, merci pour ton invitation. À samedi !", "Salut Léa, merci pour ton invitation ! À samedi, je viendrai."} {
		if status, body := doJSON(t, http.MethodPost, fmt.Sprintf("%s/speaking/takes/%d/transcripts", srv.URL, take), fmt.Sprintf(`{"text":%q}`, text)); status != http.StatusCreated {
			t.Fatalf("transcript: %d %v", status, body)
		}
	}
	// A second take with no confirmed transcript is not completed production.
	if status, body := doJSON(t, http.MethodPost, fmt.Sprintf("%s/speaking/exercises/%d/takes", srv.URL, spk), `{"audio_source":"none"}`); status != http.StatusCreated && status != http.StatusOK {
		t.Fatalf("second typed take: %d %v", status, body)
	}
	// Writing: a learner task, a first draft and a revision.
	status, task := doJSON(t, http.MethodPost, srv.URL+"/writing/tasks", `{"title":"Lettre à Éloïse","prompt":"Écrivez à votre amie.","requirements":[],"word_min":5,"word_max":80}`)
	if status != http.StatusCreated {
		t.Fatalf("task: %d %v", status, task)
	}
	taskID := int64(path(task, "task", "id").(float64))
	for _, text := range []string{"Chère Éloïse, je suis contente de te voir bientôt.", "Chère Éloïse, je suis très contente de te revoir bientôt !"} {
		if status, body := doJSON(t, http.MethodPost, fmt.Sprintf("%s/writing/tasks/%d/drafts", srv.URL, taskID), fmt.Sprintf(`{"text":%q}`, text)); status != http.StatusCreated {
			t.Fatalf("draft: %d %v", status, body)
		}
	}
	// Notebook: a saved mistake, marked and then done for today (twice: the second changes nothing).
	_, lesson, _ := postScript(t, srv, "ls-wb1-u05")
	if status, body := saveMistake(t, srv, "week-l01", lesson["current_exercise_id"].(float64), 1, ""); status != http.StatusCreated {
		t.Fatalf("save: %d %v", status, body)
	}
	entry := int64(notebookItem(t, srv, "week-l01")["entry_id"].(float64))
	for _, marked := range []string{"true", "false", "false"} {
		doJSON(t, http.MethodPut, fmt.Sprintf("%s/mistake-notebook/items/%d/retry", srv.URL, entry), `{"marked":`+marked+`}`)
	}

	w := week("Asia/Shanghai")
	totals := w["totals"].(map[string]any)
	if totals["production"] != 2.0 || totals["own_corrections"] != 2.0 || totals["reviewed"] != 2.0 || totals["provider_feedback"] != 0.0 ||
		totals["distinct_exercises"] != 2.0 || totals["active_days"] != 1.0 {
		t.Fatalf("totals: %v", totals)
	}
	corrections := w["corrections"].([]any)
	if len(corrections) != 2 {
		t.Fatalf("corrections: %v", corrections)
	}
	bySkill := map[string]map[string]any{}
	for _, c := range corrections {
		bySkill[path(c, "skill").(string)] = c.(map[string]any)
	}
	if sp := bySkill["speaking"]; sp == nil || sp["exercise_id"] != float64(spk) || sp["take_id"] != float64(take) || sp["version"] != 2.0 || sp["prior_version"] != 1.0 {
		t.Fatalf("speaking correction: %v", bySkill["speaking"])
	}
	if wr := bySkill["writing"]; wr == nil || wr["task_id"] != float64(taskID) || wr["version"] != 2.0 || wr["title"] != "Lettre à Éloïse" {
		t.Fatalf("writing correction: %v", bySkill["writing"])
	}
	last := w["days"].([]any)[6].(map[string]any)
	if w["to"] != last["day"] || last["production"] != 2.0 {
		t.Fatalf("today's row: %v", last)
	}
	// Review Today in the same zone names the same local day.
	doJSON(t, http.MethodPut, fmt.Sprintf("%s/mistake-notebook/items/%d/retry", srv.URL, entry), `{"marked":true}`)
	status, rt := doJSON(t, http.MethodGet, srv.URL+"/review-today?zone=Asia/Shanghai", "")
	if status != http.StatusOK || rt["zone"] != "Asia/Shanghai" || rt["today"] != w["to"] {
		t.Fatalf("review today zone: %d %v", status, rt)
	}
	for _, it := range rt["items"].([]any) {
		if path(it, "source") == "notebook" && path(it, "since_day") != w["to"] {
			t.Fatalf("since_day: %v", it)
		}
	}
	// Unknown zones are refused, never guessed.
	for _, u := range []string{"/learning-week?zone=Mars/Olympus", "/review-today?zone=Local"} {
		if status, _ := doJSON(t, http.MethodGet, srv.URL+u, ""); status != http.StatusBadRequest {
			t.Fatalf("%s: %d", u, status)
		}
	}
}
