package http_test

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/storage/sqlite"
	transporthttp "french-learning-app/internal/transport/http"
)

// Revisions of an imported authored script (ARCHITECTURE.md §4.3). Every case
// runs on its own disposable database with fixture packs built from the
// embedded one; nothing calls a provider.

// buildRevisionServer serves listening with the given pack, plus captures with
// the Mistake Notebook source resolver and the notebook itself, so a saved
// mistake goes through the real source_ref validation.
func buildRevisionServer(t *testing.T, dbPath string, pack domain.ListeningScriptPack) (*httptest.Server, *sql.DB) {
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
	lrepo := sqlite.NewListeningRepository(db)
	annotation := application.NewEffectiveAnnotationService(conceptRepo, conceptRepo)
	library := application.NewKnowledgeLibraryService(conceptRepo, knowledgeRepo, entryRepo, analysisRepo, feedbackRepo, annotation)
	resolver := application.NewMistakeSourceResolver(lrepo, sqlite.NewReadingRepository(db), sqlite.NewWritingRepository(db), sqlite.NewSpeakingRepository(db))
	handler := transporthttp.NewHandler(
		application.NewEntryService(entryRepo), application.NewAnalysisService(entryRepo, analysisRepo, nil),
		application.NewFeedbackService(feedbackRepo), application.NewEffectiveAnalysisService(analysisRepo, feedbackRepo),
		application.NewInventoryService(sqlite.NewInventoryRepository(db)),
		application.NewCaptureService(sqlite.NewCaptureRepository(db), application.WithSourceResolver(resolver)),
		application.NewKnowledgeService(entryRepo, analysisRepo, feedbackRepo, knowledgeRepo, sqlite.NewAdmissionRepository(db), nil),
		application.NewConceptService(knowledgeRepo, conceptRepo, conceptRepo), annotation,
		application.NewConceptAnnotationDatasetService(annotation, knowledgeRepo, conceptRepo),
		transporthttp.WithListening(application.NewListeningService(lrepo, nil, application.WithListeningScripts(pack))),
		transporthttp.WithMistakeNotebook(application.NewMistakeNotebookService(sqlite.NewNotebookRepository(db), resolver, entryRepo, library)),
	)
	srv := httptest.NewServer(handler.Routes())
	t.Cleanup(func() { srv.Close(); db.Close() })
	return srv, db
}

const u05 = 4 // index of ls-wb1-u05 in the embedded pack

// earlierU05 is the embedded pack as it was before a correction: u05-l04's
// explanation relied on the brochure's class time, u05-l02 had other
// wording, and one line that no question cites read differently.
func earlierU05(t *testing.T) (domain.ListeningScriptPack, string) {
	t.Helper()
	pack := embeddedScripts(t)
	sc := &pack.Scripts[u05]
	if sc.ID != "ls-wb1-u05" || sc.Questions[3].ID != "u05-l04" || sc.Questions[1].ID != "u05-l02" {
		t.Fatalf("pack order changed: %s %s", sc.ID, sc.Questions[3].ID)
	}
	q := &sc.Questions[3]
	q.RationaleEN, q.RationaleZH = "Work ends before the 18:30 class.", "她在18点30分上课前就下班了。"
	q.Evidence, q.Segments = []domain.ListeningEvidence{{Segment: 5, Excerpt: "Je finis le travail à 17 h 30"}}, []int{5}
	sc.Questions[1].Question += " (ancienne formulation)"
	line := uncitedLine(t, *sc)
	sc.Lines[line].Text += " Voilà."
	if err := domain.ValidateListeningScript(sc); err != nil {
		t.Fatalf("earlier fixture is invalid: %v", err)
	}
	return pack, sc.Lines[line].ID
}

// uncitedLine is the index of a line that no question or note cites.
func uncitedLine(t *testing.T, sc domain.ListeningScript) int {
	t.Helper()
	cited := map[int]bool{}
	for _, q := range sc.Questions {
		for _, s := range q.Segments {
			cited[s] = true
		}
	}
	for _, a := range sc.Annotations {
		cited[a.Segment] = true
	}
	for i := range sc.Lines {
		if !cited[i+1] {
			return i
		}
	}
	t.Fatalf("every line of %s is cited", sc.ID)
	return 0
}

func materialOf(t *testing.T, lesson map[string]any) string {
	t.Helper()
	return itoa(int64(path(lesson, "material", "id").(float64)))
}

func currentItem(t *testing.T, lesson map[string]any, n int) map[string]any {
	t.Helper()
	current := lesson["current_exercise_id"]
	for _, e := range lesson["exercises"].([]any) {
		ex := e.(map[string]any)
		if ex["id"] == current {
			return ex["content"].(map[string]any)["items"].([]any)[n-1].(map[string]any)
		}
	}
	t.Fatalf("current exercise %v not in the lesson", current)
	return nil
}

func saveMistake(t *testing.T, srv *httptest.Server, captureID string, exerciseID float64, item int, attempt string) (int, map[string]any) {
	t.Helper()
	doc := map[string]any{"schema_version": "learning_capture_v1", "capture_id": captureID, "source": "manual",
		"original_input": "Je n'ai pas compris la question " + itoa(int64(item)), "original_context": "Listening exercise: authored script (no audio or video)",
		"source_ref": map[string]any{"type": domain.SourceListeningItem, "record_id": int64(exerciseID), "item": item, "attempt": attempt}}
	raw, _ := json.Marshal(doc)
	return doJSON(t, http.MethodPost, srv.URL+"/captures", string(raw))
}

func notebookItem(t *testing.T, srv *httptest.Server, captureID string) map[string]any {
	t.Helper()
	status, body := doJSON(t, http.MethodGet, srv.URL+"/mistake-notebook/items", "")
	if status != http.StatusOK {
		t.Fatalf("notebook: %d %v", status, body)
	}
	for _, it := range body["items"].([]any) {
		if row := it.(map[string]any); row["capture_id"] == captureID {
			return row
		}
	}
	t.Fatalf("notebook has no %s: %v", captureID, body)
	return nil
}

func confirmBody(from any, fingerprint any) string {
	raw, _ := json.Marshal(map[string]any{"from_revision": from, "pack_fingerprint": fingerprint})
	return string(raw)
}

func postUpdate(t *testing.T, srv *httptest.Server, id, body string) (int, map[string]any, string) {
	t.Helper()
	req, _ := http.NewRequest(http.MethodPost, srv.URL+"/listening/materials/"+id+"/script-update", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return resp.StatusCode, out, resp.Header.Get("Idempotency-Replayed")
}

// An unchanged pack: import replays, the preview lists nothing, a
// confirmation replays, and nothing is written.
func TestListeningScriptRevisions_UnchangedImportReplaysAndOffersNoUpdate(t *testing.T) {
	pack := embeddedScripts(t)
	srv, db := buildRevisionServer(t, filepath.Join(t.TempDir(), "rev.db"), pack)
	status, lesson, _ := postScript(t, srv, "ls-wb1-u05")
	if status != http.StatusCreated {
		t.Fatalf("import: %d", status)
	}
	id := materialOf(t, lesson)
	if st := lesson["script_revision"].(map[string]any); st["revision"] != 1.0 || st["pack_status"] != domain.ListeningScriptUpToDate ||
		st["fingerprint"] != st["pack_fingerprint"] || st["script_id"] != "ls-wb1-u05" {
		t.Fatalf("script_revision after import: %v", st)
	}
	before := listeningCounts(t, db)
	if status, _, replayed := postScript(t, srv, "ls-wb1-u05"); status != http.StatusOK || replayed != "true" {
		t.Fatalf("unchanged re-import: %d %q", status, replayed)
	}
	status, preview := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/script-update", "")
	changes := preview["changes"].(map[string]any)
	if status != http.StatusOK || preview["pack_status"] != domain.ListeningScriptUpToDate || preview["next_revision"] != nil ||
		len(changes["lines"].([]any)) != 0 || len(changes["questions"].([]any)) != 0 || changes["annotations_changed"] != false {
		t.Fatalf("preview of an unchanged script: %d %v", status, preview)
	}
	status, body, replayed := postUpdate(t, srv, id, confirmBody(1, preview["pack_fingerprint"]))
	if status != http.StatusOK || replayed != "true" || body["revision"] != 1.0 || body["replayed"] != true {
		t.Fatalf("confirming an unchanged script: %d %q %v", status, replayed, body)
	}
	if after := listeningCounts(t, db); after != before {
		t.Fatalf("an unchanged script wrote rows: %s -> %s", before, after)
	}
	_, list := doJSON(t, http.MethodGet, srv.URL+"/listening/scripts", "")
	for _, s := range list["scripts"].([]any) {
		row := s.(map[string]any)
		switch row["id"] {
		case "ls-wb1-u05":
			if row["imported_revision"] != 1.0 || row["pack_status"] != domain.ListeningScriptUpToDate {
				t.Fatalf("imported row: %v", row)
			}
		default:
			if row["imported_revision"] != nil || row["pack_status"] != nil {
				t.Fatalf("not imported row: %v", row)
			}
		}
	}
}

// The whole contract on one database: a lesson imported before a pack
// correction, with saved mistakes, opened by a server with the corrected
// pack. Nothing changes until the learner confirms the preview; the update
// appends revision 2; a lost response resent replays; old mistakes keep
// resolving to revision 1's words; a new mistake saves against revision 2.
func TestListeningScriptRevisions_CorrectedPackExplicitUpdateEndToEnd(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "rev.db")
	earlier, changedLine := earlierU05(t)
	current := embeddedScripts(t)

	old, db := buildRevisionServer(t, dbPath, earlier)
	status, lesson, _ := postScript(t, old, "ls-wb1-u05")
	if status != http.StatusCreated {
		t.Fatalf("earlier import: %d", status)
	}
	id := materialOf(t, lesson)
	oldExercise := lesson["current_exercise_id"].(float64)
	if status, body := saveMistake(t, old, "rev-old-l04", oldExercise, 4, "Parce qu'il est moins cher"); status != http.StatusCreated {
		t.Fatalf("save on revision 1: %d %v", status, body)
	}
	if status, body := saveMistake(t, old, "rev-old-l02", oldExercise, 2, ""); status != http.StatusCreated {
		t.Fatalf("save on revision 1: %d %v", status, body)
	}
	savedOld := notebookItem(t, old, "rev-old-l04")
	old.Close()

	srv, _ := buildRevisionServer(t, dbPath, current)
	before := listeningCounts(t, db)
	// Reads: the lesson is unchanged and says an update is available.
	_, lesson = doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id, "")
	st := lesson["script_revision"].(map[string]any)
	if lesson["current_exercise_id"] != oldExercise || st["revision"] != 1.0 || st["pack_status"] != domain.ListeningScriptUpdateAvailable ||
		currentItem(t, lesson, 4)["rationale_en"] != "Work ends before the 18:30 class." {
		t.Fatalf("lesson before the update: current %v state %v item 4 %v", lesson["current_exercise_id"], st, currentItem(t, lesson, 4))
	}
	_, list := doJSON(t, http.MethodGet, srv.URL+"/listening/scripts", "")
	for _, s := range list["scripts"].([]any) {
		if row := s.(map[string]any); row["id"] == "ls-wb1-u05" && (row["imported_revision"] != 1.0 || row["pack_status"] != domain.ListeningScriptUpdateAvailable) {
			t.Fatalf("listing before the update: %v", row)
		}
	}
	// A re-import is still 409 and names the lesson.
	status, conflict, _ := postScript(t, srv, "ls-wb1-u05")
	if status != http.StatusConflict || conflict["code"] != "script_conflict" || itoa(int64(conflict["material_id"].(float64))) != id ||
		conflict["current_revision"] != 1.0 || conflict["pack_status"] != domain.ListeningScriptUpdateAvailable {
		t.Fatalf("re-import before the update: %d %v", status, conflict)
	}
	// The preview reads only and lists exactly what differs.
	status, preview := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/script-update", "")
	if status != http.StatusOK || preview["pack_status"] != domain.ListeningScriptUpdateAvailable || preview["current_revision"] != 1.0 ||
		preview["next_revision"] != 2.0 || preview["script_id"] != "ls-wb1-u05" {
		t.Fatalf("preview: %d %v", status, preview)
	}
	changes := preview["changes"].(map[string]any)
	lines := changes["lines"].([]any)
	if len(lines) != 1 || path(lines[0], "line") != changedLine || path(lines[0], "change") != "changed" ||
		!strings.HasSuffix(path(lines[0], "before", "text").(string), " Voilà.") || strings.HasSuffix(path(lines[0], "after", "text").(string), " Voilà.") {
		t.Fatalf("line changes: %v", lines)
	}
	questions := map[string][]string{}
	for _, q := range changes["questions"].([]any) {
		var fields []string
		for _, f := range path(q, "fields").([]any) {
			fields = append(fields, f.(string))
		}
		questions[path(q, "item_id").(string)] = fields
	}
	if len(questions) != 2 || !slices.Equal(questions["u05-l02"], []string{"question"}) ||
		!slices.Contains(questions["u05-l04"], "rationale") || !slices.Contains(questions["u05-l04"], "evidence") {
		t.Fatalf("question changes: %v", questions)
	}
	if after := listeningCounts(t, db); after != before {
		t.Fatalf("reads or a refused import wrote rows: %s -> %s", before, after)
	}

	// The explicit update appends revision 2.
	body := confirmBody(1, preview["pack_fingerprint"])
	status, updated, replayed := postUpdate(t, srv, id, body)
	if status != http.StatusCreated || replayed != "" || updated["revision"] != 2.0 || updated["replayed"] != false {
		t.Fatalf("update: %d %q %v", status, replayed, updated)
	}
	lesson = updated["lesson"].(map[string]any)
	newExercise := lesson["current_exercise_id"].(float64)
	if newExercise == oldExercise || path(lesson, "transcript", "version") != 2.0 ||
		path(lesson, "script_revision", "pack_status") != domain.ListeningScriptUpToDate ||
		currentItem(t, lesson, 4)["rationale_en"] != current.Scripts[u05].Questions[3].RationaleEN {
		t.Fatalf("lesson after the update: current %v transcript %v state %v", newExercise, path(lesson, "transcript", "version"), lesson["script_revision"])
	}
	afterUpdate := listeningCounts(t, db)
	if want := strings.NewReplacer("listening_transcripts=1", "listening_transcripts=2", "listening_exercises=1", "listening_exercises=2").Replace(before); afterUpdate != want {
		t.Fatalf("the update wrote other rows: %s -> %s", before, afterUpdate)
	}

	// Lost response: the same confirmation again replays revision 2.
	status, again, replayed := postUpdate(t, srv, id, body)
	if status != http.StatusOK || replayed != "true" || again["revision"] != 2.0 || path(again, "lesson", "current_exercise_id") != newExercise {
		t.Fatalf("resent confirmation: %d %q %v", status, replayed, again)
	}
	if status, _, replayed := postScript(t, srv, "ls-wb1-u05"); status != http.StatusOK || replayed != "true" {
		t.Fatalf("re-import after the update: %d %q", status, replayed)
	}
	if now := listeningCounts(t, db); now != afterUpdate {
		t.Fatalf("a replay wrote rows: %s -> %s", afterUpdate, now)
	}

	// Old mistakes: the same words, linked to revision 1, flagged as having a newer one.
	oldItem := notebookItem(t, srv, "rev-old-l04")
	if oldItem["explanation_en"] != savedOld["explanation_en"] || oldItem["prompt"] != savedOld["prompt"] || oldItem["reference"] != savedOld["reference"] ||
		path(oldItem, "link", "listening_exercise_id") != oldExercise || path(oldItem, "link", "listening_transcript_version") != 1.0 ||
		oldItem["latest_version"] != 2.0 || oldItem["source_status"] != "resolved" || path(oldItem, "source", "attempt") != "Parce qu'il est moins cher" {
		t.Fatalf("old mistake after the update: %v (saved %v)", oldItem, savedOld)
	}
	if path(notebookItem(t, srv, "rev-old-l02"), "prompt") != earlier.Scripts[u05].Questions[1].Question {
		t.Fatal("the old u05-l02 mistake lost its earlier wording")
	}
	// Revision 1 still reads in full: its lines and its exercise.
	status, rev1 := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/revisions/1", "")
	segments := path(rev1, "transcript", "segments").([]any)
	if status != http.StatusOK || rev1["revision"] != 1.0 || rev1["current_revision"] != 2.0 || path(rev1, "exercise", "id") != oldExercise ||
		!strings.HasSuffix(path(segments[uncitedLine(t, earlier.Scripts[u05])], "text").(string), " Voilà.") ||
		path(rev1, "exercise", "content", "items").([]any)[3].(map[string]any)["rationale_en"] != "Work ends before the 18:30 class." {
		t.Fatalf("revision 1: %d %v", status, rev1)
	}
	// A new mistake saves against revision 2; the same question on revision 1 is still the old record.
	if status, body := saveMistake(t, srv, "rev-new-l04", newExercise, 4, ""); status != http.StatusCreated {
		t.Fatalf("save on revision 2: %d %v", status, body)
	}
	newItem := notebookItem(t, srv, "rev-new-l04")
	if newItem["explanation_en"] != current.Scripts[u05].Questions[3].RationaleEN || path(newItem, "link", "listening_transcript_version") != 2.0 ||
		newItem["latest_version"] != nil {
		t.Fatalf("new mistake: %v", newItem)
	}
	if status, body := saveMistake(t, srv, "rev-old-l04-again", oldExercise, 4, ""); status != http.StatusConflict || body["code"] != "source_already_saved" {
		t.Fatalf("saving revision 1's item again: %d %v", status, body)
	}
}

// A preview that no longer describes the update is refused with a fresh one:
// (a) the server's pack changed after the preview; (b) the lesson moved to
// another revision (here: updated under one pack, then confirmed under
// another). Nothing is written.
func TestListeningScriptRevisions_StalePreviewIsRefusedWithAFreshOne(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "rev.db")
	earlier, _ := earlierU05(t)
	p2 := embeddedScripts(t)
	p3 := embeddedScripts(t)
	p3.Scripts[u05].Questions[0].RationaleEN += " (second correction)"

	first, db := buildRevisionServer(t, dbPath, earlier)
	_, lesson, _ := postScript(t, first, "ls-wb1-u05")
	id := materialOf(t, lesson)
	first.Close()

	b, _ := buildRevisionServer(t, dbPath, p2)
	_, previewP2 := doJSON(t, http.MethodGet, b.URL+"/listening/materials/"+id+"/script-update", "")
	b.Close()

	// (a) the pack changed between the preview and the confirmation.
	c, _ := buildRevisionServer(t, dbPath, p3)
	before := listeningCounts(t, db)
	status, body, _ := postUpdate(t, c, id, confirmBody(1, previewP2["pack_fingerprint"]))
	fresh, _ := body["preview"].(map[string]any)
	if status != http.StatusConflict || body["code"] != "stale_preview" || fresh == nil || fresh["current_revision"] != 1.0 ||
		fresh["pack_fingerprint"] == previewP2["pack_fingerprint"] || fresh["pack_status"] != domain.ListeningScriptUpdateAvailable {
		t.Fatalf("confirmation under a changed pack: %d %v", status, body)
	}
	if after := listeningCounts(t, db); after != before {
		t.Fatalf("a stale confirmation wrote rows: %s -> %s", before, after)
	}
	// Confirming the fresh preview works.
	if status, body, _ := postUpdate(t, c, id, confirmBody(1, fresh["pack_fingerprint"])); status != http.StatusCreated || body["revision"] != 2.0 {
		t.Fatalf("confirming the fresh preview: %d %v", status, body)
	}
	c.Close()

	// (b) back under pack 2: the old confirmation names revision 1, but the
	// lesson is at revision 2 with other content.
	d, _ := buildRevisionServer(t, dbPath, p2)
	before = listeningCounts(t, db)
	status, body, _ = postUpdate(t, d, id, confirmBody(1, previewP2["pack_fingerprint"]))
	fresh, _ = body["preview"].(map[string]any)
	if status != http.StatusConflict || body["code"] != "stale_preview" || fresh == nil || fresh["current_revision"] != 2.0 ||
		fresh["pack_fingerprint"] != previewP2["pack_fingerprint"] {
		t.Fatalf("confirmation of a superseded revision: %d %v", status, body)
	}
	if after := listeningCounts(t, db); after != before {
		t.Fatalf("a stale confirmation wrote rows: %s -> %s", before, after)
	}
}

// Many confirmations of the same preview at once append one revision: one
// 201, every other 200 with the same revision.
func TestListeningScriptRevisions_ConcurrentConfirmationsAppendOnce(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "rev.db")
	earlier, _ := earlierU05(t)
	first, db := buildRevisionServer(t, dbPath, earlier)
	_, lesson, _ := postScript(t, first, "ls-wb1-u05")
	id := materialOf(t, lesson)
	first.Close()
	srv, _ := buildRevisionServer(t, dbPath, embeddedScripts(t))
	_, preview := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/script-update", "")
	body := confirmBody(1, preview["pack_fingerprint"])

	const n = 8
	statuses := make([]int, n)
	revisions := make([]any, n)
	var wg sync.WaitGroup
	for i := range n {
		wg.Add(1)
		go func() {
			defer wg.Done()
			req, _ := http.NewRequest(http.MethodPost, srv.URL+"/listening/materials/"+id+"/script-update", strings.NewReader(body))
			req.Header.Set("Content-Type", "application/json")
			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				return
			}
			defer resp.Body.Close()
			var out map[string]any
			_ = json.NewDecoder(resp.Body).Decode(&out)
			statuses[i], revisions[i] = resp.StatusCode, out["revision"]
		}()
	}
	wg.Wait()
	created := 0
	for i := range n {
		switch {
		case statuses[i] == http.StatusCreated:
			created++
		case statuses[i] != http.StatusOK:
			t.Fatalf("confirmation %d: %d", i, statuses[i])
		}
		if revisions[i] != 2.0 {
			t.Fatalf("confirmation %d saw revision %v", i, revisions[i])
		}
	}
	if created != 1 || countRows(t, db, "listening_transcripts") != 2 || countRows(t, db, "listening_exercises") != 2 {
		t.Fatalf("concurrent confirmations: %d created, %s", created, listeningCounts(t, db))
	}
}

// Refusals write nothing, and YouTube lessons have no revisions: their reads,
// transcripts and exercises are unchanged.
func TestListeningScriptRevisions_RefusalsAndYouTubeUnaffected(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "rev.db")
	pack := embeddedScripts(t)
	srv, db := buildRevisionServer(t, dbPath, pack)
	_, lesson, _ := postScript(t, srv, "ls-wb1-u05")
	id := materialOf(t, lesson)
	yt := itoa(createLesson(t, srv, authoredTranscript(t)))
	_, ytLesson := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+yt, "")
	if _, ok := ytLesson["script_revision"]; !ok || ytLesson["script_revision"] != nil {
		t.Fatalf("youtube lesson script_revision = %v", ytLesson["script_revision"])
	}
	_, preview := doJSON(t, http.MethodGet, srv.URL+"/listening/materials/"+id+"/script-update", "")
	fp := preview["pack_fingerprint"]
	before := listeningCounts(t, db)
	for _, c := range []struct {
		name, method, url, body string
		status                  int
		code                    string
	}{
		{"youtube preview", http.MethodGet, "/listening/materials/" + yt + "/script-update", "", http.StatusConflict, "not_authored_script"},
		{"youtube update", http.MethodPost, "/listening/materials/" + yt + "/script-update", confirmBody(1, fp), http.StatusConflict, "not_authored_script"},
		{"youtube revision", http.MethodGet, "/listening/materials/" + yt + "/revisions/1", "", http.StatusConflict, "not_authored_script"},
		{"unknown lesson preview", http.MethodGet, "/listening/materials/999/script-update", "", http.StatusNotFound, ""},
		{"unknown lesson update", http.MethodPost, "/listening/materials/999/script-update", confirmBody(1, fp), http.StatusNotFound, ""},
		{"revision 0", http.MethodPost, "/listening/materials/" + id + "/script-update", confirmBody(0, fp), http.StatusUnprocessableEntity, ""},
		{"bad fingerprint", http.MethodPost, "/listening/materials/" + id + "/script-update", confirmBody(1, "abc"), http.StatusUnprocessableEntity, ""},
		{"unknown field", http.MethodPost, "/listening/materials/" + id + "/script-update", `{"from_revision":1,"pack_fingerprint":"x","force":true}`, http.StatusBadRequest, ""},
		{"no body", http.MethodPost, "/listening/materials/" + id + "/script-update", "", http.StatusBadRequest, ""},
		{"unknown revision", http.MethodGet, "/listening/materials/" + id + "/revisions/9", "", http.StatusNotFound, ""},
		{"invalid revision", http.MethodGet, "/listening/materials/" + id + "/revisions/0", "", http.StatusBadRequest, ""},
	} {
		status, body := doJSON(t, c.method, srv.URL+c.url, c.body)
		if status != c.status || (c.code != "" && body["code"] != c.code) {
			t.Fatalf("%s: %d %v", c.name, status, body)
		}
	}
	if after := listeningCounts(t, db); after != before {
		t.Fatalf("refusals wrote rows: %s -> %s", before, after)
	}
	// YouTube is unchanged: a new transcript version still shows, no script fields.
	status, body := doJSON(t, http.MethodPost, srv.URL+"/listening/materials/"+yt+"/transcripts", `{"transcript":"Une deuxième version."}`)
	if status != http.StatusCreated || path(body, "transcript", "version") != 2.0 || body["script_revision"] != nil {
		t.Fatalf("youtube transcript: %d %v", status, body)
	}

	// A pack that renamed the script: the preview says so, the update is refused.
	renamed := embeddedScripts(t)
	renamed.Scripts[u05].Title = "Inscription à la Maison des langues"
	renamed.Scripts[u05].Questions[0].RationaleEN += " (corrected)"
	r, _ := buildRevisionServer(t, dbPath, renamed)
	status, preview = doJSON(t, http.MethodGet, r.URL+"/listening/materials/"+id+"/script-update", "")
	if status != http.StatusOK || preview["pack_status"] != domain.ListeningScriptTitleChanged || preview["next_revision"] != nil {
		t.Fatalf("renamed preview: %d %v", status, preview)
	}
	before = listeningCounts(t, db)
	if status, body, _ := postUpdate(t, r, id, confirmBody(1, preview["pack_fingerprint"])); status != http.StatusConflict || body["code"] != "script_title_changed" {
		t.Fatalf("renamed update: %d %v", status, body)
	}
	// A pack without the script: the lesson still opens and says so.
	without := embeddedScripts(t)
	without.Scripts = slices.Delete(without.Scripts, u05, u05+1)
	w, _ := buildRevisionServer(t, dbPath, without)
	_, gone := doJSON(t, http.MethodGet, w.URL+"/listening/materials/"+id, "")
	if path(gone, "script_revision", "pack_status") != domain.ListeningScriptNotInPack || path(gone, "script_revision", "pack_fingerprint") != nil {
		t.Fatalf("lesson whose script left the pack: %v", gone["script_revision"])
	}
	if status, body := doJSON(t, http.MethodGet, w.URL+"/listening/materials/"+id+"/script-update", ""); status != http.StatusConflict || body["code"] != "script_not_in_pack" {
		t.Fatalf("preview without the script: %d %v", status, body)
	}
	if after := listeningCounts(t, db); after != before {
		t.Fatalf("refusals wrote rows: %s -> %s", before, after)
	}
}

// The public demo never reaches the revision routes, at the root or under /api.
func TestListeningScriptRevisions_UnavailableInThePublicDemo(t *testing.T) {
	_, _, handler := buildListeningServer(t, filepath.Join(t.TempDir(), "demo.db"), nil, application.WithListeningScripts(embeddedScripts(t)))
	demo := httptest.NewServer(transporthttp.NewPublicDemoBoundary(handler.Routes(), false))
	t.Cleanup(demo.Close)
	for _, prefix := range []string{"", "/api"} {
		for _, c := range []struct{ method, path string }{
			{http.MethodGet, "/listening/materials/1/script-update"},
			{http.MethodGet, "/listening/materials/1/revisions/1"},
		} {
			if status, _ := doJSON(t, c.method, demo.URL+prefix+c.path, ""); status != http.StatusNotFound {
				t.Fatalf("demo %s %s%s: %d", c.method, prefix, c.path, status)
			}
		}
		if status, _ := doJSON(t, http.MethodPost, demo.URL+prefix+"/listening/materials/1/script-update", confirmBody(1, "x")); status != http.StatusMethodNotAllowed {
			t.Fatalf("demo POST %s: %d", prefix, status)
		}
	}
}
